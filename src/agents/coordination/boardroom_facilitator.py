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
class Statement:
    """티키타카 라운드 1건의 발언 — Cross-Agent Consultant 산출 (v13 Phase 5.4).

    Attributes:
        agent: 발언자 (예: "SystemRefactoringStrategist", "CTO", "AutoFixCoordinator").
        role: ``proposer`` / ``reviewer`` / ``dissenter`` / ``mediator``.
            발언의 *맥락* — 안건 발제 / 1차 검토 / 반박 / 중재 / 동의.
        content: 발언 내용 (한국어 1~3문장).
        timestamp: 발언 시각 ISO8601 UTC.
    """

    agent: str
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: _now_ts())


@dataclass
class Round:
    """이사회 1 라운드 — N개 Statement 의 결과 (v13 Phase 5.4).

    Attributes:
        round_num: 1, 2, 3 (최대 3 하드 캡).
        statements: 라운드 내 모든 발언 (시간순).
        dissent_detected: 반박 의견이 있는지 여부 — 다음 라운드 진입 조건.
        started_at / ended_at: ISO8601.
    """

    round_num: int
    statements: list[Statement] = field(default_factory=list)
    dissent_detected: bool = False
    started_at: str = field(default_factory=lambda: _now_ts())
    ended_at: str = ""


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
        rounds: Phase 5.4 ★ 티키타카 라운드 기록 (직렬 의결 모드에서는 빈 list).
        consensus: Phase 5.4 ★ Facilitator 가 라운드 종합으로 도출한 타협안
            (라운드 진행 안 했거나 미도출 시 None).
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
    rounds: list[Round] = field(default_factory=list)
    consensus: Optional[str] = None
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
    # v13 Phase 5.4 (PR #224) — 라운드 + consensus (있을 때만)
    if session.rounds:
        lines.extend(["", "## Tikitaka Rounds (Phase 5.4)", ""])
        for r in session.rounds:
            lines.append(
                f"### Round {r.round_num} "
                f"({'dissent ⚠️' if r.dissent_detected else 'consensus ✓'})"
            )
            lines.append("")
            for s in r.statements:
                lines.append(
                    f"- **[{s.role}] {s.agent}** ({s.timestamp}): {s.content}"
                )
            lines.append("")
        if session.consensus:
            lines.extend(["### Consensus", "", f"{session.consensus}", ""])

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
# (v13 Phase 4 v1 → Phase 5.4 v2 — rounds + consensus 추가, PR #224)
# ---------------------------------------------------------------------------
DECISION_SCHEMA_VERSION = "v2"


