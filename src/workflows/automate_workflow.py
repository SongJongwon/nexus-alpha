# -*- coding: utf-8 -*-
"""
Nexus Alpha 자동화 워크플로우 (Phase 6 Track B 통합 — 옵션 6.B / PR #70).

`run_automate_workflow(...)` — Phase 6 Track B 5 에이전트 중 *사용자 요청 도메인에
가장 적합한* 1명을 선택해 호출하는 별도 워크플로우. Track A (`analyze_and_implement`)
와 분리 책임으로 *Track A 안정성* 을 보호한다.

5명 도메인 (PR #68 등록):
    - Web Scraping Specialist (Playwright/Selenium)
    - Desktop Automation Specialist (PyWinAuto/PyAutoGUI)
    - API Integration Developer (REST/GraphQL/Webhook)
    - Data Parser Engineer (Excel/PDF/CSV/JSON)
    - DevOps Engineer (Docker/CI/CD)

설계 원칙:
    1. **휴리스틱 도메인 분류 (LLM 무관).** `router.py` 와 같은 패턴. 키워드 기반
       단순 매칭 — 결정론적 + 빠름 + 테스트 용이.
    2. **단일 에이전트 호출 (1차 통합).** 5명 동시 호출 X — 사용자 요청 1건 = 도메인 1개
       가정. 향후 다중 도메인 확장 시 `auto_chain=True` 옵션으로.
    3. **Track A 격리.** automate_workflow 내부 회귀가 analyze_and_implement
       (Calculator.exe 풀체인) 에 영향 미치지 않도록 분리.
    4. **산출 형식은 Track A 와 동일.** `code/` 디렉터리 + `# file: <X>.py`
       헤더 추출 + saved_code_files 반환 — 기존 도구 (build_workflow / qa) 가
       그대로 재사용 가능.

호출 측 사용 예:
    from src.workflows import run_automate_workflow

    result = run_automate_workflow(
        user_request="네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=Path("outputs/"),
    )
    # result.detected_domain == "web_scraping"
    # result.saved_code_files == [Path("outputs/.../code/scrape.py")]
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from crewai import Crew, Process, Task

from src.agents.engineering import (
    create_api_integration_developer_agent,
    create_data_parser_engineer_agent,
    create_desktop_automation_specialist_agent,
    create_devops_engineer_agent,
    create_web_scraping_specialist_agent,
)
from src.monitoring import get_langfuse_client
from src.workflows._common import (
    kickoff_with_converter_rescue,
    retry_short_tasks_in_chain,
    task_output_text as _task_output_text,
)
from src.workflows._schemas import (
    APIIntegrationOutput,
    DataParserOutput,
    DesktopAutomationOutput,
    DevOpsOutput,
    WebScrapingOutput,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 도메인 분류 (휴리스틱 — LLM 무관)
# ---------------------------------------------------------------------------
class AutomationDomain(str, Enum):
    """Track B 자동화 도메인 — 5 에이전트 도메인 + UNKNOWN."""

    WEB_SCRAPING = "web_scraping"
    DESKTOP_AUTOMATION = "desktop_automation"
    API_INTEGRATION = "api_integration"
    DATA_PARSER = "data_parser"
    DEVOPS = "devops"
    UNKNOWN = "unknown"


# 도메인별 가중치 키워드 (PR #80 — 휴리스틱 분류 개선).
#
# 배경 (PR #79 5 도메인 sample 검증에서 발견):
#     "FastAPI Docker 배포 파이프라인" → API_INTEGRATION 으로 오분류.
#     원인: 단순 부분문자열 매칭으로 ``fastapi`` 안의 ``api`` 가 도매로 1점
#     추가 → API: fastapi(1)+api(1)=2 vs DEVOPS: docker(1)=1 → API 승.
#
# PR #80 처방 (3 tier 가중치 + 단어 경계):
#   1. STRONG (weight=3): 도메인 고유 도구·라이브러리·다중 단어 phrase
#      (예: ``fastapi``, ``playwright``, ``dockerfile``, ``배포 자동화``)
#   2. MEDIUM (weight=2): 일반 도구·핵심 명사 (예: ``docker``, ``엑셀``,
#      ``파싱``, ``컨테이너``)
#   3. WEAK (weight=1, **word_boundary=True**): 짧은 모호 영어 토큰 —
#      `\bword\b` 패턴 강제 (예: ``api``, ``pdf``, ``csv``, ``json``,
#      ``url``, ``http`` 등)
#
# 형식: tuple[str, int, bool] = (keyword, weight, word_boundary).
# word_boundary=True 이면 `\bkeyword\b` 매칭 — 한국어/한자 키워드는 항상 False.
_DomainKeyword = tuple[str, int, bool]
_DOMAIN_KEYWORDS: dict[AutomationDomain, tuple[_DomainKeyword, ...]] = {
    AutomationDomain.WEB_SCRAPING: (
        # STRONG (도구·도메인 고유)
        ("크롤링", 3, False), ("스크래핑", 3, False), ("스크래퍼", 3, False),
        # PR #172 — 한국어 동의어 누락 보완 ("크롤러" 누락 → "네이버 쇼핑 크롤러" 분류 실패 사례)
        ("크롤러", 3, False),
        ("스크레이퍼", 3, False), ("스크레이핑", 3, False),
        ("playwright", 3, False), ("selenium", 3, False), ("beautifulsoup", 3, False),
        # MEDIUM
        ("웹사이트", 2, False), ("웹페이지", 2, False), ("수집해", 2, False),
        ("긁어", 2, False),
        # PR #172 — "수집기" / "수집" 동의어 추가
        ("수집기", 2, False),
        ("scrape", 2, False), ("crawl", 2, False),
        # WEAK (짧은 영어 — 단어 경계)
        ("requests", 2, True),
        ("http", 1, True), ("https", 1, True), ("url", 1, True),
    ),
    AutomationDomain.DESKTOP_AUTOMATION: (
        # STRONG
        ("rpa", 3, False), ("키 입력", 3, False), ("마우스", 3, False),
        ("엑셀 자동", 3, False), ("메일 발송", 3, False),
        ("한컴", 3, False), ("한글 자동", 3, False), ("outlook 자동", 3, False),
        ("pyautogui", 3, False), ("pywinauto", 3, False), ("pywin32", 3, False),
        ("comtypes", 3, False), ("keyboard automation", 3, False),
        # MEDIUM
        ("자동화", 2, False), ("윈도우", 2, False),
        # WEAK (짧은 영어 — 단어 경계)
        ("click", 1, True), ("hotkey", 1, True), ("press", 1, True),
        # NOTE: ``type`` 은 너무 일반적 (Python type hint, 데이터 type 등) → 제거
    ),
    AutomationDomain.API_INTEGRATION: (
        # STRONG
        ("api 연동", 3, False), ("웹훅", 3, False), ("오픈 api", 3, False),
        ("엔드포인트", 3, False),
        ("webhook", 3, False), ("rest api", 3, False), ("graphql", 3, False),
        ("oauth", 3, False), ("jwt", 3, False), ("fastapi", 3, False),
        ("stripe", 3, False), ("slack", 3, False), ("shopify", 3, False),
        ("github api", 3, False), ("httpx", 3, False),
        # MEDIUM
        ("외부 서비스", 2, False),
        # WEAK (짧은 영어 — 단어 경계로 ``fastapi`` 안의 ``api`` 부분 매칭 차단)
        ("api", 1, True),
    ),
    AutomationDomain.DATA_PARSER: (
        # STRONG
        ("pdf 파싱", 3, False), ("pdf 추출", 3, False), ("pdf 분석", 3, False),
        ("json 파싱", 3, False),
        ("openpyxl", 3, False), ("pdfplumber", 3, False),
        # MEDIUM
        ("엑셀", 2, False), ("파싱", 2, False), ("스프레드시트", 2, False),
        ("엑셀파일", 2, False),
        ("pandas", 2, False),
        # WEAK (짧은 영어 — 단어 경계)
        ("pdf", 1, True), ("csv", 1, True), ("json", 1, True),
        # 확장자는 점이 단어 경계 역할
        (".xlsx", 1, False), (".xls", 1, False),
    ),
    AutomationDomain.DEVOPS: (
        # STRONG
        ("도커파일", 3, False), ("컨테이너화", 3, False),
        ("배포 자동화", 3, False), ("배포 파이프라인", 3, False),
        ("ci/cd", 3, False),
        ("dockerfile", 3, False), ("docker-compose", 3, False),
        ("github actions", 3, False),
        ("kubernetes", 3, False), ("helm", 3, False), ("terraform", 3, False),
        ("ansible", 3, False), ("multi-stage", 3, False),
        # MEDIUM
        ("도커", 2, False), ("컨테이너", 2, False),
        # WEAK (짧은 영어 — 단어 경계, 가중치 2 — DevOps 핵심 도구이지만 일반어 빈도 높음)
        ("docker", 2, True), ("k8s", 2, True),
    ),
}


def _keyword_matches(text: str, keyword: str, word_boundary: bool) -> bool:
    """주어진 키워드가 ``text`` 에 매칭하는지 검사.

    word_boundary=True 이면 ``\\bkeyword\\b`` 정규식, 아니면 단순 부분문자열.
    text/keyword 모두 호출자가 lower() 한 상태로 들어온다.
    """
    if word_boundary:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def detect_automation_domain(
    user_request: str, *, allow_llm_fallback: bool = True
) -> AutomationDomain:
    """사용자 요청을 받아 가중치 합산이 가장 큰 도메인을 반환한다 (PR #80).

    PR #80 개선:
        - 3 tier 가중치 (STRONG=3 / MEDIUM=2 / WEAK=1)
        - 짧은 모호 영어 키워드 (``api``, ``pdf``, ``csv``, ``json``, ``docker`` 등)
          은 단어 경계 (``\\bword\\b``) 매칭 — ``fastapi`` 안의 ``api`` 부분 매칭 차단
        - 가중치 동률 시 LLM fallback (allow_llm_fallback=True + pytest 미실행 시)
        - 매칭 0건 → UNKNOWN (이전과 동일)

    Args:
        user_request: 사용자의 자연어 요청.
        allow_llm_fallback: 동률 시 LLM 분류 호출 허용 (default True).
            테스트 / 결정론 보장 / 비용 회피 위해 False 강제 가능.

    Returns:
        가장 적합한 ``AutomationDomain``. 매칭 0건 또는 LLM 도 결정 못하면 UNKNOWN.
    """
    text = (user_request or "").strip().lower()
    if not text:
        return AutomationDomain.UNKNOWN
    scores: dict[AutomationDomain, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = 0
        for kw, weight, word_boundary in keywords:
            if _keyword_matches(text, kw, word_boundary):
                score += weight
        scores[domain] = score
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_domain, top_score = sorted_scores[0]
    second_score = sorted_scores[1][1]
    if top_score == 0:
        return AutomationDomain.UNKNOWN
    if top_score > second_score:
        return top_domain
    # 가중치 동률 — LLM fallback (allow_llm_fallback + 비-pytest 환경에만)
    tied_domains = [d for d, s in sorted_scores if s == top_score]
    if allow_llm_fallback:
        llm_choice = _llm_classify_domain(user_request, tied_domains)
        if llm_choice is not None:
            return llm_choice
    return AutomationDomain.UNKNOWN


def _resolve_track_b_domain(
    user_request: str,
    forced_domain: Optional[AutomationDomain] = None,
    *,
    fallback_domain: AutomationDomain = AutomationDomain.WEB_SCRAPING,
) -> AutomationDomain:
    """Track B 도메인 결정 — graceful fallback 포함 (PR #172).

    이전 (PR #172 이전) 의 ``run_automate_workflow`` 진입부는 ``detect_automation_domain``
    가 ``UNKNOWN`` 을 반환하면 ``ValueError`` 를 raise 하는 fail-HARD 분기 → 사용자가
    "네이버 쇼핑 크롤러" 같은 명확히 web_scraping 의도의 요청도 키워드 사전 갭만으로
    *전체 run 중단*. 본 helper 는:

    1. ``forced_domain`` 명시 → 그대로 사용 (휴리스틱 우회)
    2. 휴리스틱 정상 도메인 감지 → 그대로 사용
    3. ``UNKNOWN`` → ``fallback_domain`` (default WEB_SCRAPING) 으로 graceful 진행
       + ``sys.stderr`` 에 진단 메시지 + ``forced_domain`` 안내

    fail-silent 아님 — *진단 정보 surface* (PR #160a vision_unavailable / PR #170
    CodeQASkipped 패턴과 일관성).

    Returns:
        결정된 ``AutomationDomain`` — ``UNKNOWN`` 절대 반환 X (fallback 보장).
    """
    domain = forced_domain or detect_automation_domain(user_request)
    if domain is AutomationDomain.UNKNOWN:
        print(
            f"[Track B] ⚠️  domain 자동 감지 실패 — '{user_request}' 에 매칭된 "
            f"도메인 키워드 없음 (web_scraping / desktop_automation / api_integration / "
            f"data_parser / devops).",
            file=sys.stderr,
        )
        print(
            f"[Track B] ↩️  fallback: {fallback_domain.value} (기본). 다른 도메인 의도 "
            f"였으면 더 구체적인 요청 또는 ``forced_domain=`` 파라미터 사용.",
            file=sys.stderr,
        )
        domain = fallback_domain
    return domain


def _llm_classify_domain(
    user_request: str, tied_domains: list[AutomationDomain]
) -> Optional[AutomationDomain]:
    """가중치 휴리스틱이 동률을 낼 때 LLM 으로 1회 분류 (PR #80).

    pytest 환경에선 None 반환 — FakeProvider 호환 + 테스트 결정론 보장.
    실 LLM 환경에선 ``NexusAlphaLLM`` 으로 short prompt + JSON 응답 강제.

    Args:
        user_request: 원본 자연어 요청.
        tied_domains: 동률을 낸 도메인 후보 목록 (보통 2~3개).

    Returns:
        선택된 ``AutomationDomain`` (UNKNOWN 도 허용) — LLM 호출 실패 또는
        파싱 실패 시 None.
    """
    import sys

    # pytest 환경 — FakeProvider 호환 위해 LLM 우회
    if "pytest" in sys.modules:
        return None

    try:
        from src.llm import NexusAlphaLLM
    except ImportError:
        return None

    candidate_values = ", ".join(d.value for d in tied_domains)
    system = (
        "당신은 자동화 도메인 분류 분석가입니다. 사용자의 자연어 요청을 받아 "
        "주어진 후보 중 가장 적합한 단일 도메인을 선택해 JSON 한 줄로 응답합니다."
    )
    prompt = (
        f"사용자 요청: {user_request}\n\n"
        f"후보 도메인 (휴리스틱 가중치 동률): [{candidate_values}]\n\n"
        "후보 중 가장 적합한 1개를 선택하세요. 분류 기준:\n"
        "- web_scraping: 웹페이지 크롤링·스크래핑\n"
        "- desktop_automation: 데스크톱 앱·OS 자동화 (RPA)\n"
        "- api_integration: 외부 API 호출·webhook 수신\n"
        "- data_parser: 파일 (Excel/PDF/CSV/JSON) 파싱·추출\n"
        "- devops: 컨테이너화·CI/CD·배포 자동화\n\n"
        "응답 형식 (JSON 한 줄, 다른 텍스트 금지):\n"
        '{"domain": "<선택>"}'
    )
    try:
        llm = NexusAlphaLLM()
        response = llm.call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
        )
    except Exception:
        return None

    # JSON 추출 — 첫 ``{...}`` 블록만
    match = re.search(r"\{[^}]*\"domain\"\s*:\s*\"([a-z_]+)\"[^}]*\}", response or "")
    if not match:
        return None
    chosen_value = match.group(1)
    for domain in tied_domains:
        if domain.value == chosen_value:
            return domain
    # 후보 목록에 없는 값 — 부적절 응답
    return None


# ---------------------------------------------------------------------------
# 결과 dataclass
# ---------------------------------------------------------------------------
@dataclass
class AutomateWorkflowResult:
    """`run_automate_workflow` 의 산출물.

    Attributes:
        user_request: 입력 echo.
        detected_domain: 휴리스틱이 감지한 도메인 (UNKNOWN 가능).
        agent_output: 선택된 에이전트 LLM 산출 마크다운.
        saved_dir: 산출 저장 디렉터리 (None 이면 디스크 저장 skip).
        saved_code_files: code/ 추출된 .py 파일 목록.
        pytest_suite: Pytest Author 산출 (PR #81 — enable_qa_loop=True 시).
            devops 도메인 또는 enable_qa_loop=False 시 빈 문자열.
        code_qa_result: code_qa 실행 결과 (PR #81 — enable_qa_loop=True 시).
            None 이면 미실행 (devops / disabled). 호출은 시도됐으나 실패한 경우
            (qa_feedback_loop 미가용 / run_code_qa 예외) 에는 ``CodeQASkipped`` (PR #170)
            를 반환 — duck-type 호환 (``success=False`` + ``summary_line()`` + ``skip_reason``).
            duck-typed: ``success: bool`` + ``summary_line() -> str`` 만 보장.
    """

    user_request: str
    detected_domain: AutomationDomain
    agent_output: str
    saved_dir: Optional[Path] = None
    saved_code_files: list[Path] = field(default_factory=list)
    pytest_suite: str = ""
    code_qa_result: Any = None
    executor_result: Any = None
    """PR #82 — PyInstaller 실 호출 결과 (``ExecuteResult`` 또는 None).
    enable_build=False / devops / outputs_dir=None / entry .py 부재 시 None."""
    update_module_spec: str = ""
    """PR #83 — Update Checker LLM 산출 (``updater.py`` 참조 구현 포함 markdown).
    enable_release=False / devops 시 빈 문자열."""
    publish_result: Any = None
    """PR #83 — gh release create 결과 (``PublishResult`` 또는 None).
    enable_release=False / devops / .exe 부재 / repo_url 부재 시 None."""


# ---------------------------------------------------------------------------
# 도메인 → 에이전트 factory + Task description 매핑
# ---------------------------------------------------------------------------
_DOMAIN_TO_FACTORY = {
    AutomationDomain.WEB_SCRAPING: create_web_scraping_specialist_agent,
    AutomationDomain.DESKTOP_AUTOMATION: create_desktop_automation_specialist_agent,
    AutomationDomain.API_INTEGRATION: create_api_integration_developer_agent,
    AutomationDomain.DATA_PARSER: create_data_parser_engineer_agent,
    AutomationDomain.DEVOPS: create_devops_engineer_agent,
}


# 도메인별 output_pydantic schema 매핑 (PR #78 — Track B 방어선 2).
# Track A 의 ``analyze_and_implement._build_*_task`` 와 같은 패턴: pytest 환경에선
# FakeProvider 호환을 위해 적용 skip → ``_build_track_b_task`` 에서 gating.
_DOMAIN_TO_SCHEMA = {
    AutomationDomain.WEB_SCRAPING: WebScrapingOutput,
    AutomationDomain.DESKTOP_AUTOMATION: DesktopAutomationOutput,
    AutomationDomain.API_INTEGRATION: APIIntegrationOutput,
    AutomationDomain.DATA_PARSER: DataParserOutput,
    AutomationDomain.DEVOPS: DevOpsOutput,
}


# 공용 분량/구조 임계 헤더 — 모든 도메인 description 에 prepend (PR #78).
# 배경: PR #75 sample 검증에서 Web Scraping 41 bytes / API Integration 57 bytes —
# Final Answer 한 줄만 출력 (이슈 4/6 회귀 패턴). Track A PR #59 분량 임계 패턴
# 재사용 + schema 강제 명시.
_TRACK_B_COMMON_PREAMBLE = (
    "## 분량 + 구조 임계 (PR #78 — Track B 방어선 2) 🚨\n"
    "  - 전체 출력 **최소 1200자** — Final Answer 한 줄만 출력하면 task 실패로 간주\n"
    "    (PR #75 sample 검증 회귀 사례: Web Scraping 41 bytes / API Integration "
    "    57 bytes — 5단 본문 누락 → ``code/`` 빈 디렉터리)\n"
    "  - 5단 본문 **모두** 채울 것 — 빈 섹션 / 'TODO' / '생략' 표기 절대 금지\n"
    "  - 코드 블록 fence 마커 (```<lang>\\n...\\n```) 반드시 포함 [PR #64 패턴 재사용] —\n"
    "    fence 누락 시 ``_extract_track_b_code_blocks`` 매치 실패로 산출 추출 X\n"
    "  - 코드 블록 첫 줄 ``# file: <name>`` 헤더 필수 [PR #66 패턴 재사용]\n\n"
    "## output_pydantic 강제\n"
    "본 task 는 schema 로 6개 필드 (summary + 5단 본문) 모두 채워져야 완료됩니다. "
    "누락 시 CrewAI 가 재호출 → 그래도 실패 시 PR #55 capture-before-rescue 로 "
    "raw 보존.\n\n"
)


_DOMAIN_TASK_DESCRIPTION_TEMPLATES: dict[AutomationDomain, str] = {
    AutomationDomain.WEB_SCRAPING: (
        "[사용자 요청]\n{request}\n\n"
        + _TRACK_B_COMMON_PREAMBLE
        + "본 요청을 백스토리에 명시된 5단 구조로 한국어 마크다운 산출물을 작성하세요:\n"
        "  ### 1. 도구 선택 + 근거 (Playwright 1순위 / Selenium fallback / requests 정적)\n"
        "  ### 2. robots.txt + ToS 검토 결과 (차단/허용 경로, 우회 거절)\n"
        "  ### 3. 단독 실행 코드 (```python``` 블록, 첫 줄 `# file: scrape.py`,\n"
        "         `python scrape.py` 만으로 실행 가능, 코드 50줄+)\n"
        "  ### 4. 셀렉터 전략 + flakiness 방지 (data-testid → role → text → CSS 우선순위,\n"
        "         명시적 wait, headless/headed 토글)\n"
        "  ### 5. 작성자 노트 (rate limit 결정 근거, 캡차 발견 시 사용자 액션)\n\n"
        "rate limit (`asyncio.sleep(1.0)` 또는 randomized jitter) 명시 필수. "
        "WebScrapingOutput schema 가 강제됩니다."
    ),
    AutomationDomain.DESKTOP_AUTOMATION: (
        "[사용자 요청]\n{request}\n\n"
        + _TRACK_B_COMMON_PREAMBLE
        + "본 요청을 백스토리에 명시된 5단 구조로 한국어 마크다운 산출물을 작성하세요:\n"
        "  ### 1. 도구 선택 + 근거 (PyWinAuto 1순위 / PyAutoGUI / pywin32 / 조합)\n"
        "  ### 2. 대상 앱 식별 전략 (title regex + class + UIA tree dump)\n"
        "  ### 3. 단독 실행 코드 (```python``` 블록, 첫 줄 `# file: automate.py`,\n"
        "         `python automate.py` 만으로 실행, 코드 50줄+,\n"
        "         **`pyautogui.FAILSAFE = True` 명시 필수**)\n"
        "  ### 4. 실패 처리 + 로그 (timeout 10s 기본, 실패 시 스크린샷, 단계별 logging.INFO)\n"
        "  ### 5. 작성자 노트 (해상도 의존성, 무인 실행 가능 여부, 위험 조작 거절)\n\n"
        "DesktopAutomationOutput schema 가 강제됩니다."
    ),
    AutomationDomain.API_INTEGRATION: (
        "[사용자 요청]\n{request}\n\n"
        + _TRACK_B_COMMON_PREAMBLE
        + "본 요청을 백스토리에 명시된 5단 구조로 한국어 마크다운 산출물을 작성하세요:\n"
        "  ### 1. 도구 선택 + 근거 (httpx 1순위 / gql / FastAPI / requests/Flask legacy)\n"
        "  ### 2. 인증 전략 (OAuth2 refresh rotation / API key / JWT algorithms 명시 /\n"
        "         webhook HMAC, .env 변수 목록)\n"
        "  ### 3. 단독 실행 코드 (```python``` 블록, 첫 줄 `# file: api_client.py`,\n"
        "         코드 50줄+, **secret 은 `os.environ['<KEY>']` — 코드 하드코딩 절대 금지**,\n"
        "         **`timeout=10` 강제 + `@retry` (tenacity) + 응답 Pydantic 모델 검증**)\n"
        "  ### 4. rate limit + pagination 처리 (응답 헤더 파싱, 429 처리, generator 추상화)\n"
        "  ### 5. 작성자 노트 (schema drift 감지, idempotency 위치, secret 회전)\n\n"
        "APIIntegrationOutput schema 가 강제됩니다."
    ),
    AutomationDomain.DATA_PARSER: (
        "[사용자 요청]\n{request}\n\n"
        + _TRACK_B_COMMON_PREAMBLE
        + "본 요청을 백스토리에 명시된 5단 구조로 한국어 마크다운 산출물을 작성하세요:\n"
        "  ### 1. 도구 선택 + 근거 (openpyxl/pandas Excel / pdfplumber/PyMuPDF PDF /\n"
        "         csv+chardet / json+ijson — 입력 형식별)\n"
        "  ### 2. 인코딩 + 한글 처리 전략 (`chardet.detect()` 우선,\n"
        "         **fallback 순서 utf-8 → cp949 → euc-kr 명시 필수**, 한글 컬럼 보존)\n"
        "  ### 3. 단독 실행 코드 (```python``` 블록, 첫 줄 `# file: parser.py`,\n"
        "         코드 50줄+, streaming 모드, row 단위 try/except graceful)\n"
        "  ### 4. 출력 데이터 구조 (DataFrame schema 또는 dataclass 시그니처,\n"
        "         개인정보 마스킹 옵션)\n"
        "  ### 5. 작성자 노트 (메모리 한계, 인코딩 fallback 결과, 깨진 데이터 통계)\n\n"
        "DataParserOutput schema 가 강제됩니다."
    ),
    AutomationDomain.DEVOPS: (
        "[사용자 요청]\n{request}\n\n"
        + _TRACK_B_COMMON_PREAMBLE
        + "본 요청을 백스토리에 명시된 5단 구조로 한국어 마크다운 산출물을 작성하세요:\n"
        "  ### 1. 도구 선택 + 근거 (Dockerfile multi-stage 1순위 + docker-compose +\n"
        "         GitHub Actions + Makefile 어떤 조합)\n"
        "  ### 2. Dockerfile (```dockerfile``` 블록, 첫 줄 `# file: Dockerfile`,\n"
        "         **multi-stage (builder + runtime) + python:3.13-slim base +\n"
        "         non-root user (`useradd -m app && USER app`) 명시 필수**, 30줄+)\n"
        "  ### 3. CI/CD 워크플로 (```yaml``` 블록, 첫 줄 `# file: .github/workflows/ci.yml`,\n"
        "         matrix build (Python 3.11/3.12/3.13) + actions/cache + concurrency +\n"
        "         **`permissions: contents: read` minimal scope 명시**, 30줄+)\n"
        "  ### 4. 보안 + secret 관리 (이미지 baked 절대 금지, GitHub Secrets/BuildKit\n"
        "         `--secret` mount, Trivy 스캔, cosign 서명, action SHA pin)\n"
        "  ### 5. 작성자 노트 (이미지 크기 예상치, 빌드 시간, rollback 절차)\n\n"
        "DevOpsOutput schema 가 강제됩니다."
    ),
}


_DOMAIN_TASK_EXPECTED_OUTPUTS: dict[AutomationDomain, str] = {
    AutomationDomain.WEB_SCRAPING: (
        "5단 한국어 산출물. 마지막 줄 `Final Answer: tool=playwright|selenium|"
        "requests, pages=<N>, rate_limit=<S>s`."
    ),
    AutomationDomain.DESKTOP_AUTOMATION: (
        "5단 한국어 산출물. 마지막 줄 `Final Answer: tool=pywinauto|pyautogui|"
        "pywin32, target=<app>, failsafe=on`."
    ),
    AutomationDomain.API_INTEGRATION: (
        "5단 한국어 산출물. 마지막 줄 `Final Answer: tool=httpx|gql|fastapi, "
        "auth=<oauth2|apikey|jwt|webhook_hmac>, retry=tenacity`."
    ),
    AutomationDomain.DATA_PARSER: (
        "5단 한국어 산출물. 마지막 줄 `Final Answer: format=<excel|pdf|csv|json>, "
        "tool=<X>, encoding=<auto|cp949|utf8>, streaming=<yes|no>`."
    ),
    AutomationDomain.DEVOPS: (
        "5단 한국어 산출물. 마지막 줄 `Final Answer: docker=multi-stage, "
        "ci=github_actions, base=python-slim, security=non-root+trivy`."
    ),
}


# ---------------------------------------------------------------------------
# 산출물 추출 (analyze_and_implement._extract_code_blocks 와 동일 로직 — 분리 격리)
# ---------------------------------------------------------------------------
_PYTHON_FENCE_PATTERN = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
_DOCKERFILE_FENCE_PATTERN = re.compile(r"```dockerfile\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_YAML_FENCE_PATTERN = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _extract_track_b_code_blocks(markdown: str, code_dir: Path) -> list[Path]:
    """Track B 산출물에서 ```python``` / ```dockerfile``` / ```yaml``` 블록 추출.

    각 블록 첫 줄에 `# file: <name>` 헤더 주석 시 해당 이름 사용,
    부재 시 자동 번호 (block01.py 등). Track A 의 ``_extract_code_blocks``
    와 같은 패턴이지만 dockerfile / yaml 도 추가 — DevOps 산출물 호환.
    """
    code_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for pattern, default_ext in (
        (_PYTHON_FENCE_PATTERN, "py"),
        (_DOCKERFILE_FENCE_PATTERN, "dockerfile"),
        (_YAML_FENCE_PATTERN, "yml"),
    ):
        for idx, block in enumerate(pattern.findall(markdown), start=1):
            first_line = block.splitlines()[0] if block.strip() else ""
            name_match = re.match(r"#\s*file:\s*(\S+)", first_line)
            if name_match:
                safe_name = name_match.group(1).replace("/", "__").replace("\\", "__")
                file_path = code_dir / safe_name
            else:
                file_path = code_dir / f"block{idx:02d}.{default_ext}"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(block, encoding="utf-8")
            saved.append(file_path)
    return saved


# ---------------------------------------------------------------------------
# Task 빌더 — output_pydantic 적용 (pytest gating, PR #78)
# ---------------------------------------------------------------------------
def _build_track_b_task(
    domain: AutomationDomain, agent, user_request: str
) -> Task:
    """도메인별 Task 생성 + ``output_pydantic`` 적용 (PR #78 — Track B 방어선 2).

    Track A (``analyze_and_implement._build_pytest_author_task`` 등) 와 같은
    pytest gating 패턴: pytest 환경에선 ``output_pydantic`` 미적용 — FakeProvider
    (autouse fixture) 가 schema 검증 실패 없이 raw 응답 반환 가능. 실 LLM 호출
    경로 (운영 / E2E 검증) 에선 schema 강제 발동.

    Args:
        domain: 결정된 ``AutomationDomain`` (UNKNOWN 제외).
        agent: 해당 도메인 factory 가 생성한 ``Agent`` 인스턴스.
        user_request: 원본 사용자 자연어 요청.

    Returns:
        ``Task`` — description / expected_output / agent / (실 환경) output_pydantic.
    """
    import sys

    description_template = _DOMAIN_TASK_DESCRIPTION_TEMPLATES[domain]
    expected_output = _DOMAIN_TASK_EXPECTED_OUTPUTS[domain]

    kwargs: dict = dict(
        description=description_template.format(request=user_request),
        expected_output=expected_output,
        agent=agent,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = _DOMAIN_TO_SCHEMA[domain]
    return Task(**kwargs)


# ---------------------------------------------------------------------------
# QA 루프 통합 (PR #81) — Pytest Author + code_qa 통합
# Build 통합 (PR #82) — execute_pyinstaller 직접 호출
# ---------------------------------------------------------------------------
# devops 는 산출이 Dockerfile / .yml — Python 테스트·.exe 빌드 부적합 → 둘 다 skip.
_QA_LOOP_SKIP_DOMAINS: frozenset[AutomationDomain] = frozenset({AutomationDomain.DEVOPS})
_BUILD_SKIP_DOMAINS: frozenset[AutomationDomain] = frozenset({AutomationDomain.DEVOPS})
_RELEASE_SKIP_DOMAINS: frozenset[AutomationDomain] = frozenset({AutomationDomain.DEVOPS})

# 도메인 → entry .py 파일명 매핑 (PR #78 schema description 과 일치).
# Track B 4 python 도메인 모두 단일 .py 산출 — entry 결정 결정론적.
_DOMAIN_TO_ENTRY_FILENAME: dict[AutomationDomain, str] = {
    AutomationDomain.WEB_SCRAPING: "scrape.py",
    AutomationDomain.DESKTOP_AUTOMATION: "automate.py",
    AutomationDomain.API_INTEGRATION: "api_client.py",
    AutomationDomain.DATA_PARSER: "parser.py",
}


def _extract_imports_from_track_b_code_block(agent_output: str) -> list[str]:
    """domain 에이전트 산출 마크다운의 첫 ```python``` 블록에서 import 문 추출 (PR #88).

    배경 (PR #87 검증에서 발견):
        scrape.py: ``from playwright.async_api import ...`` (async)
        test_scrape.py: ``_StubPW`` (sync_playwright 가정) → ``sys.modules['playwright']``
        만 stub → ``ModuleNotFoundError: No module named 'playwright.async_api';
        'playwright' is not a package``.

    처방 (방어선 4 패턴 — 결정형 후처리):
        ``code_task`` 산출에서 정규식으로 import 문 추출 → ``pytest_task.description``
        에 명시 → Pytest Author 가 *서브모듈까지 cover* 하는 stub 작성하도록 인지.

    Args:
        agent_output: 도메인 에이전트의 산출 마크다운 (5단 본문 포함).

    Returns:
        ``import X`` / ``from X import Y`` 라인 목록 (첫 ```python``` 블록 한정).
        블록 부재 또는 import 부재 시 빈 리스트.
    """
    if not agent_output:
        return []
    matches = _PYTHON_FENCE_PATTERN.findall(agent_output)
    if not matches:
        return []
    code = matches[0]  # 첫 블록 (entry .py 가정)
    imports: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        # 단순 ``import X``, ``import X as Y``, ``from X import Y``,
        # ``from X.Y import Z`` 모두 매칭. 멀티라인 import (괄호) 는 첫 줄만 캡처.
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
    return imports


def _extract_imported_symbols_from_track_b_code_block(
    agent_output: str,
) -> dict[str, list[str]]:
    """첫 ```python``` 블록의 ``from X import a, b as c, ...`` 라인에서
    *모듈 → 심볼 리스트* 매핑을 추출한다 (PR #100 — 후보 O).

    배경 (PR #99 5-iter 안정성 검증에서 발견된 결정적 결함):
        ITER 2 + 5 가 동일 root cause 로 fail:
        ``ImportError: cannot import name 'expect' from 'playwright.async_api'``.
        PR #88 의 ``_extract_imports_from_track_b_code_block`` 는 import *라인*
        만 추출 → Pytest Author 가 stub 에 어떤 *심볼* 을 enumerate 해야 하는지
        암묵적 추론에 의존 → ``expect`` 등 누락 발생.

    처방 (PR #100 — Same N-failure rule 결정형 후처리 패턴):
        ``from X import a, b, c as d, (e, f, g)`` 모두 파싱 → ``{X: [a, b, c, e, f, g]}``.
        ``_inject_track_b_stub_getattr_directive`` 가 이 매핑을 directive 에
        명시 + ``__getattr__`` fallback 강제 → 심볼 leak 차단.

    파싱 규칙:
        - ``from playwright.async_api import async_playwright, expect``
            → ``{"playwright.async_api": ["async_playwright", "expect"]}``
        - ``from playwright.async_api import async_playwright as ap``
            → ``{"playwright.async_api": ["async_playwright"]}`` (alias 제거)
        - ``from playwright.async_api import (\\n    async_playwright,\\n    expect,\\n)``
            → 괄호 멀티라인 결합 후 동일 매핑
        - ``import X`` (from 없음) → 매핑 미포함 (심볼 enumeration 불필요)

    Returns:
        ``{모듈명: [심볼1, 심볼2, ...]}`` — 같은 모듈 여러 줄이면 합산.
        블록 부재 / from import 부재 시 빈 dict.
    """
    if not agent_output:
        return {}
    matches = _PYTHON_FENCE_PATTERN.findall(agent_output)
    if not matches:
        return {}
    code = matches[0]
    # 멀티라인 괄호 import 결합 — `from X import (\n  a,\n  b,\n)` 는 한 줄 처럼 처리
    flattened = _flatten_multiline_imports(code)

    mapping: dict[str, list[str]] = {}
    pattern = re.compile(
        r"^\s*from\s+([\w\.]+)\s+import\s+(.+?)\s*$", re.MULTILINE
    )
    for module, symbols_blob in pattern.findall(flattened):
        symbols_blob = symbols_blob.strip().lstrip("(").rstrip(")")
        parts = [p.strip() for p in symbols_blob.split(",") if p.strip()]
        symbols: list[str] = []
        for part in parts:
            # `name` 또는 `name as alias` → 원본 name 만 보존
            head = part.split(" as ", 1)[0].strip()
            # 별표 import (``from X import *``) 는 stub 강제 의미 없음 → skip
            if head and head != "*" and head.isidentifier():
                symbols.append(head)
        if symbols:
            mapping.setdefault(module, []).extend(symbols)
    # 중복 제거 (순서 보존)
    for module, syms in mapping.items():
        seen: set[str] = set()
        unique: list[str] = []
        for s in syms:
            if s not in seen:
                unique.append(s)
                seen.add(s)
        mapping[module] = unique
    return mapping


_MULTILINE_FROM_IMPORT_PATTERN = re.compile(
    r"^(\s*from\s+[\w\.]+\s+import\s*)\(([^)]*)\)",
    re.MULTILINE | re.DOTALL,
)


def _flatten_multiline_imports(code: str) -> str:
    """``from X import (\\n  a,\\n  b,\\n)`` 의 줄바꿈을 제거 → 한 줄로 결합.

    pattern 매칭이 한 줄 단위로 작동하도록 사전 변환. 단순 ``import X`` 나
    한 줄 ``from X import a, b`` 는 변경 없음.
    """

    def _join(match: re.Match[str]) -> str:
        head, body = match.group(1), match.group(2)
        flat = " ".join(part.strip() for part in body.splitlines() if part.strip())
        return f"{head}{flat}"

    return _MULTILINE_FROM_IMPORT_PATTERN.sub(_join, code)


def _inject_track_b_import_directive(
    description: str, imports: list[str]
) -> str:
    """pytest_task description 에 entry .py 의 import path 강제 directive 추가 (PR #88).

    ``_inject_track_b_entry_filename_directive`` 다음에 chained 호출 가정.
    빈 imports → 변경 없음 (방어적).
    """
    if not imports:
        return description
    # 최대 12개 — description 폭주 방지 (대부분 entry 파일은 5~10 imports)
    imports_block = "\n".join(f"  - ``{imp}``" for imp in imports[:12])
    if len(imports) > 12:
        imports_block += f"\n  - (... 외 {len(imports) - 12}개)"
    return description + (
        f"\n## entry .py 가 사용하는 import path 강제 (PR #88) 🚨\n"
        f"엔트리 파일은 다음 import 들을 *정확히* 사용합니다:\n"
        f"{imports_block}\n\n"
        f"**테스트의 stub/mock 은 이 import path 들을 정확히 cover** 해야 합니다. "
        f"예: ``from playwright.async_api import async_playwright`` 라면 "
        f"``sys.modules['playwright.async_api'] = <stub_module>`` 으로 *서브모듈* "
        f"까지 등록 필수. ``sys.modules['playwright'] = <stub>`` 만으로는 "
        f"``ModuleNotFoundError: No module named 'playwright.async_api'; "
        f"'playwright' is not a package`` 회귀 사례 (PR #87 검증). "
        f"async API 면 ``pytest.mark.asyncio`` 또는 ``asyncio.run`` 으로 호출.\n"
    )


def _inject_track_b_stub_getattr_directive(
    description: str, symbol_map: dict[str, list[str]]
) -> str:
    """PR #100 — pytest_task description 에 stub 심볼 enumeration +
    ``__getattr__`` fallback 강제 directive 추가.

    배경 (PR #99 5-iter 안정성 검증, 후보 N):
        ITER 2 + 5 가 동일 ``cannot import name 'expect' from 'playwright.async_api'``
        ImportError 로 fail → Pytest Author 가 ``expect`` 등 일부 심볼을 stub 에
        enumerate 하지 않음 (PR #88 directive 가 *심볼 단위* 가 아닌 *라인 단위*
        강제였기 때문).

    처방 (방어선 패턴 *12 차* 재사용):
        - 각 stubbed 모듈의 *심볼 enumeration* 을 description 에 명시
        - 추가 fallback: ``def __getattr__(name): return _StubNoop`` 형태로
          미정의 심볼도 안전 noop 반환 → 심볼 leak 차단
        - 빈 매핑 (``from X import`` 부재) → directive 미추가

    Args:
        description: 이미 ``_inject_track_b_entry_filename_directive`` +
            ``_inject_track_b_import_directive`` 가 chain 으로 적용된 텍스트.
        symbol_map: ``_extract_imported_symbols_from_track_b_code_block`` 산출.

    Returns:
        directive 가 추가된 description. 빈 매핑이면 그대로 반환.
    """
    if not symbol_map:
        return description
    # 모듈별 심볼 enumeration 블록 (최대 8 모듈 / 각 12 심볼)
    lines: list[str] = []
    for module, symbols in list(symbol_map.items())[:8]:
        truncated = symbols[:12]
        overflow = (
            f" (... 외 {len(symbols) - 12}개)" if len(symbols) > 12 else ""
        )
        sym_str = ", ".join(f"``{s}``" for s in truncated)
        lines.append(f"  - ``{module}``: {sym_str}{overflow}")
    if len(symbol_map) > 8:
        lines.append(f"  - (... 외 {len(symbol_map) - 8} 모듈)")
    symbol_block = "\n".join(lines)
    return description + (
        f"\n## stub 심볼 enumeration + ``__getattr__`` fallback 강제 (PR #100) 🚨\n"
        f"각 stubbed 모듈에 다음 심볼들을 *명시 등록* + *fallback* 두 layer 모두 "
        f"갖춰야 합니다 (PR #99 검증에서 ``expect`` 누락 ImportError 반복 사례):\n"
        f"{symbol_block}\n\n"
        f"**필수 패턴**:\n"
        f"  1. 위 심볼들을 ``_sub.<symbol> = <stub_obj>`` 로 *명시 등록*\n"
        f"  2. 추가로 ``__getattr__`` fallback 으로 *미정의 심볼 도 안전 noop* 반환:\n"
        f"     ```python\n"
        f"     class _StubModule(types.ModuleType):\n"
        f"         def __getattr__(self, name):\n"
        f"             if name.startswith('_'):\n"
        f"                 raise AttributeError(name)\n"
        f"             # 미정의 심볼 → 콜러블 + 컨텍스트매니저 + async 호환 noop\n"
        f"             return _UNIVERSAL_NOOP\n"
        f"     ```\n"
        f"  3. 이렇게 두 layer 갖추면 LLM 이 enumerate 누락해도 fallback 이 흡수.\n"
        f"  4. ``_UNIVERSAL_NOOP`` 은 *모든 호출* 을 받는 객체 — 다음 예시 권장:\n"
        f"     ```python\n"
        f"     class _Noop:\n"
        f"         def __call__(self, *a, **k): return self\n"
        f"         def __getattr__(self, name):\n"
        f"             if name.startswith('_'):\n"
        f"                 raise AttributeError(name)\n"
        f"             return self\n"
        f"         async def __aenter__(self): return self\n"
        f"         async def __aexit__(self, *a): return False\n"
        f"         def __enter__(self): return self\n"
        f"         def __exit__(self, *a): return False\n"
        f"         def __await__(self):\n"
        f"             import asyncio\n"
        f"             return asyncio.sleep(0).__await__()\n"
        f"     _UNIVERSAL_NOOP = _Noop()\n"
        f"     ```\n"
        f"이 패턴은 PR #99 의 ITER 2/5 fail (5-iter 60%) 을 결정적으로 차단합니다.\n"
    )


def _inject_track_b_exception_assertion_directive(description: str) -> str:
    """PR #101 — pytest_task description 에 ``test_error_*`` 카테고리의 잘못된
    예외 단정 차단 directive 추가.

    배경 (PR #100 적용 5-iter 검증, 후보 P 의 ITER 3 fail):
        Pytest Author 가 ``pytest.raises((TypeError, AttributeError)): urlparse(None)``
        과 같이 *raise 가정* 으로 단정 → 실제 Python 3.13 의 ``urlparse(None)`` 은
        예외 없이 빈 ``ParseResultBytes`` 반환 → ``Failed: DID NOT RAISE``.
        attempt 1 + attempt 2 모두 동일 가정 재생산 → 단일 iter 내 N-failure rule.

    처방 (방어선 패턴 *13 차* 재사용):
        - stdlib 의 *None / empty / missing* 입력 동작에 대한 *검증된 fact 목록*
          을 directive 본문에 명시
        - ``pytest.raises`` 단정은 *검증된 raise 패턴* 만 사용
        - 불확실하면 *결과 검증* 패턴 (try/except + assert) 권장

    description 길이 +400~600자 — 다른 directive 들과 비슷한 폭. PR #88 + #100 의
    chain 다음에 호출.
    """
    return description + (
        "\n## ``test_error_*`` 예외 단정 보수적 규칙 (PR #101) 🚨\n"
        "**stdlib 함수의 *None / 빈 문자열 / 잘못된 키* 입력은 raise 가 *아닐* "
        "가능성이 높습니다.** ``with pytest.raises(...):`` 단정은 *검증된 raise* "
        "케이스에만 사용하세요.\n\n"
        "### raise 안 함 — ``pytest.raises`` 금지 (결과 반환)\n"
        "  - ``urllib.parse.urlparse(None)`` → ``ParseResultBytes(b'', ...)`` "
        "(PR #100 ITER 3 회귀 사례)\n"
        "  - ``urllib.parse.urlparse('')`` → ``ParseResult('', ...)``\n"
        "  - ``dict.get(missing_key)`` → ``None``\n"
        "  - ``list.__contains__(item)`` → ``False``\n"
        "  - ``os.path.join()`` (인자 0개) → ``''``\n"
        "  - ``str.split('')`` 같은 빈 구분자만 ``ValueError`` (인자 없으면 OK)\n"
        "  - ``re.match(None, ...)`` → ``TypeError`` (참고용 — 이건 raise)\n\n"
        "### 검증된 raise — ``pytest.raises`` 허용\n"
        "  - ``int('abc')`` → ``ValueError``\n"
        "  - ``int(None)`` → ``TypeError``\n"
        "  - ``json.loads(None)`` → ``TypeError``\n"
        "  - ``json.loads('not json')`` → ``json.JSONDecodeError``\n"
        "  - ``max([])`` / ``min([])`` → ``ValueError``\n"
        "  - ``pathlib.Path(None)`` → ``TypeError``\n"
        "  - 존재하지 않는 디렉터리에 파일 쓰기 → ``FileNotFoundError`` / ``OSError``\n"
        "  - 0 나누기 → ``ZeroDivisionError``\n\n"
        "### 불확실 시 보수적 패턴 (결과 + 예외 둘 다 허용)\n"
        "```python\n"
        "def test_error_invalid_input_handles_gracefully():\n"
        "    \"\"\"잘못된 입력은 *명확한 실패 표식* (예외 OR 결정론적 무효 결과) \"\"\"\n"
        "    try:\n"
        "        result = fn(invalid_input)\n"
        "    except (TypeError, ValueError, AttributeError):\n"
        "        return  # 예외 발생도 valid\n"
        "    # 예외 없으면 결과가 명확히 *무효 표식* 이어야 한다\n"
        "    assert result in (None, '', False, [], {}) or \\\\\n"
        "        (hasattr(result, '__len__') and len(result) == 0)\n"
        "```\n\n"
        "**핵심**: ``DID NOT RAISE`` fail 은 *시작부터 차단* — 단정 전에 *위 표* 와 "
        "*공식 문서* 확인. 확신 없는 패턴은 결과 검증 으로 우회.\n"
    )


def _inject_track_b_entry_filename_directive(
    description: str, domain: AutomationDomain
) -> str:
    """PR #86 — pytest_task description 에 entry 파일명 강제 directive 추가.

    배경 (PR #84 Track B 풀체인 E2E 검증에서 발견된 회귀):
        Track A 의 ``_build_pytest_author_task`` description 은 entry 파일명을
        컨텍스트 (code_task) 에서 LLM 이 추론하도록 위임. Track A Calculator
        시나리오는 calculator.py 일관 산출로 안정적이었으나, Track B web_scraping
        E2E 에서 LLM 이 ``scraper`` 로 변형 → ImportError → code_qa /
        functional / robustness 연쇄 fail.

    처방 (방어선 4 패턴 — 결정론적 후처리):
        PR #82 의 ``_DOMAIN_TO_ENTRY_FILENAME`` 을 description 에 직접 주입.
        LLM 자유 영역 차단 — Calculator 외 시나리오에서도 같은 패턴 안정.

    Args:
        description: ``_build_pytest_author_task`` 가 생성한 원본 description.
        domain: 결정된 ``AutomationDomain``.

    Returns:
        directive 추가된 description. 도메인이 ``_DOMAIN_TO_ENTRY_FILENAME``
        에 없으면 (devops 등) 변경 없이 원본 반환.
    """
    expected_entry = _DOMAIN_TO_ENTRY_FILENAME.get(domain)
    if not expected_entry:
        return description
    entry_module = expected_entry.removesuffix(".py")
    return description + (
        f"\n\n## Track B entry 파일명 강제 (PR #86) 🚨\n"
        f"엔트리 파일은 정확히 ``{expected_entry}`` 입니다 — "
        f"``import {entry_module}`` 로 작성하세요. **다른 파일명/모듈명 추론 "
        f"절대 금지**. PR #84 web_scraping E2E 검증에서 LLM 이 ``scraper`` 로 "
        f"변형 → ImportError → QA gate fail 회귀 사례 차단. "
        f"테스트 파일명은 ``test_{entry_module}.py`` 권장.\n"
    )


@dataclass(frozen=True)
class CodeQASkipped:
    """code_qa 호출 자체 실패 — duck-type 호환 sentinel (PR #170).

    ``CodeQAResult`` 의 ``success`` + ``summary_line()`` 만 보장하면 caller (특히
    ``_adapt_automate_to_chain_result`` / 결과 패널) 가 진단 메시지를 표시할 수 있다.
    ``skip_reason`` 은 *왜* 실행되지 못 했는지 (ImportError / 예외 type+msg) 보존.

    PR #160a 의 ``vision_unavailable`` property 패턴과 동일 — *환경 부재 / 실 실패*
    구분을 caller 까지 propagate 해서 fail-silent 차단.
    """

    skip_reason: str
    success: bool = False

    def summary_line(self) -> str:
        return f"[CODE_QA SKIPPED] {self.skip_reason}"


def _run_code_qa_with_skip_reason(saved_dir: Path) -> Any:
    """``run_code_qa`` 호출 + 실패 분기별 진단 정보 보존 (PR #170).

    Returns:
        ``CodeQAResult`` (성공/실패 무관 — ``run_code_qa`` 정상 응답) 또는
        ``CodeQASkipped`` (호출 자체 실패: ImportError / 예외 발생).

    Why:
        2026-05-18 fail-silent 검색 — 이전 분기는 단일 ``None`` 반환 → caller 가
        어느 원인 인지 미보존. *그리고* import 경로 자체가 잘못돼서
        (``src.workflows.qa_feedback_loop`` 에는 ``run_code_qa`` 미정의 — 실 정의 위치는
        ``src.agents.qa.code_qa_executor``) PR #81 이래로 ImportError 분기가 *영원히* hit
        → Track B + enable_qa_loop=True 시 실 code_qa 단 한 번도 실행 안 됨. fail-silent
        가 본 결함을 *마스킹* 한 정확한 사례. 본 helper 는 import 경로 정정 + 진단 보존
        (PR #160a Vision QA + PR #162 결과 패널과 같은 패턴).
    """
    try:
        from src.agents.qa.code_qa_executor import run_code_qa
    except ImportError as exc:
        return CodeQASkipped(
            skip_reason=f"code_qa_executor 미가용 (ImportError: {exc})"
        )
    try:
        return run_code_qa(saved_dir / "code")
    except Exception as exc:  # noqa: BLE001 — 모든 예외 surface (caller 진단용)
        return CodeQASkipped(skip_reason=f"{type(exc).__name__}: {exc}")


def _run_track_b_qa_loop(
    domain: AutomationDomain,
    code_task: Task,
    saved_dir: Path,
    saved_code_files: list[Path],
    *,
    verbose: bool,
) -> tuple[str, Any]:
    """Track B 산출에 대한 QA 루프 (PR #81).

    pytest_author 로 ``test_<entry>.py`` 생성 → 같은 ``code/`` 디렉터리에 저장
    → ``code_qa`` (pytest + ruff) 실행 → 결과 dataclass 반환.

    devops 는 호출자가 미리 차단 (``_QA_LOOP_SKIP_DOMAINS``).

    Args:
        domain: 결정된 도메인 (DEVOPS 제외).
        code_task: 선행 도메인 에이전트 task (CrewAI Task) — pytest_author 의 컨텍스트.
        saved_dir: ``automate_workflow_<ts>/`` 디렉터리.
        saved_code_files: 도메인 task 에서 추출된 코드 파일 목록 (pytest_author
            가 생성한 test_*.py 가 합산됨).
        verbose: CrewAI 중간 로그.

    Returns:
        ``(pytest_suite_text, code_qa_result)``
        - ``pytest_suite_text`` 는 pytest_author 산출 마크다운 (빈 문자열 가능)
        - ``code_qa_result`` 는 ``CodeQAResult`` 등 — duck-typed (success 속성).
          qa_feedback_loop 모듈 미가용 시 None.
    """
    # 지연 import — qa_feedback_loop 미머지 환경 호환
    from src.agents.qa import create_pytest_author_agent
    from src.workflows.analyze_and_implement import _build_pytest_author_task

    pytest_author = create_pytest_author_agent(verbose=verbose)
    pytest_task = _build_pytest_author_task(pytest_author, code_task)
    # PR #86 — Pytest Author entry 파일명 강제 directive 주입 (PR #84 회귀 차단)
    pytest_task.description = _inject_track_b_entry_filename_directive(
        pytest_task.description, domain
    )
    # PR #88 — entry .py 의 import path 강제 directive 주입 (PR #87 회귀 차단)
    code_task_output = _task_output_text(code_task)
    entry_imports = _extract_imports_from_track_b_code_block(code_task_output)
    pytest_task.description = _inject_track_b_import_directive(
        pytest_task.description, entry_imports
    )
    # PR #100 — stub 심볼 enumeration + __getattr__ fallback directive (PR #99 ITER 2/5 차단)
    symbol_map = _extract_imported_symbols_from_track_b_code_block(code_task_output)
    pytest_task.description = _inject_track_b_stub_getattr_directive(
        pytest_task.description, symbol_map
    )
    # PR #101 — test_error_* 카테고리 예외 단정 보수적 규칙 (PR #100 ITER 3 차단)
    pytest_task.description = _inject_track_b_exception_assertion_directive(
        pytest_task.description
    )
    pytest_crew = Crew(
        agents=[pytest_author],
        tasks=[pytest_task],
        process=Process.sequential,
        verbose=verbose,
    )
    kickoff_with_converter_rescue(pytest_crew, [pytest_task])
    retry_short_tasks_in_chain([pytest_task])
    pytest_suite_text = _task_output_text(pytest_task)

    # pytest_author 산출 저장 + code/ 디렉터리에 test_*.py 추출
    (saved_dir / "03_pytest_suite.md").write_text(
        pytest_suite_text, encoding="utf-8"
    )
    test_files = _extract_track_b_code_blocks(pytest_suite_text, saved_dir / "code")
    # saved_code_files 에 신규 test_*.py 합산 (중복 제거)
    seen = {p.resolve() for p in saved_code_files}
    for p in test_files:
        if p.resolve() not in seen:
            saved_code_files.append(p)
            seen.add(p.resolve())

    # code_qa 실행 — PR #170: 실패 분기별 진단 보존 (CodeQASkipped duck-type 반환)
    code_qa_result = _run_code_qa_with_skip_reason(saved_dir)
    return pytest_suite_text, code_qa_result


def _build_track_b_update_checker_task(
    update_agent, app_short_name: str, target_platform: str, repo_url: str
):
    """Track B 전용 Update Checker task — Track A 와 달리 release_task context 없음.

    PR #66 의 deterministic ``UpdateModuleSpecOutput.to_markdown`` (fence + ``# file:
    updater.py`` 헤더 자동) 그대로 활용. 결과는 ``_integrate_update_checker`` 가
    추출 + entry .py 자동 import.
    """
    import sys

    from src.workflows._schemas import UpdateModuleSpecOutput

    update_endpoint = (
        f"https://api.github.com/repos/{repo_url.rstrip('/').split('github.com/')[-1]}"
        "/releases/latest"
        if repo_url and "github.com" in repo_url
        else "TBD — repo_url 미제공"
    )
    kwargs: dict = dict(
        description=(
            "백스토리에 명시된 5단 구조(동작 흐름 / 참조 구현 updater.py / 통합 위치 / "
            "보안 체크리스트 / 작성자 노트)로 한국어 자동 업데이트 모듈 사양을 작성하세요. "
            "**보안 5원칙 (HTTPS / TLS 검증 / 화이트리스트 / SHA256 검증 / 자동 적용 "
            "금지) 모두 준수해야 합니다.**\n\n"
            f"[APP_METADATA]\n"
            f"short_name: {app_short_name}\n\n"
            f"[UPDATE_ENDPOINT]\n{update_endpoint}\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n\n"
            "[SIGNING_AVAILABLE]\nno\n"
        ),
        expected_output=(
            "5단 한국어 자동 업데이트 모듈 사양. 마지막 줄 `Final Answer: updater "
            "module — endpoint=<도메인>, sha256_check=yes, signing_check=no, "
            "check_interval=24h`."
        ),
        agent=update_agent,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = UpdateModuleSpecOutput
    return Task(**kwargs)


def _run_track_b_release(
    domain: AutomationDomain,
    saved_dir: Path,
    saved_code_files: list[Path],
    executor_result: Any,
    *,
    repo_url: str,
    release_tag: str,
    release_title: str,
    publish_as_draft: bool,
    publish_timeout_sec: int,
    target_platform: str,
    verbose: bool,
) -> tuple[str, list[Path], Any]:
    """Track B Release 통합 (PR #83).

    1. Update Checker LLM 호출 → 5단 산출 (``UpdateModuleSpecOutput.to_markdown``
       이 fence + ``# file: updater.py`` 헤더 deterministic 보강 — PR #66 패턴 재사용)
    2. ``_integrate_update_checker`` 호출 → ``code/updater.py`` 추출 + entry .py
       에 자동 import 라인 주입 (PR #66 헬퍼 재사용)
    3. ``executor_result.exe_path`` 가 있고 repo_url + release_tag 가 있으면
       ``execute_gh_release`` 호출 → Draft Release 생성 + .exe 업로드

    Returns:
        ``(update_module_spec, integrated_files, publish_result)``
        - update_module_spec: Update Checker 산출 markdown (빈 문자열 가능)
        - integrated_files: 새 ``updater.py`` + 수정된 entry 파일 목록
        - publish_result: ``PublishResult`` 또는 None
    """
    from src.agents.build_release import create_update_checker_agent
    from src.workflows.analyze_and_implement import _integrate_update_checker

    # 1) Update Checker LLM
    app_short_name = _DOMAIN_TO_ENTRY_FILENAME.get(domain, "app.py").replace(".py", "")
    update_agent = create_update_checker_agent(verbose=verbose)
    update_task = _build_track_b_update_checker_task(
        update_agent, app_short_name, target_platform, repo_url
    )
    update_crew = Crew(
        agents=[update_agent],
        tasks=[update_task],
        process=Process.sequential,
        verbose=verbose,
    )
    kickoff_with_converter_rescue(update_crew, [update_task])
    retry_short_tasks_in_chain([update_task])
    update_module_spec = _task_output_text(update_task)

    # 1a) Update Checker 산출 markdown 저장
    (saved_dir / "05_update_module_spec.md").write_text(
        update_module_spec, encoding="utf-8"
    )

    # 2) Update Checker 통합 — code/updater.py + entry import 주입
    integrated_files: list[Path] = _integrate_update_checker(saved_dir, update_module_spec)
    seen = {p.resolve() for p in saved_code_files}
    for p in integrated_files:
        if p.resolve() not in seen:
            saved_code_files.append(p)
            seen.add(p.resolve())

    # 3) gh release create (executor_result 의 .exe + repo_url + tag 모두 있을 때만)
    publish_result: Any = None
    exe_path = getattr(executor_result, "exe_path", None) if executor_result else None
    can_publish = (
        exe_path is not None
        and getattr(executor_result, "success", False)
        and bool(repo_url)
        and bool(release_tag)
    )
    if can_publish:
        from src.agents.build_release.distribution_executor import execute_gh_release

        publish_result = execute_gh_release(
            repo=repo_url,
            tag=release_tag,
            title=release_title or f"{app_short_name} {release_tag}",
            notes_body=(
                f"# {app_short_name} {release_tag}\n\n"
                f"Track B 자동 산출물 — domain={domain.value}.\n\n"
                f"## 다운로드\n\n"
                f"- `{exe_path.name}` — Track B {domain.value} 산출\n"
            ),
            files_to_upload=[exe_path],
            draft=publish_as_draft,
            timeout_sec=publish_timeout_sec,
        )
        # 06_publish_result.md 저장
        if publish_result is not None:
            (saved_dir / "06_publish_result.md").write_text(
                _format_track_b_publish_result_md(publish_result),
                encoding="utf-8",
            )

    return update_module_spec, integrated_files, publish_result


def _format_track_b_publish_result_md(result: Any) -> str:
    """``PublishResult`` → ``06_publish_result.md`` 형식 markdown."""
    lines = [
        "# Track B GitHub Release 발행 결과 (PR #83)",
        "",
        f"**상태**: {'✅ SUCCESS' if result.success else '🔴 FAILED'}",
        f"**Tag**: `{result.tag}`",
        f"**Draft**: {'yes' if result.is_draft else 'no'}",
        f"**Exit Code**: `{result.exit_code}`",
        f"**Elapsed**: {result.elapsed_sec:.2f}초",
    ]
    if getattr(result, "release_url", None):
        lines.append(f"**Release URL**: {result.release_url}")
    if getattr(result, "download_urls", None):
        lines.append("")
        lines.append("## 다운로드 URL")
        for url in result.download_urls:
            lines.append(f"- {url}")
    if getattr(result, "error_message", None):
        lines.append("")
        lines.append(f"**에러 메시지**: {result.error_message}")
    if getattr(result, "command", None):
        lines.append("")
        lines.append("## 실행 명령")
        lines.append("```")
        lines.append(" ".join(result.command))
        lines.append("```")
    return "\n".join(lines) + "\n"


def _resolve_track_b_entry_path(
    domain: AutomationDomain, saved_code_files: list[Path]
) -> Optional[Path]:
    """도메인 → entry .py 결정 (PR #82).

    우선순위:
        1. 도메인 표준 파일명 (``_DOMAIN_TO_ENTRY_FILENAME``) — schema 의 ``# file:``
           헤더와 일치 (예: web_scraping → ``scrape.py``)
        2. 임의 .py 파일 (test_*.py 제외 — pytest_author 산출 회피)
        3. None — entry 미탐지 시 build skip 신호
    """
    expected = _DOMAIN_TO_ENTRY_FILENAME.get(domain)
    if expected is not None:
        for p in saved_code_files:
            if p.name == expected and p.exists():
                return p
    # fallback — 임의 .py (test_*.py 제외)
    for p in saved_code_files:
        if p.suffix == ".py" and not p.name.startswith("test_") and p.exists():
            return p
    return None


def _format_track_b_executor_result_md(result: Any) -> str:
    """``ExecuteResult`` → ``04_executor_result.md`` 형식 markdown (Track A 25_*.md 와 같은 구조)."""
    lines = [
        "# Track B PyInstaller 실행 결과 (PR #82)",
        "",
        f"**상태**: {'✅ SUCCESS' if result.success else '🔴 FAILED'}",
        f"**Exit Code**: `{result.exit_code}`",
        f"**Elapsed**: {result.elapsed_sec:.2f}초",
    ]
    if getattr(result, "exe_path", None):
        lines.append(f"**산출 파일**: `{result.exe_path}`")
    if getattr(result, "exe_size_bytes", None) is not None:
        lines.append(
            f"**크기**: {result.exe_size_bytes:,} bytes "
            f"({result.exe_size_bytes / (1024 * 1024):.2f} MB)"
        )
    if getattr(result, "sha256", None):
        lines.append(f"**SHA256**: `{result.sha256}`")
    if getattr(result, "error_message", None):
        lines.append("")
        lines.append(f"**에러 메시지**: {result.error_message}")
    if getattr(result, "command", None):
        lines.append("")
        lines.append("## 실행 명령")
        lines.append("```")
        lines.append(" ".join(result.command))
        lines.append("```")
    if getattr(result, "stdout", ""):
        lines.append("")
        lines.append("## stdout (tail)")
        lines.append("```")
        lines.append(result.stdout)
        lines.append("```")
    if getattr(result, "stderr", ""):
        lines.append("")
        lines.append("## stderr (tail)")
        lines.append("```")
        lines.append(result.stderr)
        lines.append("```")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# PR #133 — Track B 도 entry .py 의 import 자동 스캔 → pip install (B안 Track B 적용)
# PR #133 fixup #6 — _scan_imports_from_py 는 build_workflow.py 로 이동 (Track A 도 사용).
# 본 파일은 build_workflow.py 에서 re-export.
# ---------------------------------------------------------------------------
from src.workflows.build_workflow import _scan_imports_from_py  # noqa: F401, E402


def _run_track_b_build(
    domain: AutomationDomain,
    saved_dir: Path,
    saved_code_files: list[Path],
    *,
    timeout_sec: int = 300,
) -> Any:
    """Track B 산출 .py 를 PyInstaller 로 빌드 (PR #82, PR #133 deps 자동 설치 추가).

    Track A 의 5단 LLM 사양 사슬 (run_build_workflow) 은 생략 — Track B 는
    *단일 .py CLI 스크립트* 가정 → 직접 ``execute_pyinstaller()`` 호출이 충분.

    PR #133 — entry .py 의 import 문 AST 스캔 → 외부 패키지 자동 ``pip install``
    → PyInstaller 호출. dependency_report 가 없는 Track B 환경에서도 자연어 →
    동작하는 .exe 풀체인 보장.

    Args:
        domain: 결정된 도메인 (DEVOPS 제외 — 호출자가 미리 차단).
        saved_dir: ``automate_workflow_<ts>/`` 디렉터리 — ``build_output/`` 하위 생성.
        saved_code_files: 추출된 .py 파일 목록 (test_*.py 제외 후 entry 자동 선택).
        timeout_sec: PyInstaller subprocess 타임아웃 (기본 300s = 5분).

    Returns:
        ``ExecuteResult`` (graceful failure 모델 — 예외 propagate 안 함).
        entry 미탐지 시 None.
    """
    from src.agents.build_release.build_executor import ExecuteResult, execute_pyinstaller
    from src.workflows.build_workflow import (
        _install_dependencies_for_build,
        _pre_pyinstaller_validation,
        _resolve_build_deps,
        _validate_module_attributes,
    )

    entry_path = _resolve_track_b_entry_path(domain, saved_code_files)
    if entry_path is None:
        return None

    # PR #133 fixup #8 — Track B 도 AST primary + Mutex + Whitelist (Track A 와 동일 로직)
    # dependency_report 가 없으므로 빈 문자열 전달 (AST 스캔만 작동)
    build_deps = _resolve_build_deps("", entry_path, saved_code_files)
    if build_deps.direct_deps_to_install:
        pip_ok, pip_log = _install_dependencies_for_build(build_deps.direct_deps_to_install)
        if not pip_ok:
            # PyInstaller 호출 중단 — 누락된 의존성이 있으면 .exe 가 런타임 실패할 것
            return ExecuteResult(
                success=False,
                exit_code=-4,
                elapsed_sec=0.0,
                error_message=(
                    f"Track B: 필수 의존성 pip install 실패 — PyInstaller 호출 중단. "
                    f"실패 로그: {pip_log}"
                ),
            )

    # PR #133 fixup #11 — Track B 도 pre-PyInstaller validation
    # 코드 자체 결함 (AttributeError 등) 사전 검출 → 빈 껍데기 .exe 양산 차단
    pre_ok, pre_log = _pre_pyinstaller_validation(entry_path)
    if not pre_ok:
        return ExecuteResult(
            success=False,
            exit_code=-5,
            elapsed_sec=0.0,
            error_message=(
                f"Track B: Pre-PyInstaller validation 실패 — 코드 자체 결함이 있어 "
                f"PyInstaller 호출해도 .exe 가 런타임 실패할 것. build 중단.\n\n{pre_log}"
            ),
        )

    # PR #133 fixup #14 — Track B 도 정적 attribute 검증
    attr_ok, attr_broken = _validate_module_attributes(entry_path, saved_code_files)
    if not attr_ok:
        return ExecuteResult(
            success=False,
            exit_code=-6,
            elapsed_sec=0.0,
            error_message=(
                f"Track B: 정적 attribute 검증 실패 — LLM 코드가 설치된 모듈의 존재하지 "
                f"않는 attribute 를 사용. build 중단.\n"
                f"누락 attribute 체인 ({len(attr_broken)}개):\n  "
                + "\n  ".join(attr_broken[:10])
            ),
        )

    # Track B 4 python 도메인 모두 CLI 스크립트 — windowed=False
    app_name = entry_path.stem.title() or "App"
    return execute_pyinstaller(
        entry_path=entry_path,
        output_dir=saved_dir / "build_output",
        app_name=app_name,
        windowed=False,
        onefile=True,
        # fixup #8 — 화이트리스트의 패키지만 --collect-all
        collect_all=build_deps.collect_all_packages or None,
        # fixup #8 — mutex group 비채택 패키지 차단
        exclude_modules=build_deps.excluded_modules or None,
        timeout_sec=timeout_sec,
    )


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_automate_workflow(
    user_request: str,
    *,
    outputs_dir: Optional[Path] = None,
    forced_domain: Optional[AutomationDomain] = None,
    verbose: bool = False,
    enable_qa_loop: bool = False,
    enable_build: bool = False,
    build_timeout_sec: int = 300,
    enable_release: bool = False,
    repo_url: str = "",
    release_tag: str = "",
    release_title: str = "",
    publish_as_draft: bool = True,
    publish_timeout_sec: int = 120,
    target_platform: str = "windows",
) -> AutomateWorkflowResult:
    """Phase 6 Track B — 사용자 요청 도메인에 적합한 단일 에이전트 호출.

    Args:
        user_request: 사용자의 자연어 요청.
        outputs_dir: 산출 저장 디렉터리. None 이면 디스크 저장 skip.
        forced_domain: 휴리스틱 결과를 무시하고 강제로 사용할 도메인. 테스트·디버그용.
        verbose: CrewAI 중간 로그.
        enable_qa_loop: PR #81 — Pytest Author + code_qa 통합 활성. True 면 도메인
            task 후 ``test_<entry>.py`` 생성 + pytest 실행 + code_qa 결과 반환.
            **devops 도메인 + 디스크 저장 skip (outputs_dir=None) 시 자동 우회**.
            기본 False — backward compat (PR #75/#79 호출 측 변경 불필요).
        enable_build: PR #82 — PyInstaller 실 호출 활성. True 면 도메인 산출 .py 를
            ``execute_pyinstaller`` 로 .exe 빌드 + ``executor_result`` 반환 +
            ``04_executor_result.md`` 저장. **devops + outputs_dir=None + entry 미탐지
            시 자동 우회**. 기본 False — backward compat.
        build_timeout_sec: PyInstaller subprocess 타임아웃 (기본 300s = 5분).
        enable_release: PR #83 — Update Checker LLM + 자동 import 주입 + (조건 충족
            시) ``gh release create`` 호출. True 면 ``code/updater.py`` 추가 + entry
            .py 에 import 라인 자동 삽입 (PR #66 패턴 재사용) + .exe 산출 시 Draft
            Release 발행. **devops + outputs_dir=None + .exe 부재 시 자동 우회**.
        repo_url: PR #83 — gh release create 의 repo (예: ``owner/name`` 또는
            GitHub URL). 빈 문자열이면 publish skip.
        release_tag: PR #83 — release tag (예: ``v0.1.0-track-b``). 빈 문자열이면
            publish skip.
        release_title: PR #83 — release 제목. 빈 문자열이면 도메인 + tag 자동 생성.
        publish_as_draft: PR #83 — Draft 발행 (기본 True — public 노출 안 됨).
        publish_timeout_sec: gh release subprocess 타임아웃 (기본 120s).
        target_platform: Update Checker 입력 — windows / macos / linux (기본 windows).

    Returns:
        ``AutomateWorkflowResult`` — 감지된 도메인 + 에이전트 산출 + 저장 경로 +
        (enable_qa_loop=True 시) pytest_suite + code_qa_result +
        (enable_build=True 시) executor_result.

    Raises:
        (PR #172) 휴리스틱이 ``UNKNOWN`` 을 반환해도 ``ValueError`` 를 raise 하지
        않음 — ``_resolve_track_b_domain`` 이 ``web_scraping`` 으로 graceful fallback +
        ``sys.stderr`` 진단 메시지. 명시적 도메인 강제는 ``forced_domain=`` 사용.

    Note:
        본 함수는 LLM 호출 1~2건 (도메인 task + (옵션) pytest_author task) +
        (옵션) PyInstaller subprocess 1건. Track A 의 5단 LLM 빌드 사양 사슬은
        Track B 에 미적용 — 단일 .py CLI 스크립트 가정으로 직접 호출이 충분.
    """
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="automate_workflow",
        user_id="local-dev",
        metadata={
            "phase": "phase_6_track_b",
            "workflow": "automate_workflow",
            "enable_qa_loop": enable_qa_loop,
            "enable_build": enable_build,
        },
    )

    try:
        # PR #172 — fail-HARD 대신 graceful fallback (helper 가 UNKNOWN 시 web_scraping
        # default + 진단 메시지). 이전 fail-HARD 는 "네이버 쇼핑 크롤러" 처럼 명확한
        # web_scraping 의도의 요청도 키워드 갭만으로 전체 run 중단시키는 결함.
        domain = _resolve_track_b_domain(user_request, forced_domain)

        factory = _DOMAIN_TO_FACTORY[domain]
        agent = factory(verbose=verbose)
        task = _build_track_b_task(domain, agent, user_request)
        crew = Crew(
            agents=[agent], tasks=[task], process=Process.sequential, verbose=verbose
        )
        # 이슈 6 방어선 3 (PR #53) — ConverterError 시 1회 재시도
        kickoff_with_converter_rescue(crew, [task])
        # 이슈 6 방어선 1 (PR #29) — LLM 본문 누락 자동 재시도
        retry_short_tasks_in_chain([task])

        agent_output = _task_output_text(task)

        saved_dir: Optional[Path] = None
        saved_code_files: list[Path] = []
        if outputs_dir is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved_dir = outputs_dir / f"automate_workflow_{timestamp}"
            saved_dir.mkdir(parents=True, exist_ok=True)
            (saved_dir / "00_user_request.txt").write_text(user_request, encoding="utf-8")
            (saved_dir / "01_detected_domain.txt").write_text(domain.value, encoding="utf-8")
            (saved_dir / "02_agent_output.md").write_text(agent_output, encoding="utf-8")
            saved_code_files = _extract_track_b_code_blocks(agent_output, saved_dir / "code")

        # PR #81 — QA 루프 통합 (devops 자동 skip + 디스크 저장 skip 시 우회)
        pytest_suite_text = ""
        code_qa_result: Any = None
        if (
            enable_qa_loop
            and saved_dir is not None
            and domain not in _QA_LOOP_SKIP_DOMAINS
        ):
            pytest_suite_text, code_qa_result = _run_track_b_qa_loop(
                domain,
                task,
                saved_dir,
                saved_code_files,
                verbose=verbose,
            )

        # PR #82 — Build 통합 (PyInstaller, devops 자동 skip + 디스크 저장 skip 시 우회)
        executor_result: Any = None
        if (
            enable_build
            and saved_dir is not None
            and domain not in _BUILD_SKIP_DOMAINS
        ):
            executor_result = _run_track_b_build(
                domain,
                saved_dir,
                saved_code_files,
                timeout_sec=build_timeout_sec,
            )
            if executor_result is not None:
                executor_md = saved_dir / "04_executor_result.md"
                executor_md.write_text(
                    _format_track_b_executor_result_md(executor_result),
                    encoding="utf-8",
                )

        # PR #83 — Release 통합 (Update Checker + integration + (옵션) gh release create)
        update_module_spec = ""
        publish_result: Any = None
        if (
            enable_release
            and saved_dir is not None
            and domain not in _RELEASE_SKIP_DOMAINS
        ):
            update_module_spec, _, publish_result = _run_track_b_release(
                domain,
                saved_dir,
                saved_code_files,
                executor_result,
                repo_url=repo_url,
                release_tag=release_tag,
                release_title=release_title,
                publish_as_draft=publish_as_draft,
                publish_timeout_sec=publish_timeout_sec,
                target_platform=target_platform,
                verbose=verbose,
            )

        return AutomateWorkflowResult(
            user_request=user_request,
            detected_domain=domain,
            agent_output=agent_output,
            saved_dir=saved_dir,
            saved_code_files=saved_code_files,
            pytest_suite=pytest_suite_text,
            code_qa_result=code_qa_result,
            executor_result=executor_result,
            update_module_spec=update_module_spec,
            publish_result=publish_result,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
