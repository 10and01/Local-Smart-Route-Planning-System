#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图POI数据获取脚本 v2（泛化版）

核心改进：
1. 对每类POI使用多组泛化关键词搜索（非具体景点名），任何城市通用
2. LLM批量评估地标潜力：根据名称判断对游客的推荐价值（替代高德的rating排序）
3. 扩大抓取量后精选，避免高分截断误杀知名景点

用法:
    python scripts/fetch_pois_amap_v2.py
"""

import requests
import json
import time
import os
import sys
import re
from typing import List, Dict, Set
from dotenv import load_dotenv

if sys.platform == "win32":
    import codecs
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path, override=True)

AMAP_KEY = os.getenv("AMAP_KEY", "")
OUTPUT_DIR = "data"

# LLM配置（复用项目现有配置）
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "")

# ==========================================
# 泛化配置（城市无关，任何城市复用同一套）
# ==========================================

CATEGORY_CONFIG: Dict[str, Dict] = {
    "110000": {
        "type_name": "风景名胜",
        "keywords": ["", "景点", "风景区", "名胜", "古迹"],
        "max_per_type": 80,
        "pages_per_kw": 4,
        "use_llm_score": True,   # 风景名胜用LLM评估
    },
    "050000": {
        "type_name": "餐饮服务",
        "keywords": ["", "美食", "特色菜", "老字号", "名店"],
        "max_per_type": 60,
        "pages_per_kw": 3,
        "use_llm_score": False,  # 餐饮用rating即可
    },
    "060000": {
        "type_name": "购物服务",
        "keywords": ["", "商场", "步行街", "夜市", "集市", "老街"],
        "max_per_type": 40,
        "pages_per_kw": 3,
        "use_llm_score": False,
    },
    "080000": {
        "type_name": "体育休闲服务",
        "keywords": ["", "娱乐", "休闲", "体验", "咖啡馆", "茶室"],
        "max_per_type": 40,
        "pages_per_kw": 3,
        "use_llm_score": False,
    },
}

# 低质量名称模式（直接过滤）
LOW_QUALITY_PATTERNS = [
    r".*村村.*", r".*社区.*", r".*居委会.*", r".*警务室.*", r".*卫生室.*",
    r".*幼儿园.*", r".*小学.*", r".*中学.*校区.*", r".*大学.*校区.*",
    r".*停车场.*", r".*加油站.*", r".*收费站.*", r".*公厕.*", r".*垃圾.*",
    r".*招呼站.*", r".*临时.*", r".*建设.*", r".*拆迁.*", r".*待建.*",
]


def _get_llm_client():
    """复用项目已有的LLM client配置"""
    try:
        from openai import OpenAI
        return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    except Exception:
        return None


def _llm_landmark_score_batch(names: List[str], city: str, batch_size: int = 10) -> Dict[str, float]:
    """
    用LLM批量评估POI名称的地标潜力分（1-5分）。
    分批处理避免超时，每批约10个POI，耗时约20-30秒。
    """
    client = _get_llm_client()
    if not client:
        print("    [LLM评估] LLM未配置，跳过")
        return {n: 3.0 for n in names}  # fallback: 默认3分

    scores = {}
    total_batches = (len(names) + batch_size - 1) // batch_size

    for i in range(0, len(names), batch_size):
        batch = names[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"    [LLM评估] 批次 {batch_num}/{total_batches} ({len(batch)}个POI)...", end=" ", flush=True)

        prompt = f'''你是一位资深旅游专家。以下是从高德地图抓取的{city}POI列表。

请判断每个POI对游客（尤其是第一次去{city}的外地游客）的推荐价值，按1-5分打分：
- 5分：全国/省级知名地标，必去景点
- 4分：市内知名景点，值得专程前往
- 3分：区域小众景点，顺路可去
- 2分：本地休闲场所，游客不必去
- 1分：完全不适合旅游推荐

请严格按JSON数组格式输出，只输出JSON：
[{{"name": "...", "score": 1-5}}]

POI列表：
''' + '\n'.join(batch)

        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是资深旅游专家。严格按JSON格式输出，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                timeout=40,
            )
            content = resp.choices[0].message.content
            m = re.search(r'\[.*\]', content, re.DOTALL)
            if m:
                result = json.loads(m.group())
                for item in result:
                    scores[item["name"]] = float(item["score"])
                print(f"OK")
            else:
                print(f"解析失败")
                for n in batch:
                    scores[n] = 3.0
        except Exception as e:
            print(f"失败: {e}")
            for n in batch:
                scores[n] = 3.0

        time.sleep(0.5)

    return scores


def search_poi(city: str, poi_type: str, keywords: str, page: int = 1) -> Dict:
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_KEY,
        "types": poi_type,
        "city": city,
        "citylimit": "true",
        "offset": 25,
        "page": page,
        "extensions": "all",
        "output": "JSON",
    }
    if keywords:
        params["keywords"] = keywords
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data
        else:
            print(f"    API错误: {data.get('info', '未知错误')}")
            return {}
    except Exception as e:
        print(f"    请求失败: {e}")
        return {}


def parse_poi(raw: Dict, type_name: str) -> Dict:
    biz_ext = raw.get("biz_ext", {})
    location_str = raw.get("location", "")
    lng, lat = None, None
    if "," in location_str:
        parts = location_str.split(",")
        try:
            lng = float(parts[0])
            lat = float(parts[1])
        except (ValueError, IndexError):
            pass

    type_full = raw.get("type", "")
    category = type_full.split(";")[0] if type_full else type_name

    photos_raw = raw.get("photos", [])
    photos = []
    if isinstance(photos_raw, list):
        for ph in photos_raw:
            if isinstance(ph, dict) and ph.get("url"):
                photos.append(ph["url"])
            elif isinstance(ph, str):
                photos.append(ph)

    price_val = None
    if biz_ext.get("cost"):
        try:
            price_val = int(float(biz_ext["cost"]))
        except (ValueError, TypeError):
            pass

    rating_val = None
    if biz_ext.get("rating"):
        try:
            rating_val = float(biz_ext["rating"])
        except (ValueError, TypeError):
            pass

    review_count = 0
    if biz_ext.get("num_review"):
        try:
            review_count = int(biz_ext["num_review"])
        except (ValueError, TypeError):
            pass

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
        "location": {"lng": lng, "lat": lat},
        "tel": raw.get("tel", "") or None,
        "rating": rating_val,
        "price": price_val,
        "review_count": review_count,
        "business_hours": raw.get("business", "") or None,
        "suggested_duration": 60,
        "tags": tags,
        "ugc_keywords": [],
        "highlights": None,
        "photos": photos if photos else None,
        "suitable_for": None,
        "source": "amap",
    }


def fetch_city_pois_v2(city: str) -> List[Dict]:
    """
    泛化版POI抓取：多关键词搜索 + LLM批量评估（仅风景名胜）
    """
    all_pois: List[Dict] = []
    seen_ids: Set[str] = set()

    for type_code, config in CATEGORY_CONFIG.items():
        type_name = config["type_name"]
        keywords_list = config["keywords"]
        max_keep = config["max_per_type"]
        pages_per_kw = config["pages_per_kw"]
        use_llm = config["use_llm_score"]

        print(f"\n[{city}] - {type_name}")
        merged_pois: Dict[str, Dict] = {}

        # 第一步：多关键词搜索，合并去重
        for kw in keywords_list:
            kw_label = f'"{kw}"' if kw else "(无关键词)"
            print(f"  关键词 {kw_label}:", end=" ", flush=True)

            for page in range(1, pages_per_kw + 1):
                data = search_poi(city, type_code, kw, page)
                pois = data.get("pois", [])
                if not pois:
                    break

                for raw in pois:
                    parsed = parse_poi(raw, type_name)
                    pid = parsed["poi_id"]
                    if pid and pid not in merged_pois:
                        # 预过滤：名称匹配低质量模式的直接丢弃
                        name = parsed.get("name", "")
                        is_low_quality = any(re.match(p, name) for p in LOW_QUALITY_PATTERNS)
                        if not is_low_quality:
                            merged_pois[pid] = parsed

                print(f"{len(pois)}", end=" ", flush=True)

                if len(pois) < 25:
                    break
                time.sleep(0.25)

            print(f"=> 累计 {len(merged_pois)}")

        type_pois = list(merged_pois.values())

        # 第二步：排序
        if use_llm and len(type_pois) > 0:
            # 风景名胜用LLM批量评估
            names = [p["name"] for p in type_pois]
            llm_scores = _llm_landmark_score_batch(names, city, batch_size=10)
            for p in type_pois:
                p["_llm_score"] = llm_scores.get(p["name"], 3.0)
            type_pois.sort(key=lambda p: (p.get("_llm_score", 0), p.get("rating") or 0), reverse=True)
        else:
            # 其他类型用rating排序（餐饮/购物的rating相对可靠）
            type_pois.sort(key=lambda p: (p.get("rating") or 0, p.get("review_count", 0)), reverse=True)

        selected = type_pois[:max_keep]
        top_score = selected[0].get("_llm_score") if use_llm else selected[0].get("rating")
        print(f"  => 精选 Top {len(selected)} 条 (最高{'LLM' if use_llm else 'rating'}={top_score})")

        for p in selected:
            p.pop("_llm_score", None)
            if p["poi_id"] not in seen_ids:
                seen_ids.add(p["poi_id"])
                all_pois.append(p)

    print(f"\n{'='*50}")
    print(f"{city} 最终: {len(all_pois)} 条POI")
    print(f"{'='*50}")
    return all_pois


def save_pois(pois: List[Dict], filename: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"已保存: {filepath}")


if __name__ == "__main__":
    if not AMAP_KEY or AMAP_KEY == "YOUR_AMAP_KEY_HERE":
        print("请先配置高德API Key! 在 .env 文件中设置 AMAP_KEY")
        exit(1)

    CITIES = ["杭州"]  # 可扩展: "南京", "苏州", "成都", "西安"
    for city in CITIES:
        pois = fetch_city_pois_v2(city)
        save_pois(pois, f"{city}_pois.json")
