# -*- coding: utf-8 -*-
"""PR #138 Phase 1 full — Meeting Facilitator 모듈 단위 테스트.

배경 (본인 비전 통찰 6, 2026-05-15):
    환율 변환기 사례 — CTO/Analyst/UI Designer 가 "frankfurter API 실시간 환율"
    결정했으나 GUI Code Generator 가 정적 dict 내장 → 9% 오차. 4 에이전트가
    *전혀 다른 가정* 으로 일했지만 누구도 인지 못함.

PR #138 Phase 1 full 처방:
    Meeting Facilitator (본부 10 첫 멤버) 가 워크플로 진입 시 1회 호출되어
    ``SharedKickoffDecisions`` 산출 → 후속 task description 들에 자동 주입.

본 테스트 목적:
    - SharedAssumption / SharedKickoffDecisions dataclass + yaml 라운드트립
    - to_kickoff_context_directive() markdown 구조 안정성
    - 결정론 파싱: Requirement Expander YAML 에서 assumptions / open_questions 추출
    - LLM 합성: agent_responsibilities JSON 파싱 (다양한 형식)
    - 하이브리드 진입점: pytest 환경 자동 skip + 외부 주입 가능

회귀 차단: 본 테스트가 깨지면 PR #138 Phase 1 full 의 핵심 메커니즘 (킥오프 회의
→ 공유 결정 산출) 이 무력화 — 환율 사례 재발 가능.
"""

from __future__ import annotations

from src.agents.coordination import (
    SharedAssumption,
    SharedKickoffDecisions,
    run_kickoff_meeting,
)
from src.agents.coordination.meeting_facilitator import (
    _parse_responsibility_json,
    _parse_spec_deterministic,
)


# ---------------------------------------------------------------------------
# 1. SharedAssumption / SharedKickoffDecisions dataclass + yaml 라운드트립
# ---------------------------------------------------------------------------


def test_shared_assumption_dataclass_fields() -> None:
    """필수 4 필드 보유 (id / decision / rationale / owner)."""
    a = SharedAssumption(
        id="data_source",
        decision="frankfurter API 실시간",
        rationale="stale 환율 위험 회피",
        owner="CTO",
    )
    assert a.id == "data_source"
    assert a.owner == "CTO"
    assert "frankfurter" in a.decision


def test_kickoff_decisions_yaml_roundtrip() -> None:
    """to_yaml → from_yaml 라운드트립으로 모든 필드 보존."""
    original = SharedKickoffDecisions(
        user_request="환율 변환기 만들어줘",
        spec_summary="USD/KRW 환율 변환 GUI 앱",
        shared_assumptions=[
            SharedAssumption(
                id="data_source",
                decision="frankfurter API 실시간",
                rationale="stale 환율 차단",
                owner="CTO",
            )
        ],
        agent_responsibilities={
            "GUI Code Generator": ["frankfurter API 호출 코드", "tkinter GUI"]
        },
        open_questions=["캐시 TTL?"],
    )
    text = original.to_yaml()
    restored = SharedKickoffDecisions.from_yaml(text)

    assert restored.user_request == original.user_request
    assert restored.spec_summary == original.spec_summary
    assert len(restored.shared_assumptions) == 1
    assert restored.shared_assumptions[0].id == "data_source"
    assert restored.agent_responsibilities == original.agent_responsibilities
    assert restored.open_questions == original.open_questions


def test_kickoff_decisions_yaml_preserves_korean() -> None:
    """한글 escape 없이 보존 (allow_unicode=True)."""
    d = SharedKickoffDecisions(
        user_request="환율 변환기",
        spec_summary="실시간 API",
        open_questions=["캐시 정책?"],
    )
    text = d.to_yaml()
    # 한글이 \uXXXX 로 escape 되지 않아야 함
    assert "환율" in text
    assert "\\u" not in text


# ---------------------------------------------------------------------------
# 2. to_kickoff_context_directive — markdown 구조
# ---------------------------------------------------------------------------


