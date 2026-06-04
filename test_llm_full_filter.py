# -*- coding: utf-8 -*-
"""测试LLM全量筛选效果"""
import sys
sys.path.insert(0, '.')
from backend.data import direction_api
direction_api._amap_key_invalid = True

from backend.data.loader import get_cached_pois
from backend.models.schemas import PlanRequest, RouteConstraints
from backend.core.preference import parse_preference_from_request
from backend.core.hybrid_filter import HybridPOIFilter
from backend.core.semantic_matcher import semantic_matcher

semantic_matcher.clear_cache()
pois = get_cached_pois('杭州')
for p in pois:
    semantic_matcher.get_poi_embedding(p)

print("=" * 60)
print("测试：LLM全量筛选 219个POI（拍照+美食）")
print("=" * 60)

user_pref = parse_preference_from_request(['拍照','美食'], '情侣', '适中', 500)
req = PlanRequest(
    raw_query='杭州情侣拍照和美食',
    city='杭州',
    start_time='09:00',
    end_time='18:00',
    budget=500,
    travelers='情侣',
    preferences=['拍照','美食'],
    pace='适中'
)
cons = RouteConstraints(city='杭州', start_time='09:00', end_time='18:00', budget=500, transport_mode='步行')

hf = HybridPOIFilter()
candidates, strategy, metadata = hf.filter(pois, req, user_pref, cons)

print(f"\nLLM覆盖率: {metadata.get('llm_coverage', 'N/A')}")
print(f"候选池Top-10:")
for i, p in enumerate(candidates[:10]):
    print(f"  #{i+1} {p.name} | Embedding={p.pre_score:.3f} LLM={getattr(p, 'llm_match_score', 'N/A')} cat={p.category}")

# 找西湖
xihu = [(i,p) for i,p in enumerate(candidates) if '西湖' in p.name]
print(f"\n西湖相关POI排名:")
for idx,p in xihu[:5]:
    print(f"  #{idx+1} {p.name} | Embedding={p.pre_score:.3f} LLM={getattr(p, 'llm_match_score', 'N/A')} cat={p.category}")

# 找KTV
ktv = [(i,p) for i,p in enumerate(candidates) if '纯K' in p.name or 'KTV' in p.name]
print(f"\nKTV排名:")
for idx,p in ktv[:3]:
    print(f"  #{idx+1} {p.name} | Embedding={p.pre_score:.3f} LLM={getattr(p, 'llm_match_score', 'N/A')} cat={p.category}")

print("\n===== 测试完成 =====")
