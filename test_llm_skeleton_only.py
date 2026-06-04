# -*- coding: utf-8 -*-
"""单独测试第四层骨架规划和第三层动态抓取"""
import sys
sys.path.insert(0, '.')

# 1. 测试动态抓取
print("=" * 60)
print("测试1: 第三层 动态抓取（preferences非空触发）")
print("=" * 60)

from backend.core.dynamic_fetch_planner import fetch_city_pois_dynamic
pois = fetch_city_pois_dynamic(
    city='杭州',
    user_query='拍照、美食',
    avoid=[],
    max_pois=20,
    pages_per_query=1
)
print(f"动态抓取返回 {len(pois)} 个POI")
for p in pois[:5]:
    print(f"  {p.name} | {p.category} | source={getattr(p, 'source', 'unknown')}")

# 2. 测试骨架规划
print("\n" + "=" * 60)
print("测试2: 第四层 LLM骨架规划")
print("=" * 60)

from backend.data.loader import get_cached_pois
from backend.core.preference import parse_preference_from_request
from backend.services.planner import RoutePlannerService

all_pois = get_cached_pois('杭州')
user_pref = parse_preference_from_request(['拍照', '美食'], '情侣', '适中', 500)
# 取Top-30候选
candidates = sorted(all_pois, key=lambda p: getattr(p, 'pre_score', 0.5), reverse=True)[:30]

planner = RoutePlannerService()
skeleton = planner._llm_skeleton_planning(
    candidate_pool=candidates,
    user_pref=user_pref,
    raw_query='杭州情侣拍照和美食，想去西湖',
    city='杭州'
)
print(f"骨架规划返回 {len(skeleton)} 个POI")
for p in skeleton:
    print(f"  {p.name} | {p.category}")

print("\n===== LLM专项测试完成 =====")
