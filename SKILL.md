---
name: computer-use
description: 通过 Computer Use Agent (OpenCUA-7B) 自动化 Windows 桌面操作。用于需要操控桌面应用（微信、浏览器等）的任务。
---

# Computer Use Agent Skill

通过 CUA (Computer Use Agent) 控制 Windows 桌面，执行 GUI 自动化任务。

## 架构

```
OpenClaw → FastAPI(:8100) → OpenCUA Agent → vLLM(:8000) → pyautogui 执行
```

## 前置条件

1. **vLLM 服务**必须在宿主机运行（`http://10.0.0.1:8000`，模型 `opencua-7b`）
2. **VNC 桌面会话**必须保持连接（CUA 通过 mss 截图，需要活跃桌面）
3. **FastAPI 服务**需要启动（见下方启动步骤）

## 步骤 1：检查服务状态

先检查 FastAPI 是否已在运行：

```powershell
try { $r = Invoke-WebRequest -Uri http://localhost:8100/health -UseBasicParsing -TimeoutSec 3; $r.Content } catch { "OFFLINE" }
```

如果返回 OFFLINE，进入步骤 2。如果已在线，跳到步骤 3。

## 步骤 2：启动 FastAPI 服务

**必须在后台启动**，使用 exec 工具的 background 模式：

```powershell
cd C:\Users\Administrator\Documents\computer-use-agent; $env:CUA_API_KEY="test123"; $env:PYTHONIOENCODING="utf-8"; python main.py
```

启动后等待 5-10 秒，再次检查 health 确认服务就绪。

如果 vLLM 不可达（报连接错误到 10.0.0.1:8000），告知用户需要在宿主机启动 vLLM，这个无法远程操作。

## 步骤 3：提交任务

API 端点：`POST http://localhost:8100/task`
认证：`Authorization: Bearer test123`

请求体：
```json
{
  "prompt": "任务描述（英文或中文均可）",
  "max_steps": 15,
  "timeout": 180,
  "clipboard_preload": "可选：需要输入的中文文本"
}
```

### 关键参数说明

- **prompt**: 详细的任务指令，描述每个步骤
- **max_steps**: 最大执行步数，简单任务 10-15，复杂任务 20-30
- **timeout**: 超时秒数
- **clipboard_preload**: ⚠️ **重要** — OpenCUA-7B 无法在代码中输出中文字符，会变成错误拼音。任何需要输入的中文文本必须通过此字段预加载到剪贴板，executor 会自动用 Ctrl+V 粘贴替代 pyautogui.write
- **confirm_before_send**: 设为 `true` 时，agent 检测到发送动作会暂停，等待确认后才执行。**建议始终开启**

### 提交示例（PowerShell）

```powershell
$body = @{
    prompt = "你的任务描述"
    max_steps = 15
    timeout = 180
    clipboard_preload = "需要输入的中文文本"
} | ConvertTo-Json -Depth 3

$headers = @{ "Authorization" = "Bearer test123"; "Content-Type" = "application/json" }
$r = Invoke-WebRequest -Uri http://localhost:8100/task -Method POST -Headers $headers -Body $body -UseBasicParsing
$r.Content
```

返回中会包含 `task_id`，用于后续查询。

## 步骤 4：监控任务

查询任务状态：

```powershell
$headers = @{ "Authorization" = "Bearer test123" }
$r = Invoke-WebRequest -Uri "http://localhost:8100/task/<task_id>" -Headers $headers -UseBasicParsing
$r.Content
```

状态值：
- `pending` → 排队中
- `running` → 执行中（检查 steps 和 history）
- `awaiting_confirm` → 等待确认（发送前暂停）
- `completed` → 成功完成
- `cancelled` → 用户拒绝发送
- `failed` / `error` / `timeout` / `stopped` → 失败

建议每 10-15 秒轮询一次，直到状态不再是 running。

## 步骤 5：发送确认（confirm_before_send=true 时）

