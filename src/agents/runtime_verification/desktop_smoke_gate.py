# -*- coding: utf-8 -*-
"""v13 P23 — 데스크탑 .exe 런타임 스모크 게이트.

빌드된 .exe 를 판정(Convergence Judge) 직전에 잠깐 실제로 띄워 *실행 즉시/실행 중 크래시·치명
에러*를 검출한다. P17(web headless 시각 QA)의 데스크탑 대응물.

FAIL 신호 (이것만 COMPLETE 차단):
  (a) 비정상 종료(exit≠0) — Exe Runtime Tester 의 CRASH.
  (b) stdout/stderr 에러 패턴 (Traceback/Exception/OperationalError/FATAL/치명적/오류/Error).
      생존(PASS) 앱도 terminate 후 *부분 출력 회수*(exe_runtime_tester._drain_after_kill)로 검사.
  (d) 실행 중 오류 다이얼로그 창 감지 (창 제목 — best-effort, 아래 한계 참조).
SKIPPED (COMPLETE 차단 안 함):
  - 즉시 종료 exit 0(SILENT_FAIL) + 에러 출력 없음 → *보수적 SKIP*. CLI/단발 .exe 의 정상 종료를
    크래시로 오판해 거짓 BLOCKED 하지 않기 위함(GUI/CLI 를 게이트가 강제 구분하지 않으므로 보수적).
    (단 exit 0 + 에러 출력이 있으면 FAIL.)
  - .exe 미존재 / 비-win32(헤드리스·CI) / 실행 예외 / 알 수 없는 verdict.
PASS = 타임아웃 동안 생존 + 위 FAIL 신호 없음.

설계 원칙 (v13 P23 live fix 반영):
  - 기존 ``run_exe_runtime_test`` *재사용* — spawn 로직 신설 X. **프로세스 트리 종료는 spawn 전
    생성한 Win32 Job Object(CREATE_SUSPENDED 로 실행 전 할당 → race 0) + ``taskkill /T /F`` 로
    커널 차원 보장** → onefile 부트로더의 detached 실 앱 자식까지 확실히 정리(스모크 후 생존 0).
    psutil 은 비-win32 / 최종 best-effort (이 환경엔 psutil 미설치 → Job/taskkill 가 주경로).
  - 창 감지는 **Job 멤버 PID(우리 프로세스 트리)가 소유한 창만** 본다(``_scoped_error_window`` =
    win32gui+win32process 로 창→PID 귀속). owned PID 는 ``run_exe_runtime_test`` 가 넘기는 **Job
    프로세스 리스트**(kernel-authoritative — stale ppid/PID 재사용 무관, reparented 자식 포함). 무관
    한 다른 앱 창은 절대 보지 않아 stray-창 false FAIL 근절. 단어경계 + benign 화이트리스트로 제목
    오탐도 완화. pywin32 미가용/비-win32 면 빈 신호(FAIL 아님 — 보수적).
  - 검증 실패가 메인 cycle 을 막지 않는다 (예외 → SKIPPED). SKIPPED 는 FAIL 아님(재빌드 미발동).
  - ``_runtime_test`` / ``_error_window_probe`` 주입으로 실 subprocess/창 없이 결정론 단위 검증.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIPPED = "SKIPPED"

# (b) 출력 에러 패턴 — 살아있는(PASS) GUI 라도 stdout/stderr 에 이게 있으면 FAIL.
# 정밀화(review fix): Traceback 헤더 + CamelCase 예외(OperationalError/FooException 등) + FATAL/치명적
# 만 매칭. bare 'error'/'오류' 광범위 매칭 제거 → '0 errors found'/'오류 없음'/'terror'/'errorless'/
# 'Error Console' 같은 *정상* 출력의 거짓 FAIL 방지(대소문자 구분 — CamelCase 의도 보존).
_ERROR_OUTPUT_RE = re.compile(
    r"Traceback \(most recent call last\)"
    r"|\b[A-Z][A-Za-z]*(Error|Exception)\b"
    r"|\bFATAL\b"
    r"|치명적"
)
# (d) 오류 다이얼로그 창 제목 패턴. 한글은 구체 토큰, 영문은 *단어경계* — 'Mirror'/'Terror' 같은
# 부분문자열 오탐 방지. 'Error Console/List/Log' 류 정상 개발도구 창은 _WINDOW_BENIGN_RE 로 제외.
_WINDOW_ERROR_PATTERNS = (
    re.compile(r"오류"),
    re.compile(r"치명적"),
    re.compile(r"\bfatal\b", re.IGNORECASE),
    re.compile(r"unhandled exception", re.IGNORECASE),
    re.compile(r"application error", re.IGNORECASE),
    re.compile(r"\b(error|exception)\b", re.IGNORECASE),
)
_WINDOW_BENIGN_RE = re.compile(r"error\s+(console|list|log|output|lens|reporting)", re.IGNORECASE)


@dataclass
class DesktopSmokeResult:
    """데스크탑 런타임 스모크 결과. verdict='FAIL' 만 COMPLETE 를 차단한다."""

    verdict: str  # PASS | FAIL | SKIPPED
    reason: str = ""
    exit_code: Optional[int] = None
    survived_sec: float = 0.0
    error_excerpt: str = ""
    signal: str = ""           # exit|silent|spawn|stderr|window|alive|skipped
    window_title_hit: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == VERDICT_PASS

    @property
    def failed(self) -> bool:
        return self.verdict == VERDICT_FAIL


def _match_error_window(titles: list[str]) -> str:
    """창 제목 목록에서 오류 다이얼로그로 보이는 첫 제목 반환 (없으면 "").

    단어경계 정규식 + benign 화이트리스트('Error Console/List/Log' 등 정상 도구 창 제외)로
    제목 오탐을 줄인다. (호출 측은 *우리 PID 트리가 소유한* 창만 넘겨야 한다 — _scoped_error_window.)
    """
    for t in titles:
        if _WINDOW_BENIGN_RE.search(t):
            continue
        if any(p.search(t) for p in _WINDOW_ERROR_PATTERNS):
            return t
    return ""


def _scoped_error_window(pid_set: set) -> str:
    """우리 프로세스 트리(``pid_set``)가 *소유한* 최상위 창 중 오류 다이얼로그 제목 (없으면 "").

    v13 P23 (live fix): win32gui+win32process 로 **창→PID 귀속** → 무관한 *다른 앱* 창은 절대
    보지 않는다(전역 열거의 stray-창 오탐 근절). pywin32 미가용/비-win32/빈 pid_set 면 ""(신호
    없음 — 보수적, false FAIL 금지).
    """
    if sys.platform != "win32" or not pid_set:
        return ""
    try:
        import win32gui  # type: ignore  # noqa: PLC0415
        import win32process  # type: ignore  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — pywin32 미설치 → 신호 없음
        return ""

    hits: list[str] = []

    def _cb(hwnd, _ctx):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pid_set:
                title = win32gui.GetWindowText(hwnd) or ""
                if title.strip() and _match_error_window([title]):
                    hits.append(title)
        except Exception:  # noqa: BLE001
            pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:  # noqa: BLE001
        return ""
    return hits[0] if hits else ""


def _combine_smoke_verdict(rt: Any, window_title_hit: str, *, timeout_sec: float) -> DesktopSmokeResult:
    """(순수) Exe Runtime Tester 결과 + 창 제목 신호 → 데스크탑 스모크 verdict.

    - CRASH/SILENT_FAIL  → FAIL (비정상/즉시 종료).
    - SPAWN_ERROR        → FAIL (빌드된 .exe 가 실행조차 안 됨).
    - PASS(생존) + 오류창 → FAIL (실행 중 오류 다이얼로그).
    - PASS(생존) + 출력 에러 패턴 → FAIL.
    - PASS(생존) + 무신호 → PASS.
    - 그 외 알 수 없는 verdict → SKIPPED (보수적 — COMPLETE 차단 안 함).
    """
    verdict = str(getattr(rt, "verdict", "") or "")
    exit_code = getattr(rt, "exit_code", None)
    stderr = str(getattr(rt, "stderr", "") or "")
    stdout = str(getattr(rt, "stdout", "") or "")
    error_trace = str(getattr(rt, "error_trace", "") or "")
    combined = "\n".join(x for x in (error_trace, stderr, stdout) if x)

    if verdict == "CRASH":
        return DesktopSmokeResult(
            verdict=VERDICT_FAIL,
            reason=f"실행 즉시 비정상 종료 (exit={exit_code}≠0)",
            exit_code=exit_code,
            error_excerpt=(error_trace or stderr or "(출력 없음)").strip()[:1500],
            signal="exit",
        )
    if verdict == "SILENT_FAIL":
        # exit 0 즉시 종료 — GUI 면 mainloop 미진입 의심이나 CLI/단발 .exe 면 *정상*.
        # 거짓 BLOCKED 회피: 에러 출력(Traceback 등)이 *있을 때만* FAIL, 아니면 보수적 SKIP.
        if combined and _ERROR_OUTPUT_RE.search(combined):
            return DesktopSmokeResult(
                verdict=VERDICT_FAIL,
                reason=f"즉시 종료(exit 0) + 에러 출력 감지 (verdict={verdict})",
                exit_code=exit_code,
                error_excerpt=combined.strip()[:1500],
                signal="silent",
            )
        return DesktopSmokeResult(
            verdict=VERDICT_SKIPPED,
            reason="즉시 종료(exit 0, 에러 출력 없음) — CLI/단발 정상 가능, 보수적 SKIP",
            exit_code=exit_code,
            signal="skipped",
        )
    if verdict == "SPAWN_ERROR":
        return DesktopSmokeResult(
            verdict=VERDICT_FAIL,
            reason="빌드된 .exe 실행(spawn) 실패 — 사용자 손에서 실행 불가",
            exit_code=exit_code,
            error_excerpt=(stderr or error_trace or "(출력 없음)").strip()[:1500],
            signal="spawn",
        )
    if verdict == VERDICT_PASS:
        if window_title_hit:
            return DesktopSmokeResult(
                verdict=VERDICT_FAIL,
                reason=f"실행 중 오류 다이얼로그 감지: {window_title_hit!r}",
                exit_code=exit_code,
                error_excerpt=window_title_hit[:1500],
                signal="window",
                window_title_hit=window_title_hit,
            )
        if combined and _ERROR_OUTPUT_RE.search(combined):
            return DesktopSmokeResult(
                verdict=VERDICT_FAIL,
                reason="실행 중 에러 출력(stdout/stderr) 감지",
                exit_code=exit_code,
                error_excerpt=combined.strip()[:1500],
                signal="stderr",
            )
        return DesktopSmokeResult(
            verdict=VERDICT_PASS,
            reason=f"{timeout_sec:.0f}s 동안 정상 생존 (크래시·에러 신호 없음)",
            exit_code=exit_code,
            survived_sec=float(timeout_sec),
            signal="alive",
        )
    return DesktopSmokeResult(
        verdict=VERDICT_SKIPPED,
        reason=f"판정 불가 verdict={verdict!r} — 스모크 건너뜀",
        exit_code=exit_code,
        signal="skipped",
    )


def run_desktop_smoke_gate(
    exe_path: Path,
    *,
    timeout_sec: float = 8.0,
    settle_sec: float = 1.5,
    _runtime_test: Optional[Callable[..., Any]] = None,
    _error_window_probe: Optional[Callable[[set], str]] = None,
) -> DesktopSmokeResult:
    """데스크탑 .exe 를 잠깐 띄워 크래시/치명 에러 검출 → DesktopSmokeResult.

    비-win32(헤드리스/CI) 또는 .exe 미존재면 graceful SKIPPED (FAIL 아님). ``_runtime_test`` 주입
    시 플랫폼 게이트 우회(단위 테스트용). 창 감지는 **런치된 .exe 의 PID 트리가 소유한 창만**
    본다(``_scoped_error_window``) — 무관한 다른 앱의 오류성 창에 false FAIL 하지 않는다.
    owned PID 집합은 ``run_exe_runtime_test`` 가 ``on_spawn(pid, owned_pids_fn)`` 으로 넘기는 **Job
    멤버 리스트**(kernel-authoritative — stale ppid/PID 재사용 무관). 프로세스 트리 종료(좀비 0)도
    그쪽 Job/taskkill 가 담당. 검출 누락 방지를 위해 스캔 스레드(실행 중 일시 다이얼로그 포착) +
    **종료 직후 최종 1회 probe**(정상상태 보장, 테스트 결정론)를 함께 쓴다.
    """
    probe = _error_window_probe or _scoped_error_window

    if _runtime_test is None and sys.platform != "win32":
        return DesktopSmokeResult(
            VERDICT_SKIPPED, reason="non-win32 — .exe 실행 불가(헤드리스/CI)", signal="skipped"
        )

    p = Path(str(exe_path))
    if not p.exists():
        return DesktopSmokeResult(VERDICT_SKIPPED, reason=f".exe 미존재: {p}", signal="skipped")

    # run_exe_runtime_test 가 on_spawn(pid, owned_pids_fn) 으로 통지. 기본 owned 는 빈 집합.
    spawned = {"pid": None, "owned": (lambda: set())}
    window_hit = {"title": ""}
    stop = threading.Event()

    def _scan() -> None:
        deadline = time.monotonic() + max(0.0, float(timeout_sec)) + 1.0
        settle_done_at = time.monotonic() + min(max(0.0, float(settle_sec)), max(0.0, float(timeout_sec)))
        while time.monotonic() < deadline and not stop.is_set():
            if spawned["pid"] is None:
                time.sleep(0.05)  # pid 도착 능동 대기
                continue
            if time.monotonic() >= settle_done_at:
                hit = probe(spawned["owned"]())  # Job 멤버(우리 트리) 소유 창만
                if hit:
                    window_hit["title"] = hit
                    return
            time.sleep(0.2)

    scanner = threading.Thread(target=_scan, daemon=True)
    scanner.start()

    runtime_test = _runtime_test
    if runtime_test is None:
        from src.agents.runtime_verification import run_exe_runtime_test  # noqa: PLC0415

        runtime_test = run_exe_runtime_test

    def _on_spawn(pid: int, owned_pids_fn=None) -> None:
        spawned["pid"] = pid
        if owned_pids_fn is not None:
            spawned["owned"] = owned_pids_fn

    try:
        rt = runtime_test(p, timeout_sec=timeout_sec, on_spawn=_on_spawn)
    except Exception as exc:  # noqa: BLE001 — 스모크 실행 실패가 메인 cycle 차단 X
        stop.set()
        return DesktopSmokeResult(
            VERDICT_SKIPPED, reason=f"스모크 실행 예외(차단 안 함): {exc!r}", signal="skipped"
        )
    finally:
        stop.set()
    scanner.join(timeout=1.0)
    # 최종 1회 probe 보장 — 짧은 윈도우/스레드 타이밍에도 최소 한 번 검사(결정론).
    if not window_hit["title"] and spawned["pid"] is not None:
        try:
            window_hit["title"] = probe(spawned["owned"]())
        except Exception:  # noqa: BLE001
            pass

    return _combine_smoke_verdict(rt, window_hit["title"], timeout_sec=timeout_sec)
