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
from .compliance_officer import (
    COMPLIANCE_OFFICER_BACKSTORY,
    COMPLIANCE_OFFICER_GOAL,
    COMPLIANCE_OFFICER_NAME,
    COMPLIANCE_OFFICER_ROLE,
    create_compliance_officer_agent,
)
from .performance_engineer import (
    PERFORMANCE_ENGINEER_BACKSTORY,
    PERFORMANCE_ENGINEER_GOAL,
    PERFORMANCE_ENGINEER_NAME,
    PERFORMANCE_ENGINEER_ROLE,
    create_performance_engineer_agent,
)
from .security_auditor import (
    SECURITY_AUDITOR_BACKSTORY,
    SECURITY_AUDITOR_GOAL,
    SECURITY_AUDITOR_NAME,
    SECURITY_AUDITOR_ROLE,
    create_security_auditor_agent,
)

__all__ = [
    # Code Reviewer (정적 일반 품질, PR #25)
    "CODE_REVIEWER_BACKSTORY",
    "CODE_REVIEWER_GOAL",
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_ROLE",
    "create_code_reviewer_agent",
    # Security Auditor (PR #47)
    "SECURITY_AUDITOR_BACKSTORY",
    "SECURITY_AUDITOR_GOAL",
    "SECURITY_AUDITOR_NAME",
    "SECURITY_AUDITOR_ROLE",
    "create_security_auditor_agent",
    # Performance Engineer (PR #47)
    "PERFORMANCE_ENGINEER_BACKSTORY",
    "PERFORMANCE_ENGINEER_GOAL",
    "PERFORMANCE_ENGINEER_NAME",
    "PERFORMANCE_ENGINEER_ROLE",
    "create_performance_engineer_agent",
    # Compliance Officer (PR #47)
    "COMPLIANCE_OFFICER_BACKSTORY",
    "COMPLIANCE_OFFICER_GOAL",
    "COMPLIANCE_OFFICER_NAME",
    "COMPLIANCE_OFFICER_ROLE",
    "create_compliance_officer_agent",
]
