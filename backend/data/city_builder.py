# -*- coding: utf-8 -*-
"""
城市数据自动构建模块
支持任意城市的POI数据拉取、丰富化、缓存

使用方式:
    from backend.data.city_builder import get_city_status, start_city_build
    status = get_city_status("北京")
    if status["status"] == "missing":
        start_city_build("北京")
"""

import json
import os
import sys
import time
import threading
from typing import Dict, Optional, List

# 将项目根目录加入sys.path，以便导入scripts下的模块
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 构建状态全局字典: city -> {"status": str, "progress": int, "message": str, "started_at": float}
_build_status: Dict[str, Dict] = {}
_status_lock = threading.Lock()


def _update_status(city: str, status: str, progress: int, message: str):
    """线程安全地更新构建状态"""
    with _status_lock:
        _build_status[city] = {
            "status": status,
            "progress": progress,
            "message": message,
            "started_at": _build_status.get(city, {}).get("started_at", time.time()),
        }


def get_city_status(city: str) -> Dict:
    """获取城市数据构建状态"""
    # 1. 检查是否有LLM丰富化后的最终数据
    final_file = os.path.join(DATA_DIR, f"{city}_pois.json")
    if os.path.exists(final_file):
        return {"status": "done", "progress": 100, "message": "数据已就绪（LLM丰富化完成）"}
    
    # 2. 检查是否有fallback临时数据
    fallback_file = os.path.join(DATA_DIR, f"{city}_pois_fallback.json")
    if os.path.exists(fallback_file):
        # 如果正在构建中，返回实时状态
        with _status_lock:
            if city in _build_status and _build_status[city]["status"] not in ("done", "failed"):
                return dict(_build_status[city])
        return {"status": "fallback_ready", "progress": 50, "message": "fallback数据可用，LLM丰富化待完成"}
    
    # 3. 检查是否有原始高德数据
    raw_file = os.path.join(DATA_DIR, f"{city}_pois_amap_raw.json")
    if os.path.exists(raw_file):
        with _status_lock:
            if city in _build_status and _build_status[city]["status"] not in ("done", "failed"):
                return dict(_build_status[city])
        return {"status": "raw_ready", "progress": 20, "message": "原始数据已拉取，待丰富化"}
    
    # 4. 检查是否有构建状态
    with _status_lock:
        if city in _build_status:
            return dict(_build_status[city])
    
    # 5. 完全缺失
    return {"status": "missing", "progress": 0, "message": "该城市数据不存在，请调用init接口初始化"}


def get_available_cities() -> List[str]:
    """扫描data目录，返回已有数据的城市列表
    过滤无效的城市名（如以_结尾、空字符串、非中文）
    """
    cities = set()
    if os.path.exists(DATA_DIR):
        for fname in os.listdir(DATA_DIR):
            city = None
            if fname.endswith("_pois.json"):
                city = fname[:-10]
            elif fname.endswith("_pois_fallback.json"):
                city = fname[:-19]
            elif fname.endswith("_pois_amap_raw.json"):
                city = fname[:-18]
            
            if city and len(city) > 0 and not city.endswith("_"):
                # 额外校验：城市名应该是中文字符或常见城市英文名
                cities.add(city)
    return sorted(list(cities))


def _build_city_thread(city: str):
    """后台线程：构建城市数据"""
    try:
        _build_city_data(city)
    except Exception as e:
        _update_status(city, "failed", 0, f"构建失败: {str(e)}")
        print(f"[CityBuilder] {city} 构建失败: {e}")


