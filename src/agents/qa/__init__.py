# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent, create_functional_test_agent
    from src.agents.qa import run_test_cases, format_functional_test_result_for_task

    reviewer = create_code_reviewer_agent()
    ft_agent = create_functional_test_agent()
    ft_result = run_test_cases(target_script=Path("calculator.py"))
"""

from .code_reviewer import (
    CODE_REVIEWER_BACKSTORY,
    CODE_REVIEWER_GOAL,
    CODE_REVIEWER_NAME,
    CODE_REVIEWER_ROLE,
    create_code_reviewer_agent,
)
from .functional_test_agent import (
    FUNCTIONAL_TEST_AGENT_BACKSTORY,
    FUNCTIONAL_TEST_AGENT_GOAL,
    FUNCTIONAL_TEST_AGENT_NAME,
    FUNCTIONAL_TEST_AGENT_ROLE,
    create_functional_test_agent,
)
from .functional_test_executor import (
    DEFAULT_EDGE_CASES,
    FunctionalTestResult,
    TestCase,
    TestCaseResult,
    format_functional_test_result_for_task,
    run_test_cases,
)

__all__ = [
    # Code Reviewer (정적 분석, PR #25)
    "CODE_REVIEWER_BACKSTORY",
    "CODE_REVIEWER_GOAL",
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_ROLE",
    "create_code_reviewer_agent",
    # Functional Test Agent (엣지케이스 동적 검증, PR #43)
    "FUNCTIONAL_TEST_AGENT_BACKSTORY",
    "FUNCTIONAL_TEST_AGENT_GOAL",
    "FUNCTIONAL_TEST_AGENT_NAME",
    "FUNCTIONAL_TEST_AGENT_ROLE",
    "create_functional_test_agent",
    # Functional Test Executor (결정론적 도구, PR #43)
    "DEFAULT_EDGE_CASES",
    "FunctionalTestResult",
    "TestCase",
    "TestCaseResult",
    "format_functional_test_result_for_task",
    "run_test_cases",
]
