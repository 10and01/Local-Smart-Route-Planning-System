# -*- coding: utf-8 -*-
"""
个性化效果离线评测框架（增强版）
支持三层对比：
  A组: 规则解析偏好（无画像，preferences为空）
  B组: LLM解析偏好（无画像）
  C组: LLM解析偏好 + 历史画像融合

评测用例设计：
  - 去掉明确的 preferences，让LLM纯从 raw_query 解析
  - 同一query配不同画像，验证画像影响力
"""

import json
from typing import List, Dict, Optional, Tuple

from backend.models.schemas import POI, UserPreference, PlanRequest, RouteConstraints, Location
from backend.core.route_engine import generate_preference_variants
from backend.core.personalization import UserPersonalizationEngine
from backend.core.preference import parse_preference_from_request
from backend.core.llm_parser import parse_preference_from_llm


# ============================================================================
# 模拟画像集（由LLM从用户画像文本生成）
# ============================================================================

MOCK_PROFILES = {
    "亲子型": UserPreference(
        theme_weights={"自然": 0.9, "娱乐": 0.8, "美食": 0.5, "拍照": 0.4, "文化": 0.3, "购物": 0.2},
        traveler_type="亲子",
        pace_preference="适中",
        price_sensitivity=0.3,
        willingness_to_queue=0.2,
        willingness_to_walk=0.4,
    ),
    "情侣型": UserPreference(
        theme_weights={"拍照": 0.95, "美食": 0.8, "文化": 0.6, "自然": 0.5, "购物": 0.3, "娱乐": 0.4},
        traveler_type="情侣",
        pace_preference="悠闲",
        price_sensitivity=0.4,
        willingness_to_queue=0.5,
        willingness_to_walk=0.6,
    ),
    "美食型": UserPreference(
        theme_weights={"美食": 0.95, "文化": 0.5, "拍照": 0.4, "自然": 0.2, "购物": 0.3, "娱乐": 0.5},
        traveler_type="朋友",
        pace_preference="适中",
        price_sensitivity=0.6,
        willingness_to_queue=0.7,
        willingness_to_walk=0.5,
    ),
    "户外型": UserPreference(
        theme_weights={"自然": 0.95, "拍照": 0.7, "文化": 0.3, "美食": 0.2, "购物": 0.1, "娱乐": 0.3},
        traveler_type="独自",
        pace_preference="紧凑",
        price_sensitivity=0.2,
        willingness_to_queue=0.3,
        willingness_to_walk=0.9,
    ),
    "文化型": UserPreference(
        theme_weights={"文化": 0.95, "美食": 0.6, "拍照": 0.5, "自然": 0.4, "购物": 0.3, "娱乐": 0.2},
        traveler_type="独自",
        pace_preference="适中",
        price_sensitivity=0.3,
        willingness_to_queue=0.4,
        willingness_to_walk=0.6,
    ),
    "购物型": UserPreference(
        theme_weights={"购物": 0.95, "美食": 0.7, "拍照": 0.6, "娱乐": 0.5, "文化": 0.3, "自然": 0.2},
        traveler_type="朋友",
        pace_preference="紧凑",
        price_sensitivity=0.5,
        willingness_to_queue=0.6,
        willingness_to_walk=0.7,
    ),
}


# ============================================================================
# 评测核心函数
# ============================================================================

def _extract_plan_signature(plans: List) -> List[Dict]:
    """提取路线的可比较特征"""
    return [
        {
            "theme": getattr(p, "theme", "unknown"),
            "poi_names": [s.poi.name for s in p.segments],
            "categories": [s.poi.category for s in p.segments],
            "tags": list(set(t for s in p.segments for t in s.poi.tags)),
        }
        for p in plans
    ]


def _compute_plan_diff(plans_a: List, plans_b: List) -> float:
    """计算两套方案的差异度（0=完全相同，1=完全不同）"""
    names_a = set(s.poi.name for p in plans_a for s in p.segments)
    names_b = set(s.poi.name for p in plans_b for s in p.segments)
    intersection = len(names_a & names_b)
    union = len(names_a | names_b)
    return 1.0 - (intersection / union) if union > 0 else 0.0


def _build_base_pref(request: PlanRequest) -> UserPreference:
    """将请求转换为规则解析的 UserPreference（preferences为空时所有标签0.25）"""
    return parse_preference_from_request(
        preferences=request.preferences,
        travelers=getattr(request, "travelers", getattr(request, "traveler_type", "独自")),
        pace=request.pace,
        budget=request.budget
    )


