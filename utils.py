"""
工具函数（精简官方 utils.py）
"""
import re
import ast
import base64
import math
from typing import Tuple
from loguru import logger


def encode_image(image_content: bytes) -> str:
    """将图片内容编码为 base64"""
    return base64.b64encode(image_content).decode("utf-8")


def smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280,
) -> Tuple[int, int]:
    """
    智能调整图片尺寸（用于 qwen25 坐标映射）
    """
    if height < factor or width < factor:
        raise ValueError(f"height:{height} or width:{width} must be larger than factor:{factor}")

    h_bar = max(1, round(height / factor)) * factor
    w_bar = max(1, round(width / factor)) * factor

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(1, math.floor(height / beta / factor)) * factor
        w_bar = max(1, math.floor(width / beta / factor)) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor

    return h_bar, w_bar


def project_coordinate_to_absolute_scale(
    pyautogui_code: str,
    screen_width: int,
    screen_height: int,
    coordinate_type: str = "relative",
    screenshot_scale: float = 1.0
) -> str:
    """
    将 pyautogui 代码中的相对坐标转换为绝对坐标
    """
    def _coordinate_projection(x, y, screen_width, screen_height, coordinate_type, scale=1.0):
        if coordinate_type == "relative":
            return int(round(x * screen_width)), int(round(y * screen_height))
        elif coordinate_type == "qwen25":
            height, width = smart_resize(
                height=screen_height,
                width=screen_width,
                factor=28,
                min_pixels=3136,
                max_pixels=12845056
            )
            if 0 <= x <= 1 and 0 <= y <= 1:
                return int(round(x * width)), int(round(y * height))
            return int(x / width * screen_width), int(y / height * screen_height)
        elif coordinate_type == "absolute":
            # 如果截图被缩放过，需要把坐标乘以 scale 还原到原始屏幕坐标
            return int(round(x * scale)), int(round(y * scale))
        else:
            raise ValueError(f"Invalid coordinate type: {coordinate_type}")

    pattern = r'(pyautogui\.\w+\([^\)]*\))'
    matches = re.findall(pattern, pyautogui_code)
    new_code = pyautogui_code

    for full_call in matches:
        func_name_pattern = r'(pyautogui\.\w+)\((.*)\)'
        func_match = re.match(func_name_pattern, full_call, re.DOTALL)
        if not func_match:
            continue

        func_name = func_match.group(1)
        args_str = func_match.group(2)

        try:
            parsed = ast.parse(f"func({args_str})").body[0].value
            parsed_args = parsed.args
            parsed_keywords = parsed.keywords
        except SyntaxError:
            return pyautogui_code

        function_parameters = {
            'click': ['x', 'y', 'clicks', 'interval', 'button', 'duration', 'pause'],
            'rightClick': ['x', 'y', 'duration', 'tween', 'pause'],
            'middleClick': ['x', 'y', 'duration', 'tween', 'pause'],
            'doubleClick': ['x', 'y', 'interval', 'button', 'duration', 'pause'],
            'tripleClick': ['x', 'y', 'interval', 'button', 'duration', 'pause'],
            'moveTo': ['x', 'y', 'duration', 'tween', 'pause'],
            'dragTo': ['x', 'y', 'duration', 'button', 'mouseDownUp', 'pause'],
        }

        func_base_name = func_name.split('.')[-1]
        param_names = function_parameters.get(func_base_name, [])

        args = {}
        for idx, arg in enumerate(parsed_args):
            if idx < len(param_names):
                param_name = param_names[idx]
                arg_value = ast.literal_eval(arg)
                args[param_name] = arg_value

        try:
            for kw in parsed_keywords:
                param_name = kw.arg
                arg_value = ast.literal_eval(kw.value)
                args[param_name] = arg_value
        except Exception as e:
            logger.error(f"Error parsing keyword arguments: {e}")
            return pyautogui_code

        updated = False
        if 'x' in args and 'y' in args:
            try:
                x_rel = float(args['x'])
                y_rel = float(args['y'])
                x_abs, y_abs = _coordinate_projection(x_rel, y_rel, screen_width, screen_height, coordinate_type, screenshot_scale)
                logger.info(f"Projecting coordinates: ({x_rel}, {y_rel}) -> ({x_abs}, {y_abs})")
                args['x'] = x_abs
                args['y'] = y_abs
                updated = True
            except ValueError:
                pass

        if updated:
            reconstructed_args = []
            for idx, param_name in enumerate(param_names):
                if param_name in args:
                    arg_value = args[param_name]
                    if isinstance(arg_value, str):
                        arg_repr = f"'{arg_value}'"
                    else:
                        arg_repr = str(arg_value)
                    reconstructed_args.append(arg_repr)
                else:
                    break

            used_params = set(param_names[:len(reconstructed_args)])
            for kw in parsed_keywords:
                if kw.arg not in used_params:
                    arg_value = args[kw.arg]
                    if isinstance(arg_value, str):
                        arg_repr = f"{kw.arg}='{arg_value}'"
                    else:
                        arg_repr = f"{kw.arg}={arg_value}"
                    reconstructed_args.append(arg_repr)

            new_args_str = ', '.join(reconstructed_args)
            new_full_call = f"{func_name}({new_args_str})"
            new_code = new_code.replace(full_call, new_full_call)

    return new_code
