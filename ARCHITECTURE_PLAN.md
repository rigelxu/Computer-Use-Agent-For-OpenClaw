# CUA 通用化架构分析与开发计划

## 一、当前架构优势与局限性

### 优势
1. **清晰的模块分层** — main.py(服务层) / agent.py(Agent核心) / executor.py(执行层) / screenshot.py(截图)
2. **安全机制完善** — AST白名单、路径验证、重复检测、并发控制
3. **针对性优化** — clipboard_preload + file_preload 两阶段机制、write→clipboard自动替换、坐标映射三模式
4. **可观测性** — 完整历史记录、loguru日志

### 局限性
1. **微信特化逻辑硬编码** — SEND_ACTION_PATTERNS、发送确认流程、wechat_send.py坐标硬编码
2. **缺乏应用状态感知** — 只有截图，无窗口信息/进程/焦点
3. **缺乏UI元素感知** — 完全依赖7B视觉模型识别文本和控件，无YOLO检测/OCR辅助
4. **单一执行器** — 只支持pyautogui，无Windows API/shell命令
5. **Prompt工程不足** — 通用prompt，无应用特定知识/few-shot
6. **缺乏错误恢复** — 执行失败直接FAIL，无回滚/重试

## 二、架构调整方案

### 需要重构的模块
1. **executor.py → 多执行器架构** — BaseExecutor + PyAutoGUIExecutor + WindowsAPIExecutor + ShellExecutor + ExecutorManager
2. **agent.py → 工具调用架构** — Tool基类 + OCRTool/WindowTool等，模型输出结构化工具调用
3. **prompts.py → 应用特定Prompt库** — PromptTemplate + 微信/浏览器/文件管理器特定prompt + PromptManager动态选择

### 需要新增的模块
1. **context_manager.py** — 整合窗口管理+OmniParser+截图，提供统一上下文
2. **omniparser_service.py** — OmniParser集成（YOLO UI元素检测 + OCR文字识别），输出带标签的UI元素列表
3. **task_planner.py** — LLM任务分解+完成验证
4. **recovery_manager.py** — 检查点保存+错误恢复策略
5. **app_controllers/** — 应用特定控制器（微信/浏览器/文件管理器）

### 模块交互流程
```
FastAPI → TaskOrchestrator → ContextManager + TaskPlanner + PromptManager
    → OpenCUAAgent(LLM) → ExecutorManager → PyAutoGUI/WindowsAPI/Shell
    → RecoveryManager(监控+恢复)
    ↑ OmniParser(YOLO+OCR) 提供UI元素感知
```

## 三、基础设施建设

| 能力 | 技术选型 | 优先级 | 工作量 |
|------|---------|--------|--------|
| UI元素感知 | OmniParser（微软开源，YOLO检测+OCR融合，专为GUI agent设计） | P0 | 2天 |
| 窗口管理 | pywin32（完整Windows API绑定） | P0 | 1天 |
| UI Automation | pywinauto（Win32+UIA双后端） | P1 | 3天 |
| 应用状态检测 | pywin32 + OmniParser | P1 | 2天 |
| 剪贴板高级操作 | win32clipboard | P2 | 1天 |

## 四、具体开发计划

### P0 阶段：核心能力增强（2-3周）
**目标**: 提升鲁棒性和泛化能力，支持3-5个常见应用

| 任务 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| OmniParser集成 | YOLO+OCR UI元素检测，输出带标签控件列表 | 2天 | 无 |
| 窗口管理 | get_active_window/detect_app/activate_window | 1天 | 无 |
| 上下文管理器 | 整合窗口+OmniParser+截图 | 1天 | OmniParser+窗口 |
| 应用特定Prompt | 微信/浏览器/文件管理器prompt + PromptManager | 3天 | 上下文 |
| 多执行器架构 | BaseExecutor + WindowsAPIExecutor | 3天 | 窗口管理 |
| 错误恢复 | 检查点+常见错误处理+弹窗检测 | 2天 | OmniParser |

### P1 阶段：能力扩展（3-4周）
**目标**: 支持浏览器、文件管理、Office操作

| 任务 | 内容 | 工作量 |
|------|------|--------|
| UI Automation | pywinauto集成，控件树获取 | 3天 |
| 浏览器控制器 | Chrome/Edge操作封装 | 3天 |
| 文件管理控制器 | 文件管理器操作封装 | 2天 |
| 任务规划器 | LLM任务分解+子任务编排 | 3天 |
| Shell执行器 | 白名单shell命令 | 2天 |
| 应用状态检测 | 响应检测+弹窗处理+加载等待 | 2天 |

### P2 阶段：智能化（2-3周）
**目标**: 提升任务成功率和用户体验

| 任务 | 内容 | 工作量 |
|------|------|--------|
| 多模型协作 | 大模型规划+7B执行 | 3天 |
| 操作录制回放 | 录制人工操作→自动化脚本 | 3天 |
| 自适应重试 | 根据失败原因调整策略 | 2天 |
| 性能监控 | 任务成功率/耗时/步数统计 | 1天 |

### P3 阶段：生态建设（持续）
- 插件系统（第三方应用控制器）
- 操作知识库（成功操作序列存储复用）
- 模型微调（收集操作数据fine-tune）

## 五、模型层面建议

### 7B模型能力边界
- ✅ 适合：简单GUI操作（1-5步）、按钮点击、文本输入
- ⚠️ 勉强：多步骤流程（5-10步）、需要判断的操作
- ❌ 不适合：复杂推理、多应用切换、异常处理决策

### 多模型协作方案（推荐）
```
用户指令 → 大模型(Claude/GPT-4o)规划子任务
    → 7B模型逐步执行GUI操作
    → 大模型验证结果+异常决策
```

### Prompt优化方向
1. 应用特定UI布局描述（按钮位置、控件名称）
2. Few-shot示例（成功操作序列）
3. 明确的完成条件判断指导
4. 错误恢复指令（"如果看到弹窗，先关闭弹窗"）
