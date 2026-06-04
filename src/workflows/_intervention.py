# -*- coding: utf-8 -*-
"""v13 P20 — codegen 직전 사람 개입(human-in-the-loop) 체크포인트.

자율 런 중간에 사람이 *한 번* 끼어들 수 있게: 계획·스펙 확정 후 codegen 체인 직전에
잠깐 멈춰 (1) 계획/스펙 요약을 보여주고 (2) 사람이 피드백을 주면 P12 메커니즘으로 codegen
입력에 반영, (3) 안 주면 타임아웃 후 자동 진행. **기본 OFF** — opt-in 일 때만 작동.

모드 (intervene=True 일 때):
  - 파일(GUI): ``--emit-events``(telemetry.enabled) 면 checkpoint 이벤트를 events.jsonl 에
    emit + ``<run>/intervention_in.json`` 폴링 (타임아웃 有). GUI 가 패널로 피드백을 그 파일에
    기록 → 하네스가 읽어 반영. non-interactive(앱) 환경에서도 동작 (파일 기반).
  - 콘솔: 실 tty + 비-pytest 면 계획 출력 + 타임아웃 stdin 읽기.
  - 그 외(헤드리스 CI / non-interactive 무 GUI): 즉시 None — 자동 진행 (블록 금지).

주입은 *기존 P12 conduit 재사용*: 반환된 피드백을 호출부(_node_run_chain)가 ``feedback``
문자열에 넣으면 ``request_with_feedback`` → ``user_request`` → 코드젠 product_anchor 로 흘러
codegen 입력에 반영된다 (자체 주입 로직 신설 0).

테스트 결정론: ``run_root`` / ``file_poll`` / ``stdin_read`` 주입으로 실 파일/소켓/stdin 없이
검증. OFF(intervene=False)면 즉시 None — 어떤 외부 접근도 없음 (회귀 0).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

DEFAULT_INTERVENE_TIMEOUT_SEC = 90
_INTERVENTION_FILENAME = "intervention_in.json"
_POLL_INTERVAL_SEC = 0.25
# GUI 카운트다운은 events.jsonl tail(~0.5s) + IPC 지연만큼 하네스 deadline 보다 *늦게* 출발한다.
# 하네스가 정확히 timeout_sec 에 끊으면 GUI 가 '아직 N초 남음' 을 보여주는 경계에서 사용자가
# 막판 제출한 피드백이 유실될 수 있다. 하네스 폴링을 grace 만큼 더 길게 잡아 GUI 카운트다운이
# 0 에 도달(패널 닫힘)할 때까지 폴링이 살아있게 한다 → 막판 제출도 잡는다 (파일 모드 한정).
_POLL_GRACE_SEC = 3


# ---------------------------------------------------------------------------
# run root / 이벤트 emit
# ---------------------------------------------------------------------------
def _run_root_from_emitter() -> Optional[Path]:
    """events.jsonl 의 부모 디렉터리 = run root (GUI 파일 모드). telemetry 비활성이면 None.

    Tauri 는 --emit-events <root>/outputs/events.jsonl 로 spawn 하므로 그 부모가 run root.
    intervention_in.json 을 같은 디렉터리에 두면 GUI(앱)와 하네스가 같은 경로에 합의.
    """
    try:
        from src.monitoring import get_telemetry_emitter  # noqa: PLC0415

        emitter = get_telemetry_emitter()
        if getattr(emitter, "enabled", False) and getattr(emitter, "path", None):
            return Path(emitter.path).parent
    except Exception:  # noqa: BLE001
        return None
    return None


def _emit_checkpoint(
    plan_summary: str,
    timeout_sec: int,
    intervention_file: Path,
    *,
    node: str,
    checkpoint_id: str,
    iteration: int = 0,
    prev_build_path: str = "",
) -> None:
    """checkpoint 이벤트를 events.jsonl 에 emit (telemetry 활성 시만, fail-safe).

    v13 P22 — ``iteration`` (codegen 진입 iteration, GUI 패널 분기용) + ``prev_build_path``
    (iter 2+ 직전 빌드 경로, '빌드 열어보기'용) 를 함께 실음. 둘 다 기본값이면 P20 와 동일.
    """
    try:
        from src.monitoring import CheckpointEvent, get_telemetry_emitter  # noqa: PLC0415

        emitter = get_telemetry_emitter()
        if getattr(emitter, "enabled", False):
            emitter.emit(
                CheckpointEvent(
                    checkpoint_id=checkpoint_id,
                    node=node,
                    plan_summary=plan_summary[:4000],
                    timeout_sec=timeout_sec,
                    intervention_file=str(intervention_file),
                    iteration=iteration,
                    prev_build_path=prev_build_path,
                )
            )
    except Exception:  # noqa: BLE001 — emit 실패가 런을 막지 않음
        pass


# ---------------------------------------------------------------------------
# intervention_in.json 읽기/폴링
# ---------------------------------------------------------------------------
def _read_intervention_file(path: Path) -> Optional[str]:
    """파일 읽고 *삭제* → action=='inject' + feedback 있으면 feedback, 아니면 None('그냥 계속').

    JSON 파싱 실패/형식 이상은 None (안전 — 자동 진행). 삭제로 다음 run/iteration 누수 방지.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    action = str(data.get("action", "inject")).strip().lower()
    feedback = str(data.get("feedback", "") or "").strip()
    if action == "continue" or not feedback:
        return None
    return feedback


