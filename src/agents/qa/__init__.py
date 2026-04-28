# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent

    reviewer = create_code_reviewer_agent()
"""

from .code_reviewer import (
    CODE_REVIEWER_BACKSTORY,
    CODE_REVIEWER_GOAL,
    CODE_REVIEWER_NAME,
    CODE_REVIEWER_ROLE,
    create_code_reviewer_agent,
)
from .robustness_executor import (
    DEFAULT_SCENARIOS,
    RobustnessResult,
    RobustnessScenario,
    ScenarioResult,
    format_robustness_result_for_task,
    run_robustness_scenarios,
)
from .robustness_tester import (
    ROBUSTNESS_TESTER_BACKSTORY,
    ROBUSTNESS_TESTER_GOAL,
    ROBUSTNESS_TESTER_NAME,
    ROBUSTNESS_TESTER_ROLE,
    create_robustness_tester_agent,
)

__all__ = [
    # Code Reviewer (정적, PR #25)
    "CODE_REVIEWER_BACKSTORY",
    "CODE_REVIEWER_GOAL",
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_ROLE",
    "create_code_reviewer_agent",
    # Robustness Tester (부하 시나리오, PR #46)
    "ROBUSTNESS_TESTER_BACKSTORY",
    "ROBUSTNESS_TESTER_GOAL",
    "ROBUSTNESS_TESTER_NAME",
    "ROBUSTNESS_TESTER_ROLE",
    "create_robustness_tester_agent",
    "DEFAULT_SCENARIOS",
    "RobustnessResult",
    "RobustnessScenario",
    "ScenarioResult",
    "format_robustness_result_for_task",
    "run_robustness_scenarios",
]
