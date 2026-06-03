#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenStreetMap POI数据获取脚本（完全免费，无需Key）
通过Overpass API查询OSM数据库
用法: python scripts/fetch_pois_osm.py
"""

import requests
import json
import os
from typing import List, Dict

OUTPUT_DIR = "data"

# OSM标签映射：我们要的POI类型 → OSM标签
OSM_TAGS = {
    "景点": ['["tourism"="attraction"]', '["tourism"="viewpoint"]'],
    "餐厅": ['["amenity"="restaurant"]', '["amenity"="fast_food"]'],
    "咖啡厅": ['["amenity"="cafe"]'],
    "酒吧": ['["amenity"="bar"]'],
    "公园": ['["leisure"="park"]'],
    "博物馆": ['["tourism"="museum"]'],
    "商场": ['["shop"="mall"]', '["shop"="department_store"]'],
}

# Overpass API公共实例
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]


def build_query(city: str, tags: List[str]) -> str:
    """
    构建Overpass QL查询语句
    """
    tag_clauses = "\n".join(f"      node{t}(area.searchArea);" for t in tags)
    
    query = f"""
[out:json][timeout:30];
area[name="{city}"]->.searchArea;
(
{tag_clauses}
);
out body;
"""
    return query


def query_overpass(city: str, category: str, tags: List[str]) -> List[Dict]:
    """
    调用Overpass API获取POI
    """
    query = build_query(city, tags)
    
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint,
                data={"data": query},
                timeout=35
            )
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                
                pois = []
                for elem in elements:
                    tags_data = elem.get("tags", {})
                    name = tags_data.get("name:zh") or tags_data.get("name", "未命名")
                    
                    # 跳过没有中文名的POI（可能是数据不完整）
                    if name == "未命名":
                        continue
                    
                    pois.append({
                        "poi_id": f"osm_{elem.get('id')}",
                        "name": name,
                        "city": city,
                        "category": category,
                        "location": {
                            "lng": elem.get("lon"),
                            "lat": elem.get("lat"),
                        },
                        "address": tags_data.get("addr:street", ""),
                        "tag": [category],
                        "source": "osm",
                        "osm_tags": {k: v for k, v in tags_data.items() if k.startswith(("amenity", "tourism", "leisure", "shop"))}
                    })
                
                print(f"  [{category}] 从 {endpoint.split('/')[2]} 获取 {len(pois)} 条")
                return pois
            
        except Exception as e:
            print(f"  {endpoint} 失败: {e}")
            continue
    
    print(f"  [{category}] 所有节点均失败")
    return []


def fetch_city_pois(city: str, max_per_category: int = 20) -> List[Dict]:
    """
    获取一个城市的OSM POI数据
    """
    all_pois = []
    
    for category, tags in OSM_TAGS.items():
        print(f"正在获取 [{city}] - [{category}] ...")
        pois = query_overpass(city, category, tags)
        
        # 限制数量
        pois = pois[:max_per_category]
        print(f"  保留 {len(pois)} 条")
        all_pois.extend(pois)
    
    # 去重
    seen = set()
    unique = []
    for p in all_pois:
        key = (p["name"], p.get("location", {}).get("lat"))
        if key not in seen:
            seen.add(key)
            unique.append(p)
    
    print(f"\n{city} 去重后共 {len(unique)} 条POI")
    return unique


def save_pois(pois: List[Dict], filename: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"已保存到: {filepath}")


if __name__ == "__main__":
    city = "杭州"
    pois = fetch_city_pois(city, max_per_category=15)
    save_pois(pois, f"{city}_pois_osm.json")
