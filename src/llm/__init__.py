# -*- coding: utf-8 -*-
"""
Nexus Alpha LLM Provider 패키지.

외부 모듈은 보통 아래 두 가지만 쓴다.

    from src.llm import get_llm_provider, BaseLLMProvider

    provider = get_llm_provider()
    text = await provider.generate("안녕")
"""

from .base_provider import BaseLLMProvider
from .factory import get_llm_provider

__all__ = [
    "BaseLLMProvider",
    "get_llm_provider",
]
