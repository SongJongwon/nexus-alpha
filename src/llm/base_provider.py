# -*- coding: utf-8 -*-
"""
LLM Provider 공통 인터페이스.

모든 구체 Provider(AgentSDKProvider, APIKeyProvider 등)는
이 `BaseLLMProvider` 추상 클래스를 상속하여 동일한 호출 규약을 따른다.
에이전트/워크플로우 코드는 구체 구현에 의존하지 않고 이 인터페이스에만
의존하므로, `.env`의 `LLM_PROVIDER` 값을 바꾸는 것만으로 백엔드를 교체할 수 있다.

구현 규약 (Template Method):
    하위 클래스는 `_generate_impl()`을 구현하면 된다.
    공개 API `generate()`가 LangFuse 로깅까지 함께 처리한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional


class BaseLLMProvider(ABC):
    """LLM 백엔드의 추상 기본 클래스.

    모든 Provider는 최소한 `name`과 `_generate_impl`을 구현해야 한다.
    `stream`은 기본 구현이 `generate` 결과를 단일 청크로 반환하므로
    스트리밍을 실제로 지원하는 Provider에서만 오버라이드하면 된다.
    """

    # ------------------------------------------------------------------
    # 하위 클래스가 구현해야 하는 것
    # ------------------------------------------------------------------
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider의 사람이 읽을 수 있는 이름(콘솔 표시·로깅용)."""

    @abstractmethod
    async def _generate_impl(
        self,
        prompt: str,
        system: Optional[str],
    ) -> str:
        """실제 LLM 호출을 수행한다. `generate()`가 이 메서드를 감싸 로깅까지 처리한다.

        Args:
            prompt: 사용자 메시지 본문.
            system: 선택적 system prompt.

        Returns:
            모델이 생성한 최종 응답 문자열.
        """

    # ------------------------------------------------------------------
    # 선택적 훅
    # ------------------------------------------------------------------
    def _model_identifier(self) -> str:
        """LangFuse 로깅에 사용할 모델 식별자. 하위 클래스에서 오버라이드 권장."""
        return "unknown"

    def _extra_log_metadata(self) -> dict[str, Any]:
        """generation 이벤트 metadata에 덧붙일 Provider 고유 정보."""
        return {}

    # ------------------------------------------------------------------
    # 공개 API (로깅 포함)
    # ------------------------------------------------------------------
    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """단일 프롬프트에 대한 완성 결과(전체 텍스트)를 비동기로 반환한다.

        내부적으로 `_generate_impl`을 호출한 뒤 결과를 LangFuse에 자동 기록한다.
        LangFuse 전송이 실패해도(또는 비활성화되어 있어도) 메인 흐름은 영향받지 않는다.
        """
        output: str = ""
        error: Optional[str] = None
        try:
            output = await self._generate_impl(prompt, system)
            return output
        except Exception as exc:
            error = repr(exc)
            raise
        finally:
            # 로깅은 실패해도 메인 경로를 차단하지 않는다.
            try:
                from src.monitoring import get_langfuse_client  # 지연 import (순환 방지)

                monitor = get_langfuse_client()
                metadata: dict[str, Any] = {
                    "provider": self.name,
                    **self._extra_log_metadata(),
                }
                if error is not None:
                    metadata["error"] = error

                monitor.log_generation(
                    name=f"{type(self).__name__}.generate",
                    input={"prompt": prompt, "system": system},
                    output=output,
                    model=self._model_identifier(),
                    metadata=metadata,
                )
            except Exception:  # noqa: BLE001
                pass

            # PR #187 — Sprint 4 telemetry hook. Tauri 데스크탑 앱 대화 panel 용
            # AgentMessageEvent emit. NEXUS_TELEMETRY_PATH 미 set 시 silent no-op.
            try:
                from src.monitoring import (  # 지연 import (순환 방지)
                    AgentMessageEvent,
                    ENGINEERING,
                    get_telemetry_emitter,
                )

                emitter = get_telemetry_emitter()
                if emitter.enabled:
                    emitter.emit(AgentMessageEvent(
                        agent=type(self).__name__,
                        department=ENGINEERING,
                        role="llm_call",
                        prompt_preview=(prompt or "")[:240],
                        output_preview=(output or "")[:240],
                        model=self._model_identifier(),
                        prompt_length=len(prompt or ""),
                        output_length=len(output or ""),
                        error=error,
                    ))
            except Exception:  # noqa: BLE001
                pass

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """응답을 청크 단위로 비동기 스트리밍한다.

        기본 구현은 `generate` 결과를 단일 청크로 내보낸다.
        실제 토큰 스트리밍을 지원하는 Provider는 이 메서드를 오버라이드한다.
        """
        text = await self.generate(prompt, system)
        yield text
