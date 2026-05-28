# -*- coding: utf-8 -*-
"""Boardroom Facilitator — 본부 10 전략 이사회 의장 (v13 Phase 3 + Phase 4).

v12 Meeting Facilitator (kickoff 회의 진행) 가 v13 에서 격상된 형태.
Phase 2 System Refactoring Strategist 가 발제한 안건을 받아 *부서 대표 토론*
+ *C-Level 의결권 행사* 를 오케스트레이션하는 의장 노드.

Phase 진화 흐름:
    [Phase 1] RV silent fail 5회 누적 ─► Auto-Fix Coordinator escalate
                ▼
    [Phase 2] System Refactoring Strategist 안건 발제 (RefactoringProposal md)
                ▼
    [Phase 3] Boardroom Facilitator.convene_boardroom() ─► BoardroomSession
                ▼
              boardroom_trigger 노드 — 참석자 선정 + 의장권 부여
                ▼
    [Phase 4 ★] goal_alignment_check 노드 — Goal Alignment Agent 실 의결
                ▼
    [Phase 4 ★] budget_brake 노드 — Token Budget Optimizer 실 의결
                ▼
              outputs/_boardroom_sessions/<ts>_<session_id>.md (회의록)
              outputs/board_decisions/<ts>_<session_id>/decision.yaml (의결 로그)
                ▼
              final_decision: approved → build_workflow 허용
                              blocked  → build_workflow 차단

Telemetry: ``dept="planning"`` (boardroom_trigger — 본부 10 의장 역할)
           ``dept="c-level"`` (goal_alignment_check + budget_brake — 본부 0)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml


# ---------------------------------------------------------------------------
# 산출 schemas
# ---------------------------------------------------------------------------
@dataclass
class BoardroomSession:
    """이사회 회의 1건 — boardroom_trigger 산출.

    Attributes:
        session_id: 세션 식별자 (UUID4 hex 12자).
        agenda: 안건 제목 (Strategist proposal.title 인용).
        attendees: 참석 부서 대표 리스트.
        opened_at: 세션 개시 ISO8601 UTC.
        proposal_path: 발제 markdown 경로 (Strategist 산출).
        proposal: 발제 객체 (duck-typed, transient — markdown/yaml 미직렬화).
        alignment_result: Phase 4 의결 결과.
        budget_result: Phase 4 의결 결과.
        final_decision: alignment + budget 종합.
        closed_at: 세션 종료 시각.
    """

    session_id: str
    agenda: str
    attendees: list[str]
    opened_at: str
    proposal_path: str = ""
    proposal: Optional[Any] = None
    alignment_result: Optional["AlignmentCheckResult"] = None
    budget_result: Optional["BudgetBrakeResult"] = None
    final_decision: Optional["FinalDecision"] = None
    closed_at: str = ""


@dataclass
class AlignmentCheckResult:
    """Goal Alignment Agent 검토 결과 (Phase 4 활성화 — PR #222).

    Phase 4: 실 의결권 행사. status ∈ {"approved", "rejected"}.

    Attributes:
        status: "approved" 또는 "rejected".
        note: 의결 사유 (한국어 1~2문장).
        references: 검토 시 참조한 거버넌스 항목 (mission / security).
        checked_at: 의결 시각 ISO8601 UTC.
    """

    status: str
    note: str
    references: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: _now_ts())


@dataclass
class BudgetBrakeResult:
    """Token Budget Optimizer 검토 결과 (Phase 4 활성화 — PR #222).

    Phase 4: 실 비용 견적 + brake 결정. status ∈ {"approved", "throttled"}.

    Attributes:
        status: "approved" 또는 "throttled".
        estimated_cost_usd: 안건 적용 시 예상 추가 LLM 비용.
        budget_limit_usd: 현재 run 한도.
        cumulative_cost_usd: 이번 run 누적 비용.
        note: 의결 사유 (한국어 1~2문장).
        checked_at: 의결 시각.
    """

    status: str
    estimated_cost_usd: Optional[float]
    budget_limit_usd: Optional[float] = None
    cumulative_cost_usd: Optional[float] = None
    note: str = ""
    checked_at: str = field(default_factory=lambda: _now_ts())


@dataclass
class FinalDecision:
    """alignment + budget 종합 결과 (v13 Phase 4, PR #222).

    Attributes:
        outcome: "approved" 또는 "blocked".
        reason: 종합 사유 (한국어 1~2문장).
        blocked_by: blocked 시 ["alignment"] / ["budget"] / 둘 다. approved 면 [].
        decided_at: 종합 결정 시각.
    """

    outcome: str
    reason: str
    blocked_by: list[str] = field(default_factory=list)
    decided_at: str = field(default_factory=lambda: _now_ts())


def compute_final_decision(
    alignment: AlignmentCheckResult, budget: BudgetBrakeResult
) -> FinalDecision:
    """alignment.status + budget.status → FinalDecision.

    Rule (PM 확인 — OR 조건):
        alignment=rejected OR budget=throttled → blocked
        둘 다 approved → approved
    """
    blocked_by: list[str] = []
    if alignment.status != "approved":
        blocked_by.append("alignment")
    if budget.status != "approved":
        blocked_by.append("budget")

    if not blocked_by:
        return FinalDecision(
            outcome="approved",
            reason=(
                "alignment=approved AND budget=approved — build_workflow 진입 허용"
            ),
            blocked_by=[],
        )

    parts = []
    if "alignment" in blocked_by:
        parts.append(f"alignment={alignment.status}")
    if "budget" in blocked_by:
        parts.append(f"budget={budget.status}")
    return FinalDecision(
        outcome="blocked",
        reason=" + ".join(parts) + " — build_workflow 진입 차단",
        blocked_by=blocked_by,
    )


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
# Boardroom Facilitator — v13 전략 이사회 의장
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
    "  4. 합의 도출 — Phase 4 의결권 활성화: alignment + budget 종합\n"
    "  5. 회의록 보존 — outputs/_boardroom_sessions/ markdown + "
    "     outputs/board_decisions/<ts>_<session_id>/decision.yaml 의결 로그"
)

DEFAULT_BOARDROOM_ATTENDEES: list[str] = [
    "CTO",
    "GoalAlignmentAgent",
    "TokenBudgetOptimizer",
    "BuildEngineer",
    "PythonEngineer",
    "SystemRefactoringStrategist",
    "AutoFixCoordinator",
]


class BoardroomFacilitator:
    """전략 이사회 의장. 회의 라이프사이클 오케스트레이션."""

    def __init__(self, attendees: Optional[list[str]] = None) -> None:
        self._attendees = attendees or list(DEFAULT_BOARDROOM_ATTENDEES)

    def convene_boardroom(
        self, proposal: Any, proposal_path: str = ""
    ) -> BoardroomSession:
        """안건 발제 → 회의 세션 개시."""
        _emit("boardroom_facilitator", "working", "planning", "convene")
        session = BoardroomSession(
            session_id=uuid.uuid4().hex[:12],
            agenda=getattr(proposal, "title", "(제목 미지정)"),
            attendees=list(self._attendees),
            opened_at=_now_ts(),
            proposal_path=proposal_path,
            proposal=proposal,
        )
        _emit(
            "boardroom_facilitator",
            "done",
            "planning",
            f"session={session.session_id} agenda={session.agenda[:40]}",
        )
        return session

    def request_alignment_check(
        self,
        session: BoardroomSession,
        llm_call: Optional[Callable[[str], str]] = None,
    ) -> AlignmentCheckResult:
        """Goal Alignment Agent 의결 요청 (Phase 4 실 호출)."""
        from src.agents.c_level.goal_alignment_agent import assess_alignment

        result = assess_alignment(session.proposal, llm_call=llm_call)
        session.alignment_result = result
        return result

    def request_budget_brake(
        self,
        session: BoardroomSession,
        llm_call: Optional[Callable[[str], str]] = None,
        events_path: Optional[Path] = None,
    ) -> BudgetBrakeResult:
        """Token Budget Optimizer 의결 요청 (Phase 4 실 호출)."""
        from src.agents.c_level.token_budget_optimizer import assess_budget

        result = assess_budget(
            session.proposal, llm_call=llm_call, events_path=events_path
        )
        session.budget_result = result
        return result

    def summarize_discussion(self, session: BoardroomSession) -> str:
        """회의 요약 — Phase 5 UI 시각화 입력용."""
        alignment = session.alignment_result
        budget = session.budget_result
        final = session.final_decision
        return (
            f"[Boardroom #{session.session_id}] {session.agenda}\n"
            f"- 참석: {', '.join(session.attendees)}\n"
            f"- alignment: {alignment.status if alignment else 'not requested'}\n"
            f"- budget: {budget.status if budget else 'not requested'}\n"
            f"- final: {final.outcome if final else 'pending'}\n"
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
    llm_call: Optional[Callable[[str], str]] = None,
) -> AlignmentCheckResult:
    """goal_alignment_check 노드 — Goal Alignment Agent 실 의결 (Phase 4).

    Telemetry: ``dept="c-level"`` (본부 0).
    """
    _emit("goal_alignment_check", "working", "c-level", "assessing")
    fac = facilitator or BoardroomFacilitator()
    result = fac.request_alignment_check(session, llm_call=llm_call)
    _emit(
        "goal_alignment_check", "done", "c-level", f"status={result.status}"
    )
    return result


def node_budget_brake(
    session: BoardroomSession,
    facilitator: Optional[BoardroomFacilitator] = None,
    llm_call: Optional[Callable[[str], str]] = None,
    events_path: Optional[Path] = None,
) -> BudgetBrakeResult:
    """budget_brake 노드 — Token Budget Optimizer 실 의결 (Phase 4).

    Telemetry: ``dept="c-level"`` (본부 0).
    """
    _emit("budget_brake", "working", "c-level", "assessing")
    fac = facilitator or BoardroomFacilitator()
    result = fac.request_budget_brake(
        session, llm_call=llm_call, events_path=events_path
    )
    cost = result.estimated_cost_usd
    cost_str = f"{cost:.2f}" if cost is not None else "N/A"
    _emit(
        "budget_brake",
        "done",
        "c-level",
        f"status={result.status} est={cost_str}",
    )
    return result


# ---------------------------------------------------------------------------
# 회의록 markdown writer — outputs/_boardroom_sessions/<ts>_<session_id>.md
# ---------------------------------------------------------------------------
def write_boardroom_session_markdown(
    session: BoardroomSession, output_dir: Path
) -> Path:
    """BoardroomSession 을 회의록 markdown 으로 보존."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if not session.closed_at:
        session.closed_at = _now_ts()
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    md_path = output_dir / f"{timestamp}_{session.session_id}.md"

    alignment = session.alignment_result
    budget = session.budget_result
    final = session.final_decision

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
        "## Goal Alignment Check",
        "",
        f"- status: `{alignment.status if alignment else 'not requested'}`",
        f"- note: {alignment.note if alignment else '(skipped)'}",
    ])
    if alignment and alignment.references:
        lines.append(f"- references: {', '.join(alignment.references)}")
    lines.extend([
        "",
        "## Budget Brake",
        "",
        f"- status: `{budget.status if budget else 'not requested'}`",
        f"- estimated_cost_usd: {budget.estimated_cost_usd if budget else 'N/A'}",
        f"- budget_limit_usd: {budget.budget_limit_usd if budget else 'N/A'}",
        f"- cumulative_cost_usd: {budget.cumulative_cost_usd if budget else 'N/A'}",
        f"- note: {budget.note if budget else '(skipped)'}",
        "",
        "## Final Decision",
        "",
        f"- outcome: `{final.outcome if final else 'pending'}`",
        f"- reason: {final.reason if final else '(pending)'}",
        f"- blocked_by: {final.blocked_by if final else '[]'}",
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
                "final_outcome": final.outcome if final else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# 의결 로그 YAML writer — outputs/board_decisions/<ts>_<session_id>/decision.yaml
# (v13 Phase 4, PR #222)
# ---------------------------------------------------------------------------
DECISION_SCHEMA_VERSION = "v1"


def write_boardroom_decision_yaml(
    session: BoardroomSession, output_dir: Optional[Path] = None
) -> Path:
    """BoardroomSession 을 의결 로그 YAML 로 보존.

    Args:
        session: alignment + budget + final_decision 채워진 session.
        output_dir: 부모 디렉터리 — None 이면 ``outputs/board_decisions``.

    Returns:
        ``<output_dir>/<ts>_<session_id>/decision.yaml`` 경로.
    """
    base = output_dir or (Path("outputs") / "board_decisions")
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    run_dir = base / f"{timestamp}_{session.session_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = run_dir / "decision.yaml"

    alignment = session.alignment_result
    budget = session.budget_result
    final = session.final_decision

    payload: dict[str, Any] = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "session": {
            "session_id": session.session_id,
            "agenda": session.agenda,
            "proposal_path": session.proposal_path or None,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at or _now_ts(),
            "attendees": list(session.attendees),
        },
        "alignment": (
            {
                "status": alignment.status,
                "reason": alignment.note,
                "references": list(alignment.references),
                "checked_at": alignment.checked_at,
            }
            if alignment is not None
            else None
        ),
        "budget": (
            {
                "status": budget.status,
                "estimated_cost_usd": budget.estimated_cost_usd,
                "budget_limit_usd": budget.budget_limit_usd,
                "cumulative_cost_usd": budget.cumulative_cost_usd,
                "reason": budget.note,
                "checked_at": budget.checked_at,
            }
            if budget is not None
            else None
        ),
        "final_decision": (
            {
                "outcome": final.outcome,
                "reason": final.reason,
                "blocked_by": list(final.blocked_by),
                "decided_at": final.decided_at,
            }
            if final is not None
            else None
        ),
    }
    yaml_text = yaml.safe_dump(
        payload, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    yaml_path.write_text(yaml_text, encoding="utf-8")
    return yaml_path


# ---------------------------------------------------------------------------
# 풀체인 진입점 — Strategist 안건 → 회의 → 의결 → 회의록 + decision.yaml
# ---------------------------------------------------------------------------
def convene_full_boardroom_cycle(
    proposal: Any,
    proposal_path: str = "",
    output_dir: Optional[Path] = None,
    decision_output_dir: Optional[Path] = None,
    llm_call: Optional[Callable[[str], str]] = None,
    events_path: Optional[Path] = None,
    facilitator: Optional[BoardroomFacilitator] = None,
) -> tuple[BoardroomSession, Path, Path]:
    """안건 → 3 노드 순차 실행 → 회의록 + decision.yaml 저장.

    Args:
        proposal: ``RefactoringProposal`` duck-typed.
        proposal_path: 안건 markdown 경로 (옵션).
        output_dir: 회의록 markdown 저장 디렉터리 (옵션).
        decision_output_dir: 의결 로그 YAML 부모 디렉터리 (옵션).
        llm_call: 옵션 LLM caller — alignment + budget 양쪽에 동일하게 전달.
        events_path: 누적 비용 산출용 events.jsonl 경로 (옵션).
        facilitator: 기존 Facilitator 재사용 (옵션).

    Returns:
        (BoardroomSession, 회의록 markdown 경로, decision.yaml 경로).
    """
    fac = facilitator or BoardroomFacilitator()
    session = node_boardroom_trigger(
        proposal, proposal_path=proposal_path, facilitator=fac
    )
    alignment = node_goal_alignment_check(
        session, facilitator=fac, llm_call=llm_call
    )
    budget = node_budget_brake(
        session,
        facilitator=fac,
        llm_call=llm_call,
        events_path=events_path,
    )
    session.final_decision = compute_final_decision(alignment, budget)

    if output_dir is None:
        output_dir = Path("outputs") / "_boardroom_sessions"
    md_path = write_boardroom_session_markdown(session, output_dir)
    yaml_path = write_boardroom_decision_yaml(session, decision_output_dir)
    return session, md_path, yaml_path
