# -*- coding: utf-8 -*-
"""
偏好量化与匹配计算
负责：
  1. 从自然语言/结构化输入中提取 UserPreference
  2. 计算 POI 与用户偏好的匹配度
  3. 计算 POI 与用户出行人群的适配度
"""

import random
from typing import Dict, List, Set, Optional

from backend.models.schemas import POI, UserPreference


def parse_preference_from_request(
    preferences: List[str],
    travelers: str,
    pace: str,
    budget: Optional[int] = None
) -> UserPreference:
    """
    将前端请求中的偏好信息转换为 UserPreference 对象
    简化版：不做LLM调用，直接基于规则映射
    """
    # 主题权重映射 【Day 3 修复】使用确定性权重，避免每次请求结果不同
    all_themes = ["美食", "拍照", "文化", "自然", "购物", "娱乐"]
    theme_weights = {}
    
    for theme in all_themes:
        if theme in preferences:
            theme_weights[theme] = 0.85
        else:
            theme_weights[theme] = 0.25
    
    # 预算级别
    budget_level = "标准"
    if budget is not None:
        if budget < 200:
            budget_level = "经济"
        elif budget > 500:
            budget_level = "高端"
    
    # 价格敏感度（预算越低越敏感）
    price_sensitivity = 0.5
    if budget is not None:
        price_sensitivity = max(0.0, min(1.0, 1.0 - budget / 1000))
    
    return UserPreference(
        theme_weights=theme_weights,
        traveler_type=travelers,
        pace_preference=pace,
        budget_level=budget_level,
        willingness_to_queue=0.5,
        willingness_to_walk=0.5,
        price_sensitivity=round(price_sensitivity, 2)
    )


# 主题同义词映射：扩展主题的语义覆盖范围
THEME_SYNONYMS: Dict[str, List[str]] = {
    "自然": ["风景", "山水", "爬山", "登山", "徒步", "户外", "森林", "公园", "湿地", "生态", "自然", "氧吧", "绿色"],
    "文化": ["历史", "古迹", "博物馆", "文物", "非遗", "传统", "人文", "书院", "寺庙", "古建", "文化"],
    "美食": ["小吃", "餐厅", "美食", "特色菜", "老字号", "米其林", "夜市", "烧烤", "火锅", "海鲜", "美食街"],
    "拍照": ["摄影", "出片", "打卡", "网红", "ins风", "航拍", "日落", "夜景", "花海", "建筑美学", "光影"],
    "购物": ["商场", "步行街", "市集", "买手店", "免税店", "奥特莱斯", "批发市场", "文创", "纪念品"],
    "娱乐": ["游乐园", "演出", "酒吧", "KTV", "密室", "剧本杀", "温泉", "SPA", "亲子", "萌宠", "休闲"],
}


def _tag_matches_theme(tag: str, theme: str) -> bool:
    """检查标签是否语义上匹配某个主题（支持同义词扩展）"""
    # 直接匹配
    if theme in tag or tag in theme:
        return True
    # 同义词匹配
    synonyms = THEME_SYNONYMS.get(theme, [])
    for syn in synonyms:
        if syn in tag or tag in syn:
            return True
    return False


def compute_preference_match(
    poi_tags: List[str],
    theme_weights: Dict[str, float]
) -> float:
    """
    计算POI标签与用户主题偏好的匹配度（0~1）
    
    算法：加权Jaccard的变体 + 同义词扩展
    - 对POI每个标签，如果在用户偏好中有权重，累加该权重
    - 支持同义词映射（如"自然"可匹配"风景优美"、"爬山"、"户外"等）
    - 归一化到 0~1
    """
    if not theme_weights or not poi_tags:
        return 0.0
    
    matched_weight = 0.0
    total_weight = sum(theme_weights.values())
    
    if total_weight == 0:
        return 0.0
    
    for tag in poi_tags:
        # 直接匹配
        if tag in theme_weights:
            matched_weight += theme_weights[tag]
        else:
            # 语义匹配：通过同义词扩展主题覆盖
            best_match = 0.0
            for theme, weight in theme_weights.items():
                if _tag_matches_theme(tag, theme):
                    best_match = max(best_match, weight)
            if best_match > 0:
                matched_weight += best_match * 0.7  # 语义匹配打7折
    
    # 归一化：考虑POI标签数量和总权重
    return min(1.0, matched_weight / max(total_weight * 0.5, 0.1))


def compute_crowd_match(
    poi_suitable_for: Optional[List[str]],
    traveler_type: str
) -> float:
    """
    计算POI适合人群与用户出行人群的适配度（0~1）
    """
    if not poi_suitable_for:
        return 0.7  # 默认中性
    
    # 人群适配表
    crowd_compat = {
        "独自": ["独自", "年轻人", "背包客"],
        "情侣": ["情侣", "浪漫", "年轻人", "摄影爱好者"],
        "亲子": ["亲子", "家庭", "儿童", "老人"],
        "朋友": ["朋友", "年轻人", "聚会"],
        "家庭": ["家庭", "亲子", "老人"],
    }
    
    compatible_tags = crowd_compat.get(traveler_type, [traveler_type])
    
    for tag in poi_suitable_for:
        if tag in compatible_tags:
            return 1.0
    
    # 部分匹配
    for tag in poi_suitable_for:
        for compat in compatible_tags:
            if compat in tag or tag in compat:
                return 0.7
    
    return 0.4  # 不太匹配


def record_selection_reason(
    poi: POI,
    user_pref: UserPreference,
    arrive_time: str
) -> List[str]:
    """
    记录为什么选中这个POI — 用于后续解释生成
    在贪心选择POI时调用
    """
    reasons = []
    
    # 1. 记录匹配的偏好主题
    matched_themes = []
    for theme, weight in user_pref.theme_weights.items():
        if weight > 0.5 and theme in poi.tags:
            matched_themes.append(theme)
    if matched_themes:
        reasons.append(f"[规则] 匹配你的{'和'.join(matched_themes)}偏好")
    
    # 2. 记录人群适配原因
    if user_pref.traveler_type == "情侣" and "浪漫" in poi.tags:
        reasons.append("[规则] 适合情侣约会")
    elif user_pref.traveler_type == "亲子" and any(t in poi.tags for t in ["儿童", "亲子"]):
        reasons.append("[规则] 适合带孩子")
    elif user_pref.traveler_type == "独自" and "安静" in poi.tags:
        reasons.append("[规则] 适合独自体验")
    
    # 3. 记录时间合理性
    try:
        hour = int(arrive_time.split(":")[0])
        if hour < 10 and any(t in matched_themes for t in ["拍照", "摄影"]):
            reasons.append("[规则] 上午光线柔和，适合拍照")
        elif 11 <= hour <= 13 and poi.category in ["餐饮服务", "咖啡厅"]:
            reasons.append("[规则] 正好是用餐时间")
        elif hour >= 17 and any(t in poi.tags for t in ["夜景", "灯光"]):
            reasons.append("[规则] 夜晚景色最美")
    except Exception:
        pass
    
    # 4. 记录评分/性价比原因
    if poi.rating and poi.rating >= 4.7:
        reasons.append(f"[规则] 评分高达{poi.rating}分")
    if poi.price == 0:
        reasons.append("[规则] 免费开放")
    
    return reasons
