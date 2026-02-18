"""动作重试管理器 — 截图对比变化检测 + 自动重试"""
import io
import numpy as np
from PIL import Image
from loguru import logger

from llm.router import AgentAction


def action_to_pyautogui(action: AgentAction) -> str:
    """将统一 AgentAction 转为 pyautogui 可执行代码"""
    if action.raw_code:
        return action.raw_code

    t = action.action_type.value
    if t == "click":
        sub = action.key  # "double_click" / "right_click" / None
        if sub == "double_click":
            return f"pyautogui.doubleClick(x={action.x}, y={action.y})"
        if sub == "right_click":
            return f"pyautogui.rightClick(x={action.x}, y={action.y})"
        return f"pyautogui.click(x={action.x}, y={action.y})"
    if t == "type":
        escaped = (action.text or "").replace("'", "\\'")
        return f"win32type('{escaped}')"
    if t == "hotkey":
        keys = ", ".join(f"'{k}'" for k in (action.key or "").split("+"))
        return f"pyautogui.hotkey({keys})"
    if t == "scroll":
        amt = action.amount or 3
        amt = -amt if action.direction == "down" else amt
        return f"pyautogui.scroll({amt})"
    if t == "wait":
        return "WAIT"
    if t == "done":
        return "DONE"
    if t == "fail":
        return "FAIL"
    return "FAIL"


class ActionRetryManager:
    def __init__(self, max_retries: int = 3, change_threshold: float = 0.02):
        self.max_retries = max_retries
        self.change_threshold = change_threshold

    def check_action_effect(self, before: bytes, after: bytes, action: AgentAction) -> dict:
        ratio = self._compute_change_ratio(before, after)
        changed = ratio > self.change_threshold
        suggestion = "none"
        if not changed:
            if action.action_type.value == "click":
                suggestion = "retry"
            elif action.action_type.value == "scroll":
                suggestion = "scroll_down"
        return {"changed": changed, "change_ratio": ratio, "suggestion": suggestion}

    def _compute_change_ratio(self, img1_bytes: bytes, img2_bytes: bytes) -> float:
        img1 = np.array(Image.open(io.BytesIO(img1_bytes)).convert("L"))
        img2 = np.array(Image.open(io.BytesIO(img2_bytes)).convert("L"))
        if img1.shape != img2.shape:
            return 1.0
        diff = np.abs(img1.astype(int) - img2.astype(int))
        return float(np.sum(diff > 15)) / diff.size
