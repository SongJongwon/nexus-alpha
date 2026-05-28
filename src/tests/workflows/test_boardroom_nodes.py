# -*- coding: utf-8 -*-
"""Boardroom 회의실 인프라 단위 test (v13 Phase 3 + Phase 4, PR #221 + #222).

검증 범위:
    1. BoardroomSession / AlignmentCheckResult / BudgetBrakeResult / FinalDecision
       dataclasses
    2. BoardroomFacilitator 격상 5 메소드 (convene / alignment / budget / summary
       + Phase 4 실 의결 결과 채움)
    3. node_boardroom_trigger — 실 회의 세션 생성
    4. node_goal_alignment_check — 실 의결 (approved / rejected 분기)
    5. node_budget_brake — 실 의결 (approved / throttled 분기)
    6. compute_final_decision — alignment + budget OR 종합
    7. write_boardroom_session_markdown — 회의록 파일 작성
    8. write_boardroom_decision_yaml — Phase 4 의결 로그 YAML (PR #222)
    9. convene_full_boardroom_cycle — 풀체인 진입점 (3-tuple 반환)
    10. Telemetry 부서 매핑 (planning + c-level)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.coordination.boardroom_facilitator import (
    DECISION_SCHEMA_VERSION,
    DEFAULT_BOARDROOM_ATTENDEES,
    AlignmentCheckResult,
    BoardroomFacilitator,
    BoardroomSession,
    BudgetBrakeResult,
    FinalDecision,
    compute_final_decision,
    convene_full_boardroom_cycle,
    node_boardroom_trigger,
    node_budget_brake,
    node_goal_alignment_check,
    write_boardroom_decision_yaml,
    write_boardroom_session_markdown,
)
from src.monitoring.telemetry import C_LEVEL, _NODE_DEPARTMENT, department_for_node


def _make_proposal(
    title: str = "GUI sandbox 강화",
    estimated_cost: str = "medium",
    proposed_changes: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        estimated_cost=estimated_cost,
        proposed_changes=proposed_changes or [],
    )


# =============================================================================
# 1. Dataclass schemas
# =============================================================================
class TestSchemas:
    def test_boardroom_session_fields(self) -> None:
        s = BoardroomSession(
            session_id="abc123",
            agenda="GUI sandbox 강화",
            attendees=["CTO", "GoalAlignmentAgent"],
            opened_at="2026-05-28T07:00:00Z",
            proposal_path="/x/y.md",
        )
        assert s.session_id == "abc123"
        assert s.alignment_result is None
        assert s.budget_result is None
        assert s.final_decision is None
        assert s.closed_at == ""

    def test_alignment_check_result_approved_status(self) -> None:
        r = AlignmentCheckResult(status="approved", note="mission 부합")
        assert r.status == "approved"
        assert r.references == []  # default

    def test_alignment_check_result_rejected_with_references(self) -> None:
        r = AlignmentCheckResult(
            status="rejected",
            note="security 위배",
            references=["mission.md", "security.md"],
        )
        assert r.status == "rejected"
        assert len(r.references) == 2

    def test_budget_brake_result_extended_fields(self) -> None:
        """⭐ Phase 4 — budget_limit_usd / cumulative_cost_usd 추가."""
        r = BudgetBrakeResult(
            status="approved",
            estimated_cost_usd=0.5,
            budget_limit_usd=15.0,
            cumulative_cost_usd=3.0,
            note="잔여 11.5 USD",
        )
        assert r.status == "approved"
        assert r.budget_limit_usd == 15.0
        assert r.cumulative_cost_usd == 3.0

    def test_final_decision_approved_empty_blocked_by(self) -> None:
        """⭐ FinalDecision — approved 시 blocked_by 빈 list."""
        f = FinalDecision(outcome="approved", reason="둘 다 통과")
        assert f.outcome == "approved"
        assert f.blocked_by == []

    def test_final_decision_blocked_lists_blockers(self) -> None:
        f = FinalDecision(
            outcome="blocked",
            reason="alignment=rejected",
            blocked_by=["alignment"],
        )
        assert f.outcome == "blocked"
        assert "alignment" in f.blocked_by


# =============================================================================
# 2. ⭐ compute_final_decision — OR 종합 (PM 확인)
# =============================================================================
class TestComputeFinalDecision:
    """⭐ PM 확인 결정 #2 — alignment=rejected OR budget=throttled → blocked."""

    def test_both_approved_yields_approved(self) -> None:
        a = AlignmentCheckResult(status="approved", note="OK")
        b = BudgetBrakeResult(status="approved", estimated_cost_usd=0.5, note="OK")
        f = compute_final_decision(a, b)
        assert f.outcome == "approved"
        assert f.blocked_by == []

    def test_alignment_rejected_yields_blocked(self) -> None:
        a = AlignmentCheckResult(status="rejected", note="security 위배")
        b = BudgetBrakeResult(status="approved", estimated_cost_usd=0.5, note="OK")
        f = compute_final_decision(a, b)
        assert f.outcome == "blocked"
        assert f.blocked_by == ["alignment"]

    def test_budget_throttled_yields_blocked(self) -> None:
        a = AlignmentCheckResult(status="approved", note="OK")
        b = BudgetBrakeResult(status="throttled", estimated_cost_usd=20.0, note="초과")
        f = compute_final_decision(a, b)
        assert f.outcome == "blocked"
        assert f.blocked_by == ["budget"]

    def test_both_failed_lists_both_blockers(self) -> None:
        a = AlignmentCheckResult(status="rejected", note="X")
        b = BudgetBrakeResult(status="throttled", estimated_cost_usd=20.0, note="Y")
        f = compute_final_decision(a, b)
        assert f.outcome == "blocked"
        assert set(f.blocked_by) == {"alignment", "budget"}


