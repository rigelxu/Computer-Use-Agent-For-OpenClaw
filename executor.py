"""
安全执行器（白名单 pyautogui 函数）
"""
import ast
import re
import time
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

# 允许的模块
ALLOWED_MODULES = {'time'}

# 允许的 time 模块函数
ALLOWED_TIME_FUNCTIONS = {'sleep'}


class SafeExecutor:
    """
    安全执行器，只允许执行白名单中的 pyautogui 函数
    """

    def __init__(self, platform: str = "windows"):
        self.platform = platform.lower()
        # Windows 滚动缩放因子
        self.scroll_factor = 50 if self.platform == "windows" else 1
        # 关闭 fail-safe（鼠标移到角落不中断）
        pyautogui.FAILSAFE = False

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

            # 创建安全的执行环境（只提供白名单模块）
            safe_globals = {
                "pyautogui": pyautogui,
                "time": time,
                "__builtins__": {
                    # 只允许基本类型和操作
                    "int": int,
                    "float": float,
                    "str": str,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "tuple": tuple,
                    "range": range,
                    "len": len,
                    "min": min,
                    "max": max,
                }
            }

            exec(code, safe_globals)

            return {"success": True, "message": "Executed successfully", "error": None}

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": None, "error": error_msg}

    def _is_safe(self, code: str) -> bool:
        """
        使用 AST 检查代码是否安全（白名单验证）
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.warning(f"Syntax error in code: {e}")
            return False

        # 遍历 AST 节点
        for node in ast.walk(tree):
            # 禁止 import（除了已有的 pyautogui 和 time）
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name not in ALLOWED_MODULES:
                            logger.warning(f"Disallowed import: {alias.name}")
                            return False
                elif isinstance(node, ast.ImportFrom):
                    if node.module not in ALLOWED_MODULES:
                        logger.warning(f"Disallowed import from: {node.module}")
                        return False

            # 检查函数调用
            if isinstance(node, ast.Call):
                # pyautogui.xxx() 调用
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        module_name = node.func.value.id
                        func_name = node.func.attr

                        if module_name == 'pyautogui':
                            if func_name not in ALLOWED_FUNCTIONS:
                                logger.warning(f"Disallowed pyautogui function: {func_name}")
                                return False
                        elif module_name == 'time':
                            if func_name not in ALLOWED_TIME_FUNCTIONS:
                                logger.warning(f"Disallowed time function: {func_name}")
                                return False
                        else:
                            logger.warning(f"Disallowed module call: {module_name}.{func_name}")
                            return False
                    else:
                        # 禁止属性链访问（如 obj.__class__.__bases__）
                        logger.warning(f"Disallowed attribute chain access")
                        return False

            # 禁止访问 __ 开头的属性（防止沙箱绕过）
            if isinstance(node, ast.Attribute):
                if node.attr.startswith('__'):
                    logger.warning(f"Disallowed dunder attribute: {node.attr}")
                    return False

            # 禁止 exec/eval
            if isinstance(node, ast.Name):
                if node.id in ('exec', 'eval', 'compile', '__import__'):
                    logger.warning(f"Disallowed builtin: {node.id}")
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
