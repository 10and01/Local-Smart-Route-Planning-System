# -*- coding: utf-8 -*-
"""
LLM 策略生成器 (Policy Generator)

核心职责：
  1. 根据用户 query + 历史画像 + 候选 POI 统计摘要，调用 LLM 生成个性化规划参数包
  2. 输出 PlanningPolicy（Pydantic 模型），供规则引擎消费
  3. 提供值域校验、异常 fallback、POI 统计摘要构建等辅助能力

架构位置：
  用户 query + 历史画像 + POI 统计摘要
      ↓
  [LLM Policy Generator] —— 每次规划请求调用 1 次 LLM
      ↓
  输出 PlanningPolicy 对象（JSON）
      ↓
  [规则引擎] —— 纯本地计算，100% 确定性
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from backend.models.schemas import POI, UserPreference, RouteConstraints
from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config

from openai import OpenAI, APITimeoutError, RateLimitError, APIError
import time
import hashlib

# ---------------------------------------------------------------------------
# API 配置
# ---------------------------------------------------------------------------
API_KEY = LLM_API_KEY
BASE_URL = LLM_BASE_URL
MODEL_NAME = LLM_MODEL_NAME

_client: Optional[OpenAI] = None

# Policy 缓存: key -> (timestamp, PlanningPolicy)
_policy_cache: Dict[str, tuple] = {}
_POLICY_CACHE_TTL_SECONDS = 3600  # 1小时


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def _make_policy_cache_key(raw_query: Optional[str], user_pref: UserPreference) -> str:
    """生成 Policy 缓存 key"""
    data = f"{raw_query or ''}|{user_pref.model_dump_json(exclude_none=True)}"
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _get_cached_policy(key: str) -> Optional[PlanningPolicy]:
    """获取缓存的 Policy，若过期返回 None"""
    entry = _policy_cache.get(key)
    if not entry:
        return None
    ts, policy = entry
    if time.time() - ts > _POLICY_CACHE_TTL_SECONDS:
        del _policy_cache[key]
        return None
    print(f"[Policy Generator] 命中缓存 (key={key[:8]}...)")
    return policy


def _set_cached_policy(key: str, policy: PlanningPolicy):
    """缓存 Policy"""
    _policy_cache[key] = (time.time(), policy)
    # 控制缓存大小，防止内存泄漏
    if len(_policy_cache) > 200:
        oldest = min(_policy_cache.keys(), key=lambda k: _policy_cache[k][0])
        del _policy_cache[oldest]


# ---------------------------------------------------------------------------
# Pydantic 模型定义
# ---------------------------------------------------------------------------

class StrategyConfig(BaseModel):
    """单个方案策略配置（深度体验 / 高效省时 / 均衡推荐）"""
    name: str = Field(..., description="策略名称，如'深度体验'")
    description: str = Field(..., description="策略一句话描述")
    config: Dict[str, float] = Field(..., description="策略参数键值对")


class ScoringCoefficients(BaseModel):
    """评分系数：全局默认值 + 关键类别覆盖"""
    global_: Dict[str, float] = Field(default_factory=dict, alias="global")
    category_overrides: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class PlanningPolicy(BaseModel):
    """
    LLM 策略生成器输出的完整参数包
    """
    policy_version: str = "1.0"
    reasoning: str = Field(default="", description="LLM 决策理由")

    # 偏好空间：自由维度 + keyword_map
    preference_space: Dict[str, Any] = Field(default_factory=dict)
    theme_keyword_map: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="每个维度对应的关键词列表，用于 POI 匹配"
    )

    # 画像融合配置
    fusion_config: Dict[str, Any] = Field(default_factory=dict)

    # 评分系数
    scoring_coefficients: ScoringCoefficients = Field(
        default_factory=lambda: ScoringCoefficients(global_={}, category_overrides={})
    )

    # 三套定制化策略
    strategies: List[StrategyConfig] = Field(default_factory=list)

    # 硬性约束覆盖
    hard_constraint_overrides: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 默认 Policy（fallback 用）
# ---------------------------------------------------------------------------

DEFAULT_POLICY = PlanningPolicy(
    policy_version="1.0",
    reasoning="使用默认策略参数",
    preference_space={},
    theme_keyword_map={},
    fusion_config={"alpha": 0.7, "alpha_reason": "默认融合比例"},
    scoring_coefficients=ScoringCoefficients(
        global_={
            "ugc_sentiment_weight": 1.0,
            "scene_match_weight": 1.0,
            "price_sensitivity_weight": 1.0,
            "exploration_bonus_factor": 1.0,
            "distance_penalty_factor": 1.0,
            "time_efficiency_weight": 1.0,
            "queue_bonus_weight": 1.0,
        },
        category_overrides={}
    ),
    strategies=[],
    hard_constraint_overrides={}
)


# ---------------------------------------------------------------------------
# 辅助函数：值域校验 / 裁剪
# ---------------------------------------------------------------------------

_COEFF_BOUNDS = (0.1, 3.0)


def _clamp(value: float, bounds: tuple = _COEFF_BOUNDS) -> float:
    """将浮点数裁剪到指定范围"""
    if value is None or not isinstance(value, (int, float)) or math.isnan(value):
        return 1.0
    return max(bounds[0], min(bounds[1], float(value)))


def clamp_policy_coefficients(policy: PlanningPolicy) -> PlanningPolicy:
    """
    对 policy 中所有系数执行值域裁剪 [0.1, 3.0]，防止 LLM 输出极端值。
    会原地修改 policy 并返回自身。
    """
    sc = policy.scoring_coefficients

    # 全局系数
    for k, v in list(sc.global_.items()):
        sc.global_[k] = _clamp(v)

    # 类别覆盖系数
    for cat, coefs in list(sc.category_overrides.items()):
        for ck, cv in list(coefs.items()):
            coefs[ck] = _clamp(cv)

    # 策略 config 中的数值（只裁剪看起来是系数的键）
    _known_coef_keys = {
        "pref_match_boost", "time_penalty_factor", "two_opt_pref_weight",
        "distance_weight", "max_distance_from_start_km", "candidate_count",
        "max_travel_km_per_step", "max_total_route_km", "min_poi_count",
    }
    for s in policy.strategies:
        for k, v in list(s.config.items()):
            if k in _known_coef_keys and isinstance(v, (int, float)):
                # 距离/数量类参数不裁剪到 0.1~3.0，只保证非负
                if k in {"candidate_count", "min_poi_count"}:
                    s.config[k] = max(1, int(v))
                elif "km" in k or "distance" in k or "_m" in k:
                    s.config[k] = max(0.5, float(v))
                else:
                    s.config[k] = _clamp(v)

    # fusion alpha
    alpha = policy.fusion_config.get("alpha")
    if alpha is not None:
        policy.fusion_config["alpha"] = max(0.0, min(1.0, float(alpha)))

    return policy


# ---------------------------------------------------------------------------
# 辅助函数：构建 POI 统计摘要
# ---------------------------------------------------------------------------

def build_poi_statistics_summary(candidates: List[POI]) -> Dict[str, Any]:
    """
    从候选 POI 列表构建统计摘要，供策略生成器使用（避免 token 爆炸）。
    """
    if not candidates:
        return {"total_candidates": 0}

    total = len(candidates)

    # 类别分布
    category_dist: Dict[str, int] = {}
    for p in candidates:
        cat = p.category or "未知"
        category_dist[cat] = category_dist.get(cat, 0) + 1

    # 距离分布（相对于第一个 POI 的粗略分布，具体距离在策略生成器中不重要）
    # 这里只给出评分分布
    rating_dist = {"4.5+": 0, "4.0-4.5": 0, "<4.0": 0, "无评分": 0}
    for p in candidates:
        if p.rating is None:
            rating_dist["无评分"] += 1
        elif p.rating >= 4.5:
            rating_dist["4.5+"] += 1
        elif p.rating >= 4.0:
            rating_dist["4.0-4.5"] += 1
        else:
            rating_dist["<4.0"] += 1

    # UGC 情感平均分
    sentiment_scores = [p.ugc_sentiment_score for p in candidates if p.ugc_sentiment_score != 0]
    ugc_sentiment_avg = round(sum(sentiment_scores) / len(sentiment_scores), 2) if sentiment_scores else 0.0

    # Top tags
    tag_counts: Dict[str, int] = {}
    for p in candidates:
        for t in p.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # 价格分布
    price_dist = {"免费": 0, "1-50元": 0, "51-100元": 0, "100元+": 0}
    for p in candidates:
        pr = p.price or 0
        if pr == 0:
            price_dist["免费"] += 1
        elif pr <= 50:
            price_dist["1-50元"] += 1
        elif pr <= 100:
            price_dist["51-100元"] += 1
        else:
            price_dist["100元+"] += 1

    return {
        "total_candidates": total,
        "category_distribution": category_dist,
        "rating_distribution": rating_dist,
        "price_distribution": price_dist,
        "ugc_sentiment_avg": ugc_sentiment_avg,
        "top_tags": [t[0] for t in top_tags],
    }


# ---------------------------------------------------------------------------
# Prompt 设计
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一位智能旅行规划策略生成专家。根据用户画像和原始需求，输出一套PlanningPolicy JSON。

输出格式（纯JSON，无markdown）：
{
  "policy_version": "1.0",
  "reasoning": "策略核心逻辑，1句话",
  "preference_space": {
    "theme_weights": {"维度": 0.0~1.0},
    "negative_themes": ["用户明确不喜欢的维度"],
    "traveler_type": "独自/情侣/亲子/朋友/家庭",
    "pace_preference": "紧凑/适中/悠闲",
    "budget_level": "经济/标准/高端"
  },
  "theme_keyword_map": {"维度": ["关键词1", "关键词2", "关键词3"]},
  "fusion_config": {"alpha": 0.0~1.0, "alpha_reason": "一句话解释"},
  "scoring_coefficients": {
    "global": {
      "ugc_sentiment_weight": 0.1~3.0,
      "scene_match_weight": 0.1~3.0,
      "price_sensitivity_weight": 0.1~3.0,
      "exploration_bonus_factor": 0.1~3.0,
      "distance_penalty_factor": 0.1~3.0,
      "time_efficiency_weight": 0.1~3.0,
      "queue_bonus_weight": 0.1~3.0
    },
    "category_overrides": {"类别名": {"scene_match_weight": 0.1~3.0}}
  },
  "strategies": [
    {"name": "深度体验", "description": "策略描述", "config": {
      "pref_match_boost": 1.8~2.5, "time_penalty_factor": 0.4~0.7, "distance_weight": 0.3~0.5
    }},
    {"name": "高效省时", "description": "策略描述", "config": {
      "pref_match_boost": 0.4~0.8, "time_penalty_factor": 1.5~2.5, "distance_weight": 1.0~1.5
    }},
    {"name": "均衡推荐", "description": "策略描述", "config": {
      "pref_match_boost": 1.0~1.3, "time_penalty_factor": 0.9~1.1, "distance_weight": 0.6~0.8
    }}
  ],
  "hard_constraint_overrides": {"must_visit": [], "avoid": []}
}

规则：
1. theme_weights自由提取用户query中的偏好维度，不限于固定维度。
2. 【重构】theme_keyword_map直接使用theme_weights中的关键词作为key，value为关键词本身（因为语义匹配不需要额外扩展）。
3. alpha：用户说"今天想换个风格"则偏低(0.3-0.5)，偏好稳定则偏高(0.6-0.8)。
4. scoring_coefficients所有系数在[0.1,3.0]范围内。
5. strategies只输出3个关键config字段，其余字段用默认值。
6. must_visit/avoid精确提取用户query中提到的内容。
7. 只输出JSON，不要任何解释。"""



