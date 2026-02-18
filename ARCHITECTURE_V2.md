# ARCHITECTURE V2 — Claude Opus 4.6 + OmniParser SoM + OmniTool 动作原语

> 版本：v2.0 | 日期：2026-02-18 | 作者：架构组

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Service (main.py)                    │
│                     POST /task  GET /task/{id}                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      TaskOrchestrator (main.py)                     │
│              execute_task() — 任务循环、重试、超时控制                │
└───────┬──────────────┬──────────────┬───────────────┬───────────────┘
        │              │              │               │
        ▼              ▼              ▼               ▼
┌──────────────┐ ┌───────────┐ ┌───────────────┐ ┌──────────────────┐
│ContextManager│ │LLMRouter  │ │ActionRetry    │ │SafeExecutor      │
│(context_     │ │(llm/      │ │Manager        │ │(executor.py)     │
│ manager.py)  │ │ router.py)│ │(action_retry  │ │pyautogui 白名单  │
│              │ │           │ │ _manager.py)  │ │                  │
│ ┌──────────┐ │ │ ┌───────┐ │ │               │ │                  │
│ │Screenshot│ │ │ │Claude │ │ │ 截图对比      │ │                  │
│ │OmniParser│ │ │ │Backend│ │ │ 变化检测      │ │                  │
│ │WindowMgr │ │ │ ├───────┤ │ │ 自动重试      │ │                  │
│ │SoM转换器 │ │ │ │OpenCUA│ │ │ 滚动探索      │ │                  │
│ └──────────┘ │ │ │Backend│ │ │               │ │                  │
└──────────────┘ │ └───────┘ │ └───────────────┘ └──────────────────┘
                 └───────────┘
        │              │
        ▼              ▼
┌──────────────┐ ┌───────────────────────────────────────────────────┐
│OmniParser    │ │PromptManager (prompts/manager.py)                 │
│Service       │ │  ├─ ClaudeSoMPrompt   (SoM Element ID 模式)      │
│(omniparser_  │ │  ├─ OpenCUAPrompt     (坐标模式，保持现有)        │
│ service.py)  │ │  └─ AppSpecificPrompt (微信/浏览器/文件管理器)    │
│              │ └───────────────────────────────────────────────────┘
│ YOLO + OCR   │
│ bbox 检测    │
└──────────────┘
```

### 核心数据流

```
Claude 模式（SoM）:
  截图 → OmniParser → UI元素列表 → SoM转换器 → 元素描述清单
  → Claude Opus 4.6 (选 Element ID + 动作) → 坐标校正(bbox→像素) → 执行
  → 截图对比 → 变化检测 → (无变化则重试)

OpenCUA 模式（坐标）:
  截图 → [可选OmniParser辅助] → OpenCUA-7B (输出相对坐标+代码) → 坐标映射 → 执行
  → (保持现有流程不变)
```

## 二、模块设计

### 2.1 新增文件：`llm/router.py` — LLM 路由器

**职责**：根据配置选择 Claude 或 OpenCUA 后端，统一输出格式。

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

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
    """统一动作输出格式（两个后端都转成这个）"""
    action_type: ActionType
    element_id: Optional[int] = None    # SoM 模式：元素 ID
    x: Optional[int] = None             # 绝对像素坐标（校正后）
    y: Optional[int] = None
    text: Optional[str] = None          # type 动作的文本
    key: Optional[str] = None           # hotkey/press 的按键
    direction: Optional[str] = None     # scroll 方向: up/down
    amount: Optional[int] = None        # scroll 量
    thought: Optional[str] = None       # 模型思考过程
    raw_response: Optional[str] = None  # 原始响应

class LLMRouter:
    """LLM 路由器：Claude 优先，OpenCUA 兜底"""

    def __init__(self):
        self.claude_backend: Optional[ClaudeBackend] = None
        self.opencua_backend: Optional[OpenCUABackend] = None
        self._init_backends()

    def _init_backends(self):
        """根据 config 初始化可用后端"""
        if config.LLM_PROVIDER == "anthropic" and config.LLM_API_KEY:
            self.claude_backend = ClaudeBackend()
        self.opencua_backend = OpenCUABackend()  # 始终初始化作为兜底

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int) -> AgentAction:
        """
        统一预测接口。
        context 包含: screenshot_b64, som_elements, active_app 等
        """
        if self.claude_backend:
            try:
                return self.claude_backend.predict(
                    instruction, context, history, step_idx)
            except Exception as e:
                logger.warning(f"Claude failed, falling back to OpenCUA: {e}")
        return self.opencua_backend.predict(
            instruction, context, history, step_idx)
```

