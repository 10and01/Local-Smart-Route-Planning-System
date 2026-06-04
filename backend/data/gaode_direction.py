# -*- coding: utf-8 -*-
"""
智能多模式交通规划
基于 direction_api 的底层能力，提供自动降级策略：
- 步行偏好且步行时间>30分钟时，自动选择更快的交通方式
"""

from typing import Tuple, Optional
from backend.models.schemas import Location
from backend.data.direction_api import get_travel_info

WALK_TIMEOUT_MIN = 30


def select_best_transport(
    from_loc: Location,
    to_loc: Location,
    preferred_mode: str = "步行",
    city: Optional[str] = None,
    walk_timeout: int = WALK_TIMEOUT_MIN,
) -> Tuple[int, int, str]:
    """
    智能选择最优交通方式。

    策略：
    1. 用户偏好非步行 → 直接使用该模式
    2. 用户偏好步行且步行时间 <= walk_timeout → 使用步行
    3. 用户偏好步行但步行时间 > walk_timeout → 查询公交/驾车/骑行，选最快的

    返回: (时间分钟, 距离米, 实际交通方式)
    """
    # 查询首选方式
    time_min, dist_m = get_travel_info(from_loc, to_loc, preferred_mode, city)

    if preferred_mode != "步行":
        return time_min, dist_m, preferred_mode

    if time_min <= walk_timeout:
        return time_min, dist_m, "步行"

    # 检查API是否已失效，避免超时等待（使用模块属性访问确保同步）
    import backend.data.direction_api as _direction_api
    if _direction_api._amap_key_invalid:
        # API已失效，直接用Haversine距离 + 不同模式速度估算，选择最快的
        from backend.core.route_engine import haversine_distance_m
        h_dist = int(haversine_distance_m(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng))
        best_time = time_min
        best_dist = dist_m
        best_mode = "步行"
        speed_map = {"公交": 20, "驾车": 30, "骑行": 15}
        for fallback, speed in speed_map.items():
            est_time = max(1, int(h_dist / 1000 / speed * 60))
            if est_time < best_time:
                best_time = est_time
                best_dist = h_dist
                best_mode = fallback
        return best_time, best_dist, best_mode

    # 步行超时：降级查询其他方式，选择最快的
    best_time = time_min
    best_dist = dist_m
    best_mode = "步行"
    api_failed = False

    for fallback in ("公交", "驾车", "骑行"):
        try:
            t, d = get_travel_info(from_loc, to_loc, fallback, city)
            if t < best_time:
                best_time = t
                best_dist = d
                best_mode = fallback
        except Exception:
            api_failed = True
            continue

    # 如果所有降级查询都因API失败而回退到相同估算，基于速度重新选择
    # 确保至少返回一个合理的非步行模式
    if best_mode == "步行" and api_failed:
        # 用Haversine距离 + 不同模式速度重新估算，选择最快的
        from backend.core.route_engine import haversine_distance_m
        h_dist = int(haversine_distance_m(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng))
        speed_map = {"公交": 20, "驾车": 30, "骑行": 15}
        for fallback, speed in speed_map.items():
            est_time = max(1, int(h_dist / 1000 / speed * 60))
            if est_time < best_time:
                best_time = est_time
                best_dist = h_dist
                best_mode = fallback

    return best_time, best_dist, best_mode
