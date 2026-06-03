# -*- coding: utf-8 -*-
"""
统一配置加载模块
从 .env 文件加载环境变量，供各模块使用
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 本文件位于 backend/core/，项目根目录是上级目录的上级
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)


# LLM API 配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dxb.huifei.net/v1")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-5.5")

# 高德 API 配置
AMAP_KEY = os.getenv("AMAP_KEY", "")


def check_llm_config() -> bool:
    """检查 LLM 配置是否完整（排除占位符）"""
    invalid_placeholders = ["", "你的_Kimi_API_Key", "YOUR_API_KEY", "sk-xxxx"]
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_API_KEY not in invalid_placeholders)


def check_amap_config() -> bool:
    """检查高德配置是否完整"""
    return bool(AMAP_KEY)
