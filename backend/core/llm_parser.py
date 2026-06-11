# -*- coding: utf-8 -*-
"""
LLM 意图理解模块
将自然语言 raw_query 解析为结构化的 UserPreference（自由关键词+权重）

使用 OpenAI-compatible API:
  - model: gpt-5.5-xhigh
  - base_url: https://dxb.huifei.net/v1
"""

import functools
import json
from typing import Optional, List, Dict

from backend.models.schemas import UserPreference

from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config

# API 配置（从 .env 文件加载）
API_KEY = LLM_API_KEY
BASE_URL = LLM_BASE_URL
MODEL_NAME = LLM_MODEL_NAME


SYSTEM_PROMPT = """你是一位专业的本地旅游偏好解析助手。你的任务是从用户的自然语言描述中提取意图关键词和权重。

【核心变化】不再限制固定主题维度，自由提取用户 query 中的意图关键词。

请严格按以下 JSON 格式输出（不要包含任何 markdown 代码块标记，只输出纯 JSON）：
{
  "theme_weights": {"关键词1": 0.0~1.0, "关键词2": ..., "关键词3": ...},
  "traveler_type": "独自/情侣/亲子/朋友/家庭",
  "pace_preference": "紧凑/适中/悠闲",
  "budget_level": "经济/标准/高端",
  "willingness_to_queue": 0.0~1.0,
  "willingness_to_walk": 0.0~1.0,
  "price_sensitivity": 0.0~1.0,
  "must_visit": ["用户明确想去的POI名称"],
  "avoid": ["用户明确不想去的POI名称或类别"],
  "transport_mode": "步行/骑行/驾车/公交"
}

提取规则（自由关键词维度）：
1. theme_weights 自由提取用户query中的意图关键词，不限数量、不限类型，范围 0.0~1.0。
   - 用户明确提到的正面偏好作为独立关键词，给 0.85~0.95
   - 隐含相关的关键词给 0.50~0.70
   - 用户明确不喜欢/排斥的关键词给 0.05~0.15（作为负面过滤信号）
   - 无关的不列出或给低值
   - 示例："想吃辣、拍照、不想排队" → {"吃辣":0.9, "拍照":0.85, "排队":0.1}
   - 示例："想带孩子去游乐园" → {"亲子":0.95, "游乐园":0.9, "儿童":0.85}
   - 示例："想逛博物馆、吃老字号" → {"博物馆":0.9, "老字号":0.85, "文化":0.75}
   - 示例："周末带女朋友去杭州玩，喜欢拍照和吃辣" → {"拍照":0.9, "吃辣":0.85, "情侣":0.8, "杭州":0.3}
2. traveler_type：从描述中推断人群，如"带女朋友"=情侣，"带孩子/小孩"=亲子，"带老人"=家庭，"和朋友"=朋友。
3. pace_preference："赶时间/多玩几个"=紧凑，"慢慢逛"=悠闲，默认适中。
4. budget_level：预算<200=经济，>500=高端，中间=标准；也可从描述推断，如"便宜点/省钱"=经济。
5. willingness_to_queue：用户提到"不怕排队/网红店"则高(>0.7)，"不想排队/讨厌排队"则低(<0.3)。
6. willingness_to_walk：用户提到"多走走/Citywalk"则高(>0.7)，"懒得走/打车/地铁"则低(<0.3)。
7. price_sensitivity：预算低或提到"省钱/便宜/穷游"则高(>0.7)，"不差钱/豪华"则低(<0.3)。
8. must_visit / avoid：
   - must_visit：提取用户明确提到想去的具体POI名称（如"西湖"、"灵隐寺"）。
   - avoid：提取用户明确不想去的POI名称，或负面偏好类别（如"辣食"、"排队"、"人多的地方"）。注意：用户明确喜欢的活动（如"喜欢爬山"、"爱吃辣"）应作为正面偏好放入theme_weights，不要放入avoid。
9. transport_mode：用户提到"开车/自驾"=驾车，"骑车/骑行"=骑行，"地铁/公交"=公交，"走路/步行"=步行，默认步行。
10. 如果用户描述中没有提到某项，使用合理的默认值，不要随意猜测。

只输出 JSON，不要任何解释。"""


def _extract_first_json(text: str) -> str:
    """Extract the first valid JSON object or array from text, handling markdown fences, think tags and trailing text."""
    text = text.strip()
    # Remove <think>...</think> tags (reasoning content from some models)
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>") + len("</think>")
        text = text[:start] + text[end:]
    text = text.strip()
    # Remove markdown code block fences
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


