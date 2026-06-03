# -*- coding: utf-8 -*-
"""
LLM 精排模块 (LLM Reranker)

核心职责：
  1. 接收规则粗排后的 Top-N 候选 POI（默认 20 个）
  2. 将 POI 详细信息 + 用户画像输入 LLM
  3. 获取 LLM 对每个 POI 的个性化评分、推荐理由、排除理由
  4. 融合规则分数 × 0.6 + LLM 分数 × 0.4 = 最终分数

架构位置：
  规则粗排 → Top-20 候选 POI
      ↓
  [LLM 精排] —— 1 次 LLM 调用（约 1500 tokens）
      ↓
  输出每个 POI 的个性化评分 + 推荐理由
      ↓
  融合分数 → 贪心选择 → 2-opt

使用 OpenAI-compatible API:
  - model: gpt-5.5
  - base_url: https://dxb.huifei.net/v1
"""

import json
import math
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

from backend.models.schemas import POI, UserPreference
from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config

from openai import OpenAI, APITimeoutError, RateLimitError, APIError

# ---------------------------------------------------------------------------
# API 配置
# ---------------------------------------------------------------------------
API_KEY = LLM_API_KEY
BASE_URL = LLM_BASE_URL
MODEL_NAME = LLM_MODEL_NAME

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------

class POIRerankResult(BaseModel):
    """单个 POI 的精排结果"""
    poi_id: str = Field(..., description="POI 唯一标识")
    name: str = Field(..., description="POI 名称")
    llm_score: float = Field(0.0, description="LLM 个性化评分 0-100", ge=0, le=100)
    rule_score: float = Field(0.0, description="规则粗排分数 0-100", ge=0, le=100)
    final_score: float = Field(0.0, description="融合后最终分数", ge=0, le=100)
    recommendation_reason: Optional[str] = Field(None, description="推荐理由")
    exclusion_reason: Optional[str] = Field(None, description="排除理由（如不适合）")


# ---------------------------------------------------------------------------
# JSON 清理
# ---------------------------------------------------------------------------

def _clean_llm_json(content: str) -> str:
    """清理 LLM 返回的内容，提取纯 JSON 部分。"""
    if not content:
        return "{}"
    content = content.strip()
    # Remove <think>...</think> tags (reasoning content from some models)
    while "<think>" in content and "</think>" in content:
        start = content.find("<think>")
        end = content.find("</think>") + len("</think>")
        content = content[:start] + content[end:]
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if not (content.startswith("{") or content.startswith("[")):
        start_obj = content.find("{")
        start_arr = content.find("[")
        if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
            end = content.rfind("}")
            if end != -1:
                content = content[start_obj:end + 1]
        elif start_arr != -1:
            end = content.rfind("]")
            if end != -1:
                content = content[start_arr:end + 1]
    return content


# ---------------------------------------------------------------------------
# Prompt 设计
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一位专业的旅行规划精排专家。你的任务是根据用户画像，对候选 POI 列表中的每个地点进行精细化评估，给出个性化评分和推荐理由/排除理由。

评估维度（综合给出 0-100 分）：
1. 画像匹配度：POI 是否符合用户的偏好主题、人群、节奏
2. UGC 负面信息识别：从评论摘要中识别"排队2小时""最近在装修""人太多"等负面信号
3. 协同关系：POI 之间是否在地理上邻近或主题上互补
4. 特殊需求：是否满足用户的隐含需求（如"带孩子去博物馆，最好有休息区"）

输出格式（严格 JSON，不要 markdown 代码块）：
{
  "results": [
    {
      "poi_name": "POI名称",
      "score": 0~100,
      "reason": "一句话推荐理由（15-30字）",
      "exclude_reason": null 或 "一句话排除理由"
    }
  ]
}

