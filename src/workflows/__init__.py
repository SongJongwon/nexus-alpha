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
from .build_workflow import BuildWorkflowResult, run_build_workflow
from .iterative_loop import (
    LoopOutcome,
    build_iterative_loop_graph,
    run_iterative_loop,
)
from .router import Intent, RoutingDecision, route_request

__all__ = [
    "BuildWorkflowResult",
    "Intent",
    "LoopOutcome",
    "RoutingDecision",
    "WorkflowResult",
    "build_iterative_loop_graph",
    "route_request",
    "run_analyze_and_implement",
    "run_build_workflow",
    "run_iterative_loop",
]
