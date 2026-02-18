"""SoM 转换器 — OmniParser JSON → 标准化元素清单 + 坐标校正"""
from dataclasses import dataclass
from typing import List, Tuple


def detect_dpi_scale() -> float:
    """Windows DPI 缩放检测"""
    try:
        import ctypes
        scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        return scale / 100.0
    except Exception:
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except Exception:
            return 1.0


@dataclass
class SoMElement:
    id: int
    type: str
    content: str
    bbox: Tuple[float, float, float, float]
    interactable: bool
    center_x: int
    center_y: int


class SoMConverter:
    def __init__(self, screen_w: int, screen_h: int, dpi_scale: float = 1.0):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.dpi_scale = dpi_scale

    def convert(self, omniparser_elements: list, max_elements: int = 40) -> List[SoMElement]:
        elements = []
        for el in omniparser_elements:
            if len(elements) >= max_elements:
                break
            bbox = el.get("bbox", [0, 0, 0, 0])
            cx, cy = self.bbox_to_pixel(bbox)
            elements.append(SoMElement(
                id=len(elements),
                type=self._classify_type(el),
                content=el.get("content", "").strip(),
                bbox=tuple(bbox),
                interactable=el.get("interactivity", False),
                center_x=cx,
                center_y=cy,
            ))
        elements.sort(key=lambda e: (e.center_y // 50, e.center_x))
        # Re-assign IDs after sorting
        for i, el in enumerate(elements):
            el.id = i
        return elements

    def bbox_to_pixel(self, bbox: list) -> Tuple[int, int]:
        raw_x = (bbox[0] + bbox[2]) / 2 * self.screen_w
        raw_y = (bbox[1] + bbox[3]) / 2 * self.screen_h
        return int(raw_x / self.dpi_scale), int(raw_y / self.dpi_scale)

    def format_for_claude(self, elements: List[SoMElement]) -> str:
        lines = []
        for el in elements:
            if not el.interactable and not el.content:
                continue
            tag = "\U0001f518" if el.interactable else "\U0001f4dd"
            pos = self._describe_position(el.center_x, el.center_y)
            content_str = f'"{el.content}"' if el.content else "(无文字)"
            lines.append(f"  [{el.id}] {tag} {el.type} | {content_str} | {pos}")
        return "\n".join(lines)

    def _classify_type(self, el: dict) -> str:
        t = el.get("type", "").lower()
        if "button" in t:
            return "button"
        if "input" in t or ("text" in t and el.get("interactivity")):
            return "text_field"
        if "link" in t:
            return "link"
        if "icon" in t or "image" in t:
            return "icon"
        if el.get("interactivity"):
            return "control"
        return "label"

    def _describe_position(self, x: int, y: int) -> str:
        h = "左" if x < self.screen_w * 0.33 else "中" if x < self.screen_w * 0.66 else "右"
        v = "上" if y < self.screen_h * 0.33 else "中" if y < self.screen_h * 0.66 else "下"
        return f"屏幕{v}{h}"