# =============================================================================
# 3. ⭐ Boardroom Facilitator 격상 + Phase 4 실 의결
# =============================================================================
class TestBoardroomFacilitator:
    def test_convene_creates_session_with_uuid(self) -> None:
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(_make_proposal(), proposal_path="/tmp/p.md")
        assert session.agenda == "GUI sandbox 강화"
        assert len(session.session_id) == 12
        assert session.opened_at
        assert "GoalAlignmentAgent" in session.attendees
        assert session.proposal_path == "/tmp/p.md"
        assert session.proposal is not None  # Phase 4: 의결 평가용 transient ref

    def test_request_alignment_approved_default(self) -> None:
        """⭐ Phase 4 — clean 안건 → forbidden 없음 → approved (default)."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(_make_proposal(title="합법 안건"))
        result = fac.request_alignment_check(session)
        assert result.status == "approved"
        assert session.alignment_result is result

    def test_request_alignment_rejected_forbidden_keyword(self) -> None:
        """⭐ Phase 4 — forbidden 키워드 → 즉시 rejected."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(
            _make_proposal(title="QA 우회 — 빌드 강제 통과")
        )
        result = fac.request_alignment_check(session)
        assert result.status == "rejected"
        assert "위배" in result.note or "forbidden" in result.note.lower()

    def test_request_budget_approved_within_limit(self) -> None:
        """⭐ Phase 4 — medium cost (2.0) ≤ default 한도 (15.0) → approved."""
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(_make_proposal(estimated_cost="medium"))
        result = fac.request_budget_brake(session)
        assert result.status == "approved"
        assert result.estimated_cost_usd == 2.0
        assert result.budget_limit_usd == 15.0

    def test_request_budget_throttled_high_cost_over_limit(
        self, monkeypatch
    ) -> None:
        """⭐ Phase 4 — 한도 5 USD 인데 high (10 USD) → throttled."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "5.0")
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(_make_proposal(estimated_cost="high"))
        result = fac.request_budget_brake(session)
        assert result.status == "throttled"
        assert result.estimated_cost_usd == 10.0
        assert result.budget_limit_usd == 5.0

    def test_summarize_discussion_includes_final(self) -> None:
        fac = BoardroomFacilitator()
        session = fac.convene_boardroom(_make_proposal(title="agenda X"))
        fac.request_alignment_check(session)
        fac.request_budget_brake(session)
        session.final_decision = FinalDecision(
            outcome="approved", reason="둘 다 통과"
        )
        summary = fac.summarize_discussion(session)
        assert "agenda X" in summary
        assert "approved" in summary
        assert session.session_id in summary


# =============================================================================
# 4. Node 함수 3개 — Phase 4 실 의결
# =============================================================================
class TestNodeFunctions:
    def test_node_boardroom_trigger_creates_session(self) -> None:
        proposal = _make_proposal(title="silent fail 5회 → GUI 강화")
        session = node_boardroom_trigger(proposal, proposal_path="/x.md")
        assert isinstance(session, BoardroomSession)
        assert session.agenda == "silent fail 5회 → GUI 강화"
        assert session.proposal is proposal

    def test_node_goal_alignment_check_returns_approved_default(self) -> None:
        session = BoardroomSession(
            session_id="s1",
            agenda="X",
            attendees=[],
            opened_at="t",
            proposal=_make_proposal(),
        )
        result = node_goal_alignment_check(session)
        assert result.status == "approved"

    def test_node_goal_alignment_check_returns_rejected_for_forbidden(
        self,
    ) -> None:
        """⭐ forbidden 키워드 안건 → rejected."""
        session = BoardroomSession(
            session_id="s1",
            agenda="X",
            attendees=[],
            opened_at="t",
            proposal=_make_proposal(title="force push to main 강제 배포"),
        )
        result = node_goal_alignment_check(session)
        assert result.status == "rejected"

    def test_node_budget_brake_returns_approved_within_limit(self) -> None:
        session = BoardroomSession(
            session_id="s1",
            agenda="X",
            attendees=[],
            opened_at="t",
            proposal=_make_proposal(estimated_cost="low"),
        )
        result = node_budget_brake(session)
        assert result.status == "approved"
        assert result.estimated_cost_usd == 0.5

    def test_node_budget_brake_returns_throttled_over_limit(
        self, monkeypatch
    ) -> None:
        """⭐ 한도 0.1 + high (10) → throttled."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "0.1")
        session = BoardroomSession(
            session_id="s1",
            agenda="X",
            attendees=[],
            opened_at="t",
            proposal=_make_proposal(estimated_cost="high"),
        )
        result = node_budget_brake(session)
        assert result.status == "throttled"


