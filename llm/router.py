"""LLM 路由器 — Claude 优先，OpenCUA 兜底；统一 AgentAction 输出"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from loguru import logger

import config


class ActionType(Enum):
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    HOTKEY = "hotkey"
    DRAG = "drag"
    WAIT = "wait"
    DONE = "done"
    FAIL = "fail"


@dataclass
class AgentAction:
    action_type: ActionType
    element_id: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None
    direction: Optional[str] = None
    amount: Optional[int] = None
    thought: Optional[str] = None
    raw_response: Optional[str] = None
    raw_code: Optional[str] = None


class LLMRouter:
    """LLM 路由器：Claude 优先，OpenCUA 兜底"""

    def __init__(self):
        self.claude_backend = None
        self.opencua_backend = None
        self._init_backends()

    def _init_backends(self):
        if config.LLM_PROVIDER == "anthropic" and config.LLM_API_KEY:
            from llm.claude_backend import ClaudeBackend
            self.claude_backend = ClaudeBackend()
            logger.info("Claude backend initialized")
        from llm.opencua_backend import OpenCUABackend
        self.opencua_backend = OpenCUABackend()
        logger.info("OpenCUA backend initialized")

    def reset(self):
        if self.claude_backend:
            self.claude_backend.reset()
        if self.opencua_backend:
            self.opencua_backend.reset()

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int) -> AgentAction:
        if self.claude_backend:
            try:
                return self.claude_backend.predict(instruction, context, history, step_idx)
            except Exception as e:
                logger.warning(f"Claude failed, falling back to OpenCUA: {e}")
        return self.opencua_backend.predict(instruction, context, history, step_idx)
