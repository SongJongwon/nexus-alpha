# -*- coding: utf-8 -*-
"""Cross-Agent Consultant 단위 test (v13 Phase 5.4, PR #224).

검증 범위:
    1. route_message — sender → recipients 순차 라우팅 + AgentResponse 산출
    2. conduct_round — 1 라운드 진행 + dissent 감지 + max 3 하드 캡
    3. collect_dissent — 발언 list → dissent agent 이름
    4. default_round_speakers — 라운드별 default 발언 순서
    5. _detect_dissent — 결정론 키워드 감지
    6. create_delegation_enabled_pair — 양방향 위임 helper
    7. _build_speaker_prompt — context 누적 prompt 구조
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.coordination import (
    AgentResponse,
    Round,
    RoundResult,
    Speaker,
    Statement,
    collect_dissent,
    conduct_round,
    default_round_speakers,
    route_message,
)
from src.agents.coordination.cross_agent_consultant import (
    _build_speaker_prompt,
    _detect_dissent,
    _extract_speaker_content,
)


# =============================================================================
# 1. _detect_dissent — 결정론 키워드
# =============================================================================
class TestDetectDissent:
    def test_korean_dissent_keywords(self) -> None:
        assert _detect_dissent("그 의견에 반박합니다") is True
        assert _detect_dissent("동의하지 않습니다") is True
        assert _detect_dissent("재검토가 필요합니다") is True

    def test_english_dissent_keywords(self) -> None:
        assert _detect_dissent("I disagree with this") is True
        assert _detect_dissent("Object to the proposal") is True
        assert _detect_dissent("This needs to be reconsidered") is True

    def test_no_dissent_in_agreement(self) -> None:
        assert _detect_dissent("동의합니다") is False
        assert _detect_dissent("좋은 안건입니다") is False
        assert _detect_dissent("I agree completely") is False

    def test_case_insensitive(self) -> None:
        assert _detect_dissent("DISAGREE STRONGLY") is True


# =============================================================================
# 2. default_round_speakers
# =============================================================================
class TestDefaultRoundSpeakers:
    def test_round_1_has_proposer_plus_reviewers(self) -> None:
        speakers = default_round_speakers(1, [])
        roles = [s.role for s in speakers]
        assert roles[0] == "proposer"
        assert "reviewer" in roles
        # Strategist 첫 발언
        assert speakers[0].agent == "SystemRefactoringStrategist"

    def test_round_2_has_dissenters_when_supplied(self) -> None:
        speakers = default_round_speakers(2, ["CTO", "PythonEngineer"])
        dissenter_agents = [s.agent for s in speakers if s.role == "dissenter"]
        assert "CTO" in dissenter_agents
        assert "PythonEngineer" in dissenter_agents

    def test_round_3_is_mediator_only(self) -> None:
        speakers = default_round_speakers(3, ["CTO"])
        assert len(speakers) == 1
        assert speakers[0].role == "mediator"
        assert speakers[0].agent == "BoardroomFacilitator"

    def test_invalid_round_yields_empty(self) -> None:
        assert default_round_speakers(4, []) == []
        assert default_round_speakers(0, []) == []


# =============================================================================
# 3. route_message — recipient 순차 발언 + context 누적
# =============================================================================
class TestRouteMessage:
    def test_route_to_single_recipient_with_llm(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "동의합니다."})

        responses = route_message(
            sender="BoardroomFacilitator",
            message="라운드 1 시작",
            recipients=[Speaker("CTO", "reviewer")],
            proposal_context="안건: GUI sandbox 강화",
            prior_statements=[],
            llm_call=fake_llm,
        )
        assert len(responses) == 1
        assert responses[0].agent == "CTO"
        assert responses[0].content == "동의합니다."
        assert responses[0].is_dissent is False

    def test_route_to_multiple_recipients_in_order(self) -> None:
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            # 각 호출별 다른 응답
            idx = len(calls)
            return json.dumps({"content": f"발언 #{idx}"})

        responses = route_message(
            sender="X",
            message="m",
            recipients=[
                Speaker("CTO", "reviewer"),
                Speaker("AutoFixCoordinator", "reviewer"),
                Speaker("PythonEngineer", "reviewer"),
            ],
            proposal_context="안건",
            prior_statements=[],
            llm_call=fake_llm,
        )
        assert [r.agent for r in responses] == [
            "CTO",
            "AutoFixCoordinator",
            "PythonEngineer",
        ]
        assert [r.content for r in responses] == [
            "발언 #1",
            "발언 #2",
            "발언 #3",
        ]

    def test_route_without_llm_uses_deterministic_placeholder(self) -> None:
        responses = route_message(
            sender="X",
            message="m",
            recipients=[Speaker("CTO", "reviewer")],
            proposal_context="안건",
            prior_statements=[],
            llm_call=None,
        )
        assert "CTO" in responses[0].content
        assert "1차 검토" in responses[0].content

    def test_dissenter_role_marks_is_dissent_true(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "검토 의견"})

        responses = route_message(
            sender="X",
            message="m",
            recipients=[Speaker("CTO", "dissenter")],
            proposal_context="안건",
            prior_statements=[],
            llm_call=fake_llm,
        )
        # role=dissenter 면 content 와 무관하게 is_dissent=True
        assert responses[0].is_dissent is True

    def test_content_keyword_triggers_is_dissent(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "이 안건에 반박합니다 — 근거 부족"})

        responses = route_message(
            sender="X",
            message="m",
            recipients=[Speaker("CTO", "reviewer")],  # role=reviewer
            proposal_context="안건",
            prior_statements=[],
            llm_call=fake_llm,
        )
        # 결정론 키워드 "반박" → is_dissent=True
        assert responses[0].is_dissent is True

    def test_llm_exception_falls_back_to_placeholder(self) -> None:
        def broken_llm(prompt: str) -> str:
            raise RuntimeError("LLM 결함")

        responses = route_message(
            sender="X",
            message="m",
            recipients=[Speaker("CTO", "reviewer")],
            proposal_context="안건",
            prior_statements=[],
            llm_call=broken_llm,
        )
        assert "LLM 실패" in responses[0].content


# =============================================================================
# 4. _build_speaker_prompt — context 누적
# =============================================================================
class TestBuildSpeakerPrompt:
    def test_includes_proposal_context(self) -> None:
        prompt = _build_speaker_prompt(
            speaker=Speaker("CTO", "reviewer"),
            sender="Strategist",
            message="라운드 1",
            proposal_context="안건: GUI sandbox 강화",
            prior_statements=[],
        )
        assert "GUI sandbox 강화" in prompt
        assert "CTO" in prompt

    def test_includes_prior_statements_when_supplied(self) -> None:
        prior = [
            Statement(
                agent="Strategist",
                role="proposer",
                content="안건 발제 내용",
                timestamp="2026-05-28T07:00:00Z",
            ),
        ]
        prompt = _build_speaker_prompt(
            speaker=Speaker("CTO", "dissenter"),
            sender="Facilitator",
            message="반박 라운드",
            proposal_context="안건",
            prior_statements=prior,
        )
        assert "안건 발제 내용" in prompt
        assert "Strategist" in prompt

    def test_role_specific_guidance_present(self) -> None:
        for role, marker in [
            ("proposer", "발제자"),
            ("reviewer", "검토자"),
            ("dissenter", "반박자"),
            ("mediator", "중재자"),
        ]:
            prompt = _build_speaker_prompt(
                speaker=Speaker("X", role),
                sender="Y",
                message="m",
                proposal_context="c",
                prior_statements=[],
            )
            assert marker in prompt, f"role={role} guidance 누락"


# =============================================================================
# 5. _extract_speaker_content
# =============================================================================
class TestExtractSpeakerContent:
    def test_json_with_content_key(self) -> None:
        out = _extract_speaker_content(
            '{"content": "발언입니다"}', Speaker("X", "reviewer")
        )
        assert out == "발언입니다"

    def test_raw_text_fallback(self) -> None:
        out = _extract_speaker_content("not json", Speaker("X", "reviewer"))
        assert out == "not json"

    def test_empty_response_yields_placeholder(self) -> None:
        out = _extract_speaker_content("", Speaker("CTO", "reviewer"))
        assert "CTO" in out
        assert "빈 값" in out


# =============================================================================
# 6. collect_dissent
# =============================================================================
class TestCollectDissent:
    def test_empty_returns_empty(self) -> None:
        assert collect_dissent([]) == []

    def test_only_dissenters_returned(self) -> None:
        responses = [
            AgentResponse("CTO", "reviewer", "동의", is_dissent=False),
            AgentResponse("PE", "reviewer", "반박합니다", is_dissent=True),
            AgentResponse("AC", "dissenter", "재검토 필요", is_dissent=True),
        ]
        dissent_agents = collect_dissent(responses)
        assert set(dissent_agents) == {"PE", "AC"}


# =============================================================================
# 7. conduct_round — 라운드 진행 + max 3 하드 캡
# =============================================================================
class TestConductRound:
    def test_round_1_returns_proceed_if_dissent(self) -> None:
        def fake_llm(prompt: str) -> str:
            # 첫 발언자 (proposer): 일반 발언
            # 후속 발언자: dissent 트리거 키워드
            if "발제자" in prompt:
                return json.dumps({"content": "안건 발제"})
            return json.dumps({"content": "이 안건에 반박합니다"})

        result = conduct_round(
            round_num=1,
            proposal_context="안건",
            prior_statements=[],
            llm_call=fake_llm,
        )
        assert isinstance(result, RoundResult)
        assert result.round.round_num == 1
        assert result.round.dissent_detected is True
        assert result.proceed_to_next is True

    def test_round_1_no_proceed_when_consensus(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "전적으로 동의합니다"})

        result = conduct_round(
            round_num=1,
            proposal_context="안건",
            prior_statements=[],
            llm_call=fake_llm,
        )
        assert result.round.dissent_detected is False
        assert result.proceed_to_next is False

    def test_round_3_never_proceeds(self) -> None:
        """Round 3 (mediator) 는 dissent 와 무관하게 마지막."""

        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "반박 의견 여전"})

        result = conduct_round(
            round_num=3,
            proposal_context="안건",
            prior_statements=[],
            dissenters_from_prev=["CTO"],
            llm_call=fake_llm,
        )
        assert result.proceed_to_next is False

    def test_invalid_round_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="1~3"):
            conduct_round(
                round_num=4,
                proposal_context="x",
                prior_statements=[],
            )
        with pytest.raises(ValueError, match="1~3"):
            conduct_round(
                round_num=0,
                proposal_context="x",
                prior_statements=[],
            )

    def test_explicit_speakers_override(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "ok"})

        result = conduct_round(
            round_num=1,
            proposal_context="안건",
            prior_statements=[],
            speakers=[Speaker("CustomAgent", "reviewer")],
            llm_call=fake_llm,
        )
        assert len(result.round.statements) == 1
        assert result.round.statements[0].agent == "CustomAgent"

    def test_round_2_includes_dissenters_from_prev(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "재발언"})

        result = conduct_round(
            round_num=2,
            proposal_context="안건",
            prior_statements=[],
            dissenters_from_prev=["CTO", "PythonEngineer"],
            llm_call=fake_llm,
        )
        agents = [s.agent for s in result.round.statements]
        assert "CTO" in agents
        assert "PythonEngineer" in agents


# =============================================================================
# 8. create_delegation_enabled_pair — PM 명세 #3
# =============================================================================
class TestDelegationEnabledPair:
    def test_pair_factory_returns_two_agents_with_delegation(self) -> None:
        from unittest.mock import patch

        from src.agents.coordination import create_delegation_enabled_pair

        with (
            patch(
                "src.agents.engineering.python_engineer.NexusAlphaLLM"
            ) as MockLLM1,
            patch("src.agents.qa.code_reviewer.NexusAlphaLLM") as MockLLM2,
        ):
            from src.llm import NexusAlphaLLM

            # 실 LLM 인스턴스 (pydantic validation 통과)
            real_llm = NexusAlphaLLM.__new__(NexusAlphaLLM)
            pair = create_delegation_enabled_pair(llm=real_llm)
            assert set(pair.keys()) == {"code_reviewer", "python_engineer"}
            assert pair["code_reviewer"].allow_delegation is True
            assert pair["python_engineer"].allow_delegation is True


# =============================================================================
# 9. CrewAI Agent metadata (factory 시그니처)
# =============================================================================
class TestConsultantAgentMetadata:
    def test_constants_present(self) -> None:
        from src.agents.coordination import (
            CROSS_AGENT_CONSULTANT_BACKSTORY,
            CROSS_AGENT_CONSULTANT_GOAL,
            CROSS_AGENT_CONSULTANT_NAME,
            CROSS_AGENT_CONSULTANT_ROLE,
        )

        assert CROSS_AGENT_CONSULTANT_NAME == "CrossAgentConsultant"
        assert "Cross-Agent" in CROSS_AGENT_CONSULTANT_ROLE
        assert "Routing" in CROSS_AGENT_CONSULTANT_ROLE
        assert "수집" in CROSS_AGENT_CONSULTANT_GOAL
        assert "양방향" in CROSS_AGENT_CONSULTANT_BACKSTORY

    def test_factory_signature_includes_allow_delegation(self) -> None:
        import inspect

        from src.agents.coordination import create_cross_agent_consultant_agent

        sig = inspect.signature(create_cross_agent_consultant_agent)
        assert "allow_delegation" in sig.parameters
        # default=True (Cross-Agent Consultant 는 본 의도)
        assert sig.parameters["allow_delegation"].default is True
