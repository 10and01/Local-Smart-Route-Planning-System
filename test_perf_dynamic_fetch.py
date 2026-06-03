#!/usr/bin/env python3
"""阶段1测评：动态抓取性能优化测试"""

import time
import requests
import json

payload = {
    "city": "杭州",
    "date": "2026-06-02",
    "start_time": "09:00",
    "end_time": "18:00",
    "budget": 500,
    "traveler_type": "独自",
    "transport_mode": "步行",
    "preferences": ["美食", "拍照", "自然"],
    "pace": "适中",
    "raw_query": "喜欢爬山，爬完山想吃美食"  # 触发动态抓取
}

print("=" * 60)
print("阶段1测评：动态抓取性能优化")
print("=" * 60)

# 首次请求（无缓存）
print("\n[首次请求 - 无缓存]")
start = time.time()
try:
    r = requests.post("http://127.0.0.1:8000/api/plan", json=payload, timeout=180)
    end = time.time()
    print(f"Total time: {end-start:.1f}s")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        plans = data.get("plans", [])
        print(f"返回方案数: {len(plans)}")
        if plans:
            for i, plan in enumerate(plans[:3]):
                pois = [s["poi"]["name"] for s in plan.get("segments", [])]
                print(f"  方案{i+1}({plan.get('theme','?')}): {pois}")
    else:
        print(f"Error: {r.text[:200]}")
except Exception as e:
    print(f"Request failed: {e}")

# 等待1秒
print("\n等待1秒后发起重复请求...")
time.sleep(1)

# 重复请求（有缓存）
print("\n[重复请求 - 有缓存]")
start2 = time.time()
try:
    r2 = requests.post("http://127.0.0.1:8000/api/plan", json=payload, timeout=180)
    end2 = time.time()
    print(f"Total time: {end2-start2:.1f}s")
    print(f"Status: {r2.status_code}")
    if r2.status_code == 200:
        data = r2.json()
        plans = data.get("plans", [])
        print(f"返回方案数: {len(plans)}")
        if plans:
            for i, plan in enumerate(plans[:3]):
                pois = [s["poi"]["name"] for s in plan.get("segments", [])]
                print(f"  方案{i+1}({plan.get('theme','?')}): {pois}")
    else:
        print(f"Error: {r2.text[:200]}")
except Exception as e:
    print(f"Request failed: {e}")

print("\n" + "=" * 60)
print("通过标准检查:")
print("  [ ] 首次请求（无缓存）≤ 20秒")
print("  [ ] 重复请求（有缓存）≤ 2秒")
print("  [ ] 后端日志中 [DynamicFetch] 输出显示并发执行")
print("  [ ] 返回的POI数量与优化前基本一致（±10%以内）")
print("=" * 60)
