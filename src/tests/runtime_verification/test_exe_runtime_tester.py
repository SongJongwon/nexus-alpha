# -*- coding: utf-8 -*-
"""Exe Runtime Tester 단위 test (v13 Phase 1)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_terminate_process_tree_kills_children(self):
        """⭐ onefile 부트로더 자식까지 트리 종료 (orphan 좀비 방지) — psutil mock."""
        from src.agents.runtime_verification.exe_runtime_tester import _terminate_process_tree

        proc = MagicMock()
        proc.pid = 4321
        child = MagicMock()
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value.children.return_value = [child]
        fake_psutil.wait_procs.return_value = ([], [child])  # child 잔존 → kill 대상
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            _terminate_process_tree(proc)
        child.terminate.assert_called_once()  # 자식 terminate
        child.kill.assert_called_once()       # 잔존 자식 강제 kill
        proc.terminate.assert_called_once()   # 직접 자식(부트로더) terminate

    def test_terminate_process_tree_graceful_without_psutil(self):
        """psutil 미설치/실패여도 직접 자식 terminate 는 수행 (best-effort fallback)."""
        from src.agents.runtime_verification.exe_runtime_tester import _terminate_process_tree

        proc = MagicMock()
        proc.pid = 4321
        # psutil import 실패 시뮬레이션
        with patch.dict("sys.modules", {"psutil": None}):
            _terminate_process_tree(proc)
        proc.terminate.assert_called_once()
