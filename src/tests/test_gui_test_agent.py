# -*- coding: utf-8 -*-
"""
GUI Test Agent (PR #44) smoke + regression test.

검증 항목:
    1) `create_gui_test_agent()` 가 NexusAlphaLLM (FakeProvider 자동 주입) 으로
       정상 생성되는지
    2) Agent backstory 에 출력 규약 (`Final Answer:` 우선) 명시 (이슈 4 회귀 방지)
    3) 5단 구조 + 결함 분류 (CRITICAL / MAJOR / MINOR) + skipped 처리 명시
    4) CrewAI Crew 로 단일 Task 실행 시 FakeProvider 응답 정상 수렴
"""

from __future__ import annotations

from crewai import Crew, Task

from src.agents.qa import (
    GUI_TEST_AGENT_BACKSTORY,
    GUI_TEST_AGENT_NAME,
    GUI_TEST_AGENT_ROLE,
    create_gui_test_agent,
)


def test_create_gui_test_agent_uses_fake_provider() -> None:
    agent = create_gui_test_agent(verbose=False)
    assert agent.role == GUI_TEST_AGENT_ROLE
    assert agent.llm.backend_provider.name == "fake"


def test_gui_test_agent_name_consistency() -> None:
    agent = create_gui_test_agent(verbose=False)
    assert agent.role == GUI_TEST_AGENT_ROLE
    assert GUI_TEST_AGENT_NAME == "GUITestAgent"


def test_backstory_enforces_final_answer_first_pattern() -> None:
    bs = GUI_TEST_AGENT_BACKSTORY
    assert "출력 규약 (CRITICAL)" in bs
    assert "Final Answer:" in bs
    assert "본문" in bs and "앞" in bs


def test_backstory_does_not_use_truncating_final_answer_pattern() -> None:
    bs = GUI_TEST_AGENT_BACKSTORY
    forbidden = [
        "마지막 줄 Final Answer:",
        "Final Answer 한 줄로 마무리",
        "Final Answer: <summary>",
    ]
    for pat in forbidden:
        assert pat not in bs, f"backstory 에 금지 패턴 포함: {pat!r}"


def test_backstory_contains_5_section_structure() -> None:
    bs = GUI_TEST_AGENT_BACKSTORY
    sections = [
        "1. 종합 판정",
        "2. 스크린샷별 분석",
        "3. 우선순위별 결함",
        "4. 재생성 지시",
        "5. 미검증",
    ]
    for section in sections:
        assert section in bs, f"backstory 섹션 누락: {section!r}"


def test_backstory_specifies_severity_levels() -> None:
    """CRITICAL / MAJOR / MINOR 결함 분류 명시."""
    bs = GUI_TEST_AGENT_BACKSTORY
    for level in ["CRITICAL", "MAJOR", "MINOR"]:
        assert level in bs, f"backstory 에 결함 분류 누락: {level}"


def test_backstory_handles_skipped_state() -> None:
    """skipped=True 가 결함이 아님을 명시."""
    bs = GUI_TEST_AGENT_BACKSTORY
    # 'skipped' 또는 'SKIPPED' 가 보고서 결과 분류에 포함됐는지
    assert "SKIPPED" in bs
    assert "결함이 아니다" in bs or "FAIL 도 아님" in bs


def test_backstory_mentions_terminated_by_signals() -> None:
    """process_terminated_by 단서 활용 명시 (timeout_kill / natural_exit / terminated_after_capture)."""
    bs = GUI_TEST_AGENT_BACKSTORY
    assert "natural_exit" in bs
    assert "timeout_kill" in bs


def test_backstory_includes_korean_font_example() -> None:
    """한글 깨짐 → 코드 보정 매핑 예시 (Malgun Gothic 등)."""
    bs = GUI_TEST_AGENT_BACKSTORY
    assert "Malgun Gothic" in bs or "한글" in bs


def test_gui_test_agent_runs_through_crew_with_fake_provider() -> None:
    agent = create_gui_test_agent(verbose=False)

    task = Task(
        description=(
            "다음 GUITestResult 를 분석하고 5단 구조의 보고서를 작성하세요.\n"
            "# GUI Test Result — overall_success=False, skipped=False, elapsed=4.2s\n"
            "target: Calculator.exe\n"
            "screenshots: 1 장\n"
            "process: exit_code=0, terminated_by=terminated_after_capture\n"
            "summary: critical_issues=1, ui_issues=2\n"
            "\n"
            "## screenshot 1 — screenshot_01.png\n"
            "  [VISION CRITICAL×1] is_window_visible=True\n"
            "  summary: 한글 일부 □ 깨짐\n"
            "  ui_issues:\n"
            "    - '계산기' 라벨 □□□ 표시\n"
            "    - 숫자 7 버튼 살짝 잘림\n"
        ),
        expected_output=(
            "5단 구조 (종합 / 스크린샷별 / 우선순위 결함 / 재생성 지시 / 미검증) "
            "한국어 마크다운 보고서. Final Answer 가 본문보다 앞."
        ),
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "GUI Test Agent kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text
