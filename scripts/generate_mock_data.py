#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock POI数据生成脚本
当无法获取真实数据时，用此脚本生成高质量的模拟数据用于Hackthon演示
用法: python scripts/generate_mock_data.py
"""

import json
import random
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = "data"

# 杭州市中心范围（西湖周边）
HANGZHOU_CENTER = {"lat": 30.2596, "lng": 120.1460}

# 模拟POI数据库：真实存在的杭州热门POI
HANGZHOU_POIS = [
    # 景点类
    {"name": "西湖断桥残雪", "category": "风景名胜", "tags": ["拍照", "浪漫", "免费", "标志性"], 
     "lat": 30.2596, "lng": 120.1460, "rating": 4.8, "price": 0, "duration": 60},
    {"name": "雷峰塔", "category": "风景名胜", "tags": ["历史文化", "登高", "西湖十景"],
     "lat": 30.2310, "lng": 120.1485, "rating": 4.6, "price": 40, "duration": 90},
    {"name": "灵隐寺", "category": "风景名胜", "tags": ["寺庙", "祈福", "古建筑", "人气旺"],
     "lat": 30.2405, "lng": 120.0980, "rating": 4.7, "price": 75, "duration": 120},
    {"name": "三潭印月", "category": "风景名胜", "tags": ["西湖", "游船", "拍照", "人民币背景"],
     "lat": 30.2390, "lng": 120.1410, "rating": 4.5, "price": 55, "duration": 90},
    {"name": "苏堤春晓", "category": "风景名胜", "tags": ["漫步", "自然风光", "免费", "晨跑"],
     "lat": 30.2450, "lng": 120.1350, "rating": 4.7, "price": 0, "duration": 60},
    {"name": "河坊街", "category": "风景名胜", "tags": ["古街", "小吃", "购物", "夜景"],
     "lat": 30.2410, "lng": 120.1680, "rating": 4.3, "price": 0, "duration": 120},
    {"name": "宋城", "category": "休闲娱乐", "tags": ["演出", "穿越", "主题公园", "千古情"],
     "lat": 30.1850, "lng": 120.1050, "rating": 4.5, "price": 320, "duration": 240},
    {"name": "西溪湿地", "category": "风景名胜", "tags": ["自然", "乘船", "宁静", "拍照"],
     "lat": 30.2700, "lng": 120.0650, "rating": 4.6, "price": 80, "duration": 180},
    
    # 美食类
    {"name": "楼外楼", "category": "餐饮服务", "tags": ["杭帮菜", "西湖醋鱼", "老字号", "景观位"],
     "lat": 30.2580, "lng": 120.1400, "rating": 4.2, "price": 200, "duration": 90},
    {"name": "知味观", "category": "餐饮服务", "tags": ["小笼包", "点心", "老字号", "平价"],
     "lat": 30.2550, "lng": 120.1650, "rating": 4.4, "price": 80, "duration": 60},
    {"name": "外婆家", "category": "餐饮服务", "tags": ["杭帮菜", "排队王", "性价比高", "家庭"],
     "lat": 30.2680, "lng": 120.1550, "rating": 4.5, "price": 90, "duration": 75},
    {"name": "绿茶餐厅", "category": "餐饮服务", "tags": ["创意菜", "环境好", "拍照", "年轻人"],
     "lat": 30.2720, "lng": 120.1600, "rating": 4.3, "price": 100, "duration": 75},
    {"name": "新白鹿餐厅", "category": "餐饮服务", "tags": ["杭帮菜", "便宜", "排队", "必吃"],
     "lat": 30.2640, "lng": 120.1580, "rating": 4.4, "price": 70, "duration": 75},
    {"name": "老头儿油爆虾", "category": "餐饮服务", "tags": ["油爆虾", "地道", "老店", "夜宵"],
     "lat": 30.2500, "lng": 120.1700, "rating": 4.3, "price": 110, "duration": 60},
    
    # 咖啡厅/下午茶
    {"name": "星巴克(西湖天地店)", "category": "咖啡厅", "tags": ["湖景", "下午茶", "拍照", "休息"],
     "lat": 30.2560, "lng": 120.1420, "rating": 4.5, "price": 50, "duration": 45},
    {"name": "% Arabica(杭州店)", "category": "咖啡厅", "tags": ["网红", "拿铁", "极简风", "拍照"],
     "lat": 30.2700, "lng": 120.1500, "rating": 4.4, "price": 45, "duration": 40},
    {"name": "M Stand", "category": "咖啡厅", "tags": ["鲜椰冰咖", "设计感", "商务", "下午茶"],
     "lat": 30.2650, "lng": 120.1620, "rating": 4.3, "price": 40, "duration": 40},
    
    # 购物/休闲
    {"name": "湖滨银泰in77", "category": "购物服务", "tags": ["商场", "潮牌", "美食", "地铁直达"],
     "lat": 30.2555, "lng": 120.1640, "rating": 4.5, "price": 0, "duration": 120},
    {"name": "武林夜市", "category": "购物服务", "tags": ["夜市", "小吃", "手作", "热闹"],
     "lat": 30.2750, "lng": 120.1650, "rating": 4.2, "price": 0, "duration": 90},
    {"name": "小河直街", "category": "风景名胜", "tags": ["文艺", "古街", "拍照", "下午茶"],
     "lat": 30.2950, "lng": 120.1550, "rating": 4.4, "price": 0, "duration": 90},
]

# UGC关键词库（用于生成每个POI的用户评价标签）
UGC_KEYWORDS = {
    "景点": ["景色美", "值得去", "人多", "拍照出片", "有历史", "空气好", "门票贵", "建议早去"],
    "餐饮": ["味道好", "排队久", "性价比高", "服务一般", "分量足", "环境好", "必点菜", "提前预约"],
    "咖啡厅": ["咖啡香", "适合办公", "拍照好看", "座位少", "价格偏贵", "氛围好"],
    "购物": ["品牌多", "好逛", "停车难", "吃饭方便", "周末人多"],
}


def enrich_poi(poi: dict, index: int) -> dict:
    """
    为POI添加额外字段，使其更像真实数据
    """
    # 营业时间模拟
    business_hours_map = {
        "风景名胜": "全天开放" if poi["price"] == 0 else "08:00-17:00",
        "餐饮服务": "10:30-21:00",
        "咖啡厅": "08:00-22:00",
        "购物服务": "10:00-22:00",
        "休闲娱乐": "09:00-21:00",
    }
    
    # 根据分类选UGC关键词
    category_type = "景点"
    if poi["category"] == "餐饮服务":
        category_type = "餐饮"
    elif poi["category"] == "咖啡厅":
        category_type = "咖啡厅"
    elif poi["category"] == "购物服务":
        category_type = "购物"
    
    keywords = UGC_KEYWORDS.get(category_type, [])
    selected_keywords = random.sample(keywords, min(3, len(keywords)))
    
    # 添加一些随机扰动，让数据更自然
    rating = round(min(5.0, max(3.5, poi["rating"] + random.uniform(-0.2, 0.2))), 1)
    
    return {
        "poi_id": f"mock_hangzhou_{index:03d}",
        "name": poi["name"],
        "city": "杭州",
        "district": random.choice(["西湖区", "上城区", "拱墅区", "滨江区"]),
        "category": poi["category"],
        "address": f"杭州市{random.choice(['西湖区', '上城区', '拱墅区'])}某某路{random.randint(1, 999)}号",
        "location": {
            "lat": poi["lat"] + random.uniform(-0.001, 0.001),  # 微小偏移
            "lng": poi["lng"] + random.uniform(-0.001, 0.001),
        },
        "tel": f"0571-{random.randint(80000000, 89999999)}",
        "rating": rating,
        "price": poi["price"],
        "business_hours": business_hours_map.get(poi["category"], "09:00-18:00"),
        "suggested_duration": poi["duration"],
        "tags": poi["tags"],
        "ugc_keywords": selected_keywords,
        "highlights": f"{poi['tags'][0]}是这里的最大特色",
        "source": "mock"
    }


def generate_mock_pois() -> list:
    """生成完整Mock数据集"""
    pois = []
    for i, raw in enumerate(HANGZHOU_POIS):
        enriched = enrich_poi(raw, i)
        pois.append(enriched)
    return pois


def main():
    print("=" * 50)
    print("生成杭州Mock POI数据")
    print("=" * 50)
    
    pois = generate_mock_pois()
    
    # 统计
    categories = {}
    for p in pois:
        cat = p["category"]
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"\n共生成 {len(pois)} 个POI:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}个")
    
    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "杭州_pois_mock.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    
    print(f"\n[OK] 已保存到: {filepath}")
    
    # 打印前3条示例
    print("\n数据示例（前3条）:")
    for p in pois[:3]:
        print(f"  -> {p['name']} | {p['category']} | 评分:{p['rating']} | 标签:{','.join(p['tags'])}")


if __name__ == "__main__":
    main()