@functools.lru_cache(maxsize=128)
def _parse_preference_from_llm_cached(
    raw_query: str,
    preferences: tuple,
    travelers: str,
    pace: str,
    budget: Optional[int],
    must_visit: tuple,
    avoid: tuple,
    transport_mode: str,
) -> Optional[UserPreference]:
    """
    调用 LLM 解析自然语言偏好，输出自由关键词+权重（已缓存版本）。
    参数必须为可 hash 类型。
    """
    if not raw_query or not raw_query.strip():
        return None

    # 组装用户上下文，把已有的结构化字段也提供给 LLM，让它知道哪些已经明确
    user_context = f"""用户自然语言描述：{raw_query}

已有的结构化字段（供参考，自然语言优先）：
- 偏好标签：{list(preferences)}
- 出行人群：{travelers}
- 节奏：{pace}
- 预算：{budget if budget is not None else '未指定'} 元
- 必去：{list(must_visit) if must_visit else '未指定'}
- 不想去：{list(avoid) if avoid else '未指定'}
- 交通方式：{transport_mode}
"""

    try:
        if not check_llm_config():
            print("[LLM Parser Warning] LLM 配置不完整，请检查 .env 文件")
            return None

        from backend.core.llm_client import safe_llm_chat_completion
        content = safe_llm_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_context},
            ],
            temperature=0.2,
            timeout_seconds=15,
            extra_body={"instructions": "请严格按JSON格式输出，不要添加任何解释或markdown代码块。"},
        )

        if not content:
            return None

        clean = _extract_first_json(content)
        parsed = json.loads(clean)
        return _build_user_preference(parsed, list(preferences), travelers, pace, budget)

    except Exception as e:
        # 生产环境可打印日志；这里静默 fallback
        print(f"[LLM Parser Warning] 解析失败，fallback 到规则解析。错误: {e}")
        return None


def parse_preference_from_llm(
    raw_query: str,
    preferences: List[str],
    travelers: str,
    pace: str,
    budget: Optional[int] = None,
    must_visit: Optional[List[str]] = None,
    avoid: Optional[List[str]] = None,
    transport_mode: str = "步行",
) -> Optional[UserPreference]:
    """
    调用 LLM 解析自然语言偏好，输出自由关键词+权重。

    返回 UserPreference 对象；若解析失败返回 None，由上层 fallback 到规则解析。
    """
    return _parse_preference_from_llm_cached(
        raw_query,
        tuple(preferences) if preferences else (),
        travelers,
        pace,
        budget,
        tuple(must_visit) if must_visit else (),
        tuple(avoid) if avoid else (),
        transport_mode,
    )


def _build_user_preference(
    parsed,
    fallback_preferences: List[str],
    fallback_travelers: str,
    fallback_pace: str,
    fallback_budget: Optional[int],
) -> Optional[UserPreference]:
    """
    将 LLM 返回的 JSON 转换为 UserPreference 对象，
    与前端传入的 fallback 字段做合并（前端字段兜底）。
    """
    # Handle case where LLM returns a list instead of dict
    if isinstance(parsed, list):
        if len(parsed) > 0 and isinstance(parsed[0], dict):
            parsed = parsed[0]
        else:
            return None
    if not isinstance(parsed, dict):
        return None

    # 【核心】自由维度关键词权重：直接采纳 LLM 返回的所有维度
    theme_weights = {}
    llm_themes = parsed.get("theme_weights", {})

    if isinstance(llm_themes, dict):
        for dimension, val in llm_themes.items():
            try:
                v = float(val)
                theme_weights[dimension] = max(0.0, min(1.0, v))
            except (ValueError, TypeError):
                continue

    # 前端 fallback_preferences 作为补充（如果LLM没提到但用户勾选了）
    for pref in fallback_preferences:
        if pref not in theme_weights:
            theme_weights[pref] = 0.85

    # 确保至少有基础关键词（兼容旧代码，防止空字典导致后续除零）
    if not theme_weights:
        theme_weights = {"通用": 0.5}

    # 出行人群
    traveler_type = parsed.get("traveler_type", fallback_travelers)
    if traveler_type not in ("独自", "情侣", "亲子", "朋友", "家庭"):
        traveler_type = fallback_travelers

    # 节奏
    pace_preference = parsed.get("pace_preference", fallback_pace)
    if pace_preference not in ("紧凑", "适中", "悠闲"):
        pace_preference = fallback_pace

    # 预算级别
    budget_level = parsed.get("budget_level")
    if budget_level not in ("经济", "标准", "高端"):
        if fallback_budget is not None:
            if fallback_budget < 200:
                budget_level = "经济"
            elif fallback_budget > 500:
                budget_level = "高端"
            else:
                budget_level = "标准"
        else:
            budget_level = "标准"

    # 价格敏感度
    price_sensitivity = parsed.get("price_sensitivity")
    if price_sensitivity is None:
        if fallback_budget is not None:
            price_sensitivity = max(0.0, min(1.0, 1.0 - fallback_budget / 1000))
        else:
            price_sensitivity = 0.5
    else:
        price_sensitivity = max(0.0, min(1.0, float(price_sensitivity)))

    # 排队意愿 & 走路意愿
    willingness_to_queue = max(0.0, min(1.0, float(parsed.get("willingness_to_queue", 0.5))))
    willingness_to_walk = max(0.0, min(1.0, float(parsed.get("willingness_to_walk", 0.5))))

    return UserPreference(
        theme_weights=theme_weights,
        traveler_type=traveler_type,
        pace_preference=pace_preference,
        budget_level=budget_level,
        willingness_to_queue=willingness_to_queue,
        willingness_to_walk=willingness_to_walk,
        price_sensitivity=round(price_sensitivity, 2),
    )


def extract_must_avoid_from_llm(
    parsed_raw: Optional[str]
) -> tuple[List[str], List[str]]:
    """
    若上层需要单独提取 must_visit / avoid，可复用。
    当前与 parse_preference_from_llm 内联处理即可。
    """
    return [], []
