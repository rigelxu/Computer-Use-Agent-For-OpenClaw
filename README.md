# Computer-Use-Agent-For-OpenClaw

基于 [OpenCUA-7B](https://huggingface.co/xlangai/OpenCUA-7B) 模型的 Windows 11 桌面自动化 Agent，通过 OpenClaw 集成实现任务调度。

## 架构

```
OpenClaw → FastAPI Service (8100) → OpenCUA Agent → vLLM (主机) → pyautogui 执行
                                         ↑
                                    mss 截图 ←── VNC 桌面会话
```

## 核心特性

- 基于 OpenCUA 官方 Agent 改造，去掉 OSWorld 依赖，独立运行
- 调用本地 vLLM 服务（OpenAI 兼容 API）
- L2 CoT 推理（Thought → Action → Code）
- 相对坐标映射（模型输出 0-1 → 屏幕绝对坐标）
- pyautogui 安全执行器（白名单函数，防止危险操作）
- Windows 滚动缩放适配（scroll ×50）
- FastAPI 异步任务管理

## 模块说明

| 文件 | 说明 |
|------|------|
| `main.py` | FastAPI 服务入口，任务管理 |
| `agent.py` | OpenCUA Agent，截图→推理→解析循环 |
| `executor.py` | pyautogui 安全执行器 |
| `screenshot.py` | mss 截图模块 |
| `prompts.py` | System prompt（L1/L2/L3） |
| `utils.py` | 坐标映射、图片编码 |
| `config.py` | 配置（vLLM 地址、屏幕分辨率等） |
| `reference/` | OpenCUA 官方参考代码 |

## 快速开始

### 前置条件

- 主机部署 vLLM + OpenCUA-7B（默认 `http://192.168.1.36:8000`）
- VNC 连接保持桌面会话
- Python 3.10+

### 安装

```bash
pip install -r requirements.txt
```

### 启动

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8100
```

### API

```bash
# 提交任务
curl -X POST http://localhost:8100/task \
  -H "Content-Type: application/json" \
  -d '{"prompt": "打开记事本，输入 Hello World"}'

# 查询状态
curl http://localhost:8100/task/{task_id}

# 停止任务
curl -X POST http://localhost:8100/task/{task_id}/stop

# 调试截图
curl http://localhost:8100/screenshot
```

## 配置

编辑 `config.py`：

```python
VLLM_BASE_URL = "http://192.168.1.36:8000"  # vLLM 服务地址
VLLM_MODEL_NAME = "opencua-7b"               # 模型名
SCREEN_WIDTH = 1920                           # 屏幕宽度
SCREEN_HEIGHT = 1080                          # 屏幕高度
COT_LEVEL = "l2"                              # CoT 级别 (l1/l2/l3)
MAX_STEPS = 30                                # 最大步数
FASTAPI_PORT = 8100                           # 服务端口
```

## 致谢

- [OpenCUA](https://github.com/xlang-ai/OpenCUA) — XLANG Lab
- [OSWorld](https://github.com/xlang-ai/OSWorld) — 官方 Agent 参考实现
- [OpenClaw](https://github.com/openclaw/openclaw) — AI Agent 框架
