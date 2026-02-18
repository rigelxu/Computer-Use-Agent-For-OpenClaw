# Computer Use Agent For OpenClaw

Windows 11 桌面自动化 Agent，支持 Claude Opus（主力）和 OpenCUA-7B（备用）双后端。

## 架构

```
OpenClaw → FastAPI(:8100) → LLM Router ─→ Claude Opus (直接坐标模式)
                │                     └→ OpenCUA-7B (fallback)
                │
                ├── executor.py (pyautogui + Win32 API 键盘)
                ├── ContextManager (截图 + OmniParser)
                └── WindowManager (窗口激活/最小化)
```

## 核心特性

- **双后端 LLM**：Claude Opus 主力（视觉理解强），OpenCUA-7B 备用自动 fallback
- **Claude 直接坐标模式**：看截图输出像素坐标，不依赖 OmniParser element_id
- **Win32 API 键盘**：Hyper-V VM 中 pyautogui 键盘不生效，所有键盘操作走 AttachThreadInput + PostMessage
- **桌面快捷路径**：重命名等确定性操作直接用 os.rename，跳过 agent 循环
- **安全沙箱**：AST 白名单 + 禁止 dunder 属性 + 禁止 import/exec/eval
- **截图缩放**：1920x1080 → 1600x900（scale=1.2），Claude 在图片坐标系输出，后端自动换算

## 模块说明

| 文件 | 说明 |
|------|------|
| `main.py` | FastAPI 服务、任务调度、桌面快捷路径 |
| `executor.py` | 安全执行器 + Win32 键盘拦截 |
| `win32_keyboard.py` | Win32 API 键盘模块（Hyper-V 唯一可靠方案） |
| `llm/claude_backend.py` | Claude 直接坐标后端 |
| `llm/opencua_backend.py` | OpenCUA-7B 后端 |
| `llm/router.py` | 双后端路由（Claude → OpenCUA fallback） |
| `action_retry_manager.py` | 动作重试 + pyautogui 代码生成 |
| `screenshot.py` | mss 截图 + 缩放 |
| `window_manager.py` | 窗口检测/激活/最小化 |
| `context_manager.py` | 上下文收集（截图+OmniParser+窗口信息） |
| `config.py` | 配置（从 .env 读取） |

## 快速开始

### 前置条件

- Python 3.10+
- VNC 连接保持桌面会话（mss 截图需要）
- Claude API key（主力后端）
- vLLM + OpenCUA-7B（可选备用，`http://10.0.0.1:8000`）

### 安装

```bash
pip install -r requirements.txt
```

### 配置

创建 `.env`：

```env
CUA_LLM_PROVIDER=anthropic
CUA_LLM_BASE_URL=https://api.anthropic.com
CUA_LLM_API_KEY=sk-ant-xxx
CUA_LLM_MODEL=claude-opus-4-6
CUA_API_KEY=your-secret-key
```

### 启动

```bash
python main.py
```

### API

所有端点需要 `Authorization: Bearer <CUA_API_KEY>`：

```bash
# 提交任务
curl -X POST http://localhost:8100/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Double-click the file on the desktop"}'

# 查询状态
curl http://localhost:8100/task/{id} -H "Authorization: Bearer $API_KEY"

# 停止任务
curl -X POST http://localhost:8100/task/{id}/stop -H "Authorization: Bearer $API_KEY"
```

## Hyper-V VM 注意事项

- **键盘**：pyautogui/SendInput/pywinauto 全部不生效，必须走 `win32_keyboard.py`（PostMessage）
- **桌面焦点**：最小化所有窗口后，PostMessage F2 可能不生效，桌面重命名改用 `os.rename`
- **截图**：需要 VNC 保持桌面会话，否则 mss 返回黑屏

## 致谢

- [OpenCUA](https://github.com/xlang-ai/OpenCUA) — XLANG Lab
- [OpenClaw](https://github.com/openclaw/openclaw) — AI Agent 框架
