# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent, create_code_qa_agent
    from src.agents.qa import run_code_qa, format_code_qa_result_for_task

    reviewer = create_code_reviewer_agent()
    qa_agent = create_code_qa_agent()
    qa_result = run_code_qa(target_dir=Path("src/tests"))
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
]
