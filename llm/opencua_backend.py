"""OpenCUA 后端 — 包装现有 OpenCUAAgent，输出统一 AgentAction"""
from loguru import logger

import config
from agent import OpenCUAAgent


class OpenCUABackend:
    def __init__(self):
        from screenshot import get_screen_size
        sw, sh = get_screen_size()
        model = config.LLM_MODEL if config.LLM_PROVIDER == "anthropic" else config.VLLM_MODEL_NAME
        self.agent = OpenCUAAgent(
            model=model,
            history_type="thought_history",
            max_steps=config.MAX_STEPS,
            max_image_history_length=config.MAX_IMAGE_HISTORY_LENGTH,
            platform=config.PLATFORM,
            max_tokens=config.MAX_TOKENS,
            top_p=config.TOP_P,
            temperature=config.TEMPERATURE,
            cot_level=config.COT_LEVEL,
            screen_size=(sw, sh),
            coordinate_type=config.COORDINATE_TYPE,
            password="password",
        )

    def reset(self):
        self.agent.reset()

    def predict(self, instruction: str, context: dict,
                history: list, step_idx: int):
        from llm.router import AgentAction, ActionType

        obs = {
            "screenshot": context["screenshot_bytes"],
            "screenshot_scale": context.get("screenshot_scale", 1.0),
        }
        response, actions, cot = self.agent.predict(
            instruction=instruction, obs=obs, step_idx=step_idx,
            recovery_hint=context.get("recovery_hint", ""),
        )
        return self._convert(actions, cot, response)

    def _convert(self, actions, cot, response):
        from llm.router import AgentAction, ActionType

        code = actions[0] if actions else "FAIL"
        if code == "DONE":
            return AgentAction(action_type=ActionType.DONE, raw_response=response)
        if code == "FAIL":
            return AgentAction(action_type=ActionType.FAIL, raw_response=response)
        if code == "WAIT":
            return AgentAction(action_type=ActionType.WAIT, raw_response=response)
        return AgentAction(
            action_type=ActionType.CLICK,
            raw_code=code,
            thought=cot.get("thought"),
            raw_response=response,
        )
