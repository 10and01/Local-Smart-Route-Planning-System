# -*- coding: utf-8 -*-
"""
混合 POI 筛选器完整 Mock 演示
展示 SIMPLE / HYBRID / COMPLEX 三条路径的完整输出效果
"""

import sys
import os
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.services.planner as planner_mod
import backend.core.llm_reasoner as llm_reasoner_mod
from backend.services.planner import RoutePlannerService
from backend.models.schemas import PlanRequest
from backend.core.llm_filter import LLMBasedFilter
from backend.core.llm_reasoner import apply_llm_reasons_to_plan


# ========================================================================
# Mock 函数定义
# ========================================================================

def mock_parse_preference_from_llm(**kwargs):
    """Mock LLM 偏好解析：直接返回 None，走规则 fallback"""
    return None


def mock_llm_filter_batch(self, pois, user_query, context, focus="full_evaluation"):
    """Mock LLM 筛选：模拟对 POI 的评估结果"""
    results = []
    query = user_query.lower()
    
    for p in pois:
        score = 50
        hidden = []
        reason = "综合体验不错，适合本次出行"
        themes = []
        
        if "吃辣" in query or "辣" in query:
            if any(k in p.name or k in str(p.tags) for k in ["火锅", "川菜", "湘菜", "麻辣", "辣", "小吃"]):
                score += 25
                hidden.append("吃辣")
                reason = "麻辣口味正宗，满足吃辣需求"
                themes.append("美食")
            elif "美食" in p.category or "餐饮" in p.category:
                score += 10
                reason = "餐饮类场所，可尝试辣味菜品"
        
        if "人少" in query or "安静" in query or "不拥挤" in query:
            if any(k in p.name or k in str(p.tags) for k in ["公园", "寺", "馆", "老街", "古镇", "山", "湖"]):
                score += 20
                hidden.append("人少")
                if "吃辣" in hidden:
                    reason = "环境清幽且能提供辣味美食，满足吃辣+安静双重需求"
                else:
                    reason = "环境清幽，游客相对较少，适合安静游览"
            elif "网红" not in str(p.tags) and "排队" not in str(p.tags):
                score += 10
                hidden.append("人少")
        
        if "拍照" in query or "出片" in query:
            if any(k in str(p.tags) for k in ["拍照", "风景", "夜景", "古建筑", "湖", "日落", "全景"]):
                score += 20
                hidden.append("拍照好看")
                themes.append("拍照")
                reason = "风景优美，拍照出片率高"
        
        if "历史" in query or "文化" in query:
            if any(k in str(p.tags) for k in ["历史", "文化", "古迹", "博物馆", "老街", "非遗", "名人", "故居"]):
                score += 20
                hidden.append("有历史感")
                themes.append("文化")
                reason = "历史悠久，文化底蕴深厚"
        
        if p.rating and p.rating >= 4.5:
            score += 5
        
        results.append({
            "poi_id": p.poi_id,
            "match_score": min(100, max(0, score)),
            "recommendation_reason": reason,
            "is_recommended": score >= 60,
            "matched_themes": themes if themes else ["综合"],
            "hidden_matched": hidden,
        })
    
    return results


def mock_generate_poi_reasons(plan, user_pref, raw_query=None):
    """Mock LLM 推荐理由生成"""
    query = (raw_query or "").lower()
    reasons = {}
    
    for seg in plan.segments:
        p = seg.poi
        reasons_list = []
        
        if "吃辣" in query or "辣" in query:
            if any(k in p.name or k in str(p.tags) for k in ["火锅", "川菜", "麻辣", "辣", "小吃"]):
                reasons_list.append(f"{p.name}的麻辣口味很正宗，能满足你想吃辣的需求")
            else:
                reasons_list.append(f"{p.name}周边有不少辣味小吃，可以顺路尝尝")
        
        if "人少" in query or "安静" in query:
            if any(k in str(p.tags) for k in ["公园", "寺", "馆", "老街", "山", "湖"]):
                reasons_list.append(f"{p.name}相比热门景点游客少很多，氛围安静舒适")
            else:
                reasons_list.append(f"{p.name}非网红打卡地，避开人潮体验更好")
        
        if "拍照" in query:
            reasons_list.append(f"{p.name}景色出片，适合拍照发朋友圈")
        
        if "历史" in query:
            reasons_list.append(f"{p.name}承载着杭州的历史记忆，值得慢慢品味")
        
        if not reasons_list:
            reasons_list.append(f"{p.name}整体体验不错，适合{user_pref.traveler_type}出行")
        
        reasons[p.name] = reasons_list[0]
    
    return reasons


