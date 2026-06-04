# -*- coding: utf-8 -*-
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
import sys
sys.path.insert(0, '.')
from backend.data import direction_api
direction_api._amap_key_invalid = True

from backend.data.loader import get_cached_pois
from backend.models.schemas import PlanRequest, UserPreference, RouteConstraints, Location
from backend.core.preference import parse_preference_from_request
from backend.core.hybrid_filter import HybridPOIFilter
from backend.core import route_engine
from backend.core.semantic_matcher import semantic_matcher

semantic_matcher.clear_cache()
pois = get_cached_pois('杭州')
for p in pois:
    semantic_matcher.get_poi_embedding(p)

def run_test(name, preferences, travelers, pace, budget):
    print(f'\n===== {name} =====')
    user_pref = parse_preference_from_request(preferences, travelers, pace, budget)
    print(f'关键词: {dict(sorted(user_pref.theme_weights.items(), key=lambda x: -x[1])[:3])}')
    
    hf = HybridPOIFilter()
    req = PlanRequest(raw_query='', city='杭州', start_time='09:00', end_time='18:00',
                      budget=budget, travelers=travelers, preferences=preferences, pace=pace)
    cons = RouteConstraints(city='杭州', start_time='09:00', end_time='18:00',
                            start_point=Location(lat=30.2596, lng=120.1460), budget=budget, transport_mode='步行')
    
    candidates, _, _ = hf.filter(pois, req, user_pref, cons)
    print(f'候选池Top-5: {[(p.name, round(p.pre_score, 3)) for p in candidates[:5]]}')
    
    plans = route_engine.generate_preference_variants(candidates, user_pref, cons)
    for p in plans:
        cats = {}
        for s in p.segments:
            cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
        names = ' → '.join([s.poi.name for s in p.segments])
        print(f'  [{p.theme}] {p.poi_count}POIs ¥{p.total_cost} | 类别分布: {cats}')
        print(f'    路线: {names}')

run_test('情侣拍照美食', ['拍照','美食'], '情侣', '适中', 500)
run_test('亲子游乐园', ['娱乐','自然'], '亲子', '悠闲', 800)
run_test('独自安静文化', ['文化'], '独自', '悠闲', 300)
run_test('预算敏感学生', ['拍照','美食'], '朋友', '紧凑', 200)
print('\n===== 验证完成 =====')
