"""
安全执行器（白名单 pyautogui 函数）
"""
import ast
import re
import time
import subprocess
import pyautogui
import pyperclip
from loguru import logger
from typing import Any, Dict, Optional


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
ALLOWED_MODULES = {'time', 'pyperclip'}

# 允许的 time 模块函数
ALLOWED_TIME_FUNCTIONS = {'sleep'}

# 允许的 pyperclip 函数
ALLOWED_PYPERCLIP_FUNCTIONS = {'copy', 'paste'}


class SafeExecutor:
    """
    安全执行器，只允许执行白名单中的 pyautogui 函数
    """

    def __init__(self, platform: str = "windows"):
        self.platform = platform.lower()
        # Windows 滚动缩放因子
        self.scroll_factor = 5 if self.platform == "windows" else 1
        # 关闭 fail-safe（鼠标移到角落不中断）
        pyautogui.FAILSAFE = False
        # 预加载剪贴板内容（用于中文等非ASCII文本粘贴）
        self._clipboard_preload = None
        # 文件预加载路径（clipboard_preload 消费后自动复制文件到剪贴板）
        self._file_preload = None
        # 标记 clipboard_preload 是否已被消费（只粘贴一次）
        self._clipboard_consumed = False
        # 上一次执行的代码（用于检测重复）
        self._last_executed_code = None
        # 连续重复执行计数
        self._repeat_count = 0

    def set_clipboard_preload(self, text: str, file_preload: Optional[str] = None):
        """设置预加载剪贴板内容，并立即写入系统剪贴板"""
        self._clipboard_preload = text
        self._file_preload = file_preload
        self._clipboard_consumed = False
        # 立即写入系统剪贴板，确保第一次 Ctrl+V 能粘贴到正确内容
        pyperclip.copy(text)
        logger.info(f"Clipboard preload written to system clipboard: {text[:50]}")

    def clear_clipboard_preload(self):
        """清除预加载剪贴板内容"""
        self._clipboard_preload = None
        self._file_preload = None
        self._clipboard_consumed = False

    def copy_file_to_clipboard(self, file_path: str):
        """用 PowerShell 把图片作为 Bitmap 复制到系统剪贴板（微信可直接粘贴）"""
        # 判断是否为图片文件
        img_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')
        is_image = file_path.lower().endswith(img_exts)

        if is_image:
            # 图片文件：作为 Bitmap 复制，微信 Ctrl+V 可直接粘贴为图片
            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile('{file_path}')