当任务状态变为 `awaiting_confirm` 时：

1. 获取当前截图查看屏幕状态：
```powershell
$r = Invoke-WebRequest -Uri "http://localhost:8100/task/<task_id>/screenshot" -Headers $headers -UseBasicParsing
# 返回 base64 截图，可保存为文件查看或发给用户确认
```

2. 将截图保存并发给用户确认：
```powershell
$resp = $r.Content | ConvertFrom-Json
$bytes = [Convert]::FromBase64String($resp.screenshot.Replace("data:image/png;base64,",""))
[IO.File]::WriteAllBytes("C:\Users\Administrator\Desktop\confirm_screenshot.png", $bytes)
```
然后用 message 工具将截图发给用户，询问是否确认发送。

3. 根据用户回复确认或拒绝：
```powershell
# 确认发送
$body = '{"confirm": true}' 
Invoke-WebRequest -Uri "http://localhost:8100/task/<task_id>/confirm" -Method POST -Headers @{"Authorization"="Bearer test123";"Content-Type"="application/json"} -Body $body -UseBasicParsing

# 拒绝发送
$body = '{"confirm": false}'
Invoke-WebRequest -Uri "http://localhost:8100/task/<task_id>/confirm" -Method POST -Headers @{"Authorization"="Bearer test123";"Content-Type"="application/json"} -Body $body -UseBasicParsing
```

确认超时为 5 分钟，超时自动取消。

停止任务：

```powershell
Invoke-WebRequest -Uri "http://localhost:8100/task/<task_id>/stop" -Method POST -Headers $headers -UseBasicParsing
```

## 编写 Prompt 的最佳实践

1. **步骤要明确**：分步描述，每步只做一件事
2. **说明当前状态**：告诉 agent 当前屏幕可能的状态
3. **指定完成条件**：明确什么时候算完成，提醒 agent 完成后 terminate
4. **中文输入走 clipboard_preload**：不要在 prompt 里让 agent 用 pyautogui.write 输入中文

### Prompt 模板

```
请完成以下任务：

1. [第一步操作]
2. [第二步操作]
3. [第三步操作]

注意：每个步骤只执行一次，不要重复。完成后立即 terminate。
```

## 常见任务示例

### 微信发消息
```json
{
  "prompt": "请完成以下任务：\n1. 打开微信（如果未打开，在任务栏找到微信图标点击）\n2. 在微信搜索框中搜索联系人\"XXX\"\n3. 点击搜索结果进入聊天\n4. 在聊天输入框中输入消息并发送\n5. 确认消息发送成功后 terminate",
  "max_steps": 15,
  "timeout": 180,
  "clipboard_preload": "要发送的中文消息内容"
}
```

### 微信发文件
```json
{
  "prompt": "请完成以下任务：\n1. 打开微信，找到联系人\"XXX\"的聊天窗口\n2. 点击聊天输入框旁边的文件发送按钮（📎 或文件图标）\n3. 在文件选择对话框中导航到指定路径\n4. 选择文件并发送\n5. 确认发送成功后 terminate",
  "max_steps": 20,
  "timeout": 300
}
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 连接 10.0.0.1:8000 失败 | vLLM 未启动 | 需要在宿主机 WSL2 中启动 vLLM |
| 中文变成拼音乱码 | 未用 clipboard_preload | 必须通过 clipboard_preload 传入中文 |
| Agent 重复执行相同动作 | 模型陷入循环 | executor 有重复检测（≥2次跳过），也可手动 stop |
| 截图全黑 | VNC 会话断开 | 重新连接 VNC 桌面 |
| FastAPI 启动失败 | 端口占用或依赖缺失 | 检查 8100 端口，确认 requirements.txt 已安装 |

## 项目路径

- 代码：`C:\Users\Administrator\Documents\computer-use-agent\`
- 关键文件：`main.py`（FastAPI）、`executor.py`（执行器）、`agent.py`（Agent）、`config.py`（配置）
