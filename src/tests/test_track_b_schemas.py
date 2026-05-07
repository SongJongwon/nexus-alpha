# -*- coding: utf-8 -*-
"""Track B 5 도메인 output_pydantic schema 회귀 방지 테스트 (PR #78).

배경 (PR #75 sample 검증 — 이슈 4/6 회귀):
    Track A 의 방어선 2 (``output_pydantic``) 가 Track B
    (``automate_workflow``) 에 미적용 → 2 도메인 (Web Scraping / API
    Integration) sample 검증에서 Final Answer 한 줄 (41~57바이트) 만 출력 →
    5단 본문 누락 → ``code/`` 빈 디렉터리.

PR #78 처방 (PR #59 패턴 재사용):
    1. 5 도메인 schema (WebScrapingOutput / DesktopAutomationOutput /
       APIIntegrationOutput / DataParserOutput / DevOpsOutput) 도입
    2. fence + ``# file:`` 헤더 자동 보강 (PR #64/#66 헬퍼 일반화)
    3. ``automate_workflow._build_track_b_task`` 에 ``output_pydantic`` 적용
       (pytest gating)
    4. description 분량 임계 1200자 + 5단 본문 강제

본 테스트는 LLM 호출 없는 정적·schema 검증만 — 풀체인 PASS 검증은 5 도메인
sample 재검증 (E2E) 에서.
"""

from __future__ import annotations

import pytest

from src.workflows._schemas import (
    APIIntegrationOutput,
    DataParserOutput,
    DesktopAutomationOutput,
    DevOpsOutput,
    WebScrapingOutput,
    _ensure_fence,
    _ensure_file_header_in_block,
)


# ---------------------------------------------------------------------------
# 1. Generic helper 테스트 — _ensure_fence / _ensure_file_header_in_block
# ---------------------------------------------------------------------------


def test_ensure_fence_wraps_raw_dockerfile() -> None:
    """``dockerfile`` 펜스 없는 raw 코드 → ``` ```dockerfile ... ``` ``` 자동 감싸기."""
    raw = "FROM python:3.13-slim\nCOPY . /app\n"
    out = _ensure_fence(raw, "dockerfile")
    assert "```dockerfile" in out
    assert out.endswith("```")
    assert "FROM python:3.13-slim" in out


def test_ensure_fence_wraps_raw_yaml() -> None:
    """``yaml`` 펜스 없는 raw 본문 → 자동 감싸기."""
    raw = "name: CI\non: [push]\n"
    out = _ensure_fence(raw, "yaml")
    assert "```yaml" in out
    assert out.endswith("```")


def test_ensure_fence_idempotent_for_each_language() -> None:
    """이미 fence 가 있으면 다시 감싸지 않음 (idempotent)."""
    for lang in ("python", "dockerfile", "yaml"):
        wrapped = f"```{lang}\nfoo\n```"
        once = _ensure_fence(wrapped, lang)
        twice = _ensure_fence(once, lang)
        assert once == twice
        assert once.count(f"```{lang}") == 1


def test_ensure_fence_handles_empty_string() -> None:
    """빈 입력은 그대로."""
    assert _ensure_fence("", "python") == ""
    assert _ensure_fence("   ", "yaml") == "   "


def test_ensure_file_header_in_block_inserts_dockerfile_header() -> None:
    """``# file: Dockerfile`` 헤더 자동 삽입."""
    text = "```dockerfile\nFROM python:3.13-slim\nCOPY . /app\n```"
    out = _ensure_file_header_in_block(text, "dockerfile", "Dockerfile")
    assert "# file: Dockerfile\n" in out
    # 원본 본문 보존
    assert "FROM python:3.13-slim" in out


def test_ensure_file_header_in_block_inserts_yaml_header() -> None:
    """``# file: .github/workflows/ci.yml`` 헤더 자동 삽입."""
    text = "```yaml\nname: CI\non: [push]\n```"
    out = _ensure_file_header_in_block(text, "yaml", ".github/workflows/ci.yml")
    assert "# file: .github/workflows/ci.yml\n" in out


def test_ensure_file_header_in_block_idempotent() -> None:
    """이미 헤더가 있으면 두 번 삽입하지 않음."""
    text = "```dockerfile\n# file: Dockerfile\nFROM scratch\n```"
    once = _ensure_file_header_in_block(text, "dockerfile", "Dockerfile")
    twice = _ensure_file_header_in_block(once, "dockerfile", "Dockerfile")
    assert once == twice
    assert once.count("# file: Dockerfile") == 1


def test_ensure_file_header_in_block_no_fence_returns_unchanged() -> None:
    """fence 가 없으면 변형하지 않음."""
    text = "no fence here"
    out = _ensure_file_header_in_block(text, "yaml", "foo.yml")
    assert out == text


