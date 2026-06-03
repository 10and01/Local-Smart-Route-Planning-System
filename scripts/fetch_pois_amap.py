#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图POI数据获取脚本
用法:
    1. 到 https://lbs.amap.com/dev/key/app 申请Web服务Key
    2. 填写下面的 AMAP_KEY
    3. python scripts/fetch_pois_amap.py
"""

import requests
import json
import time
import os
import sys
from typing import List, Dict
from dotenv import load_dotenv

# Windows控制台UTF-8编码修复
if sys.platform == "win32":
    import codecs
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

# 加载项目根目录的 .env 文件
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path, override=True)

# ==========================================
# 配置区 - 从 .env 文件或环境变量读取高德Key
# ==========================================
AMAP_KEY = os.getenv("AMAP_KEY", "")

# POI分类：覆盖景点、美食、休闲娱乐、购物
POI_TYPES = [
    ("110000", "风景名胜"),      # 景点
    ("050000", "餐饮服务"),      # 美食
    ("080000", "休闲娱乐"),      # 休闲娱乐
    ("060000", "购物服务"),      # 购物
    # ("140000", "酒店宾馆"),      # 酒店 — 不抓取，避免进入旅游路线
]

CITIES = ["杭州"]  # 可扩展多城市
OUTPUT_DIR = "data"


def search_poi(city: str, poi_type: str, page: int = 1) -> Dict:
    """
    高德地点搜索API
    文档: https://lbs.amap.com/api/webservice/guide/api/search
    """
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "types": poi_type,
        "city": city,
        "citylimit": "true",      # 严格限制在城市内
        "offset": 25,             # 每页25条（最大）
        "page": page,
        "extensions": "all",      # 返回全部信息
        "output": "JSON"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data
        else:
            print(f"  API错误: {data.get('info', '未知错误')}")
            return {}
    except Exception as e:
        print(f"  请求失败: {e}")
        return {}


def parse_poi(raw: Dict) -> Dict:
    """
    将高德原始POI数据解析为项目标准格式
    """
    biz_ext = raw.get("biz_ext", {})
    
    # 解析坐标
    location_str = raw.get("location", "")
    lng, lat = None, None
    if "," in location_str:
        parts = location_str.split(",")
        try:
            lng = float(parts[0])
            lat = float(parts[1])
        except (ValueError, IndexError):
            pass
    
    # 处理分类：高德type可能是"风景名胜;公园广场"，取一级分类
    type_full = raw.get("type", "")
    category = type_full.split(";")[0] if type_full else ""
    
    # 处理图片：高德photos是对象列表，提取url
    photos_raw = raw.get("photos", [])
    photos = []
    if isinstance(photos_raw, list):
        for ph in photos_raw:
            if isinstance(ph, dict) and ph.get("url"):
                photos.append(ph["url"])
            elif isinstance(ph, str):
                photos.append(ph)
    
    # 处理价格
    price_val = None
    if biz_ext.get("cost"):
        try:
            price_val = int(float(biz_ext["cost"]))
        except (ValueError, TypeError):
            pass
    
    # 处理评分
    rating_val = None
    if biz_ext.get("rating"):
        try:
            rating_val = float(biz_ext["rating"])
        except (ValueError, TypeError):
            pass
    
    # 处理tags
    tags = []
    if raw.get("tag"):
        tags = [t.strip() for t in raw["tag"].split(",") if t.strip()]
    
    return {
        "poi_id": raw.get("id"),
        "name": raw.get("name", ""),
        "city": raw.get("cityname", ""),
        "district": raw.get("adname", ""),
        "category": category,
        "sub_category": None,
        "address": raw.get("address") if isinstance(raw.get("address"), str) else "",
        "location": {
            "lng": lng,
            "lat": lat
        },
        "tel": raw.get("tel", "") or None,
        "rating": rating_val,
        "price": price_val,
        "business_hours": raw.get("business", "") or None,
        "suggested_duration": 60,
        "tags": tags,
        "ugc_keywords": [],
        "highlights": None,
        "photos": photos if photos else None,
        "suitable_for": None,
        "source": "amap"
    }


def fetch_city_pois(city: str, max_per_type: int = 50, fetch_pages: int = 8) -> List[Dict]:
    """
    获取一个城市的POI数据
    
    Args:
        max_per_type: 每类POI最终保留多少条（按评分取Top N）
        fetch_pages: 每类抓取多少页（多抓然后筛高分，默认8页=200条）
    """
    all_pois = []
    
    for type_code, type_name in POI_TYPES:
        print(f"正在获取 [{city}] - [{type_name}] ...")
        type_pois = []
        
        # 第一步：多页抓取（比最终保留量多抓几倍，确保有足够的高分候选）
        for page in range(1, fetch_pages + 1):
            data = search_poi(city, type_code, page)
            pois = data.get("pois", [])
            
            if not pois:
                break
            
            for raw in pois:
                parsed = parse_poi(raw)
                parsed["type_name"] = type_name
                type_pois.append(parsed)
            
            print(f"  第{page}页获取 {len(pois)} 条")
            
            if len(pois) < 25:
                break
            
            time.sleep(0.3)
        
        # 第二步：按评分降序排序，取高分Top N
        # 有评分的排前面，无评分或低分的放到后面
        type_pois.sort(key=lambda p: (p.get("rating") or 0.0), reverse=True)
        selected = type_pois[:max_per_type]
        
        print(f"  [{type_name}] 原始 {len(type_pois)} 条 -> 按评分取Top {len(selected)} 条 "
              f"(最高分 {selected[0].get('rating','N/A') if selected else 'N/A'})")
        all_pois.extend(selected)
    
    # 去重（按poi_id）
    seen = set()
    unique_pois = []
    for poi in all_pois:
        if poi["poi_id"] not in seen:
            seen.add(poi["poi_id"])
            unique_pois.append(poi)
    
    print(f"\n{city} 去重后共 {len(unique_pois)} 条POI")
    return unique_pois


def save_pois(pois: List[Dict], filename: str):
    """保存POI数据为JSON"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"已保存到: {filepath}")


if __name__ == "__main__":
    if AMAP_KEY == "YOUR_AMAP_KEY_HERE":
        print("=" * 60)
        print("⚠️  请先配置高德API Key!")
        print("   1. 访问 https://lbs.amap.com/dev/key/app 申请Key")
        print("   2. 将Key填入本文件 AMAP_KEY 变量，或设置环境变量 AMAP_KEY")
        print("=" * 60)
        exit(1)
    
    for city in CITIES:
        pois = fetch_city_pois(city, max_per_type=30)
        save_pois(pois, f"{city}_pois_amap_raw.json")
