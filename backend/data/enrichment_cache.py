# -*- coding: utf-8 -*-
"""
POI 丰富化结果增量缓存
按 poi_id 全局缓存 LLM 丰富化结果，跨城市复用
"""

import json
import os
from typing import Dict, List, Optional

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CACHE_FILE = os.path.join(_PROJECT_ROOT, "data", "poi_enrichment_cache.json")

# 内存缓存
_cache_data: Optional[Dict[str, Dict]] = None
_cache_file: str = DEFAULT_CACHE_FILE

# 丰富化字段列表（用于校验缓存条目完整性）
_ENRICHMENT_FIELDS = [
    "tags",
    "ugc_keywords",
    "highlights",
    "suggested_duration",
    "business_hours",
    "sub_category",
    "suitable_for",
]


def _get_cache_file() -> str:
    return _cache_file


def set_cache_file(filepath: str):
    """设置缓存文件路径（用于测试或非默认位置）"""
    global _cache_file, _cache_data
    _cache_file = filepath
    _cache_data = None


def load_cache(force_reload: bool = False) -> Dict[str, Dict]:
    """加载缓存到内存"""
    global _cache_data
    if _cache_data is not None and not force_reload:
        return _cache_data

    filepath = _get_cache_file()
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _cache_data = data
                return _cache_data
        except (json.JSONDecodeError, IOError):
            pass

    _cache_data = {}
    return _cache_data


def save_cache():
    """将内存缓存持久化到文件"""
    global _cache_data
    if _cache_data is None:
        return

    filepath = _get_cache_file()
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(_cache_data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[EnrichmentCache] 保存缓存失败: {e}")


def get_cached_enrichment(poi_id: str, skip_fallback: bool = True) -> Optional[Dict]:
    """
    获取单个 POI 的缓存丰富化结果
    返回 None 表示未缓存、缓存不完整、或来源为fallback（当skip_fallback=True时）
    """
    cache = load_cache()
    entry = cache.get(poi_id)
    if not entry:
        return None

    # 跳过fallback结果
    if skip_fallback and entry.get("_source") == "fallback":
        return None

    # 校验必需字段
    for field in _ENRICHMENT_FIELDS:
        if field not in entry:
            return None

    return dict(entry)


def batch_get_cached(poi_ids: List[str], skip_fallback: bool = True) -> Dict[str, Dict]:
    """批量获取缓存结果，返回 {poi_id: enrichment}"""
    result = {}
    for pid in poi_ids:
        cached = get_cached_enrichment(pid, skip_fallback=skip_fallback)
        if cached:
            result[pid] = cached
    return result


def cache_enrichment(poi_id: str, enrichment: Dict):
    """缓存单个 POI 的丰富化结果（跳过fallback）"""
    if enrichment.get("_source") == "fallback":
        return
    cache = load_cache()
    cache[poi_id] = dict(enrichment)


def batch_cache_enrichments(enrichments: List[Dict]):
    """批量缓存丰富化结果（跳过fallback）"""
    cache = load_cache()
    for e in enrichments:
        if e.get("_source") == "fallback":
            continue
        pid = e.get("poi_id")
        if pid:
            cache[pid] = dict(e)


def get_cache_stats() -> Dict:
    """返回缓存统计"""
    cache = load_cache()
    return {
        "total_cached": len(cache),
        "cache_file": _get_cache_file(),
    }


def clear_memory_cache():
    """清除内存缓存（不影响磁盘文件）"""
    global _cache_data
    _cache_data = None
