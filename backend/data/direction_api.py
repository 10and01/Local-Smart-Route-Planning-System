# -*- coding: utf-8 -*-
"""
多模式路径规划服务 (高德 v5/direction 路线规划2.0)
- 步行：优先使用预计算 OSRM 矩阵
- 骑行/驾车/公交/电动车：查询高德路径规划 API + SQLite 缓存
"""

import os
import requests
from typing import Optional, Tuple

from backend.models.schemas import Location
from backend.data.loader import get_matrix_provider
from backend.db.models import DirectionCacheDAO
from backend.core.config import AMAP_KEY

# 交通模式映射（v5/direction）
MODE_MAP = {
    "步行": "walking",
    "驾车": "driving",
    "骑行": "bicycling",
    "公交": "transit/integrated",
    "电动车": "electrobike",
}

# 城市名 -> 高德 citycode（用于公交路径规划）
CITYCODE_MAP = {
    "北京": "010",
    "上海": "021",
    "天津": "022",
    "重庆": "023",
    "杭州": "0571",
    "南京": "025",
    "广州": "020",
    "深圳": "0755",
    "成都": "028",
    "武汉": "027",
    "西安": "029",
    "苏州": "0512",
    "郑州": "0371",
}

# 复用 HTTP Session，避免每次请求都重建 SSL 连接
_amap_session: Optional[requests.Session] = None
_amap_key_invalid = False  # 检测到 key 无效后，后续直接跳过


def _get_amap_session() -> requests.Session:
    """获取复用的 requests Session"""
    global _amap_session
    if _amap_session is None:
        _amap_session = requests.Session()
    return _amap_session


def _get_city_code(city_name: Optional[str]) -> str:
    """根据城市名获取高德 citycode，用于公交路径规划"""
    if not city_name:
        return "0571"  # 默认杭州
    code = CITYCODE_MAP.get(city_name)
    if code:
        return code
    # 尝试模糊匹配
    for name, c in CITYCODE_MAP.items():
        if name in city_name or city_name in name:
            return c
    return "0571"


def _parse_v5_response(data: dict, mode: str) -> Optional[Tuple[int, int]]:
    """
    解析高德 v5/direction 响应
    返回: (距离米, 时间秒) 或 None
    """
    route = data.get("route", {})

    if "transit/integrated" in mode:
        # 公交模式：使用 transits 而不是 paths
        transits = route.get("transits", [])
        if not transits:
            return None
        transit = transits[0]
        distance_m = int(transit.get("distance", 0))
        # 公交耗时在 cost.duration 中
        cost = transit.get("cost", {})
        duration_sec = int(cost.get("duration", 0))
        return distance_m, duration_sec
    else:
        # 驾车/步行/骑行/电动车：使用 paths
        paths = route.get("paths", [])
        if not paths:
            return None
        path = paths[0]
        distance_m = int(path.get("distance", 0))
        # 默认情况下 duration 不返回，需要 show_fields=cost
        # 先尝试直接获取，如果没有则尝试 cost.duration
        duration_sec = int(path.get("duration", 0))
        if not duration_sec:
            cost = path.get("cost", {})
            duration_sec = int(cost.get("duration", 0))
        return distance_m, duration_sec


