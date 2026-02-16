"""
OpenCUA Agent（基于官方改造）
"""
import re
import time
import httpx
import traceback
from typing import Dict, List, Tuple
from loguru import logger

from utils import encode_image, project_coordinate_to_absolute_scale
from prompts import (
    build_sys_prompt,
    INSTRUTION_TEMPLATE,
    STEP_TEMPLATE,
    ACTION_HISTORY_TEMPLATE,
    THOUGHT_HISTORY_TEMPLATE,
    OBSERVATION_HISTORY_TEMPLATE,
)
import config


def parse_response_to_cot_and_action(
    input_string: str,
    screen_size: Tuple[int, int],
    coordinate_type: str,
    screenshot_scale: float = 1.0
) -> Tuple[str, List[str], dict]:
    """
    解析模型响应，提取 Observation/Thought/Action/Code
    """
    sections = {}
    try:
        # 提取 Observation
        obs_match = re.search(
            r'^##\s*Observation\s*:?[\n\r]+(.*?)(?=^##\s*Thought:|^##\s*Action:|^##|\Z)',
            input_string,
            re.DOTALL | re.MULTILINE
        )
        if obs_match:
            sections['observation'] = obs_match.group(1).strip()

        # 提取 Thought
        thought_match = re.search(
            r'^##\s*Thought\s*:?[\n\r]+(.*?)(?=^##\s*Action:|^##|\Z)',
            input_string,
            re.DOTALL | re.MULTILINE
        )
        if thought_match:
            sections['thought'] = thought_match.group(1).strip()

        # 提取 Action
        action_match = re.search(
            r'^##\s*Action\s*:?[\n\r]+(.*?)(?=^##|\Z)',
            input_string,
            re.DOTALL | re.MULTILINE
        )
        if action_match:
            sections['action'] = action_match.group(1).strip()

        # 提取 Code
        code_blocks = re.findall(
            r'```(?:code|python)?\s*(.*?)\s*```',
            input_string,
            re.DOTALL | re.IGNORECASE
        )
        if not code_blocks:
            logger.error("No code blocks found")
            return f"<Error>: no code blocks found: {input_string}", ["FAIL"], sections

        code_block = code_blocks[-1].strip()
        sections['original_code'] = code_block

        # 处理特殊命令
        if "computer.wait" in code_block.lower():
            sections["code"] = "WAIT"
            return sections.get('action', 'Wait'), ["WAIT"], sections

        elif "computer.terminate" in code_block.lower():
            lower_block = code_block.lower()
            if ("failure" in lower_block) or ("fail" in lower_block):
                sections['code'] = "FAIL"
                return code_block, ["FAIL"], sections
            elif "success" in lower_block:
                sections['code'] = "DONE"
                return code_block, ["DONE"], sections
            else:
                logger.error("Terminate without status")
                return f"<Error>: terminate without status: {input_string}", ["FAIL"], sections

        # 坐标映射
        corrected_code = code_block
        sections['code'] = project_coordinate_to_absolute_scale(
            corrected_code,
            screen_width=screen_size[0],
            screen_height=screen_size[1],
            coordinate_type=coordinate_type,
            screenshot_scale=screenshot_scale
        )

        if not sections.get('code') or not sections.get('action'):
            logger.error("Missing action or code")
            return f"<Error>: missing action or code: {input_string}", ["FAIL"], sections

        return sections['action'], [sections['code']], sections

    except Exception as e:
        error_message = f"<Error>: parsing response: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_message)
        return error_message, ['FAIL'], sections


