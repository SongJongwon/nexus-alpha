# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent, create_gui_test_agent
    from src.agents.qa import run_gui_test, format_gui_test_result_for_task

    reviewer = create_code_reviewer_agent()
    gui_agent = create_gui_test_agent()
    gui_result = run_gui_test(target_path=Path("Calculator.exe"), output_dir=Path("logs"))
"""

from .code_reviewer import (
    CODE_REVIEWER_BACKSTORY,
    CODE_REVIEWER_GOAL,
    CODE_REVIEWER_NAME,
    CODE_REVIEWER_ROLE,
    create_code_reviewer_agent,
)
from .gui_test_agent import (
    GUI_TEST_AGENT_BACKSTORY,
    GUI_TEST_AGENT_GOAL,
    GUI_TEST_AGENT_NAME,
    GUI_TEST_AGENT_ROLE,
    create_gui_test_agent,
)
from .gui_test_executor import (
    DEFAULT_VISION_MODEL,
    DEFAULT_VISION_PROMPT,
    GUITestResult,
    VisionAnalysis,
    analyze_screenshot,
    format_gui_test_result_for_task,
    launch_and_capture,
    run_gui_test,
)

__all__ = [
    # Code Reviewer (정적 분석, PR #25)
    "CODE_REVIEWER_BACKSTORY",
    "CODE_REVIEWER_GOAL",
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_ROLE",
    "create_code_reviewer_agent",
    # GUI Test Agent (시각 검증, PR #44)
    "GUI_TEST_AGENT_BACKSTORY",
    "GUI_TEST_AGENT_GOAL",
    "GUI_TEST_AGENT_NAME",
    "GUI_TEST_AGENT_ROLE",
    "create_gui_test_agent",
    # GUI Test Executor (결정론적 도구, PR #44)
    "DEFAULT_VISION_MODEL",
    "DEFAULT_VISION_PROMPT",
    "GUITestResult",
    "VisionAnalysis",
    "analyze_screenshot",
    "format_gui_test_result_for_task",
    "launch_and_capture",
    "run_gui_test",
]