# =============================================================================
# 5. Markdown writer
# =============================================================================
class TestMarkdownWriter:
    def test_session_markdown_written(self, tmp_path: Path) -> None:
        session = BoardroomSession(
            session_id="abc12345",
            agenda="GUI sandbox 강화",
            attendees=["CTO", "GoalAlignmentAgent"],
            opened_at="2026-05-28T07:00:00Z",
            proposal_path="/tmp/p.md",
        )
        session.alignment_result = AlignmentCheckResult(
            status="approved", note="mission 부합", references=["mission.md"]
        )
        session.budget_result = BudgetBrakeResult(
            status="approved",
            estimated_cost_usd=2.0,
            budget_limit_usd=15.0,
            cumulative_cost_usd=0.0,
            note="잔여 13 USD",
        )
        session.final_decision = FinalDecision(
            outcome="approved", reason="둘 다 통과"
        )
        md_path = write_boardroom_session_markdown(session, tmp_path)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "GUI sandbox 강화" in content
        assert "abc12345" in content
        assert "approved" in content
        assert "Final Decision" in content
        assert '"session_id": "abc12345"' in content

    def test_session_closed_at_auto_set(self, tmp_path: Path) -> None:
        session = BoardroomSession(
            session_id="x", agenda="Y", attendees=[], opened_at="t",
        )
        assert session.closed_at == ""
        write_boardroom_session_markdown(session, tmp_path)
        assert session.closed_at  # ISO8601 자동 채움


