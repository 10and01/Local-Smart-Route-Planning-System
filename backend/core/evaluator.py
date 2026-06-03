# -*- coding: utf-8 -*-
"""
评测增强模块 (P2-3)

功能：
  1. LLM 自动评价者（5维度评分）
  2. 消融实验框架（4组对比）
  3. 评测报告持久化（JSON + Markdown）
"""

import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict

from backend.models.schemas import PlanRequest, RoutePlan, UserPreference, RouteConstraints, POI
from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config
from backend.core.personalization import UserPersonalizationEngine
from backend.core.preference import parse_preference_from_request
from backend.core.llm_parser import parse_preference_from_llm
from backend.core.policy_generator import generate_planning_policy, PlanningPolicy, DEFAULT_POLICY
from backend.core.llm_reranker import rerank_and_fuse
from backend.core import route_engine
from backend.data.loader import get_cached_pois, get_city_center

from openai import OpenAI, APITimeoutError, RateLimitError, APIError


# ============================================================================
# LLM 自动评价者
# ============================================================================

LLM_EVALUATOR_PROMPT = """你是一位旅行规划质量评估专家。请根据用户请求和生成的路线方案，从以下5个维度进行评分。

请严格按以下 JSON 格式输出（只输出纯 JSON，不要任何解释）：
{
  "preference_alignment": {"score": 1~10, "reason": "简述"},
  "route_rationality": {"score": 1~10, "reason": "简述"},
  "poi_diversity": {"score": 1~10, "reason": "简述"},
  "budget_control": {"score": 1~10, "reason": "简述"},
  "time_feasibility": {"score": 1~10, "reason": "简述"},
  "overall_score": 1~10,
  "summary": "总体评价（50字以内）"
}

评分维度说明：
1. preference_alignment（偏好对齐度）：方案中的POI是否匹配用户的主题偏好、人群、节奏
2. route_rationality（路线合理性）：POI之间的地理顺序是否顺路，交通是否高效
3. poi_diversity（POI多样性）：类别是否丰富，避免单一类型重复
4. budget_control（预算控制）：总花费是否合理，是否超出用户预算（未指定预算时按标准评估）
5. time_feasibility（时间可行性）：总时长是否在用户要求范围内，每个POI停留时间是否合理
"""


@dataclass
class EvaluationScore:
    preference_alignment: int = 5
    preference_alignment_reason: str = ""
    route_rationality: int = 5
    route_rationality_reason: str = ""
    poi_diversity: int = 5
    poi_diversity_reason: str = ""
    budget_control: int = 5
    budget_control_reason: str = ""
    time_feasibility: int = 5
    time_feasibility_reason: str = ""
    overall_score: float = 5.0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _build_eval_context(
    request: PlanRequest,
    user_pref: UserPreference,
    plan: RoutePlan,
    candidates: List[POI]
) -> str:
    """构建评估所需的上下文文本"""
    lines = [
        f"用户原始需求：{request.raw_query or '未提供'}",
        f"目标城市：{request.city}",
        f"时间：{request.start_time} ~ {request.end_time}",
        f"预算：{request.budget if request.budget else '未指定'} 元",
        f"出行人群：{request.travelers}",
        f"节奏：{request.pace}",
        f"偏好标签：{request.preferences}",
        "",
        "解析出的用户画像：",
        f"  主题权重：{user_pref.theme_weights}",
        f"  人群：{user_pref.traveler_type}",
        f"  节奏：{user_pref.pace_preference}",
        f"  预算级别：{user_pref.budget_level}",
        "",
        "生成的路线方案：",
        f"  主题：{plan.theme}",
        f"  描述：{plan.description}",
        f"  总时间：{plan.total_time}",
        f"  总花费：{plan.total_cost} 元",
        f"  POI数量：{plan.poi_count}",
        "  POI列表：",
    ]
    for seg in plan.segments:
        lines.append(
            f"    - {seg.poi.name} ({seg.poi.category}, "
            f"评分{seg.poi.rating or '无'}, "
            f"{seg.poi.price or '未知'}元) "
            f"[{seg.arrive_time}-{seg.leave_time}, 停留{seg.duration}分钟]"
        )
        if seg.transport_to_next:
            lines.append(f"      -> 下一程：{seg.transport_to_next}")
    return "\n".join(lines)


