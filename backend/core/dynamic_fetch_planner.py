# -*- coding: utf-8 -*-
"""
LLM 动态 POI 抓取规划器
根据用户自然语言查询，调用 LLM 生成精准的高德搜索参数，按需抓取 POI

架构设计：
  1. 城市初始化保留轻量级默认抓取（固定分类，快速完成）
  2. 规划阶段根据用户 raw_query 调用本模块，动态补充精准 POI
  3. 动态抓取结果与缓存城市数据合并，扩大候选池
"""

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config, AMAP_KEY
from backend.models.schemas import POI, Location
from backend.db.models import DynamicFetchCacheDAO

# 导入高德原始数据解析函数
from scripts.fetch_pois_amap import parse_poi


# 中文类型名 → 高德数字代码映射（兼容LLM返回中文的情况）
TYPE_NAME_TO_CODE = {
    "风景名胜": "110000",
    "餐饮服务": "050000",
    "休闲娱乐": "080000",
    "购物服务": "060000",
    "酒店宾馆": "140000",
    "生活服务": "150000",
    "体育休闲服务": "160000",
    "交通设施服务": "200000",
    "科教文化服务": "140200",
    "商务住宅": "120000",
}

SYSTEM_PROMPT = """你是高德地图POI搜索专家。根据用户的自然语言旅行需求，生成精确的高德地图POI搜索参数。

## 高德地图搜索API参数说明
- keywords: 搜索关键词（单个具体关键词，如"西湖"、"火锅"、"山"、"博物馆"）
- types: POI分类代码（可选，用于限制搜索范围）

## 常见POI类型代码
- 110000: 风景名胜
- 050000: 餐饮服务
- 080000: 休闲娱乐
- 060000: 购物服务
- 140000: 酒店宾馆（通常避免）
- 150000: 生活服务
- 160000: 体育休闲服务

## 生成规则
1. 将用户的自然语言需求拆解为2-4个具体搜索查询
2. 每个查询应聚焦于一个主题维度，关键词要精准具体
3. 如果用户提到"爬山/户外/徒步/自然"，keywords必须包含"山"、"森林公园"、"登山步道"、"自然风景区"等
4. 如果用户提到"美食/吃/火锅/辣"，keywords应包含具体菜系或食物类型
5. 如果用户提到"历史/文化/博物馆"，keywords应包含"博物馆"、"古迹"、"历史文化"等
6. 避开用户明确排除的类别（如酒店、宾馆）
7. 返回纯JSON数组，不要markdown代码块，不要解释文字
"""


def _build_fetch_prompt(user_query: str, city: str, avoid: Optional[List[str]]) -> str:
    avoid_str = "、".join(avoid) if avoid else "无"
    return f"""用户要去 {city} 旅行，需求描述："{user_query}"

需要避开的类别/POI：{avoid_str}

请生成2-4个高德地图POI搜索查询，每个查询包含：
- keywords: 搜索关键词（1-2个词，精准具体）
- types: POI类型代码（如果需要限制分类，否则留空字符串）
- reason: 为什么这个查询能召回符合用户需求的POI（简短说明）

输出格式（纯JSON数组）：
[
  {{"keywords": "西湖", "types": "110000", "reason": "用户喜欢自然风光，西湖是标志性景点"}},
  {{"keywords": "火锅", "types": "050000", "reason": "用户提到喜欢吃辣，火锅是首选"}},
  {{"keywords": "山", "types": "110000", "reason": "用户提到喜欢爬山，搜索山景和登山点"}}
]
"""


def _parse_search_queries(content: str) -> List[Dict]:
    """解析LLM返回的搜索查询JSON"""
    if not content:
        return []

    content = content.strip()

    # 去除 markdown 代码块
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            valid = []
            for item in parsed:
                if isinstance(item, dict) and item.get("keywords"):
                    types_val = str(item.get("types", "")).strip()
                    # 兼容LLM返回中文类型名的情况
                    if types_val and not types_val.isdigit():
                        types_val = TYPE_NAME_TO_CODE.get(types_val, types_val)
                    valid.append({
                        "keywords": str(item.get("keywords", "")).strip(),
                        "types": types_val,
                        "reason": str(item.get("reason", "")).strip(),
                    })
            return valid
        elif isinstance(parsed, dict) and "queries" in parsed:
            return _parse_search_queries(json.dumps(parsed["queries"]))
    except json.JSONDecodeError:
        # 尝试提取JSON数组
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return _parse_search_queries(content[start:end + 1])
            except Exception:
                pass

    return []


