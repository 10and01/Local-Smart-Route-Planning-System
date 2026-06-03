#!/usr/bin/env python3
"""阶段2调试：v5/direction 4种交通模式全面测试"""

import json
import requests
from backend.models.schemas import Location
from backend.data.direction_api import _get_amap_direction, MODE_MAP, _get_city_code

AMAP_KEY = "c1ee66fda72ea53f554376c6e903f4a9"

loc_a = Location(lat=30.2596, lng=120.1460)  # 西湖附近
loc_b = Location(lat=30.1890, lng=120.1000)  # 灵隐附近

def test_api_directly(mode_key: str):
    """直接调用高德API并打印完整响应"""
    amap_mode = MODE_MAP.get(mode_key, "walking")
    url = f"https://restapi.amap.com/v5/direction/{amap_mode}"
    params = {
        "origin": f"{loc_a.lng},{loc_a.lat}",
        "destination": f"{loc_b.lng},{loc_b.lat}",
        "key": AMAP_KEY,
        "show_fields": "cost",
    }
    if mode_key == "公交":
        params["city1"] = "0571"
        params["city2"] = "0571"

    print(f"\n{'='*60}")
    print(f"[直接测试] {mode_key} -> {amap_mode}")
    print(f"URL: {url}")
    print(f"Params: {params}")

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        print(f"Status: {data.get('status')}")
        print(f"Info: {data.get('info')}")
        print(f"Infocode: {data.get('infocode')}")

        if data.get("status") == "1":
            route = data.get("route", {})
            if "transit/integrated" in amap_mode:
                transits = route.get("transits", [])
                print(f"Transits count: {len(transits)}")
                if transits:
                    t = transits[0]
                    cost = t.get("cost", {})
                    print(f"  Distance: {t.get('distance')}m")
                    print(f"  Duration: {cost.get('duration')}s")
            else:
                paths = route.get("paths", [])
                print(f"Paths count: {len(paths)}")
                if paths:
                    p = paths[0]
                    cost = p.get("cost", {})
                    print(f"  Distance: {p.get('distance')}m")
                    print(f"  Duration(raw): {p.get('duration')}s")
                    print(f"  Duration(cost): {cost.get('duration')}s")
        else:
            print(f"FAILED: {data}")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")


def test_wrapper(mode_key: str):
    """测试封装函数 _get_amap_direction"""
    print(f"\n{'='*60}")
    print(f"[封装测试] {mode_key}")
    result = _get_amap_direction(loc_a, loc_b, mode_key, city="杭州")
    if result:
        distance_m, duration_sec = result
        print(f"  Result: distance={distance_m}m, duration={duration_sec}s ({duration_sec/60:.1f}min)")
    else:
        print(f"  Result: None")


if __name__ == "__main__":
    print("="*60)
    print("高德 v5/direction API 调试脚本")
    print(f"Key: {AMAP_KEY[:8]}...")
    print(f"From: {loc_a.lat},{loc_a.lng} (西湖)")
    print(f"To:   {loc_b.lat},{loc_b.lng} (灵隐)")
    print("="*60)

    # 重置 key 无效标记
    import backend.data.direction_api as da
    da._amap_key_invalid = False

    for mode in ["步行", "驾车", "骑行", "公交", "电动车"]:
        test_api_directly(mode)

    print("\n" + "="*60)
    print("封装函数测试")
    print("="*60)

    for mode in ["步行", "驾车", "骑行", "公交", "电动车"]:
        test_wrapper(mode)