def evaluate_personalization_impact(
    candidates: List[POI],
    base_request: PlanRequest,
    constraints: RouteConstraints,
    profile_name: str,
    profile_pref: UserPreference,
    llm_pref: Optional[UserPreference] = None,
    fusion_alpha: float = 0.3
) -> Dict:
    """
    三层对比评测：
      A组: 规则解析偏好（无画像，preferences为空时所有权重0.25）
      B组: LLM解析偏好（无画像）
      C组: LLM解析偏好 + 历史画像融合
    """
    engine = UserPersonalizationEngine()
    engine.fusion_alpha = fusion_alpha

    # A组：规则解析偏好（无画像）
    rule_pref = _build_base_pref(base_request)
    plans_rule = generate_preference_variants(candidates, rule_pref, constraints)

    # B组：LLM解析偏好（无画像）
    if llm_pref is None and base_request.raw_query and base_request.raw_query.strip():
        llm_pref = parse_preference_from_llm(
            raw_query=base_request.raw_query,
            preferences=base_request.preferences,
            travelers=getattr(base_request, "travelers", getattr(base_request, "traveler_type", "独自")),
            pace=base_request.pace,
            budget=base_request.budget,
            must_visit=base_request.must_visit,
            avoid=base_request.avoid,
            transport_mode=base_request.transport_mode,
        )

    if llm_pref is None:
        llm_pref = rule_pref

    plans_llm = generate_preference_variants(candidates, llm_pref, constraints)

    # C组：LLM解析偏好 + 历史画像融合
    fused = engine.fuse_preferences(llm_pref, profile_pref)
    plans_fused = generate_preference_variants(candidates, fused, constraints)

    # 计算三层差异度
    diff_rule_vs_llm = _compute_plan_diff(plans_rule, plans_llm)
    diff_llm_vs_fused = _compute_plan_diff(plans_llm, plans_fused)
    diff_rule_vs_fused = _compute_plan_diff(plans_rule, plans_fused)

    report = {
        "profile": profile_name,
        "plans_rule_count": len(plans_rule),
        "plans_llm_count": len(plans_llm),
        "plans_fused_count": len(plans_fused),
        "diff_rule_vs_llm": round(diff_rule_vs_llm, 3),
        "diff_llm_vs_fused": round(diff_llm_vs_fused, 3),
        "diff_rule_vs_fused": round(diff_rule_vs_fused, 3),
        "llm_parsed": llm_pref is not rule_pref,
        "llm_pref_summary": {
            "theme_weights": llm_pref.theme_weights if llm_pref else {},
            "traveler_type": llm_pref.traveler_type if llm_pref else "",
            "budget_level": llm_pref.budget_level if llm_pref else "",
            "willingness_to_queue": llm_pref.willingness_to_queue if llm_pref else 0,
        } if llm_pref is not rule_pref else None,
        "signature_rule": _extract_plan_signature(plans_rule),
        "signature_llm": _extract_plan_signature(plans_llm),
        "signature_fused": _extract_plan_signature(plans_fused),
    }
    return report


def run_batch_evaluation(
    city: str = "杭州",
    queries: Optional[List[Dict]] = None
) -> Dict:
    """
    批量评测：对多个模糊query和多个画像运行评测
    重点验证：同一query + 不同画像 的推荐差异
    """
    from backend.data.loader import get_cached_pois

    if queries is None:
        # 去掉明确的 preferences，让LLM纯从 raw_query 解析
        queries = [
            {"raw_query": "周末带女朋友去杭州玩，喜欢拍照和吃辣", "preferences": [], "traveler_type": "情侣"},
            {"raw_query": "带小孩去杭州，想爬山和看博物馆", "preferences": [], "traveler_type": "亲子"},
            {"raw_query": "一个人去杭州，预算有限，喜欢安静的地方", "preferences": [], "traveler_type": "独自", "budget": 200},
            {"raw_query": "和朋友一起去杭州，想吃遍美食，不怕排队", "preferences": [], "traveler_type": "朋友"},
            {"raw_query": "喜欢历史文化，想参观古迹和博物馆", "preferences": [], "traveler_type": "独自"},
        ]

    candidates = get_cached_pois(city)
    if not candidates:
        print("[Eval] 无候选POI，跳过评测")
        return {}

    from backend.data.loader import get_city_center
    center = get_city_center(city)
    start_point = Location(lat=center["lat"], lng=center["lng"]) if center else None

    all_reports = []
    profile_scores = {name: {"llm": [], "fused": [], "total": []} for name in MOCK_PROFILES}

    for q in queries:
        request = PlanRequest(
            city=city,
            preferences=q.get("preferences", []),  # 可能为空列表
            traveler_type=q.get("traveler_type", "独自"),
            budget=q.get("budget", 500),
            raw_query=q.get("raw_query", ""),
            start_time="09:00",
            end_time="18:00",
            transport_mode="步行",
            pace="适中",
        )
        constraints = RouteConstraints(
            city=city,
            start_time="09:00",
            end_time="18:00",
            start_point=start_point,
            budget=request.budget,
            transport_mode="步行",
        )

        # 每个query只调用一次LLM解析，复用给所有画像
        llm_pref = None
        if request.raw_query and request.raw_query.strip():
            print(f"[Eval] LLM解析 query: {request.raw_query[:40]}...")
            llm_pref = parse_preference_from_llm(
                raw_query=request.raw_query,
                preferences=request.preferences,
                travelers=getattr(request, "travelers", getattr(request, "traveler_type", "独自")),
                pace=request.pace,
                budget=request.budget,
                must_visit=request.must_visit,
                avoid=request.avoid,
                transport_mode=request.transport_mode,
            )
            if llm_pref:
                print(f"[Eval]   -> LLM解析成功: "
                      f"theme={ {k:v for k,v in llm_pref.theme_weights.items() if v>0.3} }, "
                      f"traveler={llm_pref.traveler_type}, budget={llm_pref.budget_level}")
            else:
                print(f"[Eval]   -> LLM解析失败，回退到规则解析")

        for profile_name, profile_pref in MOCK_PROFILES.items():
            report = evaluate_personalization_impact(
                candidates, request, constraints, profile_name, profile_pref,
                llm_pref=llm_pref
            )
            all_reports.append(report)
            profile_scores[profile_name]["llm"].append(report["diff_rule_vs_llm"])
            profile_scores[profile_name]["fused"].append(report["diff_llm_vs_fused"])
            profile_scores[profile_name]["total"].append(report["diff_rule_vs_fused"])

    # 汇总统计
    summary = {}
    for name, scores in profile_scores.items():
        summary[name] = {
            "avg_llm_diff": round(sum(scores["llm"]) / len(scores["llm"]), 3) if scores["llm"] else 0,
            "avg_fused_diff": round(sum(scores["fused"]) / len(scores["fused"]), 3) if scores["fused"] else 0,
            "avg_total_diff": round(sum(scores["total"]) / len(scores["total"]), 3) if scores["total"] else 0,
            "max_total_diff": round(max(scores["total"]), 3) if scores["total"] else 0,
            "min_total_diff": round(min(scores["total"]), 3) if scores["total"] else 0,
            "sample_count": len(scores["total"]),
        }

    overall_avg_llm = sum(r["diff_rule_vs_llm"] for r in all_reports) / len(all_reports) if all_reports else 0
    overall_avg_fused = sum(r["diff_llm_vs_fused"] for r in all_reports) / len(all_reports) if all_reports else 0
    overall_avg_total = sum(r["diff_rule_vs_fused"] for r in all_reports) / len(all_reports) if all_reports else 0

    return {
        "summary_by_profile": summary,
        "overall_avg_llm_diff": round(overall_avg_llm, 3),
        "overall_avg_fused_diff": round(overall_avg_fused, 3),
        "overall_avg_total_diff": round(overall_avg_total, 3),
        "total_comparisons": len(all_reports),
        "detail_reports": all_reports,
    }


