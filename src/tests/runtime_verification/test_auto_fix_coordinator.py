# -*- coding: utf-8 -*-
"""Auto-Fix Coordinator 단위 test (v13 Phase 1)."""

from __future__ import annotations

from pathlib import Path

from src.agents.runtime_verification.auto_fix_coordinator import (
    AutoFixDecision,
    ESCALATION_THRESHOLD,
    decide_auto_fix,
)
from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult
from src.agents.runtime_verification.runtime_failure_analyzer import FailureAnalysis
from src.agents.runtime_verification.ui_automation_specialist import (
    UIAutomationResult,
)


def _rt(verdict: str, stderr: str = "", exit_code: int = 0) -> RuntimeTestResult:
    return RuntimeTestResult(
        exit_code=exit_code,
        stderr=stderr,
        stdout="",
        startup_time_ms=50.0,
        memory_peak_mb=None,
        timed_out=verdict == "PASS",
        verdict=verdict,
        error_trace=stderr,
        exe_path=Path("C:/fake.exe"),
    )


def _analysis(severity: str = "high", method: str = "rule") -> FailureAnalysis:
    return FailureAnalysis(
        root_cause="test cause",
        recommended_fix="test fix",
        severity=severity,
        confidence=0.9,
        analysis_method=method,
    )


class TestDecisionSchema:
    def test_dataclass_fields(self):
        d = AutoFixDecision(action="rebuild", target_agent="python_engineer", fix_instruction="fix")
        assert d.action == "rebuild"
        assert d.consecutive_failures == 0


class TestNoOpRule:
    """Rule 1 — runtime PASS + ui PASS → noop."""

    def test_pass_runtime_no_ui(self):
        decision = decide_auto_fix(_rt("PASS"))
        assert decision.action == "noop"
        assert decision.consecutive_failures == 0  # success 시 reset

    def test_pass_runtime_and_ui(self):
        ui = UIAutomationResult(passed=True, completed_steps=5, failed_step_index=None, failed_step_reason=None)
        decision = decide_auto_fix(_rt("PASS"), ui_result=ui)
        assert decision.action == "noop"

    def test_pass_runtime_ui_skipped(self):
        """ui skipped 도 noop — 의미적 SKIP."""
        ui = UIAutomationResult(
            passed=True, completed_steps=0, failed_step_index=None,
            failed_step_reason="pyautogui not avail", skipped=True,
        )
        decision = decide_auto_fix(_rt("PASS"), ui_result=ui)
        assert decision.action == "noop"


class TestEscalationThreshold:
    """⭐ Rule 2 — 5회 연속 실패 시 escalate (DoD 의 핵심)."""

    def test_consec_5_triggers_escalate(self):
        decision = decide_auto_fix(
            _rt("CRASH", stderr="UnicodeEncodeError"),
            failure_analysis=_analysis(severity="high"),
            consecutive_failures=ESCALATION_THRESHOLD,
        )
        assert decision.action == "escalate"
        assert decision.target_agent == "boardroom_facilitator"

    def test_consec_4_does_not_escalate(self):
        """4회는 아직 rebuild — threshold 미달."""
        decision = decide_auto_fix(
            _rt("CRASH"),
            failure_analysis=_analysis(severity="high"),
            consecutive_failures=4,
        )
        assert decision.action == "rebuild"
        assert decision.consecutive_failures == 5  # +1 누적

    def test_consec_10_still_escalates(self):
        decision = decide_auto_fix(
            _rt("CRASH"), failure_analysis=_analysis(), consecutive_failures=10,
        )
        assert decision.action == "escalate"


class TestSpawnErrorRule:
    """Rule 3 — SPAWN_ERROR → escalate (인프라 결함)."""

    def test_spawn_error_escalates(self):
        decision = decide_auto_fix(_rt("SPAWN_ERROR", stderr="file not found"))
        assert decision.action == "escalate"
        assert decision.target_agent == "boardroom_facilitator"


class TestCrashSilentFailRouting:
    """Rule 4 — severity 기반 rebuild target 라우팅."""

    def test_critical_severity_routes_to_build_engineer(self):
        decision = decide_auto_fix(
            _rt("SILENT_FAIL"),
            failure_analysis=_analysis(severity="critical"),
        )
        assert decision.action == "rebuild"
        assert decision.target_agent == "build_engineer"

    def test_high_severity_routes_to_python_engineer(self):
        decision = decide_auto_fix(
            _rt("CRASH", stderr="UnicodeEncodeError"),
            failure_analysis=_analysis(severity="high"),
        )
        assert decision.action == "rebuild"
        assert decision.target_agent == "python_engineer"
        assert "test fix" in decision.fix_instruction

    def test_medium_severity_routes_to_code_reviewer(self):
        decision = decide_auto_fix(
            _rt("CRASH"),
            failure_analysis=_analysis(severity="medium"),
        )
        assert decision.action == "rebuild"
        assert decision.target_agent == "code_reviewer"

    def test_crash_without_analysis_uses_default(self):
        """failure_analysis None 시 severity=medium 가정."""
        decision = decide_auto_fix(_rt("CRASH", stderr="some error"))
        assert decision.action == "rebuild"
        assert decision.target_agent == "code_reviewer"


class TestUIFailRouting:
    """Rule 5 — runtime PASS + ui FAIL → gui_code_generator."""

    def test_ui_fail_routes_to_gui_code_generator(self):
        ui = UIAutomationResult(
            passed=False,
            completed_steps=2,
            failed_step_index=2,
            failed_step_reason="button not found",
        )
        decision = decide_auto_fix(_rt("PASS"), ui_result=ui)
        assert decision.action == "rebuild"
        assert decision.target_agent == "gui_code_generator"
        assert "step[2]" in decision.fix_instruction
