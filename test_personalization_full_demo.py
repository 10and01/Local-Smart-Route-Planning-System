#!/usr/bin/env python3
"""
个性化系统全链路演示：
  1. 用户画像文本 -> LLM生成初始画像
  2. 模糊query -> LLM解析当前偏好
  3. 画像融合 -> 生成差异化路线
  4. 三层对比评测
"""

from backend.core.personalization import UserPersonalizationEngine
from backend.core.personalization_eval import (
    MOCK_PROFILES, evaluate_personalization_impact
)
from backend.models.schemas import PlanRequest, RouteConstraints, Location
from backend.data.loader import get_cached_pois, get_city_center

print("=" * 70)
print("个性化系统全链路演示")
print("=" * 70)

engine = UserPersonalizationEngine()
candidates = get_cached_pois("杭州")
center = get_city_center("杭州")
start_point = Location(lat=center["lat"], lng=center["lng"]) if center else None

# ========================================================================
# 演示1：用户画像文本 -> 初始画像生成
# ========================================================================
print("\n[演示1] 用户画像文本初始化")
print("-" * 70)

profile_texts = [
    "我喜欢美食和拍照，不喜欢排队，经常带孩子出门，预算不太高",
    "情侣出游，喜欢浪漫夜景和安静的地方，预算充足",
]

for text in profile_texts:
    print(f"\n  输入文本: {text}")
    pref = engine.init_profile_from_text(text)
    if pref:
        print(f"  生成画像:")
        print(f"    theme_weights: {pref.theme_weights}")
        print(f"    traveler_type: {pref.traveler_type}")
        print(f"    budget_level: {pref.budget_level}")
        print(f"    willingness_to_queue: {pref.willingness_to_queue}")
        print(f"    price_sensitivity: {pref.price_sensitivity}")

# ========================================================================
# 演示2：同一模糊query + 不同画像 -> 差异化路线
# ========================================================================
print("\n[演示2] 同一query配不同画像的推荐差异")
print("-" * 70)

query = "周末去杭州玩，想体验当地特色"
request = PlanRequest(
    city="杭州",
    preferences=[],  # 无明确标签！
    traveler_type="独自",
    budget=500,
    raw_query=query,
    start_time="09:00",
    end_time="18:00",
    transport_mode="步行",
    pace="适中",
)
constraints = RouteConstraints(
    city="杭州",
    start_time="09:00",
    end_time="18:00",
    start_point=start_point,
    budget=500,
    transport_mode="步行",
)

# 先调用LLM解析当前query
from backend.core.llm_parser import parse_preference_from_llm
llm_pref = parse_preference_from_llm(
    raw_query=query,
    preferences=[],
    travelers="独自",
    pace="适中",
    budget=500,
)
print(f"\n  Query: {query}")
if llm_pref:
    print(f"  LLM解析结果: { {k:v for k,v in llm_pref.theme_weights.items() if v>0.3} }, "
          f"traveler={llm_pref.traveler_type}")

# 对比3种画像
for profile_name in ["美食型", "文化型", "户外型"]:
    report = evaluate_personalization_impact(
        candidates, request, constraints,
        profile_name, MOCK_PROFILES[profile_name],
        llm_pref=llm_pref, fusion_alpha=0.3
    )
    fused_pois = report["signature_fused"][0]["poi_names"] if report["signature_fused"] else []
    print(f"\n  [{profile_name}] 推荐POI: {fused_pois}")
    print(f"    规则vsLLM差异: {report['diff_rule_vs_llm']}")
    print(f"    LLMvs画像差异: {report['diff_llm_vs_fused']}")

# ========================================================================
# 演示3：不同query + 同一画像 -> 画像的跨场景一致性
# ========================================================================
print("\n[演示3] 不同query配同一画像（亲子型）的跨场景一致性")
print("-" * 70)

queries = [
    "带小孩去杭州，想爬山和看博物馆",
    "周末亲子游，想去乐园和动物园",
]

for q in queries:
    req = PlanRequest(
        city="杭州", preferences=[], traveler_type="亲子",
        budget=500, raw_query=q,
        start_time="09:00", end_time="18:00",
        transport_mode="步行", pace="适中",
    )
    report = evaluate_personalization_impact(
        candidates, req, constraints,
        "亲子型", MOCK_PROFILES["亲子型"],
        llm_pref=None, fusion_alpha=0.3
    )
    rule_pois = report["signature_rule"][0]["poi_names"] if report["signature_rule"] else []
    fused_pois = report["signature_fused"][0]["poi_names"] if report["signature_fused"] else []
    print(f"\n  Query: {q}")
    print(f"    无画像推荐: {rule_pois}")
    print(f"    有画像推荐: {fused_pois}")
    print(f"    差异度: {report['diff_rule_vs_fused']}")

print("\n" + "=" * 70)
print("演示完成")
print("=" * 70)
