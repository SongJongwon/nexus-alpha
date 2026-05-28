# -*- coding: utf-8 -*-
"""Boardroom E2E 통합 test (v13 Phase 3 + Phase 4, PR #221 + #222).

PR #218 패턴 준수 — mock-only unit test 만으로는 통합 시점 누락 회피.

검증 시나리오:
    1. ⭐ 풀체인: RV silent fail 5회 → Strategist 안건 → Boardroom 회의록 + decision.yaml
    2. ⭐ default OFF: enable_boardroom=False 시 회의 미소집 (회귀 0)
    3. ⭐ 실 TelemetryEmitter + dept="c-level" / dept="planning" JSON-parse 검증
    4. ⭐ Phase 4 — decision.yaml 파일 자동 생성 + schema 검증
    5. ⭐ Phase 4 — alignment=rejected 시 final=blocked + yaml 반영 (라이브)
    6. CLI 3 flag 독립
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult


def _make_silent_fail_rv(exe_path: Path) -> RuntimeTestResult:
    return RuntimeTestResult(
        exit_code=0,
        stderr="",
        stdout="",
        startup_time_ms=10.0,
        memory_peak_mb=None,
        timed_out=False,
        verdict="SILENT_FAIL",
        error_trace="(exit 0 immediate — silent fail)",
        exe_path=exe_path,
    )


def _make_chain_mock(exe_path: Path, saved_dir: Path) -> MagicMock:
    chain = MagicMock()
    chain.executor_result.exe_path = exe_path
    chain.saved_dir = saved_dir
    return chain


# =============================================================================
# 1. ⭐ 풀체인 — RV → Strategist → Boardroom + decision.yaml (Phase 4)
# =============================================================================
class TestFullMetaLoopE2E:
    """⭐ Phase 1 + 2 + 3 + 4 메타 루프 풀체인 검증."""

    def test_5_silent_fails_triggers_boardroom_session_md_and_decision_yaml(
        self, tmp_path: Path
    ) -> None:
        from src.workflows.iterative_loop import _node_runtime_verify

        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir()
        fake_exe = tmp_path / "App.exe"
        fake_exe.write_bytes(b"")
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        chain = _make_chain_mock(fake_exe, saved_dir)
        rv_silent = _make_silent_fail_rv(fake_exe)

        state: dict = {
            "enable_rv": True,
            "enable_strategist": True,
            "enable_boardroom": True,
            "chain_result": chain,
            "consecutive_rv_failures": 0,
            "outputs_dir": str(outputs_dir),
            "strategist_proposal_path": None,
            "boardroom_session_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_silent,
        ):
            for _ in range(5):
                result = _node_runtime_verify(state)
                state.update(result)

        # Phase 2 — Strategist 안건 발제 확인
        proposal_dir = outputs_dir / "_refactoring_proposals"
        assert proposal_dir.exists(), "Phase 2 안건 미발제"
        assert len(list(proposal_dir.glob("*.md"))) >= 1

        # Phase 3 — 회의록 markdown
        boardroom_dir = outputs_dir / "_boardroom_sessions"
        assert boardroom_dir.exists(), "Phase 3 회의록 미생성"
        sessions = list(boardroom_dir.glob("*.md"))
        assert len(sessions) >= 1
        content = sessions[0].read_text(encoding="utf-8")
        assert "Boardroom Session" in content
        assert "GUI sandbox" in content

        # ⭐ Phase 4 — decision.yaml 자동 생성
        decision_dir = outputs_dir / "board_decisions"
        assert decision_dir.exists(), "Phase 4 의결 로그 디렉터리 미생성"
        decision_subdirs = [p for p in decision_dir.iterdir() if p.is_dir()]
        assert len(decision_subdirs) >= 1, "decision.yaml 부모 디렉터리 없음"
        yaml_path = decision_subdirs[0] / "decision.yaml"
        assert yaml_path.exists(), "decision.yaml 파일 미생성"

        # decision.yaml schema 검증 (v1 PR #222 → v2 PR #224 진화)
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["schema_version"] in {"v1", "v2"}
        assert data["session"]["agenda"].startswith("GUI sandbox")
        # Phase 4 의결권 실 동작 (pending_phase4 가 없는지 확인)
        assert data["alignment"]["status"] in {"approved", "rejected"}
        assert data["budget"]["status"] in {"approved", "throttled"}
        assert data["final_decision"]["outcome"] in {"approved", "blocked"}


# =============================================================================
# 2. ⭐ default OFF — 회귀 0
# =============================================================================
class TestBoardroomDefaultOff:
    def test_boardroom_off_no_session_no_decision(
        self, tmp_path: Path
    ) -> None:
        """⭐ enable_boardroom=False → 회의 미소집 + decision.yaml 미생성."""
        from src.workflows.iterative_loop import _node_runtime_verify

        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir()
        fake_exe = tmp_path / "App.exe"
        fake_exe.write_bytes(b"")
        outputs_dir = tmp_path / "outputs"

        chain = _make_chain_mock(fake_exe, saved_dir)
        rv_silent = _make_silent_fail_rv(fake_exe)

        state: dict = {
            "enable_rv": True,
            "enable_strategist": True,
            "chain_result": chain,
            "consecutive_rv_failures": 0,
            "outputs_dir": str(outputs_dir),
            "strategist_proposal_path": None,
            "boardroom_session_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_silent,
        ):
            for _ in range(5):
                result = _node_runtime_verify(state)
                state.update(result)

        assert (outputs_dir / "_refactoring_proposals").exists()
        assert not (outputs_dir / "_boardroom_sessions").exists(), (
            "enable_boardroom=False 인데 회의록 생성 — 회귀"
        )
        assert not (outputs_dir / "board_decisions").exists(), (
            "enable_boardroom=False 인데 decision.yaml 디렉터리 생성 — Phase 4 회귀"
        )


# =============================================================================
# 3. ⭐ Telemetry — dept="c-level" + dept="planning" JSON-parse (PR #218 패턴)
# =============================================================================
class TestBoardroomTelemetryEmission:
    """⭐ 실 TelemetryEmitter — Phase 4 c-level 이벤트가 라이브 emit 되는지."""

    def test_full_cycle_emits_planning_and_c_level_events(
        self, tmp_path: Path
    ) -> None:
        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            from src.agents.coordination import convene_full_boardroom_cycle

            proposal = SimpleNamespace(
                title="GUI sandbox 강화 — 5회 silent fail",
                estimated_cost="medium",
                proposed_changes=[],
            )
            convene_full_boardroom_cycle(
                proposal=proposal,
                proposal_path="/x/y.md",
                output_dir=tmp_path / "_boardroom_sessions",
                decision_output_dir=tmp_path / "board_decisions",
            )

            assert events_path.exists()
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            assert lines
            parsed = [json.loads(line) for line in lines]

            # ⭐ dept="planning" (boardroom_trigger + facilitator)
            planning = [e for e in parsed if e.get("department") == "planning"]
            assert len(planning) >= 2
            assert "boardroom_trigger" in {e.get("agent") for e in planning}

            # ⭐ dept="c-level" (goal_alignment_check + budget_brake working+done = 4 events)
            c_level = [e for e in parsed if e.get("department") == "c-level"]
            assert len(c_level) >= 4, (
                f"c-level 이벤트 부족 — Phase 4 의결 emit 누락, 실제 {len(c_level)}"
            )
            c_level_agents = {e.get("agent") for e in c_level}
            assert "goal_alignment_check" in c_level_agents
            assert "budget_brake" in c_level_agents

            # ⭐ Phase 4 — done 이벤트 detail 에 실 status 반영 (pending_phase4 없음)
            done_events = [e for e in c_level if e.get("status") == "done"]
            done_details = " ".join(e.get("detail", "") for e in done_events)
            assert "pending_phase4" not in done_details, (
                "Phase 4 라인데 pending_phase4 emit — placeholder 잔재"
            )
            assert "status=approved" in done_details or "status=rejected" in done_details
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()


# =============================================================================
# 4. ⭐ Phase 4 — Telemetry + decision.yaml 라이브 동시 검증 (PR #218 패턴 확장)
# =============================================================================
class TestPhase4LiveTelemetryAndDecisionYaml:
    """⭐ PR #218 패턴 — 실 emit + 파일 산출 동시 검증."""

    def test_alignment_rejected_blocks_final_and_appears_in_yaml(
        self, tmp_path: Path
    ) -> None:
        """⭐ forbidden 안건 라이브 → telemetry c-level + decision.yaml blocked 반영."""
        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            from src.agents.coordination import convene_full_boardroom_cycle

            proposal = SimpleNamespace(
                title="security 우회 — qa 우회 강제 머지",
                estimated_cost="low",
                proposed_changes=["skip review"],
            )
            session, _md, yaml_path = convene_full_boardroom_cycle(
                proposal=proposal,
                output_dir=tmp_path / "_boardroom_sessions",
                decision_output_dir=tmp_path / "board_decisions",
            )

            # 의결 결과
            assert session.alignment_result.status == "rejected"
            assert session.final_decision.outcome == "blocked"
            assert "alignment" in session.final_decision.blocked_by

            # decision.yaml 라이브 반영
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            assert data["alignment"]["status"] == "rejected"
            assert data["final_decision"]["outcome"] == "blocked"
            assert data["final_decision"]["blocked_by"] == ["alignment"]

            # Telemetry c-level done 이벤트 — status=rejected 가 라이브 emit
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            parsed = [json.loads(line) for line in lines]
            c_level_done = [
                e
                for e in parsed
                if e.get("department") == "c-level"
                and e.get("status") == "done"
            ]
            details = " ".join(e.get("detail", "") for e in c_level_done)
            assert "status=rejected" in details, (
                f"goal_alignment_check done detail 에 rejected 미반영: {details}"
            )
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()

    def test_budget_throttled_appears_in_yaml_and_telemetry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """⭐ 한도 0.1 + high cost → throttled + yaml + telemetry 동시 반영."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "0.1")
        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            from src.agents.coordination import convene_full_boardroom_cycle

            proposal = SimpleNamespace(
                title="대규모 refactor — 추가 LLM 호출 다수",
                estimated_cost="high",
                proposed_changes=[],
            )
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
            assert data["budget"]["budget_limit_usd"] == 0.1
            assert data["budget"]["estimated_cost_usd"] == 10.0

            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            parsed = [json.loads(line) for line in lines]
            c_level_done = [
                e
                for e in parsed
                if e.get("department") == "c-level"
                and e.get("status") == "done"
            ]
            details = " ".join(e.get("detail", "") for e in c_level_done)
            assert "status=throttled" in details
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()


# =============================================================================
# 5. CLI 3 flag 독립 — PR #221 보존
# =============================================================================
class TestFullChainCLIFlags:
    def test_three_flags_independent(self) -> None:
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = [
                "run.py", "--request", "X", "--enable-boardroom", "--non-interactive",
            ]
            from scripts.run import _parse_args

            args = _parse_args()
            assert args.enable_boardroom is True
            assert args.enable_rv is False
            assert args.enable_strategist is False
        finally:
            _sys.argv = prev
