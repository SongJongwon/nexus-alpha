# -*- coding: utf-8 -*-
"""System Refactoring Strategist 단위 test (v13 Phase 2, PR #219).

검증 범위:
    1. RefactoringProposal dataclass schema
    2. analyze_runtime_patterns — 결정론 패턴 매처 (silent fail / BLOCKED 비율)
    3. LLM fallback 동작
    4. write_proposal_markdown — file system 저장
    5. trigger_strategist_on_escalation — decision routing
    6. edge cases (빈 events / 부분 데이터 / 잘못된 JSON)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis.system_refactoring_strategist import (
    SILENT_FAIL_THRESHOLD,
    RefactoringProposal,
    analyze_runtime_patterns,
    trigger_strategist_on_escalation,
    write_proposal_markdown,
)


# =============================================================================
# 1. Schema
# =============================================================================
class TestRefactoringProposalSchema:
    def test_dataclass_fields(self) -> None:
        p = RefactoringProposal(
            title="test",
            root_cause_analysis="cause",
            proposed_changes=["a", "b"],
            estimated_cost="medium",
            confidence=0.8,
            analysis_method="rule",
            signal_summary={"x": 1},
        )
        assert p.title == "test"
        assert p.confidence == 0.8
        assert p.proposed_changes == ["a", "b"]
        assert p.signal_summary == {"x": 1}

    def test_default_values(self) -> None:
        p = RefactoringProposal(
            title="t", root_cause_analysis="c", proposed_changes=[]
        )
        assert p.estimated_cost == "medium"
        assert p.confidence == 0.5
        assert p.analysis_method == "rule"
        assert p.signal_summary == {}


# =============================================================================
# 2. ⭐ 결정론 매처 — silent fail 5회 패턴 (DoD)
# =============================================================================
class TestDeterministicSilentFailPattern:
    """⭐ DoD: silent fail 5회 연속 감지 시 GUI sandbox 강화 안건 자율 발제."""

    def test_silent_fail_5_triggers_gui_sandbox_proposal(self) -> None:
        """silent fail 5건 → GUI sandbox 강화 안건 (결정론 0.9 confidence)."""
        events = [
            {"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=SILENT_FAIL"}
            for _ in range(SILENT_FAIL_THRESHOLD)
        ]
        proposal = analyze_runtime_patterns(events)
        assert "GUI sandbox 강화" in proposal.title
        assert proposal.analysis_method == "rule"
        assert proposal.confidence >= 0.85
        assert len(proposal.proposed_changes) >= 3
        assert proposal.signal_summary["silent_fail_count"] == 5

    def test_silent_fail_below_threshold_no_proposal(self) -> None:
        """silent fail 4건 → threshold 미달 → unknown fallback (confidence 낮음)."""
        events = [
            {"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=SILENT_FAIL"}
            for _ in range(SILENT_FAIL_THRESHOLD - 1)
        ]
        proposal = analyze_runtime_patterns(events)
        assert "GUI sandbox 강화" not in proposal.title
        assert proposal.confidence < 0.5  # 신호 부족 fallback


# =============================================================================
# 3. 결정론 매처 — BLOCKED 비율 50%+ 패턴
# =============================================================================
class TestBlockedRatioPattern:
    def test_blocked_ratio_high_triggers_budget_proposal(self) -> None:
        """recent_verdicts 중 BLOCKED 비율 ≥ 50% → budget 상향 안건."""
        proposal = analyze_runtime_patterns(
            events=[],
            recent_verdicts=["BLOCKED", "BLOCKED", "BLOCKED", "COMPLETE"],
        )
        assert "max_iterations" in proposal.title or "budget" in proposal.title.lower()
        assert proposal.signal_summary["blocked_ratio"] >= 0.5
        assert proposal.confidence >= 0.8

    def test_blocked_ratio_low_no_proposal(self) -> None:
        """BLOCKED 비율 < 50% → 안건 발제 X (신호 부족 fallback)."""
        proposal = analyze_runtime_patterns(
            events=[], recent_verdicts=["COMPLETE", "COMPLETE", "BLOCKED"]
        )
        assert "max_iterations" not in proposal.title
        assert proposal.confidence < 0.5


# =============================================================================
# 4. LLM fallback
# =============================================================================
class TestLLMFallback:
    def test_llm_call_when_no_deterministic_match(self) -> None:
        """결정론 미매치 + LLM 제공 → LLM 호출 → JSON parse."""

        def mock_llm(prompt: str) -> str:
            return json.dumps({
                "title": "LLM 산출 안건",
                "root_cause_analysis": "LLM 패턴 해석",
                "proposed_changes": ["do X", "do Y"],
                "estimated_cost": "high",
                "confidence": 0.75,
            })

        events = [{"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=CRASH"}]
        proposal = analyze_runtime_patterns(events, llm_call=mock_llm)
        assert proposal.title == "LLM 산출 안건"
        assert proposal.analysis_method == "llm"
        assert proposal.confidence == 0.75
        assert proposal.estimated_cost == "high"

    def test_llm_invalid_json_falls_through_to_unknown(self) -> None:
        """LLM 응답 JSON parse 실패 → unknown fallback."""

        def bad_llm(prompt: str) -> str:
            return "not valid json"

        events = [{"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=CRASH"}]
        proposal = analyze_runtime_patterns(events, llm_call=bad_llm)
        assert proposal.analysis_method == "rule"
        assert proposal.confidence < 0.5

    def test_no_llm_no_deterministic_match_returns_fallback(self) -> None:
        """결정론 미매치 + LLM 미제공 → unknown fallback."""
        proposal = analyze_runtime_patterns(events=[], recent_verdicts=None)
        assert "신호 부족" in proposal.title
        assert proposal.confidence < 0.5
        assert proposal.analysis_method == "rule"


# =============================================================================
# 5. write_proposal_markdown
# =============================================================================
class TestWriteProposalMarkdown:
    def test_markdown_file_created(self, tmp_path: Path) -> None:
        """proposal → <timestamp>_<slug>.md 작성 + 내용 검증."""
        p = RefactoringProposal(
            title="GUI sandbox 강화 — 5회 silent fail",
            root_cause_analysis="root cause text",
            proposed_changes=["change A", "change B"],
            estimated_cost="medium",
            confidence=0.9,
            analysis_method="rule",
            signal_summary={"silent_fail_count": 5},
        )
        md_path = write_proposal_markdown(p, tmp_path)
        assert md_path.exists()
        assert md_path.suffix == ".md"
        content = md_path.read_text(encoding="utf-8")
        assert "GUI sandbox 강화" in content
        assert "change A" in content
        assert "change B" in content
        assert '"silent_fail_count": 5' in content
        assert "Phase 4 의결권 활성화" in content

    def test_output_dir_auto_created(self, tmp_path: Path) -> None:
        """output_dir 부재 시 자동 생성."""
        nested = tmp_path / "deep" / "nested" / "dir"
        p = RefactoringProposal(
            title="x", root_cause_analysis="x", proposed_changes=[]
        )
        md_path = write_proposal_markdown(p, nested)
        assert nested.exists()
        assert md_path.exists()


# =============================================================================
# 6. trigger_strategist_on_escalation — routing
# =============================================================================
class TestTriggerOnEscalation:
    def test_non_escalate_decision_returns_none(self, tmp_path: Path) -> None:
        """decision.action != 'escalate' → no-op (None 반환)."""
        decision = SimpleNamespace(action="rebuild")
        result = trigger_strategist_on_escalation(
            decision=decision,
            events_jsonl_path=None,
            output_dir=tmp_path,
        )
        assert result is None

    def test_escalate_decision_writes_proposal(self, tmp_path: Path) -> None:
        """decision.action == 'escalate' → proposal markdown 작성."""
        decision = SimpleNamespace(action="escalate")
        # 5회 silent fail events.jsonl 시뮬레이션
        events_path = tmp_path / "events.jsonl"
        events_lines = [
            json.dumps({
                "agent": "exe_runtime_tester",
                "status": "done",
                "detail": "verdict=SILENT_FAIL",
            })
            for _ in range(5)
        ]
        events_path.write_text("\n".join(events_lines), encoding="utf-8")

        md_path = trigger_strategist_on_escalation(
            decision=decision,
            events_jsonl_path=events_path,
            output_dir=tmp_path / "proposals",
        )
        assert md_path is not None
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "GUI sandbox 강화" in content

    def test_missing_events_file_handled_gracefully(self, tmp_path: Path) -> None:
        """events.jsonl 미존재 → 빈 events 로 진행 (no-op fallback)."""
        decision = SimpleNamespace(action="escalate")
        md_path = trigger_strategist_on_escalation(
            decision=decision,
            events_jsonl_path=tmp_path / "_nonexistent.jsonl",
            recent_verdicts=None,
            output_dir=tmp_path / "proposals",
        )
        # 빈 events + recent_verdicts None → 신호 부족 안건 발제 (markdown 은 생성됨)
        assert md_path is not None
        assert md_path.exists()
        assert "신호 부족" in md_path.read_text(encoding="utf-8")

    def test_corrupted_jsonl_lines_skipped(self, tmp_path: Path) -> None:
        """events.jsonl 의 corrupted line 은 skip + 정상 line 만 분석."""
        decision = SimpleNamespace(action="escalate")
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            "\n".join([
                "not valid json",
                json.dumps({"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=SILENT_FAIL"}),
                "{{broken",
                json.dumps({"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=SILENT_FAIL"}),
            ]),
            encoding="utf-8",
        )
        md_path = trigger_strategist_on_escalation(
            decision=decision,
            events_jsonl_path=events_path,
            output_dir=tmp_path / "proposals",
        )
        assert md_path is not None
        # corrupted skip 후 silent_fail 2건만 인식 → threshold 미달 → 신호 부족 fallback
        assert "신호 부족" in md_path.read_text(encoding="utf-8")
