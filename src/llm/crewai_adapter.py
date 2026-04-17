# -*- coding: utf-8 -*-
"""
CrewAI ↔ BaseLLMProvider 어댑터.

CrewAI 에이전트가 Nexus Alpha의 Provider 시스템(MAX ↔ API Key 전환,
LangFuse 자동 추적)을 그대로 사용할 수 있도록, `crewai.llms.base_llm.BaseLLM`
을 상속한 경량 래퍼를 제공한다.

사용 예:

    from crewai import Agent
    from src.llm import NexusAlphaLLM

    agent = Agent(
        role="데이터 분석가",
        goal="매출 트렌드를 요약한다",
        backstory="...",
        llm=NexusAlphaLLM(),  # factory.get_llm_provider() 자동 호출
    )

설계 원칙:
    - 어댑터는 **얇고 stateless**에 가깝다. 실제 LLM 호출·로깅은
      `BaseLLMProvider.generate()`가 전담한다.
    - 새 Provider가 추가되어도 어댑터는 전혀 수정할 필요가 없다.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Optional

import anyio
from crewai.llms.base_llm import BaseLLM
from pydantic import PrivateAttr

from .base_provider import BaseLLMProvider
from .factory import get_llm_provider


class NexusAlphaLLM(BaseLLM):
    """CrewAI가 기대하는 BaseLLM 인터페이스를 구현하는 어댑터.

    내부적으로 하나의 `BaseLLMProvider`를 감싸 `call()` / `acall()`을 제공한다.
    Provider 생성은 기본적으로 factory(`get_llm_provider`)가 담당하며,
    필요하면 `provider` 인자로 직접 주입할 수 있다(주로 테스트 용도).

    자동 상속되는 기능(Provider 레이어에서 처리):
        - `.env`의 `LLM_PROVIDER`에 따른 MAX ↔ API Key 전환
        - 호출마다 LangFuse generation 자동 기록

    현재 어댑터가 **지원하지 않는** CrewAI 기능:
        - 툴 콜(tools / available_functions)
        - 구조화 출력(response_model)
        - 콜백(callbacks)
        이들 인자는 받아 두고 무시한다. 이후 Phase에서 점진적으로 채운다.
    """

    _provider: BaseLLMProvider = PrivateAttr()

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
        **kwargs: Any,
    ) -> None:
        # CrewAI BaseLLM은 Pydantic이라 `model` 필드가 필수다.
        # Provider가 실제 모델을 결정하므로 어댑터 레벨에서는 라벨만 둔다.
        if "model" not in kwargs:
            kwargs["model"] = "nexus-alpha-provider"
        super().__init__(**kwargs)
        self._provider = provider if provider is not None else get_llm_provider()

    # ------------------------------------------------------------------
    # 외부 조회용
    # ------------------------------------------------------------------
    # NOTE: CrewAI의 BaseLLM이 이미 `provider: str = "openai"` 필드를 갖고 있어
    #       같은 이름을 쓰면 Pydantic 필드가 우선한다. 충돌을 피하기 위해
    #       별도 이름을 사용한다.
    @property
    def backend_provider(self) -> BaseLLMProvider:
        """현재 어댑터가 위임 중인 Provider 인스턴스."""
        return self._provider

    # ------------------------------------------------------------------
    # 메시지 변환
    # ------------------------------------------------------------------
    @staticmethod
    def _messages_to_prompt(
        messages: Any,
    ) -> tuple[str, Optional[str]]:
        """CrewAI 메시지를 `(prompt, system)` 튜플로 변환한다.

        - 문자열: 전체를 user prompt로 간주하고 system은 None.
        - list[dict]: role == "system" 항목은 system으로 병합,
          그 외는 역할 태그(`[role]`)를 붙여 하나의 prompt로 이어 붙인다.
          OpenAI 스타일의 content block 리스트도 text만 추출해 지원.
        """
        if isinstance(messages, str):
            return messages, None

        system_parts: list[str] = []
        dialogue_parts: list[str] = []

        for m in messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role", "user")).lower()
            content = m.get("content", "")

            if isinstance(content, list):
                text_parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            content_str = str(content)

            if role == "system":
                if content_str.strip():
                    system_parts.append(content_str)
            else:
                dialogue_parts.append(f"[{role}] {content_str}")

        system = "\n\n".join(system_parts) if system_parts else None
        prompt = "\n\n".join(dialogue_parts) if dialogue_parts else ""
        return prompt, system

    # ------------------------------------------------------------------
    # CrewAI 진입점
    # ------------------------------------------------------------------
    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        """CrewAI 기본 오케스트레이션이 사용하는 동기 진입점."""
        prompt, system = self._messages_to_prompt(messages)
        return self._run_async_in_sync(prompt, system)

    async def acall(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        """이미 async 컨텍스트 안에서 호출될 때 사용하는 진입점."""
        prompt, system = self._messages_to_prompt(messages)
        return await self._provider.generate(prompt, system)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _run_async_in_sync(self, prompt: str, system: Optional[str]) -> str:
        """비동기 `provider.generate`를 동기 컨텍스트에서 안전하게 실행한다.

        이미 실행 중인 event loop가 감지되면 별도 스레드에서 새 loop로
        실행해 `RuntimeError: asyncio.run() cannot be called from a running
        event loop` 충돌을 피한다.
        """
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop:
            return anyio.run(self._provider.generate, prompt, system)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                anyio.run, self._provider.generate, prompt, system
            )
            return future.result()
