# -*- coding: utf-8 -*-
"""
운영 지원(Operations) 에이전트 패키지.

사용 예:
    from src.agents.operations import (
        SandboxResult,
        create_sandbox_runner_agent,
        format_sandbox_result_for_task,
        run_python_in_sandbox,
    )

    # 1단계: 결정론적 실행
    result = run_python_in_sandbox("print(1+1)", timeout_sec=10)

    # 2단계: LLM Agent에 결과 해석을 맡김
    agent = create_sandbox_runner_agent()
    # ... Task(description=format_sandbox_result_for_task(result), agent=agent)
"""

from .sandbox_runner import (
    SANDBOX_RUNNER_BACKSTORY,
    SANDBOX_RUNNER_GOAL,
    SANDBOX_RUNNER_NAME,
    SANDBOX_RUNNER_ROLE,
    SandboxResult,
    create_sandbox_runner_agent,
    format_sandbox_result_for_task,
    run_python_in_sandbox,
    run_python_package_in_sandbox,
)

__all__ = [
    "SANDBOX_RUNNER_BACKSTORY",
    "SANDBOX_RUNNER_GOAL",
    "SANDBOX_RUNNER_NAME",
    "SANDBOX_RUNNER_ROLE",
    "SandboxResult",
    "create_sandbox_runner_agent",
    "format_sandbox_result_for_task",
    "run_python_in_sandbox",
    "run_python_package_in_sandbox",
]
