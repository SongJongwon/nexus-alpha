# -*- coding: utf-8 -*-
"""Phase 6 Track B 5 에이전트 smoke + factory 테스트 (PR #68).

배경:
    PR #67 까지 본부 3 (개발) 은 Python Engineer 단독 (1/9 = 11%). Phase 6 Track B
    의 5명 동시 추가로 6/9 = 67%. 전체 구현률 34/46 (74%) → 39/46 (85%).

본 PR (#68) 은 *에이전트 클래스만* 등록 — workflow 통합은 별도 PR (옵션 6.B).
따라서 검증 항목은:
    1. 모든 에이전트 메타데이터 (NAME / ROLE / GOAL / BACKSTORY) 비어있지 않음
    2. factory 함수가 인자 없이 호출 가능 (NexusAlphaLLM 자동 주입)
    3. backstory 에 *도메인 핵심 키워드* 포함 (회귀 방지 — backstory 가 다른 곳에서
       복사된 빈 껍데기 아님 확인)
    4. backstory 가 "Final Answer" 우선 패턴 명시 (이슈 4 회귀 방지)
    5. `__init__.py` 가 5 에이전트 모두 export

LLM 호출 없는 정적 검증만 — 풀체인 PASS 검증은 향후 workflow 통합 PR 에서.
"""

from __future__ import annotations

import inspect

from src.agents.engineering import (
    API_INTEGRATION_DEVELOPER_BACKSTORY,
    API_INTEGRATION_DEVELOPER_GOAL,
    API_INTEGRATION_DEVELOPER_NAME,
    API_INTEGRATION_DEVELOPER_ROLE,
    DATA_PARSER_ENGINEER_BACKSTORY,
    DATA_PARSER_ENGINEER_GOAL,
    DATA_PARSER_ENGINEER_NAME,
    DATA_PARSER_ENGINEER_ROLE,
    DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY,
    DESKTOP_AUTOMATION_SPECIALIST_GOAL,
    DESKTOP_AUTOMATION_SPECIALIST_NAME,
    DESKTOP_AUTOMATION_SPECIALIST_ROLE,
    DEVOPS_ENGINEER_BACKSTORY,
    DEVOPS_ENGINEER_GOAL,
    DEVOPS_ENGINEER_NAME,
    DEVOPS_ENGINEER_ROLE,
    WEB_SCRAPING_SPECIALIST_BACKSTORY,
    WEB_SCRAPING_SPECIALIST_GOAL,
    WEB_SCRAPING_SPECIALIST_NAME,
    WEB_SCRAPING_SPECIALIST_ROLE,
    create_api_integration_developer_agent,
    create_data_parser_engineer_agent,
    create_desktop_automation_specialist_agent,
    create_devops_engineer_agent,
    create_web_scraping_specialist_agent,
)


# ---------------------------------------------------------------------------
# 1. 메타데이터 비어있지 않음 + NAME 일관성
# ---------------------------------------------------------------------------


def test_web_scraping_specialist_metadata() -> None:
    assert WEB_SCRAPING_SPECIALIST_NAME == "WebScrapingSpecialist"
    assert WEB_SCRAPING_SPECIALIST_ROLE.startswith("Senior Web Scraping")
    assert WEB_SCRAPING_SPECIALIST_GOAL
    assert WEB_SCRAPING_SPECIALIST_BACKSTORY


def test_desktop_automation_specialist_metadata() -> None:
    assert DESKTOP_AUTOMATION_SPECIALIST_NAME == "DesktopAutomationSpecialist"
    assert DESKTOP_AUTOMATION_SPECIALIST_ROLE.startswith("Senior Desktop Automation")
    assert DESKTOP_AUTOMATION_SPECIALIST_GOAL
    assert DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY


def test_api_integration_developer_metadata() -> None:
    assert API_INTEGRATION_DEVELOPER_NAME == "APIIntegrationDeveloper"
    assert API_INTEGRATION_DEVELOPER_ROLE.startswith("Senior API Integration")
    assert API_INTEGRATION_DEVELOPER_GOAL
    assert API_INTEGRATION_DEVELOPER_BACKSTORY


def test_data_parser_engineer_metadata() -> None:
    assert DATA_PARSER_ENGINEER_NAME == "DataParserEngineer"
    assert DATA_PARSER_ENGINEER_ROLE.startswith("Senior Data Parser")
    assert DATA_PARSER_ENGINEER_GOAL
    assert DATA_PARSER_ENGINEER_BACKSTORY


