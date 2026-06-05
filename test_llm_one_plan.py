# -*- coding: utf-8 -*-
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
sys.path.insert(0, '.')

import time
from backend.data import direction_api
direction_api._amap_key_invalid = True

from backend.data.loader import get_cached_pois
from backend.models.schemas import PlanRequest, RouteConstraints, Location
from backend.core.preference import parse_preference_from_request
from backend.core.hybrid_filter import HybridPOIFilter
from backend.core import route_engine
from backend.core.semantic_matcher import semantic_matcher

pois = get_cached_pois('杭州')
print(f'[初始化] 杭州POI数量: {len(pois)}')
t0 = time.time()
for p in pois:
    semantic_matcher.get_poi_embedding(p)
print(f'[初始化] Embedding预计算耗时: {time.time()-t0:.2f}s')

# 测试：美食为主的query，带LLM
print('\n' + '='*60)
print('测试: 美食之旅（带LLM raw_query）')
print('raw_query: 去杭州主要就是吃，美食之旅')

user_pref = parse_preference_from_request(['美食'], '朋友', '适中', 500)
hf = HybridPOIFilter()
req = PlanRequest(raw_query='去杭州主要就是吃，美食之旅', city='杭州', start_time='09:00', end_time='18:00',
                  budget=500, travelers='朋友', preferences=['美食'], pace='适中')
cons = RouteConstraints(city='杭州', start_time='09:00', end_time='18:00',
                        start_point=Location(lat=30.2596, lng=120.1460), budget=500, transport_mode='步行')

candidates, _, _ = hf.filter(pois, req, user_pref, cons)
print(f'候选池: {len(candidates)} 个POI')

# 只测均衡推荐策略
t0 = time.time()
seg = route_engine.preference_guided_greedy(
    candidates, user_pref, cons, strategy='balanced', raw_query='去杭州主要就是吃，美食之旅'
)
t1 = time.time()
print(f'均衡推荐规划耗时: {t1-t0:.2f}s')

cats = {}
for s in seg:
    cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
names = ' → '.join([s.poi.name for s in seg])
print(f'路线: {names}')
print(f'类别分布: {cats}')

# 对比：不带LLM
print('\n[对比：不带LLM]')
t0 = time.time()
seg2 = route_engine.preference_guided_greedy(
    candidates, user_pref, cons, strategy='balanced', raw_query=None
)
t1 = time.time()
print(f'均衡推荐规划耗时: {t1-t0:.2f}s')

cats2 = {}
for s in seg2:
    cats2[s.poi.category] = cats2.get(s.poi.category, 0) + 1
names2 = ' → '.join([s.poi.name for s in seg2])
print(f'路线: {names2}')
print(f'类别分布: {cats2}')

print('\n' + '='*60)
print('单策略规划测试完成')
print('='*60)