def print_evaluation_report(report: Dict):
    """打印评测报告"""
    print("\n" + "=" * 70)
    print("个性化效果离线评测报告（增强版：规则 vs LLM vs 画像融合）")
    print("=" * 70)
    print(f"\n总对比次数: {report.get('total_comparisons', 0)}")
    print(f"整体平均差异度:")
    print(f"  规则 vs LLM解析:     {report.get('overall_avg_llm_diff', 0)}")
    print(f"  LLM解析 vs 画像融合: {report.get('overall_avg_fused_diff', 0)}")
    print(f"  规则 vs 画像融合:    {report.get('overall_avg_total_diff', 0)}")

    print("\n按画像类型统计:")
    for name, stats in report.get("summary_by_profile", {}).items():
        llm_pass = "PASS" if stats["avg_llm_diff"] > 0.1 else "FAIL"
        fused_pass = "PASS" if stats["avg_fused_diff"] > 0.15 else "FAIL"
        total_pass = "PASS" if stats["avg_total_diff"] > 0.2 else "FAIL"
        print(f"  [{llm_pass}/{fused_pass}/{total_pass}] {name:6s}: "
              f"规则vsLLM={stats['avg_llm_diff']:.3f} | "
              f"LLMvs画像={stats['avg_fused_diff']:.3f} | "
              f"总差异={stats['avg_total_diff']:.3f} "
              f"(n={stats['sample_count']})")

    # 展示一个典型案例
    print("\n典型案例（同一query + 不同画像的POI选择差异）:")
    reports = report.get("detail_reports", [])
    if reports:
        sample = reports[0]
        print(f"  Query: {sample.get('query', 'N/A')}")
        print(f"  规则解析POI: {sample.get('signature_rule', [{}])[0].get('poi_names', [])}")
        print(f"  LLM解析POI:  {sample.get('signature_llm', [{}])[0].get('poi_names', [])}")
        print(f"  画像融合POI: {sample.get('signature_fused', [{}])[0].get('poi_names', [])}")

    print("\n通过标准:")
    llm_passed = sum(1 for s in report.get("summary_by_profile", {}).values() if s["avg_llm_diff"] > 0.1)
    fused_passed = sum(1 for s in report.get("summary_by_profile", {}).values() if s["avg_fused_diff"] > 0.15)
    total_passed = sum(1 for s in report.get("summary_by_profile", {}).values() if s["avg_total_diff"] > 0.2)
    total_profiles = len(report.get("summary_by_profile", {}))
    print(f"  LLM解析改变推荐 (>0.1):    {llm_passed}/{total_profiles}")
    print(f"  画像融合改变推荐 (>0.15):  {fused_passed}/{total_profiles}")
    print(f"  端到端差异显著 (>0.2):     {total_passed}/{total_profiles}")
    print("=" * 70)
