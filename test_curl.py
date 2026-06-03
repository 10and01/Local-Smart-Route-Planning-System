import subprocess
import json

payload = json.dumps({
    "city": "杭州",
    "date": "2026-06-02",
    "start_time": "09:00",
    "end_time": "18:00",
    "budget": 0,
    "traveler_type": "独自",
    "transport_mode": "步行",
    "selected_themes": ["美食", "拍照", "自然"],
    "pace_preference": "适中",
    "raw_query": "喜欢爬山，爬完山想吃美食"
}, ensure_ascii=False)

result = subprocess.run(
    ["curl", "-s", "-X", "POST", "http://127.0.0.1:8000/api/plan",
     "-H", "Content-Type: application/json",
     "-d", payload,
     "--max-time", "10"],
    capture_output=True, text=True, encoding="utf-8"
)
print("Return code:", result.returncode)
print("Stdout:", result.stdout[:500])
print("Stderr:", result.stderr[:200])
