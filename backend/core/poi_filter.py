# -*- coding: utf-8 -*-
"""
POI 筛选器
根据质量条件筛选出值得 LLM 丰富化的高质量旅游 POI
"""

import math
from typing import List, Dict, Optional, Set


DEFAULT_EXCLUDE_CATEGORIES: Set[str] = {
    "商务住宅",
    "地名地址信息",
    "科教文化服务",
    "政府机构及社会团体",
    "交通设施服务",
    "金融保险服务",
    "公司企业",
    "住宿服务",        # 排除酒店、宾馆、旅馆等
}


def haversine_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """计算两点间距离（公里）"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def compute_pois_center(pois: List[Dict]) -> Optional[tuple]:
    """计算 POI 列表的中心坐标 (lat, lng)"""
    valid = []
    for p in pois:
        loc = p.get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is not None and lng is not None:
            valid.append((lat, lng))
    if not valid:
        return None
    avg_lat = sum(v[0] for v in valid) / len(valid)
    avg_lng = sum(v[1] for v in valid) / len(valid)
    return avg_lat, avg_lng


def filter_pois(
    pois: List[Dict],
    center_lat: Optional[float] = None,
    center_lng: Optional[float] = None,
    max_distance_km: float = 50.0,     # 放宽距离限制，让更多候选进入精筛
    min_rating: Optional[float] = 3.5,  # 评分门槛：低于3.5的POI质量通常较差
    exclude_categories: Optional[Set[str]] = None,
    max_per_category: int = 60,         # 每类保留更多，避免规则误筛
    require_location: bool = True,
) -> List[Dict]:
    """
    筛选高质量旅游 POI

    筛选规则（按顺序应用）：
    1. 必须有有效坐标（除非 require_location=False）
    2. 排除非旅游类分类
    3. 距离城市中心不超过 max_distance_km
    4. 有评分且不低于 min_rating（如果设置）
    5. 每类最多保留 top max_per_category 条（按评分降序）

    返回：筛选后的 POI 列表（保持原始顺序的子集）
    """
    if exclude_categories is None:
        exclude_categories = DEFAULT_EXCLUDE_CATEGORIES

    # 计算中心坐标
    if center_lat is None or center_lng is None:
        center = compute_pois_center(pois)
        if center:
            center_lat, center_lng = center
        else:
            # 无坐标时无法按距离筛选，直接跳过距离检查
            center_lat, center_lng = 0.0, 0.0

    # Step 1: 基础过滤（坐标、分类）
    candidates = []
    for poi in pois:
        loc = poi.get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")

        if require_location and (lat is None or lng is None):
            continue

        category = poi.get("category", "")
        if any(excl in category for excl in exclude_categories):
            continue

        candidates.append(poi)

    # Step 2: 距离过滤
    if max_distance_km > 0 and center_lat is not None and center_lng is not None:
        filtered_by_distance = []
        for poi in candidates:
            loc = poi.get("location", {})
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is None or lng is None:
                continue
            dist = haversine_distance_km(lat, lng, center_lat, center_lng)
            if dist <= max_distance_km:
                poi["_distance_km"] = round(dist, 2)
                filtered_by_distance.append(poi)
        candidates = filtered_by_distance

    # Step 3: 评分过滤
    if min_rating is not None:
        candidates = [p for p in candidates if p.get("rating") is not None and p.get("rating") >= min_rating]

    # Step 4: 每类取 top N（按评分降序，无评分排最后）
    category_groups: Dict[str, List[Dict]] = {}
    for poi in candidates:
        cat = poi.get("category", "其他")
        category_groups.setdefault(cat, []).append(poi)

    final = []
    for cat, group in category_groups.items():
        # 按评分降序排序，无评分的放最后
        group.sort(key=lambda p: (p.get("rating") or 0), reverse=True)
        selected = group[:max_per_category]
        final.extend(selected)

    # 清理临时字段，按原始顺序排序
    id_to_poi = {p.get("poi_id"): p for p in final}
    result = []
    for poi in pois:
        if poi.get("poi_id") in id_to_poi:
            p = id_to_poi[poi["poi_id"]]
            p.pop("_distance_km", None)
            result.append(p)

    return result


def get_filter_stats(pois: List[Dict], filtered: List[Dict]) -> Dict:
    """返回筛选统计信息"""
    return {
        "total": len(pois),
        "filtered": len(filtered),
        "excluded": len(pois) - len(filtered),
        "exclusion_rate": round((len(pois) - len(filtered)) / len(pois) * 100, 1) if pois else 0,
    }
