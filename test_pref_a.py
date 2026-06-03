import sys
sys.path.insert(0, 'backend')
from core.route_engine import generate_preference_variants
from models.schemas import POI, Location, UserPreference, RouteConstraints

poi = POI(
    poi_id="1",
    name="Test",
    location=Location(lat=30.0, lng=120.0),
    category="test",
    rating=4.5,
    tags=["test"],
    city="杭州"
)

pref = UserPreference(
    theme_weights={"自然": 0.5},
    selected_themes=["自然"]
)

cons = RouteConstraints(
    start_time="09:00",
    end_time="18:00",
    city="杭州"
)

try:
    result = generate_preference_variants([poi], pref, cons)
    print("Success:", len(result))
except Exception as e:
    import traceback
    traceback.print_exc()
