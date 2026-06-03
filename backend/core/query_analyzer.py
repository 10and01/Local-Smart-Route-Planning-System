# -*- coding: utf-8 -*-
"""
需求复杂度分析器
判定用户需求的复杂度，决定后续筛选路径
"""

import re
from enum import Enum
from typing import List, Set, Optional

from backend.models.schemas import PlanRequest


class QueryComplexity(Enum):
    SIMPLE = "simple"      # 纯规则即可
    HYBRID = "hybrid"      # 规则+LLM
    COMPLEX = "complex"    # LLM主导


# 预设标签集合
KNOWN_TAGS: Set[str] = {"美食", "拍照", "文化", "自然", "购物", "娱乐"}

# 规则外隐性需求关键词（用于检测自然语言中的复杂需求）
HIDDEN_NEED_KEYWORDS: List[str] = [
    "吃辣", "不吃辣", "清淡", "重口味",
    "人少", "安静", "不拥挤", "避开人流", "清静", "清幽",
    "适合发朋友圈", "网红", "出片", "拍照好看", "小红书", "朋友圈",
    "有历史感", "古老", "传统", "文化底蕴", "古韵", "古迹",
    "适合约会", "浪漫", "私密", "情调",
    "带娃", "适合孩子", "亲子互动", "儿童",
    "便宜", "性价比高", "实惠", "不贵", "省钱",
    "高端", "豪华", "有档次", "轻奢",
    "夜景", "晚上", "夜生活", "夜间",
    "正宗", "老字号", "老店", "地道", "本地人",
    "不累", "轻松", "休闲", "惬意",
    "小众", "冷门", "宝藏", " hidden gem",
]

# 预设标签的同义词映射（用于识别自然语言中的简单需求）
TAG_SYNONYMS: dict = {
    "美食": ["好吃", "吃", "美食", "餐厅", "吃饭", " Dining", "food", "吃好吃的", "好吃的"],
    "拍照": ["拍照", "摄影", "打卡", "拍照片", "照相", "拍片", "出片", "摄影"],
    "文化": ["文化", "博物馆", "历史", "人文", "艺术", "展览", "古迹"],
    "自然": ["自然", "风景", "山水", "公园", "户外", "景色", "风光"],
    "购物": ["购物", "买", "逛街", "商场", "购物", "shopping", "买东西"],
    "娱乐": ["娱乐", "玩", "好玩", "乐趣", "休闲", " amusement", "fun"],
}


class QueryAnalyzer:
    """
    查询分析器：分析用户请求的复杂度，提取隐性需求
    """

    def __init__(self):
        self.known_tags = KNOWN_TAGS
        self.hidden_keywords = HIDDEN_NEED_KEYWORDS
        self.tag_synonyms = TAG_SYNONYMS

    def extract_hidden_needs(self, raw_query: str) -> List[str]:
        """
        从自然语言 query 中提取规则外的隐性需求关键词
        
        Returns:
            匹配到的隐性需求关键词列表
        """
        if not raw_query:
            return []
        
        matched = []
        for keyword in self.hidden_keywords:
            if keyword in raw_query:
                matched.append(keyword)
        
        return matched

    def extract_tag_references(self, raw_query: str) -> List[str]:
        """
        从自然语言 query 中提取对预设标签的引用
        
        Returns:
            被引用的预设标签列表
        """
        if not raw_query:
            return []
        
        matched_tags = []
        for tag, synonyms in self.tag_synonyms.items():
            for syn in synonyms:
                if syn in raw_query:
                    matched_tags.append(tag)
                    break
        
        return matched_tags

    def analyze(self, request: PlanRequest) -> QueryComplexity:
        """
        分析请求复杂度，决定筛选路径
        
        判定规则：
        - 无 raw_query，preferences 为空 → SIMPLE
        - 无 raw_query，preferences 全是预设标签 → SIMPLE
        - 有 raw_query，包含 >=2 个规则外隐性需求 → COMPLEX
        - 有 raw_query，包含 1 个规则外隐性需求 → HYBRID
        - 有 raw_query，无规则外需求 → HYBRID
        - 有 must_visit / avoid 且 raw_query 复杂 → COMPLEX
        """
        raw_query = request.raw_query or ""
        raw_query = raw_query.strip()
        
        # 有自然语言query
        if raw_query:
            hidden_needs = self.extract_hidden_needs(raw_query)
            
            # 包含多个规则外需求（>=3） → 复杂
            if len(hidden_needs) >= 3:
                return QueryComplexity.COMPLEX
            
            # 包含 must_visit / avoid 且有 >=2 个隐性需求 → 复杂
            if (request.must_visit or request.avoid) and len(hidden_needs) >= 2:
                return QueryComplexity.COMPLEX
            
            # 包含1-2个隐性需求 → 混合
            if len(hidden_needs) >= 1:
                return QueryComplexity.HYBRID
            
            # 有自然语言但只包含预设标签同义词 → 混合（LLM辅助验证）
            return QueryComplexity.HYBRID
        
        # 无自然语言，只有结构化标签
        if request.preferences:
            if set(request.preferences).issubset(self.known_tags):
                return QueryComplexity.SIMPLE
            return QueryComplexity.HYBRID
        
        # 无任何偏好 → 最简单
        return QueryComplexity.SIMPLE


def analyze_query_complexity(request: PlanRequest) -> QueryComplexity:
    """便捷函数：直接分析请求复杂度"""
    analyzer = QueryAnalyzer()
    return analyzer.analyze(request)