def _get_amap_direction(
    from_loc: Location,
    to_loc: Location,
    mode: str,
    city: Optional[str] = None
) -> Optional[Tuple[int, int]]:
    """
    调用高德 v5/direction 路径规划 API
    返回: (距离米, 时间秒) 或 None
    """
    global _amap_key_invalid

    if not AMAP_KEY or _amap_key_invalid:
        return None

    amap_mode = MODE_MAP.get(mode, "walking")
    url = f"https://restapi.amap.com/v5/direction/{amap_mode}"
    params = {
        "origin": f"{from_loc.lng},{from_loc.lat}",
        "destination": f"{to_loc.lng},{to_loc.lat}",
        "key": AMAP_KEY,
        "show_fields": "cost",  # 确保返回耗时信息
    }

    # 公交模式需要 city1/city2 参数
    if mode == "公交":
        city_code = _get_city_code(city)
        params["city1"] = city_code
        params["city2"] = city_code

    try:
        session = _get_amap_session()
        resp = session.get(url, params=params, timeout=3)
        data = resp.json()

        if data.get("status") != "1":
            info = data.get("info", "unknown")
            infocode = data.get("infocode", "")
            if info == "INSUFFICIENT_PRIVILEGES":
                _amap_key_invalid = True
                print(f"[DirectionAPI] 高德 API key 权限不足，后续请求将直接跳过")
            elif infocode in ("10021", "10019", "10044"):
                # 10021=QPS超限 10019=日配额超限 10044=并发超限
                _amap_key_invalid = True
                print(f"[DirectionAPI] 高德 API 配额已超限 (code:{infocode})，后续请求将直接跳过")
            else:
                print(f"[DirectionAPI] 高德 API 错误: {info} (code:{infocode})")
            return None

        return _parse_v5_response(data, amap_mode)

    except Exception as e:
        print(f"[DirectionAPI] 高德 API 调用异常: {e}")
        return None


def get_travel_info(
    from_loc: Location,
    to_loc: Location,
    mode: str = "步行",
    city: Optional[str] = None
) -> Tuple[int, int]:
    """
    获取两点间的通行信息
    返回: (时间分钟, 距离米)

    策略：
    1. 步行模式 → 优先 OSRM 预计算矩阵 → Haversine 回退
    2. 其他模式 → 查 SQLite 缓存 → 高德 API（仅缓存未命中时） → 估算回退
    3. API key 无效时直接回退估算，避免超时等待
    """

    # 1. 步行模式：优先 OSRM 矩阵（不调用外部 API）
    if mode == "步行":
        provider = get_matrix_provider(city) if city else None
        if provider:
            result = provider.get_distance_time(
                from_loc.lat, from_loc.lng,
                to_loc.lat, to_loc.lng
            )
            if result:
                dist_m, time_sec = result
                return max(1, int(time_sec / 60)), int(dist_m)
        # 步行无矩阵 → Haversine 直接估算（不调用 API）
        from backend.core.route_engine import haversine_distance_m
        dist_m = int(haversine_distance_m(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng))
        time_min = max(1, int(dist_m / 1000 / 5 * 60))
        return time_min, dist_m

    # 2. API key 无效时直接估算回退，不查缓存不调用API
    if _amap_key_invalid:
        from backend.core.route_engine import haversine_distance_m
        dist_m = int(haversine_distance_m(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng))
        speed_kmh = {
            "步行": 5,
            "骑行": 15,
            "驾车": 30,
            "公交": 20,
            "电动车": 25,
        }.get(mode, 5)
        time_min = max(1, int(dist_m / 1000 / speed_kmh * 60))
        return time_min, dist_m

    # 3. 非步行模式：查缓存
    cached = DirectionCacheDAO.get(
        from_loc.lat, from_loc.lng,
        to_loc.lat, to_loc.lng,
        mode
    )
    if cached:
        dur_min = max(1, int(cached["duration_sec"] / 60))
        return dur_min, cached["distance_m"]

    # 4. 非步行且无缓存：调用高德 API（单次，带缓存写入）
    result = _get_amap_direction(from_loc, to_loc, mode, city=city)
    if result:
        distance_m, duration_sec = result
        DirectionCacheDAO.save(
            from_loc.lat, from_loc.lng,
            to_loc.lat, to_loc.lng,
            mode, distance_m, duration_sec
        )
        return max(1, int(duration_sec / 60)), distance_m

    # 5. 回退到 Haversine 估算
    from backend.core.route_engine import haversine_distance_m
    dist_m = int(haversine_distance_m(from_loc.lat, from_loc.lng, to_loc.lat, to_loc.lng))

    speed_kmh = {
        "步行": 5,
        "骑行": 15,
        "驾车": 30,
        "公交": 20,
        "电动车": 25,
    }.get(mode, 5)

    time_min = max(1, int(dist_m / 1000 / speed_kmh * 60))
    return time_min, dist_m
