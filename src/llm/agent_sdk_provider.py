# -*- coding: utf-8 -*-
"""
Claude Code MAX 구독을 경유해 Claude를 호출하는 Provider.

`claude-agent-sdk`의 `query()`를 사용한다. 이 SDK는 내부적으로 `claude`
CLI를 서브프로세스로 띄워 사용자의 Claude Code 로그인(MAX 구독)을
그대로 재사용하므로 별도 `ANTHROPIC_API_KEY`가 필요 없다.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .base_provider import BaseLLMProvider


class AgentSDKProvider(BaseLLMProvider):
    """Claude Code CLI(`claude`)를 경유해 Claude를 호출하는 Provider.

    전제: `claude` 실행 파일이 PATH에서 발견되어야 하며, 해당 CLI가
    MAX 구독으로 이미 로그인되어 있어야 한다.

    Args:
        model: Claude 모델 ID. `None`이면 Claude Code 기본값을 따른다.
        max_turns: 에이전트 최대 턴 수. 단발성 응답이면 1로 충분하다.
        permission_mode: 도구 실행 권한 모드. 기본 `"bypassPermissions"`는
            프롬프트 없이 모든 도구를 허용한다(비대화식 환경 안전).
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_turns: int = 1,
        permission_mode: str = "bypassPermissions",
    ) -> None:
        self._model = model
        self._max_turns = max_turns
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
