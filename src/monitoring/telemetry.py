# -*- coding: utf-8 -*-
"""
Telemetry Event Emitter (Sprint 4 — Desktop App prerequisite).

LangFuse 와 분리된 *경량 로컬 JSON Lines* 이벤트 stream. Tauri 데스크탑 앱
(``docs/insights/desktop_app_vision.md``) 이 sidecar 프로세스로 ``scripts/run.py``
를 spawn 한 뒤 본 file 을 tail 하여 부서별 카드 그리드 / 대화 panel /
iteration progress / 결과 패널 을 실시간 갱신한다.

설계 원칙 (LangFuse client 와 동일):
    - 활성화 조건: 환경변수 ``NEXUS_TELEMETRY_PATH`` 가 *비어있지 않은 경로* 이면 활성.
      미 set 또는 빈 문자열 이면 모든 emit 가 조용히 no-op (default OFF).
    - **메인 기능 절대 차단 금지** — 어떤 emit 실패도 stderr 한 줄 경고 후 silent.
    - JSON Lines (UTF-8) — 한 줄 = 한 event, append-only, atomic write.

Event 4 종 (Sprint 4):
    - AgentStatusEvent       : agent working/done/error (부서별 카드 갱신)
    - AgentMessageEvent      : LLM input/output 한 건 (대화 panel)
    - IterationProgressEvent : run 시작 / iteration boundary / run 종료
    - ResultEvent            : 최종 verdict + .exe + duration (결과 패널)

CLI / 환경변수 활성 경로:
    1) ``scripts/run.py --emit-events <abs_path>`` (PR #187) → ``main()`` 가
       ``NEXUS_TELEMETRY_PATH`` env var 를 abs_path 로 set.
    2) 외부 도구가 직접 ``NEXUS_TELEMETRY_PATH=...`` 로 export.

Tauri sidecar 예시:
    ``python scripts/run.py --request ... --emit-events events.jsonl`` →
    Tauri shell 이 ``events.jsonl`` 을 tail → React state 갱신.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 부서 매핑 (docs/insights/desktop_app_vision.md §2)
# ---------------------------------------------------------------------------
# 본부 10 의 부서별 색상 매핑을 *데이터 차원* 으로 보존.
# Tauri UI 가 본 매핑을 사용해 카드 그리드 색상을 결정한다.
PLANNING = "planning"        # 🔵 파랑 (기획)
ENGINEERING = "engineering"  # 🟣 보라 (개발)
LEARNING = "learning"        # 🟢 청록 (학습)
SYSTEM = "system"            # 종결/오케스트레이션 노드 (부서 N/A)
RV = "rv"                    # 🟠 본부 9 Runtime Verification (v13 Phase 1)
C_LEVEL = "c-level"          # 🟡 C-Level 의결권자 (v13 Phase 3 — Goal Alignment + Token Budget)

# iterative_loop 노드 → 부서 매핑.
# (운영 안전: 매핑 누락 시 SYSTEM 로 fallback — emit 결함 차단)
_NODE_DEPARTMENT: dict[str, str] = {
    # 기획 부서 (Analyst / Meeting Facilitator)
    "expand_requirements": PLANNING,
    "kickoff_meeting": PLANNING,
    "analyze_gap": PLANNING,
    "prepare_feedback": PLANNING,
    # 개발 부서 (CTO / Engineer / Reviewer / QA / Sandbox / Pytest)
    "run_chain": ENGINEERING,
    "run_sandbox": ENGINEERING,
    # v13 Phase 1 2단계 — 본부 9 RV (system_architecture.md 계층 2.5 명세)
    "runtime_verify": RV,
    # v13 Phase 3 — Boardroom 회의실 인프라 (boardroom_facilitator.py)
    "boardroom_trigger": PLANNING,         # 본부 10 Coordination — 의장 격상
    "goal_alignment_check": C_LEVEL,        # Placeholder (Phase 4 교체)
    "budget_brake": C_LEVEL,                # Placeholder (Phase 4 교체)
    # 학습 부서 (Curator / Retrospective Lead / Convergence Judge)
    "recall_past_knowledge": LEARNING,
    "judge_convergence": LEARNING,
    "retrospective": LEARNING,
    "retrospective_blocked": LEARNING,
    "curate_knowledge": LEARNING,
    "curate_knowledge_blocked": LEARNING,
    # 종결 노드
    "finalize": SYSTEM,
    "escalate": SYSTEM,
}


def department_for_node(node_name: str) -> str:
    """노드 이름 → 부서 식별자. 미매핑 시 SYSTEM 반환 (emit 차단 X)."""
    return _NODE_DEPARTMENT.get(node_name, SYSTEM)


# ---------------------------------------------------------------------------
# Event dataclass — 4 종
# ---------------------------------------------------------------------------
def _now_ts() -> str:
    """ISO 8601 UTC timestamp (Tauri React 호환)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class AgentStatusEvent:
    """부서 카드 상태 변경 (working / done / error / idle).

    Tauri UI: 부서 카드 테두리 강조 + 펄스 애니메이션 ON/OFF.
    """
    agent: str           # 노드 이름 (예: "run_chain")
    department: str      # PLANNING / ENGINEERING / LEARNING / SYSTEM
    status: str          # "working" | "done" | "error" | "idle"
    run_id: str = ""
    iteration: int = 0
    detail: str = ""     # 선택적 상세 (error message 등)
    ts: str = field(default_factory=_now_ts)
    type: str = "agent_status"


