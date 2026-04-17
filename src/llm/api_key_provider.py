# -*- coding: utf-8 -*-
"""
API Key 기반 Claude Provider.

`.env`의 `ANTHROPIC_API_KEY`를 이용해 Anthropic Messages API를 직접 호출한다.
별도 과금이 발생하므로 MAX 구독 사용이 어려운 환경(CI, 서버 배포 등)에서만 권장.
LangChain의 `ChatAnthropic`을 통해 Anthropic SDK를 호출한다.
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .base_provider import BaseLLMProvider


class APIKeyProvider(BaseLLMProvider):
    """Anthropic API Key를 사용해 Claude를 호출하는 Provider.

    Args:
        model: 사용할 Claude 모델 ID. 기본값은 Sonnet 4.6.
        temperature: 샘플링 온도(0.0~1.0).
        max_tokens: 응답 최대 토큰 수.

    Raises:
        RuntimeError: 환경변수 `ANTHROPIC_API_KEY`가 비어 있을 때.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "APIKeyProvider 초기화 실패: 환경변수 ANTHROPIC_API_KEY가 비어 있습니다. "
                "`.env` 파일에 `ANTHROPIC_API_KEY=sk-ant-...`를 설정하거나 "
                "`LLM_PROVIDER=agent_sdk`로 MAX 구독 모드를 사용하세요."
            )

        self._model = model
        self._client = ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
        )

    @property
    def name(self) -> str:
        return f"APIKeyProvider (model={self._model})"

    def _model_identifier(self) -> str:
        """LangFuse 로깅용 모델 식별자."""
        return self._model

    def _extra_log_metadata(self) -> dict:
        return {"transport": "langchain-anthropic"}

    async def _generate_impl(self, prompt: str, system: Optional[str] = None) -> str:
        """Anthropic API를 비동기 호출해 단일 응답을 반환한다."""
        messages: list = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        result = await self._client.ainvoke(messages)
        # LangChain AIMessage.content는 보통 str이지만, 구조화 블록 리스트일 수도 있다.
        content = result.content
        if isinstance(content, str):
            return content
        # 블록 리스트 → text 블록만 추출해 이어붙임
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
