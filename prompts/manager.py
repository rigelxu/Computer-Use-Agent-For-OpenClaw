"""Prompt管理器 - 根据应用名返回对应Prompt"""
from prompts import PromptTemplate
from prompts.wechat import WECHAT_PROMPT
from prompts.browser import BROWSER_PROMPT
from prompts.file_explorer import FILE_EXPLORER_PROMPT

GENERIC_PROMPT = PromptTemplate(
    system_prompt="You are controlling a Windows 11 desktop application. Observe the screen carefully and perform the requested task step by step. After completing, call terminate with status='success'.",
    app_hints="",
)

_PROMPT_MAP = {
    "wechat": WECHAT_PROMPT,
    "chrome": BROWSER_PROMPT,
    "edge": BROWSER_PROMPT,
    "file_explorer": FILE_EXPLORER_PROMPT,
}


class PromptManager:
    def get_prompt(self, app_name: str) -> PromptTemplate:
        return _PROMPT_MAP.get(app_name, GENERIC_PROMPT)
