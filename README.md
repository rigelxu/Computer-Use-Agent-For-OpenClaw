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

- 主机部署 vLLM + OpenCUA-7B（默认 `http://10.0.0.1:8000`，详见 [NETWORK.md](NETWORK.md)）
- VNC 连接保持桌面会话
- Python 3.10+

### 安装

```bash
pip install -r requirements.txt
```

### 启动

```bash
# 设置 API Key（可选，不设置会自动生成随机 key）
export CUA_API_KEY="your-secret-key-here"

python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8100
```

启动后会在日志中看到生成的 API Key（如果未设置环境变量）。

### API 认证

所有 API 端点都需要 Bearer Token 认证：

```bash
# 设置 API Key
export API_KEY="your-api-key"

# 提交任务
curl -X POST http://localhost:8100/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"prompt": "打开记事本，输入 Hello World"}'

# 查询状态
curl http://localhost:8100/task/{task_id} \
  -H "Authorization: Bearer $API_KEY"

# 停止任务
curl -X POST http://localhost:8100/task/{task_id}/stop \
  -H "Authorization: Bearer $API_KEY"

# 调试截图
curl http://localhost:8100/screenshot \
  -H "Authorization: Bearer $API_KEY"
```

## 配置

编辑 `config.py`：

```python
VLLM_BASE_URL = "http://10.0.0.1:8000"  # vLLM 服务地址
VLLM_MODEL_NAME = "opencua-7b"               # 模型名
SCREEN_WIDTH = 1920                           # 屏幕宽度
SCREEN_HEIGHT = 1080                          # 屏幕高度
COT_LEVEL = "l2"                              # CoT 级别 (l1/l2/l3)
MAX_STEPS = 30                                # 最大步数
FASTAPI_PORT = 8100                           # 服务端口
```

或通过环境变量配置 API Key：

```bash
export CUA_API_KEY="your-secret-key-here"
```

如果不设置 `CUA_API_KEY`，系统会自动生成随机密钥并在启动时输出到日志。

## 致谢

- [OpenCUA](https://github.com/xlang-ai/OpenCUA) — XLANG Lab
- [OSWorld](https://github.com/xlang-ai/OSWorld) — 官方 Agent 参考实现
- [OpenClaw](https://github.com/openclaw/openclaw) — AI Agent 框架

## 常见问题

### vLLM 连接不上

本项目运行在 Hyper-V VM 中，vLLM 运行在宿主机 WSL2 里，通过内部交换机通信。如果连接失败，参考 [NETWORK.md](NETWORK.md) 排查。

常见原因：
- WSL2 重启后 IP 变化，需要更新 portproxy 的 `connectaddress`
- vLLM 未用 `--host 0.0.0.0` 启动
- VM 内部网卡 IP 未配置

快速检查：

```powershell
# VM 中验证网络
ping 10.0.0.1
curl http://10.0.0.1:8000/v1/models

# 宿主机中检查 portproxy
netsh interface portproxy show all

# WSL2 中查看当前 IP
ip addr show eth0 | grep inet
```

### 截图失败

需要通过 VNC 保持桌面会话，否则 mss 截图返回黑屏。Hyper-V VM 没有持久交互式桌面，必须依赖 VNC。

### pyautogui 执行报错

执行器使用 AST 白名单验证，只允许 pyautogui 的安全函数。如果模型生成了不在白名单内的代码，会被拒绝执行。
