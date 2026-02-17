"""上下文管理器 - 整合窗口管理+截图，预留OmniParser接口"""
import time
import base64
from loguru import logger
from window_manager import WindowManager
from screenshot import capture_screenshot


class ContextManager:
    def __init__(self):
        self.wm = WindowManager()

    def get_context(self) -> dict:
        start = time.time()

        # 截图
        screenshot_bytes, _ = capture_screenshot()
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

        # 窗口信息
        active_window = self.wm.get_active_window()
        active_app = self.wm.detect_app()

        ctx = {
            "screenshot_bytes": screenshot_bytes,
            "screenshot_base64": screenshot_b64,
            "active_window": active_window,
            "active_app": active_app,
            "window_list": self.wm.list_windows(),
            "omniparser_elements": [],  # 预留OmniParser接口
        }

        elapsed = (time.time() - start) * 1000
        logger.info(f"Context collected in {elapsed:.0f}ms | app={active_app} | window={active_window['title'][:30]}")
        return ctx
