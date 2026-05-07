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
from typing import Optional

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


# 도메인별 키워드 (한국어 우선 + 영문 보조). 부분 문자열 매칭 (case-insensitive).
_DOMAIN_KEYWORDS: dict[AutomationDomain, tuple[str, ...]] = {
    AutomationDomain.WEB_SCRAPING: (
        # 한국어
        "크롤링", "스크래핑", "스크래퍼", "웹사이트", "웹페이지", "수집해", "긁어",
        # 영문 도구·동사
        "playwright", "selenium", "beautifulsoup", "requests", "scrape", "crawl",
        # URL 패턴 신호
        "http://", "https://", "url",
    ),
    AutomationDomain.DESKTOP_AUTOMATION: (
        # 한국어
        "자동화", "rpa", "키 입력", "마우스", "윈도우", "엑셀 자동", "메일 발송",
        "한컴", "한글 자동", "outlook 자동",
        # 영문 도구
        "pyautogui", "pywinauto", "pywin32", "comtypes", "keyboard automation",
        # OS 자동화 동사
        "click", "type", "press", "hotkey",
    ),
    AutomationDomain.API_INTEGRATION: (
        # 한국어
        "api 연동", "웹훅", "외부 서비스", "오픈 api", "엔드포인트",
        # 영문
        "api", "webhook", "rest api", "graphql", "oauth", "jwt", "fastapi",
        "stripe", "slack", "shopify", "github api", "httpx", "graphql",
    ),
    AutomationDomain.DATA_PARSER: (
        # 한국어
        "엑셀", "pdf 파싱", "pdf 추출", "pdf 분석", "파싱", "json 파싱",
        # 영문 라이브러리·확장자
        "pdf", "csv", ".xlsx", ".xls", "json", "openpyxl", "pandas", "pdfplumber",
        # 파일 명사
        "스프레드시트", "엑셀파일",
    ),
    AutomationDomain.DEVOPS: (
        # 한국어
        "도커", "도커파일", "컨테이너", "컨테이너화", "배포 자동화", "ci/cd",
        # 영문
        "docker", "dockerfile", "docker-compose", "github actions", "ci/cd",
        "kubernetes", "k8s", "helm", "terraform", "ansible",
    ),
}


