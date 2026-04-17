# -*- coding: utf-8 -*-
"""
C-Level (경영 의사결정) 에이전트 패키지.

사용 예:
    from src.agents.c_level import create_cto_agent

    cto = create_cto_agent()
"""

from .cto import (
    CTO_BACKSTORY,
    CTO_GOAL,
    CTO_NAME,
    CTO_ROLE,
    create_cto_agent,
)

__all__ = [
    "CTO_BACKSTORY",
    "CTO_GOAL",
    "CTO_NAME",
    "CTO_ROLE",
    "create_cto_agent",
]
