# -*- coding: utf-8 -*-
"""src/agents/qa/code_qa_executor.py 회귀 방지 테스트.

PR #42 — pytest + ruff subprocess executor.

실제 pytest 호출은 무한 재귀 위험 (CI 가 본 테스트를 돌리는 중에 pytest 를
또 호출), 실제 ruff 호출은 venv 미설치 가능성이 있어 둘 다 monkeypatch.
순수 헬퍼 (parser) + graceful failure 경로만 단위 테스트로 검증.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.agents.qa.code_qa_executor import (
    CodeQAResult,
    PytestResult,
    RuffResult,
    _parse_pytest_summary,
    _parse_ruff_violations,
    _resolve_executable,
    _tail_text,
    format_code_qa_result_for_task,
    run_code_qa,
    run_pytest,
    run_ruff,
)


# ---------------------------------------------------------------------------
# 순수 헬퍼 — _tail_text / _resolve_executable
# ---------------------------------------------------------------------------


def test_tail_text_preserves_short_text() -> None:
    assert _tail_text("hello") == "hello"


def test_tail_text_truncates_long_with_marker() -> None:
    long_text = "x" * 1000
    result = _tail_text(long_text, limit=200)
    assert result.startswith("...(truncated 800 bytes)...")
    assert result.endswith("x" * 200)


def test_tail_text_handles_empty() -> None:
    assert _tail_text("") == ""


def test_resolve_executable_returns_path_or_none() -> None:
    """`pytest` 는 venv 에 설치돼 있으므로 발견되거나 (Path) 또는 미설치 (None)."""
    result = _resolve_executable("pytest")
    assert result is None or isinstance(result, Path)


def test_resolve_executable_returns_none_for_definitely_missing() -> None:
    result = _resolve_executable("__definitely_not_a_real_executable_xyz123__")
    assert result is None


# ---------------------------------------------------------------------------
# _parse_pytest_summary — 실제 pytest summary 라인 패턴
# ---------------------------------------------------------------------------


def test_parse_pytest_summary_all_passed() -> None:
    stdout = "===== 5 passed in 0.42s ====="
    assert _parse_pytest_summary(stdout) == (5, 0, 0, 0)


def test_parse_pytest_summary_mixed() -> None:
    stdout = "===== 1 failed, 4 passed in 0.51s ====="
    assert _parse_pytest_summary(stdout) == (4, 1, 0, 0)


def test_parse_pytest_summary_with_errors() -> None:
    stdout = "===== 2 errors in 0.18s ====="
    assert _parse_pytest_summary(stdout) == (0, 0, 2, 0)


def test_parse_pytest_summary_with_skipped() -> None:
    stdout = "===== 3 passed, 1 skipped in 0.22s ====="
    assert _parse_pytest_summary(stdout) == (3, 0, 0, 1)


def test_parse_pytest_summary_full_combo() -> None:
    stdout = "===== 2 failed, 5 passed, 1 error, 3 skipped in 1.23s ====="
    assert _parse_pytest_summary(stdout) == (5, 2, 1, 3)


def test_parse_pytest_summary_handles_empty() -> None:
    assert _parse_pytest_summary("") == (0, 0, 0, 0)


def test_parse_pytest_summary_handles_no_summary_line() -> None:
    """summary 라인 없는 출력 — 0 으로 fallback."""
    stdout = "ImportError: No module named foo\n"
    assert _parse_pytest_summary(stdout) == (0, 0, 0, 0)


def test_parse_pytest_summary_uses_last_summary_in_multi_run() -> None:
    """역순 매칭 — 여러 summary 가 섞여도 마지막 줄 사용."""
    stdout = (
        "===== 1 passed in 0.10s =====\n"
        "(some other output)\n"
        "===== 5 passed, 1 failed in 0.50s =====\n"
    )
    # 역순 첫 매칭 → 마지막 summary 라인 (5p/1f)
    assert _parse_pytest_summary(stdout) == (5, 1, 0, 0)


# ---------------------------------------------------------------------------
# _parse_ruff_violations — ruff text format 파싱
# ---------------------------------------------------------------------------


def test_parse_ruff_violations_empty_clean() -> None:
    assert _parse_ruff_violations("") == (0, {})


def test_parse_ruff_violations_single() -> None:
    stdout = "src/foo.py:12:5: E501 line too long (105 > 100 characters)\n"
    count, by_rule = _parse_ruff_violations(stdout)
    assert count == 1
    assert by_rule == {"E501": 1}


def test_parse_ruff_violations_multiple_rules() -> None:
    stdout = (
        "src/foo.py:12:5: E501 line too long\n"
        "src/foo.py:13:1: F401 'os' imported but unused\n"
        "src/bar.py:5:1: E501 line too long\n"
        "src/bar.py:7:1: W291 trailing whitespace\n"
    )
    count, by_rule = _parse_ruff_violations(stdout)
    assert count == 4
    assert by_rule == {"E501": 2, "F401": 1, "W291": 1}


def test_parse_ruff_violations_ignores_summary_lines() -> None:
    """ruff 요약 라인 (예: ``Found 3 errors.``) 은 위반 패턴과 다르므로 무시."""
    stdout = (
        "src/foo.py:12:5: E501 line too long\n"
        "Found 1 error.\n"
        "[*] 1 fixable with the --fix option.\n"
    )
    count, _ = _parse_ruff_violations(stdout)
    assert count == 1


# ---------------------------------------------------------------------------
# run_pytest — graceful failure 경로 (실제 호출 X, monkeypatch 사용)
# ---------------------------------------------------------------------------


def test_run_pytest_returns_failure_when_target_dir_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    result = run_pytest(nonexistent)
    assert result.success is False
    assert result.exit_code == -3
    assert "부재" in (result.error_message or "")


def test_run_pytest_handles_subprocess_filenotfound(monkeypatch, tmp_path: Path) -> None:
    """Python 자체가 없을 때 (극단 케이스) graceful 처리."""
    target = tmp_path / "tests"
    target.mkdir()

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("python.exe missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_pytest(target)
    assert result.success is False
    assert result.exit_code == -2
    assert "FileNotFoundError" in (result.error_message or "")


def test_run_pytest_handles_timeout(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "tests"
    target.mkdir()

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_pytest(target, timeout_sec=1)
    assert result.success is False
    assert result.exit_code == -1
    assert "timeout" in (result.error_message or "").lower()


def test_run_pytest_parses_success_from_stdout(monkeypatch, tmp_path: Path) -> None:
    """exit 0 + summary 파싱 → success=True."""
    target = tmp_path / "tests"
    target.mkdir()

    class FakeProc:
        returncode = 0
        stdout = "===== 5 passed in 0.10s ====="
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    result = run_pytest(target)
    assert result.success is True
    assert result.exit_code == 0
    assert result.passed == 5
    assert result.failed == 0


def test_run_pytest_marks_failure_when_no_tests_collected(monkeypatch, tmp_path: Path) -> None:
    """exit 0 이지만 통과/실패/스킵 0건 → success=False (테스트 부재)."""
    target = tmp_path / "tests"
    target.mkdir()

    class FakeProc:
        returncode = 0
        stdout = ""  # summary 라인 없음
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    result = run_pytest(target)
    assert result.success is False  # 테스트 0개도 결함


def test_run_pytest_failed_tests_marked_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "tests"
    target.mkdir()

    class FakeProc:
        returncode = 1
        stdout = "===== 1 failed, 2 passed in 0.20s ====="
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    result = run_pytest(target)
    assert result.success is False
    assert result.failed == 1
    assert result.passed == 2


# ---------------------------------------------------------------------------
# run_ruff — graceful skip 경로
# ---------------------------------------------------------------------------


def test_run_ruff_gracefully_skips_when_missing(monkeypatch, tmp_path: Path) -> None:
    """ruff 미설치 → success=True + skipped=True (optional 도구)."""
    target = tmp_path / "src"
    target.mkdir()

    monkeypatch.setattr(
        "src.agents.qa.code_qa_executor._resolve_executable", lambda name: None
    )
    result = run_ruff(target)
    assert result.success is True
    assert result.skipped is True
    assert result.exit_code == -2


def test_run_ruff_returns_failure_when_target_dir_missing(
    monkeypatch, tmp_path: Path
) -> None:
    nonexistent = tmp_path / "does_not_exist"
    monkeypatch.setattr(
        "src.agents.qa.code_qa_executor._resolve_executable",
        lambda name: Path("/fake/ruff"),
    )
    result = run_ruff(nonexistent)
    assert result.success is False
    assert result.exit_code == -3


def test_run_ruff_clean_when_no_violations(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()

    monkeypatch.setattr(
        "src.agents.qa.code_qa_executor._resolve_executable",
        lambda name: Path("/fake/ruff"),
    )

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    result = run_ruff(target)
    assert result.success is True
    assert result.violations_count == 0


def test_run_ruff_violations_parsed(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()

    monkeypatch.setattr(
        "src.agents.qa.code_qa_executor._resolve_executable",
        lambda name: Path("/fake/ruff"),
    )

    class FakeProc:
        returncode = 1
        stdout = (
            "src/foo.py:12:5: E501 line too long\n"
            "src/foo.py:13:1: F401 unused import\n"
        )
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    result = run_ruff(target)
    assert result.success is False
    assert result.violations_count == 2
    assert result.violations_by_rule == {"E501": 1, "F401": 1}


# ---------------------------------------------------------------------------
# run_code_qa — 묶음 동작
# ---------------------------------------------------------------------------


def test_run_code_qa_success_when_both_pass(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()

    def fake_pytest(td, **kw):
        return PytestResult(
            success=True, exit_code=0, elapsed_sec=0.1, passed=3, target_dir=td
        )

    def fake_ruff(td, **kw):
        return RuffResult(success=True, exit_code=0, elapsed_sec=0.05, target_dir=td)

    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_pytest", fake_pytest)
    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_ruff", fake_ruff)

    result = run_code_qa(target)
    assert result.success is True
    assert result.pytest.passed == 3
    assert result.ruff.success is True


def test_run_code_qa_fails_when_pytest_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()

    def fake_pytest(td, **kw):
        return PytestResult(
            success=False,
            exit_code=1,
            elapsed_sec=0.1,
            passed=2,
            failed=1,
            target_dir=td,
        )

    def fake_ruff(td, **kw):
        return RuffResult(success=True, exit_code=0, elapsed_sec=0.05, target_dir=td)

    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_pytest", fake_pytest)
    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_ruff", fake_ruff)

    result = run_code_qa(target)
    assert result.success is False  # pytest 실패 → 종합 실패


def test_run_code_qa_passes_with_ruff_skipped(monkeypatch, tmp_path: Path) -> None:
    """ruff 미설치 → skipped=True 면 pytest 만으로 success 판정."""
    target = tmp_path / "src"
    target.mkdir()

    def fake_pytest(td, **kw):
        return PytestResult(
            success=True, exit_code=0, elapsed_sec=0.1, passed=3, target_dir=td
        )

    def fake_ruff(td, **kw):
        return RuffResult(
            success=True,
            exit_code=-2,
            elapsed_sec=0.0,
            skipped=True,
            target_dir=td,
        )

    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_pytest", fake_pytest)
    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_ruff", fake_ruff)

    result = run_code_qa(target)
    assert result.success is True
    assert result.ruff.skipped is True


def test_run_code_qa_skip_ruff_explicitly(monkeypatch, tmp_path: Path) -> None:
    """skip_ruff=True 명시 시 ruff 호출 자체 안 함."""
    target = tmp_path / "src"
    target.mkdir()

    def fake_pytest(td, **kw):
        return PytestResult(
            success=True, exit_code=0, elapsed_sec=0.1, passed=1, target_dir=td
        )

    def explode_ruff(td, **kw):
        raise AssertionError("ruff 가 호출되면 안 됨 (skip_ruff=True)")

    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_pytest", fake_pytest)
    monkeypatch.setattr("src.agents.qa.code_qa_executor.run_ruff", explode_ruff)

    result = run_code_qa(target, skip_ruff=True)
    assert result.success is True
    assert result.ruff.skipped is True


# ---------------------------------------------------------------------------
# format_code_qa_result_for_task — Task description 직렬화
# ---------------------------------------------------------------------------


def test_format_code_qa_result_for_task_success_path(tmp_path: Path) -> None:
    pytest_result = PytestResult(
        success=True,
        exit_code=0,
        elapsed_sec=0.5,
        passed=5,
        target_dir=tmp_path,
        stdout="===== 5 passed in 0.5s =====",
    )
    ruff_result = RuffResult(success=True, exit_code=0, elapsed_sec=0.1, target_dir=tmp_path)
    qa = CodeQAResult(success=True, elapsed_sec=0.6, pytest=pytest_result, ruff=ruff_result)

    text = format_code_qa_result_for_task(qa)
    assert "Code QA Result" in text
    assert "overall_success=True" in text
    assert "## pytest" in text
    assert "## ruff" in text
    assert "5 passed" in text


def test_format_code_qa_result_for_task_failure_path(tmp_path: Path) -> None:
    pytest_result = PytestResult(
        success=False,
        exit_code=1,
        elapsed_sec=0.5,
        passed=2,
        failed=1,
        target_dir=tmp_path,
        stdout="===== 1 failed, 2 passed in 0.5s =====",
        stderr="AssertionError: expected 5, got 3",
    )
    ruff_result = RuffResult(
        success=True, exit_code=-2, elapsed_sec=0.0, skipped=True, target_dir=tmp_path
    )
    qa = CodeQAResult(success=False, elapsed_sec=0.5, pytest=pytest_result, ruff=ruff_result)

    text = format_code_qa_result_for_task(qa)
    assert "overall_success=False" in text
    assert "AssertionError" in text
    assert "SKIPPED" in text  # ruff skipped


def test_format_code_qa_result_truncates_long_output(tmp_path: Path) -> None:
    long_stdout = "\n".join([f"line {i}" for i in range(100)])
    pytest_result = PytestResult(
        success=True,
        exit_code=0,
        elapsed_sec=0.1,
        passed=1,
        target_dir=tmp_path,
        stdout=long_stdout,
    )
    ruff_result = RuffResult(success=True, exit_code=0, elapsed_sec=0.0, target_dir=tmp_path)
    qa = CodeQAResult(success=True, elapsed_sec=0.1, pytest=pytest_result, ruff=ruff_result)

    text = format_code_qa_result_for_task(qa, max_lines=10)
    assert "앞부분 생략" in text
    # line 0 ~ line 89 는 잘렸고 line 90 ~ line 99 가 남아야 함
    assert "line 90" in text
    assert "line 99" in text


# ---------------------------------------------------------------------------
# summary_line — 콘솔 표기 검증
# ---------------------------------------------------------------------------


def test_pytest_result_summary_line_pass() -> None:
    r = PytestResult(success=True, exit_code=0, elapsed_sec=0.5, passed=5)
    line = r.summary_line()
    assert "PYTEST PASS" in line
    assert "passed=5" in line


def test_pytest_result_summary_line_fail() -> None:
    r = PytestResult(success=False, exit_code=1, elapsed_sec=0.5, passed=2, failed=1)
    line = r.summary_line()
    assert "PYTEST FAIL" in line
    assert "failed=1" in line


def test_pytest_result_summary_line_timeout() -> None:
    r = PytestResult(success=False, exit_code=-1, elapsed_sec=120.0)
    line = r.summary_line()
    assert "TIMEOUT" in line


def test_ruff_result_summary_line_skipped() -> None:
    r = RuffResult(success=True, exit_code=-2, elapsed_sec=0.0, skipped=True)
    line = r.summary_line()
    assert "SKIPPED" in line


def test_ruff_result_summary_line_clean() -> None:
    r = RuffResult(success=True, exit_code=0, elapsed_sec=0.1)
    line = r.summary_line()
    assert "CLEAN" in line


def test_ruff_result_summary_line_violations() -> None:
    r = RuffResult(success=False, exit_code=1, elapsed_sec=0.1, violations_count=3)
    line = r.summary_line()
    assert "VIOLATIONS" in line
    assert "3 위반" in line


def test_code_qa_result_summary_line() -> None:
    p = PytestResult(success=True, exit_code=0, elapsed_sec=0.5, passed=5)
    r = RuffResult(success=True, exit_code=0, elapsed_sec=0.1)
    qa = CodeQAResult(success=True, elapsed_sec=0.6, pytest=p, ruff=r)
    line = qa.summary_line()
    assert "CODE_QA PASS" in line
    assert "PYTEST PASS" in line
    assert "RUFF CLEAN" in line
