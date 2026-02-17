"""Windows API 执行器 - 窗口管理等非 pyautogui 操作"""
from loguru import logger
from window_manager import WindowManager


class WindowsAPIExecutor:
    def __init__(self):
        self.wm = WindowManager()

    def execute(self, action: str, params: dict) -> dict:
        """执行 Windows API 操作"""
        handler = {
            "activate_window": self._activate_window,
            "maximize_window": self._maximize_window,
            "get_active_window": self._get_active_window,
            "list_windows": self._list_windows,
        }.get(action)

        if not handler:
            return {"success": False, "error": f"Unknown action: {action}"}

        try:
            return handler(params)
        except Exception as e:
            logger.error(f"WindowsAPI action '{action}' failed: {e}")
            return {"success": False, "error": str(e)}

    def _activate_window(self, params: dict) -> dict:
        title = params.get("title", "")
        ok = self.wm.activate_window(title)
        return {"success": ok}

    def _maximize_window(self, params: dict) -> dict:
        hwnd = params.get("hwnd")
        ok = self.wm.maximize_window(hwnd)
        return {"success": ok}

    def _get_active_window(self, params: dict) -> dict:
        return {"success": True, "data": self.wm.get_active_window()}

    def _list_windows(self, params: dict) -> dict:
        return {"success": True, "data": self.wm.list_windows()}
