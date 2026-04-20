# -*- coding: utf-8 -*-
"""
분석(Analysis) 에이전트 패키지 (업무 분석 본부).

사용 예:
    from src.agents.analysis import (
        create_data_analyst_agent,
        create_gap_analyst_agent,
        create_requirement_expander_agent,
    )

    analyst = create_data_analyst_agent()
    expander = create_requirement_expander_agent()  # v3 (Phase 2.5)
    gap = create_gap_analyst_agent()                # v3 (Phase 2.5)
"""

from .data_analyst import (
    DATA_ANALYST_BACKSTORY,
    DATA_ANALYST_GOAL,
    DATA_ANALYST_NAME,
    DATA_ANALYST_ROLE,
    create_data_analyst_agent,
)
from .gap_analyst import (
    GAP_ANALYST_BACKSTORY,
    GAP_ANALYST_GOAL,
    GAP_ANALYST_NAME,
    GAP_ANALYST_ROLE,
    create_gap_analyst_agent,
)
from .requirement_expander import (
    REQUIREMENT_EXPANDER_BACKSTORY,
    REQUIREMENT_EXPANDER_GOAL,
    REQUIREMENT_EXPANDER_NAME,
    REQUIREMENT_EXPANDER_ROLE,
    create_requirement_expander_agent,
)

__all__ = [
    "DATA_ANALYST_BACKSTORY",
    "DATA_ANALYST_GOAL",
    "DATA_ANALYST_NAME",
    "DATA_ANALYST_ROLE",
    "GAP_ANALYST_BACKSTORY",
    "GAP_ANALYST_GOAL",
    "GAP_ANALYST_NAME",
    "GAP_ANALYST_ROLE",
    "REQUIREMENT_EXPANDER_BACKSTORY",
    "REQUIREMENT_EXPANDER_GOAL",
    "REQUIREMENT_EXPANDER_NAME",
    "REQUIREMENT_EXPANDER_ROLE",
    "create_data_analyst_agent",
    "create_gap_analyst_agent",
    "create_requirement_expander_agent",
]
