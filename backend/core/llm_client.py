# -*- coding: utf-8 -*-
"""
LLM 客户端封装
使用 requests 直接调用 OpenAI-compatible API，实现精确的 connect/read timeout 控制
"""

import json
from typing import List, Dict, Optional

import requests

from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, check_llm_config


def safe_llm_chat_completion(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    timeout_seconds: float = 15.0,
    extra_body: Optional[Dict] = None,
) -> Optional[str]:
    """
    使用 requests 直接调用 OpenAI-compatible API，返回解析后的 content 字符串。

    Args:
        messages: OpenAI 格式的消息列表
        model: 模型名称，默认从环境变量读取
        temperature: 采样温度
        max_tokens: 最大 token 数
        timeout_seconds: 读取超时时间（connect 固定 3 秒）
        extra_body: 额外的请求体参数

    Returns:
        content 字符串，失败返回 None
    """
    if not check_llm_config():
        print("[LLM Client] LLM 配置不完整")
        return None

    base_url = (LLM_BASE_URL or "").rstrip("/")
    api_key = LLM_API_KEY or ""
    model_name = model or LLM_MODEL_NAME or ""

    if not base_url or not model_name:
        print("[LLM Client] base_url 或 model 为空")
        return None

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra_body:
        payload.update(extra_body)

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(3, timeout_seconds),  # (connect, read)
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            print("[LLM Client] LLM 返回空 choices")
            return None
        content = choices[0].get("message", {}).get("content")
        return content
    except requests.exceptions.Timeout as e:
        print(f"[LLM Client] 请求超时: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[LLM Client] 请求异常: {e}")
        return None
    except Exception as e:
        print(f"[LLM Client] 解析异常: {e}")
        return None
