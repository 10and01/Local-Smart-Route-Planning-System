#!/usr/bin/env python3
"""阶段2测评：交通API升级（v5/direction）测试"""

from backend.data.direction_api import _get_amap_direction
from backend.models.schemas import Location

print("=" * 60)
print("阶段2测评：交通API升级（v3->v5）")
print("=" * 60)

loc_a = Location(lat=30.2596, lng=120.1460)  # 西湖附近
loc_b = Location(lat=30.1890, lng=120.1000)  # 灵隐附近

results = {}
for mode in ["步行", "驾车", "骑行", "公交", "电动车"]:
    print(f"\n[测试] {mode}模式")
    try:
        result = _get_amap_direction(loc_a, loc_b, mode, city="杭州")
        if result:
            distance_m, duration_sec = result
            print(f"  距离: {distance_m}m, 时间: {duration_sec}s ({duration_sec/60:.1f}分钟)")
            results[mode] = (distance_m, duration_sec)
        else:
            print(f"  结果: None (API未返回或权限不足)")
            results[mode] = None
    except Exception as e:
        print(f"  异常: {type(e).__name__}: {e}")
        results[mode] = None

print("\n" + "=" * 60)
print("通过标准检查:")
walk_dist = results.get("步行", (0, 0))
drive_dist = results.get("驾车", (0, 0))
bike_dist = results.get("骑行", (0, 0))

# 1. v5返回状态
v5_ok = any(r is not None for r in results.values())
print(f"  [{'PASS' if v5_ok else 'FAIL'}] v5/direction 返回状态")

# 2. 4种交通模式都能返回有效结果（至少4种）
modes_ok = sum(1 for r in results.values() if r is not None)
all_modes_ok = modes_ok >= 4
print(f"  [{'PASS' if all_modes_ok else 'FAIL'}] {modes_ok}/5 种交通模式返回有效(distance, duration)")

# 3. 步行距离与合理范围
if walk_dist and walk_dist[0]:
    walk_reasonable = 1000 <= walk_dist[0] <= 20000
    print(f"  [{'PASS' if walk_reasonable else 'FAIL'}] 步行距离合理性 ({walk_dist[0]}m)")
else:
    print("  [FAIL] 步行距离无法验证")

# 4. 驾车/骑行/步行距离对比
if drive_dist and walk_dist and drive_dist[0] and walk_dist[0]:
    drive_gt_walk = drive_dist[0] >= walk_dist[0] * 0.5
    print(f"  [{'PASS' if drive_gt_walk else 'FAIL'}] 驾车距离 >= 步行距离*0.5 ({drive_dist[0]} vs {walk_dist[0]})")
else:
    print("  [INFO] 驾车/步行距离对比无法验证")

# 5. 驾车比步行快
if drive_dist and walk_dist and drive_dist[1] and walk_dist[1]:
    drive_faster = drive_dist[1] < walk_dist[1]
    print(f"  [{'PASS' if drive_faster else 'FAIL'}] 驾车时间 < 步行时间 ({drive_dist[1]}s vs {walk_dist[1]}s)")

print("=" * 60)
