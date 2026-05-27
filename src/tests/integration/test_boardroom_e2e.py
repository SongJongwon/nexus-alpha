# -*- coding: utf-8 -*-
"""Boardroom E2E 통합 test (v13 Phase 3, PR #221).

PR #218 패턴 준수 — mock-only unit test 만으로는 통합 시점 누락 회피.

검증 시나리오:
    1. ⭐ 풀체인: RV silent fail 5회 → Strategist 안건 → Boardroom 회의록 생성
    2. ⭐ default OFF: enable_boardroom=False 시 회의 미소집 (회귀 0)
    3. ⭐ 실 TelemetryEmitter + dept="c-level" / dept="planning" JSON-parse 검증
    4. 회의록 markdown 내용 검증 (Phase 4 Placeholder 안내 포함)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
# 1. ⭐ 풀체인 — RV → Strategist → Boardroom
# =============================================================================
class TestFullMetaLoopE2E:
    """⭐ Phase 1 + 2 + 3 메타 루프 풀체인 검증.

    핵심 흐름:
        RV silent fail 5회 ─► Auto-Fix escalate ─► Strategist 안건 md ─►
        Boardroom 회의 소집 ─► 회의록 md 보존
    """

    def test_5_silent_fails_triggers_boardroom_session_md(
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
            "enable_boardroom": True,  # ⭐ Phase 3 활성
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
        proposals = list(proposal_dir.glob("*.md"))
        assert len(proposals) >= 1

        # ⭐ Phase 3 — Boardroom 회의록 생성 확인
        boardroom_dir = outputs_dir / "_boardroom_sessions"
        assert boardroom_dir.exists(), "Phase 3 회의실 미소집"
        sessions = list(boardroom_dir.glob("*.md"))
        assert len(sessions) >= 1, "회의록 markdown 미생성"

        content = sessions[0].read_text(encoding="utf-8")
        assert "Boardroom Session" in content
        assert "GUI sandbox" in content  # Strategist 안건 제목 인용
        assert "pending_phase4" in content  # Placeholder 의결 결과
        assert "Phase 4 의결권 활성화" in content  # 한계 명시 보존


# =============================================================================
# 2. ⭐ default OFF — 회귀 0 보장
# =============================================================================
class TestBoardroomDefaultOff:
    def test_strategist_on_but_boardroom_off_no_session_md(
        self, tmp_path: Path
    ) -> None:
        """⭐ enable_boardroom=False (default) → 회의 미소집 (Phase 2 안건만)."""
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
            # "enable_boardroom": False (default, 생략)
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

        # Phase 2 안건은 발제됨
        assert (outputs_dir / "_refactoring_proposals").exists()
        # ⭐ Phase 3 회의록 디렉터리 미생성 (회귀 0)
        assert not (outputs_dir / "_boardroom_sessions").exists(), (
            "enable_boardroom=False 인데 회의록 생성 — 회귀"
        )

    def test_state_boardroom_session_path_none_when_off(
        self, tmp_path: Path
    ) -> None:
        """state.boardroom_session_path 가 default OFF 시 None 유지."""
        from src.workflows.iterative_loop import _node_runtime_verify

        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir()
        fake_exe = tmp_path / "App.exe"
        fake_exe.write_bytes(b"")

        chain = _make_chain_mock(fake_exe, saved_dir)
        rv_silent = _make_silent_fail_rv(fake_exe)

        state: dict = {
            "enable_rv": True,
            "enable_strategist": True,
            "enable_boardroom": False,
            "chain_result": chain,
            "consecutive_rv_failures": 4,  # 1회만 더 fail 하면 escalate
            "outputs_dir": str(tmp_path),
            "strategist_proposal_path": None,
            "boardroom_session_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_silent,
        ):
            result = _node_runtime_verify(state)

        assert result["consecutive_rv_failures"] == 5
        # Phase 2 는 동작, Phase 3 는 미동작
        assert result["strategist_proposal_path"] is not None
        assert result["boardroom_session_path"] is None


# =============================================================================
# 3. ⭐ Telemetry — dept="c-level" + dept="planning" JSON-parse (PR #218 패턴)
# =============================================================================
class TestBoardroomTelemetryEmission:
    """⭐ Boardroom 3 노드 실 telemetry emit + JSON-parse 검증.

    핵심: PR #218 가 잡은 함정 (mock-only test 통과해도 라이브 emit 안 됨) 회피.
    """

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

            proposal = SimpleNamespace(title="GUI sandbox 강화 — 5회 silent fail")
            convene_full_boardroom_cycle(
                proposal=proposal,
                proposal_path="/x/y.md",
                output_dir=tmp_path / "_boardroom_sessions",
            )

            assert events_path.exists(), "events.jsonl 미생성"
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            assert lines
            parsed = [json.loads(line) for line in lines]

            # ⭐ dept="planning" (boardroom_trigger + boardroom_facilitator)
            planning = [e for e in parsed if e.get("department") == "planning"]
            assert len(planning) >= 2, (
                f"planning 이벤트 부족 — boardroom_trigger 누락 의심, 실제 {len(planning)}"
            )
            trigger_agents = {e.get("agent") for e in planning}
            assert "boardroom_trigger" in trigger_agents

            # ⭐ dept="c-level" (goal_alignment_check + budget_brake)
            c_level = [e for e in parsed if e.get("department") == "c-level"]
            assert len(c_level) >= 4, (
                f"c-level 이벤트 부족 — Placeholder 노드 emit 누락, 실제 {len(c_level)}"
            )
            c_level_agents = {e.get("agent") for e in c_level}
            assert "goal_alignment_check" in c_level_agents
            assert "budget_brake" in c_level_agents
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()


# =============================================================================
# 4. CLI 풀체인 — 3 flag 조합
# =============================================================================
class TestFullChainCLIFlags:
    def test_three_flags_independent(self) -> None:
        """--enable-rv / --enable-strategist / --enable-boardroom 각자 독립."""
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = [
                "run.py", "--request", "X", "--enable-boardroom", "--non-interactive",
            ]
            from scripts.run import _parse_args

            args = _parse_args()
            # boardroom 만 켜고 rv/strategist 는 OFF
            assert args.enable_boardroom is True
            assert args.enable_rv is False
            assert args.enable_strategist is False
        finally:
            _sys.argv = prev