def _clean_llm_json(content: str) -> str:
    """清理 LLM 返回的内容，提取纯 JSON 部分（第一个完整的 JSON 对象或数组）。"""
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

    start_obj = content.find("{")
    start_arr = content.find("[")

    if start_obj == -1 and start_arr == -1:
        return content

    if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
        start = start_obj
        open_br, close_br = "{", "}"
    else:
        start = start_arr
        open_br, close_br = "[", "]"

    count = 0
    end = -1
    for i in range(start, len(content)):
        if content[i] == open_br:
            count += 1
        elif content[i] == close_br:
            count -= 1
            if count == 0:
                end = i
                break

    if end != -1:
        return content[start:end + 1]
    return content[start:]


# 策略config的完整默认值（与route_engine中STRATEGY_CONFIG一致）
_DEFAULT_STRATEGY_CONFIGS = {
    "深度体验": {
        "max_distance_from_start_km": 50,
        "candidate_count": 35,
        "pref_match_boost": 2.0,
        "time_penalty_factor": 0.5,
        "max_travel_km_per_step": 15,
        "max_total_route_km": 50,
        "min_poi_count": 4,
        "two_opt_pref_weight": 1.0,
        "distance_weight": 0.4,
    },
    "高效省时": {
        "max_distance_from_start_km": 15,
        "candidate_count": 25,
        "pref_match_boost": 0.5,
        "time_penalty_factor": 2.0,
        "max_travel_km_per_step": 5,
        "max_total_route_km": 15,
        "min_poi_count": 4,
        "two_opt_pref_weight": 0.0,
        "distance_weight": 1.2,
    },
    "均衡推荐": {
        "max_distance_from_start_km": 30,
        "candidate_count": 30,
        "pref_match_boost": 1.0,
        "time_penalty_factor": 1.0,
        "max_travel_km_per_step": 8,
        "max_total_route_km": 20,
        "min_poi_count": 4,
        "two_opt_pref_weight": 0.5,
        "distance_weight": 0.7,
    },
}


