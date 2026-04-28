# -*- coding: utf-8 -*-
"""Robustness 부하 테스트 executor (Phase 7 — PR #46).

Robustness Tester 가 사용하는 결정론적 도구. 산출물 (calculator.py 등) 을
**부하 시나리오** (대량 입력 / 반복 실행 / 자원 고갈 시도) 로 실행해 견고성
한계를 자동 측정.

Functional Test Executor (PR #43) 와의 차별점:
    - **Functional Test**: *다양한 입력* (empty/unicode/boundary) → 입력 → 결함 매핑
    - **Robustness (본 모듈)**: *부하/규모* (1MB 입력 / 100회 반복 / 지연 입력)
      → 자원 한계 / 누수 / 비결정성 검증

시나리오 카탈로그:
    - **large_input_1mb**: 1MB stdin (메모리/스트림 처리)
    - **repeated_lines_10k**: 10000 줄 입력 (파싱 루프 견고성)
    - **rapid_repeat_5x**: 같은 타깃 5회 연속 실행 (idempotency / leak)
    - **slow_input_drip**: 입력을 천천히 (deadlock 가능성)
    - **interrupted_input**: 입력 중간 EOF (부분 입력 처리)

Sandbox Runner / Functional Test 와의 통합 가능성:
    - 본 모듈은 *별도 도구* 로 운영 — 한 PR 에 모두 통합하지 않음
    - 향후 PR #48 의 iterative_loop 가 세 도구 (code_qa / functional_test /
      robustness) 결과를 합산해 PASS/FAIL 결정
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional


_DEFAULT_PER_SCENARIO_TIMEOUT = 30
_OUTPUT_TAIL_BYTES = 5_000


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class RobustnessScenario:
    """단일 부하 시나리오 정의."""

    __test__: ClassVar[bool] = False  # pytest 수집 차단

    name: str
    description: str
    stdin_input: str
    repeat_count: int = 1
    """동일 시나리오 반복 횟수 (rapid_repeat 용)."""
    expected_no_traceback: bool = True
    expected_max_elapsed_sec: Optional[float] = None
    """기대 최대 실행 시간. 초과 시 *성능 결함* 으로 분류."""


@dataclass
class ScenarioResult:
    """``RobustnessScenario`` 단일 실행 결과."""

    __test__: ClassVar[bool] = False

    scenario_name: str
    description: str
    iteration: int
    """repeat_count > 1 일 때 1..N 반복 인덱스."""
    exit_code: int
    elapsed_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    passed: bool
    failure_reason: Optional[str] = None

    def summary_line(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        timeout_marker = " [TIMEOUT]" if self.timed_out else ""
        iter_marker = f" iter={self.iteration}" if self.iteration > 1 else ""
        return (
            f"[{verdict}{timeout_marker}] {self.scenario_name}{iter_marker} "
            f"(exit={self.exit_code}, {self.elapsed_sec:.2f}s)"
            + (f" — {self.failure_reason}" if self.failure_reason else "")
        )


@dataclass
class RobustnessResult:
    """``run_robustness_scenarios`` 의 합산 결과."""

    __test__: ClassVar[bool] = False

    success: bool
    elapsed_sec: float
    target_path: Optional[Path] = None
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.scenario_results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.scenario_results if not r.passed)

    @property
    def timeout_count(self) -> int:
        return sum(1 for r in self.scenario_results if r.timed_out)

    def summary_line(self) -> str:
        if self.error_message:
            return f"[ROBUSTNESS FAILED] {self.error_message} ({self.elapsed_sec:.2f}s)"
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"[ROBUSTNESS {verdict}] {self.passed_count}/{len(self.scenario_results)} 통과 "
            f"(timeout={self.timeout_count}, {self.elapsed_sec:.2f}s)"
        )


# ---------------------------------------------------------------------------
# 기본 시나리오 카탈로그
# ---------------------------------------------------------------------------


DEFAULT_SCENARIOS: tuple[RobustnessScenario, ...] = (
    RobustnessScenario(
        name="large_input_1mb",
        description="1MB stdin — 메모리/스트림 견고성",
        stdin_input="x" * (1024 * 1024),
        expected_max_elapsed_sec=10.0,
    ),
    RobustnessScenario(
        name="repeated_lines_10k",
        description="10000 줄 입력 — 파싱 루프 견고성",
        stdin_input=("test\n" * 10_000),
        expected_max_elapsed_sec=10.0,
    ),
    RobustnessScenario(
        name="rapid_repeat_5x",
        description="같은 타깃 5회 연속 실행 — idempotency / leak 검증",
        stdin_input="hello\n",
        repeat_count=5,
        expected_max_elapsed_sec=5.0,
    ),
    RobustnessScenario(
        name="binary_garbage",
        description="non-UTF-8 바이트 시퀀스 — 인코딩 에러 graceful 처리",
        # \\x00 \\xff \\xfe 등 — UTF-8 으로 디코드 시 에러 가능성
        stdin_input="\x00\xff\xfe binary garbage \x80\x81\x82\n",
        expected_no_traceback=True,
    ),
    RobustnessScenario(
        name="numeric_overflow",
        description="매우 큰 수치 (1000자리) — int 산술 견고성",
        stdin_input="9" * 1000 + "\n",
        expected_max_elapsed_sec=5.0,
    ),
)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _tail_text(text: str, limit: int = _OUTPUT_TAIL_BYTES) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"...(truncated {len(text) - limit} bytes)...\n" + text[-limit:]


def _has_traceback(stderr: str) -> bool:
    if not stderr:
        return False
    return "Traceback (most recent call last)" in stderr


# ---------------------------------------------------------------------------
# 단일 시나리오 실행 (1 회)
# ---------------------------------------------------------------------------


def _run_single_iteration(
    target_script: Path,
    scenario: RobustnessScenario,
    iteration: int,
    timeout_sec: int,
) -> ScenarioResult:
    started = time.time()
    cmd = [sys.executable, str(target_script)]

    timed_out = False
    stdout_text = ""
    stderr_text = ""
    exit_code = -1

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            input=scenario.stdin_input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        exit_code = proc.returncode
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        timed_out = True
        exit_code = -1
        stdout_text = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

    elapsed = time.time() - started

    passed = True
    failure_reason: Optional[str] = None

    if timed_out:
        passed = False
        failure_reason = f"timeout {timeout_sec}s 초과 — 부하 처리 한계 또는 deadlock"
    elif scenario.expected_no_traceback and _has_traceback(stderr_text):
        passed = False
        last_lines = [ln for ln in stderr_text.strip().splitlines() if ln.strip()]
        last_line = last_lines[-1] if last_lines else "(unknown)"
        failure_reason = f"unhandled exception: {last_line[:200]}"
    elif (
        scenario.expected_max_elapsed_sec is not None
        and elapsed > scenario.expected_max_elapsed_sec
    ):
        passed = False
        failure_reason = (
            f"성능 한계 초과 — 기대 ≤{scenario.expected_max_elapsed_sec}s, "
            f"실측 {elapsed:.2f}s"
        )

    return ScenarioResult(
        scenario_name=scenario.name,
        description=scenario.description,
        iteration=iteration,
        exit_code=exit_code,
        elapsed_sec=elapsed,
        timed_out=timed_out,
        stdout=_tail_text(stdout_text),
        stderr=_tail_text(stderr_text),
        passed=passed,
        failure_reason=failure_reason,
    )


# ---------------------------------------------------------------------------
# 묶음 실행
# ---------------------------------------------------------------------------


def run_robustness_scenarios(
    target_script: Path,
    scenarios: Optional[list[RobustnessScenario]] = None,
    per_scenario_timeout_sec: int = _DEFAULT_PER_SCENARIO_TIMEOUT,
) -> RobustnessResult:
    """target_script 에 부하 시나리오 묶음 적용.

    Args:
        target_script: 실행할 .py 파일.
        scenarios: 적용할 시나리오 리스트. None 이면 ``DEFAULT_SCENARIOS``.
        per_scenario_timeout_sec: 시나리오 1건 1회당 timeout (초). 기본 30.

    Returns:
        RobustnessResult — 전 시나리오·반복 결과 + 합산 success.

    Note:
        ``RobustnessScenario.repeat_count > 1`` 인 시나리오는 N 회 반복되며
        각 반복이 별도 ``ScenarioResult`` 항목으로 기록됨.
    """
    started = time.time()

    if scenarios is None:
        scenarios = list(DEFAULT_SCENARIOS)

    if not target_script.exists():
        return RobustnessResult(
            success=False,
            elapsed_sec=time.time() - started,
            target_path=target_script,
            error_message=f"target_script 부재: {target_script}",
        )

    scenario_results: list[ScenarioResult] = []
    for scenario in scenarios:
        for i in range(1, scenario.repeat_count + 1):
            scenario_results.append(
                _run_single_iteration(
                    target_script, scenario, i, per_scenario_timeout_sec
                )
            )

    elapsed = time.time() - started
    overall_success = (
        all(r.passed for r in scenario_results) and len(scenario_results) > 0
    )

    return RobustnessResult(
        success=overall_success,
        elapsed_sec=elapsed,
        target_path=target_script,
        scenario_results=scenario_results,
    )


# ---------------------------------------------------------------------------
# 헬퍼 — Robustness Tester Task description 직렬화
# ---------------------------------------------------------------------------


def format_robustness_result_for_task(
    result: RobustnessResult,
    *,
    max_lines_per_result: int = 5,
) -> str:
    """``RobustnessResult`` 를 Agent Task description 본문에 직렬화."""

    def _tail(text: str) -> str:
        if not text:
            return "(empty)"
        lines = text.splitlines()
        if len(lines) <= max_lines_per_result:
            return text.rstrip()
        return "... (앞부분 생략) ...\n" + "\n".join(lines[-max_lines_per_result:])

    parts: list[str] = []
    parts.append(
        f"# Robustness Result — overall_success={result.success}, "
        f"elapsed={result.elapsed_sec:.2f}s"
    )
    parts.append(f"target: {result.target_path}")
    parts.append(
        f"summary: {result.passed_count}/{len(result.scenario_results)} 통과, "
        f"timeout={result.timeout_count}"
    )
    if result.error_message:
        parts.append(f"error_message: {result.error_message}")
        return "\n".join(parts)

    parts.append("")
    for r in result.scenario_results:
        parts.append(f"## {r.scenario_name} (iter={r.iteration}) — {'PASS' if r.passed else 'FAIL'}")
        parts.append(f"  설명: {r.description}")
        parts.append(
            f"  exit_code={r.exit_code}, elapsed={r.elapsed_sec:.2f}s, timed_out={r.timed_out}"
        )
        if r.failure_reason:
            parts.append(f"  failure_reason: {r.failure_reason}")
        parts.append(f"  --- stderr (마지막 {max_lines_per_result}줄) ---")
        parts.append(_tail(r.stderr))
        parts.append("")

    return "\n".join(parts)