# ---------------------------------------------------------------------------
# 2. 5 도메인 schema 필드 정의 검증
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_cls, expected_fields",
    [
        (
            WebScrapingOutput,
            {
                "summary",
                "tool_choice",
                "legal_review",
                "code_block",
                "selector_strategy",
                "author_notes",
            },
        ),
        (
            DesktopAutomationOutput,
            {
                "summary",
                "tool_choice",
                "target_identification",
                "code_block",
                "failure_handling",
                "author_notes",
            },
        ),
        (
            APIIntegrationOutput,
            {
                "summary",
                "tool_choice",
                "auth_strategy",
                "code_block",
                "rate_limit_pagination",
                "author_notes",
            },
        ),
        (
            DataParserOutput,
            {
                "summary",
                "tool_choice",
                "encoding_strategy",
                "code_block",
                "output_structure",
                "author_notes",
            },
        ),
        (
            DevOpsOutput,
            {
                "summary",
                "tool_choice",
                "dockerfile_block",
                "cicd_workflow_block",
                "security_secret",
                "author_notes",
            },
        ),
    ],
)
def test_each_domain_schema_has_exactly_six_fields(
    schema_cls, expected_fields
) -> None:
    """5 도메인 모두 summary + 5단 본문 = 6 필드 정의 (LLM 이 1개라도 누락 시 task 미완료)."""
    actual = set(schema_cls.model_fields.keys())
    assert actual == expected_fields, (
        f"{schema_cls.__name__} 필드 차이: 누락={expected_fields-actual}, "
        f"잉여={actual-expected_fields}"
    )


# ---------------------------------------------------------------------------
# 3. WebScrapingOutput.to_markdown — 5단 + python fence + scrape.py 헤더
# ---------------------------------------------------------------------------


def test_web_scraping_to_markdown_renders_five_sections_and_python_fence() -> None:
    m = WebScrapingOutput(
        summary="tool=playwright, pages=10, rate_limit=1.0s",
        tool_choice="Playwright 1순위. Selenium fallback.",
        legal_review="robots.txt 확인 — Disallow 없음. ToS 확인 완료.",
        code_block=(
            "from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p: ..."
        ),
        selector_strategy="data-testid → role → text → CSS.",
        author_notes="rate limit 1.0s + jitter 0.5s. 캡차 발견 시 사용자 알림.",
    )
    md = m.to_markdown()
    assert "## Web Scraping 산출" in md
    assert "### 1. 도구 선택 + 근거" in md
    assert "### 2. robots.txt + ToS 검토 결과" in md
    assert "### 3. 단독 실행 코드" in md
    assert "### 4. 셀렉터 전략 + flakiness 방지" in md
    assert "### 5. 작성자 노트" in md
    # fence + file header 자동 보강
    assert "```python" in md
    assert "# file: scrape.py" in md


def test_web_scraping_preserves_existing_python_fence_and_header() -> None:
    """LLM 이 이미 fence + header 를 포함했으면 두 번 감싸지 않음."""
    m = WebScrapingOutput(
        summary="x",
        tool_choice="x",
        legal_review="x",
        code_block="```python\n# file: scrape.py\nfrom playwright import x\n```",
        selector_strategy="x",
        author_notes="x",
    )
    md = m.to_markdown()
    assert md.count("```python") == 1
    assert md.count("# file: scrape.py") == 1


# ---------------------------------------------------------------------------
# 4. DesktopAutomationOutput.to_markdown — automate.py 헤더
# ---------------------------------------------------------------------------


def test_desktop_automation_to_markdown_renders_five_sections_and_automate_py() -> None:
    m = DesktopAutomationOutput(
        summary="tool=pywinauto, target=Excel, failsafe=on",
        tool_choice="PyWinAuto 1순위 — UIA 트리 기반 안정성.",
        target_identification="title_re='Excel.*' + class='XLMAIN'.",
        code_block=(
            "import pyautogui\npyautogui.FAILSAFE = True\n"
            "from pywinauto import Application\n"
        ),
        failure_handling="timeout 10s + 실패 시 screenshot.",
        author_notes="해상도 독립 (UIA). 무인 실행 시 종료 조건 명시.",
    )
    md = m.to_markdown()
    assert "## Desktop Automation 산출" in md
    assert "### 2. 대상 앱 식별 전략" in md
    assert "### 4. 실패 처리 + 로그" in md
    assert "```python" in md
    assert "# file: automate.py" in md


# ---------------------------------------------------------------------------
# 5. APIIntegrationOutput.to_markdown — api_client.py 헤더
# ---------------------------------------------------------------------------


