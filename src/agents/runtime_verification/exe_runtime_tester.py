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
from typing import Any, Callable, Optional


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


def _win32_create_kill_job() -> Any:
    """v13 P23 — JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE Job Object 생성. 실패/비-win32 시 None.

    잡에 할당된 프로세스의 *모든 자손*(detached/reparented 포함)이 잡 종료(또는 핸들 close)
    시 커널 차원에서 함께 종료된다 — PyInstaller onefile 부트로더가 spawn 한 실 앱 자식까지.
    """
    if sys.platform != "win32":
        return None
    try:
        import win32job  # type: ignore

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, info
        )
        return job
    except Exception:  # noqa: BLE001 — pywin32 미설치/권한 등 → 잡 없이 fallback
        return None


def _win32_assign_job(job: Any, pid: int) -> bool:
    """프로세스를 잡에 할당(CREATE_SUSPENDED 상태에서 호출 → 이후 모든 자식이 잡에 편입).

    핸들 누수 방지: OpenProcess 핸들을 finally 에서 항상 close.
    """
    if job is None:
        return False
    handle = None
    try:
        import win32api  # type: ignore
        import win32con  # type: ignore
        import win32job  # type: ignore

        handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid
        )
        win32job.AssignProcessToJobObject(job, handle)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if handle is not None:
            try:
                import win32api  # type: ignore

                win32api.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass


def _win32_resume_pid(pid: int) -> bool:
    """CREATE_SUSPENDED 로 띄운 프로세스의 모든 스레드 재개(NtResumeProcess). 성공 시 True.

    OpenProcess restype 를 c_void_p 로 명시(Win64 핸들 절단 방지). 자기 자식 프로세스 재개는
    사실상 항상 성공한다. 호출 측은 반환값을 **best-effort 로 무시**한다 — 재개 실패(예: 테스트의
    가짜 PID)여도 communicate 가 이어받으며, 실 프로세스에서 재개 실패는 발생하지 않는다."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        PROCESS_SUSPEND_RESUME = 0x0800
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(PROCESS_SUSPEND_RESUME, False, int(pid))
        if not h:
            return False
        try:
            ntdll = ctypes.windll.ntdll
            ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
            return ntdll.NtResumeProcess(ctypes.c_void_p(h)) == 0  # STATUS_SUCCESS
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:  # noqa: BLE001
        return False


def _win32_job_pids(job: Any) -> set:
    """잡 멤버 PID 집합 — *kernel-authoritative* (detached/reparented 자식 포함, PID 재사용/stale
    ppid 무관). 창 PID-스코핑의 권위 소스. 실패/None 시 set()."""
    if job is None:
        return set()
    try:
        import win32job  # type: ignore

        info = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList)
        return {int(p) for p in info}
    except Exception:  # noqa: BLE001
        return set()


def _win32_terminate_close_job(job: Any) -> None:
    """잡 종료(트리 전체 kill) + 핸들 close (KILL_ON_JOB_CLOSE 로 이중 보장)."""
    if job is None:
        return
    try:
        import win32job  # type: ignore

        win32job.TerminateJobObject(job, 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        import win32api  # type: ignore

        win32api.CloseHandle(job)  # KILL_ON_JOB_CLOSE — 잔존 멤버까지 정리
    except Exception:  # noqa: BLE001
        pass


def _taskkill_tree(pid: int) -> None:
    """win32 네이티브 트리킬 — ``taskkill /PID <pid> /T /F`` (검증된 fallback)."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        pass


def _psutil_direct_kill(proc: "subprocess.Popen") -> None:
    """psutil 자식 트리 + 직접 자식 종료 (비-win32 주경로 / win32 최종 best-effort)."""
    children = []
    try:
        import psutil  # type: ignore

        children = psutil.Process(proc.pid).children(recursive=True)
        for c in children:
            try:
                c.terminate()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        children = []
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass
    if children:
        try:
            import psutil  # type: ignore

            _, alive = psutil.wait_procs(children, timeout=1.5)
            for c in alive:
                try:
                    c.kill()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass


def _cleanup_process_tree(proc: "subprocess.Popen", job: Any = None) -> None:
    """런치된 .exe 의 프로세스 *트리 전체* 확실 종료 — 스모크 후 생존 프로세스 0 보장.

    v13 P23 (live fix v2 — review): psutil children sweep 는 (이 venv 처럼) psutil 미설치 시
    no-op 이고, Job-kill 을 *먼저* 하면 부모를 죽여 taskkill /T 가 트리를 못 walk 한다(리뷰
    재현). **순서가 핵심**:
      (1) ``taskkill /PID <pid> /T /F`` *먼저* — 부모(부트로더) 생존 시 /T 가 *살아있는 실 트리*
          를 walk 해 자식까지 kill (검증됨).
      (2) Win32 Job terminate/close — 백스톱. 부모가 이미 죽었거나(즉시종료) detached/reparented
          여도 *잡 멤버* 는 커널이 kill (CREATE_SUSPENDED 로 spawn 전 캡처되어 멤버십 보장).
      (3) psutil sweep + 직접 terminate — 비-win32 주경로 + 최종 best-effort.
    모두 예외-격리(best-effort) — 정리 실패가 메인 흐름 차단 X.
    """
    _taskkill_tree(proc.pid)
    _win32_terminate_close_job(job)
    _psutil_direct_kill(proc)


