# -*- coding: utf-8 -*-
"""Boardroom 회의실 인프라 단위 test (v13 Phase 3, PR #221).

검증 범위:
    1. BoardroomSession / AlignmentCheckResult / BudgetBrakeResult dataclasses
    2. BoardroomFacilitator 격상 4 메소드 (convene / alignment / budget / summary)
    3. node_boardroom_trigger — 실 회의 세션 생성
    4. node_goal_alignment_check — Placeholder pending_phase4
    5. node_budget_brake — Placeholder pending_phase4
    6. write_boardroom_session_markdown — 회의록 파일 작성
    7. convene_full_boardroom_cycle — 풀체인 진입점
    8. Telemetry 부서 매핑 (planning + c-level) 검증
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.coordination.boardroom_facilitator import (
    DEFAULT_BOARDROOM_ATTENDEES,
    AlignmentCheckResult,
    BoardroomFacilitator,
    BoardroomSession,
    BudgetBrakeResult,
    convene_full_boardroom_cycle,
    node_boardroom_trigger,
    node_budget_brake,
    node_goal_alignment_check,
    write_boardroom_session_markdown,
)
from src.monitoring.telemetry import C_LEVEL, _NODE_DEPARTMENT, department_for_node


# =============================================================================
# 1. Dataclass schemas
# =============================================================================
class TestSchemas:
    def test_boardroom_session_fields(self) -> None:
        s = BoardroomSession(
            session_id="abc123",
            agenda="GUI sandbox 강화",
            attendees=["CTO", "GoalAlignmentAgent"],
            opened_at="2026-05-27T07:00:00Z",
            proposal_path="/x/y.md",
        )
        assert s.session_id == "abc123"
        assert s.alignment_result is None
        assert s.budget_result is None
        assert s.closed_at == ""

    def test_alignment_check_result_placeholder_status(self) -> None:
        r = AlignmentCheckResult(status="pending_phase4", note="대기")
        assert r.status == "pending_phase4"
        assert "Phase" in r.note or "대기" in r.note

    def test_budget_brake_result_placeholder_cost_none(self) -> None:
        r = BudgetBrakeResult(
            status="pending_phase4", estimated_cost_usd=None, note="대기"
        )
        assert r.status == "pending_phase4"
        assert r.estimated_cost_usd is None


# =============================================================================
# 2. ⭐ Boardroom Facilitator 격상 — 4 메소드
# =============================================================================
class TestBoardroomFacilitatorUpgrade:
    """⭐ v12 Meeting Facilitator → v13 전략 이사회 의장 격상."""

    def test_convene_creates_session_with_uuid(self) -> None:
        """convene_boardroom — session_id + opened_at 자동 생성."""
        fac = BoardroomFacilitator()
        proposal = SimpleNamespace(title="GUI sandbox 강화")
        session = fac.convene_boardroom(proposal, proposal_path="/tmp/p.md")
        assert session.agenda == "GUI sandbox 강화"
        assert len(session.session_id) == 12  # uuid4 hex 12자
        assert session.opened_at  # ISO8601 채워짐
        assert "GoalAlignmentAgent" in session.attendees  # default 참석자
        assert session.proposal_path == "/tmp/p.md"

    def test_request_alignment_check_placeholder(self) -> None:
        """request_alignment_check — pending_phase4 반환 + session.alignment_result 채움."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(SimpleNamespace(title="X"))
        result = fac.request_alignment_check(session)
        assert result.status == "pending_phase4"
        assert session.alignment_result is result
        assert "Goal Alignment Agent" in result.note

    def test_request_budget_brake_placeholder(self) -> None:
        """request_budget_brake — pending_phase4 + estimated_cost_usd=None."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(SimpleNamespace(title="X"))
        result = fac.request_budget_brake(session)
        assert result.status == "pending_phase4"
        assert result.estimated_cost_usd is None
        assert session.budget_result is result

    def test_summarize_discussion_includes_session_state(self) -> None:
        """summarize_discussion — Phase 5 UI 시각화 대비 짧은 markdown."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(SimpleNamespace(title="agenda X"))
        fac.request_alignment_check(session)
        fac.request_budget_brake(session)
        summary = fac.summarize_discussion(session)
        assert "agenda X" in summary
        assert "pending_phase4" in summary
        assert session.session_id in summary

    def test_custom_attendees_override_default(self) -> None:
        fac = BoardroomFacilitator(attendees=["OnlyCTO"])
        session = fac.convene_boardroom(SimpleNamespace(title="X"))
        assert session.attendees == ["OnlyCTO"]


