import sys
sys.path.insert(0, 'backend')

from models.schemas import PlanRequest
from services.planner import planner_service

req = PlanRequest(
    city="杭州",
    date="2026-06-02",
    start_time="09:00",
    end_time="18:00",
    budget=0,
    traveler_type="独自",
    transport_mode="步行",
    selected_themes=["美食", "拍照", "自然"],
    pace_preference="适中",
    raw_query="喜欢爬山，爬完山想吃美食"
)

try:
    result = planner_service.plan(req)
    print("Success:", len(result.plans))
except Exception as e:
    import traceback
    traceback.print_exc()
