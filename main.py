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
    if task["status"] == "running":
        task["status"] = "stopped"
        task["error"] = "Task stopped by user"
        return {"message": "Task stopped successfully"}
    else:
        return {"message": f"Task is not running (status: {task['status']})"}


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

    try:
        # 重置 Agent
        agent.reset()

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

            # 执行
            exec_result = executor.execute(action_code)

            if action_code == "DONE":
                task["status"] = "completed"
                task["result"] = "Task completed successfully"
                logger.info(f"Task {task_id} completed")
                break

            if action_code == "FAIL" or not exec_result["success"]:
                task["status"] = "failed"
                task["error"] = exec_result.get("error", "Task failed")
                logger.error(f"Task {task_id} failed: {task['error']}")
                break

            if action_code == "WAIT":
                logger.info("Waiting 20 seconds...")
                await asyncio.sleep(20)
                continue

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
