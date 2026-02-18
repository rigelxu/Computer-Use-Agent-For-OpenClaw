"""Win32 API 键盘操作 — Hyper-V VM 唯一可靠方案"""
import time
import ctypes
import win32gui
import win32con
import win32api
import win32process
from loguru import logger

# pyautogui key name → VK code
VK_MAP = {
    'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B,
    'enter': 0x0D, 'return': 0x0D, 'tab': 0x09,
    'escape': 0x1B, 'esc': 0x1B,
    'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E,
    'space': 0x20,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    **{f'f{i}': 0x6F + i for i in range(1, 13)},
}


def _resolve_hwnd(hwnd):
    """找到实际应该接收键盘事件的子窗口"""
    if hwnd is None:
        hwnd = win32gui.GetForegroundWindow()
    cls = win32gui.GetClassName(hwnd)
    if cls == 'Progman':
        dv = win32gui.FindWindowEx(hwnd, 0, 'SHELLDLL_DefView', None)
        if dv:
            lv = win32gui.FindWindowEx(dv, 0, 'SysListView32', None)
            if lv:
                # 如果 ListView 下有 Edit（重命名模式），发到 Edit
                edit = win32gui.FindWindowEx(lv, 0, 'Edit', None)
                return edit if edit else lv
    return hwnd


def send_hotkey(*keys, hwnd=None):
    """发送组合键到指定窗口（默认前台窗口，桌面时自动定位 ListView）"""
    hwnd = _resolve_hwnd(hwnd)

    vk_codes = []
    for k in keys:
        vk = VK_MAP.get(k.lower())
        if vk:
            vk_codes.append(vk)
        elif len(k) == 1:
            vk_codes.append(ord(k.upper()))
        else:
            logger.warning(f"Unknown key: {k}")
            return False

    tid = win32api.GetCurrentThreadId()
    ttid, _ = win32process.GetWindowThreadProcessId(hwnd)
    ctypes.windll.user32.AttachThreadInput(tid, ttid, True)
    try:
        try:
            win32gui.SetFocus(hwnd)
        except Exception:
            pass  # SetFocus 可能失败，继续发消息
        time.sleep(0.05)
        for vk in vk_codes:
            win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
        time.sleep(0.05)
        for vk in reversed(vk_codes):
            win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
    finally:
        ctypes.windll.user32.AttachThreadInput(tid, ttid, False)

    logger.info(f"win32 hotkey: {keys} -> {[hex(v) for v in vk_codes]}")
    return True


def send_text_to_edit(text, hwnd=None):
    """直接用 WM_SETTEXT 写入前台 Edit 控件（比 Ctrl+V 可靠）"""
    if hwnd is None:
        hwnd = _resolve_hwnd(None)
    cls = win32gui.GetClassName(hwnd)
    if cls != 'Edit':
        # 尝试找子 Edit
        edit = win32gui.FindWindowEx(hwnd, 0, 'Edit', None)
        if edit:
            hwnd = edit
    win32gui.SendMessage(hwnd, win32con.WM_SETTEXT, 0, text)
    logger.info(f"win32 WM_SETTEXT: '{text}' -> hwnd={hwnd}")
    return True


def get_desktop_listview():
    """获取桌面 SysListView32 句柄"""
    progman = win32gui.FindWindow('Progman', 'Program Manager')
    defview = win32gui.FindWindowEx(progman, 0, 'SHELLDLL_DefView', None)
    if not defview:
        return None, None
    lv = win32gui.FindWindowEx(defview, 0, 'SysListView32', None)
    return progman, lv
