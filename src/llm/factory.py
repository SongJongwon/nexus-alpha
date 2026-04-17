# -*- coding: utf-8 -*-
"""
LLM Provider 팩토리.

환경변수 `LLM_PROVIDER` 값에 따라 적절한 Provider 구현을 반환한다.
애플리케이션 코드는 이 팩토리를 통해서만 Provider를 얻도록 권장된다.
"""

from __future__ import annotations

import os

from .base_provider import BaseLLMProvider

_SUPPORTED = {"agent_sdk", "api_key"}


def get_llm_provider() -> BaseLLMProvider:
    """`.env`의 `LLM_PROVIDER` 값을 읽어 해당 Provider 인스턴스를 반환한다.

    환경변수 값:
        - `agent_sdk`(기본): `AgentSDKProvider` (Claude Code MAX 구독 사용, 무료)
        - `api_key`        : `APIKeyProvider` (Anthropic API Key 사용, 과금)

    Raises:
        ValueError: 지원하지 않는 값이 설정되었을 때.
        RuntimeError: 선택한 Provider 초기화에 실패했을 때(예: API Key 누락).
    """
    raw = os.getenv("LLM_PROVIDER", "agent_sdk").strip().lower()
    if raw not in _SUPPORTED:
        raise ValueError(
            f"지원하지 않는 LLM_PROVIDER 값: '{raw}'. "
            f"허용값: {sorted(_SUPPORTED)}"
        )

    if raw == "agent_sdk":
        # 지연 import — claude-agent-sdk 미설치 환경에서도 api_key 경로는 동작하도록.
        from .agent_sdk_provider import AgentSDKProvider

        return AgentSDKProvider()

    from .api_key_provider import APIKeyProvider

    return APIKeyProvider()