def _poll_intervention_file(
    path: Path,
    timeout_sec: int,
    *,
    grace_sec: int = _POLL_GRACE_SEC,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Optional[str]:
    """intervention_in.json 을 (timeout_sec + grace)까지 폴링. 발견 시 읽어 반환, 타임아웃이면 None.

    grace 는 GUI 카운트다운 출발 지연 보정 — 하네스가 GUI 보다 먼저 끊어 막판 제출을 놓치는
    경계 윈도우를 제거한다 (GUI 카운트다운이 0 에 도달해 패널이 닫힌 뒤엔 더 이상 제출 불가).
    """
    deadline = clock() + max(0.0, float(timeout_sec)) + max(0.0, float(grace_sec))
    while clock() < deadline:
        if path.exists():
            return _read_intervention_file(path)
        sleeper(_POLL_INTERVAL_SEC)
    # 타임아웃 vs 제출 레이스 완화 — 최종 1회 확인.
    if path.exists():
        return _read_intervention_file(path)
    return None


def _read_stdin_with_timeout(timeout_sec: int) -> Optional[str]:
    """타임아웃 있는 stdin 한 줄 읽기 (cross-platform — daemon thread + join)."""
    result: list[Optional[str]] = [None]

    def _read() -> None:
        try:
            result[0] = sys.stdin.readline()
        except Exception:  # noqa: BLE001
            result[0] = None

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(max(0.0, float(timeout_sec)))
    line = result[0]
    return line.strip() if line else None


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def format_intervention_directive(feedback: str) -> str:
    """사람 피드백을 codegen feedback 문자열에 끼울 directive 로 포맷 (P12 conduit 재사용)."""
    return (
        "\n\n## 🙋 사용자 개입 지시 (P20 — codegen 직전 체크포인트)\n"
        "아래는 사람이 코드 생성 직전에 직접 제공한 *최우선 반영* 지시입니다. 기존 요구를 "
        "해치지 않는 선에서 이 지시를 반영해 코드를 생성하세요:\n"
        f"{feedback.strip()}\n"
    )


def request_codegen_intervention(
    plan_summary: str,
    *,
    intervene: bool,
    timeout_sec: int = DEFAULT_INTERVENE_TIMEOUT_SEC,
    node: str = "run_chain",
    checkpoint_id: str = "pre_codegen",
    # v13 P22 — codegen 진입 iteration(GUI 패널 분기) + 직전 빌드 경로(iter 2+ '빌드 열어보기').
    iteration: int = 0,
    prev_build_path: str = "",
    # --- 테스트 주입 (실 파일/stdin 없이 결정론) ---
    run_root: Optional[Path] = None,
    file_poll: Optional[Callable[[], Optional[str]]] = None,
    stdin_read: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[str]:
    """codegen 직전 사람 개입 체크포인트. 사람 피드백 문자열 또는 None(개입 없음/타임아웃).

    Returns:
        피드백 문자열(주입할 것) 또는 None(개입 없음 / '그냥 계속' / 타임아웃).
    """
    if not intervene:
        return None  # OFF — 즉시 반환 (회귀 0, 외부 접근 없음).
    timeout_sec = max(1, int(timeout_sec))
    root = run_root if run_root is not None else _run_root_from_emitter()

    if root is not None:
        # 파일 모드 (GUI / --emit-events). 스테일 제거 → emit → 폴링.
        intervention_file = Path(root) / _INTERVENTION_FILENAME
        try:
            if intervention_file.exists():
                intervention_file.unlink()
        except OSError:
            pass
        _emit_checkpoint(
            plan_summary,
            timeout_sec,
            intervention_file,
            node=node,
            checkpoint_id=checkpoint_id,
            iteration=iteration,
            prev_build_path=prev_build_path,
        )
        if file_poll is not None:
            return file_poll()
        return _poll_intervention_file(intervention_file, timeout_sec)

    # 콘솔 모드 — 주입된 stdin_read 우선, 아니면 실 tty + 비-pytest 일 때만.
    if stdin_read is not None:
        return stdin_read()
    if "pytest" not in sys.modules and getattr(sys.stdin, "isatty", lambda: False)():
        print("\n" + "=" * 60)
        print("🙋 [개입 체크포인트] codegen 직전 — 계획/스펙 요약:")
        print(plan_summary[:2000])
        print(f"\n피드백 입력 후 Enter (무입력 {timeout_sec}s 시 자동 진행):")
        return _read_stdin_with_timeout(timeout_sec)
    # 헤드리스 CI / non-interactive 무 GUI → 사람 없음 → 자동 진행.
    return None