@dataclass
class AgentMessageEvent:
    """LLM 호출 1 건 (input/output). 대화 panel 의 1 라인.

    BaseLLMProvider.generate() 의 finally 블록에서 emit.
    """
    agent: str           # provider 이름 또는 호출 caller (예: "AgentSDKProvider")
    department: str      # 일반적으로 ENGINEERING (LLM 호출 주체)
    role: str            # "llm_call"
    prompt_preview: str  # 첫 240자
    output_preview: str  # 첫 240자
    model: str = ""
    prompt_length: int = 0
    output_length: int = 0
    error: Optional[str] = None
    run_id: str = ""
    iteration: int = 0
    ts: str = field(default_factory=_now_ts)
    type: str = "agent_message"


@dataclass
class IterationProgressEvent:
    """Run 시작 / iteration boundary / run 종료.

    Tauri UI: progress 바 (1/3 → 2/3 → 3/3).
    """
    phase: str           # "run_start" | "iteration_begin" | "iteration_end" | "run_end"
    iteration: int       # 0 = run_start/run_end, 1+ = iteration boundary
    max_iterations: int
    run_id: str = ""
    detail: str = ""
    ts: str = field(default_factory=_now_ts)
    type: str = "iteration_progress"


@dataclass
class ResultEvent:
    """최종 verdict + 산출물. 결과 패널 1 라인 (Iterate/.exe/.exe 시 SKIPPED 등).

    run_iterative_loop finally 블록에서 emit.
    """
    verdict: str         # "COMPLETE" | "BLOCKED" | "IMPROVE_NEEDED"
    blocked_cause: str = ""
    iterations_run: int = 0
    max_iterations: int = 0
    exe_path: str = ""
    duration_sec: float = 0.0
    saved_dir: str = ""
    run_id: str = ""
    summary_line: str = ""  # format_iterative_summary 결과
    ts: str = field(default_factory=_now_ts)
    type: str = "result"