### 2.2 新增文件：`llm/claude_backend.py` — Claude SoM 后端

**职责**：调用 Anthropic Messages API，解析 Element ID 输出，转为 AgentAction。

```python
class ClaudeBackend:
    """Claude Opus 4.6 + SoM 模式"""

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int) -> AgentAction:
        """
        1. 从 context["som_elements"] 构建 SoM 描述
        2. 组装 Anthropic Messages API 请求
        3. 解析 Claude 输出的 JSON（element_id + action_type）
        4. 通过 element_id 查 bbox → 计算像素坐标 → 返回 AgentAction
        """
        som_text = self._build_som_description(context["som_elements"])
        messages = self._build_messages(instruction, context, history, step_idx, som_text)
        response = self._call_api(messages)
        return self._parse_response(response, context["som_elements"], context)

    def _build_som_description(self, elements: list[dict]) -> str:
        """将 OmniParser 元素列表转为 SoM 描述文本（见第三节 Prompt 模板）"""
        ...

    def _build_messages(self, instruction, context, history, step_idx, som_text) -> list:
        """构建 Anthropic Messages API 的 messages 数组"""
        ...

    def _call_api(self, messages: list) -> dict:
        """调用 Anthropic API，返回解析后的 JSON"""
        # 复用现有 agent.py._call_anthropic 的连接逻辑
        # 但 system prompt 换成 SoM 模板
        ...

    def _parse_response(self, response: dict, elements: list, context: dict) -> AgentAction:
        """
        解析 Claude 输出的 JSON:
        {"element_id": 5, "action": "click"}
        {"element_id": 3, "action": "type", "text": "你好"}
        {"action": "scroll", "direction": "down"}
        {"action": "hotkey", "keys": ["ctrl", "v"]}
        {"action": "done"} / {"action": "fail"}

        通过 element_id 查 bbox → coordinate_from_bbox() 计算像素坐标
        """
        ...
```

### 2.3 新增文件：`llm/opencua_backend.py` — OpenCUA 后端

**职责**：封装现有 agent.py 的 OpenCUA 逻辑，输出统一 AgentAction。

```python
class OpenCUABackend:
    """OpenCUA-7B via vLLM，保持现有坐标模式不变"""

    def __init__(self):
        # 复用现有 OpenCUAAgent 的核心逻辑
        self.agent = OpenCUAAgent(
            model=config.VLLM_MODEL_NAME,
            history_type="thought_history",
            max_steps=config.MAX_STEPS,
            # ... 其余参数同 main.py startup
        )

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int) -> AgentAction:
        """
        调用现有 OpenCUAAgent.predict()，
        将 (response, pyautogui_actions, cot) 转为 AgentAction
        """
        obs = {
            "screenshot": context["screenshot_bytes"],
            "screenshot_scale": context.get("screenshot_scale", 1.0)
        }
        response, actions, cot = self.agent.predict(
            instruction=instruction, obs=obs, step_idx=step_idx)

        return self._convert_to_agent_action(actions, cot, response)

    def _convert_to_agent_action(self, actions, cot, response) -> AgentAction:
        """将 pyautogui 代码字符串转为 AgentAction"""
        code = actions[0] if actions else "FAIL"
        if code == "DONE":
            return AgentAction(action_type=ActionType.DONE, raw_response=response)
        if code == "FAIL":
            return AgentAction(action_type=ActionType.FAIL, raw_response=response)
        if code == "WAIT":
            return AgentAction(action_type=ActionType.WAIT, raw_response=response)
        # 对于 pyautogui 代码，保持原样传给 executor
        return AgentAction(
            action_type=ActionType.CLICK,  # 泛化类型
            raw_code=code,  # 新增字段：原始 pyautogui 代码
            thought=cot.get("thought"),
            raw_response=response
        )
```

**兼容性说明**：OpenCUABackend 内部包装现有 `OpenCUAAgent`，不修改 agent.py 任何代码。`raw_code` 字段直接传给 `SafeExecutor.execute()`，走现有执行路径。

