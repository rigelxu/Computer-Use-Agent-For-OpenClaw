"""上下文管理器 - 整合窗口管理+截图+OmniParser+SoM"""
import time
import base64
from loguru import logger
from window_manager import WindowManager
from screenshot import capture_screenshot
from omniparser_service import OmniParserService
from som_converter import SoMConverter, detect_dpi_scale
import config


class ContextManager:
    def __init__(self, use_omniparser: bool = False):
        self.wm = WindowManager()
        self.omniparser = OmniParserService() if use_omniparser else None
        self.som_converter = SoMConverter(
            screen_w=config.SCREEN_WIDTH,
            screen_h=config.SCREEN_HEIGHT,
            dpi_scale=config.DPI_SCALE if config.DPI_SCALE > 0 else detect_dpi_scale(),
        ) if use_omniparser else None

    def get_context(self) -> dict:
        start = time.time()

        # 截图
        screenshot_bytes, screenshot_scale = capture_screenshot(max_width=config.SCREENSHOT_MAX_WIDTH)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

        # 窗口信息
        active_window = self.wm.get_active_window()
        active_app = self.wm.detect_app()

        # OmniParser UI元素检测
        omniparser_elements = []
        omniparser_text = ""
        if self.omniparser:
            omniparser_elements = self.omniparser.parse(screenshot_bytes)
            omniparser_text = self.omniparser.format_for_prompt(omniparser_elements)

        # SoM 转换
        som_elements = []
        som_text = ""
        if self.som_converter and omniparser_elements:
            som_elements = self.som_converter.convert(omniparser_elements, max_elements=config.SOM_MAX_ELEMENTS)
            som_text = self.som_converter.format_for_claude(som_elements)

        ctx = {
            "screenshot_bytes": screenshot_bytes,
            "screenshot_base64": screenshot_b64,
            "active_window": active_window,
            "active_app": active_app,
            "window_list": self.wm.list_windows(),
            "omniparser_elements": omniparser_elements,
            "omniparser_text": omniparser_text,
            "screenshot_scale": screenshot_scale,
            "som_elements": som_elements,
            "som_text": som_text,
        }

        elapsed = (time.time() - start) * 1000
        logger.info(f"Context collected in {elapsed:.0f}ms | app={active_app} | elements={len(omniparser_elements)}")
        return ctx