def test_api_integration_to_markdown_renders_five_sections_and_api_client_py() -> None:
    m = APIIntegrationOutput(
        summary="tool=httpx, auth=oauth2, retry=tenacity",
        tool_choice="httpx 1순위 — async + type hint.",
        auth_strategy="OAuth2 refresh token rotation. .env: API_KEY, CLIENT_ID.",
        code_block=(
            "import os, httpx\n"
            "from tenacity import retry, stop_after_attempt\n"
            "API_KEY = os.environ['API_KEY']\n"
        ),
        rate_limit_pagination="X-RateLimit-Remaining 헤더 파싱 + 429 backoff.",
        author_notes="schema drift 감지 위치 + idempotency key 적용 위치.",
    )
    md = m.to_markdown()
    assert "## API Integration 산출" in md
    assert "### 2. 인증 전략" in md
    assert "### 4. rate limit + pagination 처리" in md
    assert "```python" in md
    assert "# file: api_client.py" in md


# ---------------------------------------------------------------------------
# 6. DataParserOutput.to_markdown — parser.py 헤더
# ---------------------------------------------------------------------------


def test_data_parser_to_markdown_renders_five_sections_and_parser_py() -> None:
    m = DataParserOutput(
        summary="format=excel, tool=openpyxl, encoding=auto, streaming=yes",
        tool_choice="openpyxl + pandas — Excel 표준.",
        encoding_strategy="chardet 우선, fallback utf-8 → cp949 → euc-kr.",
        code_block=(
            "import openpyxl\n"
            "wb = openpyxl.load_workbook(path, read_only=True)\n"
        ),
        output_structure="DataFrame[매출액(원): float, 날짜: date].",
        author_notes="cp949 fallback 발동률 + 개인정보 마스킹 옵션.",
    )
    md = m.to_markdown()
    assert "## Data Parser 산출" in md
    assert "### 2. 인코딩 + 한글 처리 전략" in md
    assert "### 4. 출력 데이터 구조" in md
    assert "```python" in md
    assert "# file: parser.py" in md


# ---------------------------------------------------------------------------
# 7. DevOpsOutput.to_markdown — Dockerfile + ci.yml 두 블록 모두 헤더
# ---------------------------------------------------------------------------


def test_devops_to_markdown_renders_five_sections_with_dockerfile_and_yaml() -> None:
    m = DevOpsOutput(
        summary="docker=multi-stage, ci=github_actions, base=python-slim, security=non-root+trivy",
        tool_choice="Dockerfile multi-stage + GitHub Actions + Makefile.",
        dockerfile_block=(
            "FROM python:3.13-slim AS builder\n"
            "RUN useradd -m app\n"
            "USER app\n"
            "HEALTHCHECK CMD curl -f http://localhost/health || exit 1\n"
        ),
        cicd_workflow_block=(
            "name: CI\n"
            "on: [push]\n"
            "permissions:\n  contents: read\n"
            "jobs:\n  test:\n    runs-on: ubuntu-latest\n"
        ),
        security_secret="GitHub Secrets + Trivy CVE 스캔 + cosign 서명.",
        author_notes="이미지 크기 ~120MB, 빌드 ~3min, rollback = 이전 tag 재배포.",
    )
    md = m.to_markdown()
    assert "## DevOps 산출" in md
    assert "### 2. Dockerfile" in md
    assert "### 3. CI/CD 워크플로" in md
    assert "### 4. 보안 + secret 관리" in md
    # 두 fence 모두 자동 보강
    assert "```dockerfile" in md
    assert "```yaml" in md
    # 두 file 헤더 모두 자동 삽입
    assert "# file: Dockerfile" in md
    assert "# file: .github/workflows/ci.yml" in md


def test_devops_preserves_existing_fences_and_headers() -> None:
    """LLM 이 이미 fence + header 모두 포함하면 두 번 감싸지 않음 (idempotent)."""
    m = DevOpsOutput(
        summary="x",
        tool_choice="x",
        dockerfile_block=(
            "```dockerfile\n# file: Dockerfile\nFROM scratch\n```"
        ),
        cicd_workflow_block=(
            "```yaml\n# file: .github/workflows/ci.yml\nname: CI\n```"
        ),
        security_secret="x",
        author_notes="x",
    )
    md = m.to_markdown()
    assert md.count("```dockerfile") == 1
    assert md.count("```yaml") == 1
    assert md.count("# file: Dockerfile") == 1
    assert md.count("# file: .github/workflows/ci.yml") == 1


# ---------------------------------------------------------------------------
# 8. _build_track_b_task — pytest gating + schema 매핑
# ---------------------------------------------------------------------------


