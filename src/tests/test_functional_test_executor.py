# -*- coding: utf-8 -*-
"""src/agents/qa/functional_test_executor.py 회귀 방지 테스트.

PR #43 — 엣지케이스 입력값 동적 검증 executor.

실제 subprocess 호출은 작은 임시 .py 파일로 통합 검증 — _has_traceback /
_tail_text 같은 순수 헬퍼는 단위 검증.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.agents.qa.functional_test_executor import (
    DEFAULT_EDGE_CASES,
    FunctionalTestResult,
    TestCase,
    TestCaseResult,
    _has_traceback,
    _tail_text,
    format_functional_test_result_for_task,
    run_test_cases,
)


# ---------------------------------------------------------------------------
# 순수 헬퍼
# ---------------------------------------------------------------------------


def test_tail_text_preserves_short() -> None:
    assert _tail_text("hello") == "hello"


def test_tail_text_truncates_long() -> None:
    long = "x" * 20_000
    result = _tail_text(long, limit=5_000)
    assert result.startswith("...(truncated 15000 bytes)...")
    assert result.endswith("x" * 5_000)


def test_tail_text_handles_empty() -> None:
    assert _tail_text("") == ""


def test_has_traceback_detects_python_traceback() -> None:
    stderr = "Traceback (most recent call last):\n  File ...\nValueError: bad"
    assert _has_traceback(stderr) is True


def test_has_traceback_returns_false_when_no_traceback() -> None:
    assert _has_traceback("regular output") is False
    assert _has_traceback("") is False
    assert _has_traceback("Error: something") is False  # not Python traceback signature


# ---------------------------------------------------------------------------
# DEFAULT_EDGE_CASES 정합성
# ---------------------------------------------------------------------------


def test_default_edge_cases_has_expected_categories() -> None:
    """카탈로그에 핵심 카테고리가 모두 포함됐는지."""
    names = {case.name for case in DEFAULT_EDGE_CASES}
    expected = {
        "empty_input",
        "whitespace_only",
        "zero",
        "negative",
        "very_large_number",
        "non_numeric",
        "unicode_korean",
        "unicode_emoji",
        "multiline_long",
        "injection_like",
    }
    missing = expected - names
    assert not missing, f"DEFAULT_EDGE_CASES 누락: {missing}"


def test_default_edge_cases_all_have_descriptions() -> None:
    for case in DEFAULT_EDGE_CASES:
        assert case.description, f"{case.name} 설명 비어 있음"


# ---------------------------------------------------------------------------
# run_test_cases — 실제 subprocess 통합 검증 (작은 임시 .py)
# ---------------------------------------------------------------------------


def _write_target(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "target.py"
    target.write_text(body, encoding="utf-8")
    return target


def test_run_test_cases_target_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist.py"
    result = run_test_cases(nonexistent, cases=[])
    assert result.success is False
    assert result.error_message and "부재" in result.error_message


def test_run_test_cases_robust_target_passes_all(tmp_path: Path) -> None:
    """모든 입력을 try/except 로 처리하는 견고한 타깃 — 모든 케이스 통과."""
    body = """\
import sys
try:
    raw = sys.stdin.read().strip()
    print(f"received: {raw!r}")
except Exception as e:
    print(f"handled: {type(e).__name__}")
"""
    target = _write_target(tmp_path, body)
    cases = [
        TestCase("empty", "", "빈 입력"),
        TestCase("text", "hello\\n", "일반 텍스트"),
        TestCase("unicode", "한글\\n", "유니코드"),
    ]
    result = run_test_cases(target, cases=cases, per_case_timeout_sec=10)
    assert result.success is True
    assert result.passed_count == 3
    assert result.failed_count == 0


def test_run_test_cases_crash_target_fails(tmp_path: Path) -> None:
    """input() 만 호출하고 빈 입력 시 EOFError → traceback → CRASH 분류."""
    body = """\
x = input()
print(int(x))
"""
    target = _write_target(tmp_path, body)
    cases = [TestCase("empty_eof", "", "EOF 시 EOFError")]
    result = run_test_cases(target, cases=cases, per_case_timeout_sec=10)
    assert result.success is False
    assert result.case_results[0].passed is False
    assert "exception" in (result.case_results[0].failure_reason or "").lower()


def test_run_test_cases_timeout_marks_failure(tmp_path: Path) -> None:
    """무한 루프 — 1초 timeout 으로 빠르게 실패 판정."""
    body = """\
import sys
sys.stdin.read()  # consume stdin
while True:
    pass
"""
    target = _write_target(tmp_path, body)
    cases = [TestCase("hang", "x\\n", "무한 루프")]
    result = run_test_cases(target, cases=cases, per_case_timeout_sec=1)
    assert result.success is False
    assert result.case_results[0].timed_out is True
    assert result.case_results[0].passed is False
    assert "timeout" in (result.case_results[0].failure_reason or "").lower()


def test_run_test_cases_expected_exit_code_mismatch(tmp_path: Path) -> None:
    """expected_exit_code 0 인데 실측 1 — WRONG_EXIT 분류."""
    body = """\