def test_devops_engineer_metadata() -> None:
    assert DEVOPS_ENGINEER_NAME == "DevOpsEngineer"
    assert DEVOPS_ENGINEER_ROLE.startswith("Senior DevOps Engineer")
    assert DEVOPS_ENGINEER_GOAL
    assert DEVOPS_ENGINEER_BACKSTORY


# ---------------------------------------------------------------------------
# 2. factory 함수 인자 없이 호출 가능 (NexusAlphaLLM 자동 주입)
# ---------------------------------------------------------------------------


def _assert_factory_signature(factory) -> None:
    sig = inspect.signature(factory)
    for name in ("llm", "verbose", "max_iter", "allow_delegation"):
        assert name in sig.parameters
        assert sig.parameters[name].default is not inspect.Parameter.empty


def test_factory_signatures_match_python_engineer_pattern() -> None:
    """5 에이전트 모두 같은 factory 패턴 (llm/verbose/max_iter/allow_delegation 기본값)."""
    for factory in (
        create_web_scraping_specialist_agent,
        create_desktop_automation_specialist_agent,
        create_api_integration_developer_agent,
        create_data_parser_engineer_agent,
        create_devops_engineer_agent,
    ):
        _assert_factory_signature(factory)


def test_web_scraping_factory_creates_agent_with_default_args() -> None:
    agent = create_web_scraping_specialist_agent(verbose=False)
    assert agent.role == WEB_SCRAPING_SPECIALIST_ROLE
    assert agent.goal == WEB_SCRAPING_SPECIALIST_GOAL


def test_desktop_automation_factory_creates_agent_with_default_args() -> None:
    agent = create_desktop_automation_specialist_agent(verbose=False)
    assert agent.role == DESKTOP_AUTOMATION_SPECIALIST_ROLE


def test_api_integration_factory_creates_agent_with_default_args() -> None:
    agent = create_api_integration_developer_agent(verbose=False)
    assert agent.role == API_INTEGRATION_DEVELOPER_ROLE


def test_data_parser_factory_creates_agent_with_default_args() -> None:
    agent = create_data_parser_engineer_agent(verbose=False)
    assert agent.role == DATA_PARSER_ENGINEER_ROLE


def test_devops_factory_creates_agent_with_default_args() -> None:
    agent = create_devops_engineer_agent(verbose=False)
    assert agent.role == DEVOPS_ENGINEER_ROLE


# ---------------------------------------------------------------------------
# 3. backstory 에 도메인 핵심 키워드 포함 (회귀 방지 — 빈 껍데기 아님)
# ---------------------------------------------------------------------------


def test_web_scraping_backstory_mentions_playwright_and_robots_txt() -> None:
    """1순위 도구 + robots.txt 윤리 원칙 명시."""
    assert "Playwright" in WEB_SCRAPING_SPECIALIST_BACKSTORY
    assert "Selenium" in WEB_SCRAPING_SPECIALIST_BACKSTORY
    assert "robots.txt" in WEB_SCRAPING_SPECIALIST_BACKSTORY
    assert "rate limit" in WEB_SCRAPING_SPECIALIST_BACKSTORY.lower()
    # 캡차 우회 거절 명시 (윤리 원칙)
    assert "캡차" in WEB_SCRAPING_SPECIALIST_BACKSTORY


def test_desktop_automation_backstory_mentions_pywinauto_and_failsafe() -> None:
    """1순위 도구 + 안전 원칙 명시."""
    assert "PyWinAuto" in DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY
    assert "PyAutoGUI" in DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY
    assert "failsafe" in DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY.lower() or "FAILSAFE" in DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY
    # 해상도 독립성 (좌표 하드코딩 회피)
    assert "해상도" in DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY


def test_api_integration_backstory_mentions_httpx_and_secret_safety() -> None:
    """1순위 도구 + secret 환경변수 원칙 명시."""
    assert "httpx" in API_INTEGRATION_DEVELOPER_BACKSTORY
    assert "GraphQL" in API_INTEGRATION_DEVELOPER_BACKSTORY
    assert "FastAPI" in API_INTEGRATION_DEVELOPER_BACKSTORY
    # secret 하드코딩 금지
    assert "환경변수" in API_INTEGRATION_DEVELOPER_BACKSTORY
    # webhook 서명 검증
    assert "HMAC" in API_INTEGRATION_DEVELOPER_BACKSTORY or "서명 검증" in API_INTEGRATION_DEVELOPER_BACKSTORY


