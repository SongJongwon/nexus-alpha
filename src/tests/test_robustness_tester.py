# -*- coding: utf-8 -*-
"""Robustness Tester (PR #46) smoke + regression test."""

from __future__ import annotations

from crewai import Crew, Task

from src.agents.qa import (
    ROBUSTNESS_TESTER_BACKSTORY,
    ROBUSTNESS_TESTER_NAME,
    ROBUSTNESS_TESTER_ROLE,
    create_robustness_tester_agent,
)


def test_create_uses_fake_provider() -> None:
    agent = create_robustness_tester_agent(verbose=False)
    assert agent.role == ROBUSTNESS_TESTER_ROLE
    assert agent.llm.backend_provider.name == "fake"


def test_name_consistency() -> None:
    assert ROBUSTNESS_TESTER_NAME == "RobustnessTester"


def test_backstory_enforces_final_answer_first() -> None:
    bs = ROBUSTNESS_TESTER_BACKSTORY
    assert "출력 규약 (CRITICAL)" in bs
    assert "Final Answer:" in bs
    assert "본문" in bs and "앞" in bs


def test_backstory_does_not_use_dangerous_pattern() -> None:
    bs = ROBUSTNESS_TESTER_BACKSTORY
    forbidden = ["마지막 줄은 반드시 `Final Answer:`", "마지막 줄에 반드시 `Final Answer:`"]
    for p in forbidden:
        assert p not in bs


def test_backstory_contains_5_sections() -> None:
    bs = ROBUSTNESS_TESTER_BACKSTORY
    sections = [
        "1. 종합 판정",
        "2. 실패 시나리오 상세",
        "3. 반복 일관성",
        "4. 재생성 지시",
        "5. 미검증 영역",
    ]
    for s in sections:
        assert s in bs


def test_backstory_specifies_failure_categories() -> None:
    bs = ROBUSTNESS_TESTER_BACKSTORY
    for cat in ["RESOURCE_LIMIT", "CRASH", "PERFORMANCE", "DETERMINISM"]:
        assert cat in bs


def test_runs_through_crew_with_fake_provider() -> None:
    agent = create_robustness_tester_agent(verbose=False)
    task = Task(
        description=(
            "다음 RobustnessResult 분석.\n"
            "# Robustness Result — overall_success=False, elapsed=12.5s\n"
            "summary: 3/5 통과, timeout=1\n\n"
            "## large_input_1mb (iter=1) — FAIL\n"
            "  failure_reason: 성능 한계 초과 — 기대 ≤10.0s, 실측 11.2s\n"
        ),
        expected_output="5단 보고서 한국어 마크다운",
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)
    assert output_text.strip()
    assert "FakeProvider가 반환한 고정 응답" in output_text
