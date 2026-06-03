# -*- coding: utf-8 -*-
"""
混合 POI 筛选器
将规则化筛选与 LLM 语义筛选结合，根据需求复杂度自动选择最优路径
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict

from backend.models.schemas import POI, PlanRequest, UserPreference, RouteConstraints
from backend.core.query_analyzer import QueryAnalyzer, QueryComplexity, KNOWN_TAGS
from backend.core.llm_filter import LLMBasedFilter
from backend.core.preference import compute_preference_match, compute_crowd_match


def _poi_matches_avoid(poi: POI, avoid_keywords: set) -> bool:
    """检查POI是否应被排除（支持名称模糊匹配和类别匹配）"""
    if not avoid_keywords:
        return False
    name = poi.name or ""
    category = poi.category or ""
    sub_category = getattr(poi, 'sub_category', None) or ""
    for kw in avoid_keywords:
        kw = kw.strip()
        if not kw:
            continue
        if name == kw or kw in name:
            return True
        if kw in category or kw in sub_category:
            return True
        if category in kw or sub_category in kw:
            return True
    return False


class FilterStrategy(Enum):
    RULE_ONLY = "rule_only"
    HYBRID = "hybrid"
    LLM_DOMINANT = "llm_dominant"


class RuleBasedFilter:
    """
    规则化 POI 筛选器
    负责硬约束过滤和偏好预打分
    """
    
    def hard_constraint_filter(
        self,
        pois: List[POI],
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        硬约束过滤：排除明显不符合的 POI
        - 排除 avoid 列表
        （预算约束交由路线引擎处理，召回阶段不过滤，保留更多候选）
        """
        avoid_names = set(constraints.avoid or [])
        candidates = []
        
        for poi in pois:
            # 排除 avoid 列表（支持模糊匹配和类别匹配）
            if _poi_matches_avoid(poi, avoid_names):
                continue
            
            candidates.append(poi)
        
        return candidates
    
    def loose_filter(
        self,
        pois: List[POI],
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        宽松硬约束过滤：只排除极端不符合的
        - 排除 avoid 列表
        - 排除超出预算 2 倍以上的
        """
        avoid_names = set(constraints.avoid or [])
        candidates = []
        
        for poi in pois:
            if _poi_matches_avoid(poi, avoid_names):
                continue
            
            if constraints.budget is not None and poi.price is not None:
                if poi.price > constraints.budget * 2.0:
                    continue
            
            candidates.append(poi)
        
        return candidates
    
    def score_by_preference(
        self,
        pois: List[POI],
        user_pref: UserPreference
    ) -> List[Tuple[POI, float]]:
        """
        根据用户偏好对 POI 打分
        同时设置 POI 的 pre_score / preference_match_score / crowd_match_score
        供路线引擎后续使用
        
        返回：(POI, score) 列表，按分数降序排列
        """
        scored = []
        for poi in pois:
            match = compute_preference_match(poi.tags, user_pref.theme_weights)
            crowd = compute_crowd_match(poi.suitable_for, user_pref.traveler_type)
            base_score = (poi.rating or 3.5) / 5.0
            
            # 综合分数：偏好匹配 50% + 人群适配 20% + 评分 30%
            score = match * 0.5 + crowd * 0.2 + base_score * 0.3
            
            # 【关键】设置 POI 的预计算分数，供路线引擎使用
            poi.preference_match_score = match
            poi.crowd_match_score = crowd
            poi.pre_score = score
            
            scored.append((poi, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
    
    def filter(
        self,
        pois: List[POI],
        user_pref: UserPreference,
        constraints: RouteConstraints,
        top_k: int = 30
    ) -> List[POI]:
        """
        纯规则筛选完整流程：硬约束过滤 → 偏好打分 → 取 TopK
        """
        candidates = self.hard_constraint_filter(pois, constraints)
        scored = self.score_by_preference(candidates, user_pref)
        
        # 确保 must_visit 在结果中
        must_names = set(constraints.must_visit or [])
        result = [p for p, _ in scored[:top_k]]
        result_names = {p.name for p in result}
        
        for p, _ in scored:
            if p.name in must_names and p.name not in result_names:
                result.append(p)
                result_names.add(p.name)
        
        return result


class HybridPOIFilter:
    """
    混合 POI 筛选器
    自动选择最优筛选策略，兼顾速度与精准度
    """
    
    def __init__(self):
        self.rule_filter = RuleBasedFilter()
        self.llm_filter = LLMBasedFilter(batch_size=10)
        self.query_analyzer = QueryAnalyzer()
    
    def filter(
        self,
        pois: List[POI],
        request: PlanRequest,
        user_pref: UserPreference,
        constraints: RouteConstraints,
        force_strategy: Optional[FilterStrategy] = None
    ) -> Tuple[List[POI], FilterStrategy, Dict]:
        """
        统一筛选入口
        
        Args:
            pois: 全部候选 POI
            request: 用户请求
            user_pref: 用户偏好
            constraints: 路线约束
            force_strategy: 强制指定策略（调试用）
        
        Returns:
            filtered_pois: 筛选后的 POI 列表
            strategy_used: 实际使用的策略
            metadata: 筛选过程元数据
        """
        # 确定策略
        if force_strategy:
            strategy = force_strategy
        else:
            strategy = self._select_strategy(request)
        
        # 执行筛选
        llm_rankings: List[Dict] = []
        if strategy == FilterStrategy.RULE_ONLY:
            result = self.rule_filter.filter(pois, user_pref, constraints, top_k=50)
        elif strategy == FilterStrategy.HYBRID:
            result = self._hybrid_filter(pois, request, user_pref, constraints)
        else:
            result = self._llm_dominant_filter(pois, request, user_pref, constraints)
            # LLM_DOMINANT 模式下，同时保存 LLM 全量排序结果供前端展示
            llm_rankings = getattr(self, '_last_llm_results', [])
        
        metadata = {
            "strategy": strategy.value,
            "input_count": len(pois),
            "output_count": len(result),
            "has_raw_query": bool(request.raw_query and request.raw_query.strip()),
            "hidden_needs": self.query_analyzer.extract_hidden_needs(request.raw_query or ""),
            "llm_rankings": llm_rankings,
        }
        
        return result, strategy, metadata
    
    def _select_strategy(self, request: PlanRequest) -> FilterStrategy:
        """自动选择筛选策略
        【优化】当用户有自然语言输入时，优先使用 LLM 主导排序，让 LLM 决定POI匹配度
        """
        # 有 raw_query 时，LLM 语义理解能力远强于规则，强制使用 LLM 主导
        if request.raw_query and request.raw_query.strip():
            return FilterStrategy.LLM_DOMINANT
        
        complexity = self.query_analyzer.analyze(request)
        
        if complexity == QueryComplexity.SIMPLE:
            return FilterStrategy.RULE_ONLY
        elif complexity == QueryComplexity.COMPLEX:
            return FilterStrategy.LLM_DOMINANT
        else:
            return FilterStrategy.HYBRID
    
    def _hybrid_filter(
        self,
        pois: List[POI],
        request: PlanRequest,
        user_pref: UserPreference,
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        路径 B：规则粗筛 → LLM 精筛
        """
        # Step 1: 规则硬约束过滤
        rule_filtered = self.rule_filter.hard_constraint_filter(pois, constraints)
        
        # Step 2: 规则偏好预打分，取 Top 50（粗筛放宽后，让更多候选进入LLM精筛）
        rule_scored = self.rule_filter.score_by_preference(rule_filtered, user_pref)
        candidates = [p for p, _ in rule_scored[:50]]
        
        # Step 3: LLM 精筛（只处理软偏好）
        llm_results = self.llm_filter.filter_batch(
            candidates,
            request.raw_query or "",
            context={
                "city": request.city,
                "travelers": request.travelers,
                "preferences": request.preferences,
                "pace": request.pace,
                "budget": request.budget,
                "must_visit": request.must_visit,
                "avoid": request.avoid,
                "transport_mode": request.transport_mode,
            },
            focus="soft_preference"
        )
        
        # Step 4: 融合分数
        return self._fuse_scores(rule_scored, llm_results, candidates, constraints, alpha=0.4)
    
    def _llm_dominant_filter(
        self,
        pois: List[POI],
        request: PlanRequest,
        user_pref: UserPreference,
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        路径 C：LLM 主导全量重排
        【优化】保存完整 LLM 排序结果到 self._last_llm_results，供前端展示
        """
        # Step 1: 宽松硬约束过滤
        loosely_filtered = self.rule_filter.loose_filter(pois, constraints)
        
        # Step 2: 分批调用 LLM
        llm_results = self.llm_filter.filter_all(loosely_filtered, request)
        
        # 【保存完整排序结果】
        self._last_llm_results = llm_results
        
        # Step 3: 按 LLM 分数排序
        llm_results.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        
        # Step 4: 后处理：规则校验 Top 结果，补充 must_visit
        result = []
        must_names = set(constraints.must_visit or [])
        result_names = set()
        
        for r in llm_results:
            poi_id = r.get("poi_id")
            poi = next((p for p in loosely_filtered if p.poi_id == poi_id), None)
            if not poi:
                continue
            
            # 硬约束校验
            if _poi_matches_avoid(poi, set(constraints.avoid or [])):
                continue
            
            result.append(poi)
            result_names.add(poi.name)
            
            # 附加 LLM 分数到 POI 对象（供后续使用）
            poi.__dict__["llm_match_score"] = r.get("match_score", 50)
            
            if len(result) >= 30:
                break
        
        # 确保 must_visit 在结果中
        for p in loosely_filtered:
            if p.name in must_names and p.name not in result_names:
                result.append(p)
                result_names.add(p.name)
        
        return result[:35]
    
    def _fuse_scores(
        self,
        rule_scored: List[Tuple[POI, float]],
        llm_results: List[Dict],
        candidates: List[POI],
        constraints: RouteConstraints,
        alpha: float = 0.4
    ) -> List[POI]:
        """
        融合规则分数和 LLM 分数
        
        Args:
            rule_scored: 规则打分结果 (POI, score) 列表
            llm_results: LLM 筛选结果
            candidates: 候选 POI 列表
            alpha: 规则分数权重（LLM 权重 = 1 - alpha）
        """
        # 建立查找字典
        rule_scored_dict = {p.poi_id: score for p, score in rule_scored}
        llm_results_dict = {r["poi_id"]: r.get("match_score", 50) for r in llm_results}
        
        # 融合分数
        final_scored = []
        for poi in candidates:
            rule_score = rule_scored_dict.get(poi.poi_id, 0.5) * 100  # 规则分数是 0-1，转为 0-100
            llm_score = llm_results_dict.get(poi.poi_id, 50)
            final_score = rule_score * alpha + llm_score * (1 - alpha)
            
            # 附加 LLM 分数到 POI 对象
            poi.__dict__["llm_match_score"] = llm_score
            
            final_scored.append((poi, final_score))
        
        final_scored.sort(key=lambda x: x[1], reverse=True)
        
        # 取 Top 30，确保 must_visit
        result = [p for p, _ in final_scored[:30]]
        must_names = set(constraints.must_visit or [])
        result_names = {p.name for p in result}
        
        for p, _ in final_scored:
            if p.name in must_names and p.name not in result_names:
                result.append(p)
                result_names.add(p.name)
        
        return result
