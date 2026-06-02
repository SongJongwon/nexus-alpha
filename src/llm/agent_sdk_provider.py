# -*- coding: utf-8 -*-
"""
Claude Code MAX 구독을 경유해 Claude를 호출하는 Provider.

`claude-agent-sdk`의 `query()`를 사용한다. 이 SDK는 내부적으로 `claude`
CLI를 서브프로세스로 띄워 사용자의 Claude Code 로그인(MAX 구독)을
그대로 재사용하므로 별도 `ANTHROPIC_API_KEY`가 필요 없다.
"""

from __future__ import annotations

import os
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .base_provider import BaseLLMProvider


DEFAULT_MAX_TURNS: int = 20
"""build chain / CrewAI 멀티턴 작업에 필요한 안전 기본값.

PR #220 (2026-05-27) — 이전 default=1 은 build_workflow 의 kickoff_with_converter_rescue
호출에서 ``"Reached maximum number of turns (1)"`` 에러를 유발했다. Claude Code
공식 권장 10~20 범위 + build chain 같은 복잡 작업 보수적 안전마진으로 20 채택.
"""

MAX_TURNS_ENV_VAR: str = "NEXUS_CLAUDE_MAX_TURNS"
"""환경변수 — 운영 중에도 max_turns 조절 가능 (e.g. 비용 절감 위해 10으로 하향)."""


def _resolve_default_max_turns() -> int:
    """``NEXUS_CLAUDE_MAX_TURNS`` env var 우선, 없으면 ``DEFAULT_MAX_TURNS``."""
    raw = (os.environ.get(MAX_TURNS_ENV_VAR) or "").strip()
    if not raw:
        return DEFAULT_MAX_TURNS
    try:
        parsed = int(raw)
        if parsed < 1:
            return DEFAULT_MAX_TURNS
        return parsed
    except ValueError:
        return DEFAULT_MAX_TURNS


class AgentSDKProvider(BaseLLMProvider):
    """Claude Code CLI(`claude`)를 경유해 Claude를 호출하는 Provider.

    전제: `claude` 실행 파일이 PATH에서 발견되어야 하며, 해당 CLI가
    MAX 구독으로 이미 로그인되어 있어야 한다.

    Args:
        model: Claude 모델 ID. `None`이면 Claude Code 기본값을 따른다.
        max_turns: 에이전트 최대 턴 수. 명시 None 이면 ``NEXUS_CLAUDE_MAX_TURNS``
            env var 우선, 없으면 ``DEFAULT_MAX_TURNS`` (=20). build chain 등
            멀티턴 작업 대비 안전 기본값. 단발 테스트는 ``max_turns=1`` 명시.
        permission_mode: 도구 실행 권한 모드. 기본 `"bypassPermissions"`는
            프롬프트 없이 모든 도구를 허용한다(비대화식 환경 안전).
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        permission_mode: str = "bypassPermissions",
    ) -> None:
        self._model = model
        self._max_turns = max_turns if max_turns is not None else _resolve_default_max_turns()
        self._permission_mode = permission_mode

    @property
    def name(self) -> str:
        model_suffix = f", model={self._model}" if self._model else ""
        return f"AgentSDKProvider (Claude Code MAX{model_suffix})"

    def _model_identifier(self) -> str:
        """LangFuse 로깅용 모델 식별자."""
        return self._model or "claude-code-default"

    def _extra_log_metadata(self) -> dict:
        return {
            "transport": "claude-agent-sdk",
            "max_turns": self._max_turns,
            "permission_mode": self._permission_mode,
        }

    def _build_options(self, system: Optional[str]) -> ClaudeAgentOptions:
        """이번 호출에 사용할 ClaudeAgentOptions 를 구성한다."""
        kwargs: dict = {
            "max_turns": self._max_turns,
            "permission_mode": self._permission_mode,
        }
        if system:
            kwargs["system_prompt"] = system
        if self._model:
            kwargs["model"] = self._model
        return ClaudeAgentOptions(**kwargs)

    async def _generate_impl(self, prompt: str, system: Optional[str] = None) -> str:
        """단발성 응답 전체를 문자열로 반환한다.

        AssistantMessage의 TextBlock들을 이어 붙이고, 아무 텍스트도
        수집되지 않은 경우 ResultMessage.result로 폴백한다.
        """
        options = self._build_options(system)
        parts: list[str] = []
        fallback: Optional[str] = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(message, ResultMessage) and message.result:
                fallback = message.result

        if parts:
            return "".join(parts)
        return fallback or ""

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """AssistantMessage의 TextBlock을 도착 순서대로 yield 한다."""
        options = self._build_options(system)
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text

    # ------------------------------------------------------------------
    # 멀티모달(vision) — v13 P17: vision QA 를 claude-code-default 로 일원화
    # ------------------------------------------------------------------
    def supports_vision(self) -> bool:
        """claude CLI(MAX 구독) 경유 멀티모달 지원.

        claude-agent-sdk 의 streaming-input(AsyncIterable[dict]) 경로로 image
        content block 을 전달한다. 실제 멀티모달 전달은 CLI/모델 버전에 의존하므로,
        호출 측은 응답 파싱 실패 시 ANTHROPIC_API_KEY 경로 폴백 또는 graceful SKIP 한다.
        """
        return True

    async def generate_vision(
        self,
        prompt: str,
        images: list[tuple[str, str]],
        system: Optional[str] = None,
        *,
        model: Optional[str] = None,
        max_tokens: int = 512,
    ) -> str:
        """이미지 + 텍스트를 claude-agent-sdk streaming-input 으로 전달 (P17).

        ``query(prompt=AsyncIterable[dict])`` 경로로 ``{"type":"user","message":
        {"role":"user","content":[image_block..., text_block]}}`` 메시지를 흘려보낸다.
        멀티모달 가능 모델이 필요하므로 ``model`` 인자(또는 인스턴스 model)를 지정한다.
        응답은 AssistantMessage 의 TextBlock 을 이어붙여 반환한다.
        """
        # 멀티모달은 단발 1턴이면 충분 — max_turns=1 로 고정해 비용/지연 최소화.
        # NOTE: ClaudeAgentOptions 는 max_tokens 필드를 지원하지 않는다(현행 claude-agent-sdk
        # 전 버전 공통 — 전달 시 TypeError). vision verdict 는 단발 짧은 JSON 이라 출력 상한이
        # 사실상 무의미하므로 전달하지 않는다. max_tokens 인자는 BaseLLMProvider 계약 유지를 위해
        # 시그니처엔 남기되, 실제 토큰 상한은 raw SDK(ANTHROPIC_API_KEY) 폴백 경로에서만 적용된다.
        opt_kwargs: dict = {"max_turns": 1, "permission_mode": self._permission_mode}
        if system:
            opt_kwargs["system_prompt"] = system
        chosen_model = model or self._model
        if chosen_model:
            opt_kwargs["model"] = chosen_model
        options = ClaudeAgentOptions(**opt_kwargs)

        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            }
            for data, media_type in images
        ]
        content.append({"type": "text", "text": prompt})
        message = {
            "type": "user",
            "message": {"role": "user", "content": content},
        }

        async def _stream_input() -> AsyncIterator[dict]:
            yield message

        parts: list[str] = []
        fallback: Optional[str] = None
        async for msg in query(prompt=_stream_input(), options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage) and msg.result:
                fallback = msg.result
        if parts:
            return "".join(parts)
        return fallback or ""
