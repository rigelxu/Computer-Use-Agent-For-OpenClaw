"""
截图模块（使用 mss）
"""
import mss
from io import BytesIO
from PIL import Image
from loguru import logger


def capture_screenshot() -> bytes:
    """
    使用 mss 捕获主显示器截图，返回 PNG 格式的字节数据
    """
    try:
        with mss.mss() as sct:
            # 捕获主显示器（monitor 1）
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)

            # 转换为 PIL Image
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

            # 转换为 PNG 字节
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            return buffer.getvalue()
    except Exception as e:
        logger.error(f"Failed to capture screenshot: {e}")
        raise


def get_screen_size() -> tuple:
    """
    获取主显示器的分辨率
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            return monitor['width'], monitor['height']
    except Exception as e:
        logger.error(f"Failed to get screen size: {e}")
        raise
