# -*- coding: utf-8 -*-
"""
完整LLM效果测评脚本
输出：输入偏好 + 具体路线 + LLM 5维度评分
"""
import time, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

from backend.models.schemas import PlanRequest, RouteConstraints, Location, UserPreference
from backend.data.loader import get_cached_pois, get_city_center
from backend.core.preference import parse_preference_from_request
from backend.core.llm_parser import parse_preference_from_llm
from backend.core.policy_generator import generate_planning_policy, DEFAULT_POLICY
from backend.core.personalization import UserPersonalizationEngine
from backend.core.evaluator import evaluate_plan_with_llm
from backend.core import route_engine

print("=" * 70)
print("智能旅行规划系统 -- LLM效果测评")
print("=" * 70)

# ===== 1. 定义测试用例 =====
request = PlanRequest(
    raw_query='周末带女朋友去杭州玩，喜欢拍照和吃辣，不想排队',
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    budget=500,
    travelers='情侣',
    preferences=['拍照', '美食'],
    pace='适中',
    transport_mode='步行'
)

candidates = get_cached_pois('杭州')
center = get_city_center('杭州')
constraints = RouteConstraints(
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    start_point=Location(lat=center['lat'], lng=center['lng']) if center else None,
    budget=500,
    transport_mode='步行'
)

print(f"\n【用户输入】")
print(f"  Query: {request.raw_query}")
print(f"  城市: {request.city}")
print(f"  时间: {request.start_time} ~ {request.end_time}")
print(f"  预算: {request.budget}元")
print(f"  人群: {request.travelers}")
print(f"  偏好标签: {request.preferences}")
print(f"  节奏: {request.pace}")
print(f"  候选POI总数: {len(candidates)}")

# ===== 2. A组：仅规则 =====
print(f"\n{'='*70}")
print(f"【A组】仅规则解析（无LLM，无画像）")
print(f"{'='*70}")
start = time.time()
rule_pref = parse_preference_from_request(
    preferences=request.preferences, travelers=request.travelers,
    pace=request.pace, budget=request.budget
)
t_a = (time.time() - start) * 1000
print(f"  解析偏好: {rule_pref.theme_weights}")
print(f"  规划耗时: {t_a:.1f}ms")

start = time.time()
plans_a = route_engine.generate_preference_variants(candidates, rule_pref, constraints)
t_plan_a = (time.time() - start) * 1000
print(f"  路线规划耗时: {t_plan_a:.1f}ms")
for i, p in enumerate(plans_a):
    names = ' -> '.join([s.poi.name for s in p.segments])
    print(f"\n  [{p.theme}] {names}")
    print(f"    总时间: {p.total_time} | 总费用: RMB{p.total_cost} | POI数: {p.poi_count}")
    for s in p.segments:
        print(f"      - {s.poi.name} ({s.poi.category}) [{s.arrive_time}-{s.leave_time}] RMB{s.poi.price or 0}")

# ===== 3. B组：+LLM解析 =====
print(f"\n{'='*70}")
print(f"【B组】+LLM意图解析")
print(f"{'='*70}")
start = time.time()
llm_pref = parse_preference_from_llm(
    raw_query=request.raw_query,
    preferences=request.preferences,
    travelers=request.travelers,
    pace=request.pace,
    budget=request.budget,
    must_visit=[],
    avoid=[],
    transport_mode='步行'
)
t_b = (time.time() - start) * 1000
print(f"  LLM解析耗时: {t_b:.1f}ms")

if llm_pref:
    print(f"  LLM解析偏好: {json.dumps(llm_pref.theme_weights, ensure_ascii=False)}")
    print(f"  人群: {llm_pref.traveler_type} | 节奏: {llm_pref.pace_preference} | 预算: {llm_pref.budget_level}")
    
    start = time.time()
    plans_b = route_engine.generate_preference_variants(candidates, llm_pref, constraints)
    t_plan_b = (time.time() - start) * 1000
    print(f"  路线规划耗时: {t_plan_b:.1f}ms")
    for i, p in enumerate(plans_b):
        names = ' -> '.join([s.poi.name for s in p.segments])
        print(f"\n  [{p.theme}] {names}")
        print(f"    总时间: {p.total_time} | 总费用: RMB{p.total_cost} | POI数: {p.poi_count}")
        for s in p.segments:
            print(f"      - {s.poi.name} ({s.poi.category}) [{s.arrive_time}-{s.leave_time}] RMB{s.poi.price or 0}")
else:
    print("  [WARN] LLM解析失败")
    plans_b = plans_a