### 2.4 新增文件：`som_converter.py` — SoM 转换器 + 坐标校正

**职责**：将 OmniParser 输出转为 Claude 可读的元素清单；根据 Element ID 的 bbox 计算精确点击坐标。

```python
from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass
class SoMElement:
    """标准化的 SoM 元素"""
    id: int
    type: str           # "button", "text_field", "icon", "link", "label", "image"
    content: str         # OCR 文本或元素描述
    bbox: Tuple[float, float, float, float]  # 归一化 (x1, y1, x2, y2)，0~1
    interactable: bool
    center_x: int        # 绝对像素坐标（DPI 校正后）
    center_y: int

class SoMConverter:
    """OmniParser JSON → SoM 元素清单"""

    def __init__(self, screen_w: int, screen_h: int, dpi_scale: float = 1.0):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.dpi_scale = dpi_scale

    def convert(self, omniparser_elements: list[dict],
                max_elements: int = 40) -> List[SoMElement]:
        """
        将 OmniParser 输出转为 SoMElement 列表。
        只保留可交互元素，按从上到下、从左到右排序。
        """
        elements = []
        idx = 0
        for el in omniparser_elements:
            if idx >= max_elements:
                break
            bbox = el.get("bbox", [0, 0, 0, 0])  # 归一化坐标
            cx, cy = self.bbox_to_pixel(bbox)
            elements.append(SoMElement(
                id=idx,
                type=self._classify_type(el),
                content=el.get("content", "").strip(),
                bbox=tuple(bbox),
                interactable=el.get("interactivity", False),
                center_x=cx,
                center_y=cy,
            ))
            idx += 1
        # 按 y 坐标排序（从上到下），同行按 x 排序
        elements.sort(key=lambda e: (e.center_y // 50, e.center_x))
        return elements

    def bbox_to_pixel(self, bbox: list) -> Tuple[int, int]:
        """
        bbox 归一化坐标 → 绝对像素坐标（含 DPI 校正）

        公式：
          raw_x = (bbox[0] + bbox[2]) / 2 * screen_w
          raw_y = (bbox[1] + bbox[3]) / 2 * screen_h
          pixel_x = int(raw_x / dpi_scale)
          pixel_y = int(raw_y / dpi_scale)

        说明：
          - OmniParser 的 bbox 是基于截图像素的归一化坐标 (0~1)
          - 如果截图是在高 DPI 下截取的（如 150% 缩放），
            截图像素 = 逻辑像素 × dpi_scale
          - pyautogui 操作的是逻辑像素，所以要除以 dpi_scale
        """
        raw_x = (bbox[0] + bbox[2]) / 2 * self.screen_w
        raw_y = (bbox[1] + bbox[3]) / 2 * self.screen_h
        return int(raw_x / self.dpi_scale), int(raw_y / self.dpi_scale)

    def format_for_claude(self, elements: List[SoMElement]) -> str:
        """生成 Claude SoM prompt 中的元素清单文本"""
        lines = []
        for el in elements:
            if not el.interactable and not el.content:
                continue
            tag = "🔘" if el.interactable else "📝"
            pos = self._describe_position(el.center_x, el.center_y)
            content_str = f'"{el.content}"' if el.content else "(无文字)"
            lines.append(
                f"  [{el.id}] {tag} {el.type} | {content_str} | {pos}"
            )
        return "\n".join(lines)

    def _classify_type(self, el: dict) -> str:
        """根据 OmniParser 输出推断元素类型"""
        t = el.get("type", "").lower()
        if "button" in t: return "button"
        if "input" in t or "text" in t and el.get("interactivity"): return "text_field"
        if "link" in t: return "link"
        if "icon" in t or "image" in t: return "icon"
        if el.get("interactivity"): return "control"
        return "label"

    def _describe_position(self, x: int, y: int) -> str:
        """生成人类可读的位置描述"""
        h = "左" if x < self.screen_w * 0.33 else "中" if x < self.screen_w * 0.66 else "右"
        v = "上" if y < self.screen_h * 0.33 else "中" if y < self.screen_h * 0.66 else "下"
        return f"屏幕{v}{h}"
```

### 2.5 新增文件：`action_retry_manager.py` — 动作重试管理器

**职责**：执行动作后截图对比，检测界面是否变化，未变化则重试或滚动。借鉴 OmniTool 的 `check_action_effect`。