def _get_default_queries(city: str, user_query: Optional[str] = None) -> List[Dict]:
    """默认搜索查询（LLM失败时回退）"""
    defaults = [
        {"keywords": "风景名胜", "types": "110000", "reason": "默认搜索城市热门景点"},
        {"keywords": "美食", "types": "050000", "reason": "默认搜索城市特色美食"},
        {"keywords": "休闲娱乐", "types": "080000", "reason": "默认搜索休闲娱乐场所"},
    ]
    # 根据用户查询添加针对性查询
    if user_query:
        query_lower = user_query.lower()
        if any(k in query_lower for k in ["山", "爬", "徒步", "户外", "自然", "森林"]):
            defaults.insert(0, {"keywords": "山", "types": "110000", "reason": "用户喜欢爬山/户外"})
        if any(k in query_lower for k in ["吃", "美食", "火锅", "辣", "餐厅"]):
            defaults.insert(0, {"keywords": "火锅", "types": "050000", "reason": "用户喜欢美食"})
        if any(k in query_lower for k in ["博物馆", "历史", "文化", "古迹"]):
            defaults.insert(0, {"keywords": "博物馆", "types": "110000", "reason": "用户喜欢历史文化"})

    return defaults[:4]


def generate_search_queries(
    user_query: str,
    city: str,
    avoid: Optional[List[str]] = None,
    max_queries: int = 4
) -> List[Dict]:
    """
    调用LLM将用户自然语言需求转化为高德搜索参数

    Returns:
        [{"keywords": "...", "types": "...", "reason": "..."}, ...]
    """
    if not check_llm_config():
        print("[DynamicFetch] LLM 配置不完整，使用默认搜索查询")
        return _get_default_queries(city, user_query)

    prompt = _build_fetch_prompt(user_query, city, avoid)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            timeout=30,
        )

        content = response.choices[0].message.content
        queries = _parse_search_queries(content)

        # 限制数量并过滤空关键词
        queries = [q for q in queries[:max_queries] if q["keywords"]]

        print(f"[DynamicFetch] LLM生成 {len(queries)} 个搜索查询: "
              f"{[q['keywords'] for q in queries]}")
        return queries

    except Exception as e:
        print(f"[DynamicFetch] LLM查询生成失败: {e}，使用默认查询")
        return _get_default_queries(city, user_query)


def _search_poi_keywords(
    city: str,
    keywords: str,
    poi_type: Optional[str] = None,
    page: int = 1
) -> Dict:
    """
    高德关键词搜索API（支持 keywords + types 组合）
    文档: https://lbs.amap.com/api/webservice/guide/api/search
    """
    import requests

    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "city": city,
        "citylimit": "true",
        "offset": 25,
        "page": page,
        "extensions": "all",
        "output": "JSON"
    }
    if poi_type:
        params["types"] = poi_type
    if keywords:
        params["keywords"] = keywords

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data
        else:
            print(f"  [AmapAPI] 错误: {data.get('info', '未知错误')}")
            return {}
    except Exception as e:
        print(f"  [AmapAPI] 请求失败: {e}")
        return {}


def _fetch_single_query(
    city: str,
    keywords: str,
    types: str,
    pages: int = 3
) -> List[Dict]:
    """执行单个搜索查询，抓取多页结果"""
    all_pois = []

    for page in range(1, pages + 1):
        try:
            data = _search_poi_keywords(
                city=city,
                keywords=keywords,
                poi_type=types or None,
                page=page
            )
            pois = data.get("pois", [])

            if not pois:
                break

            for raw in pois:
                parsed = parse_poi(raw)
                parsed["source"] = "amap_dynamic"
                parsed["fetch_keywords"] = keywords
                all_pois.append(parsed)

            if len(pois) < 25:
                break

            time.sleep(0.2)  # 礼貌延迟

        except Exception as e:
            print(f"[DynamicFetch] 查询 '{keywords}' 第{page}页失败: {e}")
            break

    return all_pois


def _fetch_one_with_hash(q: Dict, city: str, pages_per_query: int) -> Tuple[str, List[Dict]]:
    """执行单个查询并返回query_hash和结果"""
    query_hash = hashlib.md5(
        f"{city}:{q['keywords']}:{q.get('types','')}".encode()
    ).hexdigest()
    try:
        pois = _fetch_single_query(
            city=city,
            keywords=q["keywords"],
            types=q.get("types", ""),
            pages=pages_per_query
        )
        print(f"[DynamicFetch] 查询 '{q['keywords']}' 获取 {len(pois)} 条POI")
        return query_hash, pois
    except Exception as e:
        print(f"[DynamicFetch] 查询 '{q['keywords']}' 执行失败: {e}")
        return query_hash, []


def execute_dynamic_fetch(
    queries: List[Dict],
    city: str,
    pages_per_query: int = 3
) -> List[Dict]:
    """
    并行执行多个搜索查询（并发3个worker）

    Args:
        queries: [{"keywords": "...", "types": "...", "reason": "..."}, ...]
        city: 城市名
        pages_per_query: 每个查询抓取多少页

    Returns:
        原始POI dict列表（未去重）
    """
    if not queries:
        return []

    all_results = []

    # 高德API并发上限为3，使用3个worker并行执行查询
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_one_with_hash, q, city, pages_per_query): q
            for q in queries
        }
        for future in as_completed(futures):
            query_hash, pois = future.result()
            all_results.extend(pois)

    return all_results


