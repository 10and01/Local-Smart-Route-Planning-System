# -*- coding: utf-8 -*-
"""
需求复杂度分析器（简化版）
【重构】删除所有硬编码标签、同义词表、隐性需求关键词
只保留基础的复杂度判断，用于决定是否启用 LLM 精排
"""

from enum import Enum
from typing import Optional

from backend.models.schemas import PlanRequest


class QueryComplexity(Enum):
    SIMPLE = "simple"      # 纯规则即可
    COMPLEX = "complex"    # 需要 LLM 辅助


class QueryAnalyzer:
    """
    查询分析器（简化版）：只判断是否需要 LLM 参与
    """

    def analyze(self, request: PlanRequest) -> QueryComplexity:
        """
        分析请求复杂度
        【简化规则】
        - 有 raw_query → COMPLEX（需要 LLM 提取关键词和精排）
        - 无 raw_query，只有结构化字段 → SIMPLE
        """
        raw_query = (request.raw_query or "").strip()
        if raw_query:
            return QueryComplexity.COMPLEX
        return QueryComplexity.SIMPLE

    def extract_hidden_needs(self, raw_query: str) -> list:
        """
        【重构】不再使用硬编码关键词列表匹配
        隐性需求由 LLM 解析器从自然语言中直接提取
        """
        return []

    def extract_tag_references(self, raw_query: str) -> list:
        """
        【重构】不再使用硬编码同义词表
        标签引用由 LLM 解析器直接提取为自由关键词
        """
        return []


def analyze_query_complexity(request: PlanRequest) -> QueryComplexity:
    """便捷函数：直接分析请求复杂度"""
    analyzer = QueryAnalyzer()
    return analyzer.analyze(request)
