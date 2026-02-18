"""
配置文件
"""
import os
import sys

# LLM 配置（从环境变量读取，绝对不能硬编码）
LLM_PROVIDER = os.getenv("CUA_LLM_PROVIDER", "anthropic")  # "vllm" or "anthropic"
LLM_BASE_URL = os.getenv("CUA_LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("CUA_LLM_API_KEY", "")
LLM_MODEL = os.getenv("CUA_LLM_MODEL", "claude-opus-4-6")

# 兼容旧配置
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://10.0.0.1:8000")
VLLM_MODEL_NAME = "opencua-7b"

# FastAPI 配置
FASTAPI_HOST = "0.0.0.0"
FASTAPI_PORT = 8100

# API 认证配置（必须从环境变量读取）
API_KEY = os.getenv("CUA_API_KEY")
if not API_KEY:
    print("WARNING: CUA_API_KEY not set! Using insecure default for development only.", file=sys.stderr)
    API_KEY = "dev-insecure-key"

# 屏幕配置
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
SCREENSHOT_MAX_WIDTH = int(os.getenv("CUA_SCREENSHOT_MAX_WIDTH", "1600"))

# Agent 配置
COT_LEVEL = "l2"  # l1, l2, l3
COORDINATE_TYPE = "absolute"  # relative, absolute, qwen25
PLATFORM = "windows"
MAX_STEPS = 30
MAX_IMAGE_HISTORY_LENGTH = 3
MAX_TOKENS = 2048
TOP_P = 0.9
TEMPERATURE = 0.0

# 超时配置
STEP_TIMEOUT = 60  # 单步超时（秒）
TASK_TIMEOUT = 1800  # 任务总超时（秒）

# OmniParser 配置
OMNIPARSER_ENABLED = os.getenv("CUA_OMNIPARSER_ENABLED", "true").lower() == "true"
OMNIPARSER_URL = os.getenv("CUA_OMNIPARSER_URL", "http://10.0.0.1:8001")

# SoM 配置
SOM_MAX_ELEMENTS = int(os.getenv("CUA_SOM_MAX_ELEMENTS", "40"))

# 动作重试配置
ACTION_RETRY_ENABLED = os.getenv("CUA_ACTION_RETRY", "true").lower() == "true"
ACTION_RETRY_MAX = int(os.getenv("CUA_ACTION_RETRY_MAX", "3"))
ACTION_CHANGE_THRESHOLD = float(os.getenv("CUA_ACTION_CHANGE_THRESHOLD", "0.02"))

# DPI 缩放（0 = 自动检测）
DPI_SCALE = float(os.getenv("CUA_DPI_SCALE", "0"))
