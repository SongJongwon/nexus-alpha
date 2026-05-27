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
