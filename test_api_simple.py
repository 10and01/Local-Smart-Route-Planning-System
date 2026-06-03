import requests
import json

payload = {
    "city": "杭州",
    "date": "2026-06-02",
    "start_time": "09:00",
    "end_time": "18:00",
    "budget": 0,
    "traveler_type": "独自",
    "transport_mode": "步行",
    "selected_themes": ["美食", "拍照", "自然"],
    "pace_preference": "适中",
    "raw_query": ""
}

try:
    r = requests.post("http://127.0.0.1:8000/api/plan", json=payload, timeout=180)
    print("Status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("Plans:", len(data.get("plans", [])))
    else:
        print("Response:", r.text[:500])
except Exception as e:
    print("Error:", e)