def test_build_track_b_task_skips_output_pydantic_under_pytest() -> None:
    """pytest 환경 (sys.modules['pytest'] 존재) 에선 output_pydantic 미적용 —
    FakeProvider 호환 (Track A 와 같은 패턴)."""
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _build_track_b_task,
        _DOMAIN_TO_FACTORY,
    )

    agent = _DOMAIN_TO_FACTORY[AutomationDomain.WEB_SCRAPING](verbose=False)
    task = _build_track_b_task(
        AutomationDomain.WEB_SCRAPING, agent, "네이버 쇼핑 크롤링"
    )
    assert task.output_pydantic is None


def test_build_track_b_task_attaches_schema_outside_pytest(monkeypatch) -> None:
    """pytest 모듈 임시 제거 → output_pydantic 이 도메인별 schema 와 매칭."""
    import sys as _sys

    from src.workflows._schemas import WebScrapingOutput
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _build_track_b_task,
        _DOMAIN_TO_FACTORY,
    )

    saved_pytest = _sys.modules.pop("pytest", None)
    try:
        agent = _DOMAIN_TO_FACTORY[AutomationDomain.WEB_SCRAPING](verbose=False)
        task = _build_track_b_task(
            AutomationDomain.WEB_SCRAPING, agent, "네이버 크롤링"
        )
        assert task.output_pydantic is WebScrapingOutput
    finally:
        if saved_pytest is not None:
            _sys.modules["pytest"] = saved_pytest


@pytest.mark.parametrize(
    "domain_attr, schema_cls",
    [
        ("WEB_SCRAPING", WebScrapingOutput),
        ("DESKTOP_AUTOMATION", DesktopAutomationOutput),
        ("API_INTEGRATION", APIIntegrationOutput),
        ("DATA_PARSER", DataParserOutput),
        ("DEVOPS", DevOpsOutput),
    ],
)
def test_domain_to_schema_mapping_complete(domain_attr, schema_cls) -> None:
    """5 도메인 모두 _DOMAIN_TO_SCHEMA 에 등록."""
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _DOMAIN_TO_SCHEMA,
    )

    domain = getattr(AutomationDomain, domain_attr)
    assert _DOMAIN_TO_SCHEMA[domain] is schema_cls


def test_domain_to_schema_does_not_have_unknown() -> None:
    """UNKNOWN 은 schema 매핑에 등록되지 않음 (휴리스틱 단계에서 차단)."""
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _DOMAIN_TO_SCHEMA,
    )

    assert AutomationDomain.UNKNOWN not in _DOMAIN_TO_SCHEMA


# ---------------------------------------------------------------------------
# 9. Description templates — 1200자 임계 + 5단 본문 + schema 명시 (PR #78)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domain_attr, expected_schema_name",
    [
        ("WEB_SCRAPING", "WebScrapingOutput"),
        ("DESKTOP_AUTOMATION", "DesktopAutomationOutput"),
        ("API_INTEGRATION", "APIIntegrationOutput"),
        ("DATA_PARSER", "DataParserOutput"),
        ("DEVOPS", "DevOpsOutput"),
    ],
)
def test_each_description_template_mentions_size_threshold_and_schema(
    domain_attr, expected_schema_name
) -> None:
    """각 도메인 description 에 1200자 임계 + schema 강제 명시 — PR #75 회귀 차단."""
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _DOMAIN_TASK_DESCRIPTION_TEMPLATES,
    )

    domain = getattr(AutomationDomain, domain_attr)
    template = _DOMAIN_TASK_DESCRIPTION_TEMPLATES[domain]
    rendered = template.format(request="dummy")
    # PR #59 패턴 — 분량 임계
    assert "1200자" in rendered, f"{domain_attr}: 1200자 임계 누락"
    # schema 명시
    assert expected_schema_name in rendered, (
        f"{domain_attr}: schema 이름 ({expected_schema_name}) 누락"
    )
    # PR #75 회귀 사례 인용
    assert "PR #75" in rendered or "PR #78" in rendered or "이슈 4/6" in rendered, (
        f"{domain_attr}: 회귀 사례 인용 누락"
    )


def test_devops_description_mentions_both_dockerfile_and_yaml_fences() -> None:
    """DevOps 만 dockerfile + yaml 두 블록 — description 모두 명시."""
    from src.workflows.automate_workflow import (
        AutomationDomain,
        _DOMAIN_TASK_DESCRIPTION_TEMPLATES,
    )

    template = _DOMAIN_TASK_DESCRIPTION_TEMPLATES[AutomationDomain.DEVOPS]
    rendered = template.format(request="dummy")
    assert "```dockerfile" in rendered
    assert "```yaml" in rendered
    assert "# file: Dockerfile" in rendered
    assert "# file: .github/workflows/ci.yml" in rendered
