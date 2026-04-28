# -*- coding: utf-8 -*-
"""
Code QA Agent (PR #42) smoke + regression test.

검증 항목:
    1) `create_code_qa_agent()` 가 NexusAlphaLLM (FakeProvider 자동 주입) 으로
       정상 생성되는지
    2) Agent backstory 에 출력 규약 (`Final Answer:` 우선) 이 명시돼 있는지
       (이슈 4 회귀 방지)
    3) Code QA 본문 구조 5단 (종합 판정 / 출력 인용 / 우선순위 이슈 / 재생성 지시
       / 미검증 영역) 이 backstory 에 박혀 있는지
    4) CrewAI Crew 로 단일 Task 실행 시 FakeProvider 응답이 AgentFinish 로
       정상 수렴하는지
"""

from __future__ import annotations

from crewai import Crew, Task

from src.agents.qa import (
    CODE_QA_AGENT_BACKSTORY,
    CODE_QA_AGENT_NAME,
    CODE_QA_AGENT_ROLE,
    create_code_qa_agent,
)


def test_create_code_qa_agent_uses_fake_provider() -> None:
    """conftest 의 FakeProvider 가 자동 주입돼야 한다."""
    agent = create_code_qa_agent(verbose=False)
    assert agent.role == CODE_QA_AGENT_ROLE
    assert agent.llm.backend_provider.name == "fake"


def test_code_qa_agent_name_consistency() -> None:
    """팩토리가 모듈 상수 이름을 그대로 사용해야 한다."""
    agent = create_code_qa_agent(verbose=False)
    assert agent.role == CODE_QA_AGENT_ROLE
    # name field 는 CrewAI Agent 에 따라 다를 수 있어 모듈 상수만 검증
    assert CODE_QA_AGENT_NAME == "CodeQAAgent"


def test_backstory_enforces_final_answer_first_pattern() -> None:
    """출력 규약 (`Final Answer:` 우선) 이 backstory 에 명시돼야 한다.

    이슈 4 회귀 방지 — backstory 에서 `Final Answer:` 가 본문보다 *앞* 에
    오도록 강제하지 않으면 CrewAI 가 본문을 잃어버린다.
    """
    bs = CODE_QA_AGENT_BACKSTORY
    # 출력 규약 마커가 있어야 함
    assert "출력 규약 (CRITICAL)" in bs
    # `Final Answer:` 이 본문보다 앞에 와야 한다는 명시
    assert "Final Answer:" in bs
    assert "본문" in bs and "앞" in bs  # "본문이 ... 앞에 오면" 같은 안내


def test_backstory_does_not_use_truncating_final_answer_pattern() -> None:
    """이슈 4 회귀 방지 — 'Final Answer: <한 줄 요약>' 만으로 본문 마무리 패턴 금지.

    PR #25 의 grep 보호와 동일 원리. 본문이 Final Answer 다음 줄부터 시작하라고
    명시해야 함 — 한 줄 summary 로 끝나는 패턴은 backstory 가 본문 손실을 유발.
    """
    bs = CODE_QA_AGENT_BACKSTORY
    # 본문 손실 패턴: "마지막 줄 Final Answer:" 또는 "Final Answer 한 줄로 마무리"
    forbidden_patterns = [
        "마지막 줄 Final Answer:",
        "Final Answer 한 줄로 마무리",
        "Final Answer: <summary>",
    ]
    for pat in forbidden_patterns:
        assert pat not in bs, f"backstory 에 금지 패턴이 포함됨: {pat!r}"


def test_backstory_contains_5_section_structure() -> None:
    """5단 구조 (종합 판정 / 출력 인용 / 우선순위 이슈 / 재생성 지시 / 미검증) 명시."""
    bs = CODE_QA_AGENT_BACKSTORY
    sections = [
        "1. 종합 판정",
        "2. 출력 인용",
        "3. 우선순위별 이슈",
        "4. 재생성 지시",
        "5. 미검증 영역",
    ]
    for section in sections:
        assert section in bs, f"backstory 에 섹션 누락: {section!r}"


def test_backstory_specifies_priority_classification() -> None:
    """BLOCKER / MAJOR / MINOR 분류 기준이 명시돼 있어야 함."""
    bs = CODE_QA_AGENT_BACKSTORY
    assert "BLOCKER" in bs
    assert "MAJOR" in bs
    assert "MINOR" in bs
    # 분류 기준의 핵심 키워드
    assert "errors" in bs.lower()  # BLOCKER = pytest errors
    assert "failed" in bs.lower()  # MAJOR = pytest failed
    assert "violations" in bs.lower()  # MINOR = ruff violations


def test_code_qa_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답이 CrewAI 파서를 거쳐 AgentFinish 로 정상 수렴."""
    agent = create_code_qa_agent(verbose=False)

    task = Task(
        description=(
            "다음 CodeQAResult 를 분석하고 5단 구조의 보고서를 작성하세요.\n"
            "# Code QA Result — overall_success=True, elapsed=0.6s\n"
            "## pytest\n"
            "  [PYTEST PASS] passed=5 failed=0 errors=0 skipped=0 (exit=0, 0.5s)\n"
            "## ruff\n"
            "  [RUFF CLEAN] 0 위반 (exit=0, 0.1s)\n"
        ),
        expected_output=(
            "5단 구조 (종합 판정 / 출력 인용 / 우선순위 이슈 / 재생성 지시 / "
            "미검증 영역) 의 한국어 마크다운 보고서. Final Answer 라인이 본문보다 앞."
        ),
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Code QA Agent kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text
