#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
距离矩阵计算脚本
支持两种模式：
  1. Haversine公式（纯数学，零API调用，快速估算）
  2. OSRM（开源路由引擎，获取真实步行/驾车距离）
用法:
    python scripts/compute_distance_matrix.py --input data/杭州_pois.json --method haversine
    python scripts/compute_distance_matrix.py --input data/杭州_pois.json --method osrm
"""

import json
import math
import requests
import argparse
import os
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

OUTPUT_DIR = "data"


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine公式计算两点间直线距离（米）
    优点：完全免费，无需网络，计算极快
    缺点：是直线距离，非实际路径
    Hackthon技巧：直线距离 × 1.3 ≈ 实际步行距离
    """
    R = 6371000  # 地球半径（米）
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def osrm_distance(coord1: Tuple[float, float], coord2: Tuple[float, float], 
                  profile: str = "foot") -> Tuple[float, float]:
    """
    调用OSRM公共服务器计算真实路线距离
    coord: (lat, lng)
    profile: foot / bike / car
    返回: (距离米, 时间秒)
    """
    # OSRM坐标顺序是 lng,lat
    url = (f"http://router.project-osrm.org/route/v1/{profile}/"
           f"{coord1[1]},{coord1[0]};{coord2[1]},{coord2[0]}")
    
    try:
        resp = requests.get(url, params={"overview": "false"}, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok":
            route = data["routes"][0]
            return route["distance"], route["duration"]
        return None, None
    except Exception as e:
        return None, None


def load_pois(filepath: str) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_haversine_matrix(pois: List[Dict]) -> Dict:
    """
    用Haversine公式计算距离矩阵
    返回: {
        "poi_ids": [id1, id2, ...],
        "distance_matrix": [[0, d12, ...], [d21, 0, ...], ...],
        "unit": "meters"
    }
    """
    n = len(pois)
    poi_ids = [p.get("poi_id") or p.get("name") for p in pois]
    matrix = [[0.0] * n for _ in range(n)]
    
    for i in range(n):
        loc_i = pois[i].get("location", {})
        lat1, lng1 = loc_i.get("lat"), loc_i.get("lng")
        if lat1 is None or lng1 is None:
            continue
        
        for j in range(i + 1, n):
            loc_j = pois[j].get("location", {})
            lat2, lng2 = loc_j.get("lat"), loc_j.get("lng")
            if lat2 is None or lng2 is None:
                continue
            
            dist = haversine_distance(lat1, lng1, lat2, lng2)
            # 估算实际距离 = 直线 × 1.3
            estimated = dist * 1.3
            matrix[i][j] = round(estimated, 1)
            matrix[j][i] = round(estimated, 1)
    
    return {
        "poi_ids": poi_ids,
        "distance_matrix": matrix,
        "unit": "meters",
        "method": "haversine_estimated"
    }


def compute_osrm_matrix(pois: List[Dict], profile: str = "foot") -> Dict:
    """
    用OSRM计算真实距离矩阵
    注意：OSRM公共服务器建议不要一次性发太多请求
    """
    n = len(pois)
    poi_ids = [p.get("poi_id") or p.get("name") for p in pois]
    dist_matrix = [[0.0] * n for _ in range(n)]
    time_matrix = [[0.0] * n for _ in range(n)]
    
    coords = []
    for p in pois:
        loc = p.get("location", {})
        coords.append((loc.get("lat"), loc.get("lng")))
    
    total_pairs = n * (n - 1) // 2
    completed = 0
    
    print(f"开始计算 {n}×{n} 距离矩阵，共 {total_pairs} 对...")
    
    for i in range(n):
        for j in range(i + 1, n):
            dist, duration = osrm_distance(coords[i], coords[j], profile)
            
            if dist is not None:
                dist_matrix[i][j] = round(dist, 1)
                dist_matrix[j][i] = round(dist, 1)
                time_matrix[i][j] = round(duration, 1)
                time_matrix[j][i] = round(duration, 1)
            else:
                # OSRM失败时回退到Haversine
                dist = haversine_distance(coords[i][0], coords[i][1], 
                                          coords[j][0], coords[j][1]) * 1.3
                dist_matrix[i][j] = round(dist, 1)
                dist_matrix[j][i] = round(dist, 1)
                time_matrix[i][j] = round(dist / 1.2, 1)  # 假设步行1.2m/s
                time_matrix[j][i] = round(dist / 1.2, 1)
            
            completed += 1
            if completed % 10 == 0:
                print(f"  进度: {completed}/{total_pairs}")
            
            time.sleep(0.5)  # 礼貌延迟，避免请求过快
    
    return {
        "poi_ids": poi_ids,
        "distance_matrix": dist_matrix,
        "duration_matrix": time_matrix,
        "unit": "meters",
        "time_unit": "seconds",
        "method": f"osrm_{profile}",
        "profile": profile
    }


def save_matrix(matrix_data: Dict, output_path: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, output_path)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(matrix_data, f, ensure_ascii=False, indent=2)
    print(f"距离矩阵已保存: {filepath}")
    
    # 打印统计信息
    n = len(matrix_data["poi_ids"])
    dist_mat = matrix_data.get("distance_matrix", [])
    
    # 计算平均距离（排除对角线0）
    total_dist = 0
    count = 0
    for i in range(n):
        for j in range(n):
            if i != j and dist_mat[i][j] > 0:
                total_dist += dist_mat[i][j]
                count += 1
    
    if count > 0:
        avg_dist = total_dist / count
        print(f"  POI数量: {n}")
        print(f"  平均距离: {avg_dist:.0f} 米")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="计算POI距离矩阵")
    parser.add_argument("--input", required=True, help="POI JSON文件路径")
    parser.add_argument("--method", choices=["haversine", "osrm"], default="haversine",
                        help="计算方法")
    parser.add_argument("--profile", choices=["foot", "bike", "car"], default="foot",
                        help="OSRM出行方式（仅osrm模式有效）")
    args = parser.parse_args()
    
    print(f"加载POI数据: {args.input}")
    pois = load_pois(args.input)
    print(f"共 {len(pois)} 个POI")
    
    if args.method == "haversine":
        print("使用Haversine公式计算...")
        matrix_data = compute_haversine_matrix(pois)
        save_matrix(matrix_data, "distance_matrix_haversine.json")
    else:
        print(f"使用OSRM ({args.profile}模式) 计算...")
        matrix_data = compute_osrm_matrix(pois, args.profile)
        save_matrix(matrix_data, f"distance_matrix_osrm_{args.profile}.json")
