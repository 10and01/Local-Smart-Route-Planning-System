# -*- coding: utf-8 -*-
"""
LLM 推荐理由生成模块
为路线中的每个POI生成自然语言推荐理由

使用 OpenAI-compatible API:
  - model: gpt-5.5
  - base_url: https://dxb.huifei.net/v1
"""

import json
from typing import List, Optional, Dict

from openai import OpenAI

from backend.models.schemas import RoutePlan, UserPreference, PlanSegment


from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config

# API 配置（从 .env 文件加载）
API_KEY = LLM_API_KEY
BASE_URL = LLM_BASE_URL
MODEL_NAME = LLM_MODEL_NAME

_client: Optional[OpenAI] = None


def _clean_llm_json(content: str) -> str:
    """
    清理 LLM 返回的内容，提取纯 JSON 部分。
    处理 markdown 代码块、think标签、多余前后缀文字等常见问题。
    """
    if not content:
        return "{}"
    content = content.strip()
    # Remove <think>...</think> tags (reasoning content from some models)
    while "<think>" in content and "</think>" in content:
        start = content.find("<think>")
        end = content.find("</think>") + len("</think>")
        content = content[:start] + content[end:]
    content = content.strip()
    # 去除首尾 markdown 代码块标记
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    # 如果内容前后还有非 JSON 文字，尝试提取最外层 {} 或 []
    if not (content.startswith("{") or content.startswith("[")):
        start_obj = content.find("{")
        start_arr = content.find("[")
        if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
            end = content.rfind("}")
            if end != -1:
                content = content[start_obj:end+1]
        elif start_arr != -1:
            end = content.rfind("]")
            if end != -1:
                content = content[start_arr:end+1]
    return content


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


SYSTEM_PROMPT = """你是一位专业的本地旅游推荐文案写手。你的任务是为路线规划中的每个POI生成一段自然、有吸引力的推荐理由。

要求：
1. 每个POI的理由要简短（15-30字），口语化，像朋友推荐一样自然
2. 必须结合用户的出行人群和偏好主题来写
3. 突出POI的核心亮点，不要泛泛而谈
4. 如果有时间提示（如上午光线好、傍晚看夜景），要融入理由
5. 不要罗列标签，要转化为有温度的描述

输出格式（严格JSON，不要markdown代码块）：
{
  "reasons": {
    "POI名称1": "理由1",
    "POI名称2": "理由2",
    ...
  }
}
"""


