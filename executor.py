"""
安全执行器（白名单 pyautogui 函数）
"""
import re
import pyautogui
from loguru import logger
from typing import Any, Dict


# pyautogui 白名单函数
ALLOWED_FUNCTIONS = {
    'click', 'doubleClick', 'tripleClick', 'rightClick', 'middleClick',
    'moveTo', 'moveRel', 'dragTo', 'dragRel',
    'scroll', 'hscroll', 'vscroll',
    'press', 'keyDown', 'keyUp', 'hotkey', 'write', 'typewrite',
    'screenshot', 'locateOnScreen', 'locateCenterOnScreen',
    'position', 'size'
}


class SafeExecutor:
    """
    安全执行器，只允许执行白名单中的 pyautogui 函数
    """

    def __init__(self, platform: str = "windows"):
        self.platform = platform.lower()
        # Windows 滚动缩放因子
        self.scroll_factor = 50 if self.platform == "windows" else 1

    def execute(self, code: str) -> Dict[str, Any]:
        """
        执行 pyautogui 代码

        Args:
            code: pyautogui 代码字符串

        Returns:
            执行结果字典 {"success": bool, "message": str, "error": str}
        """
        # 特殊命令处理
        if code == "WAIT":
            logger.info("Executing WAIT command")
            return {"success": True, "message": "WAIT", "error": None}

        if code == "DONE":
            logger.info("Task completed successfully")
            return {"success": True, "message": "DONE", "error": None}

        if code == "FAIL":
            logger.warning("Task failed")
            return {"success": False, "message": "FAIL", "error": "Task failed"}

        # 检查代码安全性
        if not self._is_safe(code):
            error_msg = f"Unsafe code detected: {code}"
            logger.error(error_msg)
            return {"success": False, "message": None, "error": error_msg}

        # Windows 滚动缩放
        if self.platform == "windows":
            code = self._scale_scroll(code)

        # 执行代码
        try:
            logger.info(f"Executing: {code}")

            # 创建安全的执行环境
            safe_globals = {
                "pyautogui": pyautogui,
                "__builtins__": {}
            }

            exec(code, safe_globals)

            return {"success": True, "message": "Executed successfully", "error": None}

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": None, "error": error_msg}

    def _is_safe(self, code: str) -> bool:
        """
        检查代码是否安全（只包含白名单函数）
        """
        # 提取所有 pyautogui 函数调用
        pattern = r'pyautogui\.(\w+)\('
        matches = re.findall(pattern, code)

        for func_name in matches:
            if func_name not in ALLOWED_FUNCTIONS:
                logger.warning(f"Disallowed function: {func_name}")
                return False

        # 检查是否包含危险关键字
        dangerous_keywords = ['import', 'exec', 'eval', 'open', 'os.', 'sys.', 'subprocess', '__']
        for keyword in dangerous_keywords:
            if keyword in code:
                logger.warning(f"Dangerous keyword detected: {keyword}")
                return False

        return True

    def _scale_scroll(self, code: str) -> str:
        """
        Windows 平台滚动缩放
        """
        pattern = r'(pyautogui\.scroll\()\s*([-+]?\d+)\s*\)'
        code = re.sub(
            pattern,
            lambda m: f"{m.group(1)}{int(m.group(2)) * self.scroll_factor})",
            code
        )
        return code
