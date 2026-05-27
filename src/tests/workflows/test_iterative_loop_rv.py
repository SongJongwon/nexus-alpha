# -*- coding: utf-8 -*-
"""본부 9 Runtime Verification 워크플로 연동 테스트 (v13 Phase 1 2단계, PR #217).

검증 시나리오 4종:
    1. ``enable_rv=False`` (default) → ``_node_runtime_verify`` 가 즉시 빈 dict
       반환 (pass-through). 기존 1477 PASS 파이프라인 회귀 0 보장.
    2. ``enable_rv=True`` + silent fail .exe → ``rv_failure_detected=True`` +
       ``rv_result.verdict == "SILENT_FAIL"`` 가 state 에 보존 (prepare_feedback
       분기 trigger 확보).
    3. ``enable_rv=True`` + PASS .exe → ``rv_failure_detected=False`` (기존
       ``analyze_gap`` 경로로 자연 진행).
    4. Telemetry 부서 매핑 — ``department_for_node("runtime_verify") == "rv"``
       + AgentStatusEvent 의 department 필드 일관성.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult
from src.monitoring.telemetry import (
    RV,
    AgentStatusEvent,
    _NODE_DEPARTMENT,
    department_for_node,
)
from src.workflows import build_iterative_loop_graph, run_iterative_loop
from src.workflows.iterative_loop import _node_runtime_verify


# =============================================================================
# 1. enable_rv OFF (default) — 기존 파이프라인 무회귀 보장
# =============================================================================
class TestEnableRvDefaultOff:
    """⭐ 1477 PASS 회귀 0 — default OFF pass-through."""

    def test_node_returns_empty_when_enable_rv_false(self) -> None:
        """``enable_rv=False`` (default) → ``{}`` 반환 (state 변경 0)."""
        state = {"enable_rv": False, "chain_result": None}
        result = _node_runtime_verify(state)
        assert result == {}

    def test_node_returns_empty_when_enable_rv_missing(self) -> None:
        """``enable_rv`` key 미존재 → 안전하게 pass-through (default False)."""
        state = {"chain_result": None}
        result = _node_runtime_verify(state)
        assert result == {}

    def test_run_iterative_loop_accepts_enable_rv_kwarg(self) -> None:
        """``run_iterative_loop`` 시그니처에 ``enable_rv`` 추가 + default=False 보존."""
        import inspect

        sig = inspect.signature(run_iterative_loop)
        assert "enable_rv" in sig.parameters
        assert sig.parameters["enable_rv"].default is False


# =============================================================================
# 2. enable_rv ON + silent fail — prepare_feedback 분기 trigger 확보
# =============================================================================
class TestSilentFailDetection:
    """⭐ silent fail .exe 자율 감지 시 rv_failure_detected=True 보존."""

    @patch("src.agents.runtime_verification.run_exe_runtime_test")
    def test_silent_fail_sets_failure_detected_true(
        self, mock_run_rv: MagicMock, tmp_path: Path
    ) -> None:
        """SILENT_FAIL verdict → ``rv_failure_detected=True``."""
        # fake .exe 파일 1개 — 실제 실행은 mock 가로채므로 빈 파일이면 충분
        fake_exe = tmp_path / "FakeApp.exe"
        fake_exe.write_bytes(b"")

        mock_run_rv.return_value = RuntimeTestResult(
            exit_code=0,
            stderr="",
            stdout="",
            startup_time_ms=10.0,
            memory_peak_mb=None,
            timed_out=False,
            verdict="SILENT_FAIL",
            error_trace="(exit 0 immediate — silent fail)",
            exe_path=fake_exe,
        )

        # chain_result.executor_result.exe_path 를 통해 .exe 경로 노출
        executor_result = MagicMock()
        executor_result.exe_path = fake_exe
        chain_result = MagicMock()
        chain_result.executor_result = executor_result

        state = {"enable_rv": True, "chain_result": chain_result}
        result = _node_runtime_verify(state)

        assert result["rv_failure_detected"] is True
        assert result["rv_result"].verdict == "SILENT_FAIL"
        mock_run_rv.assert_called_once()


# =============================================================================
# 3. enable_rv ON + PASS — analyze_gap 으로 자연 진행
# =============================================================================
class TestPassContinuation:
    """⭐ PASS verdict → rv_failure_detected=False, 기존 흐름과 동일."""

    @patch("src.agents.runtime_verification.run_exe_runtime_test")
    def test_pass_keeps_failure_detected_false(
        self, mock_run_rv: MagicMock, tmp_path: Path
    ) -> None:
        """PASS verdict → ``rv_failure_detected=False`` (analyze_gap 진행)."""
        fake_exe = tmp_path / "FakeApp.exe"
        fake_exe.write_bytes(b"")

        mock_run_rv.return_value = RuntimeTestResult(
            exit_code=0,
            stderr="",
            stdout="",
            startup_time_ms=120.0,
            memory_peak_mb=12.5,
            timed_out=True,  # alive 동안 정상 — timeout 으로 terminate
            verdict="PASS",
            error_trace="",
            exe_path=fake_exe,
        )

        executor_result = MagicMock()
        executor_result.exe_path = fake_exe
        chain_result = MagicMock()
        chain_result.executor_result = executor_result

        state = {"enable_rv": True, "chain_result": chain_result}
        result = _node_runtime_verify(state)

        assert result["rv_failure_detected"] is False
        assert result["rv_result"].verdict == "PASS"

    def test_no_exe_returns_empty_even_when_enabled(self) -> None:
        """enable_rv=True 인데 .exe 가 없으면 → no-op (회귀 0)."""
        chain_result = MagicMock()
        chain_result.executor_result = None
        state = {"enable_rv": True, "chain_result": chain_result}
        result = _node_runtime_verify(state)
        assert result == {}

    @patch("src.agents.runtime_verification.run_exe_runtime_test")
    def test_run_exe_runtime_test_exception_does_not_break_pipeline(
        self, mock_run_rv: MagicMock, tmp_path: Path
    ) -> None:
        """run_exe_runtime_test 예외 시 silent + {} 반환 (메인 cycle 차단 X)."""
        fake_exe = tmp_path / "FakeApp.exe"
        fake_exe.write_bytes(b"")
        mock_run_rv.side_effect = RuntimeError("psutil missing")

        executor_result = MagicMock()
        executor_result.exe_path = fake_exe
        chain_result = MagicMock()
        chain_result.executor_result = executor_result

        state = {"enable_rv": True, "chain_result": chain_result}
        result = _node_runtime_verify(state)
        assert result == {}


# =============================================================================
# 4. Telemetry — dept="rv" 매핑 일관성
# =============================================================================
class TestTelemetryRvDepartment:
    """⭐ runtime_verify 노드 → department="rv" 일관성 (system_architecture.md 계층 2.5)."""

    def test_node_department_mapping(self) -> None:
        """``_NODE_DEPARTMENT["runtime_verify"] == "rv"`` (RV 상수와 일치)."""
        assert _NODE_DEPARTMENT["runtime_verify"] == "rv"
        assert RV == "rv"

    def test_department_for_node_returns_rv(self) -> None:
        """``department_for_node("runtime_verify") == "rv"``."""
        assert department_for_node("runtime_verify") == "rv"

    def test_agent_status_event_with_rv_department(self) -> None:
        """``AgentStatusEvent`` 가 dept="rv" 로 정상 생성."""
        evt = AgentStatusEvent(
            agent="runtime_verify",
            department=department_for_node("runtime_verify"),
            status="working",
            detail="iter=1",
        )
        assert evt.department == "rv"
        assert evt.type == "agent_status"
        assert evt.agent == "runtime_verify"

    def test_graph_includes_runtime_verify_node(self) -> None:
        """LangGraph 가 ``runtime_verify`` 노드를 포함 (build_iterative_loop_graph)."""
        graph = build_iterative_loop_graph()
        # compiled graph 의 nodes 속성을 안전하게 접근
        nodes = getattr(graph, "nodes", None) or getattr(graph.get_graph(), "nodes", {})
        node_names = set(nodes.keys()) if hasattr(nodes, "keys") else set(nodes)
        assert "runtime_verify" in node_names


# =============================================================================
# 5. ⭐ E2E 통합 — 실 telemetry emit 검증 (PR #217 후속, unit test gap 보완)
# =============================================================================
class TestEndToEndTelemetryEmission:
    """⭐ Phase 3 (boardroom_trigger / goal_alignment / budget_brake) 통합 시 동일
    함정 방지용 패턴.

    Unit test gap (PR #217 사고 원인):
        기존 단위 test 는 `run_exe_runtime_test` 를 mock 해서 함수 동작만 검증.
        실제 `_telemetry_wrap` 이 노드를 감싸서 emit 하는 *통합 시점* 은 검증 X.
        결과: 라이브 환경에서 dept="rv" 이벤트가 실제로 events.jsonl 에 떨어지는지
        보장 안 됨.

    본 E2E 검증:
        실제 LangGraph invoke + 실제 TelemetryEmitter (NEXUS_TELEMETRY_PATH set)
        → events.jsonl 에 dept="rv" 이벤트 ≥ 2 (working + done) 확인.
    """

    def test_runtime_verify_emits_dept_rv_to_events_file(self, tmp_path: Path) -> None:
        """⭐ enable_rv=True + 실 telemetry → events.jsonl 에 dept="rv" emit 보장."""
        import json
        import os

        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            # iterative_loop 의 노드 함수를 monkey-patch 해 graph invoke 시간 단축.
            # 핵심: runtime_verify 노드는 그대로 두고 _telemetry_wrap 의 emit 동작만 검증.
            import src.workflows.iterative_loop as IL
            from src.agents.c_level import (
                BlockedCause,
                GapReport,
                JudgmentDecision,
                Verdict,
            )

            def _noop(state: dict) -> dict:
                return {}

            def _fake_judge(state: dict) -> dict:
                return {
                    "decision": JudgmentDecision(
                        verdict=Verdict.COMPLETE,
                        blocked_cause=BlockedCause.NONE,
                        reason="test",
                        next_action="ok",
                        must_fix_count=0,
                    )
                }

            def _fake_analyze(state: dict) -> dict:
                return {"gap_report": GapReport()}

            # 비-RV 노드 mock — runtime_verify 와 _telemetry_wrap 만 *실제* 실행.
            patches = {
                "_node_expand_requirements": _noop,
                "_node_recall_past_knowledge": _noop,
                "_node_kickoff_meeting": _noop,
                "_node_run_chain": _noop,
                "_node_run_sandbox": _noop,
                "_node_analyze_gap": _fake_analyze,
                "_node_judge_convergence": _fake_judge,
                "_node_prepare_feedback": _noop,
                "_node_retrospective": _noop,
                "_node_curate_knowledge": _noop,
                "_node_finalize": _noop,
                "_node_escalate": _noop,
            }
            originals = {name: getattr(IL, name) for name in patches}
            for name, fn in patches.items():
                setattr(IL, name, fn)

            try:
                compiled = IL.build_iterative_loop_graph()
                compiled.invoke(
                    {
                        "enable_rv": True,
                        "chain_result": None,  # no exe → _node_runtime_verify pass-through {}
                        "iteration": 0,
                        "max_iterations": 1,
                        "budget_tokens_remaining": -1,
                        "user_request": "X",
                        "outputs_dir": str(tmp_path),
                        "iteration_artifacts": [],
                        "feedback": "",
                        "track": "A",
                        "verbose": False,
                    },
                    config={"recursion_limit": 50},
                )
            finally:
                for name, fn in originals.items():
                    setattr(IL, name, fn)

            # events.jsonl 검증
            assert events_path.exists(), "events.jsonl 미생성 — telemetry emit 누락"
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            assert lines, "events.jsonl 비어있음"

            # JSON parse 후 department 필드 검증 (raw string 매칭 X — JSON 포매팅
            # 변화에 견고)
            parsed = [json.loads(line) for line in lines]
            rv_events = [e for e in parsed if e.get("department") == "rv"]
            assert len(rv_events) >= 2, (
                f"dept='rv' 이벤트 부족 — 기대 ≥2 (working+done), 실제 {len(rv_events)}"
            )

            # working + done 둘 다 emit 됐는지 확인 (PR #217 노드 통합 보장)
            statuses = {e.get("status") for e in rv_events}
            assert "working" in statuses, "runtime_verify working 이벤트 누락"
            assert "done" in statuses, "runtime_verify done 이벤트 누락"

            # agent 이름은 runtime_verify (노드 이름)
            agents = {e.get("agent") for e in rv_events}
            assert "runtime_verify" in agents

        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()

    def test_runtime_verify_emits_artifact_md(self, tmp_path: Path) -> None:
        """⭐ enable_rv=True + .exe + saved_dir → 26_runtime_verify_*.md 작성."""
        from src.agents.runtime_verification.exe_runtime_tester import (
            RuntimeTestResult,
        )
        from src.workflows.iterative_loop import _node_runtime_verify

        saved_dir = tmp_path / "workflow"
        saved_dir.mkdir(parents=True)
        fake_exe = tmp_path / "Calculator.exe"
        fake_exe.write_bytes(b"")

        executor_result = MagicMock()
        executor_result.exe_path = fake_exe
        chain_result = MagicMock()
        chain_result.executor_result = executor_result
        chain_result.saved_dir = saved_dir

        rv_pass = RuntimeTestResult(
            exit_code=0,
            stderr="",
            stdout="",
            startup_time_ms=120.0,
            memory_peak_mb=12.5,
            timed_out=True,
            verdict="PASS",
            error_trace="",
            exe_path=fake_exe,
        )

        with patch(
            "src.agents.runtime_verification.run_exe_runtime_test",
            return_value=rv_pass,
        ):
            state = {"enable_rv": True, "chain_result": chain_result}
            _node_runtime_verify(state)

        # 26_runtime_verify_pass.md artifact 생성 확인
        artifact = saved_dir / "26_runtime_verify_pass.md"
        assert artifact.exists(), f"artifact 누락 — {artifact}"
        content = artifact.read_text(encoding="utf-8")
        assert "Runtime Verification" in content
        assert "PASS" in content
        assert "Calculator.exe" in content