# =============================================================================
# 3. Node 함수 3개
# =============================================================================
class TestNodeFunctions:
    def test_node_boardroom_trigger_creates_session(self) -> None:
        """boardroom_trigger 노드 — 안건 받아 세션 생성."""
        proposal = SimpleNamespace(title="silent fail 5회 → GUI 강화")
        session = node_boardroom_trigger(proposal, proposal_path="/x.md")
        assert isinstance(session, BoardroomSession)
        assert session.agenda == "silent fail 5회 → GUI 강화"
        assert session.proposal_path == "/x.md"

    def test_node_goal_alignment_check_returns_pending(self) -> None:
        """goal_alignment_check — Placeholder pending_phase4."""
        session = BoardroomSession(
            session_id="s1", agenda="X", attendees=[], opened_at="t",
        )
        result = node_goal_alignment_check(session)
        assert result.status == "pending_phase4"

    def test_node_budget_brake_returns_pending(self) -> None:
        """budget_brake — Placeholder pending_phase4."""
        session = BoardroomSession(
            session_id="s1", agenda="X", attendees=[], opened_at="t",
        )
        result = node_budget_brake(session)
        assert result.status == "pending_phase4"
        assert result.estimated_cost_usd is None


# =============================================================================
# 4. Markdown writer
# =============================================================================
class TestMarkdownWriter:
    def test_session_markdown_written(self, tmp_path: Path) -> None:
        """write_boardroom_session_markdown — 회의록 파일 생성 + 내용 검증."""
        session = BoardroomSession(
            session_id="abc12345",
            agenda="GUI sandbox 강화",
            attendees=["CTO", "GoalAlignmentAgent"],
            opened_at="2026-05-27T07:00:00Z",
            proposal_path="/tmp/p.md",
        )
        session.alignment_result = AlignmentCheckResult(
            status="pending_phase4", note="대기 중"
        )
        session.budget_result = BudgetBrakeResult(
            status="pending_phase4", estimated_cost_usd=None, note="대기 중"
        )
        md_path = write_boardroom_session_markdown(session, tmp_path)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "GUI sandbox 강화" in content
        assert "abc12345" in content
        assert "CTO" in content
        assert "pending_phase4" in content
        assert '"session_id": "abc12345"' in content  # JSON block

    def test_session_closed_at_auto_set(self, tmp_path: Path) -> None:
        """closed_at 미설정 시 writer 가 _now_ts() 로 자동 설정."""
        session = BoardroomSession(
            session_id="x", agenda="Y", attendees=[], opened_at="t",
        )
        assert session.closed_at == ""
        write_boardroom_session_markdown(session, tmp_path)
        assert session.closed_at  # ISO8601 자동 채움


# =============================================================================
# 5. ⭐ 풀체인 진입점 — convene_full_boardroom_cycle
# =============================================================================
class TestFullCycle:
    """⭐ 안건 → 3 노드 → 회의록 보존 풀체인 검증."""

    def test_full_cycle_writes_markdown(self, tmp_path: Path) -> None:
        proposal = SimpleNamespace(title="GUI sandbox 강화 — 5회 silent fail")
        session, md_path = convene_full_boardroom_cycle(
            proposal=proposal,
            proposal_path="/x/y.md",
            output_dir=tmp_path,
        )
        # 세션 객체 상태
        assert session.agenda == "GUI sandbox 강화 — 5회 silent fail"
        assert session.alignment_result is not None
        assert session.alignment_result.status == "pending_phase4"
        assert session.budget_result is not None
        assert session.budget_result.status == "pending_phase4"
        # markdown 파일
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Boardroom Session" in content
        assert session.session_id in content


# =============================================================================
# 6. Telemetry 부서 매핑 (planning + c-level)
# =============================================================================
class TestTelemetryDepartmentMapping:
    def test_c_level_constant(self) -> None:
        """⭐ C_LEVEL = 'c-level' 신규 부서 상수."""
        assert C_LEVEL == "c-level"

    def test_boardroom_trigger_is_planning(self) -> None:
        """boardroom_trigger — 본부 10 Coordination (planning)."""
        assert _NODE_DEPARTMENT["boardroom_trigger"] == "planning"
        assert department_for_node("boardroom_trigger") == "planning"

    def test_goal_alignment_check_is_c_level(self) -> None:
        """⭐ goal_alignment_check — C-Level (Phase 4 활성화)."""
        assert _NODE_DEPARTMENT["goal_alignment_check"] == "c-level"

    def test_budget_brake_is_c_level(self) -> None:
        """⭐ budget_brake — C-Level (Phase 4 활성화)."""
        assert _NODE_DEPARTMENT["budget_brake"] == "c-level"


# =============================================================================
# 7. CLI integration
# =============================================================================
class TestCLIIntegration:
    def test_enable_boardroom_flag_parses(self) -> None:
        """--enable-boardroom CLI flag 파싱."""
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = [
                "run.py", "--request", "X",
                "--enable-rv", "--enable-strategist", "--enable-boardroom",
                "--non-interactive",
            ]
            from scripts.run import _parse_args

            args = _parse_args()
            assert args.enable_boardroom is True
            assert args.enable_strategist is True  # 독립 flag
            assert args.enable_rv is True
        finally:
            _sys.argv = prev

    def test_run_iterative_loop_accepts_enable_boardroom(self) -> None:
        """run_iterative_loop 시그니처 + default=False."""
        import inspect

        from src.workflows.iterative_loop import run_iterative_loop

        sig = inspect.signature(run_iterative_loop)
        assert "enable_boardroom" in sig.parameters
        assert sig.parameters["enable_boardroom"].default is False
