# -*- coding: utf-8 -*-
"""
Security Auditor + Performance Engineer + Compliance Officer (PR #47) 묶음 테스트.

3개 LLM-only 에이전트의 backstory grep + FakeProvider Crew kickoff smoke.
"""

from __future__ import annotations

import pytest
from crewai import Crew, Task

from src.agents.qa import (
    COMPLIANCE_OFFICER_BACKSTORY,
    COMPLIANCE_OFFICER_NAME,
    COMPLIANCE_OFFICER_ROLE,
    PERFORMANCE_ENGINEER_BACKSTORY,
    PERFORMANCE_ENGINEER_NAME,
    PERFORMANCE_ENGINEER_ROLE,
    SECURITY_AUDITOR_BACKSTORY,
    SECURITY_AUDITOR_NAME,
    SECURITY_AUDITOR_ROLE,
    create_compliance_officer_agent,
    create_performance_engineer_agent,
    create_security_auditor_agent,
)


# parametrize 로 3 에이전트 공통 검증을 묶음
AGENT_CASES = [
    pytest.param(
        create_security_auditor_agent,
        SECURITY_AUDITOR_NAME,
        SECURITY_AUDITOR_ROLE,
        SECURITY_AUDITOR_BACKSTORY,
        "SecurityAuditor",
        id="SecurityAuditor",
    ),
    pytest.param(
        create_performance_engineer_agent,
        PERFORMANCE_ENGINEER_NAME,
        PERFORMANCE_ENGINEER_ROLE,
        PERFORMANCE_ENGINEER_BACKSTORY,
        "PerformanceEngineer",
        id="PerformanceEngineer",
    ),
    pytest.param(
        create_compliance_officer_agent,
        COMPLIANCE_OFFICER_NAME,
        COMPLIANCE_OFFICER_ROLE,
        COMPLIANCE_OFFICER_BACKSTORY,
        "ComplianceOfficer",
        id="ComplianceOfficer",
    ),
]


@pytest.mark.parametrize("factory,name,role,backstory,expected_name", AGENT_CASES)
def test_agent_factory_uses_fake_provider(factory, name, role, backstory, expected_name):
    agent = factory(verbose=False)
    assert agent.role == role
    assert agent.llm.backend_provider.name == "fake"
    assert name == expected_name


@pytest.mark.parametrize("factory,name,role,backstory,expected_name", AGENT_CASES)
def test_backstory_enforces_final_answer_first(factory, name, role, backstory, expected_name):
    assert "출력 규약 (CRITICAL)" in backstory
    assert "Final Answer:" in backstory
    assert "본문" in backstory and "앞" in backstory


@pytest.mark.parametrize("factory,name,role,backstory,expected_name", AGENT_CASES)
def test_backstory_does_not_use_dangerous_pattern(factory, name, role, backstory, expected_name):
    forbidden = ["마지막 줄은 반드시 `Final Answer:`", "마지막 줄에 반드시 `Final Answer:`"]
    for p in forbidden:
        assert p not in backstory, f"{expected_name} backstory 위험 패턴: {p!r}"


@pytest.mark.parametrize("factory,name,role,backstory,expected_name", AGENT_CASES)
def test_backstory_contains_5_sections(factory, name, role, backstory, expected_name):
    sections = ["1. 종합 판정", "5"]  # 모든 5단 구조 + 마지막 섹션 (5번)
    for s in sections:
        assert s in backstory


@pytest.mark.parametrize("factory,name,role,backstory,expected_name", AGENT_CASES)
def test_runs_through_crew_with_fake_provider(factory, name, role, backstory, expected_name):
    agent = factory(verbose=False)
    task = Task(
        description=f"{expected_name} smoke task — produce 5단 보고서.",
        expected_output="5단 한국어 마크다운 보고서. Final Answer 가 본문보다 앞.",
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)
    assert output_text.strip()
    assert "FakeProvider가 반환한 고정 응답" in output_text


# --- 에이전트별 특화 grep -----------------------------------------------


def test_security_auditor_has_owasp_categories() -> None:
    bs = SECURITY_AUDITOR_BACKSTORY
    for cat in ["OWASP", "Injection", "eval", "pickle", "CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        assert cat in bs


def test_performance_engineer_has_complexity_categories() -> None:
    bs = PERFORMANCE_ENGINEER_BACKSTORY
    for cat in ["복잡도", "PASS", "DEGRADED", "FAIL", "병목", "I/O"]:
        assert cat in bs


def test_compliance_officer_has_5_categories() -> None:
    bs = COMPLIANCE_OFFICER_BACKSTORY
    for cat in [
        "robots.txt",
        "GDPR",
        "이용약관",
        "라이선스",
        "개인정보",
        "HIGH",
        "MEDIUM",
        "LOW",
    ]:
        assert cat in bs