评分规则：
- 80-100：强烈推荐，完美匹配用户画像且无明显负面信息
- 60-79：推荐，基本匹配但有小瑕疵
- 40-59：一般，匹配度不高或有一些负面信息
- 20-39：不太推荐，明显不适合用户
- 0-19：强烈不推荐，有严重负面信息或与用户画像冲突
- 如果 POI 有 UGC 负面预警（如排队、装修、人太多），必须降低分数并在 exclude_reason 中说明
- 每个 POI 都必须输出，不能遗漏
"""


def _build_poi_detail_text(poi: POI, rank: int, distance_m: Optional[int] = None) -> str:
    """构建单个 POI 的文本描述，供 LLM 精排使用。"""
    lines = [
        f"{rank}. {poi.name}",
        f"   类别：{poi.category}",
    ]
    if poi.sub_category:
        lines.append(f"   二级分类：{poi.sub_category}")
    lines.append(f"   评分：{poi.rating if poi.rating is not None else '无'}")
    lines.append(f"   价格：{poi.price if poi.price is not None else '未知'} 元")
    if distance_m is not None:
        lines.append(f"   距离起点：{distance_m / 1000:.1f} km")
    if poi.tags:
        lines.append(f"   标签：{', '.join(poi.tags[:6])}")
    if poi.ugc_keywords:
        lines.append(f"   UGC关键词：{', '.join(poi.ugc_keywords[:5])}")
    if poi.ugc_sentiment_score != 0:
        lines.append(f"   UGC情感分：{poi.ugc_sentiment_score:+.2f}")
    if poi.ugc_recent_warn:
        lines.append(f"   ⚠️ 近期预警：{poi.ugc_recent_warn}")
    if poi.highlights:
        lines.append(f"   亮点：{poi.highlights}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 核心函数：LLM 精排
# ---------------------------------------------------------------------------

def rerank_pois_with_llm(
    pois: List[POI],
    user_pref: UserPreference,
    raw_query: Optional[str] = None,
    distances_m: Optional[Dict[str, int]] = None,
    timeout: int = 30,
) -> Dict[str, POIRerankResult]:
    """
    调用 LLM 对 Top-N POI 进行精排。

    Args:
        pois: 候选 POI 列表（建议 20 个以内）
        user_pref: 用户画像
        raw_query: 用户原始自然语言 query
        distances_m: POI ID → 距离起点米数的映射（可选）
        timeout: LLM 调用超时（秒）

    Returns:
        Dict[poi_name, POIRerankResult]：每个 POI 的精排结果
    """
    if not pois:
        return {}

    if not check_llm_config():
        print("[LLM Reranker] LLM 配置不完整，跳过精排")
        return {}

    # 构建用户画像摘要
    profile_lines = [
        f"- 出行人群：{user_pref.traveler_type}",
        f"- 节奏偏好：{user_pref.pace_preference}",
        f"- 预算级别：{user_pref.budget_level or '未指定'}",
        f"- 价格敏感度：{user_pref.price_sensitivity:.0%}",
        f"- 排队意愿：{user_pref.willingness_to_queue:.0%}",
        f"- 走路意愿：{user_pref.willingness_to_walk:.0%}",
    ]
    if user_pref.theme_weights:
        themes = ", ".join(f"{k}({v:.0%})" for k, v in user_pref.theme_weights.items() if v > 0.2)
        profile_lines.append(f"- 偏好主题：{themes}")

    profile_text = "\n".join(profile_lines)

    # 构建 POI 详情文本
    poi_details = []
    for i, poi in enumerate(pois, 1):
        dist = distances_m.get(poi.poi_id) if distances_m else None
        poi_details.append(_build_poi_detail_text(poi, i, dist))
    poi_text = "\n\n".join(poi_details)

    user_context = f"""用户画像：
{profile_text}

原始需求：{raw_query or '未提供'}

候选 POI 列表（共 {len(pois)} 个）：
{poi_text}

