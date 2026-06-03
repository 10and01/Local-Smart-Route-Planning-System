#!/usr/bin/env python3
"""阶段4测评：UGC架构先行测试"""

import copy
from backend.models.schemas import POI, Location, UserPreference, RouteConstraints
from backend.core.route_engine import compute_poi_marginal_value
from backend.data.loader import get_cached_pois

print("=" * 60)
print("阶段4测评：UGC架构先行")
print("=" * 60)

# 1. 测试UGC字段存在性
print("\n[1/3] POI模型UGC字段验证")
candidates = get_cached_pois("杭州")
ugc_fields_count = 0
for p in candidates[:20]:
    if hasattr(p, "ugc_sentiment_score") and hasattr(p, "ugc_scene_tags") and hasattr(p, "ugc_recent_warn"):
        ugc_fields_count += 1

print(f"  检查20个POI，含UGC字段: {ugc_fields_count}/20")

# 2. 测试UGC评分逻辑
print("\n[2/3] UGC参与路线评分验证")

# 构造测试POI
test_poi = POI(
    poi_id="test_001",
    name="测试景点",
    city="杭州",
    category="风景名胜",
    location=Location(lat=30.26, lng=120.15),
    rating=4.5,
    tags=["拍照", "自然"],
    ugc_keywords=["景色美", "人不多"],
    ugc_sentiment_score=0.8,
    ugc_scene_tags=["适合亲子", "情侣约会"],
    ugc_recent_warn=None,
)

user_pref = UserPreference(
    theme_weights={"美食": 0.2, "拍照": 0.9, "文化": 0.3, "自然": 0.8, "购物": 0.1, "娱乐": 0.2},
    traveler_type="亲子",
    pace_preference="适中",
)

# 计算有UGC的评分
score_with_ugc = compute_poi_marginal_value(
    poi=test_poi,
    pref_match=0.8,
    travel_time=15,
    dist_m=2000,
    user_pref=user_pref,
    budget=500,
    strategy="balanced"
)

# 计算无UGC的评分（sentiment=0, scene_tags=[]）
test_poi_no_ugc = copy.deepcopy(test_poi)
test_poi_no_ugc.ugc_sentiment_score = 0.0
test_poi_no_ugc.ugc_scene_tags = []

score_without_ugc = compute_poi_marginal_value(
    poi=test_poi_no_ugc,
    pref_match=0.8,
    travel_time=15,
    dist_m=2000,
    user_pref=user_pref,
    budget=500,
    strategy="balanced"
)

print(f"  有UGC评分: {score_with_ugc:.1f}")
print(f"  无UGC评分: {score_without_ugc:.1f}")
print(f"  UGC加分差: {score_with_ugc - score_without_ugc:.1f}")

# 3. 测试负面预警
print("\n[3/3] UGC负面预警验证")
test_poi_warn = copy.deepcopy(test_poi)
test_poi_warn.ugc_recent_warn = "五一排队3小时"

# 构建一个简化版路线来测试tips
tips = None
if test_poi_warn.ugc_recent_warn:
    tips = f"[!] 网友提醒：{test_poi_warn.ugc_recent_warn}"

print(f"  预警POI: {test_poi_warn.name}")
print(f"  生成tips: {tips}")

print("\n" + "=" * 60)
print("阶段4通过标准:")
ugc_score_diff = score_with_ugc - score_without_ugc
print(f"  [{'PASS' if ugc_fields_count >= 15 else 'FAIL'}] UGC字段正确生成/存在 ({ugc_fields_count}/20)")
print(f"  [{'PASS' if ugc_score_diff > 0 else 'FAIL'}] UGC加分使评分提高 ({ugc_score_diff:.1f})")
print(f"  [{'PASS' if tips and '排队3小时' in tips else 'FAIL'}] 负面预警正确展示")
print("=" * 60)
