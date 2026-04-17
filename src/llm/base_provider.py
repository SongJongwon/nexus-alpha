# -*- coding: utf-8 -*-
"""
LLM Provider 공통 인터페이스.

모든 구체 Provider(AgentSDKProvider, APIKeyProvider 등)는
이 `BaseLLMProvider` 추상 클래스를 상속하여 동일한 호출 규약을 따른다.
에이전트/워크플로우 코드는 구체 구현에 의존하지 않고 이 인터페이스에만
의존하므로, `.env`의 `LLM_PROVIDER` 값을 바꾸는 것만으로 백엔드를 교체할 수 있다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class BaseLLMProvider(ABC):
    """LLM 백엔드의 추상 기본 클래스.

    모든 Provider는 최소한 `generate`와 `name`을 구현해야 한다.
    `stream`은 기본 구현이 `generate` 결과를 단일 청크로 반환하므로
    스트리밍을 실제로 지원하는 Provider에서만 오버라이드하면 된다.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider의 사람이 읽을 수 있는 이름(콘솔 표시·로깅용)."""

    @abstractmethod
    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """단일 프롬프트에 대한 완성 결과(전체 텍스트)를 비동기로 반환한다.

        Args:
            prompt: 사용자 메시지 본문.
            system: 선택적 system prompt. `None`이면 Provider 기본값 사용.

        Returns:
            모델이 생성한 최종 응답 문자열.
        """

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """응답을 청크 단위로 비동기 스트리밍한다.

        기본 구현은 `generate` 결과를 단일 청크로 내보낸다.
        실제 토큰 스트리밍을 지원하는 Provider는 이 메서드를 오버라이드한다.

        Args:
            prompt: 사용자 메시지 본문.
            system: 선택적 system prompt.

        Yields:
            응답 텍스트의 청크(또는 단일 전체 응답).
        """
        text = await self.generate(prompt, system)
        yield text
