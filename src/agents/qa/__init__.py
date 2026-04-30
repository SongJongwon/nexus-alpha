# -*- coding: utf-8 -*-
"""
품질 검증(QA) 에이전트 패키지.

사용 예:
    from src.agents.qa import create_code_reviewer_agent
    from src.agents.qa import create_code_qa_agent, run_code_qa
    from src.agents.qa import create_functional_test_agent, run_test_cases
    from src.agents.qa import create_gui_test_agent, run_gui_test
    from src.agents.qa import create_robustness_tester_agent, run_robustness_scenarios
    from src.agents.qa import create_security_auditor_agent
    from src.agents.qa import create_performance_engineer_agent
    from src.agents.qa import create_compliance_officer_agent
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
    CODE_REVIEWER_BACKSTORY_WITH_EXECUTION,
    CODE_REVIEWER_GOAL,
    CODE_REVIEWER_NAME,
    CODE_REVIEWER_ROLE,
    ReviewMode,
    create_code_reviewer_agent,
)
from .compliance_officer import (
    COMPLIANCE_OFFICER_BACKSTORY,
    COMPLIANCE_OFFICER_GOAL,
    COMPLIANCE_OFFICER_NAME,
    COMPLIANCE_OFFICER_ROLE,
    create_compliance_officer_agent,
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
from .performance_engineer import (
    PERFORMANCE_ENGINEER_BACKSTORY,
    PERFORMANCE_ENGINEER_GOAL,
    PERFORMANCE_ENGINEER_NAME,
    PERFORMANCE_ENGINEER_ROLE,
    create_performance_engineer_agent,
)
from .pytest_author import (
    PYTEST_AUTHOR_BACKSTORY,
    PYTEST_AUTHOR_GOAL,
    PYTEST_AUTHOR_NAME,
    PYTEST_AUTHOR_ROLE,
    create_pytest_author_agent,
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
from .security_auditor import (
    SECURITY_AUDITOR_BACKSTORY,
    SECURITY_AUDITOR_GOAL,
    SECURITY_AUDITOR_NAME,
    SECURITY_AUDITOR_ROLE,
    create_security_auditor_agent,
)

__all__ = [
    # Code Reviewer (정적 분석, PR #25 + #45)
    "CODE_REVIEWER_BACKSTORY",
    "CODE_REVIEWER_BACKSTORY_WITH_EXECUTION",
    "CODE_REVIEWER_GOAL",
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_ROLE",
    "ReviewMode",
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
    # Security Auditor (Phase 7 정적, PR #47)
    "SECURITY_AUDITOR_BACKSTORY",
    "SECURITY_AUDITOR_GOAL",
    "SECURITY_AUDITOR_NAME",
    "SECURITY_AUDITOR_ROLE",
    "create_security_auditor_agent",
    # Performance Engineer (Phase 7 정량, PR #47)
    "PERFORMANCE_ENGINEER_BACKSTORY",
    "PERFORMANCE_ENGINEER_GOAL",
    "PERFORMANCE_ENGINEER_NAME",
    "PERFORMANCE_ENGINEER_ROLE",
    "create_performance_engineer_agent",
    # Pytest Author (workflow 내 테스트 스위트 생성, PR #58)
    "PYTEST_AUTHOR_BACKSTORY",
    "PYTEST_AUTHOR_GOAL",
    "PYTEST_AUTHOR_NAME",
    "PYTEST_AUTHOR_ROLE",
    "create_pytest_author_agent",
    # Compliance Officer (Phase 7 정책, PR #47)
    "COMPLIANCE_OFFICER_BACKSTORY",
    "COMPLIANCE_OFFICER_GOAL",
    "COMPLIANCE_OFFICER_NAME",
    "COMPLIANCE_OFFICER_ROLE",
    "create_compliance_officer_agent",
]
