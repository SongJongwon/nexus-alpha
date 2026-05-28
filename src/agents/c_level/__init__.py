# -*- coding: utf-8 -*-
"""
C-Level (경영 의사결정) 에이전트 패키지.

사용 예:
    from src.agents.c_level import (
        create_cto_agent,
        create_convergence_judge_agent,
        judge_convergence,
        create_goal_alignment_agent,
        assess_alignment,
        create_token_budget_optimizer_agent,
        assess_budget,
    )

    cto = create_cto_agent()
    judge = create_convergence_judge_agent()  # v3 (Phase 2.5)
    ga = create_goal_alignment_agent()        # v13 Phase 4
    tbo = create_token_budget_optimizer_agent()  # v13 Phase 4

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
from .goal_alignment_agent import (
    GOAL_ALIGNMENT_AGENT_BACKSTORY,
    GOAL_ALIGNMENT_AGENT_GOAL,
    GOAL_ALIGNMENT_AGENT_NAME,
    GOAL_ALIGNMENT_AGENT_ROLE,
    assess_alignment,
    create_goal_alignment_agent,
)
from .token_budget_optimizer import (
    DEFAULT_BUDGET_LIMIT_USD,
    TOKEN_BUDGET_OPTIMIZER_BACKSTORY,
    TOKEN_BUDGET_OPTIMIZER_GOAL,
    TOKEN_BUDGET_OPTIMIZER_NAME,
    TOKEN_BUDGET_OPTIMIZER_ROLE,
    BudgetSnapshot,
    assess_budget,
    create_token_budget_optimizer_agent,
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
    "DEFAULT_BUDGET_LIMIT_USD",
    "DEFAULT_MAX_ITERATIONS",
    "GOAL_ALIGNMENT_AGENT_BACKSTORY",
    "GOAL_ALIGNMENT_AGENT_GOAL",
    "GOAL_ALIGNMENT_AGENT_NAME",
    "GOAL_ALIGNMENT_AGENT_ROLE",
    "NO_BUDGET_GATE",
    "TOKEN_BUDGET_OPTIMIZER_BACKSTORY",
    "TOKEN_BUDGET_OPTIMIZER_GOAL",
    "TOKEN_BUDGET_OPTIMIZER_NAME",
    "TOKEN_BUDGET_OPTIMIZER_ROLE",
    "BlockedCause",
    "BudgetSnapshot",
    "GapReport",
    "JudgmentDecision",
    "Verdict",
    "assess_alignment",
    "assess_budget",
    "create_convergence_judge_agent",
    "create_cto_agent",
    "create_goal_alignment_agent",
    "create_token_budget_optimizer_agent",
    "format_judgment_decision_for_task",
    "judge_convergence",
    "parse_gap_report_from_yaml",
]