def _drain_after_kill(proc: "subprocess.Popen") -> tuple[str, str]:
    """종료된 프로세스의 *잔여* stdout/stderr 회수 → (stderr, stdout).

    v13 P23 — alive(PASS) 경로에서도 부분 출력을 확보해 ``_combine_smoke_verdict`` 의 (b)
    에러-출력 검출이 실효를 갖게 한다. terminate 후 호출이라 보통 즉시 EOF 로 회수되지만, orphan
    손자가 stderr 파이프를 물고 있으면 EOF 가 안 올 수 있어 **communicate(timeout=2.0) 로 상한**을
    둔다(blocking 방지의 실제 근거는 이 timeout). 초과/실패 시 ("", "") (best-effort).
    """
    try:
        out_b, err_b = proc.communicate(timeout=2.0)
        out = out_b.decode("utf-8", errors="replace") if out_b else ""
        err = err_b.decode("utf-8", errors="replace") if err_b else ""
        return (err, out)
    except Exception:  # noqa: BLE001
        return ("", "")


def run_exe_runtime_test(
    exe_path: Path,
    timeout_sec: float = 3.0,
    on_spawn: Optional[Callable[..., None]] = None,
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

    # v13 P23 (live fix v2 — review) — Job Object 를 *spawn 전* 생성하고 CREATE_SUSPENDED 로 띄워
    # *실행 전* 잡에 할당 → 부트로더가 spawn 하는 모든 자식이 잡에 편입(race 0). 그 후 재개.
    job = _win32_create_kill_job()
    creationflags = 0
    suspended = False
    if sys.platform == "win32":
        creationflags = 0x00000008  # DETACHED_PROCESS
        if job is not None:
            creationflags |= 0x00000004  # CREATE_SUSPENDED
            suspended = True

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
        _win32_terminate_close_job(job)
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

    # 잡 할당(suspended 상태) → 재개. 할당 실패 시 잡 폐기. 재개는 best-effort —
    # 자기 자식이라 정상적으로 항상 성공하며, 실패해도(테스트의 가짜 PID 등) communicate 가 이어
    # 받으므로 SPAWN_ERROR 로 강등하지 않는다(실 프로세스의 재개 실패는 사실상 발생 안 함).
    if job is not None:
        if not _win32_assign_job(job, proc.pid):
            _win32_terminate_close_job(job)
            job = None
    if suspended:
        _win32_resume_pid(proc.pid)

    # 호출 측에 PID + *owned PID 집합 조회 함수* 통지 (창 PID-스코핑 — Job 멤버가 권위 소스).
    # ★ review fix: owned_fn 은 cleanup 전 마지막 유효 스냅샷을 *freeze* 한다. cleanup 이 Job 핸들을
    #   CloseHandle 하면 그 닫힌 핸들로 _win32_job_pids 를 질의할 때 *재사용된 핸들* 이 무관 프로세스
    #   PID 를 반환할 수 있다(handle reuse). frozen 후엔 질의를 멈추고 마지막 유효 PID 집합만 반환 →
    #   닫힌 핸들 질의로 인한 *타 앱 PID 오귀속(stray false-FAIL)* 차단.
    owned_state = {"frozen": False, "pids": {proc.pid}}

    def _owned_pids_fn() -> set:
        if not owned_state["frozen"] and job is not None:
            members = _win32_job_pids(job)
            if members:
                owned_state["pids"] = members
        return owned_state["pids"]

    if on_spawn is not None:
        try:
            on_spawn(proc.pid, _owned_pids_fn)
        except Exception:  # noqa: BLE001
            pass

    def _cleanup() -> None:
        owned_state["frozen"] = True  # 닫힐 Job 핸들 질의 금지(스냅샷 고정) → cleanup
        _cleanup_process_tree(proc, job)

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
            # 즉시 종료라도 부트로더가 spawn 한 detached 자식이 남을 수 있어 트리 정리.
            _cleanup()
            _try_emit_telemetry(
                "exe_runtime_tester",
                "done",
                f"verdict={verdict} exit={exit_code}",
            )
            return result
        except subprocess.TimeoutExpired:
            # timeout 동안 살아있음 — PASS (GUI mainloop 정상)
            elapsed_ms = (time.monotonic() - start) * 1000
            # v13 P23 (live fix) — 프로세스 *트리 전체* 종료(Job/taskkill — onefile 자식 orphan
            # 방지) + 부분 출력 회수.
            _cleanup()
            alive_stderr, alive_stdout = _drain_after_kill(proc)

            result = RuntimeTestResult(
                exit_code=None,
                stderr=alive_stderr,
                stdout=alive_stdout,
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
        _cleanup()  # 예외 시에도 트리 정리(생존 0 보장)
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
