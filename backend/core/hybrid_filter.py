# -*- coding: utf-8 -*-
"""
混合 POI 筛选器（重构版）
【核心变化】
  1. 删除硬编码主题、同义词表、复杂度分析
  2. 统一筛选路径：本地 Embedding 粗排 + LLM 精排（Top-20）
  3. 所有请求走同一套语义匹配逻辑
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict

from backend.models.schemas import POI, PlanRequest, UserPreference, RouteConstraints
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
    KEYWORD_MATCH = "keyword_match"


class RuleBasedFilter:
    """
    规则化 POI 筛选器
    负责硬约束过滤和语义匹配预打分
    """

    def hard_constraint_filter(
        self,
        pois: List[POI],
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        硬约束过滤：排除 avoid 列表
        （预算约束交由路线引擎处理，召回阶段不过滤）
        """
        avoid_names = set(constraints.avoid or [])
        candidates = []
        for poi in pois:
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
        宽松硬约束过滤：只排除 avoid 列表
        不再按预算预过滤，保留更多候选给路线引擎决策
        """
        avoid_names = set(constraints.avoid or [])
        candidates = []
        for poi in pois:
            if _poi_matches_avoid(poi, avoid_names):
                continue
            candidates.append(poi)
        return candidates

    # 【泛化】关键词→类别偏好加分规则配置表
    # 当用户query中包含某类关键词时，自动给对应类别的POI加分
    CATEGORY_BOOST_RULES = [
        {"name": "餐饮", "keywords": ["美食", "吃", "餐厅", "火锅", "小吃", "吃辣", "西湖醋鱼", "杭帮菜"],
         "categories": ["餐饮服务"], "boost": 0.03, "name_contains": None},
        {"name": "山景", "keywords": ["爬山", "登山", "山", "徒步"],
         "categories": ["风景名胜"], "boost": 0.05, "name_contains": ["山", "峰", "岭"]},
        {"name": "拍照", "keywords": ["拍照", "摄影", "打卡", "风景"],
         "categories": ["风景名胜"], "boost": 0.04, "name_contains": None},
        {"name": "购物", "keywords": ["购物", "买", "逛街", "商场"],
         "categories": ["购物服务"], "boost": 0.03, "name_contains": None},
        {"name": "运动", "keywords": ["运动", "体育", "健身", "球"],
         "categories": ["体育休闲服务"], "boost": 0.03, "name_contains": None},
        {"name": "文化", "keywords": ["文化", "历史", "博物馆", "古迹"],
         "categories": ["风景名胜", "科教文化服务"], "boost": 0.03, "name_contains": None},
        {"name": "自然", "keywords": ["自然", "公园", "湖", "河", "森林"],
         "categories": ["风景名胜"], "boost": 0.04, "name_contains": None},
    ]

    def _apply_category_boost(self, poi: POI, user_pref: UserPreference, match: float) -> float:
        """根据用户偏好关键词，给对应类别的POI加分（泛化规则）"""
        boost = 0.0
        for rule in self.CATEGORY_BOOST_RULES:
            # 检查用户偏好中是否包含该规则的关键词
            has_kw = any(kw in user_pref.theme_weights for kw in rule["keywords"])
            if not has_kw:
                continue
            # 检查POI是否属于目标类别
            if poi.category not in rule["categories"]:
                continue
            # 检查名称过滤（可选）
            if rule["name_contains"]:
                if not any(nc in poi.name for nc in rule["name_contains"]):
                    continue
            boost += rule["boost"]
        return boost

    def score_by_preference(
        self,
        pois: List[POI],
        user_pref: UserPreference
    ) -> List[Tuple[POI, float]]:
        """
        根据用户偏好对 POI 打分
        【重构】使用语义匹配替代同义词表匹配
        【泛化】使用CATEGORY_BOOST_RULES替代硬编码加分规则
        """
        scored = []
        for poi in pois:
            match = compute_preference_match(poi, user_pref.theme_weights)
            crowd = compute_crowd_match(poi.suitable_for, user_pref.traveler_type)
            base_score = (poi.rating or 3.5) / 5.0

            score = match * 0.65 + crowd * 0.15 + base_score * 0.20

            if match < 0.08:
                score *= 0.2
            elif match < 0.15:
                score *= 0.5

            if match > 0.25 and base_score < 0.80:
                score += 0.06
            
            # 【泛化】应用类别偏好加分
            score += self._apply_category_boost(poi, user_pref, match)

            # 【第三层追加】动态抓取POI关键词匹配加分
            if getattr(poi, "source", "") == "amap_dynamic":
                fetch_kw = getattr(poi, "fetch_keywords", "")
                for user_kw in user_pref.theme_weights:
                    if user_kw in fetch_kw or fetch_kw in user_kw:
                        match = min(1.0, match + 0.12)
                        break

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
        top_k: int = 50
    ) -> List[POI]:
        """
        纯规则筛选完整流程：硬约束过滤 → 语义匹配打分 → 取 TopK
        【泛化】通用类别上限+下限控制，防止单一类别垄断候选池
        """
        candidates = self.loose_filter(pois, constraints)
        scored = self.score_by_preference(candidates, user_pref)

        # 通用类别多样性策略：上限+下限控制
        categories = ["风景名胜", "餐饮服务", "购物服务", "体育休闲服务"]
        max_per_cat = max(5, top_k // 3)   # 每个类别最多占1/3
        min_per_cat = 3                     # 每个主要类别至少3个
        
        result = []
        used_names = set()
        cat_counts = {}
        
        # 第一轮：按全局排序取Top，但限制每类上限
        for p, s in scored:
            if len(result) >= top_k:
                break
            cat = p.category
            if cat_counts.get(cat, 0) >= max_per_cat:
                continue
            result.append(p)
            used_names.add(p.name)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
        # 第二轮：为不足的类别补充（从剩余POI中按排序取）
        for cat in categories:
            need = min_per_cat - cat_counts.get(cat, 0)
            if need <= 0:
                continue
            cat_scored = [(p, s) for p, s in scored if p.category == cat and p.name not in used_names]
            for p, _ in cat_scored[:need]:
                if len(result) >= top_k:
                    break
                result.append(p)
                used_names.add(p.name)
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
        # 第三轮：如果还有空位，继续按全局排序补充
        for p, _ in scored:
            if p.name not in used_names:
                if len(result) >= top_k:
                    break
                result.append(p)
                used_names.add(p.name)
                cat_counts[p.category] = cat_counts.get(p.category, 0) + 1

        # 确保 must_visit 在结果中
        must_names = set(constraints.must_visit or [])
        for p, _ in scored:
            if p.name in must_names and p.name not in used_names:
                result.append(p)
                used_names.add(p.name)
        return result


class HybridPOIFilter:
    """
    混合 POI 筛选器（重构版）
    【方案A】中文Embedding粗排 + LLM精排Top-20兜底
    """

    def __init__(self):
        self.rule_filter = RuleBasedFilter()
        self.llm_filter = LLMBasedFilter(batch_size=20)

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

        Returns:
            filtered_pois: 筛选后的 POI 列表
            strategy_used: 实际使用的策略
            metadata: 筛选过程元数据
        """
        # Step 1: 宽松硬约束过滤
        candidates = self.rule_filter.loose_filter(pois, constraints)

        # Step 2: 本地 Embedding 粗排（零延迟，纯本地计算）
        scored = self.rule_filter.score_by_preference(candidates, user_pref)
        top50 = [p for p, _ in scored[:50]]

        # Step 3: LLM 精排（仅对 Top-20，生成深度语义分数和推荐理由）
        llm_results: Dict[str, Dict] = {}
        llm_rankings: List[Dict] = []

        if request.raw_query and request.raw_query.strip():
            try:
                top20 = top50[:20]
                llm_rankings = self.llm_filter.filter_batch(
                    top20,
                    request.raw_query,
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
                for r in llm_rankings:
                    if isinstance(r, dict) and r.get("poi_id"):
                        llm_results[r["poi_id"]] = r
            except Exception as e:
                print(f"[HybridFilter] LLM 精排失败（非关键）: {e}")

        # Step 4: 融合分数（规则 60% + LLM 40%）
        final_scored = []
        for poi in top50:
            rule_score = poi.pre_score * 100  # 0-100
            llm_data = llm_results.get(poi.poi_id, {})
            llm_score = llm_data.get("match_score", 50)
            poi.llm_match_score = llm_score
            final_score = rule_score * 0.6 + llm_score * 0.4
            final_scored.append((poi, final_score))

        final_scored.sort(key=lambda x: x[1], reverse=True)

        # 取 Top-40，确保 must_visit
        result = [p for p, _ in final_scored[:40]]
        must_names = set(constraints.must_visit or [])
        result_names = {p.name for p in result}

        for p, _ in final_scored:
            if p.name in must_names and p.name not in result_names:
                result.append(p)
                result_names.add(p.name)

        metadata = {
            "strategy": FilterStrategy.KEYWORD_MATCH.value,
            "input_count": len(pois),
            "output_count": len(result),
            "has_raw_query": bool(request.raw_query and request.raw_query.strip()),
            "llm_rankings": llm_rankings,
            "hidden_needs": None,
        }

        return result, FilterStrategy.KEYWORD_MATCH, metadata
