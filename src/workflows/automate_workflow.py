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

import re
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
        ("playwright", 3, False), ("selenium", 3, False), ("beautifulsoup", 3, False),
        # MEDIUM
        ("웹사이트", 2, False), ("웹페이지", 2, False), ("수집해", 2, False),
        ("긁어", 2, False),
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
            None 이면 미실행 (devops / disabled / qa_feedback_loop 미가용).
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

    # code_qa 실행 — 모듈 미가용 (PR #42 미머지 환경) 시 None 반환
    code_qa_result: Any = None
    try:
        from src.workflows.qa_feedback_loop import run_code_qa  # type: ignore[attr-defined]
    except ImportError:
        return pytest_suite_text, None
    try:
        code_qa_result = run_code_qa(saved_dir / "code")
    except Exception:
        # code_qa 실 실행 자체 실패 — 산출 보존 + None 반환 (silent failure)
        return pytest_suite_text, None

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


def _run_track_b_build(
    domain: AutomationDomain,
    saved_dir: Path,
    saved_code_files: list[Path],
    *,
    timeout_sec: int = 300,
) -> Any:
    """Track B 산출 .py 를 PyInstaller 로 빌드 (PR #82).

    Track A 의 5단 LLM 사양 사슬 (run_build_workflow) 은 생략 — Track B 는
    *단일 .py CLI 스크립트* 가정 → 직접 ``execute_pyinstaller()`` 호출이 충분.

    Args:
        domain: 결정된 도메인 (DEVOPS 제외 — 호출자가 미리 차단).
        saved_dir: ``automate_workflow_<ts>/`` 디렉터리 — ``build_output/`` 하위 생성.
        saved_code_files: 추출된 .py 파일 목록 (test_*.py 제외 후 entry 자동 선택).
        timeout_sec: PyInstaller subprocess 타임아웃 (기본 300s = 5분).

    Returns:
        ``ExecuteResult`` (graceful failure 모델 — 예외 propagate 안 함).
        entry 미탐지 시 None.
    """
    from src.agents.build_release.build_executor import execute_pyinstaller

    entry_path = _resolve_track_b_entry_path(domain, saved_code_files)
    if entry_path is None:
        return None

    # Track B 4 python 도메인 모두 CLI 스크립트 — windowed=False
    app_name = entry_path.stem.title() or "App"
    return execute_pyinstaller(
        entry_path=entry_path,
        output_dir=saved_dir / "build_output",
        app_name=app_name,
        windowed=False,
        onefile=True,
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
        ValueError: 휴리스틱이 UNKNOWN 을 반환했고 ``forced_domain`` 도 None 인 경우.

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
        domain = forced_domain or detect_automation_domain(user_request)
        if domain is AutomationDomain.UNKNOWN:
            raise ValueError(
                "Track B 자동화 도메인을 결정할 수 없습니다 "
                "(web_scraping / desktop_automation / api_integration / data_parser / "
                "devops). 더 구체적인 요청 또는 forced_domain= 파라미터를 명시해 주세요."
            )

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
