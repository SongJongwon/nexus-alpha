# -*- coding: utf-8 -*-
"""
엔지니어링(Engineering) 에이전트 패키지 — 본부 3 (개발).

사용 예:
    from src.agents.engineering import create_python_engineer_agent
    from src.agents.engineering import create_web_scraping_specialist_agent
    from src.agents.engineering import create_desktop_automation_specialist_agent
    from src.agents.engineering import create_api_integration_developer_agent
    from src.agents.engineering import create_data_parser_engineer_agent
    from src.agents.engineering import create_devops_engineer_agent

본부 3 구성 (PR #68 기준 6/9 — 67%):
    1. Python Engineer ✅ (PR #23)
    2. Web Scraping Specialist ✅ (PR #68 — Phase 6 Track B)
    3. Desktop Automation Specialist ✅ (PR #68)
    4. API Integration Developer ✅ (PR #68)
    5. Data Parser Engineer ✅ (PR #68)
    6. DevOps Engineer ✅ (PR #68)
    7~9. Gap Analyst / Code Refactoring Specialist / Migration Specialist (미구현)
"""

from .api_integration_developer import (
    API_INTEGRATION_DEVELOPER_BACKSTORY,
    API_INTEGRATION_DEVELOPER_GOAL,
    API_INTEGRATION_DEVELOPER_NAME,
    API_INTEGRATION_DEVELOPER_ROLE,
    create_api_integration_developer_agent,
)
from .data_parser_engineer import (
    DATA_PARSER_ENGINEER_BACKSTORY,
    DATA_PARSER_ENGINEER_GOAL,
    DATA_PARSER_ENGINEER_NAME,
    DATA_PARSER_ENGINEER_ROLE,
    create_data_parser_engineer_agent,
)
from .desktop_automation_specialist import (
    DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY,
    DESKTOP_AUTOMATION_SPECIALIST_GOAL,
    DESKTOP_AUTOMATION_SPECIALIST_NAME,
    DESKTOP_AUTOMATION_SPECIALIST_ROLE,
    create_desktop_automation_specialist_agent,
)
from .devops_engineer import (
    DEVOPS_ENGINEER_BACKSTORY,
    DEVOPS_ENGINEER_GOAL,
    DEVOPS_ENGINEER_NAME,
    DEVOPS_ENGINEER_ROLE,
    create_devops_engineer_agent,
)
from .python_engineer import (
    PYTHON_ENGINEER_BACKSTORY,
    PYTHON_ENGINEER_GOAL,
    PYTHON_ENGINEER_NAME,
    PYTHON_ENGINEER_ROLE,
    create_python_engineer_agent,
)
from .web_scraping_specialist import (
    WEB_SCRAPING_SPECIALIST_BACKSTORY,
    WEB_SCRAPING_SPECIALIST_GOAL,
    WEB_SCRAPING_SPECIALIST_NAME,
    WEB_SCRAPING_SPECIALIST_ROLE,
    create_web_scraping_specialist_agent,
)

__all__ = [
    # Python Engineer (PR #23)
    "PYTHON_ENGINEER_BACKSTORY",
    "PYTHON_ENGINEER_GOAL",
    "PYTHON_ENGINEER_NAME",
    "PYTHON_ENGINEER_ROLE",
    "create_python_engineer_agent",
    # Web Scraping Specialist (PR #68 — Phase 6 Track B)
    "WEB_SCRAPING_SPECIALIST_BACKSTORY",
    "WEB_SCRAPING_SPECIALIST_GOAL",
    "WEB_SCRAPING_SPECIALIST_NAME",
    "WEB_SCRAPING_SPECIALIST_ROLE",
    "create_web_scraping_specialist_agent",
    # Desktop Automation Specialist (PR #68)
    "DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY",
    "DESKTOP_AUTOMATION_SPECIALIST_GOAL",
    "DESKTOP_AUTOMATION_SPECIALIST_NAME",
    "DESKTOP_AUTOMATION_SPECIALIST_ROLE",
    "create_desktop_automation_specialist_agent",
    # API Integration Developer (PR #68)
    "API_INTEGRATION_DEVELOPER_BACKSTORY",
    "API_INTEGRATION_DEVELOPER_GOAL",
    "API_INTEGRATION_DEVELOPER_NAME",
    "API_INTEGRATION_DEVELOPER_ROLE",
    "create_api_integration_developer_agent",
    # Data Parser Engineer (PR #68)
    "DATA_PARSER_ENGINEER_BACKSTORY",
    "DATA_PARSER_ENGINEER_GOAL",
    "DATA_PARSER_ENGINEER_NAME",
    "DATA_PARSER_ENGINEER_ROLE",
    "create_data_parser_engineer_agent",
    # DevOps Engineer (PR #68)
    "DEVOPS_ENGINEER_BACKSTORY",
    "DEVOPS_ENGINEER_GOAL",
    "DEVOPS_ENGINEER_NAME",
    "DEVOPS_ENGINEER_ROLE",
    "create_devops_engineer_agent",
]
