"""Windows 窗口管理模块"""
import win32gui
import win32process
import win32con
import psutil
from loguru import logger
from typing import Optional


APP_MAPPING = {
    "wechat.exe": "wechat",
    "weixin.exe": "wechat",
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "explorer.exe": "file_explorer",
    "notepad.exe": "notepad",
    "winword.exe": "word",
    "excel.exe": "excel",
    "powerpnt.exe": "powerpoint",
    "code.exe": "vscode",
}


class WindowManager:
    def get_active_window(self) -> dict:
        """获取当前活跃窗口信息"""
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                process_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = "unknown"
            return {
                "hwnd": hwnd,
                "title": title,
                "process_name": process_name,
                "pid": pid,
                "rect": rect,
            }
        except Exception as e:
            logger.error(f"Failed to get active window: {e}")
            return {"hwnd": 0, "title": "", "process_name": "unknown", "pid": 0, "rect": (0, 0, 0, 0)}

    def detect_app(self) -> str:
        """根据活跃窗口进程名识别应用"""
        window = self.get_active_window()
        name = window["process_name"].lower()
        return APP_MAPPING.get(name, "unknown")

    def activate_window(self, title_pattern: str) -> bool:
        """通过标题模糊匹配激活窗口"""
        target = title_pattern.lower()
        results = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if target in title.lower():
                    results.append(hwnd)
            return True

        win32gui.EnumWindows(callback, None)
        if not results:
            logger.warning(f"No window matching '{title_pattern}'")
            return False
        try:
            hwnd = results[0]
            # 如果最小化先恢复
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            logger.info(f"Activated window: {win32gui.GetWindowText(hwnd)}")
            return True
        except Exception as e:
            logger.error(f"Failed to activate window: {e}")
            return False

    def list_windows(self) -> list:
        """列出所有可见窗口"""
        windows = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    process_name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_name = "unknown"
                windows.append({
                    "hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "process_name": process_name,
                })
            return True

        win32gui.EnumWindows(callback, None)
        return windows

    def maximize_window(self, hwnd: Optional[int] = None) -> bool:
        """最大化指定窗口，默认当前活跃窗口"""
        if hwnd is None:
            hwnd = win32gui.GetForegroundWindow()
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            logger.info(f"Maximized window: {win32gui.GetWindowText(hwnd)}")
            return True
        except Exception as e:
            logger.error(f"Failed to maximize window: {e}")
            return False
