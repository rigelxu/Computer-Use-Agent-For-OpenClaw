"""
FastAPI 服务入口
"""
# 加载 .env（必须在 import config 之前）
from dotenv import load_dotenv
load_dotenv()

import asyncio
import time
import uuid
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from loguru import logger

import config
from agent import OpenCUAAgent
from executor import SafeExecutor
from context_manager import ContextManager
from prompts.manager import PromptManager
from recovery_manager import RecoveryManager
from screenshot import capture_screenshot, get_screen_size
from llm.router import LLMRouter, AgentAction, ActionType
from action_retry_manager import ActionRetryManager, action_to_pyautogui


app = FastAPI(title="Computer Use Agent", version="1.0.0")

# 全局实例
context_mgr = ContextManager(use_omniparser=config.OMNIPARSER_ENABLED)
prompt_mgr = PromptManager()
recovery_mgr = RecoveryManager()

# 任务存储
tasks: Dict[str, dict] = {}
MAX_TASKS = 50  # 最多保留任务数

# 并发控制：同一时间只允许一个任务运行
_task_lock = asyncio.Lock()

# Agent 和 Executor
agent: Optional[OpenCUAAgent] = None
executor: Optional[SafeExecutor] = None
llm_router: Optional[LLMRouter] = None
retry_mgr: Optional[ActionRetryManager] = None

# API 认证
security = HTTPBearer()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """验证 API Key"""
    if credentials.credentials != config.API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


class TaskRequest(BaseModel):
    prompt: str = Field(..., max_length=10000)
    max_steps: Optional[int] = Field(default=config.MAX_STEPS, ge=1, le=100)
    timeout: Optional[int] = Field(default=config.TASK_TIMEOUT, ge=10, le=600)
    clipboard_preload: Optional[str] = Field(default=None, max_length=1000)
    file_preload: Optional[str] = Field(default=None, max_length=500)
    confirm_before_send: Optional[bool] = False


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    prompt: str
    steps: int
    result: Optional[str] = None
    error: Optional[str] = None
    history: list


@app.on_event("startup")
async def startup_event():
    """启动时初始化 Agent 和 Executor"""
    global agent, executor, llm_router, retry_mgr

    logger.info("Initializing Computer Use Agent...")

    # 获取屏幕尺寸
    screen_width, screen_height = get_screen_size()
    logger.info(f"Screen size: {screen_width}x{screen_height}")

    # 初始化 LLM Router（Claude 优先，OpenCUA 兜底）
    llm_router = LLMRouter()

    # 初始化 ActionRetryManager
    if config.ACTION_RETRY_ENABLED:
        retry_mgr = ActionRetryManager(
            max_retries=config.ACTION_RETRY_MAX,
            change_threshold=config.ACTION_CHANGE_THRESHOLD,
        )

    # 初始化传统 Agent（向后兼容）
    model_name = config.LLM_MODEL if config.LLM_PROVIDER == "anthropic" else config.VLLM_MODEL_NAME
    agent = OpenCUAAgent(
        model=model_name,
        history_type="thought_history",
        max_steps=config.MAX_STEPS,
        max_image_history_length=config.MAX_IMAGE_HISTORY_LENGTH,
        platform=config.PLATFORM,
        max_tokens=config.MAX_TOKENS,
        top_p=config.TOP_P,
        temperature=config.TEMPERATURE,
        cot_level=config.COT_LEVEL,
        screen_size=(screen_width, screen_height),
        coordinate_type=config.COORDINATE_TYPE,
        password="password"
    )

    # 初始化 Executor
    executor = SafeExecutor(platform=config.PLATFORM)

    logger.info(f"Agent initialized successfully (provider={config.LLM_PROVIDER})")


