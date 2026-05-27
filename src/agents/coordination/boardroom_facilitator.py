# -*- coding: utf-8 -*-
"""Boardroom Facilitator — 본부 10 전략 이사회 의장 (v13 Phase 3, PR #221).

v12 Meeting Facilitator (kickoff 회의 진행) 가 v13 에서 격상된 형태.
Phase 2 System Refactoring Strategist 가 발제한 안건을 받아 *부서 대표 토론*
+ *C-Level 의결 요청* 을 오케스트레이션하는 의장 노드.

핵심 흐름 (Phase 1 + 2 + 3 메타 루프):
    [Phase 1] RV silent fail 5회 누적 ─► Auto-Fix Coordinator escalate
                ▼
    [Phase 2] System Refactoring Strategist 안건 발제 (RefactoringProposal md)
                ▼
    [Phase 3] ★ Boardroom Facilitator.convene_boardroom() ─► BoardroomSession
                ▼
              boardroom_trigger 노드 — 참석자 선정 + 의장권 부여
                ▼
              goal_alignment_check (Placeholder, Phase 4 교체)
                ▼
              budget_brake       (Placeholder, Phase 4 교체)
                ▼
              outputs/_boardroom_sessions/<ts>_<session_id>.md 저장
                ▼
    [Phase 4 예정] 의결권 활성화 후 자동 적용

Phase 3 한계: BoardroomSession markdown 보존만 (자동 적용 X).
Telemetry: ``dept="planning"`` (boardroom_trigger) / ``dept="c-level"``
(goal_alignment_check, budget_brake — 새 부서 식별자).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 산출 schemas
# ---------------------------------------------------------------------------
@dataclass
class BoardroomSession:
    """이사회 회의 1건 — boardroom_trigger 산출.

    Attributes:
        session_id: 세션 식별자 (UUID4 hex 12자, run_id 와 동일 포맷).
        agenda: 안건 제목 (Strategist proposal.title 인용).
        attendees: 참석 부서 대표 리스트 (Phase 3 = 결정론, Phase 4 = 동적).
        opened_at: 세션 개시 ISO8601 UTC.
        proposal_path: 발제 markdown 경로 (Strategist 산출).
        alignment_result: AlignmentCheckResult | None — Phase 4 의결 후 채워짐.
        budget_result: BudgetBrakeResult | None — Phase 4 의결 후 채워짐.
        closed_at: 세션 종료 시각. Phase 3 는 즉시 close.
    """

    session_id: str
    agenda: str
    attendees: list[str]
    opened_at: str
    proposal_path: str = ""
    alignment_result: Optional["AlignmentCheckResult"] = None
    budget_result: Optional["BudgetBrakeResult"] = None
    closed_at: str = ""


@dataclass
class AlignmentCheckResult:
    """Goal Alignment Agent 검토 결과 (Phase 4 활성화).

    Phase 3 한계: 항상 ``status="pending_phase4"`` 반환.

    TODO(Phase 4): Goal Alignment Agent LLM 호출 로직으로 교체.
        - 입력: BoardroomSession + 프로젝트 mission/security 거버넌스 docs
        - 출력: status="approved"/"rejected" + reason
    """

    status: str
    note: str
    checked_at: str = field(default_factory=lambda: _now_ts())


@dataclass
class BudgetBrakeResult:
    """Token Budget Optimizer 검토 결과 (Phase 4 활성화).

    Phase 3 한계: 항상 ``status="pending_phase4"`` 반환.

    TODO(Phase 4): Token Budget Optimizer 실 비용 견적 + brake 결정.
        - 입력: BoardroomSession + 누적 token usage history
        - 출력: status="approved"/"throttled" + estimated_cost_usd
    """

    status: str
    estimated_cost_usd: Optional[float]
    note: str
    checked_at: str = field(default_factory=lambda: _now_ts())


# ---------------------------------------------------------------------------
# Telemetry helpers
# ---------------------------------------------------------------------------
def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _emit(agent: str, status: str, department: str, detail: str = "") -> None:
    """Telemetry emit — 실패 silent."""
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
                department=department,
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Boardroom Facilitator — 역할 격상 (v12 Meeting → v13 전략 이사회 의장)
# ---------------------------------------------------------------------------
BOARDROOM_FACILITATOR_NAME = "BoardroomFacilitator"
BOARDROOM_FACILITATOR_ROLE = "Senior Strategic Boardroom Chairperson (v13)"
BOARDROOM_FACILITATOR_GOAL = (
    "Telemetry 기반 시스템 자율 개선안 (System Refactoring Strategist 발제) 을 "
    "받아 부서 대표 + C-Level 의결권자들이 모인 *전략 이사회* 의장을 수행한다. "
    "안건 토론 → 의결 요청 (Goal Alignment + Token Budget) → 결과 보존."
)
BOARDROOM_FACILITATOR_BACKSTORY = (
    "당신은 본부 10 (Coordination/Communication) 의 격상된 의장입니다. "
    "v12 의 kickoff_meeting 진행자가 v13 에서 *전략 이사회 의장* 으로 격상.\n\n"
    "v13 책임:\n"
    "  1. 안건 접수 — System Refactoring Strategist 가 발제한 RefactoringProposal\n"
    "  2. 회의 소집 — BoardroomSession 생성 (참석자 결정론 선정)\n"
    "  3. 의결 요청 — Goal Alignment Agent + Token Budget Optimizer\n"
    "  4. 합의 도출 — Phase 4 의결권 활성화 후 자동 적용 가능\n"
    "  5. 회의록 보존 — outputs/_boardroom_sessions/ 에 markdown 저장\n\n"
    "Phase 3 한계: 의결권자 2명은 Placeholder. 회의 인프라 + 회의록 보존만 동작."
)

# 기본 참석자 (Phase 3 결정론 — Phase 4 에서 동적 라우팅)
DEFAULT_BOARDROOM_ATTENDEES: list[str] = [
    "CTO",
    "GoalAlignmentAgent",          # C-Level (Placeholder)
    "TokenBudgetOptimizer",        # C-Level (Placeholder)
    "BuildEngineer",                # 본부 4 — 빌드 결함 대응
    "PythonEngineer",               # 본부 3 — 코드 결함 대응
    "SystemRefactoringStrategist",  # 본부 1 — 안건 발제자 (Phase 2)
    "AutoFixCoordinator",           # 본부 9 — 감지 결과 (Phase 1)
]


class BoardroomFacilitator:
    """전략 이사회 의장. 4개 공개 메소드로 회의 라이프사이클 오케스트레이션."""

    def __init__(self, attendees: Optional[list[str]] = None) -> None:
        self._attendees = attendees or list(DEFAULT_BOARDROOM_ATTENDEES)

    def convene_boardroom(self, proposal: Any, proposal_path: str = "") -> BoardroomSession:
        """안건 발제 → 회의 세션 개시.

        Args:
            proposal: ``RefactoringProposal`` (duck-typed: ``.title`` 속성만 필요).
            proposal_path: 안건 markdown 파일 경로 (옵션).

        Returns:
            BoardroomSession.
        """
        _emit("boardroom_facilitator", "working", "planning", "convene")
        session = BoardroomSession(
            session_id=uuid.uuid4().hex[:12],
            agenda=getattr(proposal, "title", "(제목 미지정)"),
            attendees=list(self._attendees),
            opened_at=_now_ts(),
            proposal_path=proposal_path,
        )
        _emit(
            "boardroom_facilitator",
            "done",
            "planning",
            f"session={session.session_id} agenda={session.agenda[:40]}",
        )
        return session

    def request_alignment_check(
        self, session: BoardroomSession
    ) -> AlignmentCheckResult:
        """Goal Alignment Agent 의결 요청 (Phase 3 Placeholder).

        TODO(Phase 4): 실 LLM 호출로 교체.
        """
        result = AlignmentCheckResult(
            status="pending_phase4",
            note=(
                "Phase 4 의결권 활성화 대기 중 — Goal Alignment Agent 가 "
                "mission/security 거버넌스 docs 와 대조하여 approved/rejected 산출 예정."
            ),
        )
        session.alignment_result = result
        return result

    def request_budget_brake(self, session: BoardroomSession) -> BudgetBrakeResult:
        """Token Budget Optimizer 의결 요청 (Phase 3 Placeholder).

        TODO(Phase 4): 실 비용 견적 + brake 결정 로직으로 교체.
        """
        result = BudgetBrakeResult(
            status="pending_phase4",
            estimated_cost_usd=None,
            note=(
                "Phase 4 의결권 활성화 대기 중 — Token Budget Optimizer 가 "
                "누적 token usage + 예산 한도 대조 → approved/throttled 산출 예정."
            ),
        )
        session.budget_result = result
        return result

    def summarize_discussion(self, session: BoardroomSession) -> str:
        """회의 요약 — Phase 5 UI 시각화 입력용 짧은 markdown."""
        alignment = session.alignment_result
        budget = session.budget_result
        return (
            f"[Boardroom #{session.session_id}] {session.agenda}\n"
            f"- 참석: {', '.join(session.attendees)}\n"
            f"- alignment: {alignment.status if alignment else 'not requested'}\n"
            f"- budget: {budget.status if budget else 'not requested'}\n"
        )


# ---------------------------------------------------------------------------
# Node 함수 3개 — iterative_loop / boardroom_workflow 에서 호출 가능
# ---------------------------------------------------------------------------
def node_boardroom_trigger(
    proposal: Any,
    proposal_path: str = "",
    facilitator: Optional[BoardroomFacilitator] = None,
) -> BoardroomSession:
    """boardroom_trigger 노드 — Strategist 안건을 받아 회의 세션 생성.

    Telemetry: ``dept="planning"`` (본부 10 Coordination).
    """
    _emit("boardroom_trigger", "working", "planning", "convening")
    fac = facilitator or BoardroomFacilitator()
    session = fac.convene_boardroom(proposal, proposal_path=proposal_path)
    _emit(
        "boardroom_trigger",
        "done",
        "planning",
        f"session={session.session_id} attendees={len(session.attendees)}",
    )
    return session


def node_goal_alignment_check(
    session: BoardroomSession,
    facilitator: Optional[BoardroomFacilitator] = None,
) -> AlignmentCheckResult:
    """goal_alignment_check 노드 — Placeholder (Phase 4 교체 예정).

    Telemetry: ``dept="c-level"`` (신규 부서 키).
    TODO(Phase 4): Goal Alignment Agent LLM 호출 로직으로 교체.
    """
    _emit("goal_alignment_check", "working", "c-level", "placeholder")
    fac = facilitator or BoardroomFacilitator()
    result = fac.request_alignment_check(session)
    _emit(
        "goal_alignment_check", "done", "c-level", f"status={result.status}"
    )
    return result


def node_budget_brake(
    session: BoardroomSession,
    facilitator: Optional[BoardroomFacilitator] = None,
) -> BudgetBrakeResult:
    """budget_brake 노드 — Placeholder (Phase 4 교체 예정).

    Telemetry: ``dept="c-level"`` (신규 부서 키).
    TODO(Phase 4): Token Budget Optimizer 실 비용 견적 + brake 결정으로 교체.
    """
    _emit("budget_brake", "working", "c-level", "placeholder")
    fac = facilitator or BoardroomFacilitator()
    result = fac.request_budget_brake(session)
    _emit("budget_brake", "done", "c-level", f"status={result.status}")
    return result


# ---------------------------------------------------------------------------
# 회의록 markdown writer — outputs/_boardroom_sessions/<ts>_<session_id>.md
# ---------------------------------------------------------------------------
def write_boardroom_session_markdown(
    session: BoardroomSession, output_dir: Path
) -> Path:
    """BoardroomSession 을 회의록 markdown 으로 보존.

    Phase 3 한계: 자동 적용 X — Phase 4 의결권 활성화 후 의결 결과로 분기.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if not session.closed_at:
        session.closed_at = _now_ts()
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    md_path = output_dir / f"{timestamp}_{session.session_id}.md"

    alignment = session.alignment_result
    budget = session.budget_result

    lines = [
        f"# Boardroom Session — {session.agenda}",
        "",
        f"- **session_id**: `{session.session_id}`",
        f"- **opened_at**: {session.opened_at}",
        f"- **closed_at**: {session.closed_at}",
        f"- **proposal_path**: `{session.proposal_path or '(미지정)'}`",
        "",
        "## Attendees",
        "",
    ]
    for a in session.attendees:
        lines.append(f"- {a}")
    lines.extend([
        "",
        "## Goal Alignment Check (Phase 4 Placeholder)",
        "",
        f"- status: `{alignment.status if alignment else 'not requested'}`",
        f"- note: {alignment.note if alignment else '(skipped)'}",
        "",
        "## Budget Brake (Phase 4 Placeholder)",
        "",
        f"- status: `{budget.status if budget else 'not requested'}`",
        f"- estimated_cost_usd: {budget.estimated_cost_usd if budget else 'N/A'}",
        f"- note: {budget.note if budget else '(skipped)'}",
        "",
        "## Session Summary (machine-readable)",
        "",
        "```json",
        json.dumps(
            {
                "session_id": session.session_id,
                "agenda": session.agenda,
                "attendees": session.attendees,
                "opened_at": session.opened_at,
                "closed_at": session.closed_at,
                "alignment_status": alignment.status if alignment else None,
                "budget_status": budget.status if budget else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "---",
        "",
        "*Phase 3 한계 — 본 회의록은 markdown 보존만. Phase 4 의결권 활성화 후",
        "Goal Alignment Agent + Token Budget Optimizer 가 실 의결 결과 산출 예정.*",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# 풀체인 진입점 — Strategist 안건 → 회의 → 회의록 (1회 호출)
# ---------------------------------------------------------------------------
def convene_full_boardroom_cycle(
    proposal: Any,
    proposal_path: str = "",
    output_dir: Optional[Path] = None,
    facilitator: Optional[BoardroomFacilitator] = None,
) -> tuple[BoardroomSession, Path]:
    """안건 → 3 노드 순차 실행 → 회의록 저장.

    Returns:
        (BoardroomSession, markdown 경로).
    """
    fac = facilitator or BoardroomFacilitator()
    session = node_boardroom_trigger(proposal, proposal_path=proposal_path, facilitator=fac)
    node_goal_alignment_check(session, facilitator=fac)
    node_budget_brake(session, facilitator=fac)

    if output_dir is None:
        output_dir = Path("outputs") / "_boardroom_sessions"
    md_path = write_boardroom_session_markdown(session, output_dir)
    return session, md_path