def _build_policy_from_json(data: dict) -> PlanningPolicy:
    """将 LLM 返回的 dict 转换为 PlanningPolicy 对象，处理字段缺失。"""

    # 策略列表
    raw_strategies = data.get("strategies", [])
    strategies = []
    for rs in raw_strategies:
        if not isinstance(rs, dict):
            continue
        name = rs.get("name", "未命名")
        cfg = dict(_DEFAULT_STRATEGY_CONFIGS.get(name, _DEFAULT_STRATEGY_CONFIGS["均衡推荐"]))
        cfg.update(rs.get("config", {}))
        strategies.append(StrategyConfig(
            name=name,
            description=rs.get("description", ""),
            config=cfg
        ))

    # 评分系数
    raw_coef = data.get("scoring_coefficients", {})
    scoring = ScoringCoefficients(
        global_=raw_coef.get("global", {}),
        category_overrides=raw_coef.get("category_overrides", {})
    )

    policy = PlanningPolicy(
        policy_version=data.get("policy_version", "1.0"),
        reasoning=data.get("reasoning", ""),
        preference_space=data.get("preference_space", {}),
        theme_keyword_map=data.get("theme_keyword_map", {}),
        fusion_config=data.get("fusion_config", {"alpha": 0.7}),
        scoring_coefficients=scoring,
        strategies=strategies,
        hard_constraint_overrides=data.get("hard_constraint_overrides", {})
    )

    return clamp_policy_coefficients(policy)