def generate_poi_reasons(
    plan: RoutePlan,
    user_pref: UserPreference,
    raw_query: Optional[str] = None
) -> Dict[str, str]:
    """
    为路线中每个POI生成自然语言推荐理由
    
    Args:
        plan: 路线方案
        user_pref: 用户偏好
        raw_query: 用户的原始自然语言查询（可选，用于更精准匹配）
    
    Returns:
        dict: {poi_name: reason_text}
    """
    if not plan.segments:
        return {}
    
    # 构建POI上下文
    poi_contexts = []
    for seg in plan.segments:
        p = seg.poi
        tags_str = "、".join(p.tags[:4]) if p.tags else ""
        time_hint = ""
        try:
            hour = int(seg.arrive_time.split(":")[0])
            if hour < 10 and any(t in p.tags for t in ["拍照", "摄影"]):
                time_hint = "上午光线柔和"
            elif 11 <= hour <= 13 and p.category in ["餐饮服务", "咖啡厅"]:
                time_hint = "正好是用餐时段"
            elif hour >= 17 and any(t in p.tags for t in ["夜景", "灯光"]):
                time_hint = "傍晚景色最美"
        except Exception:
            pass
        
        ctx = {
            "name": p.name,
            "category": p.category,
            "tags": tags_str,
            "rating": p.rating,
            "price": p.price,
            "arrive_time": seg.arrive_time,
            "duration": seg.duration,
            "time_hint": time_hint,
            "highlights": p.highlights or ""
        }
        poi_contexts.append(ctx)
    
    # 构建prompt
    user_context = f"""用户画像：
- 出行人群：{user_pref.traveler_type}
- 偏好主题：{', '.join(f'{k}({v:.0%})' for k, v in user_pref.theme_weights.items() if v > 0.3)}
- 节奏：{user_pref.pace_preference}
- 预算级别：{user_pref.budget_level or '未指定'}
"""
    if raw_query:
        user_context += f"- 原始需求：{raw_query}\n"
    
    poi_details = "\n".join(
        f"{i+1}. {c['name']}（{c['category']}）| 标签：{c['tags']} | "
        f"评分{c['rating']} | 到达{c['arrive_time']} | 停留{c['duration']}分钟"
        f"{' | ' + c['time_hint'] if c['time_hint'] else ''}"
        for i, c in enumerate(poi_contexts)
    )
    
    full_prompt = f"""{user_context}

路线方案：{plan.theme}
整体描述：{plan.description}

POI列表：
{poi_details}

请为每个POI生成一段自然、有吸引力的推荐理由（15-30字），直接输出JSON格式。"""
    
    if not check_llm_config():
        print("[LLM Reasoner Warning] LLM 配置不完整，请检查 .env 文件")
        return {}
    
    try:
        client = get_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_prompt},
            ],
            temperature=0.5,
            timeout=60,
            extra_body={"instructions": "请为每个POI生成自然、简短、有吸引力的推荐理由，直接输出JSON格式。"},
        )
        
        content = response.choices[0].message.content
        if not content:
            return {}
        
        parsed = json.loads(_clean_llm_json(content))
        reasons = parsed.get("reasons", {})
        
        # 确保返回的key与POI名称匹配
        result = {}
        for seg in plan.segments:
            reason = reasons.get(seg.poi.name)
            if reason:
                result[seg.poi.name] = reason
        
        return result
    
    except Exception as e:
        print(f"[LLM Reasoner Warning] 生成推荐理由失败: {e}")
        return {}


def apply_llm_reasons_to_plan(plan: RoutePlan, reasons: Dict[str, str]) -> RoutePlan:
    """
    将LLM生成的推荐理由应用到路线方案的segments中
    """
    for seg in plan.segments:
        if seg.poi.name in reasons:
            # 将LLM理由加入selection_reasons的第一个位置
            llm_reason = f"[LLM] {reasons[seg.poi.name]}"
            if seg.selection_reasons:
                # 如果已有规则理由，LLM理由放在前面
                seg.selection_reasons = [llm_reason] + seg.selection_reasons
            else:
                seg.selection_reasons = [llm_reason]
    return plan


def generate_overall_reasoning(
    plan: RoutePlan,
    user_pref: UserPreference,
    raw_query: Optional[str] = None
) -> str:
    """
    为整条路线生成更自然的整体推荐理由（替代规则模板）
    """
    # 先尝试用LLM生成整体理由
    poi_names = [seg.poi.name for seg in plan.segments]
    if not poi_names:
        return "未生成路线"
    
    try:
        client = get_client()
        prompt = f"""用户画像：{user_pref.traveler_type}出行，偏好{', '.join(k for k, v in user_pref.theme_weights.items() if v > 0.5)}。

路线：{plan.theme}，包含 {len(poi_names)} 个地点：{' → '.join(poi_names)}。
总用时{plan.total_time}，总花费{plan.total_cost}元。

请用1-2句话生成一段自然、有感染力的整体推荐理由（不超过80字），让用户觉得这条路线是"懂我"的。直接输出纯文本，不要JSON。"""
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一位专业的旅游推荐师，擅长用简短有力的语言打动用户。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            timeout=10,
            extra_body={"instructions": "请直接输出纯文本推荐理由，不要添加任何格式标记。"},
        )
        
        content = response.choices[0].message.content
        if content and len(content.strip()) > 10:
            return content.strip()
    except Exception as e:
        print(f"[LLM Reasoner Warning] 生成整体理由失败: {e}")
    
    # fallback到原有规则生成
    return plan.overall_reasoning