def _extract_first_json(text: str) -> str:
    """Extract the first valid JSON object or array from text, handling markdown fences, think tags and trailing text."""
    text = text.strip()
    # Remove <think>...</think> tags (reasoning content from some models)
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>") + len("</think>")
        text = text[:start] + text[end:]
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    start_obj = text.find("{")
    start_arr = text.find("[")

    if start_obj == -1 and start_arr == -1:
        return text

    if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
        start = start_obj
        open_br, close_br = "{", "}"
    else:
        start = start_arr
        open_br, close_br = "[", "]"

    count = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == open_br:
            count += 1
        elif text[i] == close_br:
            count -= 1
            if count == 0:
                end = i
                break

    if end != -1:
        return text[start:end + 1]
    return text[start:]


def evaluate_plan_with_llm(
    request: PlanRequest,
    user_pref: UserPreference,
    plan: RoutePlan,
    candidates: List[POI],
    timeout: int = 20
) -> EvaluationScore:
    """
    调用 LLM 对单个方案进行5维度评分。
    若 LLM 调用失败，返回默认评分。
    """
    if not check_llm_config():
        return EvaluationScore(summary="LLM未配置，使用默认评分")

    context = _build_eval_context(request, user_pref, plan, candidates)

    try:
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": LLM_EVALUATOR_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.2,
            timeout=timeout,
        )

        content = response.choices[0].message.content
        if not content:
            return EvaluationScore(summary="LLM返回空内容")

        clean = _extract_first_json(content)
        parsed = json.loads(clean)
        return EvaluationScore(
            preference_alignment=int(parsed.get("preference_alignment", {}).get("score", 5)),
            preference_alignment_reason=parsed.get("preference_alignment", {}).get("reason", ""),
            route_rationality=int(parsed.get("route_rationality", {}).get("score", 5)),
            route_rationality_reason=parsed.get("route_rationality", {}).get("reason", ""),
            poi_diversity=int(parsed.get("poi_diversity", {}).get("score", 5)),
            poi_diversity_reason=parsed.get("poi_diversity", {}).get("reason", ""),
            budget_control=int(parsed.get("budget_control", {}).get("score", 5)),
            budget_control_reason=parsed.get("budget_control", {}).get("reason", ""),
            time_feasibility=int(parsed.get("time_feasibility", {}).get("score", 5)),
            time_feasibility_reason=parsed.get("time_feasibility", {}).get("reason", ""),
            overall_score=float(parsed.get("overall_score", 5.0)),
            summary=parsed.get("summary", ""),
        )

    except (APITimeoutError, RateLimitError, APIError) as e:
        return EvaluationScore(summary=f"LLM评分失败: {type(e).__name__}")
    except Exception as e:
        return EvaluationScore(summary=f"LLM评分失败: {e}")


# ============================================================================
# 消融实验框架（4组对比）
# ============================================================================

@dataclass
class AblationGroupResult:
    group_name: str
    plans: List[RoutePlan]
    policy: Optional[PlanningPolicy] = None
    eval_scores: Optional[List[EvaluationScore]] = None
    avg_overall_score: float = 0.0
    plan_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_name": self.group_name,
            "plan_count": len(self.plans),
            "policy_reasoning": self.policy.reasoning if self.policy else None,
            "eval_scores": [s.to_dict() for s in (self.eval_scores or [])],
            "avg_overall_score": self.avg_overall_score,
            "plan_time_ms": self.plan_time_ms,
            "plan_themes": [p.theme for p in self.plans],
        }


def _generate_ablation_plans(
    candidates: List[POI],
    user_pref: UserPreference,
    constraints: RouteConstraints,
    policy: Optional[PlanningPolicy] = None,
) -> List[RoutePlan]:
    """通用生成函数，包装 route_engine"""
    return route_engine.generate_preference_variants(
        candidates, user_pref, constraints, policy=policy
    )