def generate_planning_policy(
    raw_query: Optional[str],
    user_pref: UserPreference,
    candidates: List[POI],
    constraints: RouteConstraints,
    timeout: int = 25,
) -> PlanningPolicy:
    """
    调用 LLM 生成 PlanningPolicy。

    Args:
        raw_query: 用户原始自然语言 query
        user_pref: 当前融合后的用户画像
        candidates: 候选 POI 列表（用于构建统计摘要）
        constraints: 路线约束条件
        timeout: LLM 调用超时（秒）

    Returns:
        PlanningPolicy 对象；若 LLM 调用失败或解析失败，返回 DEFAULT_POLICY。
    """
    if not check_llm_config():
        print("[Policy Generator] LLM 配置不完整，回退到默认策略")
        return DEFAULT_POLICY

    # 构建 POI 统计摘要
    poi_summary = build_poi_statistics_summary(candidates)

    # 构建用户上下文
    pref_json = user_pref.model_dump_json(indent=2, exclude_none=True)
    summary_json = json.dumps(poi_summary, ensure_ascii=False, indent=2)

    user_context = f"""用户原始需求：{raw_query or '未提供自然语言描述'}

当前融合画像：
{pref_json}

候选POI统计摘要：
{summary_json}

路线约束：
- 城市：{constraints.city}
- 时间：{constraints.start_time} ~ {constraints.end_time}
- 预算：{constraints.budget if constraints.budget is not None else '未指定'} 元
- 交通方式：{constraints.transport_mode}
- 必去点：{constraints.must_visit if constraints.must_visit else '无'}
- 避开点：{constraints.avoid if constraints.avoid else '无'}

请根据以上信息生成 PlanningPolicy JSON。"""

    # 检查缓存
    cache_key = _make_policy_cache_key(raw_query, user_pref)
    cached = _get_cached_policy(cache_key)
    if cached:
        return cached

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
            extra_body={"instructions": "请严格按JSON格式输出，不要添加任何解释或markdown代码块。"},
        )

        content = response.choices[0].message.content
        if not content:
            print("[Policy Generator] LLM 返回空内容，回退到默认策略")
            return DEFAULT_POLICY

        clean = _clean_llm_json(content)
        parsed = json.loads(clean)
        policy = _build_policy_from_json(parsed)

        # 如果 LLM 没有输出策略，填充默认策略
        if not policy.strategies:
            policy.strategies = _fallback_strategies()

        # 写入缓存
        _set_cached_policy(cache_key, policy)
        print(f"[Policy Generator] 成功生成策略，理由：{policy.reasoning}")
        return policy

    except APITimeoutError:
        print("[Policy Generator] LLM 调用超时，回退到默认策略")
        return DEFAULT_POLICY
    except RateLimitError:
        print("[Policy Generator] LLM 速率限制(429)，回退到默认策略")
        return DEFAULT_POLICY
    except APIError as e:
        print(f"[Policy Generator] LLM API 错误({e.status_code if hasattr(e, 'status_code') else 'unknown'})，回退到默认策略")
        return DEFAULT_POLICY
    except Exception as e:
        print(f"[Policy Generator] 策略生成失败，回退到默认策略。错误：{e}")
        return DEFAULT_POLICY