```python
import numpy as np
from PIL import Image
import io

class ActionRetryManager:
    """动作效果验证 + 自动重试"""

    def __init__(self, max_retries: int = 3, change_threshold: float = 0.02):
        self.max_retries = max_retries
        self.change_threshold = change_threshold  # 像素变化比例阈值

    def check_action_effect(
        self,
        before_screenshot: bytes,
        after_screenshot: bytes,
        action: "AgentAction",
    ) -> dict:
        """
        对比动作前后截图，判断动作是否生效。

        Returns:
            {
                "changed": bool,        # 界面是否变化
                "change_ratio": float,   # 变化像素比例
                "suggestion": str,       # "none" | "retry" | "scroll_down" | "scroll_up"
            }
        """
        ratio = self._compute_change_ratio(before_screenshot, after_screenshot)
        changed = ratio > self.change_threshold

        suggestion = "none"
        if not changed:
            if action.action_type.value == "click":
                suggestion = "retry"       # 点击没反应 → 重试
            elif action.action_type.value == "scroll":
                suggestion = "scroll_down"  # 滚动没反应 → 换方向
        return {"changed": changed, "change_ratio": ratio, "suggestion": suggestion}

    def _compute_change_ratio(self, img1_bytes: bytes, img2_bytes: bytes) -> float:
        """计算两张截图的像素差异比例"""
        img1 = np.array(Image.open(io.BytesIO(img1_bytes)).convert("L"))
        img2 = np.array(Image.open(io.BytesIO(img2_bytes)).convert("L"))
        if img1.shape != img2.shape:
            return 1.0  # 尺寸不同视为完全变化
        diff = np.abs(img1.astype(int) - img2.astype(int))
        changed_pixels = np.sum(diff > 15)  # 容忍轻微渲染差异
        return changed_pixels / diff.size
```

### 2.6 修改文件：`context_manager.py` — 增加 SoM 支持

**改动点**：在现有 `get_context()` 返回值中增加 `som_elements` 字段。

```python
# 在 ContextManager.__init__ 中新增：
from som_converter import SoMConverter

class ContextManager:
    def __init__(self, use_omniparser: bool = False):
        self.wm = WindowManager()
        self.omniparser = OmniParserService() if use_omniparser else None
        self.som_converter = SoMConverter(
            screen_w=config.SCREEN_WIDTH,
            screen_h=config.SCREEN_HEIGHT,
            dpi_scale=self._detect_dpi_scale()
        ) if use_omniparser else None

    def get_context(self) -> dict:
        # ... 现有逻辑不变 ...

        # 新增：SoM 转换
        som_elements = []
        som_text = ""
        if self.som_converter and omniparser_elements:
            som_elements = self.som_converter.convert(omniparser_elements)
            som_text = self.som_converter.format_for_claude(som_elements)

        ctx = {
            # ... 现有字段不变 ...
            "som_elements": som_elements,      # 新增
            "som_text": som_text,              # 新增
        }
        return ctx

    @staticmethod
    def _detect_dpi_scale() -> float:
        """检测 Windows DPI 缩放比例"""
        try:
            import ctypes
            return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
        except Exception:
            return 1.0
```

**兼容性**：只新增字段，不修改现有字段，OpenCUA 模式忽略 `som_*` 字段即可。

### 2.7 修改文件：`config.py` — 新增配置项

```python
# 新增配置项（追加到现有 config.py 末尾）

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
```

## 三、Claude SoM 模式 Prompt 模板

### 3.1 System Prompt（完整）