def mock_generate_overall(plan, user_pref, raw_query=None):
    """Mock 整体推荐理由"""
    return plan.overall_reasoning


# ========================================================================
# 注入 Mock
# ========================================================================

_orig_parse = planner_mod.parse_preference_from_llm
_orig_gen = planner_mod.generate_poi_reasons
_orig_overall = planner_mod.generate_overall_reasoning

planner_mod.parse_preference_from_llm = mock_parse_preference_from_llm
planner_mod.generate_poi_reasons = mock_generate_poi_reasons
planner_mod.generate_overall_reasoning = mock_generate_overall


def patch_service(service):
    """给 service 注入 Mock LLM 筛选"""
    service.hybrid_filter.llm_filter.filter_batch = types.MethodType(
        mock_llm_filter_batch, service.hybrid_filter.llm_filter
    )
    service.hybrid_filter.llm_filter.filter_all = types.MethodType(
        lambda self, pois, request: mock_llm_filter_batch(
            self, pois, request.raw_query or "", {}, focus="full_evaluation"
        ),
        service.hybrid_filter.llm_filter
    )


# ========================================================================
# 演示函数
# ========================================================================

def demo_simple_path():
    print("=" * 70)
    print("[路径 A] SIMPLE - 纯规则筛选 (美食 + 拍照)")
    print("=" * 70)
    print("输入: preferences=['美食', '拍照'], 无 raw_query")
    print("预期: 走 rule_only 路径，零 LLM 调用，<100ms")
    print("-" * 70)
    
    service = RoutePlannerService()
    req = PlanRequest(
        city="杭州",
        start_time="09:00",
        end_time="18:00",
        budget=500,
        preferences=["美食", "拍照"],
        travelers="情侣",
        pace="悠闲"
    )
    
    start = time.time()
    resp = service.plan(req)
    elapsed_ms = (time.time() - start) * 1000
    
    print(f"\n[筛选结果]")
    print(f"  策略: rule_only")
    print(f"  候选池: {resp.candidate_pois_count} 个 POI")
    print(f"  耗时: {elapsed_ms:.1f}ms")
    print(f"  生成方案: {len(resp.plans)} 套")
    
    for plan in resp.plans:
        print(f"\n  >> {plan.theme} ({plan.poi_count} 个地点)")
        print(f"    描述: {plan.description}")
        print(f"    总用时: {plan.total_time} | 总花费: {plan.total_cost} 元")
        for seg in plan.segments:
            reasons = seg.selection_reasons
            print(f"    - {seg.poi.name} ({seg.arrive_time}-{seg.leave_time})")
            for r in reasons[:2]:
                print(f"      -- {r}")
    print()


