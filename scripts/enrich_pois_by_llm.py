#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM POI 数据丰富化脚本（支持筛选 + 增量缓存）

用法:
    # 基础用法（自动筛选 + 增量缓存）
    python scripts/enrich_pois_by_llm.py --input data/成都_pois_amap_raw.json --output data/成都_pois.json

    # 全量丰富化（不筛选、不用缓存）
    python scripts/enrich_pois_by_llm.py --input data/raw.json --output data/out.json --no-filter --no-use-cache

    # 调整筛选条件
    python scripts/enrich_pois_by_llm.py --input data/raw.json --output data/out.json --max-distance-km 15 --min-rating 4.0
"""

import json
import os
import sys
import time
import argparse
from typing import List, Dict, Optional

from openai import OpenAI

# Windows控制台UTF-8编码修复
if sys.platform == "win32":
    import codecs
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path, override=True)

# 将项目根目录加入 sys.path，以便导入 backend 模块
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# API 配置（从 .env 文件加载，回退到环境变量）
API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "glm-4")

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


SYSTEM_PROMPT = """你是一个专业的旅游 POI 数据标注专家。你的任务是将高德地图 API 返回的原始商户/景点数据，丰富为标准化的结构化信息，用于智能旅行路线规划系统。

你必须严格遵循以下规则：
1. 只输出纯 JSON，不要 markdown 代码块，不要任何解释文字
2. 所有字段必须基于输入信息合理推断，不得编造不存在的事实
3. 营业时间必须标准化为"HH:MM-HH:MM"格式，或"全天开放"
4. 建议时长必须是整数分钟
5. 标签和评价关键词必须贴合该 POI 的真实特征
"""

BATCH_USER_PROMPT_TEMPLATE = """请将以下 {n} 个高德地图 POI 数据分别丰富为标准格式，返回一个 JSON 数组。

## 输入数据
{pois_json}

## 规则
1. tags [array<string>]: 3-5 个精准标签，如拍照出片、亲子友好、情侣浪漫、老字号、网红打卡、夜景绝美、免费、必吃榜、适合散步、交通便利
2. ugc_keywords [array<string>]: 3 个模拟真实用户评价的关键词短语，要有正面也有中性，如"景色超美"、"值得专程去"、"节假日人太多"、"价格偏贵"
3. ugc_sentiment_score [number]: UGC整体情感分，-1.0到+1.0之间。正面评价多给0.5~0.9，中性给0.0~0.3，负面多给-0.5~-0.2
4. ugc_scene_tags [array<string>]: 从用户评价中提炼的场景标签，2-3个，如"适合亲子"、"情侣约会"、"安静独处"、"聚会打卡"
5. ugc_recent_warn [string|null]: 如有近期负面信息（如排队久、修缮中、涨价），写简短提示，否则null
6. highlights [string]: 一句话核心卖点，≤30 字，直接说明"来这里最重要的理由"
7. suggested_duration [integer]: 建议停留分钟数。风景名胜60-180（大型120-240），餐饮45-90，购物60-150，休闲90-240，酒店0
8. business_hours [string]: 标准化营业时间。高德返回"全天开放"→"全天开放"，返回具体时段→直接采用，返回空→按分类推断合理默认值，如"08:00-17:00"
9. sub_category [string]: 二级分类。风景名胜→自然风光/人文古迹/城市地标/寺庙道观，餐饮→地方菜/小吃快餐/西餐/火锅，休闲→主题公园/演出场馆/KTV酒吧，购物→综合商场/特色街区/超市便利店
10. suitable_for [array<string>]: 适合人群标签，从[情侣,亲子,朋友,独自,家庭,老人,商务,学生]中选2-4个

