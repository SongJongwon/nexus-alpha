# -*- coding: utf-8 -*-
"""src/agents/build_release/build_executor.py 회귀 방지 테스트.

PR #36 — PyInstaller 실제 호출 executor.

실제 PyInstaller 호출은 분 단위 시간 + venv 설치 의존이라 단위 테스트에선
subprocess 를 monkeypatch. 통합 검증은 8차 E2E 에서.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from src.agents.build_release.build_executor import (
    ExecuteResult,
    _compute_sha256,
    _resolve_pyinstaller_executable,
    _tail_text,
    execute_pyinstaller,
)


# ---------------------------------------------------------------------------
# 순수 헬퍼 — _compute_sha256 / _tail_text / _resolve_pyinstaller_executable
# ---------------------------------------------------------------------------


def test_compute_sha256_matches_hashlib_directly(tmp_path: Path) -> None:
    """청크 읽기 SHA256 이 단일 hash 와 일치 — 결정성 검증."""
    content = b"hello world\n" * 10000  # 120KB — 청크 경계 넘게
    f = tmp_path / "blob.bin"
    f.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert _compute_sha256(f) == expected


def test_compute_sha256_handles_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert _compute_sha256(f) == hashlib.sha256(b"").hexdigest()


def test_tail_text_preserves_short_text() -> None:
    """짧은 텍스트는 그대로."""
    short = "hello"
    assert _tail_text(short, limit=100) == short


def test_tail_text_truncates_long_with_marker() -> None:
    """긴 텍스트는 마지막 limit bytes 만 + 절단 마커."""
    long_text = "x" * 1000
    result = _tail_text(long_text, limit=200)
    assert result.startswith("...(truncated 800 bytes)...")
    assert result.endswith("x" * 200)


def test_tail_text_handles_empty() -> None:
    assert _tail_text("") == ""
    assert _tail_text(None or "") == ""


def test_resolve_pyinstaller_executable_returns_path_or_none() -> None:
    """현재 venv 에서 pyinstaller 가 발견되거나 None — 둘 다 정상 케이스."""
    result = _resolve_pyinstaller_executable()
    # PyInstaller 가 venv 에 설치돼 있어야 본 PR 의 production 경로 작동.
    # 단위 테스트에선 존재 여부만 확인 (return type Path or None).
    assert result is None or isinstance(result, Path)


# ---------------------------------------------------------------------------
# execute_pyinstaller — graceful failure 경로 (실제 호출 X)
# ---------------------------------------------------------------------------


def test_execute_pyinstaller_returns_failure_when_entry_missing(tmp_path: Path) -> None:
    """존재하지 않는 entry → exit_code=-3 + error_message."""
    result = execute_pyinstaller(
        entry_path=tmp_path / "nonexistent.py",
        output_dir=tmp_path / "out",
        app_name="X",
    )
    assert result.success is False
    assert result.exit_code == -3
    assert "존재하지 않음" in (result.error_message or "")
    assert result.exe_path is None


def test_execute_pyinstaller_returns_failure_when_pyinstaller_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyinstaller 미설치 → exit_code=-2."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")

    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: None,
    )

    result = execute_pyinstaller(
        entry_path=entry,
        output_dir=tmp_path / "out",
    )
    assert result.success is False
    assert result.exit_code == -2
    assert "pyinstaller" in (result.error_message or "").lower()


def test_execute_pyinstaller_handles_subprocess_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subprocess.TimeoutExpired → exit_code=-1 + timeout 메시지."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")

    fake_pyinstaller = tmp_path / "fake_pyinstaller"
    fake_pyinstaller.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: fake_pyinstaller,
    )

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["pyinstaller"], timeout=1, output=b"partial out", stderr=b"partial err")

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    result = execute_pyinstaller(
        entry_path=entry,
        output_dir=tmp_path / "out",
        timeout_sec=1,
    )
    assert result.success is False
    assert result.exit_code == -1
    assert "timeout" in (result.error_message or "").lower()


def test_execute_pyinstaller_handles_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit_code != 0 → success=False + exit_code 그대로 전달."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")

    fake_pyinstaller = tmp_path / "fake_pyinstaller"
    fake_pyinstaller.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: fake_pyinstaller,
    )

    class _StubProc:
        returncode = 1
        stdout = "build started"
        stderr = "ImportError: No module"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _StubProc())

    result = execute_pyinstaller(
        entry_path=entry,
        output_dir=tmp_path / "out",
    )
    assert result.success is False
    assert result.exit_code == 1
    assert "non-zero" in (result.error_message or "").lower()
    assert "ImportError" in result.stderr


def test_execute_pyinstaller_returns_failure_when_exe_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit 0 그러나 산출 .exe 없음 → success=False + 진단 메시지."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")

    fake_pyinstaller = tmp_path / "fake_pyinstaller"
    fake_pyinstaller.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: fake_pyinstaller,
    )

    class _StubProc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _StubProc())

    result = execute_pyinstaller(
        entry_path=entry,
        output_dir=tmp_path / "out",
        app_name="MissingApp",
    )
    assert result.success is False
    assert "부재" in (result.error_message or "")


def test_execute_pyinstaller_success_path_with_fake_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit 0 + 산출 .exe 존재 → success=True + SHA256 채워짐."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")
    out_dir = tmp_path / "out"

    fake_pyinstaller = tmp_path / "fake_pyinstaller"
    fake_pyinstaller.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: fake_pyinstaller,
    )

    # subprocess.run 이 호출되면 *동시에* 가짜 산출 .exe 생성
    fake_exe_content = b"FAKE_EXE_CONTENT" * 1000  # 16 KB

    def _fake_run(*args, **kwargs):
        # 가짜 .exe 파일 생성 (Windows 경로 기준)
        import sys as _sys
        ext = ".exe" if _sys.platform == "win32" else ""
        dist_dir = out_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        exe_path = dist_dir / f"TestApp{ext}"
        exe_path.write_bytes(fake_exe_content)

        class _StubProc:
            returncode = 0
            stdout = "build complete"
            stderr = ""

        return _StubProc()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = execute_pyinstaller(
        entry_path=entry,
        output_dir=out_dir,
        app_name="TestApp",
        windowed=False,
        onefile=True,
    )
    assert result.success is True
    assert result.exit_code == 0
    assert result.exe_path is not None
    assert result.exe_path.exists()
    assert result.exe_size_bytes == len(fake_exe_content)
    assert result.sha256 == hashlib.sha256(fake_exe_content).hexdigest()
    assert result.elapsed_sec > 0
    # summary_line 포맷 검증
    summary = result.summary_line()
    assert "BUILD SUCCESS" in summary
    assert result.sha256[:16] in summary


def test_execute_pyinstaller_command_contains_required_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명령에 --noconfirm / --clean / --onefile / --windowed 포함 검증."""
    entry = tmp_path / "x.py"
    entry.write_text("print('x')\n")

    fake_pyinstaller = tmp_path / "fake_pyinstaller"
    fake_pyinstaller.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.build_executor._resolve_pyinstaller_executable",
        lambda: fake_pyinstaller,
    )

    captured_cmd = []

    def _capture_run(cmd, **kwargs):
        captured_cmd.extend(cmd)

        class _StubProc:
            returncode = 1  # 실패시켜 산출 검증 우회
            stdout = ""
            stderr = ""

        return _StubProc()

    monkeypatch.setattr(subprocess, "run", _capture_run)

    execute_pyinstaller(
        entry_path=entry,
        output_dir=tmp_path / "out",
        app_name="MyApp",
        windowed=True,
        onefile=True,
        hidden_imports=["lazy_module_a", "lazy_module_b"],
    )

    assert "--noconfirm" in captured_cmd
    assert "--clean" in captured_cmd
    assert "--onefile" in captured_cmd
    assert "--windowed" in captured_cmd
    assert "--noupx" in captured_cmd
    assert "--name" in captured_cmd
    assert "MyApp" in captured_cmd
    # hidden imports 가 각각 --hidden-import 와 페어로 추가
    assert captured_cmd.count("--hidden-import") == 2
    assert "lazy_module_a" in captured_cmd
    assert "lazy_module_b" in captured_cmd


# ---------------------------------------------------------------------------
# ExecuteResult dataclass — summary_line / failure 메시지 형식
# ---------------------------------------------------------------------------


def test_execute_result_summary_line_for_failure() -> None:
    result = ExecuteResult(
        success=False,
        exit_code=1,
        elapsed_sec=12.34,
        error_message="ImportError: tkinter",
    )
    summary = result.summary_line()
    assert "BUILD FAILED" in summary
    assert "exit=1" in summary
    assert "ImportError" in summary
    assert "12.3" in summary


def test_execute_result_dataclass_default_field_factories() -> None:
    """command 가 default_factory=list 로 매번 새 list 인지 확인 (mutable default 회귀)."""
    a = ExecuteResult(success=False, exit_code=-1, elapsed_sec=0.0)
    b = ExecuteResult(success=False, exit_code=-1, elapsed_sec=0.0)
    a.command.append("test")
    assert b.command == []  # 공유되지 않음
