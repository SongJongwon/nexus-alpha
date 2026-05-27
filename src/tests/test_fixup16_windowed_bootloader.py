# -*- coding: utf-8 -*-
"""fixup #16 회귀 차단 — windowed bootloader 검증.

PM evidence (2026-05-26, 5번째 시도 사고):
    PyInstaller stdout 의 "Bootloader ...runw.exe" / "run.exe" 패턴으로
    --windowed 적용 여부를 *빌드 직후 자동 감지*. 5번째 시도 Calculator.exe 가
    windowed=False false negative 로 console 빌드 → cmd 창 표시 사고 처방.
"""

from __future__ import annotations

from pathlib import Path

from src.agents.build_release.build_executor import (
    ExecuteResult,
    _validate_windowed_bootloader,
)


def _make_result(stdout: str, success: bool = True) -> ExecuteResult:
    """ExecuteResult 시뮬레이션 — minimal field set."""
    if success:
        return ExecuteResult(
            success=True,
            exit_code=0,
            elapsed_sec=10.0,
            command=["python", "-m", "PyInstaller"],
            exe_path=Path("C:/fake/dist/App.exe"),
            exe_size_bytes=10000,
            sha256="abc123",
            stdout=stdout,
            stderr="",
        )
    return ExecuteResult(
        success=False,
        exit_code=1,
        elapsed_sec=5.0,
        command=["python", "-m", "PyInstaller"],
        error_message="build fail",
        stdout=stdout,
        stderr="",
    )


class TestValidateWindowedBootloader:
    """4 시나리오 — windowed 의도 vs 실 bootloader 의 조합."""

    def test_windowed_true_runw_pass(self):
        """windowed=True + runw.exe → PASS (정상 GUI 빌드)."""
        stdout = (
            "16171 INFO: Bootloader C:\\Python\\Lib\\site-packages\\PyInstaller"
            "\\bootloader\\Windows-64bit-intel\\runw.exe\n"
            "16172 INFO: building EXE\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=True)
        assert log is not None
        assert "PASS" in log
        assert "runw.exe" in log

    def test_windowed_true_run_fail(self):
        """⭐ windowed=True + run.exe → FAIL (5번째 사고 케이스).

        Calculator.exe 가 빌드된 시점에 PyInstaller args 의 --windowed 안 들어가
        console bootloader 가 선택됨. 사용자 더블클릭 시 cmd 창 표시.
        """
        stdout = (
            "12345 INFO: Bootloader C:\\Python\\Lib\\site-packages\\PyInstaller"
            "\\bootloader\\Windows-64bit-intel\\run.exe\n"
            "12346 INFO: building EXE\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=True)
        assert log is not None
        assert "FAIL" in log
        assert "console bootloader" in log

    def test_windowed_false_run_pass(self):
        """windowed=False + run.exe → PASS (정상 CLI 빌드)."""
        stdout = (
            "12345 INFO: Bootloader C:\\Python\\Lib\\site-packages\\PyInstaller"
            "\\bootloader\\Windows-64bit-intel\\run.exe\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=False)
        assert log is not None
        assert "PASS" in log

    def test_windowed_false_runw_warn(self):
        """windowed=False + runw.exe → WARN (CLI 인데 콘솔 없음 — stdout 안 보임)."""
        stdout = (
            "12345 INFO: Bootloader C:\\Python\\Lib\\site-packages\\PyInstaller"
            "\\bootloader\\Windows-64bit-intel\\runw.exe\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=False)
        assert log is not None
        assert "WARN" in log

    def test_no_bootloader_line_returns_none(self):
        """Bootloader 라인 자체 없음 → None (verbose 차이로 미출력 가능)."""
        stdout = (
            "12345 INFO: building EXE\n"
            "12346 INFO: writing PKG\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=True)
        assert log is None

    def test_failed_build_returns_none(self):
        """executor_result.success=False → None (검증 의미 X)."""
        stdout = "build failed\n"
        log = _validate_windowed_bootloader(
            _make_result(stdout, success=False), expected_windowed=True
        )
        assert log is None

    def test_empty_stdout_returns_none(self):
        """stdout 비어있음 → None."""
        log = _validate_windowed_bootloader(_make_result(""), expected_windowed=True)
        assert log is None

    def test_unknown_when_bootloader_no_pattern(self):
        """Bootloader 라인 있으나 runw.exe / run.exe 둘 다 없음 → UNKNOWN."""
        stdout = (
            "12345 INFO: Bootloader C:\\custom\\path\\customboot.exe\n"
        )
        log = _validate_windowed_bootloader(_make_result(stdout), expected_windowed=True)
        assert log is not None
        assert "UNKNOWN" in log