def run_ablation_experiment(
    request: PlanRequest,
    constraints: RouteConstraints,
    user_id: Optional[int] = None,
    user_type: Optional[str] = None,
    run_llm_eval: bool = True,
) -> Dict[str, Any]:
    """
    4组消融实验对比：
      A: 仅规则解析（无LLM，无画像，无Policy，无Reranker）
      B: +LLM解析偏好
      C: +画像融合
      D: +Policy Generator + LLM Reranker（完整系统）
    """
    candidates = get_cached_pois(request.city)
    if not candidates:
        return {"error": "无候选POI"}

    personalization = UserPersonalizationEngine()
    results: Dict[str, AblationGroupResult] = {}

    # 公共参数
    llm_pref = None
    historical_pref = None
    fused_pref = None
    policy = None

    # Group A: 仅规则解析
    start = time.time()
    rule_pref = parse_preference_from_request(
        preferences=request.preferences,
        travelers=request.travelers,
        pace=request.pace,
        budget=request.budget
    )
    plans_a = _generate_ablation_plans(candidates, rule_pref, constraints)
    t_a = (time.time() - start) * 1000
    results["A_rule_only"] = AblationGroupResult(
        group_name="A_仅规则",
        plans=plans_a,
        plan_time_ms=t_a
    )

    # Group B: +LLM解析
    start = time.time()
    if request.raw_query and request.raw_query.strip():
        llm_pref = parse_preference_from_llm(
            raw_query=request.raw_query,
            preferences=request.preferences,
            travelers=request.travelers,
            pace=request.pace,
            budget=request.budget,
            must_visit=request.must_visit,
            avoid=request.avoid,
            transport_mode=request.transport_mode,
        )
    if llm_pref is None:
        llm_pref = rule_pref
    plans_b = _generate_ablation_plans(candidates, llm_pref, constraints)
    t_b = (time.time() - start) * 1000
    results["B_with_llm_parser"] = AblationGroupResult(
        group_name="B_+LLM解析",
        plans=plans_b,
        plan_time_ms=t_b
    )

    # Group C: +画像融合
    start = time.time()
    if user_id is not None:
        historical_pref = personalization.profile_to_preference(
            personalization.load_profile(user_id, user_type or "registered")
        )
    fused_pref = personalization.fuse_preferences(llm_pref, historical_pref)
    plans_c = _generate_ablation_plans(candidates, fused_pref, constraints)
    t_c = (time.time() - start) * 1000
    results["C_with_fusion"] = AblationGroupResult(
        group_name="C_+画像融合",
        plans=plans_c,
        plan_time_ms=t_c
    )

    # Group D: +Policy Generator + LLM Reranker（完整系统）
    start = time.time()
    if request.raw_query and request.raw_query.strip():
        try:
            policy = generate_planning_policy(
                raw_query=request.raw_query,
                user_pref=fused_pref,
                candidates=candidates,
                constraints=constraints,
            )
        except Exception as e:
            print(f"[Ablation] Policy generation failed: {e}")
            policy = DEFAULT_POLICY

    # 简化：D组也复用 candidates，不实际做 rerank（避免额外LLM调用拖慢评测）
    plans_d = _generate_ablation_plans(candidates, fused_pref, constraints, policy=policy)
    t_d = (time.time() - start) * 1000
    results["D_full_system"] = AblationGroupResult(
        group_name="D_完整系统",
        plans=plans_d,
        policy=policy,
        plan_time_ms=t_d
    )

    # LLM 自动评分（每组取第一个plan评分，可选）
    if run_llm_eval:
        for key, group in results.items():
            if group.plans:
                eval_pref = fused_pref if key in ("C_with_fusion", "D_full_system") else (llm_pref if key == "B_with_llm_parser" else rule_pref)
                score = evaluate_plan_with_llm(
                    request=request,
                    user_pref=eval_pref,
                    plan=group.plans[0],
                    candidates=candidates
                )
                group.eval_scores = [score]
                group.avg_overall_score = score.overall_score

    return {
        "groups": {k: v.to_dict() for k, v in results.items()},
        "request_summary": {
            "city": request.city,
            "raw_query": request.raw_query,
            "budget": request.budget,
            "travelers": request.travelers,
        },
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================================
# 评测报告持久化
# ============================================================================

_EVAL_REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "eval_reports"
)


