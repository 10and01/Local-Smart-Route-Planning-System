#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 OSRM Table API 批量计算距离矩阵
大幅减少对公共OSRM服务器的请求次数（6个请求 vs 2万+个请求）

用法:
    python scripts/compute_distance_matrix_osrm_table.py --input data/杭州_pois_mock.json
"""

import json
import math
import requests
import argparse
import os
import time
import sys
from typing import List, Dict, Tuple

# Windows控制台UTF-8编码修复
if sys.platform == "win32":
    import codecs
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

OUTPUT_DIR = "data"
OSRM_BASE_URL = "http://router.project-osrm.org/table/v1/foot"
# OSRM坐标顺序: lng,lat


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def osrm_table(coords: List[Tuple[float, float]], 
               sources: List[int], 
               destinations: List[int]) -> Tuple[List[List[float]], List[List[float]]]:
    """
    调用OSRM Table API计算批量距离/时间矩阵
    返回: (distances_matrix, durations_matrix)，单位分别为米和秒
    """
    coord_str = ";".join(f"{lng},{lat}" for lat, lng in coords)
    sources_str = ";".join(str(s) for s in sources)
    destinations_str = ";".join(str(d) for d in destinations)
    
    url = f"{OSRM_BASE_URL}/{coord_str}"
    params = {
        "sources": sources_str,
        "destinations": destinations_str,
        "annotations": "distance,duration"
    }
    
    try:
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        if data.get("code") == "Ok":
            return data.get("distances", []), data.get("durations", [])
    except Exception as e:
        print(f"  OSRM请求失败: {e}")
    
    return [], []


def load_pois(filepath: str) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_osrm_table_matrix(pois: List[Dict], batch_size: int = 70) -> Dict:
    """
    使用OSRM Table API分批计算完整距离矩阵
    """
    n = len(pois)
    poi_ids = [p.get("poi_id") or p.get("name") for p in pois]
    
    coords = []
    for p in pois:
        loc = p.get("location", {})
        coords.append((loc.get("lat"), loc.get("lng")))
    
    # 初始化矩阵
    dist_matrix = [[0.0] * n for _ in range(n)]
    time_matrix = [[0.0] * n for _ in range(n)]
    
    # 分批
    batches = []
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batches.append((start, end))
    
    print(f"共 {n} 个POI，分为 {len(batches)} 批，每批最多 {batch_size} 个")
    
    request_count = 0
    
    # 1. 计算每个batch内部的矩阵
    for batch_idx, (start, end) in enumerate(batches):
        print(f"\n计算 Batch {batch_idx} 内部矩阵 [{start}:{end}]...")
        batch_coords = coords[start:end]
        local_n = end - start
        
        # 单点batch无需调用OSRM
        if local_n <= 1:
            print(f"  跳过: 只有 {local_n} 个点")
            continue
        
        sources = list(range(local_n))
        destinations = list(range(local_n))
        
        dists, durs = osrm_table(batch_coords, sources, destinations)
        request_count += 1
        time.sleep(1.0)  # 礼貌延迟
        
        if dists and len(dists) == local_n and len(dists[0]) == local_n:
            valid = True
            for i in range(local_n):
                for j in range(local_n):
                    if i != j:
                        if dists[i][j] is None:
                            valid = False
                            break
                        dist_matrix[start + i][start + j] = round(dists[i][j], 1)
                        time_matrix[start + i][start + j] = round(durs[i][j], 1)
                if not valid:
                    break
            if valid:
                print(f"  成功: {local_n}x{local_n} 子矩阵")
            else:
                print(f"  部分数据缺失，回退到Haversine估算")
                for i in range(local_n):
                    for j in range(local_n):
                        if i != j:
                            lat1, lng1 = coords[start + i]
                            lat2, lng2 = coords[start + j]
                            d = haversine_distance(lat1, lng1, lat2, lng2) * 1.3
                            dist_matrix[start + i][start + j] = round(d, 1)
                            time_matrix[start + i][start + j] = round(d / 1.2, 1)
        else:
            print(f"  失败，回退到Haversine估算")
            for i in range(local_n):
                for j in range(local_n):
                    if i != j:
                        lat1, lng1 = coords[start + i]
                        lat2, lng2 = coords[start + j]
                        d = haversine_distance(lat1, lng1, lat2, lng2) * 1.3
                        dist_matrix[start + i][start + j] = round(d, 1)
                        time_matrix[start + i][start + j] = round(d / 1.2, 1)
    
    # 2. 计算batch之间的交叉矩阵
    for i in range(len(batches)):
        for j in range(i + 1, len(batches)):
            start_i, end_i = batches[i]
            start_j, end_j = batches[j]
            print(f"\n计算交叉矩阵 Batch {i} <-> Batch {j} [{start_i}:{end_i}] x [{start_j}:{end_j}]...")
            
            # 合并坐标: batch_i 在前，batch_j 在后
            merged_coords = coords[start_i:end_i] + coords[start_j:end_j]
            n_i = end_i - start_i
            n_j = end_j - start_j
            
            # sources = batch_i indices, destinations = batch_j indices
            sources = list(range(n_i))
            destinations = list(range(n_i, n_i + n_j))
            
            dists, durs = osrm_table(merged_coords, sources, destinations)
            request_count += 1
            time.sleep(1.0)
            
            if dists:
                for ii in range(n_i):
                    for jj in range(n_j):
                        if dists[ii][jj] is not None:
                            # i -> j
                            dist_matrix[start_i + ii][start_j + jj] = round(dists[ii][jj], 1)
                            time_matrix[start_i + ii][start_j + jj] = round(durs[ii][jj], 1)
                            # j -> i (OSRM table可能返回None或实际值，但通常对称)
                            # 为安全起见，反向也用相同值
                            dist_matrix[start_j + jj][start_i + ii] = round(dists[ii][jj], 1)
                            time_matrix[start_j + jj][start_i + ii] = round(durs[ii][jj], 1)
                print(f"  成功: {n_i}x{n_j} 交叉矩阵")
            else:
                print(f"  失败，回退到Haversine估算")
                for ii in range(n_i):
                    for jj in range(n_j):
                        lat1, lng1 = coords[start_i + ii]
                        lat2, lng2 = coords[start_j + jj]
                        d = haversine_distance(lat1, lng1, lat2, lng2) * 1.3
                        dist_matrix[start_i + ii][start_j + jj] = round(d, 1)
                        time_matrix[start_i + ii][start_j + jj] = round(d / 1.2, 1)
                        dist_matrix[start_j + jj][start_i + ii] = round(d, 1)
                        time_matrix[start_j + jj][start_i + ii] = round(d / 1.2, 1)
    
    print(f"\n总共发送 {request_count} 个OSRM Table请求")
    
    # 【关键修复】校验并修正不合理的duration
    # OSRM demo服务器有时会返回明显过快的步行时间（速度>9km/h）
    corrected_count = 0
    for i in range(n):
        for j in range(n):
            if i != j:
                dist = dist_matrix[i][j]
                dur = time_matrix[i][j]
                if dist > 0 and dur > 0:
                    speed = dist / dur  # m/s
                    if speed > 2.5:  # 步行速度不应超过9km/h
                        # 重新估算：步行速度1.2m/s（约4.3km/h）
                        new_dur = dist / 1.2
                        time_matrix[i][j] = round(new_dur, 1)
                        corrected_count += 1
                elif dist > 0 and dur <= 0:
                    # 有距离但无时间，补充估算
                    time_matrix[i][j] = round(dist / 1.2, 1)
    
    if corrected_count > 0:
        print(f"修正了 {corrected_count} 个不合理的步行耗时（OSRM返回速度过快）")
    
    # 统计
    total_dist = 0
    count = 0
    for i in range(n):
        for j in range(n):
            if i != j and dist_matrix[i][j] > 0:
                total_dist += dist_matrix[i][j]
                count += 1
    
    if count > 0:
        avg_dist = total_dist / count
        print(f"平均距离: {avg_dist:.0f} 米")
    
    return {
        "poi_ids": poi_ids,
        "distance_matrix": dist_matrix,
        "duration_matrix": time_matrix,
        "unit": "meters",
        "time_unit": "seconds",
        "method": "osrm_table_foot",
        "profile": "foot"
    }


def save_matrix(matrix_data: Dict, output_path: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, output_path)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(matrix_data, f, ensure_ascii=False, indent=2)
    print(f"\n距离矩阵已保存: {filepath}")
    n = len(matrix_data["poi_ids"])
    print(f"  POI数量: {n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用OSRM Table API计算POI距离矩阵")
    parser.add_argument("--input", default="data/杭州_pois_mock.json", help="POI JSON文件路径")
    parser.add_argument("--batch-size", type=int, default=70, help="每批POI数量（OSRM限制约100）")
    args = parser.parse_args()
    
    print(f"加载POI数据: {args.input}")
    pois = load_pois(args.input)
    print(f"共 {len(pois)} 个POI")
    
    print("使用OSRM Table API计算...")
    matrix_data = compute_osrm_table_matrix(pois, batch_size=args.batch_size)
    save_matrix(matrix_data, "distance_matrix_osrm_foot.json")