def demo_hybrid_path():
    print("=" * 70)
    print("[路径 B] HYBRID - 混合筛选 (想吃辣的人少的地方)")
    print("=" * 70)
    print("输入: raw_query='想吃辣的人少的地方' (隐性需求: 吃辣 + 人少)")
    print("预期: 规则粗筛 249->20, LLM 精筛识别隐性需求, 融合排序")
    print("-" * 70)
    
    service = RoutePlannerService()
    patch_service(service)
    
    req = PlanRequest(
        city="杭州",
        raw_query="想吃辣的人少的地方",
        start_time="09:00",
        end_time="18:00",
        budget=300,
        preferences=["美食"],
        travelers="朋友",
        pace="适中"
    )
    
    start = time.time()
    resp = service.plan(req)
    elapsed_s = time.time() - start
    
    # 注入 Mock LLM 推荐理由
    for plan in resp.plans:
        mock_reasons = mock_generate_poi_reasons(plan, resp.user_preference, raw_query=req.raw_query)
        # apply_llm_reasons_to_plan 会将 LLM 理由添加到 selection_reasons 开头
        # 先清除之前可能存在的 LLM 理由，避免重复
        plan.segments = [seg for seg in plan.segments]
        for seg in plan.segments:
            seg.selection_reasons = [r for r in seg.selection_reasons if not r.startswith('[LLM]')]
        apply_llm_reasons_to_plan(plan, mock_reasons)
    
    cache_key = list(service.plan_cache.keys())[-1]
    meta = service.plan_cache[cache_key].get("filter_metadata", {})
    
    print(f"\n[筛选过程]")
    print(f"  策略: {meta.get('strategy', 'hybrid')}")
    print(f"  输入 POI 数: {meta.get('input_count', 249)}")
    print(f"  规则粗筛后: 约 80 个 (排除 avoid、预算硬约束)")
    print(f"  规则预打分 Top20 -> LLM 精筛")
    print(f"  输出 POI 数: {resp.candidate_pois_count} 个")
    print(f"  识别隐性需求: {meta.get('hidden_needs', [])}")
    print(f"  总耗时: {elapsed_s:.1f}s")
    
    print(f"\n[分数融合示例]")
    print(f"  规则分数 x 0.4 + LLM 分数 x 0.6 = 最终分数")
    print(f"  (LLM 识别出'吃辣'、'人少'等隐性需求的 POI 得分更高)")
    
    print(f"\n[生成方案]")
    for plan in resp.plans:
        print(f"\n  >> {plan.theme} ({plan.poi_count} 个地点)")
        print(f"    描述: {plan.description}")
        print(f"    总用时: {plan.total_time} | 总花费: {plan.total_cost} 元")
        for seg in plan.segments:
            reasons = seg.selection_reasons
            print(f"    - {seg.poi.name} ({seg.arrive_time}-{seg.leave_time})")
            for r in reasons[:3]:
                print(f"      -- {r}")
    print()


def demo_complex_path():
    print("=" * 70)
    print("[路径 C] COMPLEX - LLM 主导 (3+ 隐性需求)")
    print("=" * 70)
    print("输入: raw_query='想吃辣的人少安静有历史感的地方'")
    print("预期: 宽松过滤后, LLM 分批全量评估, 主导排序")
    print("-" * 70)
    
    service = RoutePlannerService()
    patch_service(service)
    
    req = PlanRequest(
        city="杭州",
        raw_query="想吃辣的人少安静有历史感的地方",
        start_time="09:00",
        end_time="18:00",
        budget=300,
        preferences=["美食", "文化"],
        travelers="情侣",
        pace="悠闲"
    )
    
    start = time.time()
    resp = service.plan(req)
    elapsed_s = time.time() - start
    
    cache_key = list(service.plan_cache.keys())[-1]
    meta = service.plan_cache[cache_key].get("filter_metadata", {})
    
    print(f"\n[筛选过程]")
    print(f"  策略: {meta.get('strategy', 'llm_dominant')}")
    print(f"  输入 POI 数: {meta.get('input_count', 249)}")
    print(f"  宽松过滤后: 约 150 个 (只排除明显不符的)")
    print(f"  LLM 分批评估: {meta.get('input_count', 249)} 个 POI (batch_size=10)")
    print(f"  输出 POI 数: {resp.candidate_pois_count} 个")
    print(f"  识别隐性需求: {meta.get('hidden_needs', [])}")
    print(f"  总耗时: {elapsed_s:.1f}s")
    
    print(f"\n[生成方案]")
    for plan in resp.plans:
        print(f"\n  >> {plan.theme} ({plan.poi_count} 个地点)")
        print(f"    描述: {plan.description}")
        for seg in plan.segments:
            print(f"    - {seg.poi.name} ({seg.arrive_time}-{seg.leave_time})")
    print()


def demo_source_tagging():
    print("=" * 70)
    print("[推荐理由来源标注]")
    print("=" * 70)
    print("每条 selection_reasons 都明确标注来源:")
    print()
    print("  [规则] 匹配你的美食偏好")
    print("  [规则] 上午光线柔和，适合拍照")
    print("  [规则] 评分高达4.8分")
    print("  [LLM] 正宗川菜满足你的'吃辣'需求 (麻辣指数高)")
    print("  [LLM] 非网红老店，符合'人少安静'的期望")
    print("  [LLM] 古建筑群拍照出片，满足拍照+安静双重需求")
    print()
    print("  -> 前端无需显示来源标签，仅用于系统调试和可解释性")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  混合 POI 筛选器 - 完整 Mock 演示")
    print("=" * 70)
    print()
    
    demo_simple_path()
    demo_hybrid_path()
    demo_complex_path()
    demo_source_tagging()
    
    print("=" * 70)
    print("  演示结束")
    print("=" * 70)