def test_directive_empty_when_no_decisions_and_no_prior() -> None:
    """빈 decisions + 빈 prior_agent_roles → 빈 string."""
    d = SharedKickoffDecisions(user_request="x", spec_summary="y")
    assert d.to_kickoff_context_directive(prior_agent_roles=[]) == ""


def test_directive_includes_kickoff_header_when_assumptions_present() -> None:
    """assumptions 가 있으면 킥오프 헤더 + 항목들 출력."""
    d = SharedKickoffDecisions(
        user_request="환율 변환기",
        spec_summary="",
        shared_assumptions=[
            SharedAssumption(
                id="data_source",
                decision="frankfurter API",
                rationale="stale 차단",
                owner="CTO",
            )
        ],
    )
    text = d.to_kickoff_context_directive()
    assert "킥오프 회의 합의 사항" in text
    assert "data_source" in text
    assert "frankfurter" in text
    assert "CTO" in text


def test_directive_includes_responsibilities_when_present() -> None:
    """agent_responsibilities 가 있으면 ``부서별 책임`` 섹션 출력."""
    d = SharedKickoffDecisions(
        user_request="x",
        spec_summary="",
        agent_responsibilities={"CTO": ["프레임워크 선정", "외부 API 결정"]},
    )
    text = d.to_kickoff_context_directive()
    assert "부서별 책임" in text
    assert "프레임워크 선정" in text


def test_directive_appends_consistency_section_when_prior_roles_given() -> None:
    """prior_agent_roles 가 있으면 consistency 절 + 환율 사례 evidence 포함."""
    d = SharedKickoffDecisions(user_request="x", spec_summary="")
    text = d.to_kickoff_context_directive(
        prior_agent_roles=["CTO", "Analyst"]
    )
    assert "Cross-agent consistency" in text
    assert "**CTO**" in text
    assert "환율 변환기" in text


# ---------------------------------------------------------------------------
# 3. 결정론 파싱 — _parse_spec_deterministic
# ---------------------------------------------------------------------------


def test_parse_spec_extracts_assumptions_from_yaml_fence() -> None:
    """```yaml ... ``` 블록 안의 assumptions 추출."""
    spec = """
어떤 분석가 노트.

```yaml
title: 환율 변환기
assumptions:
  - frankfurter API 사용
  - 캐시는 5분 TTL
open_questions:
  - 오프라인 모드 지원?
```
"""
    assumptions, questions, summary = _parse_spec_deterministic(spec)
    assert len(assumptions) == 2
    assert "frankfurter" in assumptions[0].decision
    assert len(questions) == 1
    assert summary == "환율 변환기"


def test_parse_spec_handles_no_yaml_block() -> None:
    """YAML 블록이 없어도 예외 안 던지고 빈 결과 + 한 줄 요약 시도."""
    spec = "# 환율 변환기\n\n그냥 일반 마크다운"
    assumptions, questions, summary = _parse_spec_deterministic(spec)
    assert assumptions == []
    assert questions == []
    # 첫 비공백 줄을 summary 로 (# 제거)
    assert "환율" in summary


def test_parse_spec_assigns_unique_assumption_ids() -> None:
    """slug 충돌 없이 안정적 id 생성."""
    spec = """
```yaml
assumptions:
  - 첫 번째 가정
  - 두 번째 가정
```
"""
    assumptions, _, _ = _parse_spec_deterministic(spec)
    ids = [a.id for a in assumptions]
    assert len(set(ids)) == len(ids), "assumption id 중복 — slug 알고리즘 회귀"


# ---------------------------------------------------------------------------
# 4. _parse_responsibility_json — LLM 응답 파싱
# ---------------------------------------------------------------------------


def test_parse_responsibility_json_plain() -> None:
    """순수 JSON 응답 처리."""
    text = '{"agent_responsibilities": {"CTO": ["프레임워크 결정"]}}'
    result = _parse_responsibility_json(text)
    assert result == {"CTO": ["프레임워크 결정"]}


