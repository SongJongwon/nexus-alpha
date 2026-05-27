# -*- coding: utf-8 -*-
"""Exe Runtime Tester — 본부 9 RV foundation agent (v13 Phase 1 최우선).

빌드된 `.exe` 를 sandbox 환경에서 실행하여 exit code / stderr / 시작 시간 /
메모리 peak 측정. 자기 진화 루프의 *감지 노드* — silent fail 자율 인지의 시작점.

기존 `src/agents/build_release/build_executor.py:run_exe_smoke_test` (PR #210)
보다 *측정 풍부도* 우위 — 메모리 peak / 시작 시간 / 상세 stderr 캡처.

Telemetry: `AgentStatusEvent(department="rv")` emit — 자기 진화 루프 시각화의
기반 데이터.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 측정 데이터 schema
# ---------------------------------------------------------------------------
@dataclass
class RuntimeTestResult:
    """`run_exe_runtime_test` 의 산출 — 자기 진화 루프의 *감지 raw 데이터*.

    Attributes:
        exit_code: 자식 프로세스 종료 코드. timeout 시 None.
        stderr: 자식 프로세스의 표준 오류 (UTF-8 디코딩).
        stdout: 자식 프로세스의 표준 출력 (선택, 보통 GUI 앱은 비어있음).
        startup_time_ms: spawn 부터 *프로세스 alive 확인* 까지의 시간 (ms).
        memory_peak_mb: 측정 동안 RSS 의 peak (MB). psutil 미설치 시 None.
        timed_out: timeout_sec 동안 종료되지 않아 terminate 됐는지.
        verdict: ``"PASS"`` (alive 동안 정상) / ``"SILENT_FAIL"`` (즉시 종료 +
            exit_code=0) / ``"CRASH"`` (exit_code != 0) / ``"TIMEOUT"`` /
            ``"SPAWN_ERROR"``.
        error_trace: silent fail / crash 시 추출된 trace 텍스트 (Telemetry 로그
            append 용).
    """

    exit_code: Optional[int]
    stderr: str
    stdout: str
    startup_time_ms: float
    memory_peak_mb: Optional[float]
    timed_out: bool
    verdict: str
    error_trace: str = ""
    exe_path: Optional[Path] = field(default=None)


def _try_emit_telemetry(
    agent: str, status: str, detail: str = ""
) -> None:
    """Telemetry emit — 실패해도 메인 흐름 차단 X (try/except + silent)."""
    try:
        from src.monitoring.telemetry import (
            AgentStatusEvent,
            get_telemetry_emitter,
        )

        emitter = get_telemetry_emitter()
        if not emitter.enabled:
            return
        emitter.emit(
            AgentStatusEvent(
                agent=agent,
                department="rv",  # 본부 9 RV 식별자 (system_architecture.md 계층 2.5)
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


def _measure_memory_peak(pid: int) -> Optional[float]:
    """psutil 활용해 process 의 RSS peak 측정. 미설치 시 None."""
    try:
        import psutil  # type: ignore

        proc = psutil.Process(pid)
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def run_exe_runtime_test(
    exe_path: Path,
    timeout_sec: float = 3.0,
) -> RuntimeTestResult:
    """빌드된 `.exe` 의 런타임 동작 측정.

    동작:
        1. `_try_emit_telemetry("exe_runtime_tester", "working")` emit
        2. subprocess.Popen 으로 .exe spawn (DETACHED + stdio capture)
        3. ``timeout_sec`` 동안 wait — 살아있으면 PASS (GUI 정상)
        4. 즉시 종료 — exit_code 기반 SILENT_FAIL / CRASH 판정
        5. stderr 캡처 + error_trace 추출
        6. memory peak 측정 (psutil 가용 시)
        7. `_try_emit_telemetry("exe_runtime_tester", "done")` emit

    Returns:
        RuntimeTestResult — 자기 진화 루프의 *raw 감지 데이터*.
    """
    _try_emit_telemetry(
        "exe_runtime_tester",
        "working",
        f"target={exe_path.name}",
    )

    if not exe_path.exists() or not exe_path.is_file():
        result = RuntimeTestResult(
            exit_code=None,
            stderr=f".exe 미발견: {exe_path}",
            stdout="",
            startup_time_ms=0.0,
            memory_peak_mb=None,
            timed_out=False,
            verdict="SPAWN_ERROR",
            error_trace="file not found",
            exe_path=exe_path,
        )
        _try_emit_telemetry("exe_runtime_tester", "error", "file not found")
        return result

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008  # DETACHED_PROCESS

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        result = RuntimeTestResult(
            exit_code=None,
            stderr=f"spawn 실패: {exc!r}",
            stdout="",
            startup_time_ms=elapsed_ms,
            memory_peak_mb=None,
            timed_out=False,
            verdict="SPAWN_ERROR",
            error_trace=str(exc),
            exe_path=exe_path,
        )
        _try_emit_telemetry("exe_runtime_tester", "error", f"spawn fail: {exc!r}")
        return result

    memory_peak_mb: Optional[float] = None
    try:
        # 50ms 안에 첫 alive 확인 후 memory 측정
        time.sleep(0.05)
        if proc.poll() is None:
            memory_peak_mb = _measure_memory_peak(proc.pid)

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout_sec)
            elapsed_ms = (time.monotonic() - start) * 1000
            stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            exit_code = proc.returncode

            # 판정 — 즉시 종료 = SILENT_FAIL or CRASH
            if exit_code == 0:
                # exit 0 인데 즉시 종료 — entry 오선택 / GUI mainloop 미진입
                verdict = "SILENT_FAIL"
                error_trace = stderr_str or "(exit 0 immediate — silent fail / entry 오선택 추정)"
            else:
                verdict = "CRASH"
                error_trace = stderr_str or f"exit_code={exit_code}"
            result = RuntimeTestResult(
                exit_code=exit_code,
                stderr=stderr_str,
                stdout=stdout_str,
                startup_time_ms=elapsed_ms,
                memory_peak_mb=memory_peak_mb,
                timed_out=False,
                verdict=verdict,
                error_trace=error_trace,
                exe_path=exe_path,
            )
            _try_emit_telemetry(
                "exe_runtime_tester",
                "done",
                f"verdict={verdict} exit={exit_code}",
            )
            return result
        except subprocess.TimeoutExpired:
            # timeout 동안 살아있음 — PASS (GUI mainloop 정상)
            elapsed_ms = (time.monotonic() - start) * 1000
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:  # noqa: BLE001
                pass

            result = RuntimeTestResult(
                exit_code=None,
                stderr="",
                stdout="",
                startup_time_ms=elapsed_ms,
                memory_peak_mb=memory_peak_mb,
                timed_out=True,
                verdict="PASS",
                error_trace="",
                exe_path=exe_path,
            )
            _try_emit_telemetry(
                "exe_runtime_tester",
                "done",
                f"verdict=PASS alive={timeout_sec}s mem={memory_peak_mb}MB",
            )
            return result
    except Exception as exc:  # noqa: BLE001
        result = RuntimeTestResult(
            exit_code=None,
            stderr=f"unexpected: {exc!r}",
            stdout="",
            startup_time_ms=(time.monotonic() - start) * 1000,
            memory_peak_mb=memory_peak_mb,
            timed_out=False,
            verdict="SPAWN_ERROR",
            error_trace=str(exc),
            exe_path=exe_path,
        )
        _try_emit_telemetry("exe_runtime_tester", "error", str(exc))
        return result
