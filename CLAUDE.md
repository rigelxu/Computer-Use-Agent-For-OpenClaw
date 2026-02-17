# Computer Use Agent - 开发规范

## 项目概述
基于 OpenCUA-7B 模型的 Windows 11 桌面自动化 Agent，通过 OpenClaw 集成实现任务调度。

## 架构
```
OpenClaw (小徐) → FastAPI Service → OpenCUA Agent → vLLM (主机) → pyautogui 执行
```

## 关键配置
- vLLM 服务：http://192.168.1.36:8000（OpenAI 兼容 API）
- 模型：opencua-7b
- 屏幕分辨率：1920x1080
- CoT 级别：L2（Thought + Action + Code）
- 坐标类型：relative（0-1 相对坐标）
- 平台：windows
- FastAPI 端口：8100

## 目录结构
```
computer-use-agent/
├── main.py              # FastAPI 服务入口
├── agent.py             # OpenCUA Agent（基于官方改造）
├── executor.py          # pyautogui 安全执行器
├── screenshot.py        # 截图模块（mss）
├── prompts.py           # System prompt（复用官方）
├── utils.py             # 坐标映射等工具（精简官方）
├── config.py            # 配置
├── reference/           # 官方参考代码（只读）
│   ├── opencua_agent.py
│   ├── prompts.py
│   ├── utils.py
│   └── __init__.py
└── requirements.txt
```

## 核心流程
1. 接收任务指令
2. 截图当前桌面
3. 构建 prompt（system prompt + 历史 + 当前截图 + 指令）
4. 调用 vLLM 推理，获取 Thought/Action/Code
5. 解析 pyautogui 代码，坐标映射
6. 安全执行 pyautogui 操作
7. 循环 2-6 直到 terminate 或达到最大步数

## 安全要求
- executor 只允许 pyautogui 白名单函数
- 最大步数限制（默认 30）
- 单步超时保护
- 任务总超时保护

## API 设计
- POST /task — 提交任务（prompt, max_steps, timeout）
- GET /task/{id} — 查询任务状态和结果
- POST /task/{id}/stop — 停止任务
- GET /screenshot — 获取当前截图（调试用）

## 同步规则
- 使用方式、能力范围、API 接口变更必须同步更新 OpenClaw Skill（`~/.openclaw/workspace/skills/computer-use/SKILL.md`）
- SKILL.md 是外部调用者的唯一参考，保持与实际能力一致

## 与官方代码的区别
- 去掉 OSWorld 框架依赖，独立运行
- call_llm 改为调用本地 vLLM（OpenAI 兼容 API）
- 加入 FastAPI 服务层
- 加入截图模块（官方依赖 OSWorld 环境提供截图）
- 加入安全执行器（官方直接 exec）
- Windows 滚动缩放（scroll ×50）