def write_boardroom_decision_yaml(
    session: BoardroomSession, output_dir: Optional[Path] = None
) -> Path:
    """BoardroomSession 을 의결 로그 YAML 로 보존.

    Schema v2 (Phase 5.4, PR #224) — v1 (Phase 4) 에 ``rounds`` + ``consensus``
    추가. 직렬 의결 모드 (rounds=빈 list) 도 v2 schema 로 작성.

    Args:
        session: alignment + budget + final_decision + (옵션) rounds/consensus 채워진 session.
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
        # Phase 5.4 (PR #224) ★ rounds + consensus
        "rounds": [
            {
                "round_num": r.round_num,
                "started_at": r.started_at,
                "ended_at": r.ended_at or _now_ts(),
                "dissent_detected": r.dissent_detected,
                "statements": [
                    {
                        "agent": s.agent,
                        "role": s.role,
                        "content": s.content,
                        "timestamp": s.timestamp,
                    }
                    for s in r.statements
                ],
            }
            for r in session.rounds
        ],
        "consensus": session.consensus,
    }
    yaml_text = yaml.safe_dump(
        payload, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    yaml_path.write_text(yaml_text, encoding="utf-8")
    return yaml_path


# ---------------------------------------------------------------------------
# v13 Phase 5.4 (PR #224) — 티키타카 라운드 sequence
# ---------------------------------------------------------------------------
MAX_BOARDROOM_ROUNDS = 3  # 무한 토론 방지 — 라운드 max 3 하드 캡


def _proposal_to_context(proposal: Any) -> str:
    """Proposal duck-typed object → prompt context 문자열."""
    title = str(getattr(proposal, "title", "(제목 미지정)"))
    rca = str(getattr(proposal, "root_cause_analysis", ""))
    changes = getattr(proposal, "proposed_changes", []) or []
    if isinstance(changes, (list, tuple)):
        changes_text = "\n".join(f"- {c}" for c in changes)
    else:
        changes_text = str(changes)
    return (
        f"제목: {title}\n"
        f"근본 원인 분석: {rca or '(미제공)'}\n"
        f"제안 변경사항:\n{changes_text or '(없음)'}"
    )


def _run_tikitaka_rounds(
    session: BoardroomSession,
    llm_call: Optional[Callable[[str], str]],
    events_path: Optional[Path],
) -> None:
    """티키타카 라운드 sequence — session.rounds 누적 + consensus 도출.

    동작:
        Round 1: proposer + 1차 reviewer 발언 수집
        Round 2 (dissent 발견 시만): 반박자 재발언 + 추가 reviewer
        Round 3 (여전히 dissent 시만): Facilitator 중재 (mediator)
        consensus: 마지막 라운드 mediator 발언 OR 라운드 1 종합

    안전 장치:
        - 라운드 시작 시 budget 누적 확인 (assess_budget) — throttled 즉시 종료
        - 라운드 max 3 (CrossAgentConsultant.conduct_round 검증)
    """
    # 순환 import 회피
    from src.agents.coordination.cross_agent_consultant import (
        conduct_round,
        collect_dissent,
    )
    from src.agents.c_level.token_budget_optimizer import assess_budget

    proposal_context = _proposal_to_context(session.proposal)
    accumulated_statements: list[Statement] = []
    dissenters: list[str] = []

    for round_num in range(1, MAX_BOARDROOM_ROUNDS + 1):
        # 라운드 시작 시 budget 누적 체크 — throttled 면 즉시 종료
        check = assess_budget(session.proposal, events_path=events_path)
        if check.status == "throttled":
            # consensus 미도출 → final_decision 에서 blocked 처리됨
            session.consensus = (
                f"라운드 {round_num} 시작 전 budget throttled — 토론 중단"
            )
            _emit(
                "cross_agent_consultant",
                "done",
                "planning",
                f"throttled_at_round_{round_num} reason=budget brake",
            )
            return

        _emit(
            "cross_agent_consultant",
            "working",
            "planning",
            f"round={round_num} speakers=tikitaka",
        )

        result = conduct_round(
            round_num=round_num,
            proposal_context=proposal_context,
            prior_statements=accumulated_statements,
            dissenters_from_prev=dissenters,
            llm_call=llm_call,
        )

        session.rounds.append(result.round)
        accumulated_statements.extend(result.round.statements)
        dissenters = collect_dissent(
            [
                # AgentResponse 재구성 (round.statements 의 role 이 dissenter 거나
                # content 에 dissent 키워드)
                _AgentResponseLike(s)
                for s in result.round.statements
            ]
        )

        _emit(
            "cross_agent_consultant",
            "done",
            "planning",
            f"round={round_num} statements={len(result.round.statements)} "
            f"dissent={result.round.dissent_detected}",
        )

        # 마지막 라운드 (mediator) 발언을 consensus 로 보존
        if round_num == 3 or not result.proceed_to_next:
            if result.round.statements:
                last_stmt = result.round.statements[-1]
                if last_stmt.role == "mediator":
                    session.consensus = last_stmt.content
                elif not session.consensus:
                    # mediator 안 거치고 종료 — 마지막 발언 인용
                    session.consensus = (
                        f"라운드 {round_num} 종료 — dissent 없음. "
                        f"마지막 발언 채택: {last_stmt.content}"
                    )
            return


class _AgentResponseLike:
    """conduct_round 의 statements 를 collect_dissent 가 받을 수 있게 어댑팅.

    AgentResponse 의 ``is_dissent`` 속성을 흉내내는 가벼운 wrapper.
    """

    def __init__(self, statement: Statement) -> None:
        from src.agents.coordination.cross_agent_consultant import _detect_dissent

        self.agent = statement.agent
        self.role = statement.role
        self.is_dissent = statement.role == "dissenter" or _detect_dissent(
            statement.content
        )


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
    enable_tikitaka: bool = False,
) -> tuple[BoardroomSession, Path, Path]:
    """안건 → 회의 → 의결 → 회의록 + decision.yaml 저장.

    Phase 4 모드 (enable_tikitaka=False, default — 회귀 0 보존):
        boardroom_trigger → goal_alignment_check → budget_brake → 직렬 의결

    Phase 5.4 ★ 티키타카 모드 (enable_tikitaka=True, PR #224):
        boardroom_trigger
          ↓
        Round 1 (proposer + reviewers)
          ↓ dissent?
        Round 2 (dissenters 재발언)
          ↓ dissent?
        Round 3 (Facilitator 중재 — mediator)
          ↓
        goal_alignment_check + budget_brake (consensus 반영)
          ↓
        write markdown + decision.yaml (schema v2 rounds[] + consensus)

    Args:
        proposal: ``RefactoringProposal`` duck-typed (``.title`` + 옵션
            ``.proposed_changes`` / ``.root_cause_analysis``).
        proposal_path: 안건 markdown 경로 (옵션).
        output_dir: 회의록 markdown 디렉터리.
        decision_output_dir: decision.yaml 부모 디렉터리.
        llm_call: 동기 LLM 호출 (alignment + budget + 라운드 발언 모두 동일).
        events_path: events.jsonl (누적 비용 산출용).
        facilitator: 기존 인스턴스 재사용 (옵션).
        enable_tikitaka: True 면 Phase 5.4 양방향 라운드. default False 회귀 안전.

    Returns:
        (BoardroomSession, 회의록 markdown 경로, decision.yaml 경로).
    """
    fac = facilitator or BoardroomFacilitator()
    session = node_boardroom_trigger(
        proposal, proposal_path=proposal_path, facilitator=fac
    )

    # Phase 5.4 ★ 티키타카 라운드 (옵션)
    if enable_tikitaka:
        _run_tikitaka_rounds(session, llm_call=llm_call, events_path=events_path)

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