```
你是一个桌面自动化 Agent，正在操控一台 Windows 11 虚拟机。

## 工作方式
我已经用 OmniParser 为你标注了屏幕上的 UI 元素，每个元素有唯一的 Element ID。
**请不要猜测像素坐标。** 请告诉我你想操作的 Element ID 和动作类型，我会帮你完成精确操作。

## 输出格式
你必须输出一个 JSON 对象，格式如下：

### 点击元素
{"thought": "需要点击搜索按钮", "element_id": 5, "action": "click"}

### 双击元素
{"thought": "需要双击打开文件", "element_id": 12, "action": "double_click"}

### 右键点击
{"thought": "需要右键打开菜单", "element_id": 8, "action": "right_click"}

### 在输入框中输入文字
{"thought": "在搜索框输入关键词", "element_id": 3, "action": "type", "text": "你好世界"}

### 键盘快捷键
{"thought": "保存文件", "action": "hotkey", "keys": ["ctrl", "s"]}

### 按键
{"thought": "按回车确认", "action": "press", "key": "enter"}

### 滚动
{"thought": "向下滚动查看更多内容", "action": "scroll", "direction": "down", "amount": 3}

### 等待（页面加载中）
{"thought": "等待页面加载完成", "action": "wait"}

### 任务完成
{"thought": "文件已成功保存", "action": "done"}

### 任务失败
{"thought": "找不到目标按钮，无法完成", "action": "fail"}

## 规则
1. 每次只输出一个动作
2. 优先选择 element_id 操作，只有快捷键/滚动/等待/完成/失败不需要 element_id
3. 输入文字时，直接写原始文本（中文、日文等直接写，不要转拼音）
4. 如果屏幕上没有你需要的元素，考虑滚动或切换窗口
5. 如果连续 3 次操作没有效果，尝试换一种方式
6. 任务完成后必须输出 {"action": "done"}，失败则输出 {"action": "fail"}
7. thought 字段用中文简要说明你的推理过程
```

### 3.2 User Prompt 模板（每步发送）

```
# 任务：{instruction}

# 当前屏幕 UI 元素（Step {step_idx}）：
{som_text}

# 历史操作：
{history_summary}

请根据截图和上述元素列表，输出下一步动作的 JSON。
```

其中 `{som_text}` 由 `SoMConverter.format_for_claude()` 生成，示例：

```
  [0] 🔘 button | "搜索" | 屏幕上右
  [1] 🔘 text_field | "" | 屏幕上中
  [2] 🔘 button | "发送" | 屏幕下右
  [3] 📝 label | "聊天记录" | 屏幕中中
  [4] 🔘 icon | "表情" | 屏幕下中
  [5] 🔘 button | "文件" | 屏幕下中
```

`{history_summary}` 格式：

```
Step 1: 点击了 [1] text_field → 界面变化 ✓
Step 2: 输入了 "你好" → 界面变化 ✓
Step 3: 点击了 [2] button "发送" → 界面未变化 ✗（已重试）
```

### 3.3 Anthropic Messages API 调用结构

```python
# ClaudeBackend._build_messages() 的输出结构
{
    "model": "claude-opus-4-6",
    "max_tokens": 1024,
    "system": CLAUDE_SOM_SYSTEM_PROMPT,  # 3.1 的完整 system prompt
    "messages": [
        # 历史步骤（最近 3 步带截图）
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
                {"type": "text", "text": "# 任务：...\n# 当前屏幕 UI 元素（Step 1）：\n  [0] 🔘 button ..."}
            ]
        },
        {
            "role": "assistant",
            "content": '{"thought": "点击搜索按钮", "element_id": 0, "action": "click"}'
        },
        # ... 更多历史 ...
        # 当前步骤
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
                {"type": "text", "text": "# 任务：...\n# 当前屏幕 UI 元素（Step N）：\n  [0] 🔘 ..."}
            ]
        }
    ]
}
```

## 四、OpenCUA 模式 Prompt 模板（保持现有）

OpenCUA-7B 模式完全保持现有 `prompts/__init__.py` 中的 prompt 不变：

- System Prompt：`build_sys_prompt(level="l2")` 生成的 Thought/Action/Code 格式
- User Prompt：`INSTRUTION_TEMPLATE` + 截图 + 历史
- 输出格式：`## Thought / ## Action / ## Code` markdown 块
- 坐标模式：relative (0~1) 或 absolute，由 `config.COORDINATE_TYPE` 控制

**不做任何修改**，通过 `OpenCUABackend` 包装现有 `OpenCUAAgent` 即可。

## 五、动作重试逻辑伪代码

