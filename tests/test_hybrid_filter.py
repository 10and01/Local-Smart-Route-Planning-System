# -*- coding: utf-8 -*-
"""
混合 POI 筛选器单元测试

验证：
1. 需求复杂度判定（QueryAnalyzer）
2. 纯规则路径性能（<100ms）
3. 混合路径策略选择
4. 推荐理由来源标注（[规则]/[LLM]）

运行方式:
    cd /d/美团hackthon_5
    source venv/Scripts/activate
    python -m pytest tests/test_hybrid_filter.py -v
    # 或 python tests/test_hybrid_filter.py
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.schemas import PlanRequest, POI, Location, UserPreference, RouteConstraints
from backend.core.query_analyzer import (
    QueryAnalyzer, QueryComplexity, analyze_query_complexity, HIDDEN_NEED_KEYWORDS
)
from backend.core.hybrid_filter import HybridPOIFilter, FilterStrategy, RuleBasedFilter
from backend.core.preference import record_selection_reason, parse_preference_from_request


class MockPOIFactory:
    """快速创建测试用 POI"""
    
    @staticmethod
    def make(
        poi_id="P1",
        name="测试POI",
        category="风景名胜",
        tags=None,
        rating=4.5,
        price=0,
        suitable_for=None,
        lat=30.0,
        lng=120.0
    ):
        return POI(
            poi_id=poi_id,
            name=name,
            city="杭州",
            category=category,
            tags=tags or [],
            rating=rating,
            price=price,
            suitable_for=suitable_for or ["独自"],
            location=Location(lat=lat, lng=lng),
        )


class TestQueryAnalyzer(unittest.TestCase):
    """测试需求复杂度判定"""
    
    def test_simple_no_query_no_prefs(self):
        """无query无偏好 → SIMPLE"""
        req = PlanRequest(city="杭州")
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.SIMPLE)
    
    def test_simple_known_tags_only(self):
        """只有预设标签 → SIMPLE"""
        req = PlanRequest(city="杭州", preferences=["美食", "拍照"])
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.SIMPLE)
    
    def test_hybrid_one_hidden_need(self):
        """1个隐性需求 → HYBRID"""
        req = PlanRequest(city="杭州", raw_query="想吃辣的地方")
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.HYBRID)
    
    def test_complex_two_hidden_needs(self):
        """2个隐性需求 → HYBRID（调整后阈值：>=3才走COMPLEX）"""
        req = PlanRequest(city="杭州", raw_query="想吃辣的人少的地方")
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.HYBRID)
    
    def test_complex_with_must_visit(self):
        """有must_visit + 2个隐性需求 → COMPLEX"""
        req = PlanRequest(
            city="杭州",
            raw_query="想吃辣的人少的地方",
            must_visit=["西湖"]
        )
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.COMPLEX)
    
    def test_complex_three_hidden_needs(self):
        """3个隐性需求 → COMPLEX"""
        req = PlanRequest(city="杭州", raw_query="想吃辣的人少安静的地方")
        self.assertEqual(analyze_query_complexity(req), QueryComplexity.COMPLEX)
    
    def test_extract_hidden_needs(self):
        """测试隐性需求提取"""
        analyzer = QueryAnalyzer()
        needs = analyzer.extract_hidden_needs("想吃辣的人少的地方")
        self.assertIn("吃辣", needs)
        self.assertIn("人少", needs)
    
    def test_hidden_keywords_coverage(self):
        """验证关键隐性需求词都在词表中"""
        keywords = ["吃辣", "人少", "安静", "适合发朋友圈", "有历史感", "适合约会", "便宜", "夜景", "正宗"]
        for kw in keywords:
            self.assertIn(kw, HIDDEN_NEED_KEYWORDS, f"'{kw}' 不在隐性需求关键词表中")


class TestRuleBasedFilter(unittest.TestCase):
    """测试规则筛选器"""
    
    def test_hard_constraint_avoid(self):
        """排除 avoid 列表中的 POI"""
        pois = [
            MockPOIFactory.make(poi_id="P1", name="西湖"),
            MockPOIFactory.make(poi_id="P2", name="灵隐寺"),
        ]
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00",
            avoid=["灵隐寺"]
        )
        rf = RuleBasedFilter()
        result = rf.hard_constraint_filter(pois, constraints)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "西湖")
    
    def test_hard_constraint_budget(self):
        """
        预算约束已交由路线引擎处理，hard_constraint_filter 不过滤预算。
        本测试验证 budget 字段不会导致 POI 被误过滤。
        """
        pois = [
            MockPOIFactory.make(poi_id="P1", name="便宜店", price=50),
            MockPOIFactory.make(poi_id="P2", name="豪华餐厅", price=500),
        ]
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00",
            budget=300
        )
        rf = RuleBasedFilter()
        result = rf.hard_constraint_filter(pois, constraints)
        names = {p.name for p in result}
        self.assertIn("便宜店", names)
        # 预算约束不在召回阶段过滤，保留更多候选供路线引擎决策
        self.assertIn("豪华餐厅", names)
    
    def test_score_by_preference(self):
        """偏好打分排序"""
        pois = [
            MockPOIFactory.make(poi_id="P1", name="美食街", tags=["美食", "热闹"]),
            MockPOIFactory.make(poi_id="P2", name="拍照点", tags=["拍照", "风景"]),
        ]
        user_pref = parse_preference_from_request(
            preferences=["美食"],
            travelers="独自",
            pace="适中"
        )
        rf = RuleBasedFilter()
        scored = rf.score_by_preference(pois, user_pref)
        self.assertEqual(scored[0][0].name, "美食街")  # 美食偏好 → 美食街排第一
    
    def test_rule_filter_full_pipeline(self):
        """纯规则筛选完整流程"""
        pois = [
            MockPOIFactory.make(poi_id="P1", name="西湖", tags=["自然", "拍照"], rating=4.8),
            MockPOIFactory.make(poi_id="P2", name="美食街", tags=["美食"], rating=4.5),
            MockPOIFactory.make(poi_id="P3", name="灵隐寺", tags=["文化"], rating=4.7),
        ]
        user_pref = parse_preference_from_request(
            preferences=["美食", "拍照"],
            travelers="情侣",
            pace="适中"
        )
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00"
        )
        rf = RuleBasedFilter()
        result = rf.filter(pois, user_pref, constraints, top_k=2)
        self.assertLessEqual(len(result), 3)  # top_k=2 + must_visit


class TestHybridFilterStrategy(unittest.TestCase):
    """测试混合筛选器策略选择"""
    
    def setUp(self):
        self.hybrid = HybridPOIFilter()
        self.pois = [
            MockPOIFactory.make(poi_id="P1", name="西湖", tags=["自然", "拍照"], rating=4.8),
            MockPOIFactory.make(poi_id="P2", name="美食街", tags=["美食"], rating=4.5),
            MockPOIFactory.make(poi_id="P3", name="灵隐寺", tags=["文化"], rating=4.7),
            MockPOIFactory.make(poi_id="P4", name="博物馆", tags=["文化", "历史"], rating=4.6),
        ]
        self.user_pref = parse_preference_from_request(
            preferences=["美食", "拍照"],
            travelers="情侣",
            pace="适中"
        )
    
    def test_simple_path_performance(self):
        """
        输入"美食+拍照"（预设标签）→ 走纯规则路径，<100ms
        """
        request = PlanRequest(
            city="杭州",
            preferences=["美食", "拍照"],
            travelers="情侣",
            pace="适中"
        )
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00"
        )
        
        start = time.time()
        result, strategy, metadata = self.hybrid.filter(
            self.pois, request, self.user_pref, constraints
        )
        elapsed_ms = (time.time() - start) * 1000
        
        self.assertEqual(strategy, FilterStrategy.RULE_ONLY)
        self.assertLess(elapsed_ms, 100, f"纯规则路径应在100ms内完成，实际{elapsed_ms:.1f}ms")
        self.assertGreater(len(result), 0)
        print(f"[SIMPLE] 策略={strategy.value}, 耗时={elapsed_ms:.1f}ms, 输出={len(result)}")
    
    def test_hybrid_path_strategy(self):
        """
        输入自然语言（1个隐性需求）→ 走混合路径
        使用 mock 避免真实 LLM 调用
        """
        request = PlanRequest(
            city="杭州",
            raw_query="想吃辣的地方",
            preferences=["美食"],
            travelers="朋友",
            pace="适中"
        )
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00"
        )
        
        # mock LLM filter_batch 避免真实 API 调用
        original_filter_batch = self.hybrid.llm_filter.filter_batch
        def mock_filter_batch(pois, user_query, context, focus="full_evaluation"):
            return [
                {
                    "poi_id": p.poi_id,
                    "match_score": 75,
                    "recommendation_reason": "Mock 理由",
                    "is_recommended": True,
                    "matched_themes": ["美食"],
                    "hidden_matched": ["吃辣"],
                }
                for p in pois
            ]
        self.hybrid.llm_filter.filter_batch = mock_filter_batch
        
        try:
            result, strategy, metadata = self.hybrid.filter(
                self.pois, request, self.user_pref, constraints
            )
            self.assertEqual(strategy, FilterStrategy.HYBRID)
            self.assertIn("吃辣", metadata["hidden_needs"])
            print(f"[HYBRID] 策略={strategy.value}, 隐性需求={metadata['hidden_needs']}")
        finally:
            self.hybrid.llm_filter.filter_batch = original_filter_batch
    
    def test_complex_path_strategy(self):
        """
        输入"想吃辣的人少的地方"（2个隐性需求）→ 走混合路径（调整后阈值）
        使用 mock 避免真实 LLM 调用
        """
        request = PlanRequest(
            city="杭州",
            raw_query="想吃辣的人少的地方",
            preferences=["美食"],
            travelers="朋友",
            pace="适中"
        )
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00"
        )
        
        # mock LLM filter_batch 避免真实 API 调用
        original_filter_batch = self.hybrid.llm_filter.filter_batch
        def mock_filter_batch(pois, user_query, context, focus="full_evaluation"):
            return [
                {
                    "poi_id": p.poi_id,
                    "match_score": 80,
                    "recommendation_reason": "Mock 理由",
                    "is_recommended": True,
                    "matched_themes": ["美食"],
                    "hidden_matched": ["吃辣", "人少"],
                }
                for p in pois
            ]
        self.hybrid.llm_filter.filter_batch = mock_filter_batch
        
        try:
            result, strategy, metadata = self.hybrid.filter(
                self.pois, request, self.user_pref, constraints
            )
            self.assertEqual(strategy, FilterStrategy.HYBRID)
            self.assertIn("吃辣", metadata["hidden_needs"])
            self.assertIn("人少", metadata["hidden_needs"])
            print(f"[HYBRID-2needs] 策略={strategy.value}, 隐性需求={metadata['hidden_needs']}")
        finally:
            self.hybrid.llm_filter.filter_batch = original_filter_batch
    
    def test_force_strategy(self):
        """测试强制指定策略"""
        request = PlanRequest(city="杭州", preferences=["美食"])
        constraints = RouteConstraints(
            city="杭州",
            start_time="09:00",
            end_time="18:00"
        )
        
        # mock LLM filter_batch 避免真实 API 调用
        original_filter_batch = self.hybrid.llm_filter.filter_batch
        def mock_filter_batch(pois, user_query, context, focus="full_evaluation"):
            return [
                {
                    "poi_id": p.poi_id,
                    "match_score": 60,
                    "recommendation_reason": "Mock",
                    "is_recommended": True,
                    "matched_themes": [],
                    "hidden_matched": [],
                }
                for p in pois
            ]
        self.hybrid.llm_filter.filter_batch = mock_filter_batch
        
        try:
            # 正常应该走 RULE_ONLY
            result, strategy, _ = self.hybrid.filter(
                self.pois, request, self.user_pref, constraints,
                force_strategy=FilterStrategy.HYBRID
            )
            self.assertEqual(strategy, FilterStrategy.HYBRID)
        finally:
            self.hybrid.llm_filter.filter_batch = original_filter_batch


class TestReasonSourceTagging(unittest.TestCase):
    """测试推荐理由来源标注"""
    
    def test_rule_reason_prefix(self):
        """规则推荐理由应有 [规则] 前缀"""
        poi = MockPOIFactory.make(
            poi_id="P1",
            name="西湖",
            tags=["拍照", "自然"],
            rating=4.8
        )
        user_pref = parse_preference_from_request(
            preferences=["拍照"],
            travelers="情侣",
            pace="适中"
        )
        reasons = record_selection_reason(poi, user_pref, "09:00")
        
        for reason in reasons:
            self.assertTrue(
                reason.startswith("[规则]"),
                f"规则推荐理由应以'[规则]'开头，实际: {reason}"
            )
    
    def test_rule_reason_tags(self):
        """验证不同场景下规则推荐理由的标注"""
        # 场景1：高评分POI
        poi = MockPOIFactory.make(poi_id="P1", name="名店", rating=4.8)
        user_pref = parse_preference_from_request([], "独自", "适中")
        reasons = record_selection_reason(poi, user_pref, "10:00")
        self.assertTrue(any("[规则]" in r for r in reasons))
        
        # 场景2：免费POI
        poi = MockPOIFactory.make(poi_id="P2", name="公园", price=0)
        reasons = record_selection_reason(poi, user_pref, "10:00")
        self.assertTrue(any("[规则]" in r for r in reasons))
        
        # 场景3：情侣+浪漫标签
        poi = MockPOIFactory.make(poi_id="P3", name="情侣路", tags=["浪漫"])
        user_pref = parse_preference_from_request([], "情侣", "适中")
        reasons = record_selection_reason(poi, user_pref, "10:00")
        self.assertTrue(any("[规则]" in r for r in reasons))


def run_tests():
    """直接运行测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestQueryAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestRuleBasedFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestHybridFilterStrategy))
    suite.addTests(loader.loadTestsFromTestCase(TestReasonSourceTagging))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    print("=" * 60)
    print("混合 POI 筛选器单元测试")
    print("=" * 60)
    success = run_tests()
    sys.exit(0 if success else 1)