[System.Windows.Forms.Clipboard]::SetImage($img)
$img.Dispose()
'''
        else:
            # 非图片文件：作为 FileDropList 复制
            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$file = New-Object System.Collections.Specialized.StringCollection
$file.Add('{file_path}')
[System.Windows.Forms.Clipboard]::SetFileDropList($file)
'''
        try:
            result = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                mode = "as image" if is_image else "as file"
                logger.info(f"File copied to clipboard {mode}: {file_path}")
            else:
                logger.error(f"Failed to copy file to clipboard: {result.stderr}")
        except Exception as e:
            logger.error(f"Error copying file to clipboard: {e}")

    def _on_clipboard_consumed(self):
        """clipboard_preload 被消费后的回调：如果有 file_preload，复制文件到剪贴板"""
        if self._file_preload:
            logger.info(f"Clipboard preload consumed, loading file to clipboard: {self._file_preload}")
            self.copy_file_to_clipboard(self._file_preload)

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

        # 检测重复执行（Agent 陷入循环时跳过）
        if code == self._last_executed_code:
            self._repeat_count += 1
            if self._repeat_count >= 2:
                logger.warning(f"Skipping repeated execution (repeat #{self._repeat_count}): {code[:80]}")
                return {"success": True, "message": "Skipped duplicate", "error": None}
        else:
            self._last_executed_code = code
            self._repeat_count = 0

        # 检查代码安全性
        if not self._is_safe(code):
            error_msg = f"Unsafe code detected: {code}"
            logger.error(error_msg)
            return {"success": False, "message": None, "error": error_msg}

        # Windows 滚动缩放
        if self.platform == "windows":
            code = self._scale_scroll(code)

        # 修正 hotkey 列表参数：hotkey(['cmd', 's']) -> hotkey('cmd', 's')
        code = re.sub(
            r"pyautogui\.hotkey\(\[([^\]]+)\]\)",
            r"pyautogui.hotkey(\1)",
            code
        )

        # 如果代码里有 Ctrl+V 且 clipboard_preload 未消费，标记为已消费
        # （agent 可能直接用 hotkey 粘贴而不是 write，preload 已经在剪贴板里了）
        # 注意：file_preload 的加载要在 Ctrl+V 执行之后，否则会覆盖剪贴板
        _needs_file_preload_after = False
        if (self._clipboard_preload and not self._clipboard_consumed
                and re.search(r"pyautogui\.hotkey\(\s*['\"]ctrl['\"]\s*,\s*['\"]v['\"]\s*\)", code)):
            logger.info(f"[clipboard_consumed] Ctrl+V detected, marking preload as consumed")
            self._clipboard_consumed = True
            _needs_file_preload_after = bool(self._file_preload)

        # 将所有 pyautogui.write() 替换为剪贴板粘贴
        # 原因：pyautogui.write 不支持非ASCII字符，在中文系统上不可靠
        def _replace_write_with_clipboard(match):
            text = match.group(1) or match.group(2)
            raw_text = text.strip("'\"")
            logger.info(f"[clipboard_sub] raw_text repr: {repr(raw_text[:80])}")
            logger.info(f"[clipboard_sub] has_preload={self._clipboard_preload is not None}, consumed={self._clipboard_consumed}")
            # 如果有 clipboard_preload 且未消费，使用预加载内容替代
            # 条件：文本长度 > 2 且内容不等于 preload 本身（模型输出了拼音/乱码）
            if (self._clipboard_preload and not self._clipboard_consumed
                    and len(raw_text) > 2
                    and raw_text.strip() != self._clipboard_preload.strip()):
                logger.info(f"Substituting '{raw_text[:40]}' with clipboard_preload: '{self._clipboard_preload}'")
                self._clipboard_consumed = True
                self._on_clipboard_consumed()
                escaped = self._clipboard_preload.replace("\\", "\\\\").replace("'", "\\'")
                return f"pyperclip.copy('{escaped}')\npyautogui.hotkey('ctrl', 'v')"
            # 无 preload 或已消费：仍然走剪贴板粘贴（比 write 可靠）
            return f"pyperclip.copy({text})\npyautogui.hotkey('ctrl', 'v')"
        # 匹配 pyautogui.write(message='...') 和 pyautogui.write('...')
        code = re.sub(
            r"pyautogui\.write\(message=((?:'[^']*'|\"[^\"]*\"))\)",
            _replace_write_with_clipboard,
            code
        )
        code = re.sub(
            r"pyautogui\.(?:write|typewrite)\(((?:'[^']*'|\"[^\"]*\"))\)",
            _replace_write_with_clipboard,
            code
        )

        # 执行代码
        try:
            logger.info(f"Executing: {code}")

            # 创建安全的执行环境（只提供白名单模块）
            safe_globals = {
                "pyautogui": pyautogui,
                "pyperclip": pyperclip,
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

            # 代码执行完毕后，如果需要加载文件到剪贴板，现在执行
            # （必须在 Ctrl+V 粘贴文字之后，否则会覆盖剪贴板内容）
            # 延迟 1 秒确保 Windows 粘贴动作完成（hotkey 返回不代表粘贴完成）
            if _needs_file_preload_after:
                time.sleep(1)
                self._on_clipboard_consumed()

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
                        elif module_name == 'pyperclip':
                            if func_name not in ALLOWED_PYPERCLIP_FUNCTIONS:
                                logger.warning(f"Disallowed pyperclip function: {func_name}")
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
