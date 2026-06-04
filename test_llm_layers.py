# -*- coding: utf-8 -*-
"""测试第三层（动态抓取）和第四层（LLM骨架规划）的LLM调用"""
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
from backend.services.planner import RoutePlannerService

semantic_matcher.clear_cache()
pois = get_cached_pois('杭州')
for p in pois:
    semantic_matcher.get_poi_embedding(p)

print("=" * 60)
print("测试1: 第四层 LLM骨架规划（带raw_query）")
print("=" * 60)

planner = RoutePlannerService()
req = PlanRequest(
    raw_query='杭州情侣拍照和美食，想去西湖和灵隐寺',
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    budget=500,
    travelers='情侣',
    preferences=['拍照', '美食'],
    pace='适中'
)
try:
    resp = planner.plan(req)
    print(f"\n规划成功！request_id={resp.request_id}")
    for plan in resp.plans:
        cats = {}
        for s in plan.segments:
            cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
        names = ' → '.join([s.poi.name for s in plan.segments])
        print(f"\n  [{plan.theme}] {plan.poi_count}POIs ¥{plan.total_cost}")
        print(f"    类别: {cats}")
        print(f"    路线: {names}")
except Exception as e:
    print(f"规划失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试2: 第三层 动态抓取触发（无raw_query但有preferences）")
print("=" * 60)

req2 = PlanRequest(
    raw_query='',
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    budget=500,
    travelers='情侣',
    preferences=['拍照', '美食'],
    pace='适中'
)
try:
    resp2 = planner.plan(req2)
    print(f"\n规划成功！request_id={resp2.request_id}")
    for plan in resp2.plans:
        cats = {}
        for s in plan.segments:
            cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
        names = ' → '.join([s.poi.name for s in plan.segments])
        print(f"\n  [{plan.theme}] {plan.poi_count}POIs ¥{plan.total_cost}")
        print(f"    类别: {cats}")
        print(f"    路线: {names}")
except Exception as e:
    print(f"规划失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试3: 第三层 动态抓取触发（有raw_query）")
print("=" * 60)

req3 = PlanRequest(
    raw_query='杭州安静的文化体验和博物馆',
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    budget=300,
    travelers='独自',
    preferences=['文化'],
    pace='悠闲'
)
try:
    resp3 = planner.plan(req3)
    print(f"\n规划成功！request_id={resp3.request_id}")
    for plan in resp3.plans:
        cats = {}
        for s in plan.segments:
            cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
        names = ' → '.join([s.poi.name for s in plan.segments])
        print(f"\n  [{plan.theme}] {plan.poi_count}POIs ¥{plan.total_cost}")
        print(f"    类别: {cats}")
        print(f"    路线: {names}")
except Exception as e:
    print(f"规划失败: {e}")
    import traceback
    traceback.print_exc()

print("\n===== LLM测试完成 =====")
