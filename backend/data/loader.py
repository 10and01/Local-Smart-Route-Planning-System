# -*- coding: utf-8 -*-
"""
数据加载模块
负责从JSON文件加载POI数据和距离矩阵
"""

import json
import os
from typing import List, Dict, Optional

from backend.models.schemas import POI, Location


# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def load_pois(city: Optional[str] = None) -> List[POI]:
    """
    加载POI数据
    加载优先级:
      1. {city}_pois.json (LLM丰富化后的高质量数据)
      2. {city}_pois_fallback.json (fallback规则生成的临时数据)
      3. {city}_pois_mock.json (mock数据)
      4. 默认杭州mock数据
    """
    # 尝试加载城市特定数据
    if city:
        # 1. LLM丰富化后的最终数据
        city_file = os.path.join(DATA_DIR, f"{city}_pois.json")
        if os.path.exists(city_file):
            return _load_poi_file(city_file)
        
        # 2. fallback临时数据
        fallback_file = os.path.join(DATA_DIR, f"{city}_pois_fallback.json")
        if os.path.exists(fallback_file):
            return _load_poi_file(fallback_file)
        
        # 3. mock数据
        mock_file = os.path.join(DATA_DIR, f"{city}_pois_mock.json")
        if os.path.exists(mock_file):
            return _load_poi_file(mock_file)
    
    # 加载默认mock数据（杭州）
    default_files = [
        os.path.join(DATA_DIR, "杭州_pois.json"),
        os.path.join(DATA_DIR, "杭州_pois_fallback.json"),
        os.path.join(DATA_DIR, "杭州_pois_mock.json"),
        os.path.join(DATA_DIR, "hangzhou_pois_mock.json"),
    ]
    for f in default_files:
        if os.path.exists(f):
            return _load_poi_file(f)
    
    # 没有任何数据时返回空列表
    return []


