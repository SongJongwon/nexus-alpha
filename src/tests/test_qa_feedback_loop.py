# -*- coding: utf-8 -*-
"""src/workflows/qa_feedback_loop.py 회귀 방지 테스트 (PR #48).

duck typing 입력으로 evaluate_qa_results / build_feedback_message_for_engineer
의 결정 로직 단위 검증. 다른 PR 들의 구체 클래스에 의존 안 함.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from src.workflows.qa_feedback_loop import (
    QAFeedbackDecision,
    build_feedback_message_for_engineer,
    evaluate_qa_results,
)


# ---------------------------------------------------------------------------
# duck-type stub — 4종 QA 결과 흉내
# ---------------------------------------------------------------------------


@dataclass
class FakeQAResult:
    success: bool
    skipped: bool = False
    line: Optional[str] = None

    def summary_line(self) -> str:
        return self.line or ("PASS" if self.success else "FAIL")


# ---------------------------------------------------------------------------
# evaluate_qa_results 결정 로직
# ---------------------------------------------------------------------------


def test_all_pass_overall_passed_no_retry() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="[CODE_QA PASS]"),
        "functional": FakeQAResult(success=True, line="[FUNCTIONAL PASS]"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True
    assert d.should_retry is False
    assert d.failed_qa_tools == []


def test_one_failure_should_retry_when_budget_left() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="PASS"),
        "functional": FakeQAResult(success=False, line="FAIL"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is False
    assert d.should_retry is True
    assert d.failed_qa_tools == ["functional"]


def test_failure_with_budget_exhausted_no_retry() -> None:
    results = {"code_qa": FakeQAResult(success=False, line="FAIL")}
    d = evaluate_qa_results(results, retry_count=3, max_retries=3)
    assert d.overall_passed is False
    assert d.should_retry is False  # budget exhausted


def test_skipped_tool_not_counted_as_failure() -> None:
    """skipped=True 는 실패 집계 제외 — 환경 미구비는 결함이 아님."""
    results = {
        "code_qa": FakeQAResult(success=True, line="PASS"),
        "gui": FakeQAResult(success=False, skipped=True, line="SKIPPED"),
        "robustness": FakeQAResult(success=True, line="PASS"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True  # gui skipped → 집계 제외
    assert d.failed_qa_tools == []
    assert d.skipped_qa_tools == ["gui"]


def test_none_result_treated_as_unrun() -> None:
    """None 값은 *해당 도구 미실행* 로 간주 — 실패 / skipped 어느 쪽도 아님."""
    results = {
        "code_qa": FakeQAResult(success=True),
        "functional": None,
        "gui": None,
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True
    assert d.failed_qa_tools == []
    assert d.skipped_qa_tools == []


def test_multiple_failures_collected() -> None:
    results = {
        "code_qa": FakeQAResult(success=False),
        "functional": FakeQAResult(success=False),
        "gui": FakeQAResult(success=True),
    }
    d = evaluate_qa_results(results, retry_count=1, max_retries=3)
    assert d.overall_passed is False
    assert set(d.failed_qa_tools) == {"code_qa", "functional"}


def test_retry_count_at_max_no_retry() -> None:
    results = {"code_qa": FakeQAResult(success=False)}
    d = evaluate_qa_results(results, retry_count=3, max_retries=3)
    assert d.should_retry is False


def test_summary_lines_collected() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="[CODE_QA PASS] 5p/0f"),
        "functional": FakeQAResult(success=False, line="[FUNCTIONAL FAIL] 2/10"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert any("CODE_QA PASS" in line for line in d.summary_lines)
    assert any("FUNCTIONAL FAIL" in line for line in d.summary_lines)


# ---------------------------------------------------------------------------
# QAFeedbackDecision.summary_line
# ---------------------------------------------------------------------------


def test_decision_summary_line_pass() -> None:
    d = QAFeedbackDecision(
        overall_passed=True,
        should_retry=False,
        retry_count=0,
        max_retries=3,
    )
    assert "QA_LOOP PASS" in d.summary_line()


def test_decision_summary_line_retry() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=1,
        max_retries=3,
        failed_qa_tools=["code_qa", "functional"],
    )
    line = d.summary_line()
    assert "RETRY" in line
    assert "code_qa" in line


def test_decision_summary_line_budget_exhausted() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=False,
        retry_count=3,
        max_retries=3,
        failed_qa_tools=["code_qa"],
    )
    line = d.summary_line()
    assert "BUDGET_EXHAUSTED" in line


# ---------------------------------------------------------------------------
# build_feedback_message_for_engineer
# ---------------------------------------------------------------------------


def test_build_message_pass_no_correction_needed() -> None:
    d = QAFeedbackDecision(
        overall_passed=True, should_retry=False, retry_count=0, max_retries=3
    )
    msg = build_feedback_message_for_engineer(d)
    assert "보정 불필요" in msg
    assert "모든 QA 도구 통과" in msg


def test_build_message_includes_failed_tools() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["code_qa", "functional"],
        summary_lines=[
            "code_qa: [CODE_QA FAIL] 2p/3f",
            "functional: [FUNCTIONAL FAIL] 5/10",
        ],
    )
    msg = build_feedback_message_for_engineer(d)
    assert "CODE_QA FAIL" in msg
    assert "FUNCTIONAL FAIL" in msg
    assert "재생성 지시" in msg


def test_build_message_includes_full_reports() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["code_qa"],
    )
    full_reports = {"code_qa": "## Code QA 보고서\n\n### 1. 종합 판정\n..."}
    msg = build_feedback_message_for_engineer(d, full_qa_reports=full_reports)
    assert "## Code QA 보고서" in msg
    assert "code_qa 보고서 (전문)" in msg


def test_build_message_includes_skipped_section() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["functional"],
        skipped_qa_tools=["gui"],
    )
    msg = build_feedback_message_for_engineer(d)
    assert "SKIPPED" in msg
    assert "gui" in msg


def test_build_message_includes_retry_metadata() -> None:
    d = QAFeedbackDecision(
        overall_passed=False, should_retry=True, retry_count=1, max_retries=3
    )
    msg = build_feedback_message_for_engineer(d)
    assert "retry_count=1" in msg
    assert "max_retries=3" in msg