def detect_automation_domain(user_request: str) -> AutomationDomain:
    """사용자 요청을 받아 가장 매칭 키워드가 많은 도메인을 반환한다.

    동률 / 매칭 0건 → UNKNOWN. router.py 와 같은 패턴 — LLM 무관, 결정적.

    Args:
        user_request: 사용자의 자연어 요청.

    Returns:
        가장 적합한 ``AutomationDomain``. 모호하면 UNKNOWN.
    """
    text = (user_request or "").strip().lower()
    if not text:
        return AutomationDomain.UNKNOWN
    counts: dict[AutomationDomain, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        counts[domain] = sum(1 for kw in keywords if kw in text)
    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top_domain, top_count = sorted_counts[0]
    second_count = sorted_counts[1][1]
    if top_count == 0:
        return AutomationDomain.UNKNOWN
    if top_count == second_count:
        return AutomationDomain.UNKNOWN  # 동률 — 모호
    return top_domain


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
    """

    user_request: str
    detected_domain: AutomationDomain
    agent_output: str
    saved_dir: Optional[Path] = None
    saved_code_files: list[Path] = field(default_factory=list)


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


_DOMAIN_TASK_DESCRIPTION_TEMPLATES: dict[AutomationDomain, str] = {
    AutomationDomain.WEB_SCRAPING: (
        "[사용자 요청]\n{request}\n\n"
        "본 요청을 백스토리에 명시된 5단 구조 (도구 선택 / robots.txt + ToS / "
        "단독 실행 코드 / 셀렉터 전략 / 작성자 노트) 로 한국어 마크다운 산출물을 "
        "작성하세요. **```python``` 블록 첫 줄에 `# file: scrape.py` 헤더 필수**."
    ),
    AutomationDomain.DESKTOP_AUTOMATION: (
        "[사용자 요청]\n{request}\n\n"
        "본 요청을 백스토리에 명시된 5단 구조 (도구 선택 / 대상 앱 식별 / 단독 "
        "실행 코드 / 실패 처리 / 작성자 노트) 로 한국어 마크다운 산출물을 "
        "작성하세요. **```python``` 블록 첫 줄에 `# file: automate.py` 헤더 필수**, "
        "FAILSAFE 활성화 명시 필수."
    ),
    AutomationDomain.API_INTEGRATION: (
        "[사용자 요청]\n{request}\n\n"
        "본 요청을 백스토리에 명시된 5단 구조 (도구 선택 / 인증 전략 / 단독 "
        "실행 코드 / rate limit + pagination / 작성자 노트) 로 한국어 마크다운 "
        "산출물을 작성하세요. **```python``` 블록 첫 줄에 `# file: api_client.py` "
        "헤더 필수**, secret 환경변수 사용 명시 필수."
    ),
    AutomationDomain.DATA_PARSER: (
        "[사용자 요청]\n{request}\n\n"
        "본 요청을 백스토리에 명시된 5단 구조 (도구 선택 / 인코딩 + 한글 처리 / "
        "단독 실행 코드 / 출력 데이터 구조 / 작성자 노트) 로 한국어 마크다운 "
        "산출물을 작성하세요. **```python``` 블록 첫 줄에 `# file: parser.py` "
        "헤더 필수**, cp949 인코딩 fallback 명시 필수."
    ),
    AutomationDomain.DEVOPS: (
        "[사용자 요청]\n{request}\n\n"
        "본 요청을 백스토리에 명시된 5단 구조 (도구 선택 / Dockerfile / CI/CD "
        "워크플로 / 보안 + secret / 작성자 노트) 로 한국어 마크다운 산출물을 "
        "작성하세요. **```dockerfile``` 블록 첫 줄에 `# file: Dockerfile` 헤더 "
        "필수**, multi-stage + non-root 명시 필수."
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
# 공개 진입점
# ---------------------------------------------------------------------------
def run_automate_workflow(
    user_request: str,
    *,
    outputs_dir: Optional[Path] = None,
    forced_domain: Optional[AutomationDomain] = None,
    verbose: bool = False,
) -> AutomateWorkflowResult:
    """Phase 6 Track B — 사용자 요청 도메인에 적합한 단일 에이전트 호출.

    Args:
        user_request: 사용자의 자연어 요청.
        outputs_dir: 산출 저장 디렉터리. None 이면 디스크 저장 skip.
        forced_domain: 휴리스틱 결과를 무시하고 강제로 사용할 도메인. 테스트·디버그용.
        verbose: CrewAI 중간 로그.

    Returns:
        ``AutomateWorkflowResult`` — 감지된 도메인 + 에이전트 산출 + 저장 경로.

    Raises:
        ValueError: 휴리스틱이 UNKNOWN 을 반환했고 ``forced_domain`` 도 None 인 경우.

    Note:
        본 함수는 LLM 호출 1건 (선택된 에이전트 단독 task). 향후 5 에이전트 chain
        실행이 필요해지면 별도 함수 (``run_automate_chain_workflow``) 추가.
    """
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="automate_workflow",
        user_id="local-dev",
        metadata={"phase": "phase_6_track_b", "workflow": "automate_workflow"},
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
        description_template = _DOMAIN_TASK_DESCRIPTION_TEMPLATES[domain]
        expected_output = _DOMAIN_TASK_EXPECTED_OUTPUTS[domain]

        agent = factory(verbose=verbose)
        task = Task(
            description=description_template.format(request=user_request),
            expected_output=expected_output,
            agent=agent,
        )
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

        return AutomateWorkflowResult(
            user_request=user_request,
            detected_domain=domain,
            agent_output=agent_output,
            saved_dir=saved_dir,
            saved_code_files=saved_code_files,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