import sys
sys.exit(1)
"""
    target = _write_target(tmp_path, body)
    cases = [TestCase("exit_check", "", "exit_code 검증", expected_exit_code=0)]
    result = run_test_cases(target, cases=cases, per_case_timeout_sec=5)
    assert result.case_results[0].passed is False
    assert "exit_code" in (result.case_results[0].failure_reason or "")


def test_run_test_cases_default_catalog_on_simple_target(tmp_path: Path) -> None:
    """DEFAULT_EDGE_CASES 전체로 작은 견고한 타깃 실행 — 일부는 통과해야."""
    body = """\
import sys
try:
    data = sys.stdin.read()
    print(f"len={len(data)}")
except Exception as e:
    print(f"err={type(e).__name__}")
"""
    target = _write_target(tmp_path, body)
    result = run_test_cases(target, per_case_timeout_sec=5)
    # 견고한 타깃이라 전부 통과해야 함 (traceback 없음)
    assert result.passed_count == len(DEFAULT_EDGE_CASES)
    assert result.failed_count == 0


# ---------------------------------------------------------------------------
# format_functional_test_result_for_task
# ---------------------------------------------------------------------------


def test_format_includes_overall_summary(tmp_path: Path) -> None:
    cr = TestCaseResult(
        case_name="empty",
        description="빈 입력",
        stdin_input="",
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="ok",
        stderr="",
        passed=True,
    )
    result = FunctionalTestResult(
        success=True,
        elapsed_sec=0.5,
        target_path=tmp_path / "target.py",
        case_results=[cr],
    )
    text = format_functional_test_result_for_task(result)
    assert "Functional Test Result" in text
    assert "overall_success=True" in text
    assert "1/1 통과" in text
    assert "## empty" in text


def test_format_handles_error_message(tmp_path: Path) -> None:
    """target 부재 등 *케이스 실행 자체* 가 막힌 경우."""
    result = FunctionalTestResult(
        success=False,
        elapsed_sec=0.01,
        target_path=tmp_path / "missing.py",
        error_message="target_script 부재: missing.py",
    )
    text = format_functional_test_result_for_task(result)
    assert "error_message" in text
    assert "부재" in text


def test_format_truncates_long_per_case_output(tmp_path: Path) -> None:
    long_stdout = "\n".join(f"line {i}" for i in range(100))
    cr = TestCaseResult(
        case_name="big",
        description="큰 출력",
        stdin_input="x",
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout=long_stdout,
        stderr="",
        passed=True,
    )
    result = FunctionalTestResult(
        success=True, elapsed_sec=0.1, target_path=tmp_path / "t.py", case_results=[cr]
    )
    text = format_functional_test_result_for_task(result, max_lines_per_case=5)
    assert "앞부분 생략" in text
    assert "line 99" in text
    # line 0 ~ line 94 는 잘린 상태
    assert "line 95" in text


# ---------------------------------------------------------------------------
# summary_line — 표기 검증
# ---------------------------------------------------------------------------


def test_test_case_result_summary_line_pass() -> None:
    cr = TestCaseResult(
        case_name="empty",
        description="",
        stdin_input="",
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="",
        passed=True,
    )
    assert "PASS" in cr.summary_line()


def test_test_case_result_summary_line_fail_with_reason() -> None:
    cr = TestCaseResult(
        case_name="empty",
        description="",
        stdin_input="",
        exit_code=1,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="Traceback...\nValueError: bad",
        passed=False,
        failure_reason="ValueError: bad",
    )
    line = cr.summary_line()
    assert "FAIL" in line
    assert "ValueError" in line


def test_test_case_result_summary_line_timeout() -> None:
    cr = TestCaseResult(
        case_name="hang",
        description="",
        stdin_input="",
        exit_code=-1,
        elapsed_sec=10.0,
        timed_out=True,
        stdout="",
        stderr="",
        passed=False,
        failure_reason="timeout",
    )
    line = cr.summary_line()
    assert "TIMEOUT" in line
    assert "FAIL" in line


def test_functional_test_result_summary_line_pass() -> None:
    cr = TestCaseResult(
        case_name="x",
        description="",
        stdin_input="",
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="",
        passed=True,
    )
    result = FunctionalTestResult(
        success=True, elapsed_sec=0.5, case_results=[cr, cr, cr]
    )
    line = result.summary_line()
    assert "FUNCTIONAL_TEST PASS" in line
    assert "3/3" in line


def test_functional_test_result_summary_line_with_error_message() -> None:
    result = FunctionalTestResult(
        success=False,
        elapsed_sec=0.01,
        error_message="target_script 부재",
    )
    line = result.summary_line()
    assert "FAILED" in line
    assert "부재" in line