## 输出格式
返回 JSON 数组，每个元素必须包含 poi_id 字段：
[{{"poi_id": "xxx", "tags": [...], "ugc_keywords": [...], "ugc_sentiment_score": 0.7, "ugc_scene_tags": ["适合亲子"], "ugc_recent_warn": null, "highlights": "...", "suggested_duration": 90, "business_hours": "08:00-17:00", "sub_category": "...", "suitable_for": [...]}}]
"""


def build_poi_input(poi: Dict) -> Dict:
    """构建发送给LLM的POI精简输入"""
    result = {
        "poi_id": poi.get("poi_id"),
        "name": poi.get("name"),
        "category": poi.get("category"),
        "address": poi.get("address"),
        "rating": poi.get("rating"),
        "price": poi.get("price"),
        "business_hours_raw": poi.get("business_hours"),
    }
    raw_tags = poi.get("tags", [])
    if raw_tags:
        result["tags_raw"] = raw_tags
    return result


def get_fallback_enrichment(poi: Dict) -> Dict:
    """当LLM调用失败时，使用规则生成fallback丰富化数据"""
    category = poi.get("category", "")
    name = poi.get("name", "")

    if "风景名胜" in category:
        sub_category = "自然风光"
        suggested_duration = 90
        business_hours = poi.get("business_hours") or "08:00-17:00"
        tags = ["风景优美", "拍照出片", "值得一去"]
        suitable_for = ["情侣", "亲子", "朋友"]
    elif "餐饮" in category:
        sub_category = "地方菜"
        suggested_duration = 60
        business_hours = poi.get("business_hours") or "10:00-21:00"
        tags = ["美食推荐", "口味正宗", "人气旺"]
        suitable_for = ["朋友", "家庭", "情侣"]
    elif "购物" in category:
        sub_category = "综合商场"
        suggested_duration = 90
        business_hours = poi.get("business_hours") or "10:00-22:00"
        tags = ["购物天堂", "品牌齐全", "交通便利"]
        suitable_for = ["朋友", "家庭", "情侣"]
    elif "休闲" in category or "娱乐" in category:
        sub_category = "休闲娱乐"
        suggested_duration = 120
        business_hours = poi.get("business_hours") or "10:00-22:00"
        tags = ["放松身心", "娱乐消遣", "适合聚会"]
        suitable_for = ["朋友", "情侣", "家庭"]
    elif "酒店" in category:
        sub_category = "酒店宾馆"
        suggested_duration = 0
        business_hours = "全天开放"
        tags = ["住宿推荐", "服务周到", "环境舒适"]
        suitable_for = ["商务", "家庭", "情侣"]
    else:
        sub_category = "其他"
        suggested_duration = 60
        business_hours = poi.get("business_hours") or "09:00-18:00"
        tags = ["值得一去", "体验不错"]
        suitable_for = ["朋友", "独自"]

    raw_tags = poi.get("tags", [])
    if raw_tags:
        tags = list(dict.fromkeys(raw_tags + tags))[:5]

    return {
        "poi_id": poi.get("poi_id"),
        "tags": tags,
        "ugc_keywords": ["体验不错", "值得打卡", "人气很旺"],
        "ugc_sentiment_score": 0.5,
        "ugc_scene_tags": ["适合拍照", "交通便利"],
        "ugc_recent_warn": None,
        "highlights": f"{name}是值得一去的{sub_category}",
        "suggested_duration": suggested_duration,
        "business_hours": business_hours,
        "sub_category": sub_category,
        "suitable_for": suitable_for,
        "_source": "fallback",
    }


def enrich_batch(batch: List[Dict], max_retries: int = 3) -> List[Dict]:
    """批量丰富化一组POI（调用LLM API，带重试）"""
    if not batch:
        return []

    inputs = [build_poi_input(p) for p in batch]
    prompt = BATCH_USER_PROMPT_TEMPLATE.format(
        n=len(inputs),
        pois_json=json.dumps(inputs, ensure_ascii=False, indent=2)
    )

    client = get_client()
    if not API_KEY:
        print("  ⚠️ LLM_API_KEY 未配置，请检查 .env 文件")
        return [get_fallback_enrichment(p) for p in batch]

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                timeout=120,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("LLM返回空内容")

            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            results = json.loads(content)
            if not isinstance(results, list):
                raise ValueError(f"LLM返回非数组: {type(results)}")

            result_map = {}
            for r in results:
                if isinstance(r, dict) and r.get("poi_id"):
                    result_map[r["poi_id"]] = r

            enriched = []
            for poi in batch:
                pid = poi.get("poi_id")
                if pid and pid in result_map:
                    enriched.append(result_map[pid])
                else:
                    print(f"  ⚠️  batch中未找到结果: {poi.get('name')}({pid})，使用fallback")
                    enriched.append(get_fallback_enrichment(poi))

            return enriched

        except Exception as e:
            err_msg = str(e)
            is_rate_limit = "429" in err_msg or "1302" in err_msg or "速率限制" in err_msg
            if is_rate_limit and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 5s, 10s, 15s
                print(f"  ⚠️ 触发速率限制，等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries - 1})...")
                time.sleep(wait_time)
            else:
                print(f"  ⚠️ LLM batch调用失败: {e}，全部使用fallback")
                return [get_fallback_enrichment(p) for p in batch]

    return [get_fallback_enrichment(p) for p in batch]


def merge_enrichment(poi: Dict, enrichment: Dict) -> Dict:
    """将丰富化字段合并到原始POI数据中"""
    merged = dict(poi)

    for key in ["tags", "ugc_keywords", "ugc_sentiment_score", "ugc_scene_tags",
                "ugc_recent_warn", "highlights", "suggested_duration",
                "business_hours", "sub_category", "suitable_for"]:
        if enrichment.get(key) is not None:
            merged[key] = enrichment[key]

    if merged.get("suggested_duration") is not None:
        try:
            merged["suggested_duration"] = max(5, int(merged["suggested_duration"]))
        except (ValueError, TypeError):
            merged["suggested_duration"] = 60

    if merged.get("rating") is not None:
        try:
            merged["rating"] = float(merged["rating"])
        except (ValueError, TypeError):
            merged["rating"] = None

    if merged.get("price") is not None:
        try:
            merged["price"] = int(float(merged["price"]))
        except (ValueError, TypeError):
            merged["price"] = None

    return merged


def enrich_pois(
    input_file: str,
    output_file: str,
    batch_size: int = 15,
    filter_enabled: bool = True,
    use_cache: bool = True,
    max_distance_km: float = 20.0,
    min_rating: Optional[float] = 3.5,
    cache_file: Optional[str] = None,
    progress_callback: Optional[callable] = None,
):
    """
    主流程：读取POI -> 筛选 -> 查缓存 -> LLM丰富化 -> 保存

    Args:
        input_file: 原始POI JSON文件路径
        output_file: 输出丰富化POI JSON文件路径
        batch_size: LLM每批处理数量（默认15，现代LLM可轻松处理）
        filter_enabled: 是否启用POI筛选
        use_cache: 是否启用增量缓存
        max_distance_km: 筛选条件：距离城市中心最大公里数
        min_rating: 筛选条件：最低评分（None表示不限制）
        cache_file: 缓存文件路径（None使用默认路径）
        progress_callback: 进度回调函数，签名为 (batch_num, total_batches) -> None
    """

    # 1. 读取原始POI
    print(f"读取原始POI数据: {input_file}")
    with open(input_file, "r", encoding="utf-8") as f:
        all_pois = json.load(f)

    if not all_pois:
        print("POI数据为空，退出")
        return

    print(f"共 {len(all_pois)} 个POI")

    # 2. 筛选候选POI（只做LLM丰富化的对象）
    candidate_pois = all_pois
    if filter_enabled:
        from backend.core.poi_filter import filter_pois, get_filter_stats
        candidate_pois = filter_pois(
            all_pois,
            max_distance_km=max_distance_km,
            min_rating=min_rating,
        )
        stats = get_filter_stats(all_pois, candidate_pois)
        print(f"\n📊 POI筛选结果: {stats['filtered']}/{stats['total']} 通过筛选 "
              f"(排除 {stats['excluded']} 条, {stats['exclusion_rate']}%)")

    # 3. 准备丰富化结果映射：poi_id -> enrichment
    enrichment_map: Dict[str, Dict] = {}

    # 对非候选POI，直接使用fallback
    candidate_ids = {p.get("poi_id") for p in candidate_pois}
    for poi in all_pois:
        pid = poi.get("poi_id")
        if pid and pid not in candidate_ids:
            enrichment_map[pid] = get_fallback_enrichment(poi)

    # 4. 增量缓存：分离已缓存和未缓存的候选POI
    cached_count = 0
    uncached_pois = []

    if use_cache:
        from backend.data import enrichment_cache
        if cache_file:
            enrichment_cache.set_cache_file(cache_file)

        for poi in candidate_pois:
            pid = poi.get("poi_id")
            if pid:
                cached = enrichment_cache.get_cached_enrichment(pid)
                if cached:
                    enrichment_map[pid] = cached
                    cached_count += 1
                else:
                    uncached_pois.append(poi)
            else:
                uncached_pois.append(poi)

        print(f"\n💾 缓存状态: {cached_count} 条命中缓存, {len(uncached_pois)} 条需LLM丰富化")
    else:
        uncached_pois = candidate_pois
        print(f"\n缓存已禁用，{len(uncached_pois)} 条需LLM丰富化")

    # 5. 对未缓存的POI调用LLM（batch处理）
    if uncached_pois:
        total_batches = (len(uncached_pois) + batch_size - 1) // batch_size
        llm_results = []

        for i in range(0, len(uncached_pois), batch_size):
            batch_num = i // batch_size + 1
            batch = uncached_pois[i:i + batch_size]
            batch_names = [p.get("name", "unknown") for p in batch]
            print(f"\n🤖 处理 Batch {batch_num}/{total_batches}: {', '.join(batch_names)}")

            if progress_callback:
                progress_callback(batch_num, total_batches)

            t0 = time.time()
            enrichment_results = enrich_batch(batch)
            t1 = time.time()
            print(f"   耗时: {t1 - t0:.1f}s")

            for poi, enrichment in zip(batch, enrichment_results):
                pid = poi.get("poi_id")
                if pid:
                    enrichment_map[pid] = enrichment
                    llm_results.append(enrichment)

            if batch_num < total_batches:
                time.sleep(2)  # 适度延迟，避免速率限制

        # 6. 保存新结果到缓存
        if use_cache and llm_results:
            from backend.data import enrichment_cache
            enrichment_cache.batch_cache_enrichments(llm_results)
            enrichment_cache.save_cache()
            print(f"\n💾 已将 {len(llm_results)} 条新丰富化结果写入缓存")

    # 7. 合并所有POI
    all_enriched = []
    for poi in all_pois:
        pid = poi.get("poi_id")
        enrichment = enrichment_map.get(pid)
        if enrichment:
            merged = merge_enrichment(poi, enrichment)
        else:
            merged = merge_enrichment(poi, get_fallback_enrichment(poi))
        all_enriched.append(merged)

    # 8. 保存结果
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_enriched, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 丰富化完成！已保存 {len(all_enriched)} 个POI到: {output_file}")

    # 9. 统计
    categories = {}
    sub_categories = {}
    for p in all_enriched:
        cat = p.get("category", "未知")
        sub = p.get("sub_category", "未知")
        categories[cat] = categories.get(cat, 0) + 1
        sub_categories[sub] = sub_categories.get(sub, 0) + 1

    print(f"\n分类统计:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"\n二级分类统计:")
    for sub, count in sorted(sub_categories.items(), key=lambda x: -x[1]):
        print(f"  {sub}: {count}")


def main():
    parser = argparse.ArgumentParser(description="LLM丰富化POI数据（支持筛选+增量缓存）")
    parser.add_argument("--input", default="data/杭州_pois_amap_raw.json", help="输入的原始POI JSON文件")
    parser.add_argument("--output", default="data/杭州_pois.json", help="输出的丰富化POI JSON文件")
    parser.add_argument("--batch-size", type=int, default=5, help="每批处理的POI数量（建议1-5）")

    parser.add_argument("--filter", action="store_true", default=True, help="启用POI筛选（默认启用）")
    parser.add_argument("--no-filter", action="store_true", help="禁用POI筛选")
    parser.add_argument("--max-distance-km", type=float, default=20.0, help="筛选：距离城市中心最大公里数")
    parser.add_argument("--min-rating", type=float, default=3.5, help="筛选：最低评分（设为0禁用）")

    parser.add_argument("--use-cache", action="store_true", default=True, help="启用增量缓存（默认启用）")
    parser.add_argument("--no-use-cache", action="store_true", help="禁用增量缓存")
    parser.add_argument("--cache-file", default=None, help="缓存文件路径（默认 data/poi_enrichment_cache.json）")

    args = parser.parse_args()

    filter_enabled = args.filter and not args.no_filter
    use_cache = args.use_cache and not args.no_use_cache
    min_rating = args.min_rating if args.min_rating > 0 else None

    enrich_pois(
        input_file=args.input,
        output_file=args.output,
        batch_size=args.batch_size,
        filter_enabled=filter_enabled,
        use_cache=use_cache,
        max_distance_km=args.max_distance_km,
        min_rating=min_rating,
        cache_file=args.cache_file,
    )


if __name__ == "__main__":
    main()
