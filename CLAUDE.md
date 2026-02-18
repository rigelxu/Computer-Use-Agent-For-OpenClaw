# Computer Use Agent - 开发规范

## 项目概述
Windows 11 桌面自动化 Agent，Claude Opus 主力 + OpenCUA-7B 备用双后端。运行在 Hyper-V VM 中。

## 架构
```
OpenClaw (小徐) → FastAPI(:8100) → LLM Router → Claude/OpenCUA → executor (pyautogui + Win32 API)
```

## 关键配置
- LLM 主力：Claude Opus（直接坐标模式，看截图输出像素坐标）
- LLM 备用：OpenCUA-7B via vLLM（http://10.0.0.1:8000）
- 屏幕：1920x1080，截图缩放到 1600x900（scale=1.2）
- 键盘：Win32 API（AttachThreadInput + PostMessage），pyautogui 键盘在 Hyper-V 不生效
- OmniParser：http://10.0.0.1:8001（可选，Claude 不依赖 element_id）
- FastAPI 端口：8100，认证：Bearer token

## 目录结构
```
computer-use-agent/
├── main.py                  # FastAPI + 任务调度 + 桌面快捷路径
├── executor.py              # 安全沙箱 + Win32 键盘拦截
├── win32_keyboard.py        # Win32 API 键盘模块
├── action_retry_manager.py  # 动作重试 + pyautogui 代码生成
├── screenshot.py            # mss 截图 + 缩放
├── window_manager.py        # 窗口检测/激活/最小化
├── context_manager.py       # 上下文收集
├── recovery_manager.py      # 应用恢复
├── config.py                # 配置（.env）
├── llm/
│   ├── router.py            # 双后端路由
│   ├── claude_backend.py    # Claude 直接坐标后端
│   └── opencua_backend.py   # OpenCUA-7B 后端
├── prompts/                 # 应用特定 prompt（暂未启用）
├── wechat_send.py           # 微信发文件纯脚本
└── .env                     # API keys（不提交）
```

## 核心流程
1. 接收任务 → 检测是否走快捷路径（桌面重命名等）
2. 准备窗口（最小化/激活目标应用）
3. 截图 + OmniParser（可选）→ 构建上下文
4. Claude 看截图 → 输出 JSON（action + 像素坐标）
5. executor 执行（鼠标用 pyautogui，键盘走 Win32 API）
6. 循环 3-5 直到 done 或超时

## 安全要求
- executor AST 白名单：只允许 pyautogui/time/pyperclip
- 禁止 `__` 属性、import、exec/eval/compile
- Win32 键盘拦截在沙箱外执行（_try_pywinauto_keyboard）
- API 所有端点 Bearer token 认证
- .env 在 .gitignore，不提交 key

## API
- POST /task — 提交任务
- GET /task/{id} — 查询状态
- POST /task/{id}/stop — 停止
- POST /task/{id}/confirm — 发送确认
- GET /task/{id}/screenshot — 获取截图
- GET /health — 健康检查

## 踩坑记录
- **pyautogui 键盘在 Hyper-V VM 完全不生效**，必须走 Win32 PostMessage
- **Claude thought 里中文引号破坏 JSON**，需要 strip-thought fallback 正则
- **桌面 F2 重命名在脚本进程里不可靠**（桌面没焦点），改用 os.rename
- **OmniParser 对 7B 模型无效**（token 过载），Claude 不需要 element_id
- **确定性操作不要让 AI 决策**，走快捷路径更可靠

## 同步规则
- 能力/API 变更必须同步更新 SKILL.md（`~/.openclaw/workspace/skills/computer-use/SKILL.md`）
- SKILL.md 是 OpenClaw 调用的唯一参考
