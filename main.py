"""
FastAPI 服务入口
"""
import asyncio
import time
import uuid
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from loguru import logger

import config
from agent import OpenCUAAgent
from executor import SafeExecutor
from screenshot import capture_screenshot, get_screen_size


app = FastAPI(title="Computer Use Agent", version="1.0.0")

# 任务存储
tasks: Dict[str, dict] = {}

# Agent 和 Executor
agent: Optional[OpenCUAAgent] = None
executor: Optional[SafeExecutor] = None

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
    prompt: str
    max_steps: Optional[int] = config.MAX_STEPS
    timeout: Optional[int] = config.TASK_TIMEOUT
    clipboard_preload: Optional[str] = None  # 预先加载到剪贴板的文字（用于中文等非ASCII文本）
    confirm_before_send: Optional[bool] = False  # 发送前暂停等待确认


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
    global agent, executor

    logger.info("Initializing Computer Use Agent...")

    # 获取屏幕尺寸
    screen_width, screen_height = get_screen_size()
    logger.info(f"Screen size: {screen_width}x{screen_height}")

    # 初始化 Agent
    agent = OpenCUAAgent(
        model=config.VLLM_MODEL_NAME,
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

    logger.info("Agent initialized successfully")


@app.post("/task", response_model=TaskResponse)
async def create_task(request: TaskRequest, api_key: str = Depends(verify_api_key)):
    """创建新任务"""
    task_id = str(uuid.uuid4())

    tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "prompt": request.prompt,
        "max_steps": request.max_steps,
        "timeout": request.timeout,
        "clipboard_preload": request.clipboard_preload,
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

        # 预加载剪贴板内容（用于中文等非ASCII文本）
        clipboard_text = task.get("clipboard_preload")
        if clipboard_text:
            executor.set_clipboard_preload(clipboard_text)
            logger.info(f"Clipboard preload set: {clipboard_text[:50]}...")
        else:
            executor.clear_clipboard_preload()

        instruction = task["prompt"]
        logger.info(f"Starting task {task_id}: {instruction}")

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

            # 截图
            screenshot_bytes, screenshot_scale = capture_screenshot()
            obs = {"screenshot": screenshot_bytes, "screenshot_scale": screenshot_scale}

            # Agent 预测
            response, actions, cot = agent.predict(
                instruction=instruction,
                obs=obs,
                step_idx=step
            )

            # 记录历史
            task["history"].append({
                "step": step,
                "action": cot.get("action"),
                "thought": cot.get("thought"),
                "code": cot.get("code"),
                "response": response
            })
            task["steps"] = step

            # 执行动作
            if not actions:
                task["status"] = "failed"
                task["error"] = "No actions returned from agent"
                break

            action_code = actions[0]

            if action_code == "DONE":
                task["status"] = "completed"
                task["result"] = "Task completed successfully"
                logger.info(f"Task {task_id} completed")
                break

            if action_code == "FAIL":
                task["status"] = "failed"
                task["error"] = "Task failed"
                logger.error(f"Task {task_id} failed")
                break

            if action_code == "WAIT":
                logger.info("Waiting 20 seconds...")
                await asyncio.sleep(20)
                continue

            # 发送前确认机制
            if confirm_before_send and _is_send_action(cot.get("action", ""), cot.get("thought", "")):
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
                    verify_screenshot, verify_scale = capture_screenshot()
                    verify_obs = {"screenshot": verify_screenshot, "screenshot_scale": verify_scale}

                    verify_response, verify_actions, verify_cot = agent.predict(
                        instruction=(
                            "请检查当前屏幕：发送是否成功？\n"
                            "判断标准：聊天输入框/预览区域中没有待发送的图片或文件，"
                            "且聊天记录中出现了刚才发送的内容。\n"
                            "如果发送成功，请 terminate。\n"
                            "如果输入框中仍有待发送的内容（发送按钮还在），请点击发送按钮重试。"
                        ),
                        obs=verify_obs,
                        step_idx=step + retry + 1
                    )

                    task["history"].append({
                        "step": step + retry + 1,
                        "action": verify_cot.get("action"),
                        "thought": verify_cot.get("thought"),
                        "code": verify_cot.get("code"),
                        "response": verify_response,
                        "verify_retry": retry
                    })
                    task["steps"] = step + retry + 1

                    verify_code = verify_actions[0] if verify_actions else "DONE"
                    logger.info(f"Send verify retry {retry}: action={verify_cot.get('action', '')[:60]}, code={verify_code}")

                    if verify_code == "DONE":
                        send_verified = True
                        logger.info(f"Task {task_id}: send verified successfully after {retry} retries")
                        break
                    elif verify_code == "FAIL":
                        logger.warning(f"Task {task_id}: send verification reports failure")
                        break
                    else:
                        # agent 要重试点击发送，执行它
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
            exec_result = executor.execute(action_code)

            if not exec_result["success"]:
                task["status"] = "failed"
                task["error"] = exec_result.get("error", "Task failed")
                logger.error(f"Task {task_id} failed: {task['error']}")
                break

            # 短暂延迟
            await asyncio.sleep(1)

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
