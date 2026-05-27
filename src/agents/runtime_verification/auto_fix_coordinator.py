# -*- coding: utf-8 -*-
"""Auto-Fix Coordinator — 본부 9 RV 오케스트레이터 (v13 Phase 1).

`Exe Runtime Tester` / `Runtime Failure Analyzer` / `UI Automation Specialist`
의 결과를 종합하여 *재빌드 trigger 결정* + *target agent 라우팅*.

자기 진화 루프의 *결정론 라우터* — Phase 3 의 `boardroom_trigger` 노드 도입
전까지 *간단 rule-based*. 향후 boardroom 으로 escalate.

Telemetry: `AgentStatusEvent(department="rv")` emit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult
    from src.agents.runtime_verification.runtime_failure_analyzer import FailureAnalysis
    from src.agents.runtime_verification.ui_automation_specialist import UIAutomationResult


# ---------------------------------------------------------------------------
# 결정 schema
# ---------------------------------------------------------------------------
@dataclass
class AutoFixDecision:
    """`decide_auto_fix` 의 산출 — 자기 진화 루프의 *라우팅 결정*.

    Attributes:
        action: ``"rebuild"`` (재빌드 trigger) / ``"retry"`` (즉시 재실행) /
            ``"escalate"`` (boardroom 으로 격상 — Phase 3 wire 필요) /
            ``"noop"`` (no action — PASS).
        target_agent: 라우팅 대상 (예: "python_engineer" / "gui_code_generator").
            ``escalate`` 시 ``"boardroom_facilitator"``.
        fix_instruction: 다음 agent 에게 전달할 *구체 처방 텍스트*.
        consecutive_failures: 연속 실패 카운트. 5 이상이면 escalate 강제.
        reason: 결정 사유 한 줄.
    """

    action: str
    target_agent: str
    fix_instruction: str
    consecutive_failures: int = 0
    reason: str = ""


def _try_emit_telemetry(agent: str, status: str, detail: str = "") -> None:
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
                department="rv",
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 라우팅 rule
# ---------------------------------------------------------------------------
ESCALATION_THRESHOLD: int = 5
"""5회 연속 실패 시 escalate 강제 (boardroom 으로 격상)."""


def _route_by_severity(severity: str, analysis_method: str) -> str:
    """severity + method 기반 *어떤 agent* 가 fix 해야 하는지 라우팅."""
    sev = (severity or "medium").lower()
    if sev == "critical":
        # entry 오선택 같은 빌드 워크플로 결함 — Build Engineer
        return "build_engineer"
    if sev == "high":
        # 코드 결함 (UnicodeEncodeError / ImportError / ModuleNotFoundError)
        return "python_engineer"
    # medium / low
    return "code_reviewer"


def decide_auto_fix(
    runtime_result: "RuntimeTestResult",
    failure_analysis: Optional["FailureAnalysis"] = None,
    ui_result: Optional["UIAutomationResult"] = None,
    consecutive_failures: int = 0,
) -> AutoFixDecision:
    """3개 RV 결과 종합 → *재빌드 trigger / escalate* 결정.

    Rule:
        1. runtime PASS + (ui PASS or skipped) → ``noop``
        2. consecutive_failures >= ESCALATION_THRESHOLD → ``escalate`` (boardroom)
        3. runtime SPAWN_ERROR → ``escalate`` (인프라 결함)
        4. runtime CRASH 또는 SILENT_FAIL → ``rebuild`` + severity 기반 라우팅
        5. ui FAIL (runtime PASS) → ``rebuild`` (GUI 결함 — gui_code_generator)

    Args:
        runtime_result: Exe Runtime Tester 결과.
        failure_analysis: Runtime Failure Analyzer 결과 (옵션 — 없으면 severity=medium 가정).
        ui_result: UI Automation Specialist 결과 (옵션).
        consecutive_failures: 호출 측이 누적한 연속 실패 카운트.

    Returns:
        AutoFixDecision.
    """
    _try_emit_telemetry(
        "auto_fix_coordinator",
        "working",
        f"verdict={runtime_result.verdict} consec={consecutive_failures}",
    )

    # 1. PASS — noop
    runtime_ok = runtime_result.verdict == "PASS"
    ui_ok = ui_result is None or ui_result.passed or ui_result.skipped
    if runtime_ok and ui_ok:
        decision = AutoFixDecision(
            action="noop",
            target_agent="(none)",
            fix_instruction="(no action — runtime + ui PASS)",
            consecutive_failures=0,  # 성공 시 카운트 reset
            reason="runtime PASS + ui PASS/skipped",
        )
        _try_emit_telemetry("auto_fix_coordinator", "done", "noop")
        return decision

    # 2. 연속 실패 threshold 초과 → escalate
    if consecutive_failures >= ESCALATION_THRESHOLD:
        decision = AutoFixDecision(
            action="escalate",
            target_agent="boardroom_facilitator",
            fix_instruction=(
                f"{consecutive_failures} 회 연속 실패. 본부 10 Boardroom 에서 "
                f"systemic 원인 토론 필요. 최근 분석: "
                f"{failure_analysis.root_cause if failure_analysis else 'N/A'}"
            ),
            consecutive_failures=consecutive_failures,
            reason=f"consecutive_failures={consecutive_failures} >= threshold={ESCALATION_THRESHOLD}",
        )
        _try_emit_telemetry(
            "auto_fix_coordinator", "done", f"escalate consec={consecutive_failures}"
        )
        return decision

    # 3. 인프라 결함 (spawn fail / file not found) → escalate
    if runtime_result.verdict == "SPAWN_ERROR":
        decision = AutoFixDecision(
            action="escalate",
            target_agent="boardroom_facilitator",
            fix_instruction=(
                f"인프라 결함 — .exe spawn 실패. error_trace: "
                f"{runtime_result.error_trace[:200]}"
            ),
            consecutive_failures=consecutive_failures + 1,
            reason="SPAWN_ERROR — 인프라 차원 escalate",
        )
        _try_emit_telemetry("auto_fix_coordinator", "done", "escalate spawn error")
        return decision

    # 4. runtime CRASH / SILENT_FAIL → rebuild + severity 기반 target
    if runtime_result.verdict in ("CRASH", "SILENT_FAIL"):
        severity = failure_analysis.severity if failure_analysis else "medium"
        target = _route_by_severity(severity, failure_analysis.analysis_method if failure_analysis else "rule")
        instruction = (
            failure_analysis.recommended_fix
            if failure_analysis
            else f"runtime verdict={runtime_result.verdict}. stderr: {(runtime_result.stderr or '')[:200]}"
        )
        decision = AutoFixDecision(
            action="rebuild",
            target_agent=target,
            fix_instruction=instruction,
            consecutive_failures=consecutive_failures + 1,
            reason=f"runtime {runtime_result.verdict} → {target} (severity={severity})",
        )
        _try_emit_telemetry(
            "auto_fix_coordinator",
            "done",
            f"rebuild → {target}",
        )
        return decision

    # 5. runtime PASS + ui FAIL → GUI 결함
    if runtime_ok and ui_result is not None and not ui_result.passed and not ui_result.skipped:
        decision = AutoFixDecision(
            action="rebuild",
            target_agent="gui_code_generator",
            fix_instruction=(
                f"GUI 시나리오 step[{ui_result.failed_step_index}] 실패: "
                f"{ui_result.failed_step_reason}. "
                f"GUI widget 배치 또는 이벤트 핸들러 검토."
            ),
            consecutive_failures=consecutive_failures + 1,
            reason=f"ui step[{ui_result.failed_step_index}] FAIL",
        )
        _try_emit_telemetry(
            "auto_fix_coordinator", "done", "rebuild gui_code_generator"
        )
        return decision

    # Fallback (예상 못한 조합)
    decision = AutoFixDecision(
        action="retry",
        target_agent="(none)",
        fix_instruction="(unexpected combination — single retry)",
        consecutive_failures=consecutive_failures + 1,
        reason="unexpected RV result combination — retry once",
    )
    _try_emit_telemetry("auto_fix_coordinator", "done", "retry — unexpected")
    return decision