def _load_poi_file(filepath: str) -> List[POI]:
    """从JSON文件加载POI列表"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    
    pois = []
    for item in raw_data:
        try:
            loc_data = item.get("location", {})
            location = Location(
                lat=loc_data.get("lat", 0),
                lng=loc_data.get("lng", 0)
            )
            
            poi = POI(
                poi_id=item.get("poi_id", ""),
                name=item.get("name", ""),
                city=item.get("city", ""),
                district=item.get("district"),
                category=item.get("category", ""),
                sub_category=item.get("sub_category"),
                address=item.get("address"),
                location=location,
                tel=item.get("tel"),
                rating=item.get("rating"),
                price=item.get("price"),
                business_hours=item.get("business_hours"),
                suggested_duration=item.get("suggested_duration", 60),
                tags=item.get("tags", []),
                ugc_keywords=item.get("ugc_keywords", []),
                highlights=item.get("highlights"),
                photos=item.get("photos"),
                suitable_for=item.get("suitable_for"),
                source=item.get("source", "unknown")
            )
            pois.append(poi)
        except Exception as e:
            print(f"加载POI失败: {item.get('name', 'unknown')}, 错误: {e}")
            continue
    
    return pois


def load_distance_matrix(city: Optional[str] = None) -> Optional[Dict]:
    """加载距离矩阵"""
    matrix_file = os.path.join(DATA_DIR, "distance_matrix_haversine.json")
    if os.path.exists(matrix_file):
        with open(matrix_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


class DistanceMatrixProvider:
    """
    距离矩阵查询器
    支持OSRM真实距离矩阵和Haversine回退
    """
    
    def __init__(self, matrix_data: Optional[Dict], pois: List[POI]):
        self.poi_ids = matrix_data.get("poi_ids", []) if matrix_data else []
        self.dist_matrix = matrix_data.get("distance_matrix", []) if matrix_data else []
        self.time_matrix = matrix_data.get("duration_matrix", []) if matrix_data else []
        self.has_matrix = bool(self.poi_ids and self.dist_matrix)
        
        # 构建坐标到矩阵索引的映射
        self.coord_to_idx: Dict[tuple, int] = {}
        if self.has_matrix:
            for i, pid in enumerate(self.poi_ids):
                for poi in pois:
                    if poi.poi_id == pid or poi.name == pid:
                        key = (round(poi.location.lat, 6), round(poi.location.lng, 6))
                        self.coord_to_idx[key] = i
                        break
        
        if self.has_matrix:
            print(f"[DistanceMatrixProvider] 加载了 {len(self.poi_ids)} 个POI的距离矩阵，坐标匹配 {len(self.coord_to_idx)} 个")
    
    def get_distance_time(self, lat1: float, lng1: float, lat2: float, lng2: float) -> Optional[tuple]:
        """
        查询两点间的距离和耗时
        返回: (距离米, 时间秒) 或 None
        """
        if not self.has_matrix:
            return None
        
        key1 = (round(lat1, 6), round(lng1, 6))
        key2 = (round(lat2, 6), round(lng2, 6))
        idx1 = self.coord_to_idx.get(key1)
        idx2 = self.coord_to_idx.get(key2)
        
        if idx1 is not None and idx2 is not None:
            dist = self.dist_matrix[idx1][idx2]
            if dist is not None and dist > 0:
                time_sec = self.time_matrix[idx1][idx2] if self.time_matrix else dist / 1.2
                return float(dist), float(time_sec)
        
        return None
    
    def estimate_travel(self, lat1: float, lng1: float, lat2: float, lng2: float, mode: str = "步行") -> tuple:
        """
        估算旅行时间和距离，优先用矩阵，回退到Haversine
        返回: (时间分钟, 距离米)
        """
        result = self.get_distance_time(lat1, lng1, lat2, lng2)
        if result is not None:
            dist_m, time_sec = result
            # OSRM返回的duration是秒，根据交通方式微调
            mode_factor = {
                "步行": 1.0,
                "骑行": 0.4,
                "驾车": 0.15,
                "公交": 0.5,
            }.get(mode, 1.0)
            time_min = max(1, int(time_sec * mode_factor / 60))
            return time_min, int(dist_m)
        
        # 回退到Haversine
        return None


# 全局缓存
_poi_cache: Dict[str, List[POI]] = {}
_matrix_providers: Dict[str, DistanceMatrixProvider] = {}


def get_cached_pois(city: str) -> List[POI]:
    """带缓存的POI加载"""
    if city not in _poi_cache:
        _poi_cache[city] = load_pois(city)
    return _poi_cache[city]


def get_matrix_provider(city: str) -> Optional[DistanceMatrixProvider]:
    """获取距离矩阵查询器（延迟加载，按城市隔离）"""
    global _matrix_providers
    if city not in _matrix_providers:
        pois = get_cached_pois(city)
        # 优先加载城市特定的OSRM矩阵
        osrm_file = os.path.join(DATA_DIR, f"distance_matrix_osrm_foot_{city}.json")
        matrix_data = None
        if os.path.exists(osrm_file):
            with open(osrm_file, "r", encoding="utf-8") as f:
                matrix_data = json.load(f)
        elif city in ("杭州", "hangzhou"):
            # 仅杭州回退到旧的全局矩阵（兼容旧数据）
            legacy_file = os.path.join(DATA_DIR, "distance_matrix_osrm_foot.json")
            if os.path.exists(legacy_file):
                with open(legacy_file, "r", encoding="utf-8") as f:
                    matrix_data = json.load(f)
        _matrix_providers[city] = DistanceMatrixProvider(matrix_data, pois)
    return _matrix_providers[city]


def get_city_center(city: str) -> Optional[Dict[str, float]]:
    """获取城市中心坐标（所有POI的平均位置）"""
    pois = get_cached_pois(city)
    if not pois:
        return None
    
    total_lat = 0.0
    total_lng = 0.0
    valid_count = 0
    for poi in pois:
        if poi.location and poi.location.lat and poi.location.lng:
            total_lat += poi.location.lat
            total_lng += poi.location.lng
            valid_count += 1
    
    if valid_count == 0:
        return None
    
    return {"lat": round(total_lat / valid_count, 6), "lng": round(total_lng / valid_count, 6)}


def clear_cache(city: Optional[str] = None):
    """清除缓存（用于热重启）
    city=None 时清除全部缓存
    """
    global _poi_cache, _matrix_providers
    if city is None:
        _poi_cache.clear()
        _matrix_providers.clear()
        print("[Cache] 全部POI缓存和矩阵缓存已清除")
    else:
        _poi_cache.pop(city, None)
        _matrix_providers.pop(city, None)
        print(f"[Cache] {city} 的POI缓存和矩阵缓存已清除")