# =============================================================================
# 6. ⭐ Phase 4 — decision.yaml writer (PR #222)
# =============================================================================
class TestDecisionYamlWriter:
    """⭐ write_boardroom_decision_yaml — Phase 4 의결 로그 schema."""

    def _make_complete_session(self) -> BoardroomSession:
        s = BoardroomSession(
            session_id="abc12345",
            agenda="GUI sandbox 강화 — 5회 silent fail",
            attendees=["CTO", "GoalAlignmentAgent", "TokenBudgetOptimizer"],
            opened_at="2026-05-28T07:00:00Z",
            proposal_path="/tmp/p.md",
            closed_at="2026-05-28T07:00:42Z",
        )
        s.alignment_result = AlignmentCheckResult(
            status="approved",
            note="mission 부합",
            references=["mission.md", "security.md"],
            checked_at="2026-05-28T07:00:15Z",
        )
        s.budget_result = BudgetBrakeResult(
            status="approved",
            estimated_cost_usd=2.0,
            budget_limit_usd=15.0,
            cumulative_cost_usd=3.17,
            note="잔여 11.83 USD",
            checked_at="2026-05-28T07:00:25Z",
        )
        s.final_decision = FinalDecision(
            outcome="approved",
            reason="alignment=approved AND budget=approved",
            blocked_by=[],
            decided_at="2026-05-28T07:00:42Z",
        )
        return s

    def test_decision_yaml_path_format(self, tmp_path: Path) -> None:
        """⭐ 경로 = <output_dir>/<ts>_<session_id>/decision.yaml."""
        s = self._make_complete_session()
        yaml_path = write_boardroom_decision_yaml(s, tmp_path)
        assert yaml_path.exists()
        assert yaml_path.name == "decision.yaml"
        assert s.session_id in yaml_path.parent.name

    def test_decision_yaml_schema_top_level_fields(self, tmp_path: Path) -> None:
        """⭐ schema_version 현재값 (v2 Phase 5.4) + v1 4 필드 + v2 rounds/consensus."""
        s = self._make_complete_session()
        yaml_path = write_boardroom_decision_yaml(s, tmp_path)
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == DECISION_SCHEMA_VERSION
        # v1 → v2 (PR #224) 의 점진 진화 — 본 PR 시점 "v2"
        assert data["schema_version"] in {"v1", "v2"}
        # v1 의 4 필드는 schema 진화 후에도 보존
        assert set(data.keys()) >= {
            "schema_version",
            "session",
            "alignment",
            "budget",
            "final_decision",
        }

    def test_decision_yaml_session_section(self, tmp_path: Path) -> None:
        s = self._make_complete_session()
        data = yaml.safe_load(
            write_boardroom_decision_yaml(s, tmp_path).read_text(encoding="utf-8")
        )
        sess = data["session"]
        assert sess["session_id"] == "abc12345"
        assert sess["agenda"] == "GUI sandbox 강화 — 5회 silent fail"
        assert sess["proposal_path"] == "/tmp/p.md"
        assert "CTO" in sess["attendees"]

    def test_decision_yaml_alignment_section(self, tmp_path: Path) -> None:
        s = self._make_complete_session()
        data = yaml.safe_load(
            write_boardroom_decision_yaml(s, tmp_path).read_text(encoding="utf-8")
        )
        align = data["alignment"]
        assert align["status"] == "approved"
        assert "mission" in align["reason"]
        assert "mission.md" in align["references"]
        assert align["checked_at"] == "2026-05-28T07:00:15Z"

    def test_decision_yaml_budget_section_has_all_3_amounts(
        self, tmp_path: Path
    ) -> None:
        """⭐ budget 섹션 — estimated/limit/cumulative 3개 USD 값 모두."""
        s = self._make_complete_session()
        data = yaml.safe_load(
            write_boardroom_decision_yaml(s, tmp_path).read_text(encoding="utf-8")
        )
        budget = data["budget"]
        assert budget["status"] == "approved"
        assert budget["estimated_cost_usd"] == 2.0
        assert budget["budget_limit_usd"] == 15.0
        assert budget["cumulative_cost_usd"] == 3.17

    def test_decision_yaml_final_decision_blocked_serialization(
        self, tmp_path: Path
    ) -> None:
        """⭐ blocked 시 blocked_by list 정상 직렬화."""
        s = self._make_complete_session()
        s.alignment_result = AlignmentCheckResult(
            status="rejected", note="위배", references=["security.md"]
        )
        s.final_decision = FinalDecision(
            outcome="blocked",
            reason="alignment=rejected",
            blocked_by=["alignment"],
        )
        data = yaml.safe_load(
            write_boardroom_decision_yaml(s, tmp_path).read_text(encoding="utf-8")
        )
        assert data["final_decision"]["outcome"] == "blocked"
        assert data["final_decision"]["blocked_by"] == ["alignment"]