请对每个 POI 给出个性化评分（0-100）、推荐理由或排除理由。输出严格 JSON。"""

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_context},
            ],
            temperature=0.3,
            timeout=timeout,
            extra_body={"instructions": "请严格按JSON格式输出，不要添加任何解释或markdown代码块。每个POI都必须输出评分。"},
        )

        content = response.choices[0].message.content
        if not content:
            print("[LLM Reranker] LLM 返回空内容，跳过精排")
            return {}

        clean = _clean_llm_json(content)
        parsed = json.loads(clean)
        results = parsed.get("results", [])

        # 构建返回字典
        result_map: Dict[str, POIRerankResult] = {}
        for item in results:
            name = item.get("poi_name", "")
            score = float(item.get("score", 50))
            reason = item.get("reason")
            exclude = item.get("exclude_reason")
            # 查找对应的 POI
            matched_poi = None
            for p in pois:
                if p.name == name:
                    matched_poi = p
                    break
            if matched_poi:
                result_map[name] = POIRerankResult(
                    poi_id=matched_poi.poi_id,
                    name=name,
                    llm_score=max(0, min(100, score)),
                    rule_score=0.0,  # 由上层填充
                    final_score=0.0,  # 由上层填充
                    recommendation_reason=reason if reason and reason != "null" else None,
                    exclusion_reason=exclude if exclude and exclude != "null" else None,
                )

        print(f"[LLM Reranker] 成功精排 {len(result_map)} 个 POI")
        return result_map

    except APITimeoutError:
        print("[LLM Reranker] LLM 调用超时，跳过精排")
        return {}
    except RateLimitError:
        print("[LLM Reranker] LLM 速率限制(429)，跳过精排")
        return {}
    except APIError as e:
        print(f"[LLM Reranker] LLM API 错误({e.status_code if hasattr(e, 'status_code') else 'unknown'})，跳过精排")
        return {}
    except Exception as e:
        print(f"[LLM Reranker] 精排失败，跳过。错误：{e}")
        return {}


# ---------------------------------------------------------------------------
# 分数融合
# ---------------------------------------------------------------------------

def fuse_scores(
    rule_scores: Dict[str, float],
    llm_results: Dict[str, POIRerankResult],
    rule_weight: float = 0.6,
    llm_weight: float = 0.4,
) -> Dict[str, POIRerankResult]:
    """
    融合规则分数和 LLM 精排分数。

    Args:
        rule_scores: {poi_name: rule_score_raw}，原始规则分数（可为任意范围）
        llm_results: {poi_name: POIRerankResult}，LLM 精排结果
        rule_weight: 规则分数权重（默认 0.6）
        llm_weight: LLM 分数权重（默认 0.4）

    Returns:
        完整的 POIRerankResult 字典，包含融合后的 final_score
    """
    if not rule_scores:
        return {}

    # 规则分数归一化到 0-100
    max_rule = max(rule_scores.values()) if rule_scores else 1.0
    min_rule = min(rule_scores.values()) if rule_scores else 0.0
    rule_range = max_rule - min_rule if max_rule > min_rule else 1.0

    fused: Dict[str, POIRerankResult] = {}
    for name, raw_rule in rule_scores.items():
        # 归一化规则分数
        norm_rule = (raw_rule - min_rule) / rule_range * 100
        norm_rule = max(0, min(100, norm_rule))

        llm_res = llm_results.get(name)
        if llm_res:
            llm_score = llm_res.llm_score
            final = norm_rule * rule_weight + llm_score * llm_weight
            fused[name] = POIRerankResult(
                poi_id=llm_res.poi_id,
                name=name,
                llm_score=llm_score,
                rule_score=round(norm_rule, 1),
                final_score=round(final, 1),
                recommendation_reason=llm_res.recommendation_reason,
                exclusion_reason=llm_res.exclusion_reason,
            )
        else:
            # LLM 未返回该 POI，只使用规则分数
            fused[name] = POIRerankResult(
                poi_id="",
                name=name,
                llm_score=0.0,
                rule_score=round(norm_rule, 1),
                final_score=round(norm_rule, 1),
                recommendation_reason=None,
                exclusion_reason=None,
            )

    return fused


# ---------------------------------------------------------------------------
# 便捷函数：一次性完成精排 + 融合
# ---------------------------------------------------------------------------

def rerank_and_fuse(
    pois: List[POI],
    rule_scores: Dict[str, float],
    user_pref: UserPreference,
    raw_query: Optional[str] = None,
    distances_m: Optional[Dict[str, int]] = None,
    rule_weight: float = 0.6,
    llm_weight: float = 0.4,
) -> Dict[str, POIRerankResult]:
    """
    一站式精排 + 融合。

    先调用 LLM 精排，再与规则分数融合，返回最终排序结果。
    如果 LLM 调用失败，只返回规则分数（final_score = rule_score）。
    """
    llm_results = rerank_pois_with_llm(pois, user_pref, raw_query, distances_m)
    return fuse_scores(rule_scores, llm_results, rule_weight, llm_weight)
