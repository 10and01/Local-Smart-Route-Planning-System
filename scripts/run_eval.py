# -*- coding: utf-8 -*-
"""LLM效果测评脚本"""
import time, json, sys
from backend.models.schemas import PlanRequest, RouteConstraints, Location, UserPreference
from backend.data.loader import get_cached_pois, get_city_center
from backend.core.preference import parse_preference_from_request
from backend.core.llm_parser import parse_preference_from_llm
from backend.core.personalization import UserPersonalizationEngine
from backend.core.policy_generator import generate_planning_policy, DEFAULT_POLICY
from backend.core.llm_reranker import rerank_and_fuse
from backend.core import route_engine

QUERIES = [
    {
        'raw_query': '周末带女朋友去杭州玩，喜欢拍照和吃辣，不想排队',
        'travelers': '情侣', 'preferences': ['拍照', '美食'], 'budget': 500, 'pace': '适中'
    },
    {
        'raw_query': '带小孩去杭州，想爬山和看博物馆',
        'travelers': '亲子', 'preferences': ['自然', '文化'], 'budget': 300, 'pace': '适中'
    },
]

MOCK_PROFILE = UserPreference(
    theme_weights={'拍照': 0.9, '美食': 0.85, '文化': 0.4, '自然': 0.5, '购物': 0.3, '娱乐': 0.4},
    traveler_type='情侣', pace_preference='悠闲', budget_level='标准',
    price_sensitivity=0.4, willingness_to_queue=0.3, willingness_to_walk=0.6
)

def run_ablation(query_def):
    city = '杭州'
    request = PlanRequest(
        raw_query=query_def['raw_query'], city=city,
        start_time='09:00', end_time='18:00',
        budget=query_def.get('budget', 500),
        travelers=query_def['travelers'],
        preferences=query_def.get('preferences', []),
        pace=query_def.get('pace', '适中'),
        transport_mode='步行'
    )
    candidates = get_cached_pois(city)
    center = get_city_center(city)
    constraints = RouteConstraints(
        city=city, start_time='09:00', end_time='18:00',
        start_point=Location(lat=center['lat'], lng=center['lng']),
        budget=request.budget, transport_mode='步行'
    )

    results = {'query': query_def['raw_query'], 'groups': {}}

    # A: 规则解析
    start = time.time()
    rule_pref = parse_preference_from_request(
        preferences=request.preferences, travelers=request.travelers,
        pace=request.pace, budget=request.budget
    )
    plans_a = route_engine.generate_preference_variants(candidates, rule_pref, constraints)
    t_a = (time.time() - start) * 1000
    results['groups']['A'] = {
        'name': 'A_仅规则', 'time_ms': round(t_a, 1),
        'plans': [{'theme': p.theme, 'pois': [s.poi.name for s in p.segments], 'cost': p.total_cost, 'time': p.total_time} for p in plans_a]
    }

    # B: LLM解析
    start = time.time()
    llm_pref = parse_preference_from_llm(
        raw_query=request.raw_query, preferences=request.preferences,
        travelers=request.travelers, pace=request.pace, budget=request.budget,
        must_visit=[], avoid=[], transport_mode='步行'
    )
    t_b = (time.time() - start) * 1000
    if llm_pref:
        results['groups']['B'] = {
            'name': 'B_+LLM解析', 'time_ms': round(t_b, 1),
            'theme_weights': llm_pref.theme_weights,
            'traveler_type': llm_pref.traveler_type,
            'budget_level': llm_pref.budget_level,
        }
        plans_b = route_engine.generate_preference_variants(candidates, llm_pref, constraints)
        results['groups']['B']['plans'] = [{'theme': p.theme, 'pois': [s.poi.name for s in p.segments], 'cost': p.total_cost, 'time': p.total_time} for p in plans_b]
    else:
        results['groups']['B'] = {'name': 'B_+LLM解析', 'time_ms': round(t_b, 1), 'error': 'LLM解析失败或超时'}

    # C: 画像融合
    engine = UserPersonalizationEngine()
    pref_for_c = llm_pref if llm_pref else rule_pref
    fused = engine.fuse_preferences(pref_for_c, MOCK_PROFILE)
    start = time.time()
    plans_c = route_engine.generate_preference_variants(candidates, fused, constraints)
    t_c = (time.time() - start) * 1000
    results['groups']['C'] = {
        'name': 'C_+画像融合', 'time_ms': round(t_c, 1),
        'plans': [{'theme': p.theme, 'pois': [s.poi.name for s in p.segments], 'cost': p.total_cost, 'time': p.total_time} for p in plans_c]
    }

    # D: +Policy Generator
    start = time.time()
    policy = generate_planning_policy(
        raw_query=request.raw_query, user_pref=fused,
        candidates=candidates, constraints=constraints, timeout=25
    )
    t_policy = (time.time() - start) * 1000
    results['groups']['D'] = {
        'name': 'D_完整系统(+Policy)', 'policy_time_ms': round(t_policy, 1),
        'policy_reasoning': policy.reasoning if policy else 'default',
        'policy_cached': t_policy < 100,
    }
    start = time.time()
    plans_d = route_engine.generate_preference_variants(candidates, fused, constraints, policy=policy)
    t_d = (time.time() - start) * 1000
    results['groups']['D']['time_ms'] = round(t_d, 1)
    results['groups']['D']['plans'] = [{'theme': p.theme, 'pois': [s.poi.name for s in p.segments], 'cost': p.total_cost, 'time': p.total_time} for p in plans_d]

    # E: +LLM Reranker (Top-20)
    start = time.time()
    sorted_candidates = sorted(candidates, key=lambda p: p.pre_score, reverse=True)
    candidate_pool = sorted_candidates[:40]
    top20 = candidate_pool[:20]

    from backend.core.route_engine import haversine_distance_m
    start_loc = constraints.start_point or Location(lat=30.2596, lng=120.1460)
    distances_m = {}
    for p in top20:
        if p.location:
            distances_m[p.poi_id] = int(haversine_distance_m(start_loc.lat, start_loc.lng, p.location.lat, p.location.lng))
    max_pre = max((p.pre_score for p in top20), default=1.0)
    min_pre = min((p.pre_score for p in top20), default=0.0)
    pre_range = max_pre - min_pre if max_pre > min_pre else 1.0
    rule_scores = {p.name: (p.pre_score - min_pre) / pre_range * 100 for p in top20}
    rerank_results = rerank_and_fuse(
        pois=top20, rule_scores=rule_scores, user_pref=fused,
        raw_query=request.raw_query, distances_m=distances_m, rule_weight=0.6, llm_weight=0.4
    )
    t_rerank = (time.time() - start) * 1000
    results['groups']['E'] = {
        'name': 'E_+LLM精排', 'rerank_time_ms': round(t_rerank, 1),
        'rerank_count': len(rerank_results),
        'top5': sorted(rerank_results.values(), key=lambda x: x.final_score, reverse=True)[:5]
    }

    return results

if __name__ == '__main__':
    all_results = []
    for q in QUERIES:
        print(f"[Eval] Running: {q['raw_query']}", file=sys.stderr)
        r = run_ablation(q)
        all_results.append(r)
        print(f"[Eval] Done: {r['groups']['D']['policy_reasoning']}", file=sys.stderr)

    with open('eval_report_full.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=lambda o: o.dict() if hasattr(o, 'dict') else str(o))
    print('DONE')
