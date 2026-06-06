# -*- coding: utf-8 -*-
"""
偏好量化与匹配计算
负责：
  1. 从自然语言/结构化输入中提取 UserPreference
  2. 计算 POI 与用户偏好的匹配度（基于语义相似度）
  3. 计算 POI 与用户出行人群的适配度
"""

from typing import Dict, List, Optional

from backend.models.schemas import POI, UserPreference
from backend.core.semantic_matcher import semantic_matcher


def parse_preference_from_request(
    preferences: List[str],
    travelers: str,
    pace: str,
    budget: Optional[int] = None
) -> UserPreference:
    """
    将前端请求中的偏好信息转换为 UserPreference 对象
    【重构】preferences 列表直接作为意图关键词，不再映射到固定主题
    """
    # 前端传入的 preferences 直接作为意图关键词
    theme_weights = {}
    for pref in preferences:
        pref = pref.strip()
        if pref:
            theme_weights[pref] = 0.85

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


def _rule_based_match(poi: POI, keyword: str) -> float:
    """基于名称/分类/标签的硬规则匹配（作为语义匹配的回退）"""
    name = (poi.name or "").lower()
    category = (poi.category or "").lower()
    tags = [t.lower() for t in (getattr(poi, "tags", None) or [])]
    kw = keyword.lower()
    
    # 爬山 → 名称含"山"且为风景名胜
    if kw in ("爬山", "登山", "山"):
        if "山" in name and "风景名胜" in category:
            return 0.75
        if "峰" in name and "风景名胜" in category:
            return 0.70
    
    # 西湖醋鱼 → 知名杭帮菜餐厅
    if kw in ("西湖醋鱼", "杭帮菜", "醋鱼"):
        famous = ["知味观", "楼外楼", "外婆家", "新白鹿", "绿茶", "弄堂里", "老头儿"]
        if any(f in poi.name for f in famous):
            return 0.80
        if any(t in ("杭帮菜", "浙菜", "西湖醋鱼") for t in tags):
            return 0.70
    
    # 美食/吃 → 餐饮类
    if kw in ("美食", "吃", "餐厅", "吃饭", "小吃", "吃辣"):
        if "餐饮" in category:
            return 0.55
    
    # 拍照/风景 → 风景名胜
    if kw in ("拍照", "摄影", "风景", "打卡"):
        if "风景名胜" in category:
            return 0.50
    
    # 购物 → 购物服务
    if kw in ("购物", "买", "逛街"):
        if "购物" in category:
            return 0.55
    
    # 运动/体育 → 体育休闲
    if kw in ("运动", "体育", "健身"):
        if "体育" in category:
            return 0.55
    
    # 文化/历史 → 风景名胜或文化场所
    if kw in ("文化", "历史", "博物馆"):
        if "风景名胜" in category or "博物馆" in name:
            return 0.50
    
    return 0.0


def compute_preference_match(poi: POI, theme_weights: Dict[str, float]) -> float:
    """
    计算 POI 与关键词权重的语义匹配度（0~1）
    【重构】使用本地 Embedding 模型进行语义相似度计算
    【修复】当语义匹配极低时，使用规则回退匹配
    """
    if not theme_weights:
        return 0.0

    semantic_match = semantic_matcher.match_keywords_to_poi(theme_weights, poi)
    
    # 当语义匹配器失败（返回接近0）时，使用规则回退
    if semantic_match < 0.15:
        rule_matches = []
        for kw in theme_weights:
            rm = _rule_based_match(poi, kw)
            if rm > 0:
                rule_matches.append(rm * theme_weights[kw])
        if rule_matches:
            total_weight = sum(theme_weights.values())
            rule_match = sum(rule_matches) / max(total_weight * 0.8, 0.1)
            return max(semantic_match, min(rule_match, 1.0))
    
    return semantic_match


def compute_keyword_matches(poi: POI, theme_weights: Dict[str, float]) -> Dict[str, float]:
    """
    计算每个关键词与 POI 的单独相似度
    返回: {keyword: similarity}
    """
    if not theme_weights:
        return {}
    return semantic_matcher.compute_keyword_matches(theme_weights, poi)


def compute_crowd_match(
    poi_suitable_for: Optional[List[str]],
    traveler_type: str
) -> float:
    """
    计算POI适合人群与用户出行人群的适配度（0~1）
    【保留】人群适配逻辑与主题无关
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
    【重构】使用关键词匹配逻辑替代固定主题匹配
    """
    reasons = []

    # 1. 记录匹配的关键词
    if user_pref.theme_weights:
        matched_keywords = []
        keyword_matches = compute_keyword_matches(poi, user_pref.theme_weights)
        for kw, sim in keyword_matches.items():
            if sim > 0.5 and user_pref.theme_weights.get(kw, 0) > 0.3:
                matched_keywords.append(kw)
        if matched_keywords:
            reasons.append(f"[规则] 匹配你的{'、'.join(matched_keywords)}偏好")

    # 2. 记录人群适配原因
    if user_pref.traveler_type == "情侣" and "浪漫" in (poi.tags or []):
        reasons.append("[规则] 适合情侣约会")
    elif user_pref.traveler_type == "亲子" and any(t in (poi.tags or []) for t in ["儿童", "亲子"]):
        reasons.append("[规则] 适合带孩子")
    elif user_pref.traveler_type == "独自" and "安静" in (poi.tags or []):
        reasons.append("[规则] 适合独自体验")

    # 3. 记录时间合理性
    try:
        hour = int(arrive_time.split(":")[0])
        if hour < 10 and any(t in (poi.tags or []) for t in ["拍照", "摄影"]):
            reasons.append("[规则] 上午光线柔和，适合拍照")
        elif 11 <= hour <= 13 and poi.category in ["餐饮服务", "咖啡厅"]:
            reasons.append("[规则] 正好是用餐时间")
        elif hour >= 17 and any(t in (poi.tags or []) for t in ["夜景", "灯光"]):
            reasons.append("[规则] 夜晚景色最美")
    except Exception:
        pass

    # 4. 记录评分/性价比原因
    if poi.rating and poi.rating >= 4.7:
        reasons.append(f"[规则] 评分高达{poi.rating}分")
    if poi.price == 0:
        reasons.append("[规则] 免费开放")

    return reasons