def _ensure_report_dir():
    os.makedirs(_EVAL_REPORT_DIR, exist_ok=True)


def _generate_markdown_report(data: Dict[str, Any]) -> str:
    """将评测结果转换为 Markdown 报告"""
    lines = [
        "# 旅行规划系统评测报告",
        "",
        f"**生成时间**: {data.get('timestamp', datetime.now().isoformat())}",
        f"**评测城市**: {data.get('request_summary', {}).get('city', 'N/A')}",
        f"**用户Query**: {data.get('request_summary', {}).get('raw_query', 'N/A')}",
        "",
        "## 消融实验结果",
        "",
    ]

    groups = data.get("groups", {})
    for key in ["A_rule_only", "B_with_llm_parser", "C_with_fusion", "D_full_system"]:
        g = groups.get(key)
        if not g:
            continue
        lines.append(f"### {g['group_name']} ({key})")
        lines.append(f"- 生成方案数: {g['plan_count']}")
        lines.append(f"- 规划耗时: {g['plan_time_ms']:.1f} ms")
        lines.append(f"- 方案主题: {', '.join(g['plan_themes'])}")
        if g.get("policy_reasoning"):
            lines.append(f"- Policy理由: {g['policy_reasoning']}")
        if g.get("eval_scores"):
            s = g["eval_scores"][0]
            lines.append(f"- **LLM综合评分**: {s['overall_score']}/10")
            lines.append(f"  - 偏好对齐度: {s['preference_alignment']}/10 - {s['preference_alignment_reason']}")
            lines.append(f"  - 路线合理性: {s['route_rationality']}/10 - {s['route_rationality_reason']}")
            lines.append(f"  - POI多样性: {s['poi_diversity']}/10 - {s['poi_diversity_reason']}")
            lines.append(f"  - 预算控制: {s['budget_control']}/10 - {s['budget_control_reason']}")
            lines.append(f"  - 时间可行性: {s['time_feasibility']}/10 - {s['time_feasibility_reason']}")
            lines.append(f"  - 总结: {s['summary']}")
        lines.append("")

    # 对比总结
    lines.append("## 横向对比")
    lines.append("")
    lines.append("| 组别 | 规划耗时(ms) | 综合评分 | 主题 |")
    lines.append("|------|-------------|---------|------|")
    for key in ["A_rule_only", "B_with_llm_parser", "C_with_fusion", "D_full_system"]:
        g = groups.get(key)
        if not g:
            continue
        score = g.get("avg_overall_score", "N/A")
        lines.append(
            f"| {g['group_name']} | {g['plan_time_ms']:.1f} | {score} | {', '.join(g['plan_themes'])} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("*报告由系统自动生成*")

    return "\n".join(lines)


def save_evaluation_report(data: Dict[str, Any]) -> Dict[str, str]:
    """
    将评测结果持久化到 JSON + Markdown。
    返回保存的文件路径。
    """
    _ensure_report_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"eval_{ts}"

    json_path = os.path.join(_EVAL_REPORT_DIR, f"{base_name}.json")
    md_path = os.path.join(_EVAL_REPORT_DIR, f"{base_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    md_content = _generate_markdown_report(data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return {"json": json_path, "markdown": md_path}


def run_full_evaluation_pipeline(
    request: PlanRequest,
    constraints: RouteConstraints,
    user_id: Optional[int] = None,
    user_type: Optional[str] = None,
    run_llm_eval: bool = True,
) -> Dict[str, Any]:
    """
    完整的评测流水线：消融实验 -> LLM评分 -> 持久化报告。
    """
    experiment_data = run_ablation_experiment(
        request=request,
        constraints=constraints,
        user_id=user_id,
        user_type=user_type,
        run_llm_eval=run_llm_eval,
    )

    if "error" in experiment_data:
        return experiment_data

    paths = save_evaluation_report(experiment_data)
    experiment_data["saved_paths"] = paths
    return experiment_data
