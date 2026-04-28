# -*- coding: utf-8 -*-
"""src/agents/qa/robustness_executor.py 회귀 방지 테스트 (PR #46)."""

from __future__ import annotations

from pathlib import Path

from src.agents.qa.robustness_executor import (
    DEFAULT_SCENARIOS,
    RobustnessResult,
    RobustnessScenario,
    ScenarioResult,
    _has_traceback,
    _tail_text,
    format_robustness_result_for_task,
    run_robustness_scenarios,
)


# 순수 헬퍼 ----------------------------------------------------------------


def test_tail_text_short_preserved() -> None:
    assert _tail_text("hello") == "hello"


def test_tail_text_truncates_long() -> None:
    long = "x" * 10_000
    out = _tail_text(long, limit=2_000)
    assert out.startswith("...(truncated 8000 bytes)...")
    assert out.endswith("x" * 2_000)


def test_has_traceback_detects() -> None:
    assert _has_traceback("Traceback (most recent call last):\nValueError") is True
    assert _has_traceback("normal output") is False
    assert _has_traceback("") is False


# DEFAULT_SCENARIOS 정합성 -------------------------------------------------


def test_default_scenarios_has_expected_categories() -> None:
    names = {s.name for s in DEFAULT_SCENARIOS}
    expected = {
        "large_input_1mb",
        "repeated_lines_10k",
        "rapid_repeat_5x",
        "binary_garbage",
        "numeric_overflow",
    }
    missing = expected - names
    assert not missing, f"DEFAULT_SCENARIOS 누락: {missing}"


def test_default_scenarios_have_descriptions() -> None:
    for s in DEFAULT_SCENARIOS:
        assert s.description, f"{s.name} 설명 비어 있음"


def test_rapid_repeat_5x_has_repeat_count_5() -> None:
    rapid = next(s for s in DEFAULT_SCENARIOS if s.name == "rapid_repeat_5x")
    assert rapid.repeat_count == 5


# run_robustness_scenarios — 통합 검증 ---------------------------------------


def _write_target(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "target.py"
    target.write_text(body, encoding="utf-8")
    return target


def test_target_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nope.py"
    result = run_robustness_scenarios(nonexistent, scenarios=[])
    assert result.success is False
    assert "부재" in (result.error_message or "")


def test_robust_target_passes_small_scenarios(tmp_path: Path) -> None:
    body = """\
import sys
data = sys.stdin.read()
print(f"len={len(data)}")
"""
    target = _write_target(tmp_path, body)
    scenarios = [
        RobustnessScenario(
            name="tiny_input",
            description="작은 입력",
            stdin_input="hello\n",
            expected_max_elapsed_sec=10.0,
        ),
    ]
    result = run_robustness_scenarios(target, scenarios=scenarios, per_scenario_timeout_sec=10)
    assert result.success is True
    assert result.passed_count == 1


def test_repeat_count_creates_multiple_results(tmp_path: Path) -> None:
    body = "import sys; sys.stdin.read(); print('ok')"
    target = _write_target(tmp_path, body)
    scenarios = [
        RobustnessScenario(
            name="repeat3",
            description="3회 반복",
            stdin_input="x\n",
            repeat_count=3,
        ),
    ]
    result = run_robustness_scenarios(target, scenarios=scenarios, per_scenario_timeout_sec=10)
    assert len(result.scenario_results) == 3
    iterations = [r.iteration for r in result.scenario_results]
    assert iterations == [1, 2, 3]


def test_crash_target_marks_failure(tmp_path: Path) -> None:
    body = "import sys; sys.stdin.read(); raise RuntimeError('boom')"
    target = _write_target(tmp_path, body)
    scenarios = [
        RobustnessScenario(
            name="crash",
            description="강제 crash",
            stdin_input="x\n",
        ),
    ]
    result = run_robustness_scenarios(target, scenarios=scenarios, per_scenario_timeout_sec=5)
    assert result.success is False
    assert "exception" in (result.scenario_results[0].failure_reason or "").lower()


def test_performance_limit_violation(tmp_path: Path) -> None:
    body = "import sys, time; sys.stdin.read(); time.sleep(0.5); print('ok')"
    target = _write_target(tmp_path, body)
    scenarios = [
        RobustnessScenario(
            name="perf",
            description="기대시간 초과",
            stdin_input="x\n",
            expected_max_elapsed_sec=0.1,  # 0.5s sleep > 0.1s 기대
        ),
    ]
    result = run_robustness_scenarios(target, scenarios=scenarios, per_scenario_timeout_sec=5)
    assert result.success is False
    assert "성능 한계 초과" in (result.scenario_results[0].failure_reason or "")


def test_timeout_marks_failure(tmp_path: Path) -> None:
    body = "import sys; sys.stdin.read(); \nwhile True: pass"
    target = _write_target(tmp_path, body)
    scenarios = [
        RobustnessScenario(
            name="hang",
            description="무한 루프",
            stdin_input="x\n",
        ),
    ]
    result = run_robustness_scenarios(target, scenarios=scenarios, per_scenario_timeout_sec=1)
    assert result.success is False
    assert result.scenario_results[0].timed_out is True
    assert "timeout" in (result.scenario_results[0].failure_reason or "").lower()


# format_robustness_result_for_task ------------------------------------------


def test_format_includes_summary(tmp_path: Path) -> None:
    sr = ScenarioResult(
        scenario_name="x",
        description="설명",
        iteration=1,
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="ok",
        stderr="",
        passed=True,
    )
    result = RobustnessResult(
        success=True,
        elapsed_sec=0.5,
        target_path=tmp_path / "t.py",
        scenario_results=[sr],
    )
    text = format_robustness_result_for_task(result)
    assert "Robustness Result" in text
    assert "1/1 통과" in text


def test_format_handles_error_message(tmp_path: Path) -> None:
    result = RobustnessResult(
        success=False,
        elapsed_sec=0.01,
        target_path=tmp_path / "missing.py",
        error_message="target_script 부재: missing.py",
    )
    text = format_robustness_result_for_task(result)
    assert "부재" in text


# summary_line ---------------------------------------------------------------


def test_scenario_result_summary_line_pass() -> None:
    sr = ScenarioResult(
        scenario_name="ok",
        description="",
        iteration=1,
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="",
        passed=True,
    )
    assert "PASS" in sr.summary_line()


def test_scenario_result_summary_line_iter_marker() -> None:
    sr = ScenarioResult(
        scenario_name="rapid",
        description="",
        iteration=3,
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="",
        passed=True,
    )
    assert "iter=3" in sr.summary_line()


def test_robustness_result_summary_line_pass() -> None:
    sr = ScenarioResult(
        scenario_name="x",
        description="",
        iteration=1,
        exit_code=0,
        elapsed_sec=0.1,
        timed_out=False,
        stdout="",
        stderr="",
        passed=True,
    )
    result = RobustnessResult(success=True, elapsed_sec=0.5, scenario_results=[sr] * 3)
    assert "ROBUSTNESS PASS" in result.summary_line()
    assert "3/3" in result.summary_line()
