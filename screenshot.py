"""
截图模块（使用 mss）
"""
import mss
from io import BytesIO
from PIL import Image
from loguru import logger


def capture_screenshot(max_width: int = 1280) -> bytes:
    """
    使用 mss 捕获主显示器截图，返回 PNG 格式的字节数据。
    如果截图宽度超过 max_width，会等比缩放以减少 token 消耗。
    """
    try:
        with mss.mss() as sct:
            # 捕获主显示器（monitor 1）
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)

            # 转换为 PIL Image
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

            # 等比缩放（减少发给模型的 token 数）
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                logger.info(f"Screenshot resized: {screenshot.size} -> {new_size}")

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