```python
# 在 main.py 的 execute_task() 任务循环中集成

async def execute_step_with_retry(action: AgentAction, executor, ctx_mgr, retry_mgr):
    """执行一步动作，带效果验证和自动重试"""

    # 1. 保存动作前截图
    before_screenshot = ctx_mgr.get_context()["screenshot_bytes"]

    # 2. 将 AgentAction 转为可执行代码
    code = action_to_pyautogui(action)
    exec_result = executor.execute(code)
    if not exec_result["success"]:
        return exec_result

    # 3. 等待 UI 响应（不同动作等待时间不同）
    wait_time = {
        "click": 1.0, "double_click": 1.0, "type": 0.5,
        "hotkey": 1.0, "scroll": 0.5, "press": 0.5,
    }.get(action.action_type.value, 1.0)
    await asyncio.sleep(wait_time)

    # 4. 截图对比，检测动作是否生效
    after_screenshot = ctx_mgr.get_context()["screenshot_bytes"]
    effect = retry_mgr.check_action_effect(before_screenshot, after_screenshot, action)

    if effect["changed"]:
        return {"success": True, "changed": True, "change_ratio": effect["change_ratio"]}

    # 5. 未变化 → 重试策略
    for retry in range(retry_mgr.max_retries):
        logger.warning(f"Action had no effect (ratio={effect['change_ratio']:.4f}), "
                       f"retry {retry+1}/{retry_mgr.max_retries}")

        if effect["suggestion"] == "retry":
            # 点击类：微调坐标后重试（偏移 ±3px）
            if action.x and action.y:
                action.x += random.choice([-3, 0, 3])
                action.y += random.choice([-3, 0, 3])
            code = action_to_pyautogui(action)
            executor.execute(code)

        elif effect["suggestion"] == "scroll_down":
            # 滚动无效 → 尝试反方向
            executor.execute("pyautogui.scroll(-3)")

        await asyncio.sleep(wait_time)
        after_screenshot = ctx_mgr.get_context()["screenshot_bytes"]
        effect = retry_mgr.check_action_effect(before_screenshot, after_screenshot, action)
        if effect["changed"]:
            return {"success": True, "changed": True, "retries": retry + 1}

    # 6. 重试耗尽，返回未变化状态（让 LLM 决定下一步）
    return {"success": True, "changed": False, "retries": retry_mgr.max_retries}
```

### AgentAction → pyautogui 代码转换

```python
def action_to_pyautogui(action: AgentAction) -> str:
    """将统一 AgentAction 转为 pyautogui 可执行代码"""
    # OpenCUA 模式：直接返回原始代码
    if hasattr(action, 'raw_code') and action.raw_code:
        return action.raw_code

    # Claude SoM 模式：根据 action_type 生成代码
    t = action.action_type.value
    if t == "click":
        return f"pyautogui.click(x={action.x}, y={action.y})"
    elif t == "double_click":
        return f"pyautogui.doubleClick(x={action.x}, y={action.y})"
    elif t == "right_click":
        return f"pyautogui.rightClick(x={action.x}, y={action.y})"
    elif t == "type":
        escaped = action.text.replace("'", "\\'")
        return f"pyperclip.copy('{escaped}')\npyautogui.hotkey('ctrl', 'v')"
    elif t == "hotkey":
        keys = ", ".join(f"'{k}'" for k in action.key.split("+"))
        return f"pyautogui.hotkey({keys})"
    elif t == "press":
        return f"pyautogui.press('{action.key}')"
    elif t == "scroll":
        amt = action.amount or 3
        amt = -amt if action.direction == "down" else amt
        return f"pyautogui.scroll({amt})"
    elif t == "wait":
        return "WAIT"
    elif t == "done":
        return "DONE"
    elif t == "fail":
        return "FAIL"
    return "FAIL"
```

## 六、坐标校正算法（DPI 缩放）

### 问题背景

Windows 高 DPI 缩放（如 125%、150%）导致：
- 截图像素 ≠ 逻辑像素（pyautogui 操作的是逻辑像素）
- OmniParser 检测的 bbox 基于截图像素
- 直接用 bbox 中心点作为点击坐标会偏移

### 公式

```
设：
  screen_w, screen_h = 逻辑分辨率（如 1920×1080）
  dpi_scale = Windows 缩放比例（如 1.25 表示 125%）
  bbox = [x1, y1, x2, y2]  # OmniParser 归一化坐标，范围 0~1
  screenshot_w = screen_w × dpi_scale  # 截图实际像素宽度
  screenshot_h = screen_h × dpi_scale

坐标转换：
  # Step 1: 归一化 → 截图像素
  pixel_x = (x1 + x2) / 2 × screenshot_w
  pixel_y = (y1 + y2) / 2 × screenshot_h

  # Step 2: 截图像素 → 逻辑像素（pyautogui 坐标）
  click_x = int(pixel_x / dpi_scale)
  click_y = int(pixel_y / dpi_scale)

简化（因为 screenshot_w = screen_w × dpi_scale）：
  click_x = int((x1 + x2) / 2 × screen_w)
  click_y = int((y1 + y2) / 2 × screen_h)
```

