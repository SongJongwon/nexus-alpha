# -*- coding: utf-8 -*-
"""실행 기반 Code QA executor (Phase 7 강화 — PR #42).

Code QA Agent 가 사용하는 결정론적 도구. **subprocess 호출만 담당** — LLM 무관.

`build_executor.py` (PR #36) / `distribution_executor.py` (PR #39) 와 동일한 설계
패턴: ``execute_X(...) -> Result(success, exit_code, elapsed_sec, ...)``.

기능:
    - **pytest 실행** (필수) — 통과/실패/오류/skip 카운트 파싱
    - **ruff lint** (선택) — 미설치 시 graceful skip (success=True, skipped 표기)
    - **묶음 실행** (`run_code_qa`) — 두 가지 결과를 하나로 합산

Sandbox Runner (`src/agents/operations/sandbox_runner.py`) 와의 차별점:
    - Sandbox Runner: *단일 코드 문자열* 또는 *멀티파일 패키지* 한 번 실행 → 동작 검증
    - Code QA Executor: *기존 디렉터리* 의 **테스트 스위트** 일괄 실행 → 정량 품질 지표

호출 측 (Code QA Agent / iterative_loop) 통합 패턴::

    qa_result = run_code_qa(target_dir=workflow_dir, timeout_sec=180)
    if not qa_result.success:
        # → Python Engineer 에게 재생성 지시 (PR #48 자동 피드백 루프)
        ...
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_DEFAULT_PYTEST_TIMEOUT = 120
_DEFAULT_RUFF_TIMEOUT = 60
_DEFAULT_CODE_QA_TIMEOUT = 180
_OUTPUT_TAIL_BYTES = 50_000


# ---------------------------------------------------------------------------
# 결과 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class PytestResult:
    """``pytest`` 실행 결과 — graceful failure 모델."""

    success: bool
    """모든 테스트 통과 여부 (pytest exit_code == 0). 단, 테스트 0개여도 5 (no tests collected)."""

    exit_code: int
    """pytest 종료 코드. -1=timeout, -2=pytest 미설치, 기타=pytest exit semantics."""

    elapsed_sec: float
    """소요 시간 (실측)."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    """summary 라인 (예: ``5 passed, 2 failed in 0.42s``) 에서 파싱."""

    target_dir: Optional[Path] = None
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None
    """failure 시 사람이 읽을 수 있는 진단 메시지."""

    def summary_line(self) -> str:
        if self.exit_code == -2:
            return f"[PYTEST SKIPPED] pytest 미설치 (exit=-2, {self.elapsed_sec:.2f}s)"
        if self.exit_code == -1:
            return f"[PYTEST TIMEOUT] timeout exceeded ({self.elapsed_sec:.2f}s)"
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"[PYTEST {verdict}] passed={self.passed} failed={self.failed} "
            f"errors={self.errors} skipped={self.skipped} "
            f"(exit={self.exit_code}, {self.elapsed_sec:.2f}s)"
        )


@dataclass
class RuffResult:
    """``ruff check`` 실행 결과 — graceful failure 모델."""

    success: bool
    """위반 0건 여부 (ruff exit_code == 0). ruff 미설치 시 success=True (skipped)."""

    exit_code: int
    """ruff 종료 코드. -1=timeout, -2=ruff 미설치, 0=clean, 1=violations."""

    elapsed_sec: float

    skipped: bool = False
    """ruff 미설치 또는 명시적 skip — success 와 무관한 *집행 안 됨* 표기."""

    violations_count: int = 0
    violations_by_rule: dict[str, int] = field(default_factory=dict)
    """rule code (예: ``E501``, ``F401``) 별 위반 횟수."""

    target_dir: Optional[Path] = None
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None

    def summary_line(self) -> str:
        if self.skipped:
            return f"[RUFF SKIPPED] ruff 미설치 (success={self.success}, {self.elapsed_sec:.2f}s)"
        if self.exit_code == -1:
            return f"[RUFF TIMEOUT] ({self.elapsed_sec:.2f}s)"
        verdict = "CLEAN" if self.success else "VIOLATIONS"
        return (
            f"[RUFF {verdict}] {self.violations_count} 위반 "
            f"(exit={self.exit_code}, {self.elapsed_sec:.2f}s)"
        )


@dataclass
class CodeQAResult:
    """``run_code_qa`` 의 합산 결과 — pytest + ruff."""

    success: bool
    """*모든 단계가 성공/skipped* — pytest.success AND (ruff.success OR ruff.skipped)."""

    elapsed_sec: float

    pytest: PytestResult
    ruff: RuffResult

    def summary_line(self) -> str:
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"[CODE_QA {verdict}] {self.pytest.summary_line()} | "
            f"{self.ruff.summary_line()} | total={self.elapsed_sec:.2f}s"
        )


# ---------------------------------------------------------------------------
# 유틸 — 공통 헬퍼
# ---------------------------------------------------------------------------


def _resolve_executable(name: str) -> Optional[Path]:
    """주어진 도구 이름을 PATH 에서 탐색. 미설치 시 None.

    Windows 환경에선 ``ruff.exe`` / ``pytest.exe`` 가 자동 탐지됨.
    """
    found = shutil.which(name)
    return Path(found) if found else None


def _tail_text(text: str, limit: int = _OUTPUT_TAIL_BYTES) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"...(truncated {len(text) - limit} bytes)...\n" + text[-limit:]


# ---------------------------------------------------------------------------
# pytest summary 파싱
# ---------------------------------------------------------------------------


# pytest 8/9 대표 패턴:
#   "===== 5 passed in 0.42s ====="
#   "===== 1 failed, 4 passed in 0.51s ====="
#   "===== 2 errors in 0.18s ====="
#   "===== 3 passed, 1 skipped in 0.22s ====="
# 수치를 한꺼번에 추출하는 다중 키워드 정규식.
_PYTEST_SUMMARY_KEYWORDS = ("passed", "failed", "error", "errors", "skipped")
_PYTEST_NUMBER_KW_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)\b", re.IGNORECASE)


def _parse_pytest_summary(stdout: str) -> tuple[int, int, int, int]:
    """pytest stdout 의 마지막 summary 라인에서 (passed, failed, errors, skipped) 추출.

    summary 가 stdout 끝에 ``===== ... =====`` 형식으로 출력되므로
    *역순* 으로 줄을 훑으며 첫 번째 매칭 라인을 사용.

    Returns:
        (passed, failed, errors, skipped) — 매칭 실패 시 모두 0.
    """
    if not stdout:
        return 0, 0, 0, 0

    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("="):
            continue
        # summary 라인은 양 끝에 ``=`` 가 둘러쌈
        matches = _PYTEST_NUMBER_KW_RE.findall(line)
        if not matches:
            continue
        passed = failed = errors = skipped = 0
        for count_str, kw in matches:
            count = int(count_str)
            kw_lower = kw.lower()
            if kw_lower == "passed":
                passed = count
            elif kw_lower == "failed":
                failed = count
            elif kw_lower in ("error", "errors"):
                errors = count
            elif kw_lower == "skipped":
                skipped = count
        return passed, failed, errors, skipped

    return 0, 0, 0, 0


# ---------------------------------------------------------------------------
# ruff 출력 파싱
# ---------------------------------------------------------------------------


# ruff check 기본 출력 패턴 (text format):
#   "src/foo.py:12:5: E501 line too long (105 > 100 characters)"
# rule code 는 첫 ``: <CODE> `` 위치.
_RUFF_VIOLATION_RE = re.compile(r":\s*([A-Z]+\d+)\s")


def _parse_ruff_violations(stdout: str) -> tuple[int, dict[str, int]]:
    """ruff check stdout 에서 (총 위반 수, rule code 별 위반 수) 추출.

    각 위반은 한 줄. ``: <CODE> `` 패턴으로 rule code 추출. 매칭 안 되는
    줄 (요약 라인 등) 은 무시.
    """
    if not stdout:
        return 0, {}

    by_rule: dict[str, int] = {}
    total = 0
    for line in stdout.splitlines():
        m = _RUFF_VIOLATION_RE.search(line)
        if m:
            rule = m.group(1)
            by_rule[rule] = by_rule.get(rule, 0) + 1
            total += 1
    return total, by_rule


# ---------------------------------------------------------------------------
# pytest 실행자
# ---------------------------------------------------------------------------


def run_pytest(
    target_dir: Path,
    timeout_sec: int = _DEFAULT_PYTEST_TIMEOUT,
    extra_args: Optional[list[str]] = None,
) -> PytestResult:
    """``python -m pytest <target_dir>`` 호출.

    ``sys.executable`` 기반으로 pytest 모듈을 호출 — venv 일관성 보장.
    pytest 미설치 (ImportError) 시 exit_code=-2 로 graceful return.

    Args:
        target_dir: 테스트 디렉터리 (보통 워크플로우 산출 dir 또는 ``src/tests``).
        timeout_sec: subprocess 타임아웃 (초). 기본 120.
        extra_args: pytest 추가 인자 (예: ``["-x", "-q"]``).

    Returns:
        PytestResult — passed/failed/errors/skipped 카운트 + stdout/stderr.
    """
    started = time.time()

    if not target_dir.exists():
        return PytestResult(
            success=False,
            exit_code=-3,
            elapsed_sec=time.time() - started,
            target_dir=target_dir,
            error_message=f"target_dir 부재: {target_dir}",
        )

    cmd: list[str] = [sys.executable, "-m", "pytest", str(target_dir)]
    if extra_args:
        cmd.extend(extra_args)

    try:
        proc = subprocess.run(  # noqa: S603 (의도적 subprocess 호출)
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        exit_code = proc.returncode
        stdout = _tail_text(proc.stdout)
        stderr = _tail_text(proc.stderr)
    except subprocess.TimeoutExpired as e:
        return PytestResult(
            success=False,
            exit_code=-1,
            elapsed_sec=time.time() - started,
            target_dir=target_dir,
            command=cmd,
            stdout=_tail_text(e.stdout.decode("utf-8", errors="replace") if e.stdout else ""),
            stderr=_tail_text(e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
            error_message=f"pytest timeout — {timeout_sec}s 초과.",
        )
    except FileNotFoundError as e:
        return PytestResult(
            success=False,
            exit_code=-2,
            elapsed_sec=time.time() - started,
            target_dir=target_dir,
            command=cmd,
            error_message=f"pytest 모듈 실행 실패 (FileNotFoundError): {e}",
        )

    # pytest exit code 는 0=all passed, 1=failures, 2=interrupted, 3=internal,
    # 4=usage, 5=no tests collected. 우리는 0 만 success 로 처리.
    elapsed = time.time() - started
    passed, failed, errors, skipped = _parse_pytest_summary(proc.stdout or "")

    # exit_code 5 (no tests collected) 도 *결함* 으로 간주 — Code QA 의 책무는
    # 테스트 존재성 검증이기도 함.
    success = exit_code == 0 and (passed + failed + errors + skipped) > 0

    return PytestResult(
        success=success,
        exit_code=exit_code,
        elapsed_sec=elapsed,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        target_dir=target_dir,
        command=cmd,
        stdout=stdout,
        stderr=stderr,
        error_message=None if success else f"pytest exit_code={exit_code} (non-zero or no tests).",
    )


# ---------------------------------------------------------------------------
# ruff 실행자
# ---------------------------------------------------------------------------


def run_ruff(
    target_dir: Path,
    timeout_sec: int = _DEFAULT_RUFF_TIMEOUT,
    extra_args: Optional[list[str]] = None,
) -> RuffResult:
    """``ruff check <target_dir>`` 호출.

    ruff 미설치 시 graceful skip (success=True, skipped=True). 이는
    *PR #42 의 의도된 동작* — ruff 는 optional 도구로 취급.

    Args:
        target_dir: lint 대상 디렉터리.
        timeout_sec: subprocess 타임아웃 (초). 기본 60.
        extra_args: ruff 추가 인자.

    Returns:
        RuffResult — violations_count + violations_by_rule + stdout/stderr.
    """
    started = time.time()

    ruff_exe = _resolve_executable("ruff")
    if ruff_exe is None:
        return RuffResult(
            success=True,  # missing tool = optional skip, not a failure
            exit_code=-2,
            elapsed_sec=time.time() - started,
            skipped=True,
            target_dir=target_dir,
            error_message="ruff 미설치 — `pip install ruff` 시 활성. 본 단계는 skip.",
        )

    if not target_dir.exists():
        return RuffResult(
            success=False,
            exit_code=-3,
            elapsed_sec=time.time() - started,
            target_dir=target_dir,
            error_message=f"target_dir 부재: {target_dir}",
        )

    cmd: list[str] = [str(ruff_exe), "check", str(target_dir)]
    if extra_args:
        cmd.extend(extra_args)

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        exit_code = proc.returncode
        stdout = _tail_text(proc.stdout)
        stderr = _tail_text(proc.stderr)
    except subprocess.TimeoutExpired as e:
        return RuffResult(
            success=False,
            exit_code=-1,
            elapsed_sec=time.time() - started,
            target_dir=target_dir,
            command=cmd,
            stdout=_tail_text(e.stdout.decode("utf-8", errors="replace") if e.stdout else ""),
            stderr=_tail_text(e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
            error_message=f"ruff timeout — {timeout_sec}s 초과.",
        )

    elapsed = time.time() - started
    violations_count, by_rule = _parse_ruff_violations(proc.stdout or "")
    success = exit_code == 0  # ruff exit 0 = clean, 1 = violations

    return RuffResult(
        success=success,
        exit_code=exit_code,
        elapsed_sec=elapsed,
        violations_count=violations_count,
        violations_by_rule=by_rule,
        target_dir=target_dir,
        command=cmd,
        stdout=stdout,
        stderr=stderr,
        error_message=None if success else f"ruff {violations_count} 위반.",
    )


# ---------------------------------------------------------------------------
# 묶음 실행자 — pytest + ruff 합산
# ---------------------------------------------------------------------------


def run_code_qa(
    target_dir: Path,
    timeout_sec: int = _DEFAULT_CODE_QA_TIMEOUT,
    skip_ruff: bool = False,
) -> CodeQAResult:
    """pytest + ruff 를 순차 실행하고 합산 결과 반환.

    개별 도구의 timeout 은 자동 분배 (pytest 2/3, ruff 1/3).

    Args:
        target_dir: 테스트 + lint 대상 디렉터리.
        timeout_sec: 묶음 전체 timeout. 기본 180. 개별 분배:
            - pytest: ``timeout_sec * 2/3``
            - ruff: ``timeout_sec * 1/3``
        skip_ruff: True 면 ruff 단계 통째로 skip (테스트 환경 등).

    Returns:
        CodeQAResult — pytest + ruff 결과 + 종합 success.
    """
    started = time.time()

    pytest_timeout = max(int(timeout_sec * 2 / 3), 10)
    ruff_timeout = max(int(timeout_sec * 1 / 3), 5)

    pytest_result = run_pytest(target_dir, timeout_sec=pytest_timeout)

    if skip_ruff:
        ruff_result = RuffResult(
            success=True,
            exit_code=0,
            elapsed_sec=0.0,
            skipped=True,
            target_dir=target_dir,
            error_message="skip_ruff=True — 명시적 skip.",
        )
    else:
        ruff_result = run_ruff(target_dir, timeout_sec=ruff_timeout)

    elapsed = time.time() - started
    overall_success = pytest_result.success and (ruff_result.success or ruff_result.skipped)

    return CodeQAResult(
        success=overall_success,
        elapsed_sec=elapsed,
        pytest=pytest_result,
        ruff=ruff_result,
    )


# ---------------------------------------------------------------------------
# 헬퍼 — Code QA Agent Task description 직렬화
# ---------------------------------------------------------------------------


def format_code_qa_result_for_task(result: CodeQAResult, *, max_lines: int = 30) -> str:
    """``CodeQAResult`` 를 Code QA Agent Task description 본문에 끼워 넣기 좋은 텍스트로 변환.

    너무 긴 stdout/stderr 는 마지막 ``max_lines`` 줄로 잘라낸다 (LLM 토큰 보호).
    """

    def _tail(text: str) -> str:
        if not text:
            return "(empty)"
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text.rstrip()
        return "... (앞부분 생략) ...\n" + "\n".join(lines[-max_lines:])

    p = result.pytest
    r = result.ruff

    return (
        f"# Code QA Result — overall_success={result.success}, elapsed={result.elapsed_sec:.2f}s\n"
        f"\n"
        f"## pytest\n"
        f"  {p.summary_line()}\n"
        f"  passed={p.passed} failed={p.failed} errors={p.errors} skipped={p.skipped}\n"
        f"  --- stdout (마지막 {max_lines}줄) ---\n{_tail(p.stdout)}\n"
        f"  --- stderr (마지막 {max_lines}줄) ---\n{_tail(p.stderr)}\n"
        f"\n"
        f"## ruff\n"
        f"  {r.summary_line()}\n"
        f"  violations={r.violations_count} by_rule={r.violations_by_rule}\n"
        f"  --- stdout (마지막 {max_lines}줄) ---\n{_tail(r.stdout)}\n"
        f"  --- stderr (마지막 {max_lines}줄) ---\n{_tail(r.stderr)}\n"
    )
