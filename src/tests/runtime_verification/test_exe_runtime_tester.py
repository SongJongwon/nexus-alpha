# -*- coding: utf-8 -*-
"""Exe Runtime Tester 단위 test (v13 Phase 1)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.runtime_verification.exe_runtime_tester import (
    RuntimeTestResult,
    run_exe_runtime_test,
)


def _make_fake_exe() -> Path:
    """Mock 용 .exe — 실제 binary 아니지만 file system 상 존재."""
    tf = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
    tf.write(b"fake binary")
    tf.close()
    return Path(tf.name)


class TestRuntimeTestResult:
    """schema 검증."""

    def test_dataclass_minimal_fields(self):
        result = RuntimeTestResult(
            exit_code=0,
            stderr="",
            stdout="",
            startup_time_ms=100.0,
            memory_peak_mb=None,
            timed_out=False,
            verdict="PASS",
        )
        assert result.verdict == "PASS"
        assert result.exit_code == 0
        assert result.error_trace == ""

    def test_dataclass_full_fields(self):
        result = RuntimeTestResult(
            exit_code=1,
            stderr="CRASH",
            stdout="",
            startup_time_ms=50.0,
            memory_peak_mb=12.3,
            timed_out=False,
            verdict="CRASH",
            error_trace="ImportError",
        )
        assert result.memory_peak_mb == 12.3
        assert result.error_trace == "ImportError"


class TestRunExeRuntimeTest:
    """`run_exe_runtime_test` 의 4 verdict 분기 검증."""

    def test_spawn_error_file_not_found(self):
        result = run_exe_runtime_test(Path("C:/__nonexistent_v13_rv__/fake.exe"))
        assert result.verdict == "SPAWN_ERROR"
        assert "미발견" in result.stderr

    @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
    def test_pass_when_alive_for_timeout(self, mock_popen):
        """⭐ timeout 동안 살아있으면 PASS — GUI mainloop 정상 시작 추정."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 살아있음 (memory 측정 통과)
        mock_proc.pid = 99999
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(
            cmd=["fake.exe"], timeout=0.1
        )
        mock_popen.return_value = mock_proc

        exe = _make_fake_exe()
        try:
            result = run_exe_runtime_test(exe, timeout_sec=0.1)
            assert result.verdict == "PASS"
            assert result.timed_out is True
            assert result.exit_code is None
            mock_proc.terminate.assert_called_once()
        finally:
            exe.unlink(missing_ok=True)

    @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
    def test_silent_fail_exit_zero_immediate(self, mock_popen):
        """⭐ exit 0 + 즉시 종료 = SILENT_FAIL (entry 오선택 추정)."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.pid = 99999
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        exe = _make_fake_exe()
        try:
            result = run_exe_runtime_test(exe, timeout_sec=3.0)
            assert result.verdict == "SILENT_FAIL"
            assert result.exit_code == 0
            assert "silent fail" in result.error_trace.lower()
        finally:
            exe.unlink(missing_ok=True)

    @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
    def test_crash_nonzero_exit(self, mock_popen):
        """⭐ exit != 0 = CRASH — stderr 포함 보존."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.pid = 99999
        mock_proc.communicate.return_value = (b"", b"UnicodeEncodeError: 'cp949'\n")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        exe = _make_fake_exe()
        try:
            result = run_exe_runtime_test(exe, timeout_sec=3.0)
            assert result.verdict == "CRASH"
            assert result.exit_code == 1
            assert "UnicodeEncodeError" in result.stderr
            assert "UnicodeEncodeError" in result.error_trace
        finally:
            exe.unlink(missing_ok=True)

    @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
    def test_spawn_error_oserror(self, mock_popen):
        """spawn OSError → SPAWN_ERROR."""
        mock_popen.side_effect = OSError("Permission denied")

        exe = _make_fake_exe()
        try:
            result = run_exe_runtime_test(exe)
            assert result.verdict == "SPAWN_ERROR"
            assert "Permission denied" in result.stderr or "Permission denied" in result.error_trace
        finally:
            exe.unlink(missing_ok=True)

    def test_telemetry_emit_safe_when_disabled(self):
        """Telemetry 비활성 시에도 동작 — emit 실패 silent 보장."""
        # Telemetry env var 미설정 → emitter.enabled=False → emit silent no-op
        result = run_exe_runtime_test(Path("C:/__nonexistent__/x.exe"))
        # spawn 실패는 별개 — telemetry 자체 예외 차단만 검증
        assert isinstance(result, RuntimeTestResult)


