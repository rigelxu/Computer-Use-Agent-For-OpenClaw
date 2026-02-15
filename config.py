"""
配置文件
"""
import os
import secrets

# vLLM 服务配置
VLLM_BASE_URL = "http://192.168.1.36:8000"
VLLM_MODEL_NAME = "opencua-7b"

# FastAPI 配置
FASTAPI_HOST = "0.0.0.0"
FASTAPI_PORT = 8100

# API 认证配置
# 从环境变量读取，如果没有则生成随机 key
API_KEY = os.getenv("CUA_API_KEY", secrets.token_urlsafe(32))

# 屏幕配置
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080

# Agent 配置
COT_LEVEL = "l2"  # l1, l2, l3
COORDINATE_TYPE = "relative"  # relative, absolute, qwen25
PLATFORM = "windows"
MAX_STEPS = 30
MAX_IMAGE_HISTORY_LENGTH = 3
MAX_TOKENS = 1500
TOP_P = 0.9
TEMPERATURE = 0.0

# 超时配置
STEP_TIMEOUT = 60  # 单步超时（秒）
TASK_TIMEOUT = 1800  # 任务总超时（秒）