def _build_city_data(city: str):
    """城市数据构建主流程"""
    print(f"[CityBuilder] 开始构建 {city} ...")
    
    # Step 0: 检查是否已就绪
    final_file = os.path.join(DATA_DIR, f"{city}_pois.json")
    if os.path.exists(final_file):
        _update_status(city, "done", 100, "数据已就绪")
        print(f"[CityBuilder] {city} 数据已存在，跳过构建")
        return
    
    # Step 1: 从高德拉取POI
    _update_status(city, "fetching", 10, f"正在从高德API拉取{city}POI数据")
    
    from scripts.fetch_pois_amap import fetch_city_pois, save_pois as amap_save_pois
    
    raw_file = os.path.join(DATA_DIR, f"{city}_pois_amap_raw.json")
    if not os.path.exists(raw_file):
        pois = fetch_city_pois(city, max_per_type=30)
        amap_save_pois(pois, f"{city}_pois_amap_raw.json")
    else:
        with open(raw_file, "r", encoding="utf-8") as f:
            pois = json.load(f)
        print(f"[CityBuilder] {city} 原始数据已存在，跳过拉取")
    
    if not pois:
        _update_status(city, "failed", 0, "从高德API未获取到POI数据")
        return
    
    # Step 2: fallback丰富化（立即可用）
    _update_status(city, "fallback_enriching", 30, "正在生成fallback丰富化数据")
    
    fallback_file = os.path.join(DATA_DIR, f"{city}_pois_fallback.json")
    if not os.path.exists(fallback_file):
        from scripts.enrich_pois_by_llm import get_fallback_enrichment, merge_enrichment
        enriched = []
        for poi in pois:
            enrichment = get_fallback_enrichment(poi)
            enriched.append(merge_enrichment(poi, enrichment))
        with open(fallback_file, "w", encoding="utf-8") as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)
        print(f"[CityBuilder] {city} fallback数据已保存")
    
    # Step 3: 计算距离矩阵
    _update_status(city, "matrix", 50, "正在计算距离矩阵")
    
    matrix_file = os.path.join(DATA_DIR, f"distance_matrix_osrm_foot_{city}.json")
    if not os.path.exists(matrix_file):
        try:
            from scripts.compute_distance_matrix_osrm_table import (
                compute_osrm_table_matrix, save_matrix as matrix_save
            )
            matrix_data = compute_osrm_table_matrix(pois, batch_size=70)
            matrix_save(matrix_data, f"distance_matrix_osrm_foot_{city}.json")
            print(f"[CityBuilder] {city} 距离矩阵已保存")
        except Exception as e:
            print(f"[CityBuilder] {city} 距离矩阵计算失败: {e}，继续执行")
    
    # Step 4: 丰富化（架构调整：粗筛不做LLM丰富化，精筛/规划时按需进行）
    # 城市初始化阶段只用规则生成基础标签，避免对所有POI做昂贵的LLM调用
    _update_status(city, "enriching", 60, "正在生成基础标签...")
    
    if not os.path.exists(final_file):
        import shutil
        from scripts.enrich_pois_by_llm import get_fallback_enrichment
        try:
            # 复制原始数据并附加 fallback 标签（快速，无需LLM）
            with open(raw_file, "r", encoding="utf-8") as f:
                pois = json.load(f)
            for p in pois:
                pid = p.get("poi_id")
                if pid and "enrichment" not in p:
                    p["enrichment"] = get_fallback_enrichment(p)
                    # 将 enrichment 的 tags 合并到 POI 顶层标签
                    if p["enrichment"].get("tags"):
                        existing = set(p.get("tags", []))
                        existing.update(p["enrichment"]["tags"])
                        p["tags"] = list(existing)
            with open(final_file, "w", encoding="utf-8") as f:
                json.dump(pois, f, ensure_ascii=False, indent=2)
            _update_status(city, "done", 100, "数据已就绪")
            print(f"[CityBuilder] {city} 基础标签生成完成，共 {len(pois)} 个POI")
        except Exception as e:
            print(f"[CityBuilder] {city} 标签生成失败: {e}")
            _update_status(city, "fallback_ready", 80, f"标签生成失败: {e}，原始数据可用")
    else:
        _update_status(city, "done", 100, "数据已就绪")


def start_city_build(city: str) -> Dict:
    """
    启动城市数据构建（后台线程）
    返回当前状态
    """
    status = get_city_status(city)
    
    # 如果已完成或正在构建中，直接返回状态
    if status["status"] == "done":
        return status
    
    with _status_lock:
        if city in _build_status and _build_status[city]["status"] in ("fetching", "fallback_enriching", "matrix", "llm_enriching"):
            return dict(_build_status[city])
    
    # 启动后台线程
    _update_status(city, "fetching", 5, f"正在初始化{city}数据构建")
    thread = threading.Thread(target=_build_city_thread, args=(city,), daemon=True)
    thread.start()
    
    return get_city_status(city)