def test_data_parser_backstory_mentions_korean_encoding() -> None:
    """한국 환경 핵심 — cp949 + 한글 컬럼 보존."""
    assert "openpyxl" in DATA_PARSER_ENGINEER_BACKSTORY
    assert "pdfplumber" in DATA_PARSER_ENGINEER_BACKSTORY
    # 한국 환경 cp949 인코딩
    assert "cp949" in DATA_PARSER_ENGINEER_BACKSTORY
    # 큰 파일 streaming
    assert "streaming" in DATA_PARSER_ENGINEER_BACKSTORY.lower()


def test_devops_backstory_mentions_multistage_and_secret_baked_ban() -> None:
    """multi-stage build + secret baked 금지 + non-root."""
    assert "multi-stage" in DEVOPS_ENGINEER_BACKSTORY
    assert "GitHub Actions" in DEVOPS_ENGINEER_BACKSTORY
    # secret baked 금지
    assert "baked" in DEVOPS_ENGINEER_BACKSTORY
    # non-root user
    assert "non-root" in DEVOPS_ENGINEER_BACKSTORY


# ---------------------------------------------------------------------------
# 4. Final Answer 우선 패턴 (이슈 4 회귀 방지)
# ---------------------------------------------------------------------------


def test_all_track_b_backstories_have_final_answer_pattern() -> None:
    """5 에이전트 모두 backstory 에 'Final Answer' 우선 패턴 명시 — 이슈 4 회귀 방지."""
    backstories = {
        "WebScraping": WEB_SCRAPING_SPECIALIST_BACKSTORY,
        "DesktopAutomation": DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY,
        "APIIntegration": API_INTEGRATION_DEVELOPER_BACKSTORY,
        "DataParser": DATA_PARSER_ENGINEER_BACKSTORY,
        "DevOps": DEVOPS_ENGINEER_BACKSTORY,
    }
    for name, backstory in backstories.items():
        assert "Final Answer" in backstory, f"{name} backstory 에 Final Answer 패턴 누락"
        # 이슈 4 회귀 방지: '본문보다 앞' 또는 '회귀' 키워드 명시
        assert (
            "본문보다" in backstory or "이슈 4" in backstory
        ), f"{name} backstory 에 이슈 4 회귀 방지 신호 누락"


# ---------------------------------------------------------------------------
# 5. 5단 산출 규약 명시 (각 에이전트 도메인 산출물 구조)
# ---------------------------------------------------------------------------


def test_all_track_b_backstories_specify_5_section_output_structure() -> None:
    """5 에이전트 모두 산출 규약 5단 구조 명시 (### 1~5 헤더)."""
    backstories = {
        "WebScraping": WEB_SCRAPING_SPECIALIST_BACKSTORY,
        "DesktopAutomation": DESKTOP_AUTOMATION_SPECIALIST_BACKSTORY,
        "APIIntegration": API_INTEGRATION_DEVELOPER_BACKSTORY,
        "DataParser": DATA_PARSER_ENGINEER_BACKSTORY,
        "DevOps": DEVOPS_ENGINEER_BACKSTORY,
    }
    for name, backstory in backstories.items():
        # 5단 구조 — ### 1. ~ ### 5. 헤더 모두 등장
        for n in range(1, 6):
            assert f"### {n}." in backstory, f"{name} backstory 에 '### {n}.' 섹션 누락"


# ---------------------------------------------------------------------------
# 6. __init__.py 가 5 에이전트 모두 export
# ---------------------------------------------------------------------------


def test_engineering_init_exports_all_track_b_agents() -> None:
    """`from src.agents.engineering import *` 패턴으로 5 factory 모두 import 가능."""
    from src.agents import engineering

    expected_factories = {
        "create_web_scraping_specialist_agent",
        "create_desktop_automation_specialist_agent",
        "create_api_integration_developer_agent",
        "create_data_parser_engineer_agent",
        "create_devops_engineer_agent",
    }
    for factory_name in expected_factories:
        assert hasattr(engineering, factory_name), (
            f"engineering 패키지에 {factory_name} 누락"
        )
        assert factory_name in engineering.__all__, (
            f"engineering.__all__ 에 {factory_name} 누락"
        )


def test_engineering_init_preserves_python_engineer_export() -> None:
    """기존 Python Engineer export 가 백워드 호환 유지 — 회귀 0."""
    from src.agents import engineering

    assert hasattr(engineering, "create_python_engineer_agent")
    assert "create_python_engineer_agent" in engineering.__all__
