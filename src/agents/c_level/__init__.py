# -*- coding: utf-8 -*-
"""
C-Level (경영 의사결정) 에이전트 패키지.

사용 예:
    from src.agents.c_level import (
        create_cto_agent,
        create_convergence_judge_agent,
        judge_convergence,
    )

    cto = create_cto_agent()
    judge = create_convergence_judge_agent()  # v3 (Phase 2.5)

    # 결정표는 LLM 무관 — 직접 호출 가능
    decision = judge_convergence(gap_report, max_iterations=5, ...)
"""

from .convergence_judge import (
    CONVERGENCE_JUDGE_BACKSTORY,
    CONVERGENCE_JUDGE_GOAL,
    CONVERGENCE_JUDGE_NAME,
    CONVERGENCE_JUDGE_ROLE,
    DEFAULT_MAX_ITERATIONS,
    NO_BUDGET_GATE,
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    create_convergence_judge_agent,
    format_judgment_decision_for_task,
    judge_convergence,
    parse_gap_report_from_yaml,
)
from .cto import (
    CTO_BACKSTORY,
    CTO_GOAL,
    CTO_NAME,
    CTO_ROLE,
    create_cto_agent,
)

__all__ = [
    "CONVERGENCE_JUDGE_BACKSTORY",
    "CONVERGENCE_JUDGE_GOAL",
    "CONVERGENCE_JUDGE_NAME",
    "CONVERGENCE_JUDGE_ROLE",
    "CTO_BACKSTORY",
    "CTO_GOAL",
    "CTO_NAME",
    "CTO_ROLE",
    "DEFAULT_MAX_ITERATIONS",
    "NO_BUDGET_GATE",
    "BlockedCause",
    "GapReport",
    "JudgmentDecision",
    "Verdict",
    "create_convergence_judge_agent",
    "create_cto_agent",
    "format_judgment_decision_for_task",
    "judge_convergence",
    "parse_gap_report_from_yaml",
]