# ===== 4. C组：+画像融合 =====
print(f"\n{'='*70}")
print(f"【C组】+画像融合")
print(f"{'='*70}")
engine = UserPersonalizationEngine()
mock_profile = UserPreference(
    theme_weights={'拍照': 0.9, '美食': 0.85, '文化': 0.4, '自然': 0.5, '购物': 0.3, '娱乐': 0.4},
    traveler_type='情侣',
    pace_preference='悠闲',
    budget_level='标准',
    price_sensitivity=0.4,
    willingness_to_queue=0.3,
    willingness_to_walk=0.6
)
print(f"  模拟历史画像: {mock_profile.theme_weights}")

pref_for_c = llm_pref if llm_pref else rule_pref
fused = engine.fuse_preferences(pref_for_c, mock_profile)
print(f"  融合后偏好: {json.dumps(fused.theme_weights, ensure_ascii=False)}")

start = time.time()
plans_c = route_engine.generate_preference_variants(candidates, fused, constraints)
t_plan_c = (time.time() - start) * 1000
print(f"  路线规划耗时: {t_plan_c:.1f}ms")
for i, p in enumerate(plans_c):
    names = ' -> '.join([s.poi.name for s in p.segments])
    print(f"\n  [{p.theme}] {names}")
    print(f"    总时间: {p.total_time} | 总费用: RMB{p.total_cost} | POI数: {p.poi_count}")
    for s in p.segments:
        print(f"      - {s.poi.name} ({s.poi.category}) [{s.arrive_time}-{s.leave_time}] RMB{s.poi.price or 0}")

# ===== 5. D组：+Policy Generator =====
print(f"\n{'='*70}")
print(f"【D组】完整系统（+Policy Generator）")
print(f"{'='*70}")
# 清除可能污染的缓存
route_engine._dedup_cache.clear()
generate_planning_policy.__globals__['_policy_cache'].clear()
start = time.time()
policy = generate_planning_policy(
    raw_query=request.raw_query,
    user_pref=fused,
    candidates=candidates,
    constraints=constraints,
    timeout=60
)
t_policy = (time.time() - start) * 1000
print(f"  Policy生成耗时: {t_policy:.1f}ms")
print(f"  Policy理由: {policy.reasoning}")
print(f"  是否命中缓存: {t_policy < 100}")
if policy.theme_keyword_map:
    print(f"  自由维度映射: {json.dumps(policy.theme_keyword_map, ensure_ascii=False, indent=2)}")

start = time.time()
plans_d = route_engine.generate_preference_variants(candidates, fused, constraints, policy=policy)
t_plan_d = (time.time() - start) * 1000
print(f"  路线规划耗时: {t_plan_d:.1f}ms")
for i, p in enumerate(plans_d):
    names = ' -> '.join([s.poi.name for s in p.segments])
    print(f"\n  [{p.theme}] {names}")
    print(f"    总时间: {p.total_time} | 总费用: RMB{p.total_cost} | POI数: {p.poi_count}")
    for s in p.segments:
        print(f"      - {s.poi.name} ({s.poi.category}) [{s.arrive_time}-{s.leave_time}] RMB{s.poi.price or 0}")

# ===== 6. LLM自动评分（5维度） =====
print(f"\n{'='*70}")
print(f"【LLM自动评价者】5维度评分")
print(f"{'='*70}")

all_plans = [
    ('A_仅规则', plans_a[0] if plans_a else None, rule_pref),
    ('B_LLM解析', plans_b[0] if plans_b else None, llm_pref or rule_pref),
    ('C_画像融合', plans_c[0] if plans_c else None, fused),
    ('D_完整系统', plans_d[0] if plans_d else None, fused),
]

for name, plan, pref in all_plans:
    if not plan:
        continue
    print(f"\n  --- {name} ---")
    score = evaluate_plan_with_llm(
        request=request,
        user_pref=pref,
        plan=plan,
        candidates=candidates,
        timeout=60
    )
    print(f"    综合评分: {score.overall_score}/10")
    print(f"    偏好对齐: {score.preference_alignment}/10 -- {score.preference_alignment_reason}")
    print(f"    路线合理: {score.route_rationality}/10 -- {score.route_rationality_reason}")
    print(f"    POI多样性: {score.poi_diversity}/10 -- {score.poi_diversity_reason}")
    print(f"    预算控制: {score.budget_control}/10 -- {score.budget_control_reason}")
    print(f"    时间可行: {score.time_feasibility}/10 -- {score.time_feasibility_reason}")
    print(f"    总结: {score.summary}")

print(f"\n{'='*70}")
print("测评完成")
print(f"{'='*70}")
