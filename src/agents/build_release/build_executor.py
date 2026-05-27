# -*- coding: utf-8 -*-
"""PyInstaller 실제 호출 executor (Phase 4.5 강화 — PR #36).

Build Engineer 의 BuildSpec 사양 → 실제 ``pyinstaller`` 호출 → ``.exe`` 생성 →
SHA256 산출. 첫 진짜 외부 도구 통합 — v5 doc DoD Phase 4.5 의 핵심 미완 항목 해소.

설계 원칙:
  - **subprocess 호출만 담당**: BuildSpec 의 LLM 산출 markdown 을 직접 파싱하지
    않음. 입력은 *구조화된 인자* (entry_path / app_name / windowed / hidden_imports
    등). 호출 측이 BuildSpec / ui_spec 에서 추출해 넘김.
  - **timeout 강제**: PyInstaller 가 무한 hang 가능 — 5분 기본 타임아웃.
  - **graceful failure**: 실패 시 None / 에러 메시지 반환, 예외 propagate 안 함.
  - **결정적 산출 디렉터리**: ``output_dir/dist/<App>.exe`` (PyInstaller 표준).

호출 측 (build_workflow.py) 통합 패턴:
    if enable_executor and code_files:
        result = execute_pyinstaller(
            entry_path=Path(entry_hint),
            output_dir=workflow_dir / "build_output",
            app_name=...,  # ui_spec / asset_manifest 기반
            windowed=ui_spec_indicates_gui,
            hidden_imports=parsed_from_dependency_report,
        )
        # result 를 BuildWorkflowResult 에 병합
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 결과 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class ExecuteResult:
    """PyInstaller 실행 결과 — graceful failure 모델 (예외 propagate 안 함)."""

    success: bool
    """성공 여부 — exit_code == 0 AND .exe 존재 AND 크기 > 0."""

    exit_code: int
    """subprocess 종료 코드. -1 이면 timeout, -2 이면 pyinstaller 미설치."""

    elapsed_sec: float
    """소요 시간 (실측)."""

    command: list[str] = field(default_factory=list)
    """실행한 명령 (debug/재현용)."""

    exe_path: Optional[Path] = None
    """산출 .exe 경로 — 실패 시 None."""

    exe_size_bytes: Optional[int] = None
    """.exe 크기 (bytes) — 실패 시 None."""

    sha256: Optional[str] = None
    """.exe SHA256 hex — 실패 시 None."""

    stdout: str = ""
    """PyInstaller stdout (마지막 100KB)."""

    stderr: str = ""
    """PyInstaller stderr (마지막 100KB)."""

    error_message: Optional[str] = None
    """failure 시 사람이 읽을 수 있는 진단 메시지."""

    def summary_line(self) -> str:
        """한 줄 요약 — 로그/리포트 용."""
        if self.success:
            assert self.exe_path and self.exe_size_bytes is not None
            return (
                f"[BUILD SUCCESS] {self.exe_path.name} "
                f"({self.exe_size_bytes / (1024 * 1024):.1f} MB, "
                f"sha256={self.sha256[:16]}..., elapsed={self.elapsed_sec:.1f}s)"
            )
        return (
            f"[BUILD FAILED] exit={self.exit_code}, "
            f"error={self.error_message or 'unknown'}, "
            f"elapsed={self.elapsed_sec:.1f}s"
        )


# ---------------------------------------------------------------------------
# PyInstaller 실행자
# ---------------------------------------------------------------------------


_DEFAULT_TIMEOUT_SEC = 300  # 5분 — 단순 GUI 앱 빌드 충분
_OUTPUT_TAIL_BYTES = 100_000  # stdout/stderr 보존 한도


def _resolve_pyinstaller_executable() -> Optional[Path]:
    """현재 venv 의 pyinstaller 실행 파일 위치를 찾는다.

    Windows: ``.venv/Scripts/pyinstaller.exe``
    Linux/macOS: ``.venv/bin/pyinstaller``
    Fallback: ``shutil.which("pyinstaller")`` (PATH 검색).
    """
    venv_python = Path(sys.executable)  # 현재 실행 중인 Python
    if sys.platform == "win32":
        candidate = venv_python.parent / "pyinstaller.exe"
    else:
        candidate = venv_python.parent / "pyinstaller"
    if candidate.exists():
        return candidate
    # PATH 검색
    found = shutil.which("pyinstaller")
    return Path(found) if found else None


def _compute_sha256(path: Path, chunk_size: int = 65536) -> str:
    """파일의 SHA256 hex digest 계산 — 메모리 효율적 청크 읽기."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _tail_text(text: str, limit: int = _OUTPUT_TAIL_BYTES) -> str:
    """긴 stdout/stderr 의 마지막 limit bytes 만 보존."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"...(truncated {len(text) - limit} bytes)...\n" + text[-limit:]


def execute_pyinstaller(
    entry_path: Path,
    output_dir: Path,
    app_name: str = "App",
    windowed: bool = True,
    onefile: bool = True,
    hidden_imports: Optional[list[str]] = None,
    collect_all: Optional[list[str]] = None,
    exclude_modules: Optional[list[str]] = None,
    icon_path: Optional[Path] = None,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    additional_args: Optional[list[str]] = None,
) -> ExecuteResult:
    """PyInstaller 를 subprocess 로 호출해 단일 실행파일 빌드.

    Args:
        entry_path: 엔트리 .py 파일 절대 경로 (예: code/calculator.py).
        output_dir: 빌드 산출 루트 디렉터리. ``dist/`` ``build/`` ``*.spec`` 가
            여기 아래에 생성됨.
        app_name: ``--name`` — 산출 .exe 파일명 (확장자 제외).
        windowed: True 면 ``--windowed`` (GUI), False 면 ``--console``.
        onefile: True 면 ``--onefile`` (단일 .exe), False 면 ``--onedir``.
        hidden_imports: ``--hidden-import`` 로 추가할 모듈 목록.
        collect_all: PR #133 fixup #6 — ``--collect-all`` 로 추가할 패키지 목록.
            flet / customtkinter 같이 data files / 플러그인 / 바이너리를 가진
            패키지가 PyInstaller 기본 정적 분석으로 누락되는 경우 대비.
            ``--collect-all <pkg>`` 는 패키지의 (a) submodules (b) data files
            (c) binaries 를 모두 .exe 에 포함.
        exclude_modules: PR #133 fixup #8 — ``--exclude-module`` 로 PyInstaller 가
            *수집 시도조차 안 하도록* 차단할 모듈 목록. 주 용도: mutex group 의 비채택
            패키지 (예: PySide6 채택 시 PyQt6 차단). 채택된 패키지의 hook 가
            ``import PyQt6`` 같은 fallback 라인을 만나도 hook 가 실행되지 않음.
        icon_path: ``--icon`` 으로 지정할 .ico/.icns 경로 (Optional).
        timeout_sec: subprocess 타임아웃 (초). 기본 300 (5분).
        additional_args: 추가 raw 인자 — 고급 사용자 escape hatch.

    Returns:
        ExecuteResult — 성공/실패 + 산출 경로 + SHA256 + 로그 + 진단.
        예외 propagate 안 함 (실패 시 ExecuteResult.success=False).
    """
    started = time.time()

    # 1. PyInstaller 실행 파일 검색
    pyinstaller_exe = _resolve_pyinstaller_executable()
    if pyinstaller_exe is None:
        return ExecuteResult(
            success=False,
            exit_code=-2,
            elapsed_sec=time.time() - started,
            error_message=(
                "PyInstaller 실행 파일을 찾을 수 없음. "
                "`pip install pyinstaller>=6.20.0` 로 설치 필요."
            ),
        )

    # 2. entry_path 검증
    if not entry_path.exists():
        return ExecuteResult(
            success=False,
            exit_code=-3,
            elapsed_sec=time.time() - started,
            error_message=f"entry_path 가 존재하지 않음: {entry_path}",
        )

    # 3. output_dir 준비
    output_dir.mkdir(parents=True, exist_ok=True)
    dist_dir = output_dir / "dist"
    work_dir = output_dir / "build"
    spec_dir = output_dir

    # 4. 명령 빌드
    cmd: list[str] = [
        str(pyinstaller_exe),
        "--noconfirm",
        "--clean",
        "--name", app_name,
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--specpath", str(spec_dir),
        "--noupx",  # UPX 압축 우회 — antivirus false positive 방지
    ]
    cmd.append("--onefile" if onefile else "--onedir")
    cmd.append("--windowed" if windowed else "--console")
    for hi in hidden_imports or []:
        cmd.extend(["--hidden-import", hi])
    # PR #133 fixup #6 — flet / customtkinter 같이 data files 가진 패키지 대응
    for pkg in collect_all or []:
        cmd.extend(["--collect-all", pkg])
    # PR #133 fixup #8 — mutex group 의 비채택 패키지 (PyQt5 vs PySide6 동시 번들 차단)
    for mod in exclude_modules or []:
        cmd.extend(["--exclude-module", mod])
    if icon_path and icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])
    if additional_args:
        cmd.extend(additional_args)
    cmd.append(str(entry_path))

    # 5. subprocess 실행
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,  # exit_code 직접 확인
        )
        exit_code = proc.returncode
        stdout = _tail_text(proc.stdout)
        stderr = _tail_text(proc.stderr)
    except subprocess.TimeoutExpired as e:
        return ExecuteResult(
            success=False,
            exit_code=-1,
            elapsed_sec=time.time() - started,
            command=cmd,
            stdout=_tail_text(e.stdout.decode("utf-8", errors="replace") if e.stdout else ""),
            stderr=_tail_text(e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
            error_message=f"PyInstaller timeout — {timeout_sec}s 내 완료 못 함.",
        )
    except FileNotFoundError as e:
        return ExecuteResult(
            success=False,
            exit_code=-2,
            elapsed_sec=time.time() - started,
            command=cmd,
            error_message=f"PyInstaller 실행 실패 (FileNotFoundError): {e}",
        )

    elapsed = time.time() - started

    # 6. 산출 .exe 검증
    if exit_code != 0:
        return ExecuteResult(
            success=False,
            exit_code=exit_code,
            elapsed_sec=elapsed,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            error_message=f"PyInstaller exit_code={exit_code} (non-zero).",
        )

    # 산출 파일 위치 찾기
    if sys.platform == "win32":
        if onefile:
            exe_path = dist_dir / f"{app_name}.exe"
        else:
            exe_path = dist_dir / app_name / f"{app_name}.exe"
    else:
        # macOS/Linux: 확장자 없음
        if onefile:
            exe_path = dist_dir / app_name
        else:
            exe_path = dist_dir / app_name / app_name

    if not exe_path.exists():
        return ExecuteResult(
            success=False,
            exit_code=exit_code,
            elapsed_sec=elapsed,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            error_message=f"PyInstaller 종료 코드 0 그러나 산출 파일 부재: {exe_path}",
        )

    exe_size = exe_path.stat().st_size
    if exe_size == 0:
        return ExecuteResult(
            success=False,
            exit_code=exit_code,
            elapsed_sec=elapsed,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            error_message=f"산출 파일 크기 0: {exe_path}",
        )

    # 7. SHA256 산출
    sha256 = _compute_sha256(exe_path)

    return ExecuteResult(
        success=True,
        exit_code=exit_code,
        elapsed_sec=elapsed,
        command=cmd,
        exe_path=exe_path,
        exe_size_bytes=exe_size,
        sha256=sha256,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# fixup #16 (2026-05-26) — Windowed bootloader 검증
# ---------------------------------------------------------------------------
def _validate_windowed_bootloader(
    executor_result: "ExecuteResult", expected_windowed: bool
) -> Optional[str]:
    """PyInstaller 의 stdout 에서 *bootloader 종류* 를 검증한다.

    PyInstaller 가 출력하는 패턴:
        ``Bootloader ...\\bootloader\\Windows-64bit-intel\\runw.exe`` ← windowed (GUI)
        ``Bootloader ...\\bootloader\\Windows-64bit-intel\\run.exe``  ← console (CLI)

    5번째 시도 사고 (Calculator.exe — windowed=False false negative 로 cmd 창 표시)
    같은 결함을 *빌드 직후 자동 감지*.

    Args:
        executor_result: `execute_pyinstaller` 의 반환값. ``stdout`` 에 bootloader
            라인이 포함됨.
        expected_windowed: 의도된 windowed 값. True 면 runw.exe 가 기대, False 면
            run.exe 가 기대.

    Returns:
        검증 로그 한 줄 (Optional). build_workflow 가 stderr 에 prepend 해서
        25_executor_result.md 에 자동 표시되도록.
    """
    if not executor_result.success:
        return None
    stdout = executor_result.stdout or ""
    if "Bootloader" not in stdout:
        # bootloader line 자체가 없음 — 로그 verbose level 차이 가능
        return None

    has_runw = "runw.exe" in stdout
    has_run = "run.exe" in stdout and not has_runw  # runw.exe 가 있으면 run.exe 매치는 substring noise

    if expected_windowed:
        if has_runw:
            return (
                "[WINDOWED_VALIDATION] PASS — runw.exe bootloader 확인 (콘솔 없는 "
                "GUI 빌드, --windowed 정상 적용)\n"
            )
        elif has_run:
            return (
                "[WINDOWED_VALIDATION] FAIL — windowed=True 인데 console bootloader "
                "(run.exe) 감지. 빌드된 .exe 실행 시 cmd 창 표시될 가능성. "
                "PyInstaller args 의 --windowed 적용 여부 확인 필요.\n"
            )
        else:
            return (
                "[WINDOWED_VALIDATION] UNKNOWN — Bootloader 라인 있으나 runw.exe / "
                "run.exe 패턴 어느 쪽도 매치 안 됨.\n"
            )
    else:
        # CLI 앱 — run.exe 가 기대
        if has_run:
            return (
                "[WINDOWED_VALIDATION] PASS — run.exe bootloader 확인 (CLI 빌드, "
                "콘솔 표시 정상)\n"
            )
        elif has_runw:
            return (
                "[WINDOWED_VALIDATION] WARN — windowed=False 인데 runw.exe bootloader "
                "감지. CLI 앱의 stdout 출력이 안 보일 수 있음.\n"
            )
        return None


# ---------------------------------------------------------------------------
# .exe Smoke Test — PM 명시 (2026-05-26, 4회 BLOCKED 사고 처방)
# ---------------------------------------------------------------------------
@dataclass
class SmokeTestResult:
    """`run_exe_smoke_test` 의 산출.

    Attributes:
        passed: 3초 동안 프로세스 alive 했으면 True (GUI 앱 mainloop 시작 추정).
        reason: 사람-가독 결과 메시지.
        exit_code: 프로세스 종료 코드 (timeout 으로 살아있다 terminate 했으면 None).
        survived_sec: spawn 부터 결과까지 경과 시간.
    """

    passed: bool
    reason: str
    exit_code: Optional[int]
    survived_sec: float


def run_exe_smoke_test(exe_path: Path, timeout_sec: float = 3.0) -> SmokeTestResult:
    """빌드된 .exe 의 minimal runtime 검증 (PM 명시 — 4회 BLOCKED 사고 처방).

    동작 (Windows):
        1. `subprocess.Popen` 로 .exe spawn (DETACHED_PROCESS + stdio null).
        2. `proc.wait(timeout=timeout_sec)` 로 종료 대기.
        3. timeout 이면 → 프로세스가 *살아있음* → PASS (GUI mainloop 시작 추정),
           terminate() + (필요 시) kill() 로 정리.
        4. timeout 전에 종료 → *즉시 종료* (entry 오선택 / import 실패) → FAIL.

    사용 시나리오:
        - 이전 4 사고 (계산기 / 유튜브 녹화기 / theme.py entry / 칸반 보드) 중
          theme.py entry 오선택 같은 사례를 *빌드 후 자동 검출* — 사용자가 .exe
          더블클릭 했는데 *즉시 종료* 하는 사고 차단.
        - GUI 앱은 mainloop() 가 *블로킹* 이라 3초면 충분히 시작 확인.
        - CLI 앱은 짧은 task 끝나면 즉시 종료 — *FAIL 로 판정될 수도* 있음. 따라서
          본 helper 는 *GUI 앱에 한해 사용* 권장 (호출 측이 artifact_category=='gui'
          때만 호출).

    Args:
        exe_path: 빌드 산출 .exe 의 Path.
        timeout_sec: 살아있어야 PASS 로 인정될 시간 (default 3초).

    Returns:
        SmokeTestResult — passed True 면 3초 alive, False 면 즉시 종료.
    """
    if not exe_path.exists() or not exe_path.is_file():
        return SmokeTestResult(False, f".exe 미발견: {exe_path}", None, 0.0)

    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS — 부모 stdio 무관, console 창 안 띄움.
        creationflags = 0x00000008

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SmokeTestResult(False, f".exe spawn 실패: {exc!r}", None, 0.0)

    try:
        exit_code = proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        # 3초 alive — PASS. 정리: terminate → kill.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        except (OSError, subprocess.SubprocessError):
            pass
        return SmokeTestResult(
            passed=True,
            reason=(
                f"{elapsed:.2f}s alive — GUI 앱 mainloop 정상 시작 추정 "
                f"(timeout={timeout_sec}s 동안 종료 안 됨)"
            ),
            exit_code=None,
            survived_sec=elapsed,
        )

    # timeout 전에 종료 — FAIL (entry 오선택 / import 실패).
    elapsed = time.monotonic() - start
    return SmokeTestResult(
        passed=False,
        reason=(
            f"즉시 종료 (entry 오선택 / import 실패 가능 — theme.py 사례) "
            f"exit_code={exit_code} elapsed={elapsed:.2f}s"
        ),
        exit_code=exit_code,
        survived_sec=elapsed,
    )
