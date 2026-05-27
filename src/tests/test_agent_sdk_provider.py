# -*- coding: utf-8 -*-
"""AgentSDKProvider max_turns 설정 검증 (PR #220).

배경:
    PR #220 이전 default ``max_turns=1`` 은 build_workflow 의 멀티턴 작업
    (CrewAI kickoff_with_converter_rescue) 에서 *"Reached maximum number
    of turns (1)"* 에러를 유발. Phase 1/2 코드와는 무관한 SDK 설정 결함.

검증 범위:
    1. 명시 인자 우선순위 — 호출자가 max_turns 지정 시 그대로 적용
    2. env var override — NEXUS_CLAUDE_MAX_TURNS 가 default 보다 우선
    3. default fallback — env var 부재 시 DEFAULT_MAX_TURNS (=20)
    4. 잘못된 env var 값 (음수 / 비-숫자) → DEFAULT_MAX_TURNS fallback
    5. _build_options 가 max_turns 를 ClaudeAgentOptions 로 전달
    6. _extra_log_metadata 가 max_turns 노출 (LangFuse 로깅)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.agent_sdk_provider import (
    DEFAULT_MAX_TURNS,
    MAX_TURNS_ENV_VAR,
    AgentSDKProvider,
    _resolve_default_max_turns,
)


class TestDefaultMaxTurnsConstant:
    def test_default_is_safe_for_build_chain(self) -> None:
        """⭐ DEFAULT_MAX_TURNS ≥ 10 — build chain 멀티턴 안전마진."""
        assert DEFAULT_MAX_TURNS >= 10, (
            f"DEFAULT_MAX_TURNS={DEFAULT_MAX_TURNS} 는 build chain 에 부족 — "
            "PR #220 의 'Reached maximum number of turns (1)' 회귀 위험"
        )

    def test_env_var_name_constant(self) -> None:
        assert MAX_TURNS_ENV_VAR == "NEXUS_CLAUDE_MAX_TURNS"


class TestResolveDefaultMaxTurns:
    """``_resolve_default_max_turns()`` env var 해석 로직."""

    def test_no_env_returns_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MAX_TURNS_ENV_VAR, None)
            assert _resolve_default_max_turns() == DEFAULT_MAX_TURNS

    def test_env_var_override(self) -> None:
        """NEXUS_CLAUDE_MAX_TURNS=30 → 30 반환."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "30"}):
            assert _resolve_default_max_turns() == 30

    def test_env_var_lower_value(self) -> None:
        """비용 절감 위해 5 로 하향 가능."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "5"}):
            assert _resolve_default_max_turns() == 5

    def test_invalid_env_var_falls_back(self) -> None:
        """비-숫자 → DEFAULT_MAX_TURNS."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "abc"}):
            assert _resolve_default_max_turns() == DEFAULT_MAX_TURNS

    def test_negative_env_var_falls_back(self) -> None:
        """음수 → DEFAULT_MAX_TURNS (방어)."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "-5"}):
            assert _resolve_default_max_turns() == DEFAULT_MAX_TURNS

    def test_zero_env_var_falls_back(self) -> None:
        """0 → DEFAULT_MAX_TURNS (1 미만은 의미 없음)."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "0"}):
            assert _resolve_default_max_turns() == DEFAULT_MAX_TURNS

    def test_empty_env_var_falls_back(self) -> None:
        """빈 문자열 → DEFAULT_MAX_TURNS."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: ""}):
            assert _resolve_default_max_turns() == DEFAULT_MAX_TURNS


class TestAgentSDKProviderInit:
    """``AgentSDKProvider.__init__`` max_turns 우선순위."""

    def test_default_uses_resolved_value(self) -> None:
        """max_turns 미지정 → DEFAULT_MAX_TURNS (env var 없을 때)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MAX_TURNS_ENV_VAR, None)
            provider = AgentSDKProvider()
            assert provider._max_turns == DEFAULT_MAX_TURNS

    def test_explicit_max_turns_overrides_default(self) -> None:
        """명시 max_turns=3 → 3 (env var 무시)."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "50"}):
            provider = AgentSDKProvider(max_turns=3)
            assert provider._max_turns == 3

    def test_explicit_one_still_accepted(self) -> None:
        """단발 테스트 용도로 max_turns=1 명시는 그대로 허용."""
        provider = AgentSDKProvider(max_turns=1)
        assert provider._max_turns == 1

    def test_env_var_used_when_no_explicit_value(self) -> None:
        """명시 None + env var=15 → 15."""
        with patch.dict(os.environ, {MAX_TURNS_ENV_VAR: "15"}):
            provider = AgentSDKProvider()
            assert provider._max_turns == 15


class TestBuildOptionsAndMetadata:
    """``_build_options`` 와 ``_extra_log_metadata`` 가 max_turns 노출."""

    def test_build_options_includes_max_turns(self) -> None:
        provider = AgentSDKProvider(max_turns=25)
        options = provider._build_options(system=None)
        # ClaudeAgentOptions 가 dataclass 면 직접 접근, 아니면 vars
        max_turns = getattr(options, "max_turns", None) or vars(options).get("max_turns")
        assert max_turns == 25

    def test_build_options_with_system_prompt(self) -> None:
        provider = AgentSDKProvider(max_turns=10)
        options = provider._build_options(system="be helpful")
        system_prompt = getattr(options, "system_prompt", None) or vars(options).get("system_prompt")
        assert system_prompt == "be helpful"

    def test_extra_log_metadata_includes_max_turns(self) -> None:
        provider = AgentSDKProvider(max_turns=12)
        meta = provider._extra_log_metadata()
        assert meta["max_turns"] == 12
        assert meta["transport"] == "claude-agent-sdk"


class TestFactoryIntegration:
    """factory 가 ``AgentSDKProvider`` 인스턴스화 시 안전 default 보존.

    Note: conftest 의 autouse monkeypatch 가 ``get_llm_provider`` 를 FakeProvider
    로 치환하므로, 본 test 는 factory 함수 *내부에서* ``AgentSDKProvider()`` 가
    어떻게 생성되는지를 직접 검증 (factory 가 호출하는 동일 생성자).
    """

    def test_default_provider_construction_safe_for_build_chain(self) -> None:
        """LLM_PROVIDER=agent_sdk 경로의 생성자 동작 = AgentSDKProvider() — 회귀 방지."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(MAX_TURNS_ENV_VAR, None)
            # factory 가 호출하는 그대로 — 인자 없이 생성
            provider = AgentSDKProvider()
            # ⭐ 회귀 방지 — 절대로 1 로 떨어지면 안 됨
            assert provider._max_turns >= 10, (
                f"AgentSDKProvider() default max_turns={provider._max_turns} 는 "
                "build chain 멀티턴 작업에 부족 — PR #220 fix 무효화됨"
            )
            assert provider._max_turns == DEFAULT_MAX_TURNS