def _fallback_strategies() -> List[StrategyConfig]:
    """当 LLM 未返回策略时，提供与当前系统一致的默认三套策略。"""
    # 从 route_engine 的 STRATEGY_CONFIG 同步过来的默认值
    return [
        StrategyConfig(
            name="深度体验",
            description="专注你最感兴趣的偏好，允许绕路去高体验POI",
            config={
                "max_distance_from_start_km": 50,
                "candidate_count": 35,
                "pref_match_boost": 2.0,
                "time_penalty_factor": 0.5,
                "max_travel_km_per_step": 15,
                "max_total_route_km": 50,
                "min_poi_count": 4,
                "two_opt_pref_weight": 1.0,
                "distance_weight": 0.4,
            }
        ),
        StrategyConfig(
            name="高效省时",
            description="严格短距离，用最短时间打卡最多亮点",
            config={
                "max_distance_from_start_km": 15,
                "candidate_count": 25,
                "pref_match_boost": 0.5,
                "time_penalty_factor": 2.0,
                "max_travel_km_per_step": 5,
                "max_total_route_km": 15,
                "min_poi_count": 4,
                "two_opt_pref_weight": 0.0,
                "distance_weight": 1.2,
            }
        ),
        StrategyConfig(
            name="均衡推荐",
            description="兼顾体验、时间和预算的综合最优方案",
            config={
                "max_distance_from_start_km": 30,
                "candidate_count": 30,
                "pref_match_boost": 1.0,
                "time_penalty_factor": 1.0,
                "max_travel_km_per_step": 8,
                "max_total_route_km": 20,
                "min_poi_count": 4,
                "two_opt_pref_weight": 0.5,
                "distance_weight": 0.7,
            }
        ),
    ]


# ---------------------------------------------------------------------------
# 便捷函数：从 policy 中获取有效系数
# ---------------------------------------------------------------------------

def get_effective_coefficient(poi: POI, coefficient_name: str, policy: PlanningPolicy) -> float:
    """
    获取某个 POI 在某个系数上的有效值。
    优先级：类别覆盖 > 全局默认值 > 1.0
    """
    sc = policy.scoring_coefficients
    cat = poi.category or ""
    if cat and cat in sc.category_overrides:
        override = sc.category_overrides[cat]
        if coefficient_name in override:
            return override[coefficient_name]
    return sc.global_.get(coefficient_name, 1.0)


def get_strategy_config(policy: PlanningPolicy, strategy_name: str) -> Optional[Dict[str, Any]]:
    """
    从 policy 中获取指定名称的策略配置。
    支持按名称匹配（深度体验/高效省时/均衡推荐）或按索引（0/1/2）。
    """
    name_map = {
        "experience": "深度体验",
        "efficiency": "高效省时",
        "balanced": "均衡推荐",
    }
    target_name = name_map.get(strategy_name, strategy_name)
    for s in policy.strategies:
        if s.name == target_name:
            return dict(s.config)
    return None
