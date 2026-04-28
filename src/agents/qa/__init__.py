# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent
    from src.agents.qa import create_code_qa_agent, run_code_qa
    from src.agents.qa import create_functional_test_agent, run_test_cases
"""

from .code_qa_agent import (
    CODE_QA_AGENT_BACKSTORY,
    CODE_QA_AGENT_GOAL,
    CODE_QA_AGENT_NAME,
    CODE_QA_AGENT_ROLE,
    create_code_qa_agent,
)
from .code_qa_executor import (
    CodeQAResult,
    PytestResult,
    RuffResult,
    format_code_qa_result_for_task,
    run_code_qa,
    run_pytest,
    run_ruff,
)
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
    # Code QA Agent (실행 기반, PR #42)
    "CODE_QA_AGENT_BACKSTORY",
    "CODE_QA_AGENT_GOAL",
    "CODE_QA_AGENT_NAME",
    "CODE_QA_AGENT_ROLE",
    "create_code_qa_agent",
    # Code QA Executor (결정론적 도구, PR #42)
    "CodeQAResult",
    "PytestResult",
    "RuffResult",
    "format_code_qa_result_for_task",
    "run_code_qa",
    "run_pytest",
    "run_ruff",
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