def test_parse_responsibility_json_with_fence() -> None:
    """```json 펜스로 감싸진 응답 처리."""
    text = """
설명 줄.
```json
{
  "agent_responsibilities": {
    "CTO": ["프레임워크 결정"],
    "GUI Code Generator": ["tkinter 코드 작성"]
  }
}
```
"""
    result = _parse_responsibility_json(text)
    assert "CTO" in result
    assert "GUI Code Generator" in result
    assert "tkinter 코드 작성" in result["GUI Code Generator"]


def test_parse_responsibility_json_handles_malformed() -> None:
    """잘못된 JSON 입력 시 빈 dict 반환 (예외 안 던짐)."""
    assert _parse_responsibility_json("그냥 텍스트 응답") == {}
    assert _parse_responsibility_json("") == {}


def test_parse_responsibility_json_skips_non_list_values() -> None:
    """role 값이 list 아니면 skip — 스키마 위반 방어."""
    text = '{"agent_responsibilities": {"CTO": "단일 문자열", "Analyst": ["올바른 리스트"]}}'
    result = _parse_responsibility_json(text)
    assert "Analyst" in result
    assert "CTO" not in result  # str 값은 skip


# ---------------------------------------------------------------------------
# 5. run_kickoff_meeting 진입점 — 결정론 + LLM 합성 통합
# ---------------------------------------------------------------------------


def test_run_kickoff_meeting_returns_shared_kickoff_decisions() -> None:
    """반환 타입 + 기본 필드 채워짐."""
    spec = """
```yaml
assumptions:
  - frankfurter API 실시간
open_questions:
  - 캐시 TTL?
```
"""
    result = run_kickoff_meeting(
        user_request="환율 변환기 만들어줘",
        spec_markdown=spec,
    )
    assert isinstance(result, SharedKickoffDecisions)
    assert result.user_request == "환율 변환기 만들어줘"
    assert len(result.shared_assumptions) == 1
    assert "frankfurter" in result.shared_assumptions[0].decision
    assert len(result.open_questions) == 1


def test_run_kickoff_meeting_skips_llm_in_pytest_env() -> None:
    """pytest 환경에선 LLM 호출 자동 skip → agent_responsibilities 는 빈 dict.

    이게 깨지면 CI 가 실제 LLM 호출 시도하다 OPENAI_API_KEY 등 누락으로 실패.
    """
    result = run_kickoff_meeting(
        user_request="테스트",
        spec_markdown="```yaml\nassumptions: []\n```",
    )
    assert result.agent_responsibilities == {}


def test_run_kickoff_meeting_uses_injected_llm_call() -> None:
    """외부 ``llm_call`` 주입 시 그 결과로 agent_responsibilities 채움."""
    fake_response = (
        '{"agent_responsibilities": {"CTO": ["테스트 책임"]}}'
    )
    calls: list[str] = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return fake_response

    result = run_kickoff_meeting(
        user_request="환율 변환기",
        spec_markdown="```yaml\nassumptions: []\n```",
        llm_call=fake_llm,
    )
    assert len(calls) == 1, "LLM 호출 1회만 — 비용 폭증 방지"
    assert result.agent_responsibilities == {"CTO": ["테스트 책임"]}


def test_run_kickoff_meeting_survives_llm_exception() -> None:
    """LLM 이 예외 던져도 워크플로 차단 X — deterministic half 만 사용."""

    def boom(prompt: str) -> str:
        raise RuntimeError("LLM down")

    result = run_kickoff_meeting(
        user_request="x",
        spec_markdown="```yaml\nassumptions:\n  - 가정 1\n```",
        llm_call=boom,
    )
    # assumptions 는 정상 파싱됨, responsibilities 는 빈 채로 반환
    assert len(result.shared_assumptions) == 1
    assert result.agent_responsibilities == {}