def _deduplicate_and_rank(pois: List[Dict], max_pois: int = 100) -> List[Dict]:
    """去重并按评分排序"""
    seen = set()
    unique = []

    for p in pois:
        pid = p.get("poi_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        unique.append(p)

    # 按评分降序排序，有评分的优先
    unique.sort(key=lambda p: (p.get("rating") or 0.0), reverse=True)

    return unique[:max_pois]


def _dict_to_poi(poi_dict: Dict) -> POI:
    """将原始POI dict转换为POI模型"""
    loc_data = poi_dict.get("location", {})
    location = Location(
        lat=loc_data.get("lat", 0),
        lng=loc_data.get("lng", 0)
    )

    return POI(
        poi_id=poi_dict.get("poi_id", ""),
        name=poi_dict.get("name", ""),
        city=poi_dict.get("city", ""),
        district=poi_dict.get("district"),
        category=poi_dict.get("category", ""),
        sub_category=poi_dict.get("sub_category"),
        address=poi_dict.get("address"),
        location=location,
        tel=poi_dict.get("tel"),
        rating=poi_dict.get("rating"),
        price=poi_dict.get("price"),
        business_hours=poi_dict.get("business_hours"),
        suggested_duration=poi_dict.get("suggested_duration", 60),
        tags=poi_dict.get("tags", []),
        ugc_keywords=poi_dict.get("ugc_keywords", []),
        highlights=poi_dict.get("highlights"),
        photos=poi_dict.get("photos"),
        suitable_for=poi_dict.get("suitable_for"),
        source=poi_dict.get("source", "amap_dynamic")
    )


# 查询生成结果缓存（内存级，进程内共享）
_queries_cache: Dict[str, List[Dict]] = {}


def fetch_city_pois_dynamic(
    city: str,
    user_query: Optional[str] = None,
    avoid: Optional[List[str]] = None,
    max_pois: int = 100,
    pages_per_query: int = 3
) -> List[POI]:
    """
    动态抓取城市POI（根据用户查询按需抓取），支持缓存

    Args:
        city: 城市名
        user_query: 用户自然语言查询（None时使用默认查询）
        avoid: 要避开的POI名称/类别列表
        max_pois: 最终返回的最大POI数
        pages_per_query: 每个查询抓取的页数

    Returns:
        POI模型列表
    """
    import time
    start_time = time.time()

    # Step 1: 生成搜索查询（带缓存）
    query_cache_key = hashlib.md5(
        f"queries:{city}:{user_query or ''}:{','.join(sorted(avoid or []))}".encode()
    ).hexdigest()
    
    queries = _queries_cache.get(query_cache_key)
    if queries is not None:
        print(f"[DynamicFetch] 查询生成缓存命中，{len(queries)} 个查询")
    else:
        queries = generate_search_queries(user_query or "", city, avoid, max_queries=4)
        if queries:
            _queries_cache[query_cache_key] = queries

    if not queries:
        print("[DynamicFetch] 无有效搜索查询，跳过动态抓取")
        return []

    # Step 2: 尝试缓存
    all_cached = []
    uncached_queries = []
    cache_hits = 0
    for q in queries:
        query_hash = hashlib.md5(
            f"{city}:{q['keywords']}:{q.get('types','')}".encode()
        ).hexdigest()
        cached_json = DynamicFetchCacheDAO.get(city, query_hash)
        if cached_json:
            cached_pois = json.loads(cached_json)
            all_cached.extend(cached_pois)
            cache_hits += 1
            print(f"[DynamicFetch] 缓存命中 '{q['keywords']}' ({len(cached_pois)} 条)")
        else:
            uncached_queries.append((q, query_hash))

    total_queries = len(queries)
    print(f"[DynamicFetch] 缓存命中: {cache_hits}/{total_queries}")

    # Step 3: 抓取未缓存的查询
    raw_pois = list(all_cached)
    if uncached_queries:
        fetched_results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(
                    _fetch_one_with_hash, q, city, pages_per_query
                ): (q, query_hash)
                for q, query_hash in uncached_queries
            }
            for future in as_completed(futures):
                (q, query_hash) = futures[future]
                _, pois = future.result()
                fetched_results.append((query_hash, pois))
                raw_pois.extend(pois)

        # 按查询分别缓存结果
        for query_hash, pois in fetched_results:
            if pois:
                DynamicFetchCacheDAO.save(city, query_hash, json.dumps(pois, ensure_ascii=False))

    if not raw_pois:
        print("[DynamicFetch] 动态抓取未获取到POI")
        return []

    # Step 4: 去重排序
    ranked = _deduplicate_and_rank(raw_pois, max_pois)

    # Step 5: 转换为POI模型
    result = [_dict_to_poi(p) for p in ranked]

    elapsed = time.time() - start_time
    print(f"[Perf] DynamicFetch 总耗时: {elapsed:.2f}s (缓存命中 {cache_hits}/{total_queries})")
    print(f"[DynamicFetch] 动态抓取完成: {len(raw_pois)} 原始 → {len(ranked)} 去重 → {len(result)} 最终POI")
    return result
