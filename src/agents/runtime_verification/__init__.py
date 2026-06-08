# -*- coding: utf-8 -*-
"""본부 9 — Runtime Verification (RV) 에이전트 패키지.

v13 Phase 1 (★최우선) — 자기 진화 루프의 *안테나* 노드 4명. 빌드된 .exe 의
런타임 동작을 자율 인지 → 이사회 안건 발제로 이어지는 흐름의 *감지 layer*.

조직도 v13 본부 9 명단:
    - Exe Runtime Tester       — `.exe` sandbox 실행 + 측정 (결정론)
    - Runtime Failure Analyzer — stderr/trace 분석 → actionable feedback (LLM)
    - UI Automation Specialist — PyAutoGUI/Playwright 시나리오 자동 수행
    - Auto-Fix Coordinator     — 3개 결과 종합 → 재빌드 trigger / escalate 결정

Telemetry 부서 식별자: ``department="rv"`` (system_architecture.md 계층 2.5 명세).
"""

from src.agents.runtime_verification.exe_runtime_tester import (
    RuntimeTestResult,
    run_exe_runtime_test,
)
from src.agents.runtime_verification.runtime_failure_analyzer import (
    FailureAnalysis,
    analyze_runtime_failure,
    create_runtime_failure_analyzer_agent,
)
from src.agents.runtime_verification.ui_automation_specialist import (
    UIAutomationResult,
    UIScenarioStep,
    run_ui_automation_scenario,
)
from src.agents.runtime_verification.auto_fix_coordinator import (
    AutoFixDecision,
    decide_auto_fix,
)
from src.agents.runtime_verification.desktop_smoke_gate import (
    DesktopSmokeResult,
    run_desktop_smoke_gate,
)
from src.agents.runtime_verification.packageability_gate import (
    PackageabilityResult,
    analyze_web_packageability,
    run_packageability_gate,
)

RV_DEPARTMENT: str = "rv"
"""Telemetry 부서 식별자 — 본부 9 의 모든 agent 가 emit 시 사용."""

__all__ = [
    # Exe Runtime Tester
    "RuntimeTestResult",
    "run_exe_runtime_test",
    # Runtime Failure Analyzer
    "FailureAnalysis",
    "analyze_runtime_failure",
    "create_runtime_failure_analyzer_agent",
    # UI Automation Specialist
    "UIAutomationResult",
    "UIScenarioStep",
    "run_ui_automation_scenario",
    # Auto-Fix Coordinator
    "AutoFixDecision",
    "decide_auto_fix",
    # v13 P23 — Desktop .exe runtime smoke gate
    "DesktopSmokeResult",
    "run_desktop_smoke_gate",
    # v13 P25 — 산출물 배포성(packageability) 게이트
    "PackageabilityResult",
    "analyze_web_packageability",
    "run_packageability_gate",
    # Department identifier
    "RV_DEPARTMENT",
]