@app.post("/task", response_model=TaskResponse)
async def create_task(request: TaskRequest, api_key: str = Depends(verify_api_key)):
    """创建新任务"""
    # 并发控制：检查是否有任务在运行
    running_tasks = [t for t in tasks.values() if t["status"] in ("pending", "running", "awaiting_confirm")]
    if running_tasks:
        raise HTTPException(status_code=409, detail="Another task is already running. Wait for it to finish or stop it first.")

    # 任务清理：保留最近 MAX_TASKS 个
    if len(tasks) >= MAX_TASKS:
        sorted_tasks = sorted(tasks.items(), key=lambda x: x[1].get("created_at", 0))
        for tid, _ in sorted_tasks[:len(tasks) - MAX_TASKS + 1]:
            if tasks[tid]["status"] not in ("pending", "running", "awaiting_confirm"):
                del tasks[tid]

    task_id = str(uuid.uuid4())

    tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "prompt": request.prompt,
        "max_steps": request.max_steps,
        "timeout": request.timeout,
        "clipboard_preload": request.clipboard_preload,
        "file_preload": request.file_preload,
        "confirm_before_send": request.confirm_before_send,
        "confirm_event": asyncio.Event() if request.confirm_before_send else None,
        "confirm_result": None,  # "yes" or "no"
        "pending_code": None,  # 等待确认时暂存的代码
        "steps": 0,
        "result": None,
        "error": None,
        "history": [],
        "created_at": time.time()
    }

    # 异步执行任务
    asyncio.create_task(execute_task(task_id))

    return TaskResponse(
        task_id=task_id,
        status="pending",
        message="Task created successfully"
    )


@app.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, api_key: str = Depends(verify_api_key)):
    """查询任务状态"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        prompt=task["prompt"],
        steps=task["steps"],
        result=task["result"],
        error=task["error"],
        history=task["history"]
    )


@app.post("/task/{task_id}/stop")
async def stop_task(task_id: str, api_key: str = Depends(verify_api_key)):
    """停止任务"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] in ("running", "awaiting_confirm"):
        task["status"] = "stopped"
        task["error"] = "Task stopped by user"
        # 如果在等待确认，释放事件
        if task.get("confirm_event"):
            task["confirm_result"] = "no"
            task["confirm_event"].set()
        return {"message": "Task stopped successfully"}
    else:
        return {"message": f"Task is not running (status: {task['status']})"}


class ConfirmRequest(BaseModel):
    confirm: bool = True  # True=继续发送, False=取消


@app.post("/task/{task_id}/confirm")
async def confirm_task(task_id: str, request: ConfirmRequest, api_key: str = Depends(verify_api_key)):
    """确认或拒绝待确认的发送操作"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] != "awaiting_confirm":
        return {"message": f"Task is not awaiting confirmation (status: {task['status']})"}

    task["confirm_result"] = "yes" if request.confirm else "no"
    task["confirm_event"].set()
    action = "confirmed" if request.confirm else "rejected"
    return {"message": f"Task {action} successfully"}


@app.get("/task/{task_id}/screenshot")
async def get_task_screenshot(task_id: str, api_key: str = Depends(verify_api_key)):
    """获取任务当前截图（用于确认前查看）"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        screenshot_bytes, _ = capture_screenshot()
        from utils import encode_image
        screenshot_base64 = encode_image(screenshot_bytes)
        return {
            "success": True,
            "task_id": task_id,
            "status": tasks[task_id]["status"],
            "screenshot": f"data:image/png;base64,{screenshot_base64}"
        }
    except Exception as e:
        logger.error(f"Failed to capture screenshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/screenshot")
