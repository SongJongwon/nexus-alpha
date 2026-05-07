# -*- coding: utf-8 -*-
"""
Nexus Alpha 워크플로우 패키지.

사용 예:
    from src.workflows import run_analyze_and_implement

    result = run_analyze_and_implement(
        "매출 Excel을 분석해 PDF 보고서로 만드는 Python 스크립트를 만들어줘"
    )
    print(result.saved_dir)
"""

from .analyze_and_implement import WorkflowResult, run_analyze_and_implement
from .automate_workflow import (
    AutomateWorkflowResult,
    AutomationDomain,
    detect_automation_domain,
    run_automate_workflow,
)
from .build_workflow import BuildWorkflowResult, run_build_workflow
from .iterative_loop import (
    LoopOutcome,
    build_iterative_loop_graph,
    run_iterative_loop,
)
from .release_workflow import ReleaseWorkflowResult, run_release_workflow
from .router import Intent, RoutingDecision, route_request

__all__ = [
    # Track A — analyze_and_implement (Calculator.exe 풀체인)
    "WorkflowResult",
    "run_analyze_and_implement",
    # Track B — automate_workflow (Phase 6, PR #70)
    "AutomateWorkflowResult",
    "AutomationDomain",
    "detect_automation_domain",
    "run_automate_workflow",
    # Phase 4.5 / 5
    "BuildWorkflowResult",
    "ReleaseWorkflowResult",
    "run_build_workflow",
    "run_release_workflow",
    # Routing + LangGraph loop
    "Intent",
    "RoutingDecision",
    "route_request",
    "LoopOutcome",
    "build_iterative_loop_graph",
    "run_iterative_loop",
]