# =============================================================================
# 7. ⭐ 풀체인 진입점 — convene_full_boardroom_cycle (3-tuple 반환)
# =============================================================================
class TestFullCycle:
    """⭐ 안건 → 3 노드 → 회의록 markdown + decision.yaml."""

    def test_full_cycle_returns_3_tuple(self, tmp_path: Path) -> None:
        """⭐ Phase 4 — (session, md_path, yaml_path) 반환."""
        proposal = _make_proposal(title="GUI sandbox 강화 — 5회 silent fail")
        session, md_path, yaml_path = convene_full_boardroom_cycle(
            proposal=proposal,
            proposal_path="/x/y.md",
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
        )
        assert session.agenda == "GUI sandbox 강화 — 5회 silent fail"
        assert session.alignment_result is not None
        assert session.alignment_result.status == "approved"
        assert session.budget_result is not None
        assert session.budget_result.status == "approved"
        assert session.final_decision.outcome == "approved"
        assert md_path.exists()
        assert yaml_path.exists()

    def test_full_cycle_blocked_alignment_rejected(self, tmp_path: Path) -> None:
        """⭐ forbidden 키워드 안건 → alignment=rejected → final=blocked + yaml 산출."""
        proposal = _make_proposal(title="rm -rf 강제 정리 안건")
        session, md_path, yaml_path = convene_full_boardroom_cycle(
            proposal=proposal,
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
        )
        assert session.alignment_result.status == "rejected"
        assert session.final_decision.outcome == "blocked"
        assert session.final_decision.blocked_by == ["alignment"]
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["final_decision"]["outcome"] == "blocked"

    def test_full_cycle_blocked_budget_throttled(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """⭐ 한도 0.1 + high → budget=throttled → final=blocked."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "0.1")
        proposal = _make_proposal(estimated_cost="high")
        session, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=proposal,
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
        )
        assert session.budget_result.status == "throttled"
        assert session.final_decision.outcome == "blocked"
        assert session.final_decision.blocked_by == ["budget"]
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["budget"]["status"] == "throttled"


# =============================================================================
# 8. Telemetry 부서 매핑 (planning + c-level)
# =============================================================================
class TestTelemetryDepartmentMapping:
    def test_c_level_constant(self) -> None:
        assert C_LEVEL == "c-level"

    def test_boardroom_trigger_is_planning(self) -> None:
        assert _NODE_DEPARTMENT["boardroom_trigger"] == "planning"
        assert department_for_node("boardroom_trigger") == "planning"

    def test_goal_alignment_check_is_c_level(self) -> None:
        assert _NODE_DEPARTMENT["goal_alignment_check"] == "c-level"

    def test_budget_brake_is_c_level(self) -> None:
        assert _NODE_DEPARTMENT["budget_brake"] == "c-level"


# =============================================================================
# 9. CLI integration (PR #221 보존)
# =============================================================================
class TestCLIIntegration:
    def test_enable_boardroom_flag_parses(self) -> None:
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
            assert args.enable_strategist is True
            assert args.enable_rv is True
        finally:
            _sys.argv = prev

    def test_run_iterative_loop_accepts_enable_boardroom(self) -> None:
        import inspect

        from src.workflows.iterative_loop import run_iterative_loop

        sig = inspect.signature(run_iterative_loop)
        assert "enable_boardroom" in sig.parameters
        assert sig.parameters["enable_boardroom"].default is False
