"""Claude SoM 后端 — Anthropic Messages API + Element ID 模式"""
import json
import re
import httpx
from loguru import logger
from typing import List, Optional

import config
from utils import encode_image

CLAUDE_SOM_SYSTEM_PROMPT = """你是一个桌面自动化 Agent，正在操控一台 Windows 11 虚拟机。
屏幕分辨率：{screen_w}x{screen_h}。截图已缩放到 {img_w}x{img_h}。

## 工作方式
你会看到当前屏幕截图（{img_w}x{img_h}）。请直接根据截图判断要点击的位置，输出**截图坐标**（基于 {img_w}x{img_h}），系统会自动换算到实际屏幕。

## 输出格式（JSON）

### 点击
{{"thought": "点击搜索按钮", "action": "click", "x": 800, "y": 450}}

### 双击
{{"thought": "双击打开文件", "action": "double_click", "x": 800, "y": 450}}

### 右键点击
{{"thought": "右键打开菜单", "action": "right_click", "x": 800, "y": 450}}

### 输入文字（先点击输入框坐标）
{{"thought": "在搜索框输入", "action": "type", "x": 800, "y": 450, "text": "你好"}}

### 键盘快捷键
{{"thought": "保存文件", "action": "hotkey", "keys": ["ctrl", "s"]}}

### 按键
{{"thought": "按回车确认", "action": "press", "key": "enter"}}

### 滚动
{{"thought": "向下滚动", "action": "scroll", "direction": "down", "amount": 3}}

### 等待
{{"thought": "等待加载", "action": "wait"}}

### 完成
{{"thought": "任务已完成", "action": "done"}}

### 失败
{{"thought": "无法完成", "action": "fail"}}

## 规则
1. 每次只输出一个 JSON 动作
2. 坐标基于截图尺寸 {img_w}x{img_h}，直接看图估算位置
3. 如果连续 3 次操作没效果，换一种方式
4. 完成后必须输出 done，失败输出 fail
5. thought 用中文简要说明
6. **禁止点击空白区域获取焦点**。桌面已经有焦点，直接用键盘操作。
7. **键盘优先**：选文件 Ctrl+A，重命名 F2，确认 Enter，关闭菜单 Escape。不要用鼠标点击来选文件。
8. 点击坐标要瞄准目标的**正中心**"""


USER_PROMPT_TEMPLATE = """# 任务：{instruction}

# Step {step_idx}

# 历史操作：
{history_summary}

请根据截图，输出下一步动作的 JSON。坐标基于截图尺寸。"""


class ClaudeBackend:
    """Claude Opus — 直接坐标模式（不依赖 OmniParser）"""

    def __init__(self):
        self.history: List[dict] = []

    def reset(self):
        self.history = []

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int):
        from llm.router import AgentAction, ActionType

        screenshot_b64 = encode_image(context["screenshot_bytes"])
        scale = context.get("screenshot_scale", 1.0)

        history_summary = self._build_history_summary(history)

        # 截图尺寸
        img_w = int(config.SCREEN_WIDTH / scale)
        img_h = int(config.SCREEN_HEIGHT / scale)

        user_text = USER_PROMPT_TEMPLATE.format(
            instruction=instruction,
            step_idx=step_idx,
            history_summary=history_summary or "（首步，无历史）",
        )

        # 动态填充 system prompt 的分辨率
        system_prompt = CLAUDE_SOM_SYSTEM_PROMPT.format(
            screen_w=config.SCREEN_WIDTH, screen_h=config.SCREEN_HEIGHT,
            img_w=img_w, img_h=img_h,
        )

        messages = self._build_messages(screenshot_b64, user_text, history, step_idx)

        response_text = self._call_api(messages, system_prompt)
        logger.info(f"Claude response: {response_text[:300]}")

        return self._parse_response(response_text, scale)

    def _build_history_summary(self, history: list) -> str:
        if not history:
            return ""
        lines = []
        for h in history[-10:]:
            step = h.get("step", "?")
            thought = h.get("thought", "")[:60]
            changed = "✓" if h.get("changed", True) else "✗"
            lines.append(f"Step {step}: {thought} → {changed}")
        return "\n".join(lines)

    def _build_messages(self, screenshot_b64: str, user_text: str,
                        history: list, step_idx: int) -> list:
        # Only current screenshot — history is in text summary to avoid 413
        return [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                {"type": "text", "text": user_text},
            ]
        }]

    def _call_api(self, messages: list, system_prompt: str = "") -> str:
        url = f"{config.LLM_BASE_URL}/v1/messages"
        body = {
            "model": config.LLM_MODEL,
            "max_tokens": 1024,
            "system": system_prompt or CLAUDE_SOM_SYSTEM_PROMPT,
            "messages": messages,
        }
        headers = {
            "x-api-key": config.LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = httpx.post(url, json=body, headers=headers, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        result = "\n".join(texts)
        if not result:
            raise ValueError(f"Empty response from Anthropic: {data}")
        return result

    def _parse_response(self, response_text: str, scale: float = 1.0):
        """Parse Claude JSON output → AgentAction, scale coords to screen"""
        from llm.router import AgentAction, ActionType

        text = response_text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        # 先去掉 thought 字段（中文引号会破坏 JSON 解析）
        stripped = re.sub(r'"thought"\s*:\s*".*?(?<!\\)",\s*', '', text)

        for candidate in [text, stripped]:
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                # 尝试提取 {"action":...} 块
                m = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]+?"[^{}]*\}', candidate)
                if m:
                    try:
                        data = json.loads(m.group())
                        break
                    except json.JSONDecodeError:
                        continue
        else:
            logger.error(f"Failed to parse Claude JSON: {text[:200]}")
            return AgentAction(action_type=ActionType.FAIL, raw_response=response_text)

        action_str = data.get("action", "fail")
        thought = data.get("thought", "")

        # Scale image coords → screen coords
        raw_x = data.get("x")
        raw_y = data.get("y")
        x = int(raw_x * scale) if raw_x is not None else None
        y = int(raw_y * scale) if raw_y is not None else None

        if action_str == "done":
            return AgentAction(action_type=ActionType.DONE, thought=thought, raw_response=response_text)
        if action_str == "fail":
            return AgentAction(action_type=ActionType.FAIL, thought=thought, raw_response=response_text)
        if action_str == "wait":
            return AgentAction(action_type=ActionType.WAIT, thought=thought, raw_response=response_text)

        if action_str in ("click", "double_click", "right_click"):
            at = ActionType.CLICK
            return AgentAction(action_type=at, x=x, y=y, thought=thought,
                               raw_response=response_text,
                               key=action_str if action_str != "click" else None)

        if action_str == "type":
            return AgentAction(action_type=ActionType.TYPE, x=x, y=y,
                               text=data.get("text", ""), thought=thought, raw_response=response_text)

        if action_str == "hotkey":
            return AgentAction(action_type=ActionType.HOTKEY, key="+".join(data.get("keys", [])),
                               thought=thought, raw_response=response_text)

        if action_str == "press":
            return AgentAction(action_type=ActionType.HOTKEY, key=data.get("key", ""),
                               thought=thought, raw_response=response_text)

        if action_str == "scroll":
            return AgentAction(action_type=ActionType.SCROLL,
                               direction=data.get("direction", "down"),
                               amount=data.get("amount", 3),
                               thought=thought, raw_response=response_text)

        return AgentAction(action_type=ActionType.FAIL, thought=thought, raw_response=response_text)
