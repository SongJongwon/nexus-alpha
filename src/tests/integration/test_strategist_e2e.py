# -*- coding: utf-8 -*-
"""Strategist E2E 통합 test (v13 Phase 2, PR #219).

PR #218 패턴 준수 — `mock-only unit test 만으로는 통합 시점 누락` 회피.

검증 시나리오:
    1. ⭐ enable_strategist=True + 5회 silent fail 발생 → proposal markdown
       실제 생성 (file system 차원 검증)
    2. ⭐ 실 Telemetry emit + dept="planning" 이벤트 검증 (JSON-parse 기반)
    3. enable_strategist=False (default) → escalate 발생해도 Strategist 호출 X
       (회귀 0 보장)
    4. consecutive_rv_failures state 누적 정상 (5회 도달 시 escalate trigger)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult


# ---------------------------------------------------------------------------
# 공통 helpers
# ---------------------------------------------------------------------------
def _make_silent_fail_rv(exe_path: Path) -> RuntimeTestResult:
    """SILENT_FAIL verdict 의 RuntimeTestResult 생성."""
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


def _make_pass_rv(exe_path: Path) -> RuntimeTestResult:
    return RuntimeTestResult(
        exit_code=0,
        stderr="",
        stdout="",
        startup_time_ms=120.0,
        memory_peak_mb=12.5,
        timed_out=True,
        verdict="PASS",
        error_trace="",
        exe_path=exe_path,
    )


def _make_chain_mock(exe_path: Path, saved_dir: Path) -> MagicMock:
    chain = MagicMock()
    chain.executor_result.exe_path = exe_path
    chain.saved_dir = saved_dir
    return chain


# =============================================================================
# 1. ⭐ enable_strategist=True + 5회 silent fail → proposal md 생성
# =============================================================================
class TestStrategistE2EProposalGeneration:
    """⭐ DoD: 5회 silent fail 누적 시 GUI sandbox 강화 안건 markdown 실 생성."""

    def test_5_consecutive_silent_fails_writes_proposal_md(
        self, tmp_path: Path
    ) -> None:
        """_node_runtime_verify 를 5회 호출 → consecutive=5 도달 → escalate →
        Strategist 가 outputs/_refactoring_proposals/ 에 markdown 작성.
        """
        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir()
        fake_exe = tmp_path / "App.exe"
        fake_exe.write_bytes(b"")
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        from src.workflows.iterative_loop import _node_runtime_verify

        chain = _make_chain_mock(fake_exe, saved_dir)
        rv_silent = _make_silent_fail_rv(fake_exe)

        # 5회 silent fail 누적 시뮬레이션
        state: dict = {
            "enable_rv": True,
            "enable_strategist": True,
            "chain_result": chain,
            "consecutive_rv_failures": 0,
            "outputs_dir": str(outputs_dir),
            "strategist_proposal_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_silent,
        ):
            for i in range(5):
                result = _node_runtime_verify(state)
                # state 갱신 (LangGraph 가 자동으로 하지만 unit 시나리오라 수동)
                state.update(result)

        assert state["consecutive_rv_failures"] == 5
        # 5회 도달 시점에 Strategist 가 호출되어 proposal markdown 생성
        proposal_dir = outputs_dir / "_refactoring_proposals"
        assert proposal_dir.exists(), "proposal 디렉터리 미생성"
        md_files = list(proposal_dir.glob("*.md"))
        assert len(md_files) >= 1, "proposal markdown 미작성"
        content = md_files[0].read_text(encoding="utf-8")
        assert "GUI sandbox" in content or "silent fail" in content.lower()

    def test_pass_resets_consecutive_failures(self, tmp_path: Path) -> None:
        """PASS verdict → consecutive_rv_failures = 0 reset."""
        from src.workflows.iterative_loop import _node_runtime_verify

        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir()
        fake_exe = tmp_path / "App.exe"
        fake_exe.write_bytes(b"")

        chain = _make_chain_mock(fake_exe, saved_dir)
        rv_pass = _make_pass_rv(fake_exe)

        state: dict = {
            "enable_rv": True,
            "enable_strategist": True,
            "chain_result": chain,
            "consecutive_rv_failures": 3,  # 이미 3회 누적
            "outputs_dir": str(tmp_path),
            "strategist_proposal_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_pass,
        ):
            result = _node_runtime_verify(state)

        assert result["consecutive_rv_failures"] == 0  # PASS → reset
        assert result["rv_failure_detected"] is False


# =============================================================================
# 2. ⭐ default OFF 회귀 보장
# =============================================================================
class TestStrategistDefaultOff:
    """⭐ enable_strategist=False (default) → escalate 시에도 Strategist 호출 X."""

    def test_default_off_no_strategist_call(self, tmp_path: Path) -> None:
        """enable_strategist 미지정 → 5회 silent fail 발생해도 proposal 미생성."""
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
            # "enable_strategist": False  (생략 = default)
            "chain_result": chain,
            "consecutive_rv_failures": 0,
            "outputs_dir": str(outputs_dir),
            "strategist_proposal_path": None,
        }
        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_silent,
        ):
            for _ in range(5):
                result = _node_runtime_verify(state)
                state.update(result)

        # consecutive 누적은 정상이지만 proposal 디렉터리 미생성 (Strategist 호출 X)
        assert state["consecutive_rv_failures"] == 5
        proposal_dir = outputs_dir / "_refactoring_proposals"
        assert not proposal_dir.exists(), "default OFF 인데 proposal 생성됨 — 회귀"


# =============================================================================
# 3. ⭐ E2E Telemetry — dept="planning" 이벤트 emit 검증 (PR #218 패턴)
# =============================================================================
class TestStrategistTelemetryEmission:
    """⭐ analyze_runtime_patterns 호출 시 dept="planning" 이벤트가 실 events.jsonl
    에 JSON-line 으로 떨어지는지 검증 (PR #218 의 mock-gap 보완).
    """

    def test_strategist_emits_dept_planning_to_events_file(
        self, tmp_path: Path
    ) -> None:
        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            from src.agents.analysis.system_refactoring_strategist import (
                analyze_runtime_patterns,
            )

            # 5회 silent fail → 결정론 매처 → 안건 발제 (+ telemetry emit)
            events_input = [
                {"agent": "exe_runtime_tester", "status": "done", "detail": "verdict=SILENT_FAIL"}
                for _ in range(5)
            ]
            proposal = analyze_runtime_patterns(events_input)
            assert "GUI sandbox" in proposal.title

            # events.jsonl JSON-parse 검증 (PR #218 패턴 — raw substring 매칭 X)
            assert events_path.exists(), "events.jsonl 미생성"
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            assert lines, "events.jsonl 비어있음"

            parsed = [json.loads(line) for line in lines]
            planning_events = [e for e in parsed if e.get("department") == "planning"]
            assert len(planning_events) >= 2, (
                f"dept='planning' 이벤트 부족 — 기대 ≥2 (working+done), "
                f"실제 {len(planning_events)}"
            )
            statuses = {e.get("status") for e in planning_events}
            assert "working" in statuses
            assert "done" in statuses
            agents = {e.get("agent") for e in planning_events}
            assert "system_refactoring_strategist" in agents
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()


# =============================================================================
# 4. CLI flag → run_iterative_loop signature 통합
# =============================================================================
class TestStrategistCLIIntegration:
    def test_enable_strategist_flag_parses(self) -> None:
        """--enable-strategist CLI flag 가 args.enable_strategist=True 로 파싱."""
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = ["run.py", "--request", "X", "--enable-strategist", "--non-interactive"]
            from scripts.run import _parse_args

            args = _parse_args()
            assert args.enable_strategist is True
            assert args.enable_rv is False  # 독립 flag
        finally:
            _sys.argv = prev

    def test_run_iterative_loop_accepts_enable_strategist_kwarg(self) -> None:
        """run_iterative_loop 시그니처에 enable_strategist 추가 + default=False."""
        import inspect

        from src.workflows.iterative_loop import run_iterative_loop

        sig = inspect.signature(run_iterative_loop)
        assert "enable_strategist" in sig.parameters
        assert sig.parameters["enable_strategist"].default is False
