"""错误恢复管理器 - 检测常见错误并提供恢复策略"""
import time
from loguru import logger
from window_manager import WindowManager


class RecoveryManager:
    def __init__(self):
        self.wm = WindowManager()
        self.checkpoints = []

    def save_checkpoint(self, step: int, screenshot: bytes):
        self.checkpoints.append({"step": step, "screenshot": screenshot, "time": time.time()})
        if len(self.checkpoints) > 10:
            self.checkpoints.pop(0)

    def check_and_recover(self, step: int, action_text: str, context: dict) -> dict:
        """检查是否需要恢复，返回 {"needs_recovery": bool, "recovery_hint": str}"""
        # 检查应用是否还在前台
        active = self.wm.get_active_window()
        expected_app = context.get("active_app", "unknown")
        current_app = self.wm.detect_app()

        if expected_app != "unknown" and current_app != expected_app:
            logger.warning(f"App switched: expected={expected_app}, current={current_app}")
            # 尝试切回目标应用
            app_titles = {"wechat": "微信", "chrome": "Chrome", "edge": "Edge"}
            title = app_titles.get(expected_app, "")
            if title and self.wm.activate_window(title):
                return {"needs_recovery": False, "recovery_hint": f"Auto-switched back to {expected_app}"}
            return {"needs_recovery": True, "recovery_hint": f"Target app '{expected_app}' lost focus. Current: {current_app}"}

        # 检查是否有弹窗（窗口标题变化可能意味着弹窗）
        if active["title"] and any(kw in active["title"] for kw in ["错误", "Error", "警告", "Warning"]):
            return {"needs_recovery": True, "recovery_hint": f"Error dialog detected: {active['title']}. Try pressing Escape or clicking Cancel."}

        return {"needs_recovery": False, "recovery_hint": ""}
