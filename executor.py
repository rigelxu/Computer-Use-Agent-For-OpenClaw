"""
安全执行器（白名单 pyautogui 函数）
"""
import ast
import os
import re
import time
import subprocess
import pyautogui
import pyperclip
from win32_keyboard import send_hotkey as _win32_hotkey
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
        # pywinauto 前台窗口缓存
        self._pwa_app = None
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

    # pyautogui key name → Win32 VK code
    _VK_MAP = {
        'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B,
        'enter': 0x0D, 'tab': 0x09, 'escape': 0x1B, 'esc': 0x1B,
        'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E, 'space': 0x20,
        'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
        'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
        'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
        'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
        'f11': 0x7A, 'f12': 0x7B,
    }
    _MODIFIER_VKS = {0x11, 0x10, 0x12, 0x5B}  # ctrl, shift, alt, win

    def _win32_send_keys(self, vk_codes: list):
        """用 AttachThreadInput + PostMessage 发键盘事件（Hyper-V VM 唯一可靠方案）"""
        import win32gui, win32con, win32api, win32process, ctypes
        hwnd = win32gui.GetForegroundWindow()
        tid = win32api.GetCurrentThreadId()
        ttid, _ = win32process.GetWindowThreadProcessId(hwnd)
        ctypes.windll.user32.AttachThreadInput(tid, ttid, True)
        try:
            win32gui.SetFocus(hwnd)
            time.sleep(0.05)
            # key down (modifiers first, then main keys)
            for vk in vk_codes:
                win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            # key up (reverse order)
            for vk in reversed(vk_codes):
                win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
        finally:
            ctypes.windll.user32.AttachThreadInput(tid, ttid, False)

    def _try_pywinauto_keyboard(self, code: str) -> Optional[Dict[str, Any]]:
        """拦截键盘操作和 win32type，绕过 _is_safe。返回 None 表示不拦截。"""
        # 匹配 win32type('text')
        m = re.match(r"^win32type\(['\"](.+)['\"]\)$", code.strip())
        if m:
            from win32_keyboard import send_text_to_edit
            try:
                send_text_to_edit(m.group(1))
                return {"success": True, "message": f"win32type: {m.group(1)}", "error": None}
            except Exception as e:
                return {"success": False, "message": None, "error": str(e)}

        # 匹配 pyautogui.hotkey('key1', 'key2', ...)
        m = re.match(r"^pyautogui\.hotkey\((.+)\)$", code.strip())
        if m:
            keys = [k.strip().strip("'\"") for k in m.group(1).split(',')]
            return self._exec_pwa_hotkey(keys)

        # 匹配 pyautogui.press('key')
        m = re.match(r"^pyautogui\.press\(['\"](\w+)['\"]\)$", code.strip())
        if m:
            return self._exec_pwa_hotkey([m.group(1)])

        return None

    def _exec_pwa_hotkey(self, keys: list) -> Dict[str, Any]:
        """用 Win32 PostMessage 发送键盘事件"""
        try:
            _win32_hotkey(*keys)
            return {"success": True, "message": f"win32: {keys}", "error": None}
        except Exception as e:
            return {"success": False, "message": None, "error": str(e)}

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

    def _validate_file_path(self, file_path: str) -> bool:
        """验证文件路径安全性"""
        import os.path
        # 必须是绝对路径
        if not os.path.isabs(file_path):
            logger.error(f"File path must be absolute: {file_path}")
            return False
        # 不允许路径穿越
        normalized = os.path.normpath(file_path)
        if '..' in normalized.split(os.sep):
            logger.error(f"Path traversal detected: {file_path}")
            return False
        # 只允许安全字符（字母、数字、中文、路径分隔符、点、下划线、空格、连字符）
        import re as _re
        if not _re.match(r'^[a-zA-Z]:\\[\w\u4e00-\u9fff\s.\-\\]+$', file_path):
            logger.error(f"Invalid characters in file path: {file_path}")
            return False
        # 文件必须存在
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return False
        return True

    def copy_file_to_clipboard(self, file_path: str):
        """用 PowerShell 把图片作为 Bitmap 复制到系统剪贴板（微信可直接粘贴）"""
        # 路径安全验证
        if not self._validate_file_path(file_path):
            logger.error(f"File path validation failed, skipping clipboard copy: {file_path}")
            return

        # 判断是否为图片文件
        img_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')
        is_image = file_path.lower().endswith(img_exts)

        # 使用 PowerShell -File 方式传参，避免命令注入
        ps_script_path = os.path.join(os.path.dirname(__file__), 'copy_file_to_clipboard.ps1')

        try:
            if is_image:
                result = subprocess.run(
                    ['powershell', '-ExecutionPolicy', 'Bypass', '-File', ps_script_path, '-FilePath', file_path, '-AsImage'],
                    capture_output=True, text=True, timeout=10
                )
            else:
                result = subprocess.run(
                    ['powershell', '-ExecutionPolicy', 'Bypass', '-File', ps_script_path, '-FilePath', file_path],
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

        # pywinauto 拦截：纯 hotkey/press 调用走 pywinauto（比 pyautogui 可靠）
        pwa_result = self._try_pywinauto_keyboard(code)
        if pwa_result is not None:
            return pwa_result

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

            # 包装 pyautogui，让 hotkey/press 走 pywinauto
            class _PwaWrappedPyautogui:
                def __getattr__(self, name):
                    return getattr(pyautogui, name)
                def hotkey(self, *keys):
                    self_outer = self  # noqa
                    try:
                        result = _executor_self._exec_pwa_hotkey(list(keys))
                        logger.info(f"hotkey via pywinauto: {keys}")
                    except Exception as e:
                        logger.warning(f"pywinauto hotkey failed ({e}), fallback")
                        pyautogui.hotkey(*keys)
                def press(self, key):
                    try:
                        _executor_self._exec_pwa_hotkey([key])
                    except Exception:
                        pyautogui.press(key)
            _executor_self = self
            _wrapped_pyautogui = _PwaWrappedPyautogui()

            from win32_keyboard import send_text_to_edit as _w32_type
            safe_globals = {
                "pyautogui": _wrapped_pyautogui,
                "pyperclip": pyperclip,
                "__win32_type__": _w32_type,
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
                    # 显式禁止危险函数
                    "__import__": None,
                    "eval": None,
                    "exec": None,
                    "compile": None,
                    "open": None,
                    "getattr": None,
                    "setattr": None,
                    "delattr": None,
                    "globals": None,
                    "locals": None,
                    "vars": None,
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
