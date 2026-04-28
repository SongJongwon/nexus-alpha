# -*- coding: utf-8 -*-
"""
Functional Test Agent (PR #43) smoke + regression test.

검증 항목:
    1) `create_functional_test_agent()` 가 NexusAlphaLLM (FakeProvider 자동 주입)
       으로 정상 생성되는지
    2) Agent backstory 에 출력 규약 (`Final Answer:` 우선) 이 명시 (이슈 4 회귀 방지)
    3) 5단 구조 (종합 판정 / 실패 케이스 상세 / 통과 분포 / 재생성 지시 / 미검증)
       이 backstory 에 박혀 있는지
    4) 실패 분류 (CRASH / TIMEOUT / WRONG_EXIT / INPUT_NOT_HANDLED) 명시 검증
    5) CrewAI Crew 로 단일 Task 실행 시 FakeProvider 응답 정상 수렴
"""

from __future__ import annotations

from crewai import Crew, Task

from src.agents.qa import (
    FUNCTIONAL_TEST_AGENT_BACKSTORY,
    FUNCTIONAL_TEST_AGENT_NAME,
    FUNCTIONAL_TEST_AGENT_ROLE,
    create_functional_test_agent,
)


def test_create_functional_test_agent_uses_fake_provider() -> None:
    agent = create_functional_test_agent(verbose=False)
    assert agent.role == FUNCTIONAL_TEST_AGENT_ROLE
    assert agent.llm.backend_provider.name == "fake"


def test_functional_test_agent_name_consistency() -> None:
    agent = create_functional_test_agent(verbose=False)
    assert agent.role == FUNCTIONAL_TEST_AGENT_ROLE
    assert FUNCTIONAL_TEST_AGENT_NAME == "FunctionalTestAgent"


def test_backstory_enforces_final_answer_first_pattern() -> None:
    bs = FUNCTIONAL_TEST_AGENT_BACKSTORY
    assert "출력 규약 (CRITICAL)" in bs
    assert "Final Answer:" in bs
    assert "본문" in bs and "앞" in bs


def test_backstory_does_not_use_truncating_final_answer_pattern() -> None:
    """이슈 4 회귀 방지 — 본문 손실 패턴 금지."""
    bs = FUNCTIONAL_TEST_AGENT_BACKSTORY
    forbidden_patterns = [
        "마지막 줄 Final Answer:",
        "Final Answer 한 줄로 마무리",
        "Final Answer: <summary>",
    ]
    for pat in forbidden_patterns:
        assert pat not in bs, f"backstory 에 금지 패턴 포함: {pat!r}"


def test_backstory_contains_5_section_structure() -> None:
    bs = FUNCTIONAL_TEST_AGENT_BACKSTORY
    sections = [
        "1. 종합 판정",
        "2. 실패 케이스 상세",
        "3. 통과 케이스 분포",
        "4. 재생성 지시",
        "5. 미검증 영역",
    ]
    for section in sections:
        assert section in bs, f"backstory 섹션 누락: {section!r}"


def test_backstory_specifies_failure_categories() -> None:
    """CRASH / TIMEOUT / WRONG_EXIT / INPUT_NOT_HANDLED 분류 기준 명시."""
    bs = FUNCTIONAL_TEST_AGENT_BACKSTORY
    categories = ["CRASH", "TIMEOUT", "WRONG_EXIT", "INPUT_NOT_HANDLED"]
    for cat in categories:
        assert cat in bs, f"backstory 에 분류 누락: {cat}"


def test_backstory_mentions_gui_target_detection() -> None:
    """전 케이스 timeout → GUI 가능성 검출 명시 (PR #44 위임 안내)."""
    bs = FUNCTIONAL_TEST_AGENT_BACKSTORY
    assert "GUI" in bs
    assert "PR #44" in bs


def test_functional_test_agent_runs_through_crew_with_fake_provider() -> None:
    agent = create_functional_test_agent(verbose=False)

    task = Task(
        description=(
            "다음 FunctionalTestResult 를 분석하고 5단 구조의 보고서를 작성하세요.\n"
            "# Functional Test Result — overall_success=False, elapsed=2.5s\n"
            "target: calculator.py\n"
            "summary: 8/10 통과, timeout=0\n\n"
            "## empty_input — FAIL\n"
            "  failure_reason: unhandled exception: EOFError\n"
            "## non_numeric — FAIL\n"
            "  failure_reason: unhandled exception: ValueError\n"
        ),
        expected_output=(
            "5단 구조 (종합 판정 / 실패 케이스 상세 / 통과 분포 / 재생성 지시 / "
            "미검증 영역) 한국어 마크다운 보고서. Final Answer 가 본문보다 앞."
        ),
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Functional Test Agent kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text
