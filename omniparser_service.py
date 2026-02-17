"""OmniParser 服务集成 - YOLO+OCR UI元素检测"""
import base64
import httpx
from loguru import logger
from typing import Optional

OMNIPARSER_URL = "http://10.0.0.1:8001"


class OmniParserService:
    def __init__(self, base_url: str = OMNIPARSER_URL, timeout: int = 30):
        self.base_url = base_url
        self.timeout = timeout

    def parse(self, screenshot_bytes: bytes) -> list[dict]:
        """解析截图，返回UI元素列表 [{"type","bbox","content","interactivity"}]"""
        b64 = base64.b64encode(screenshot_bytes).decode()
        try:
            r = httpx.post(
                f"{self.base_url}/parse/",
                json={"base64_image": b64},
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            elements = data.get("parsed_content_list", [])
            latency = data.get("latency", "?")
            logger.info(f"OmniParser: {len(elements)} elements, latency={latency}")
            return elements
        except Exception as e:
            logger.warning(f"OmniParser failed: {e}")
            return []

    def format_for_prompt(self, elements: list[dict], screen_w: int = 1366, screen_h: int = 768) -> str:
        """将元素列表格式化为 agent 可读的文本，只保留交互元素"""
        if not elements:
            return ""
        lines = ["Detected interactive UI elements:"]
        count = 0
        for i, el in enumerate(elements):
            interactive = el.get("interactivity", False)
            if not interactive:
                continue
            bbox = el.get("bbox", [0, 0, 0, 0])
            cx = int((bbox[0] + bbox[2]) / 2 * screen_w)
            cy = int((bbox[1] + bbox[3]) / 2 * screen_h)
            content = el.get("content", "").strip()
            el_type = el.get("type", "unknown")
            label = f'"{content}" ' if content else ""
            lines.append(f"  [{count}] {el_type}: {label}at ({cx},{cy})")
            count += 1
            if count >= 20:
                break
        if count == 0:
            return ""
        return "\n".join(lines)