### 特殊情况：截图被缩放

当 `config.SCREENSHOT_MAX_WIDTH` 限制了截图宽度时（当前默认 1600）：

```
设：
  screenshot_scale = actual_screenshot_w / SCREENSHOT_MAX_WIDTH
  # 即 context_manager 返回的 screenshot_scale 字段

此时 OmniParser 的 bbox 基于缩放后的截图，需要额外校正：
  click_x = int((x1 + x2) / 2 × SCREENSHOT_MAX_WIDTH × screenshot_scale / dpi_scale)
  click_y = int((y1 + y2) / 2 × SCREENSHOT_MAX_HEIGHT × screenshot_scale / dpi_scale)

但更简单的做法：让 OmniParser 始终处理原始分辨率截图，
在 context_manager 中对 OmniParser 传原图，对 LLM 传缩放图。
```

### DPI 自动检测

```python
def detect_dpi_scale() -> float:
    """Windows DPI 缩放检测"""
    try:
        import ctypes
        # 方法1：GetScaleFactorForDevice
        scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        return scale / 100.0
    except Exception:
        try:
            # 方法2：GetDpiForSystem (Windows 10 1607+)
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except Exception:
            return 1.0
```

## 七、文件变更总览

| 文件 | 操作 | 说明 |
|------|------|------|
| `llm/__init__.py` | 新增 | 包初始化 |
| `llm/router.py` | 新增 | LLM 路由器，Claude/OpenCUA 切换 |
| `llm/claude_backend.py` | 新增 | Claude SoM 后端 |
| `llm/opencua_backend.py` | 新增 | OpenCUA 后端（包装现有 agent.py） |
| `som_converter.py` | 新增 | OmniParser → SoM 元素清单 + 坐标校正 |
| `action_retry_manager.py` | 新增 | 动作效果验证 + 自动重试 |
| `context_manager.py` | 修改 | 增加 som_elements/som_text 字段 |
| `config.py` | 修改 | 增加 OmniParser/SoM/重试 配置项 |
| `main.py` | 修改 | 任务循环集成 LLMRouter + ActionRetryManager |
| `agent.py` | **不修改** | 通过 OpenCUABackend 包装复用 |
| `executor.py` | **不修改** | action_to_pyautogui 生成的代码走现有执行路径 |
| `prompts/__init__.py` | **不修改** | OpenCUA 模式保持原样 |

## 八、实施步骤（按优先级排序）

### Step 1：SoM 转换器 + 坐标校正（1天）

**文件**：`som_converter.py`

**内容**：
- `SoMElement` 数据类
- `SoMConverter.convert()` — OmniParser JSON → SoMElement 列表
- `SoMConverter.bbox_to_pixel()` — 归一化 bbox → 绝对像素坐标（含 DPI 校正）
- `SoMConverter.format_for_claude()` — 生成元素清单文本
- `detect_dpi_scale()` — Windows DPI 自动检测

**验证**：单元测试，给定 OmniParser mock 输出，验证坐标计算正确性。

**依赖**：无（纯数据转换）

### Step 2：Claude SoM 后端（2天）

**文件**：`llm/claude_backend.py`

**内容**：
- Claude SoM System Prompt（第三节完整模板）
- `ClaudeBackend.predict()` — 组装 messages、调用 API、解析 JSON 输出
- `ClaudeBackend._parse_response()` — JSON → AgentAction（含 element_id → 坐标查找）
- 复用现有 `agent.py._call_anthropic()` 的 HTTP 调用和消息合并逻辑

**验证**：用真实 Claude API + 一张截图 + mock SoM 元素，验证端到端输出。

**依赖**：Step 1（SoM 转换器）

### Step 3：OpenCUA 后端封装 + LLM 路由器（1天）

**文件**：`llm/opencua_backend.py`, `llm/router.py`, `llm/__init__.py`

**内容**：
- `OpenCUABackend` — 包装现有 `OpenCUAAgent`，输出 `AgentAction`
- `LLMRouter` — 根据 `config.LLM_PROVIDER` 选择后端，Claude 失败自动回退 OpenCUA
- `AgentAction` 数据类 + `ActionType` 枚举

