# -*- coding: utf-8 -*-
"""
实时数据接入服务
高德天气 API + 路况 API
"""

import os
import requests
from typing import Optional, Dict, Any

AMAP_KEY = os.getenv("AMAP_KEY", "")

# 城市编码缓存（简化版，实际需要完整 adcode 映射）
CITY_ADCODE = {
    "北京": "110000",
    "上海": "310000",
    "广州": "440100",
    "深圳": "440300",
    "杭州": "330100",
    "成都": "510100",
    "南京": "320100",
    "武汉": "420100",
    "西安": "610100",
    "重庆": "500000",
}


class RealtimeDataService:
    """实时数据服务"""
    
    def __init__(self):
        self._weather_cache: Dict[str, Dict] = {}
        self._traffic_cache: Dict[str, Dict] = {}
    
    def get_weather(self, city: str) -> Optional[Dict[str, Any]]:
        """
        获取城市天气
        返回: {temperature, weather, windpower, humidity, reporttime}
        """
        if not AMAP_KEY:
            return None
        
        adcode = CITY_ADCODE.get(city)
        if not adcode:
            return None
        
        # 简单内存缓存（5分钟）
        cache_key = f"{city}_{adcode}"
        import time
        now = time.time()
        cached = self._weather_cache.get(cache_key)
        if cached and (now - cached.get("_cached_at", 0)) < 300:
            return {k: v for k, v in cached.items() if not k.startswith("_")}
        
        try:
            url = "https://restapi.amap.com/v3/weather/weatherInfo"
            resp = requests.get(url, params={
                "key": AMAP_KEY,
                "city": adcode,
                "extensions": "base",
            }, timeout=5)
            data = resp.json()
            
            if data.get("status") != "1":
                return None
            
            lives = data.get("lives", [])
            if not lives:
                return None
            
            live = lives[0]
            result = {
                "temperature": live.get("temperature"),
                "weather": live.get("weather"),
                "windpower": live.get("windpower"),
                "humidity": live.get("humidity"),
                "reporttime": live.get("reporttime"),
            }
            result["_cached_at"] = now
            self._weather_cache[cache_key] = result
            return {k: v for k, v in result.items() if not k.startswith("_")}
        
        except Exception as e:
            print(f"[Realtime] 天气查询失败: {e}")
            return None
    
    def get_traffic_status(self, city: str) -> Optional[Dict[str, Any]]:
        """
        获取城市交通状态
        返回: {level, description} level 1-4
        """
        if not AMAP_KEY:
            return None
        
        adcode = CITY_ADCODE.get(city)
        if not adcode:
            return None
        
        try:
            url = "https://restapi.amap.com/v3/traffic/status/circle"
            # 使用城市中心点附近查询
            resp = requests.get(url, params={
                "key": AMAP_KEY,
                "location": self._get_city_center_lnglat(city) or "120.146,30.2596",
                "radius": 5000,
            }, timeout=5)
            data = resp.json()
            
            if data.get("status") != "1":
                return None
            
            traffic = data.get("trafficinfo", {})
            evaluation = traffic.get("evaluation", {})
            
            return {
                "level": evaluation.get("level"),
                "description": evaluation.get("description"),
            }
        
        except Exception as e:
            print(f"[Realtime] 路况查询失败: {e}")
            return None
    
    def _get_city_center_lnglat(self, city: str) -> Optional[str]:
        """获取城市中心坐标 (lng,lat)"""
        from backend.data.loader import get_city_center
        center = get_city_center(city)
        if center:
            return f"{center['lng']},{center['lat']}"
        return None
    
    def apply_weather_boost(self, pois, weather: Optional[Dict] = None) -> list:
        """
        根据天气调整 POI 预评分
        返回调整后的 POI 列表
        """
        if not weather:
            return pois
        
        weather_type = weather.get("weather", "晴")
        temperature = None
        try:
            temperature = float(weather.get("temperature", 25))
        except (ValueError, TypeError):
            temperature = 25
        
        indoor_tags = {"博物馆", "美术馆", "商场", "购物中心", "餐厅", "咖啡馆", "影院", "剧院", "图书馆", "书店"}
        outdoor_tags = {"公园", "山", "湖", "湿地", "徒步", "户外", "自然", "古迹", "寺庙", "海滩", "登山"}
        cool_tags = {"商场", "博物馆", "影院", "咖啡馆", "图书馆", "室内"}
        
        for poi in pois:
            boost = 1.0
            tags = set(poi.tags or [])
            
            # 雨天/雪天
            if any(w in weather_type for w in ["雨", "雪", "雨夹雪"]):
                if tags & indoor_tags:
                    boost = 1.25
                elif tags & outdoor_tags:
                    boost = 0.75
            
            # 高温（>35°C）
            elif temperature > 35:
                if tags & cool_tags:
                    boost = 1.15
                elif tags & outdoor_tags:
                    boost = 0.85
            
            # 大风
            wind = weather.get("windpower", "")
            if any(w in str(wind) for w in ["7", "8", "9", "10", "11", "12"]):
                if tags & {"山", "高处", "观景台", "户外", "徒步"}:
                    boost = min(boost, 0.8)
            
            if hasattr(poi, "pre_score") and poi.pre_score is not None:
                poi.pre_score *= boost
        
        return pois


# 全局实例
realtime_service = RealtimeDataService()