class TestP23TreeKillAndDrain:
    """v13 P23 — PASS(생존) 경로의 프로세스 트리 정리(좀비 방지) + 부분 출력 회수."""

    @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
    def test_pass_drains_partial_stderr(self, mock_popen):
        """⭐ 생존(PASS) 후 terminate → 잔여 stderr 회수 → 결과에 실림 ((b) 검출 실효화)."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        # 1차 communicate(timeout) → TimeoutExpired(생존), 2차 communicate(drain) → 잔여 출력.
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=["fake.exe"], timeout=0.1),
            (b"", b"Traceback ... OperationalError: no such column: active"),
        ]
        mock_popen.return_value = mock_proc

        exe = _make_fake_exe()
        try:
            result = run_exe_runtime_test(exe, timeout_sec=0.1)
            assert result.verdict == "PASS"
            assert "OperationalError" in result.stderr  # PASS 라도 잔여 stderr 회수됨
            mock_proc.terminate.assert_called_once()
        finally:
            exe.unlink(missing_ok=True)

    def test_psutil_direct_kill_kills_children(self):
        """⭐ onefile 부트로더 자식까지 트리 종료 (orphan 좀비 방지) — psutil mock."""
        from src.agents.runtime_verification.exe_runtime_tester import _psutil_direct_kill

        proc = MagicMock()
        proc.pid = 4321
        child = MagicMock()
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value.children.return_value = [child]
        fake_psutil.wait_procs.return_value = ([], [child])  # child 잔존 → kill 대상
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            _psutil_direct_kill(proc)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        proc.terminate.assert_called_once()

    def test_psutil_direct_kill_graceful_without_psutil(self):
        """psutil 미설치/실패여도 직접 자식 terminate 는 수행 (best-effort fallback)."""
        from src.agents.runtime_verification.exe_runtime_tester import _psutil_direct_kill

        proc = MagicMock()
        proc.pid = 4321
        with patch.dict("sys.modules", {"psutil": None}):
            _psutil_direct_kill(proc)
        proc.terminate.assert_called_once()

    def test_cleanup_process_tree_layers_in_order(self):
        """_cleanup_process_tree 가 taskkill → Job → psutil 을 *이 순서로* 호출 (순서가 핵심:
        taskkill 가 부모 생존 시 실 트리를 walk 하도록 Job-kill 보다 먼저)."""
        import src.agents.runtime_verification.exe_runtime_tester as M

        proc = MagicMock()
        proc.pid = 4321
        manager = MagicMock()
        with patch.object(M, "_taskkill_tree", manager.taskkill), \
             patch.object(M, "_win32_terminate_close_job", manager.job), \
             patch.object(M, "_psutil_direct_kill", manager.psutil):
            M._cleanup_process_tree(proc, job="JOB")
        # 호출 *순서* 단언 — taskkill 먼저, 그 다음 Job, 마지막 psutil.
        assert [c[0] for c in manager.mock_calls] == ["taskkill", "job", "psutil"]
        manager.taskkill.assert_called_once_with(4321)
        manager.job.assert_called_once_with("JOB")
        manager.psutil.assert_called_once_with(proc)

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="orphan 트리 정리는 win32(Job/taskkill) 경로 — .exe 도 win32 에서만 실행",
    )
    def test_cleanup_kills_REAL_process_tree_orphan_zero(self):
        """⭐⭐ live-fix 통합(실 프로세스, psutil 불요): 부모→자식 트리를 _cleanup_process_tree 가
        *전부* 종료(orphan 0). 기존 mock 이 'terminate 호출됨'만 보고 실제 미작동(라이브에서 onefile
        자식 생존)을 놓친 갭을 닫는다 — 실제 PID 생존을 ctypes 로 직접 확인."""
        import ctypes
        import subprocess as _sp
        import sys as _sys
        import time as _t

        from src.agents.runtime_verification.exe_runtime_tester import _cleanup_process_tree

        def _alive(pid: int) -> bool:
            PROCESS_QUERY_LIMITED = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            return bool(ok) and code.value == STILL_ACTIVE

        code = (
            "import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
            "print(c.pid,flush=True);"
            "time.sleep(30)"
        )
        proc = _sp.Popen([_sys.executable, "-c", code], stdout=_sp.PIPE)
        child_pid = int(proc.stdout.readline().decode().strip())
        try:
            assert _alive(proc.pid) and _alive(child_pid), "사전: 부모·자식 모두 생존해야"
            # psutil 부재를 *강제* — taskkill /T native-only 로 트리킬됨을 결정론적으로 증명
            # (라이브 결함 근본원인이 'psutil-only sweep 이 onefile 자식 못 잡음' 이었으므로).
            with patch.dict("sys.modules", {"psutil": None}):
                _cleanup_process_tree(proc, None)  # job 없이 → taskkill /T 가 트리 정리
            deadline = _t.monotonic() + 6.0
            while _t.monotonic() < deadline and (_alive(proc.pid) or _alive(child_pid)):
                _t.sleep(0.1)
            assert not _alive(proc.pid), "부모 프로세스 생존 (orphan)"
            assert not _alive(child_pid), "자식 프로세스 생존 (orphan) — 트리킬 실패"
        finally:
            try:
                _sp.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=5)
            except Exception:  # noqa: BLE001
                pass

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="Job Object / CREATE_SUSPENDED — win32 전용",
    )
    def test_job_captures_suspended_tree_owned_pids_and_kills(self):
        """⭐⭐ Job 경로(review v2): spawn-전 Job + CREATE_SUSPENDED + 할당 + 재개 → 자식이 race
        없이 Job 에 캡처됨. _win32_job_pids 가 자식 PID 를 포함(kernel-authoritative)하고,
        _cleanup_process_tree(job 포함) 후 orphan 0. (기존 orphan 테스트는 job=None 이라 이 경로 미검증.)"""
        import ctypes
        import subprocess as _sp
        import sys as _sys
        import time as _t

        import src.agents.runtime_verification.exe_runtime_tester as M

        def _alive(pid: int) -> bool:
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            c = ctypes.c_ulong()
            k32.GetExitCodeProcess(h, ctypes.byref(c))
            k32.CloseHandle(h)
            return c.value == 259

        job = M._win32_create_kill_job()
        assert job is not None, "win32 Job 생성 실패 (pywin32 필요)"
        code = (
            "import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
            "print(c.pid,flush=True);time.sleep(30)"
        )
        proc = _sp.Popen([_sys.executable, "-c", code], stdout=_sp.PIPE, creationflags=0x00000004)  # SUSPENDED
        try:
            assert M._win32_assign_job(job, proc.pid), "Job 할당 실패"
            assert M._win32_resume_pid(proc.pid), "재개 실패"
            child_pid = int(proc.stdout.readline().decode().strip())
            _t.sleep(0.3)
            owned = M._win32_job_pids(job)
            assert proc.pid in owned and child_pid in owned, f"Job 멤버에 자식 누락: {owned}"
            with patch.dict("sys.modules", {"psutil": None}):  # native-only 증명
                M._cleanup_process_tree(proc, job)
            deadline = _t.monotonic() + 6.0
            while _t.monotonic() < deadline and (_alive(proc.pid) or _alive(child_pid)):
                _t.sleep(0.1)
            assert not _alive(proc.pid) and not _alive(child_pid), "Job 경로 cleanup 후 orphan 잔존"
        finally:
            try:
                _sp.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=5)
            except Exception:  # noqa: BLE001
                pass

    def test_owned_fn_frozen_after_run_no_closed_handle_query(self):
        """⭐ review v2 fix — owned_fn 은 run 종료(cleanup→Job close) 후 _win32_job_pids 를 *다시
        질의하지 않는다*(닫힌/재사용 핸들 질의 → 타 앱 PID 오귀속 = stray false-FAIL 방지)."""
        import src.agents.runtime_verification.exe_runtime_tester as M

        captured = {}
        qcount = {"n": 0}

        def _fake_jp(job):
            qcount["n"] += 1
            return {7777}

        @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
        def _inner(mock_popen):
            mp = MagicMock()
            mp.poll.return_value = 0
            mp.pid = 555
            # 런 *중*(communicate 시점, Job 열림)에 owned() 1회 호출 → 스냅샷이 Job PID 로 갱신.
            def _comm(timeout=None):
                captured["owned"]()
                return (b"", b"")
            mp.communicate.side_effect = _comm
            mp.returncode = 0
            mock_popen.return_value = mp
            with patch.object(M, "_win32_create_kill_job", return_value="JOB"), \
                 patch.object(M, "_win32_assign_job", return_value=True), \
                 patch.object(M, "_win32_resume_pid", return_value=True), \
                 patch.object(M, "_win32_terminate_close_job"), \
                 patch.object(M, "_win32_job_pids", side_effect=_fake_jp), \
                 patch.object(M, "_taskkill_tree"), \
                 patch.object(M, "_psutil_direct_kill"):
                exe = _make_fake_exe()
                try:
                    M.run_exe_runtime_test(
                        exe, timeout_sec=0.1,
                        on_spawn=lambda pid, owned=None: captured.update(owned=owned),
                    )
                finally:
                    exe.unlink(missing_ok=True)

        _inner()
        owned = captured["owned"]
        n_after_run = qcount["n"]
        assert n_after_run >= 1, "런 중 Job 질의가 일어나야(스냅샷 갱신)"
        result = owned()  # 런 종료(cleanup→freeze) 후 호출 — frozen 이라 재질의 X
        assert qcount["n"] == n_after_run, "frozen 후 닫힌 Job 재질의 발생(타 앱 PID 위험)"
        assert result == {7777}, f"마지막 유효 스냅샷이 아님: {result}"

    def test_on_spawn_receives_pid_and_owned_fn(self):
        """run_exe_runtime_test 가 on_spawn(pid, owned_pids_fn) 으로 통지 (창 PID-스코핑 배선)."""
        seen = {}

        @patch("src.agents.runtime_verification.exe_runtime_tester.subprocess.Popen")
        def _inner(mock_popen):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 0
            mock_proc.pid = 54321
            mock_proc.communicate.return_value = (b"", b"")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            exe = _make_fake_exe()
            try:
                run_exe_runtime_test(
                    exe, timeout_sec=0.1,
                    on_spawn=lambda pid, owned=None: seen.update(pid=pid, owned=owned),
                )
            finally:
                exe.unlink(missing_ok=True)

        _inner()
        assert seen.get("pid") == 54321
        assert callable(seen.get("owned"))  # owned PID 집합 조회 함수 전달