class OpenCUAAgent:
    """
    OpenCUA Agent for desktop automation
    """

    def __init__(
        self,
        model: str,
        history_type: str,
        max_steps: int,
        max_image_history_length: int = 3,
        platform: str = "windows",
        max_tokens: int = 1500,
        top_p: float = 0.9,
        temperature: float = 0.0,
        cot_level: str = "l2",
        screen_size: Tuple[int, int] = (1920, 1080),
        coordinate_type: str = "relative",
        password: str = "password",
        **kwargs
    ):
        assert coordinate_type in ["relative", "absolute", "qwen25"]
        assert history_type in ["action_history", "thought_history", "observation_history"]

        self.model = model
        self.platform = platform
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.history_type = history_type
        self.coordinate_type = coordinate_type
        self.cot_level = cot_level
        self.screen_size = screen_size
        self.max_image_history_length = max_image_history_length
        self.max_steps = max_steps
        self.password = password

        # 选择历史模板
        if history_type == "action_history":
            self.HISTORY_TEMPLATE = ACTION_HISTORY_TEMPLATE
        elif history_type == "thought_history":
            self.HISTORY_TEMPLATE = THOUGHT_HISTORY_TEMPLATE
        elif history_type == "observation_history":
            self.HISTORY_TEMPLATE = OBSERVATION_HISTORY_TEMPLATE
        else:
            raise ValueError(f"Invalid history type: {history_type}")

        # 构建 system prompt
        self.system_prompt = build_sys_prompt(
            level=self.cot_level,
            password=self.password,
            use_random=False
        )

        self.actions = []
        self.observations = []
        self.cots = []

    def reset(self):
        """重置 agent 状态"""
        self.observations = []
        self.cots = []
        self.actions = []

    def predict(self, instruction: str, obs: Dict, **kwargs) -> Tuple[str, List[str], Dict]:
        """
        预测下一步动作

        Args:
            instruction: 任务指令
            obs: 观察（包含 screenshot 字段）
            **kwargs: 其他参数（如 step_idx）

        Returns:
            (response, pyautogui_actions, other_cot)
        """
        step_idx = kwargs.get('step_idx', len(self.actions) + 1)
        logger.info(f"========= Step {step_idx} =======")
        logger.info(f"Instruction: {instruction}")

        # 构建消息
        messages = []
        messages.append({
            "role": "system",
            "content": self.system_prompt
        })

        instruction_prompt = INSTRUTION_TEMPLATE.format(instruction=instruction)

        # 添加历史
        history_step_texts = []
        for i in range(len(self.actions)):
            if i > len(self.actions) - self.max_image_history_length:
                # 最近的步骤，包含图片
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encode_image(self.observations[i]['screenshot'])}"
                            }
                        }
                    ]
                })

                history_content = STEP_TEMPLATE.format(step_num=i + 1) + self.HISTORY_TEMPLATE.format(
                    observation=self.cots[i].get('observation'),
                    thought=self.cots[i].get('thought'),
                    action=self.cots[i].get('action')
                )

                messages.append({
                    "role": "assistant",
                    "content": history_content
                })
            else:
                # 较早的步骤，只保留文本
                history_content = STEP_TEMPLATE.format(step_num=i + 1) + self.HISTORY_TEMPLATE.format(
                    observation=self.cots[i].get('observation'),
                    thought=self.cots[i].get('thought'),
                    action=self.cots[i].get('action')
                )
                history_step_texts.append(history_content)
                if i == len(self.actions) - self.max_image_history_length:
                    messages.append({
                        "role": "assistant",
                        "content": "\n".join(history_step_texts)
                    })

        # 添加当前观察
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encode_image(obs['screenshot'])}"
                    }
                },
                {
                    "type": "text",
                    "text": instruction_prompt
                }
            ]
        })

        # 调用 LLM
        max_retry = 5
        retry_count = 0
        low_level_instruction = None
        pyautogui_actions = None
        other_cot = {}

        while retry_count < max_retry:
            try:
                response = self.call_llm({
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "top_p": self.top_p,
                    "temperature": self.temperature if retry_count == 0 else max(0.2, self.temperature)
                })

                logger.info(f"Model Output:\n{response}")
                if not response:
                    raise ValueError("Empty response from LLM")

                low_level_instruction, pyautogui_actions, other_cot = parse_response_to_cot_and_action(
                    response,
                    self.screen_size,
                    self.coordinate_type,
                    screenshot_scale=obs.get("screenshot_scale", 1.0)
                )

                if "<Error>" in low_level_instruction or not pyautogui_actions:
                    raise ValueError(f"Error parsing response: {low_level_instruction}")

                break

            except Exception as e:
                logger.error(f"Error during prediction: {e}")
                retry_count += 1
                if retry_count == max_retry:
                    logger.error("Maximum retries reached")
                    return str(e), ['FAIL'], other_cot

        logger.info(f"Action: {low_level_instruction}")
        logger.info(f"Code: {pyautogui_actions}")

        # 保存历史
        self.observations.append(obs)
        self.actions.append(low_level_instruction)
        self.cots.append(other_cot)

        # 检查是否达到最大步数
        current_step = len(self.actions)
        if current_step >= self.max_steps and 'computer.terminate' not in str(pyautogui_actions).lower():
            logger.warning(f"Reached maximum steps {self.max_steps}")
            low_level_instruction = 'Fail: reached maximum step limit'
            pyautogui_actions = ['FAIL']
            other_cot['code'] = 'FAIL'

        return response, pyautogui_actions, other_cot

    def call_llm(self, payload: dict) -> str:
        """
        调用 vLLM API（OpenAI 兼容）
        """
        url = f"{config.VLLM_BASE_URL}/v1/chat/completions"

        for attempt in range(20):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=500
                )

                if response.status_code != 200:
                    logger.error(f"LLM API error: {response.text}")
                    time.sleep(5)
                    continue

                response_data = response.json()
                finish_reason = response_data["choices"][0].get("finish_reason")

                if finish_reason == "stop":
                    return response_data['choices'][0]['message']['content']
                else:
                    logger.warning(f"LLM did not finish properly: {finish_reason}")
                    time.sleep(5)

            except Exception as e:
                logger.error(f"LLM API call failed: {e}")
                time.sleep(5)

        raise RuntimeError("Failed to call LLM API after 20 retries")