# ---------------------------------------------------------------------------
# TelemetryEmitter (싱글톤)
# ---------------------------------------------------------------------------
class TelemetryEmitter:
    """프로세스 전역 단일 emitter. 환경변수 ``NEXUS_TELEMETRY_PATH`` 로 활성화.

    스레드/프로세스 안전성:
        - 한 process 내 multi-thread emit: ``_lock`` 으로 직렬화.
        - multi-process tail (Tauri sidecar): line-atomic append 보장 (OS level).

    Fail-safety:
        - 첫 emit 시점에 디렉터리 생성 시도. 실패하면 disable + stderr 1회 경고.
        - 이후 emit 실패는 silent (재시도 X, stderr 폭주 방지).
    """

    _instance: Optional["TelemetryEmitter"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Optional[Path] = None
        self._enabled: bool = False
        self._warned: bool = False
        self._run_id: str = ""
        self._current_iteration: int = 0
        self._max_iterations: int = 0

        raw = (os.environ.get("NEXUS_TELEMETRY_PATH") or "").strip()
        if raw:
            try:
                p = Path(raw).expanduser()
                # parent 디렉터리 보장 (file 자체는 첫 emit 시 생성)
                p.parent.mkdir(parents=True, exist_ok=True)
                self._path = p
                self._enabled = True
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[Telemetry] NEXUS_TELEMETRY_PATH={raw!r} 초기화 실패 — 비활성 ({exc!r})",
                    file=sys.stderr,
                )

    # ------------------------------------------------------------------
    # 싱글톤 접근
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "TelemetryEmitter":
        """프로세스 전역 단일 emitter (Thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """테스트 전용 — 환경변수 변경 후 재초기화 강제. 운영 코드에서 호출 X."""
        with cls._instance_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # 활성화 / 컨텍스트
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def run_id(self) -> str:
        return self._run_id

    def begin_run(self, max_iterations: int = 0) -> str:
        """새 run 시작 시 run_id 생성 (없으면) 및 iteration 컨텍스트 초기화.

        Returns:
            run_id (UUID4 hex 12자) — 이미 set 됐으면 그대로 반환 (idempotent).
        """
        with self._lock:
            if not self._run_id:
                self._run_id = uuid.uuid4().hex[:12]
            self._max_iterations = max_iterations
            self._current_iteration = 0
            return self._run_id

    def set_iteration(self, iteration: int) -> None:
        """현재 iteration 갱신 (이후 emit 의 default context)."""
        with self._lock:
            self._current_iteration = iteration

    def end_run(self) -> None:
        """run_id / iteration 컨텍스트 초기화. 다음 begin_run 까지 idle."""
        with self._lock:
            self._run_id = ""
            self._current_iteration = 0
            self._max_iterations = 0

    # ------------------------------------------------------------------
    # 공개 emit API
    # ------------------------------------------------------------------
    def emit(self, event: Any) -> None:
        """단일 event dataclass 를 JSON Lines 한 줄로 file 에 append.

        Args:
            event: AgentStatusEvent / AgentMessageEvent / IterationProgressEvent /
                ResultEvent 중 하나. dataclass 가 아니어도 ``asdict``-호환 시 동작.
        """
        if not self._enabled or self._path is None:
            return
        # run_id 자동 주입 — 호출 측이 명시 안 한 경우 emitter 의 현재 컨텍스트 사용
        try:
            if hasattr(event, "run_id") and not getattr(event, "run_id", ""):
                event.run_id = self._run_id
            if hasattr(event, "iteration") and getattr(event, "iteration", 0) == 0:
                event.iteration = self._current_iteration
        except Exception:  # noqa: BLE001
            pass

        try:
            payload = asdict(event) if hasattr(event, "__dataclass_fields__") else dict(event)
        except Exception as exc:  # noqa: BLE001
            self._warn_once(f"event 직렬화 실패: {exc!r}")
            return

        try:
            line = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            self._warn_once(f"JSON 인코딩 실패: {exc!r}")
            return

        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as fp:
                    fp.write(line)
                    fp.write("\n")
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"file write 실패 ({self._path}): {exc!r}")

    # ------------------------------------------------------------------
    # 편의 helper — node wrapper 친화
    # ------------------------------------------------------------------
    def agent_working(self, node: str, detail: str = "") -> None:
        """``AgentStatusEvent(status=working)`` 단축 호출."""
        if not self._enabled:
            return
        self.emit(AgentStatusEvent(
            agent=node,
            department=department_for_node(node),
            status="working",
            detail=detail,
        ))

    def agent_done(self, node: str, detail: str = "") -> None:
        """``AgentStatusEvent(status=done)`` 단축 호출."""
        if not self._enabled:
            return
        self.emit(AgentStatusEvent(
            agent=node,
            department=department_for_node(node),
            status="done",
            detail=detail,
        ))

    def agent_error(self, node: str, error_msg: str) -> None:
        """``AgentStatusEvent(status=error)`` 단축 호출 — 노드 예외 surface."""
        if not self._enabled:
            return
        self.emit(AgentStatusEvent(
            agent=node,
            department=department_for_node(node),
            status="error",
            detail=error_msg,
        ))

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _warn_once(self, msg: str) -> None:
        """동일 process 내 stderr 경고 1회만 (폭주 방지) + 이후 emit disable."""
        if self._warned:
            return
        self._warned = True
        self._enabled = False
        print(f"[Telemetry] {msg} — 이후 emit 비활성", file=sys.stderr)


def get_telemetry_emitter() -> TelemetryEmitter:
    """싱글톤 ``TelemetryEmitter`` 인스턴스 반환."""
    return TelemetryEmitter.get_instance()


# ---------------------------------------------------------------------------
# 공개 export
# ---------------------------------------------------------------------------
__all__ = [
    "PLANNING",
    "ENGINEERING",
    "LEARNING",
    "SYSTEM",
    "department_for_node",
    "AgentStatusEvent",
    "AgentMessageEvent",
    "IterationProgressEvent",
    "ResultEvent",
    "TelemetryEmitter",
    "get_telemetry_emitter",
]
