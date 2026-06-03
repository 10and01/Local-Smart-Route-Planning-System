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
    "raw_query": ""
}

try:
    r = requests.post("http://127.0.0.1:8000/api/plan", json=payload, timeout=60)
    print("Status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        plans = data.get("plans", [])
        print(f"\n共生成 {len(plans)} 套方案\n")
        for i, plan in enumerate(plans):
            print(f"=== 方案 {i+1}: {plan['theme']} ===")
            print(f"描述: {plan['description']}")
            print(f"总用时: {plan['total_time']}, 总花费: {plan['total_cost']}元, POI数: {plan['poi_count']}")
            print(f"整体理由: {plan['overall_reasoning']}")
            print("路线节点:")
            for seg in plan['segments']:
                print(f"  [{seg['arrive_time']}-{seg['leave_time']}] {seg['poi']['name']} ({seg['poi']['category']})")
                print(f"    停留{seg['duration']}分钟 | 到下一站: {seg['transport_to_next']} | 距离: {seg['transport_distance_m']}m")
                if seg['tips']:
                    print(f"    💡 {seg['tips']}")
                if seg['selection_reasons']:
                    print(f"    📌 推荐理由: {seg['selection_reasons'][0]}")
            print()
    else:
        print("Error:", r.text[:500])
except Exception as e:
    print("Error:", e)