**验证**：
- `LLM_PROVIDER=anthropic` → 走 Claude 后端
- `LLM_PROVIDER=vllm` → 走 OpenCUA 后端
- Claude API 异常 → 自动回退 OpenCUA

**依赖**：Step 2

### Step 4：动作重试管理器（1天）

**文件**：`action_retry_manager.py`

**内容**：
- `ActionRetryManager.check_action_effect()` — 截图对比，判断动作是否生效
- `ActionRetryManager._compute_change_ratio()` — 灰度图像素差异计算
- 重试策略：点击微调坐标、滚动换方向

**验证**：准备 2 组截图（变化/未变化），验证检测准确性。

**依赖**：无（独立模块）

### Step 5：context_manager 集成 SoM（0.5天）

**文件**：`context_manager.py`（修改）

**改动**：
- `__init__` 中初始化 `SoMConverter`
- `get_context()` 返回值增加 `som_elements` 和 `som_text`
- 新增 `_detect_dpi_scale()` 静态方法

**验证**：调用 `get_context()`，确认 `som_text` 非空且格式正确。

**依赖**：Step 1

### Step 6：main.py 任务循环改造（1.5天）

**文件**：`main.py`（修改）

**改动**：
- `startup_event()` 中用 `LLMRouter` 替代直接创建 `OpenCUAAgent`
- `execute_task()` 循环中：
  - 用 `LLMRouter.predict()` 替代 `agent.predict()`
  - 用 `action_to_pyautogui()` 将 `AgentAction` 转为可执行代码
  - 集成 `ActionRetryManager`，每步执行后验证效果
- `ContextManager` 初始化时启用 OmniParser（当 `config.OMNIPARSER_ENABLED`）

**验证**：端到端测试，Claude 模式完成一个简单任务（如打开记事本输入文字）。

**依赖**：Step 3, 4, 5

### Step 7：config.py 新增配置项（0.5天）

**文件**：`config.py`（修改）

**改动**：追加 OmniParser/SoM/重试相关配置项（见 2.7 节）。

**依赖**：无

### 实施时间线

```
Week 1:
  Day 1: Step 1 (SoM转换器) + Step 7 (config)
  Day 2-3: Step 2 (Claude后端)
  Day 4: Step 3 (OpenCUA封装+路由器) + Step 4 (重试管理器)
  Day 5: Step 5 (context_manager) + Step 6 前半 (main.py改造)

Week 2:
  Day 1: Step 6 后半 (main.py改造+调试)
  Day 2-3: 端到端测试 + Bug修复
  Day 4: 文档更新 (CLAUDE.md, SKILL.md)
  Day 5: 缓冲

总计：~7.5 人天
```

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| OmniParser 检测不准 | Claude 选错元素 | SoM 清单同时附截图，Claude 结合视觉判断；max_elements 限噪声 |
| Claude JSON 输出不稳定 | 解析失败 | JSON 修复（去 markdown 包裹）；失败回退 OpenCUA |
| DPI 缩放检测不准 | 点击偏移 | `CUA_DPI_SCALE` 环境变量手动覆盖 |
| 截图对比误判（动画/光标） | 误认为有变化 | threshold=0.02 容忍 2%；灰度化+像素差>15 过滤 |
| Claude API 延迟高 | 任务耗时增加 | max_tokens=1024（JSON短）；历史只保留最近 3 步截图 |

## 十、.env 配置示例

```env
# === LLM 配置 ===
CUA_LLM_PROVIDER=anthropic
CUA_LLM_BASE_URL=https://api.anthropic.com
CUA_LLM_API_KEY=sk-ant-xxx
CUA_LLM_MODEL=claude-opus-4-6

# === OpenCUA 兜底 ===
VLLM_BASE_URL=http://10.0.0.1:8000

# === OmniParser ===
CUA_OMNIPARSER_ENABLED=true
CUA_OMNIPARSER_URL=http://10.0.0.1:8001

# === SoM / 重试 / DPI ===
CUA_SOM_MAX_ELEMENTS=40
CUA_ACTION_RETRY=true
CUA_ACTION_RETRY_MAX=3
CUA_ACTION_CHANGE_THRESHOLD=0.02
CUA_DPI_SCALE=0
```
