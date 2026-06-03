#!/usr/bin/env python3
"""阶段1测评：动态抓取性能优化测试（直接测试模块）"""

import time
from backend.core.dynamic_fetch_planner import fetch_city_pois_dynamic

print("=" * 60)
print("阶段1测评：动态抓取性能优化")
print("=" * 60)

# 测试1：首次请求（无缓存或部分缓存）
print("\n[测试1] 首次动态抓取（并发+缓存）")
start = time.time()
pois = fetch_city_pois_dynamic(
    city="杭州",
    user_query="喜欢爬山，爬完山想吃美食",
    avoid=None,
    max_pois=80,
    pages_per_query=3
)
elapsed = time.time() - start
print(f"耗时: {elapsed:.1f}s")
print(f"获取POI数: {len(pois)}")

# 测试2：重复请求（应命中缓存）
print("\n[测试2] 重复动态抓取（缓存命中）")
start2 = time.time()
pois2 = fetch_city_pois_dynamic(
    city="杭州",
    user_query="喜欢爬山，爬完山想吃美食",
    avoid=None,
    max_pois=80,
    pages_per_query=3
)
elapsed2 = time.time() - start2
print(f"耗时: {elapsed2:.1f}s")
print(f"获取POI数: {len(pois2)}")

# 测试3：验证返回的POI信息
print("\n[测试3] POI样例")
for i, p in enumerate(pois[:5]):
    print(f"  {i+1}. {p.name} ({p.category}, 评分:{p.rating})")

print("\n" + "=" * 60)
print("通过标准检查:")
passed = []
if elapsed <= 20:
    passed.append("  [PASS] 首次请求 ≤ 20秒")
else:
    passed.append(f"  [FAIL] 首次请求 {elapsed:.1f}s > 20秒")

if elapsed2 <= 2:
    passed.append("  [PASS] 重复请求 ≤ 2秒")
else:
    passed.append(f"  [FAIL] 重复请求 {elapsed2:.1f}s > 2秒")

if len(pois) > 0:
    passed.append(f"  [PASS] 返回POI数量 > 0 ({len(pois)})")
else:
    passed.append("  [FAIL] 返回POI数量为0")

for p in passed:
    print(p)
print("=" * 60)
