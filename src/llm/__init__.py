# -*- coding: utf-8 -*-
"""
Nexus Alpha LLM Provider 패키지.

외부 모듈은 보통 아래를 쓴다.

    # Provider 직접 호출
    from src.llm import get_llm_provider, BaseLLMProvider

    provider = get_llm_provider()
    text = await provider.generate("안녕")

    # CrewAI Agent와 연결
    from crewai import Agent
    from src.llm import NexusAlphaLLM

    agent = Agent(role="...", goal="...", backstory="...", llm=NexusAlphaLLM())
"""

from .base_provider import BaseLLMProvider
from .crewai_adapter import NexusAlphaLLM
from .factory import get_llm_provider

__all__ = [
    "BaseLLMProvider",
    "NexusAlphaLLM",
    "get_llm_provider",
]
