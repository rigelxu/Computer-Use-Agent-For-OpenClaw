"""Prompt模板基类"""
from dataclasses import dataclass, field


@dataclass
class PromptTemplate:
    system_prompt: str = ""
    app_hints: str = ""  # 注入到observation的应用提示
    few_shot_examples: list = field(default_factory=list)
