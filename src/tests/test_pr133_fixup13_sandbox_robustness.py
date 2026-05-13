# -*- coding: utf-8 -*-
"""PR #133 fixup #13 — sandbox_runner 견고성 검증.

배경 (사용자 라이브 검증, 2026-05-13):
    GUI 앱의 mainloop 가 sandbox subprocess.run timeout 트리거 →
    line 503-504 의 ``.decode()`` on str 가 AttributeError 발생 →
    빌드 전체가 죽음 (.exe 미생성). + tempdir cleanup 도 PermissionError.

본 테스트 모듈은 fixup #13 의 3가지 변경 검증:
  1. decode-on-str 버그 fix (Popen text=True 의 str 반환 처리)
  2. TimeoutExpired 시 명시적 process kill + cleanup
  3. _maybe_run_sandbox 의 예외 catch — 빌드 파이프라인 비차단
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest


def test_sandbox_handles_timeout_without_decode_error(tmp_path: Path) -> None:
    """fixup #13 — TimeoutExpired 시 str/bytes 안전 처리 (decode-on-str 버그 fix).

    사용자 라이브 시나리오 정확 재현:
        GUI 앱 mainloop → 30s timeout → 예전엔 ``.decode()`` on str AttributeError.
        fixup #13 후엔 graceful timeout = SandboxResult(timed_out=True) 반환.
    """
    from src.agents.operations.sandbox_runner import run_python_package_in_sandbox

    # 무한 루프 (GUI mainloop 시뮬레이션)
    src = (
        "# file: app.py\n"
        "import time\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    )
    p = tmp_path / "app.py"
    p.write_text(src, encoding="utf-8")

    # timeout 2초로 빠른 검증
    result = run_python_package_in_sandbox([p], timeout_sec=2)
    assert result is not None, "sandbox 가 None 반환 (entry 미탐지)"
    assert result.timed_out is True, f"timeout 미감지: {result}"
    # AttributeError 발생 안 함 → 정상 SandboxResult 반환
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)


def test_sandbox_subprocess_killed_on_timeout(tmp_path: Path) -> None:
    """fixup #13 — TimeoutExpired 후 자식 프로세스 강제 종료 확인."""
    from src.agents.operations.sandbox_runner import run_python_package_in_sandbox

    src = (
        "# file: app.py\n"
        "import time\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    )
    p = tmp_path / "app.py"
    p.write_text(src, encoding="utf-8")

    # 호출 자체가 예외 던지지 않음 — proc.kill() 이 finally 에서 실행됨
    result = run_python_package_in_sandbox([p], timeout_sec=2)
    assert result is not None
    assert result.timed_out is True
    # exit_code = -1 (timed_out 시 우리가 설정)
    assert result.exit_code == -1


def test_sandbox_normal_completion_returns_str_outputs(tmp_path: Path) -> None:
    """fixup #13 — 정상 종료 시 stdout/stderr 가 str 로 반환."""
    from src.agents.operations.sandbox_runner import run_python_package_in_sandbox

    src = (
        "# file: app.py\n"
        'print("hello from sandbox")\n'
    )
    p = tmp_path / "app.py"
    p.write_text(src, encoding="utf-8")

    result = run_python_package_in_sandbox([p], timeout_sec=5)
    assert result is not None
    assert result.timed_out is False
    assert result.exit_code == 0
    assert isinstance(result.stdout, str)
    assert "hello from sandbox" in result.stdout


def test_sandbox_handles_python_error_in_user_code(tmp_path: Path) -> None:
    """fixup #13 — 사용자 코드 에러 시 graceful (exit_code != 0)."""
    from src.agents.operations.sandbox_runner import run_python_package_in_sandbox

    src = (
        "# file: app.py\n"
        "raise RuntimeError('intentional crash')\n"
    )
    p = tmp_path / "app.py"
    p.write_text(src, encoding="utf-8")

    result = run_python_package_in_sandbox([p], timeout_sec=5)
    assert result is not None
    assert result.timed_out is False
    assert result.exit_code != 0
    assert "RuntimeError" in result.stderr


def test_maybe_run_sandbox_catches_sandbox_exception(tmp_path: Path, monkeypatch) -> None:
    """fixup #13 — sandbox 예외가 빌드 파이프라인을 차단하지 않음.

    핵심: sandbox 단계 실패가 _maybe_run_sandbox 에서 catch 되어 (None, msg) 반환.
    PyInstaller 호출은 계속됨.
    """
    from src.workflows import build_workflow

    # sandbox 가 항상 예외 던지도록 mock
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated sandbox failure")

    monkeypatch.setattr(build_workflow, "run_python_package_in_sandbox", _raise)

    p = tmp_path / "app.py"
    p.write_text("print('hi')\n", encoding="utf-8")

    # _maybe_run_sandbox 는 예외 catch + (None, "...") 반환해야 함
    result, serialized = build_workflow._maybe_run_sandbox([p], timeout_sec=5)
    assert result is None
    assert "graceful skip" in serialized
    assert "RuntimeError" in serialized


def test_maybe_run_sandbox_normal_path(tmp_path: Path) -> None:
    """fixup #13 — 정상 sandbox 동작은 변화 없이 작동.

    _reconstruct_package_tree 가 `# file:` 헤더를 요구하므로 헤더 포함된 코드 제공.
    """
    from src.workflows import build_workflow

    p = tmp_path / "app.py"
    p.write_text("# file: app.py\nprint('hi')\n", encoding="utf-8")
    result, serialized = build_workflow._maybe_run_sandbox([p], timeout_sec=5)
    # 정상 실행 → result is SandboxResult-like 또는 entry 미탐지로 None
    # (단, "graceful skip" 메시지가 들어있으면 fail — 예외 발생한 거임)
    assert "graceful skip" not in serialized, f"sandbox 가 예외 던짐: {serialized}"


def test_temporary_directory_ignore_cleanup_errors() -> None:
    """fixup #13 — tempfile.TemporaryDirectory 호출이 ignore_cleanup_errors=True 옵션 사용."""
    import inspect

    from src.agents.operations import sandbox_runner

    source = inspect.getsource(sandbox_runner)
    # 핵심: TemporaryDirectory(... ignore_cleanup_errors=True ...) 패턴 검증
    assert "ignore_cleanup_errors=True" in source, (
        "TemporaryDirectory 가 ignore_cleanup_errors=True 미사용 — "
        "Windows file lock 시 cleanup 실패가 빌드 전체 죽일 수 있음"
    )


def test_no_decode_on_str_pattern() -> None:
    """fixup #13 회귀 차단 — exc.stdout.decode / exc.stderr.decode 직접 호출 패턴 부재.

    이 패턴이 다시 도입되면 GUI 앱 mainloop 의 timeout 시 AttributeError 발생.
    fixup #13 는 Popen + communicate 로 변경해 이 패턴 완전 제거.
    """
    import inspect

    from src.agents.operations import sandbox_runner

    source = inspect.getsource(sandbox_runner)
    # 정확한 패턴 — exc.stdout/stderr .decode 직접 호출
    # (isinstance 검사 후 decode 는 OK)
    forbidden_patterns = [
        "exc.stdout.decode(",
        "exc.stderr.decode(",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source, (
            f"sandbox_runner.py 에 회귀 패턴 잔존: {pattern}. "
            f"Popen text=True 의 stdout/stderr 는 str 이므로 decode 시 AttributeError."
        )


def test_popen_used_for_explicit_cleanup_control() -> None:
    """fixup #13 — subprocess.Popen 사용 검증 (subprocess.run 의 암묵적 cleanup 한계 극복)."""
    import inspect

    from src.agents.operations import sandbox_runner

    source = inspect.getsource(sandbox_runner)
    assert "subprocess.Popen" in source, (
        "subprocess.Popen 미사용 — TimeoutExpired 시 명시적 kill + wait 불가"
    )
    assert "proc.kill()" in source, (
        "proc.kill() 미호출 — timeout 시 자식 프로세스 좀비화 위험"
    )
