# -*- coding: utf-8 -*-
"""
POI 价格数据批量补齐脚本
遍历指定城市的 POI，对 price 为 null/0 的调用 LLM 查询真实价格，
结果写回 data/{city}_pois.json

用法:
    python scripts/enrich_poi_prices.py --city 杭州
"""

import os
import sys
import json
import argparse
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME


def load_pois(city: str) -> List[Dict[str, Any]]:
    filepath = f"data/{city}_pois.json"
    if not os.path.exists(filepath):
        print(f"[ERROR] 文件不存在: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pois(city: str, pois: List[Dict[str, Any]]):
    filepath = f"data/{city}_pois.json"
    backup = f"data/{city}_pois_backup.json"
    # 先备份
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            with open(backup, "w", encoding="utf-8") as bf:
                bf.write(f.read())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"[Save] 已写回 {filepath}，备份 {backup}")


def call_llm_for_prices(batch: List[Dict[str, Any]], city: str) -> Dict[str, int]:
    """
    调用 LLM 查询一批 POI 的价格
    返回: {poi_id: price}
    """
    if not LLM_API_KEY or not LLM_MODEL_NAME:
        print("[WARN] LLM 配置不完整，跳过价格查询")
        return {}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    except Exception as e:
        print(f"[ERROR] OpenAI 客户端初始化失败: {e}")
        return {}

    scenic_items = []
    food_items = []
    for p in batch:
        if p.get("category") == "风景名胜":
            scenic_items.append(p)
        elif p.get("category") == "餐饮服务":
            food_items.append(p)

    results = {}

    # 风景名胜：查询门票价格
    if scenic_items:
        prompt_lines = []
        for p in scenic_items:
            prompt_lines.append(f"- {p['name']}（{p.get('address', '地址未知')}）")
        prompt = f"""你是一位熟悉{city}旅游的专家。请查询以下景点的门票价格（人民币元）。
规则：
1. 如果景点免费开放，价格填 0
2. 如果需要门票，填实际票价（如 45、75）
3. 如果是部分区域收费（如西湖大景区免费，但雷峰塔收费），填该景点本身的门票价格
4. 如果不确定，填 0
5. 必须按JSON格式输出，只输出JSON，不要解释

景点列表：
{chr(10).join(prompt_lines)}

输出格式：
{{"景点名称": 价格数字, ...}}
"""
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "旅游价格专家，严格JSON输出，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                timeout=30,
            )
            content = resp.choices[0].message.content
            import re
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                price_map = json.loads(m.group())
                for p in scenic_items:
                    price = price_map.get(p["name"])
                    if isinstance(price, (int, float)) and price >= 0:
                        results[p["poi_id"]] = int(price)
        except Exception as e:
            print(f"[WARN] 风景名胜价格查询失败: {e}")

    # 餐饮：查询人均消费
    if food_items:
        prompt_lines = []
        for p in food_items:
            prompt_lines.append(f"- {p['name']}（{p.get('address', '地址未知')}）")
        prompt = f"""你是一位熟悉{city}美食的本地向导。请查询以下餐厅的人均消费（人民币元）。
规则：
1. 如果是小吃/快餐店，人均约 20-50 元
2. 如果是普通餐厅，人均约 80-150 元
3. 如果是中高端餐厅/酒店餐厅，人均约 200-500 元
4. 如果不确定，根据餐厅名称和地址推断一个合理值
5. 必须按JSON格式输出，只输出JSON，不要解释

餐厅列表：
{chr(10).join(prompt_lines)}

输出格式：
{{"餐厅名称": 价格数字, ...}}
"""
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "本地美食向导，严格JSON输出，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                timeout=30,
            )
            content = resp.choices[0].message.content
            import re
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                price_map = json.loads(m.group())
                for p in food_items:
                    price = price_map.get(p["name"])
                    if isinstance(price, (int, float)) and price >= 0:
                        results[p["poi_id"]] = int(price)
        except Exception as e:
            print(f"[WARN] 餐饮价格查询失败: {e}")

    return results


def enrich_prices(city: str, batch_size: int = 12):
    pois = load_pois(city)
    if not pois:
        return

    # 找出需要补齐的POI
    to_enrich = [p for p in pois if p.get("price") is None or p.get("price") == 0]
    # 只处理风景名胜和餐饮
    to_enrich = [p for p in to_enrich if p.get("category") in ("风景名胜", "餐饮服务")]

    print(f"[Enrich] {city} 共 {len(pois)} 个POI，需要补齐价格: {len(to_enrich)} 个")
    if not to_enrich:
        print("[Enrich] 无需补齐，退出")
        return

    enriched_count = 0
    for i in range(0, len(to_enrich), batch_size):
        batch = to_enrich[i:i + batch_size]
        print(f"[Enrich] 处理批次 {i // batch_size + 1}/{(len(to_enrich) - 1) // batch_size + 1}，{len(batch)} 个POI")
        prices = call_llm_for_prices(batch, city)
        for p in batch:
            pid = p["poi_id"]
            if pid in prices:
                p["price"] = prices[pid]
                enriched_count += 1
                print(f"  {p['name']}: {prices[pid]}元")

    print(f"[Enrich] 完成，共补齐 {enriched_count}/{len(to_enrich)} 个POI 的价格")
    save_pois(city, pois)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="杭州", help="目标城市")
    parser.add_argument("--batch-size", type=int, default=12, help="每批LLM查询数量")
    args = parser.parse_args()
    enrich_prices(args.city, args.batch_size)