async def get_screenshot(api_key: str = Depends(verify_api_key)):
    """获取当前截图（调试用）"""
    try:
        screenshot_bytes = capture_screenshot()
        from utils import encode_image
        screenshot_base64 = encode_image(screenshot_bytes)
        return {
            "success": True,
            "screenshot": f"data:image/png;base64,{screenshot_base64}"
        }
    except Exception as e:
        logger.error(f"Failed to capture screenshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _desktop_rename(instruction: str, task: dict) -> bool:
    """桌面重命名快捷路径：直接用 os.rename"""
    import re as _re, os, glob

    m = _re.search(r'(?:to|为|成)\s+(\S+\.(?:png|jpg|txt|pdf|docx?|xlsx?|zip|exe))', instruction, _re.I)
    if not m:
        return False
    new_name = m.group(1)
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    files = [f for f in os.listdir(desktop) if os.path.isfile(os.path.join(desktop, f))]
    if len(files) != 1:
        # 多个文件时尝试从指令中匹配源文件名
        return False
    old_path = os.path.join(desktop, files[0])
    new_path = os.path.join(desktop, new_name)
    os.rename(old_path, new_path)
    task["status"] = "completed"
    task["result"] = f"Renamed {files[0]} -> {new_name}"
    logger.info(f"Desktop rename: {files[0]} -> {new_name}")
    return True


async def execute_task(task_id: str):
    """执行任务（后台异步）"""
    task = tasks[task_id]
    task["status"] = "running"

    start_time = time.time()
    max_steps = task["max_steps"]
    timeout = task["timeout"]
    confirm_before_send = task.get("confirm_before_send", False)

    # 发送相关关键词（仅匹配 action 文本中明确的发送按钮点击）
    SEND_ACTION_PATTERNS = [
        '点击发送', '点击"发送"', '点击"发送"', '确认发送',
        'click the send', 'click send', 'press send',
        'click the "send"', "click the 'send'",
        '发送(S)', '发送按钮',
    ]

    def _is_send_action(action_text: str, thought_text: str) -> bool:
        """检测当前动作是否是真正的发送按钮点击（只看 action，不看 thought）"""
        action_lower = (action_text or '').lower()
        for pattern in SEND_ACTION_PATTERNS:
            if pattern.lower() in action_lower:
                return True
        return False

    try:
        # 重置 Agent
        agent.reset()
        llm_router.reset()
        task_history = []  # LLMRouter 用的历史

        # 预加载剪贴板内容（用于中文等非ASCII文本）
        clipboard_text = task.get("clipboard_preload")
        file_preload = task.get("file_preload")
        if clipboard_text:
            executor.set_clipboard_preload(clipboard_text, file_preload=file_preload)
            logger.info(f"Clipboard preload set: {clipboard_text[:50]}...")
            if file_preload:
                logger.info(f"File preload set: {file_preload}")
        else:
            executor.clear_clipboard_preload()
            # 如果只有 file_preload 没有 clipboard_preload，直接把文件复制到剪贴板
            if file_preload:
                executor.copy_file_to_clipboard(file_preload)
                logger.info(f"File copied to clipboard: {file_preload}")

        instruction = task["prompt"]
        logger.info(f"Starting task {task_id}: {instruction}")

        # 任务开始前：激活目标应用并最大化
        try:
            from window_manager import WindowManager
            import win32gui, win32con
            wm = WindowManager()
            current_app = wm.detect_app()
            prompt_lower = instruction.lower()
            needs_wechat = "微信" in prompt_lower or "wechat" in prompt_lower
            # 只有桌面文件操作（rename/delete/move 桌面上的文件）才最小化窗口
            _desktop_ops = any(k in prompt_lower for k in ["rename", "重命名", "delete", "删除"])
            needs_desktop = ("desktop" in prompt_lower or "桌面" in prompt_lower) and _desktop_ops

            if needs_desktop:
                # 最小化所有窗口，露出桌面
                import win32gui, win32con as _wc
                def _min_all(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                        cls = win32gui.GetClassName(hwnd)
                        if cls not in ('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
                            try: win32gui.ShowWindow(hwnd, _wc.SW_MINIMIZE)
                            except: pass
                    return True
                win32gui.EnumWindows(_min_all, None)
                await asyncio.sleep(1)
            elif needs_wechat and current_app != "wechat":
                for w in wm.list_windows():
                    if any(kw in w["process_name"].lower() for kw in ["powershell", "cmd", "windowsterminal"]):
                        try:
                            win32gui.ShowWindow(w["hwnd"], win32con.SW_MINIMIZE)
                        except:
                            pass
                await asyncio.sleep(0.5)
                wm.activate_window("微信")
                await asyncio.sleep(1)
            else:
                wm.maximize_window()
            await asyncio.sleep(0.5)
            logger.info(f"Window prepared: app={wm.detect_app()}")
        except Exception as e:
            logger.warning(f"Failed to prepare window: {e}")

        # 桌面重命名快捷路径：直接用 Win32 API，跳过 agent 循环
        if needs_desktop and "rename" in prompt_lower:
            try:
                result = await _desktop_rename(instruction, task)
                if result:
                    return
            except Exception as e:
                logger.warning(f"Desktop rename shortcut failed: {e}, falling back to agent")

        for step in range(1, max_steps + 1):
            # 检查超时
            if time.time() - start_time > timeout:
                task["status"] = "timeout"
                task["error"] = f"Task timeout after {timeout} seconds"
                logger.warning(f"Task {task_id} timeout")
                break

            # 检查是否被停止
            if task["status"] == "stopped":
                logger.info(f"Task {task_id} stopped by user")
                break

            # 获取上下文（截图+窗口信息+SoM）
            ctx = context_mgr.get_context()
            screenshot_bytes = ctx["screenshot_bytes"]

            # 错误恢复检查
            recovery = recovery_mgr.check_and_recover(step, "", ctx)
            if recovery["recovery_hint"]:
                logger.info(f"Recovery: {recovery['recovery_hint']}")
                ctx["recovery_hint"] = recovery["recovery_hint"]

            # LLMRouter 预测（Claude 优先，OpenCUA 兜底）
            agent_action = llm_router.predict(
                instruction=instruction,
                context=ctx,
                history=task_history,
                step_idx=step,
            )

            # 转为可执行代码
            action_code = action_to_pyautogui(agent_action)

            # 记录历史
            from utils import encode_image as _enc
            task_history.append({
                "step": step,
                "thought": agent_action.thought,
                "action": action_code,
                "raw_response": agent_action.raw_response,
                "screenshot_b64": _enc(screenshot_bytes),
            })
            task["history"].append({
                "step": step,
                "action": action_code,
                "thought": agent_action.thought,
                "code": action_code,
                "response": agent_action.raw_response,
            })
            task["steps"] = step

            # 终止动作
            if agent_action.action_type == ActionType.DONE:
                task["status"] = "completed"
                task["result"] = "Task completed successfully"
                logger.info(f"Task {task_id} completed")
                break

            if agent_action.action_type == ActionType.FAIL:
                task["status"] = "failed"
                task["error"] = "Task failed"
                logger.error(f"Task {task_id} failed")
                break

            if agent_action.action_type == ActionType.WAIT:
                logger.info("Waiting 20 seconds...")
                await asyncio.sleep(20)
                continue

            # 发送前确认机制
            if confirm_before_send and _is_send_action(action_code, agent_action.thought or ""):
                logger.info(f"Task {task_id} step {step}: send action detected, awaiting confirmation")
                task["status"] = "awaiting_confirm"
                task["pending_code"] = action_code
                task["confirm_event"].clear()

                # 等待确认（最多等 5 分钟）
                try:
                    await asyncio.wait_for(task["confirm_event"].wait(), timeout=300)
                except asyncio.TimeoutError:
                    task["status"] = "timeout"
                    task["error"] = "Confirmation timeout (5 min)"
                    logger.warning(f"Task {task_id} confirmation timeout")
                    break

                if task["confirm_result"] != "yes":
                    task["status"] = "cancelled"
                    task["error"] = "Send action rejected by user"
                    logger.info(f"Task {task_id} cancelled by user")
                    break

                # 确认通过，继续执行
                task["status"] = "running"
                logger.info(f"Task {task_id} confirmed, executing send action")

                # 执行发送动作
                exec_result = executor.execute(action_code)
                if not exec_result["success"]:
                    task["status"] = "failed"
                    task["error"] = exec_result.get("error", "Task failed")
                    logger.error(f"Task {task_id} failed: {task['error']}")
                    break

                # 发送后验证：等待后截图，让 agent 判断是否发送成功
                # 重试最多 3 次，每次间隔 3 秒
                send_verified = False
                for retry in range(3):
                    await asyncio.sleep(3)
                    verify_ctx = context_mgr.get_context()
                    verify_action = llm_router.predict(
                        instruction=(
                            "请检查当前屏幕：发送是否成功？\n"
                            "判断标准：聊天输入框/预览区域中没有待发送的图片或文件，"
                            "且聊天记录中出现了刚才发送的内容。\n"
                            "如果发送成功，输出 done。\n"
                            "如果输入框中仍有待发送的内容（发送按钮还在），请点击发送按钮重试。"
                        ),
                        context=verify_ctx,
                        history=task_history,
                        step_idx=step + retry + 1,
                    )
                    verify_code = action_to_pyautogui(verify_action)

                    task["history"].append({
                        "step": step + retry + 1,
                        "action": verify_code,
                        "thought": verify_action.thought,
                        "code": verify_code,
                        "response": verify_action.raw_response,
                        "verify_retry": retry
                    })
                    task["steps"] = step + retry + 1
                    logger.info(f"Send verify retry {retry}: code={verify_code}")

                    if verify_action.action_type == ActionType.DONE:
                        send_verified = True
                        logger.info(f"Task {task_id}: send verified after {retry} retries")
                        break
                    elif verify_action.action_type == ActionType.FAIL:
                        logger.warning(f"Task {task_id}: send verification reports failure")
                        break
                    else:
                        executor.execute(verify_code)

                if send_verified:
                    task["status"] = "completed"
                    task["result"] = "Task completed successfully (send verified)"
                    logger.info(f"Task {task_id} completed with send verification")
                else:
                    task["status"] = "failed"
                    task["error"] = "Send verification failed after retries"
                    logger.error(f"Task {task_id}: send verification failed")
                break  # 发送流程结束，退出主循环

            # 执行
            before_screenshot = screenshot_bytes
            exec_result = executor.execute(action_code)

            if not exec_result["success"]:
                task["status"] = "failed"
                task["error"] = exec_result.get("error", "Task failed")
                logger.error(f"Task {task_id} failed: {task['error']}")
                break

            # 短暂延迟
            await asyncio.sleep(1)

            # 动作效果验证 + 自动重试
            if retry_mgr and agent_action.action_type in (ActionType.CLICK, ActionType.SCROLL):
                import random
                after_ctx = context_mgr.get_context()
                effect = retry_mgr.check_action_effect(
                    before_screenshot, after_ctx["screenshot_bytes"], agent_action)
                task_history[-1]["changed"] = effect["changed"]
                if not effect["changed"]:
                    # 最多重试 1 次，避免点空白区域时死循环
                    max_retry = min(retry_mgr.max_retries, 1)
                    for r in range(max_retry):
                        logger.warning(f"No effect (ratio={effect['change_ratio']:.4f}), retry {r+1}")
                        if effect["suggestion"] == "retry" and agent_action.x and agent_action.y:
                            agent_action.x += random.choice([-3, 0, 3])
                            agent_action.y += random.choice([-3, 0, 3])
                            executor.execute(action_to_pyautogui(agent_action))
                        elif effect["suggestion"] == "scroll_down":
                            executor.execute("pyautogui.scroll(-3)")
                        await asyncio.sleep(1)
                        after_ctx2 = context_mgr.get_context()
                        effect = retry_mgr.check_action_effect(
                            before_screenshot, after_ctx2["screenshot_bytes"], agent_action)
                        if effect["changed"]:
                            break

        # 如果循环结束但没有明确状态
        if task["status"] == "running":
            task["status"] = "failed"
            task["error"] = f"Reached maximum steps ({max_steps})"

    except Exception as e:
        logger.error(f"Task {task_id} error: {e}")
        task["status"] = "error"
        task["error"] = str(e)

    finally:
        elapsed = time.time() - start_time
        logger.info(f"Task {task_id} finished in {elapsed:.2f}s with status: {task['status']}")


@app.get("/")
async def root(api_key: str = Depends(verify_api_key)):
    """根路径"""
    return {
        "service": "Computer Use Agent",
        "version": "1.0.0",
        "status": "running"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.FASTAPI_HOST,
        port=config.FASTAPI_PORT,
        log_level="info"
    )
