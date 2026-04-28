# -*- coding: utf-8 -*-
"""실행 기반 Functional Test executor (Phase 7 강화 — PR #43).

Functional Test Agent 가 사용하는 결정론적 도구. **subprocess 호출만 담당** — LLM 무관.

Code QA Executor (PR #42) 와의 차별점:
    - **Code QA Executor**: *기존 테스트 스위트* (pytest) 일괄 실행 → 정량 지표
    - **Functional Test Executor (본 모듈)**: 산출물 *script 자체* 를 *엣지케이스
      입력값* 으로 stdin 주입 실행 → 입력 → 동작 매핑 검증

Sandbox Runner 와의 차별점:
    - **Sandbox Runner**: *단일 실행* (PASS/FAIL/TIMEOUT). 정상 입력 가정.
    - **Functional Test Executor**: *복수 입력* 반복 실행. **엣지케이스 — 빈 입력,
      경계값, 유니코드, 매우 큰 값, 타입 불일치 등** 으로 robustness 검증.

타깃 한계:
    - **CLI/script 전용** — stdin 으로 입력 받고 stdout 으로 출력하는 프로그램.
    - GUI 프로그램 (tkinter / PyQt 등) 은 **모든 케이스가 타임아웃** 되어 실패
      판정. GUI 검증은 PR #44 (GUI Test Agent — pyautogui + Vision) 에서 별도 처리.

호출 측 통합 패턴::

    result = run_test_cases(target_script=Path("calculator.py"))
    if not result.success:
        # → Python Engineer 에게 "엣지케이스 X 에서 Y 발생" 재생성 지시
        ...
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional


_DEFAULT_PER_CASE_TIMEOUT = 10
_OUTPUT_TAIL_BYTES = 10_000


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    """단일 엣지케이스 정의.

    Attributes:
        name: 테스트 식별자 (예: ``"empty"``, ``"unicode_korean"``).
        stdin_input: 자식 프로세스에 stdin 으로 주입할 문자열. 줄바꿈 포함.
        description: 사람이 읽을 수 있는 설명 (보고서용).
        expected_exit_code: 기대 종료 코드. None 이면 *crash 아님* (exit_code != 0
            이지만 traceback 없으면 OK) 으로 관대하게 평가.
        expect_no_traceback: True 면 stderr 에 ``Traceback`` 등장 시 실패. 기본 True.
    """

    # pytest 가 ``Test`` 로 시작하는 클래스를 test class 로 수집하려 하지 않도록.
    # 본 클래스는 dataclass — pytest test 가 아님.
    __test__: ClassVar[bool] = False

    name: str
    stdin_input: str
    description: str = ""
    expected_exit_code: Optional[int] = None
    expect_no_traceback: bool = True


@dataclass
class TestCaseResult:
    """``TestCase`` 한 건의 실행 결과."""

    # pytest 수집 차단 (TestCase 와 동일 사유).
    __test__: ClassVar[bool] = False

    case_name: str
    description: str
    stdin_input: str
    exit_code: int
    elapsed_sec: float
    timed_out: bool
    stdout: str
    stderr: str
    passed: bool
    failure_reason: Optional[str] = None
    """실패 시 사람이 읽을 수 있는 진단 한 줄."""

    def summary_line(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        timeout_marker = " [TIMEOUT]" if self.timed_out else ""
        return (
            f"[{verdict}{timeout_marker}] {self.case_name} "
            f"(exit={self.exit_code}, {self.elapsed_sec:.2f}s)"
            + (f" — {self.failure_reason}" if self.failure_reason else "")
        )


@dataclass
class FunctionalTestResult:
    """``run_test_cases`` 의 합산 결과."""

    success: bool
    """모든 케이스 통과 여부."""

    elapsed_sec: float
    target_path: Optional[Path] = None
    case_results: list[TestCaseResult] = field(default_factory=list)
    error_message: Optional[str] = None
    """target 부재 / 실행 불가 등 *케이스 실행 자체* 가 막힌 사유."""

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.case_results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.case_results if not r.passed)

    @property
    def timeout_count(self) -> int:
        return sum(1 for r in self.case_results if r.timed_out)

    def summary_line(self) -> str:
        if self.error_message:
            return f"[FUNCTIONAL_TEST FAILED] {self.error_message} ({self.elapsed_sec:.2f}s)"
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"[FUNCTIONAL_TEST {verdict}] {self.passed_count}/{len(self.case_results)} 통과 "
            f"(timeout={self.timeout_count}, {self.elapsed_sec:.2f}s)"
        )


# ---------------------------------------------------------------------------
# 기본 엣지케이스 카탈로그
# ---------------------------------------------------------------------------


DEFAULT_EDGE_CASES: tuple[TestCase, ...] = (
    TestCase(
        name="empty_input",
        stdin_input="",
        description="빈 입력 (EOF 즉시) — input() 호출 시 EOFError 적절 처리 검증",
        expect_no_traceback=True,
    ),
    TestCase(
        name="whitespace_only",
        stdin_input="   \n",
        description="공백만 — strip() 후 빈 문자열 처리 검증",
    ),
    TestCase(
        name="zero",
        stdin_input="0\n",
        description="수치 0 — 0 으로 나눗셈 ZeroDivisionError 적절 처리 검증",
    ),
    TestCase(
        name="negative",
        stdin_input="-1\n",
        description="음수 — 음수 입력 처리 (sqrt 등은 ValueError) 검증",
    ),
    TestCase(
        name="very_large_number",
        stdin_input="9" * 100 + "\n",
        description="매우 큰 수 (100자리) — int 변환 OK 이지만 후속 연산 overflow 가능",
    ),
    TestCase(
        name="non_numeric",
        stdin_input="abc\n",
        description="타입 불일치 — int(input()) 에서 ValueError 적절 처리 검증",
    ),
    TestCase(
        name="unicode_korean",
        stdin_input="안녕하세요\n",
        description="한글 입력 — UTF-8 인코딩 처리 + ValueError 메시지 한글 보존",
    ),
    TestCase(
        name="unicode_emoji",
        stdin_input="🎉\n",
        description="이모지 (4-byte UTF-8) — 인코딩 경로 robustness",
    ),
    TestCase(
        name="multiline_long",
        stdin_input="\n".join(["1"] * 100) + "\n",
        description="100줄 입력 — 입력 EOF 후 종료 처리",
    ),
    TestCase(
        name="injection_like",
        stdin_input="'; DROP TABLE users; --\n",
        description="SQL injection 형태 — 단순 input() 에선 string 으로 처리, "
        "eval() 같은 안티패턴 노출 시 위험",
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
    """stderr 에 Python traceback 시그니처 포함 여부 검사."""
    if not stderr:
        return False
    return "Traceback (most recent call last)" in stderr


# ---------------------------------------------------------------------------
# 단일 케이스 실행
# ---------------------------------------------------------------------------


def _run_single_case(
    target_script: Path,
    case: TestCase,
    timeout_sec: int,
) -> TestCaseResult:
    """target_script 를 ``case.stdin_input`` 을 stdin 으로 주입해 한 번 실행."""
    started = time.time()
    cmd = [sys.executable, str(target_script)]

    timed_out = False
    stdout_text = ""
    stderr_text = ""
    exit_code = -1

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            input=case.stdin_input,
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

    # 합격/불합격 판정
    passed = True
    failure_reason: Optional[str] = None

    if timed_out:
        passed = False
        failure_reason = f"timeout {timeout_sec}s 초과 — 입력 대기 / 무한 루프 / GUI 가능성"
    elif case.expect_no_traceback and _has_traceback(stderr_text):
        passed = False
        # 마지막 traceback 라인 (예외 종류) 추출
        last_lines = [ln for ln in stderr_text.strip().splitlines() if ln.strip()]
        last_line = last_lines[-1] if last_lines else "(unknown)"
        failure_reason = f"unhandled exception: {last_line[:200]}"
    elif case.expected_exit_code is not None and exit_code != case.expected_exit_code:
        passed = False
        failure_reason = (
            f"exit_code 기대값 {case.expected_exit_code}, 실측 {exit_code}"
        )

    return TestCaseResult(
        case_name=case.name,
        description=case.description,
        stdin_input=case.stdin_input,
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


def run_test_cases(
    target_script: Path,
    cases: Optional[list[TestCase]] = None,
    per_case_timeout_sec: int = _DEFAULT_PER_CASE_TIMEOUT,
) -> FunctionalTestResult:
    """target_script 를 각 ``TestCase`` 의 stdin 으로 반복 실행.

    Args:
        target_script: 실행할 .py 파일 경로 (보통 워크플로우 산출 ``calculator.py``).
        cases: 적용할 케이스 리스트. None 이면 ``DEFAULT_EDGE_CASES`` 사용.
        per_case_timeout_sec: 케이스 1건당 timeout (초). 기본 10.

    Returns:
        FunctionalTestResult — 전 케이스 결과 + 합산 success.

    Note:
        타깃이 GUI 프로그램이면 모든 케이스가 timeout → 전부 실패. PR #44
        (GUI Test Agent) 의 영역이므로 본 executor 는 CLI/script 전용.
    """
    started = time.time()

    if cases is None:
        cases = list(DEFAULT_EDGE_CASES)

    if not target_script.exists():
        return FunctionalTestResult(
            success=False,
            elapsed_sec=time.time() - started,
            target_path=target_script,
            error_message=f"target_script 부재: {target_script}",
        )

    case_results: list[TestCaseResult] = []
    for case in cases:
        case_results.append(_run_single_case(target_script, case, per_case_timeout_sec))

    elapsed = time.time() - started
    overall_success = all(r.passed for r in case_results) and len(case_results) > 0

    return FunctionalTestResult(
        success=overall_success,
        elapsed_sec=elapsed,
        target_path=target_script,
        case_results=case_results,
    )


# ---------------------------------------------------------------------------
# 헬퍼 — Functional Test Agent Task description 직렬화
# ---------------------------------------------------------------------------


def format_functional_test_result_for_task(
    result: FunctionalTestResult,
    *,
    max_lines_per_case: int = 10,
) -> str:
    """``FunctionalTestResult`` 를 Agent Task description 본문에 직렬화.

    각 케이스의 stdout/stderr 를 마지막 ``max_lines_per_case`` 줄로 절단
    (LLM 토큰 보호).
    """

    def _tail(text: str) -> str:
        if not text:
            return "(empty)"
        lines = text.splitlines()
        if len(lines) <= max_lines_per_case:
            return text.rstrip()
        return "... (앞부분 생략) ...\n" + "\n".join(lines[-max_lines_per_case:])

    parts: list[str] = []
    parts.append(
        f"# Functional Test Result — overall_success={result.success}, "
        f"elapsed={result.elapsed_sec:.2f}s"
    )
    parts.append(f"target: {result.target_path}")
    parts.append(
        f"summary: {result.passed_count}/{len(result.case_results)} 통과, "
        f"timeout={result.timeout_count}"
    )
    if result.error_message:
        parts.append(f"\nerror_message: {result.error_message}")
        return "\n".join(parts)

    parts.append("")
    for r in result.case_results:
        parts.append(f"## {r.case_name} — {'PASS' if r.passed else 'FAIL'}")
        parts.append(f"  설명: {r.description}")
        parts.append(f"  stdin_input: {r.stdin_input!r}")
        parts.append(f"  exit_code: {r.exit_code}, elapsed: {r.elapsed_sec:.2f}s, timed_out: {r.timed_out}")
        if r.failure_reason:
            parts.append(f"  failure_reason: {r.failure_reason}")
        parts.append(f"  --- stdout (마지막 {max_lines_per_case}줄) ---")
        parts.append(_tail(r.stdout))
        parts.append(f"  --- stderr (마지막 {max_lines_per_case}줄) ---")
        parts.append(_tail(r.stderr))
        parts.append("")

    return "\n".join(parts)
