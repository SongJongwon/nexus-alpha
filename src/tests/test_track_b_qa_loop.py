# -*- coding: utf-8 -*-
"""Track B + QA 피드백 루프 통합 회귀 방지 테스트 (PR #81).

배경:
    PR #70 Track B 워크플로 + PR #78 방어선 2 + PR #79 5/5 sample PASS +
    PR #80 휴리스틱 개선 까지 도달. 그러나 Track B 는 단일 에이전트 호출만
    — Track A 의 QA 피드백 루프 (pytest_author + code_qa) 미동반.

PR #81 처방:
    1. ``run_automate_workflow(..., enable_qa_loop=True)`` 추가 (default False —
       backward compat)
    2. devops 자동 skip (산출이 Dockerfile/yml — Python 테스트 부적합)
    3. ``AutomateWorkflowResult.pytest_suite`` + ``code_qa_result`` 필드 추가
    4. ``analyze_and_implement.run_analyze_and_implement(...,
       enable_automate_qa_loop=True)`` plumbing

본 테스트는 LLM 호출 없는 정적·구조 검증만 (FakeProvider 호환). 풀체인 PASS
검증은 PR #81 머지 후 E2E 에서.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.workflows.automate_workflow import (
    AutomateWorkflowResult,
    AutomationDomain,
    _DOMAIN_TO_ENTRY_FILENAME,
    _QA_LOOP_SKIP_DOMAINS,
    _extract_imported_symbols_from_track_b_code_block,
    _extract_imports_from_track_b_code_block,
    _inject_track_b_entry_filename_directive,
    _inject_track_b_import_directive,
    _inject_track_b_stub_getattr_directive,
    run_automate_workflow,
)


# ---------------------------------------------------------------------------
# 1. 시그니처 + backward compat
# ---------------------------------------------------------------------------


def test_run_automate_workflow_has_enable_qa_loop_param_default_false() -> None:
    """``enable_qa_loop`` 파라미터 추가 + default False (backward compat)."""
    sig = inspect.signature(run_automate_workflow)
    assert "enable_qa_loop" in sig.parameters
    assert sig.parameters["enable_qa_loop"].default is False


def test_automate_workflow_result_has_pytest_suite_field_default_empty() -> None:
    """``AutomateWorkflowResult.pytest_suite`` 추가 + default 빈 문자열."""
    fields = AutomateWorkflowResult.__dataclass_fields__
    assert "pytest_suite" in fields
    assert fields["pytest_suite"].default == ""


def test_automate_workflow_result_has_code_qa_result_field_default_none() -> None:
    """``AutomateWorkflowResult.code_qa_result`` 추가 + default None."""
    fields = AutomateWorkflowResult.__dataclass_fields__
    assert "code_qa_result" in fields
    assert fields["code_qa_result"].default is None


def test_automate_workflow_result_can_be_constructed_without_new_fields() -> None:
    """기존 호출자는 새 필드 없이 생성 가능 (backward compat)."""
    result = AutomateWorkflowResult(
        user_request="x",
        detected_domain=AutomationDomain.WEB_SCRAPING,
        agent_output="x",
    )
    assert result.pytest_suite == ""
    assert result.code_qa_result is None


# ---------------------------------------------------------------------------
# 2. enable_qa_loop=False (default) — backward compat (PR #70 동작 유지)
# ---------------------------------------------------------------------------


def test_qa_loop_disabled_default_skips_pytest_author(tmp_path: Path) -> None:
    """default enable_qa_loop=False → pytest_author 미실행 + 03_pytest_suite.md 미생성."""
    result = run_automate_workflow(
        "엑셀 파일에서 데이터 추출",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
    )
    assert result.pytest_suite == ""
    assert result.code_qa_result is None
    assert result.saved_dir is not None
    assert not (result.saved_dir / "03_pytest_suite.md").exists()


# ---------------------------------------------------------------------------
# 3. enable_qa_loop=True — Python 도메인 (4종)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domain",
    [
        AutomationDomain.WEB_SCRAPING,
        AutomationDomain.DESKTOP_AUTOMATION,
        AutomationDomain.API_INTEGRATION,
        AutomationDomain.DATA_PARSER,
    ],
)
def test_qa_loop_enabled_runs_pytest_author_for_python_domains(
    domain, tmp_path: Path
) -> None:
    """4 Python 도메인 모두 enable_qa_loop=True 시 pytest_author 실행 + 03_*.md 저장."""
    request_map = {
        AutomationDomain.WEB_SCRAPING: "네이버 쇼핑 가격 크롤링",
        AutomationDomain.DESKTOP_AUTOMATION: "엑셀 자동 입력 RPA",
        AutomationDomain.API_INTEGRATION: "GitHub API 이슈 생성",
        AutomationDomain.DATA_PARSER: "한글 Excel 파싱",
    }
    result = run_automate_workflow(
        request_map[domain],
        outputs_dir=tmp_path,
        forced_domain=domain,
        verbose=False,
        enable_qa_loop=True,
    )
    assert result.detected_domain is domain
    # FakeProvider 가 텍스트 산출 → pytest_suite 비어있지 않음
    assert result.pytest_suite, f"{domain.value}: pytest_suite 비어있음"
    assert result.saved_dir is not None
    # 03_pytest_suite.md 가 디스크에 저장됨
    pytest_md = result.saved_dir / "03_pytest_suite.md"
    assert pytest_md.exists(), f"{domain.value}: 03_pytest_suite.md 미생성"
    assert pytest_md.read_text(encoding="utf-8") == result.pytest_suite


# ---------------------------------------------------------------------------
# 4. devops — QA 루프 자동 skip
# ---------------------------------------------------------------------------


def test_qa_loop_skipped_for_devops_domain(tmp_path: Path) -> None:
    """devops 도메인 + enable_qa_loop=True → QA 루프 자동 skip (Dockerfile/yml 산출)."""
    result = run_automate_workflow(
        "Docker multi-stage Dockerfile GitHub Actions 작성",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DEVOPS,
        verbose=False,
        enable_qa_loop=True,
    )
    assert result.detected_domain is AutomationDomain.DEVOPS
    # devops 는 QA 루프 미실행
    assert result.pytest_suite == ""
    assert result.code_qa_result is None
    assert result.saved_dir is not None
    assert not (result.saved_dir / "03_pytest_suite.md").exists()


def test_qa_loop_skip_domains_constant_includes_devops() -> None:
    """``_QA_LOOP_SKIP_DOMAINS`` 가 DEVOPS 포함 + 다른 도메인 제외."""
    assert AutomationDomain.DEVOPS in _QA_LOOP_SKIP_DOMAINS
    assert AutomationDomain.WEB_SCRAPING not in _QA_LOOP_SKIP_DOMAINS
    assert AutomationDomain.DESKTOP_AUTOMATION not in _QA_LOOP_SKIP_DOMAINS
    assert AutomationDomain.API_INTEGRATION not in _QA_LOOP_SKIP_DOMAINS
    assert AutomationDomain.DATA_PARSER not in _QA_LOOP_SKIP_DOMAINS


# ---------------------------------------------------------------------------
# 5. enable_qa_loop=True 가 outputs_dir=None 시 자동 우회 (디스크 저장 skip)
# ---------------------------------------------------------------------------


def test_qa_loop_skipped_when_outputs_dir_none() -> None:
    """``outputs_dir=None`` (디스크 저장 skip) 시 enable_qa_loop=True 라도 QA 루프 우회."""
    result = run_automate_workflow(
        "엑셀 파일에서 데이터 추출",
        outputs_dir=None,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
        enable_qa_loop=True,
    )
    # saved_dir=None 이면 03_*.md 저장할 곳 없음 → QA 루프 자동 skip
    assert result.saved_dir is None
    assert result.pytest_suite == ""
    assert result.code_qa_result is None


# ---------------------------------------------------------------------------
# 6. analyze_and_implement plumbing (enable_automate_qa_loop)
# ---------------------------------------------------------------------------


def test_analyze_and_implement_has_enable_automate_qa_loop_param() -> None:
    """``run_analyze_and_implement`` 에 ``enable_automate_qa_loop`` 파라미터 추가 (default False)."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    sig = inspect.signature(run_analyze_and_implement)
    assert "enable_automate_qa_loop" in sig.parameters
    assert sig.parameters["enable_automate_qa_loop"].default is False


def test_analyze_and_implement_passes_qa_loop_flag_to_track_b(
    tmp_path: Path,
) -> None:
    """``enable_automate_qa_loop=True`` 가 Track B 까지 전달 → pytest_suite 채워짐."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    result = run_analyze_and_implement(
        "Docker multi-stage Dockerfile + docker-compose + GitHub Actions 작성해줘",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_qa_loop=True,
    )
    # devops 분류 → chosen_path automate_devops + QA 루프 skip
    assert result.chosen_path == "automate_devops"


def test_analyze_and_implement_qa_loop_runs_for_python_domain(
    tmp_path: Path,
) -> None:
    """Python 도메인 + enable_automate_qa_loop=True → 03_pytest_suite.md 저장 검증."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    result = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_qa_loop=True,
    )
    assert result.chosen_path == "automate_web_scraping"
    assert result.saved_dir is not None
    assert (result.saved_dir / "03_pytest_suite.md").exists()


# ---------------------------------------------------------------------------
# PR #86 — Pytest Author entry 파일명 강제 (PR #84 회귀 차단)
#
# 배경: PR #84 Track B 풀체인 E2E 검증에서 LLM 이 'scraper' 로 변형 →
# ImportError → code_qa / functional / robustness 연쇄 fail 발견. 처방:
# PR #82 의 _DOMAIN_TO_ENTRY_FILENAME 을 pytest_task description 에 직접 주입.
# ---------------------------------------------------------------------------


def test_inject_directive_adds_section_header_and_module_name() -> None:
    """directive 가 ``Track B entry 파일명 강제 (PR #86)`` + ``import <module>`` 포함."""
    original = "## 분량 임계\n전체 출력 최소 1200자.\n"
    result = _inject_track_b_entry_filename_directive(
        original, AutomationDomain.WEB_SCRAPING
    )
    # directive 마커 + import 모듈명 포함
    assert "Track B entry 파일명 강제 (PR #86)" in result
    assert "scrape.py" in result  # 도메인별 파일명
    assert "import scrape" in result  # 모듈명 (확장자 제거)
    assert "test_scrape.py" in result  # 테스트 파일명 권장
    # 원본 description 보존 (append 방식)
    assert result.startswith(original)


@pytest.mark.parametrize(
    "domain, expected_module, expected_filename",
    [
        (AutomationDomain.WEB_SCRAPING, "scrape", "scrape.py"),
        (AutomationDomain.DESKTOP_AUTOMATION, "automate", "automate.py"),
        (AutomationDomain.API_INTEGRATION, "api_client", "api_client.py"),
        (AutomationDomain.DATA_PARSER, "parser", "parser.py"),
    ],
)
def test_inject_directive_for_4_python_domains(
    domain, expected_module, expected_filename
) -> None:
    """4 Python 도메인 모두 도메인별 정확한 파일명 + 모듈명 주입."""
    result = _inject_track_b_entry_filename_directive("BASE\n", domain)
    assert f"``{expected_filename}``" in result
    assert f"import {expected_module}" in result
    assert f"test_{expected_module}.py" in result


def test_inject_directive_skip_for_devops() -> None:
    """devops 는 _DOMAIN_TO_ENTRY_FILENAME 에 없음 → 원본 description 그대로 (변경 없음)."""
    original = "BASE description\n"
    result = _inject_track_b_entry_filename_directive(
        original, AutomationDomain.DEVOPS
    )
    assert result == original  # 변경 없음
    assert "PR #86" not in result


def test_inject_directive_handles_unknown_domain() -> None:
    """UNKNOWN 도메인 (방어적) — 원본 그대로."""
    original = "BASE\n"
    result = _inject_track_b_entry_filename_directive(
        original, AutomationDomain.UNKNOWN
    )
    assert result == original


def test_inject_directive_mentions_pr84_regression_for_traceability() -> None:
    """directive 본문에 PR #84 회귀 사례 명시 — 회귀 추적성 확보."""
    result = _inject_track_b_entry_filename_directive(
        "BASE\n", AutomationDomain.WEB_SCRAPING
    )
    assert "PR #84" in result
    assert "scraper" in result  # 회귀 변형 사례 명시
    assert "ImportError" in result


def test_inject_directive_is_deterministic_and_no_side_effects() -> None:
    """동일 입력 → 동일 출력 (함수 결정성)."""
    original = "BASE\n"
    r1 = _inject_track_b_entry_filename_directive(
        original, AutomationDomain.WEB_SCRAPING
    )
    r2 = _inject_track_b_entry_filename_directive(
        original, AutomationDomain.WEB_SCRAPING
    )
    assert r1 == r2
    # 원본 mutate 안 됨
    assert original == "BASE\n"


def test_qa_loop_actually_injects_directive_into_pytest_task(
    tmp_path: Path, monkeypatch
) -> None:
    """_run_track_b_qa_loop 내부에서 pytest_task.description 이 실제로 directive
    포함하도록 mutate 됐는지 — 통합 검증.

    ``kickoff_with_converter_rescue`` 호출 직전에 task list 를 캡처. Track B
    풀체인엔 두 번 호출됨 (도메인 task + pytest_task) — pytest_task 가 두 번째.
    """
    captured: dict = {"calls": []}

    from src.workflows import automate_workflow as awm
    original_kickoff = awm.kickoff_with_converter_rescue

    def capturing_kickoff(crew, tasks):
        if tasks:
            captured["calls"].append(tasks[0].description)
        return original_kickoff(crew, tasks)

    monkeypatch.setattr(awm, "kickoff_with_converter_rescue", capturing_kickoff)

    run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_qa_loop=True,
    )

    # 두 번 호출 (도메인 task + pytest_task). 마지막 호출이 pytest_task.
    assert len(captured["calls"]) >= 2, (
        f"kickoff 호출 수가 2 미만: {len(captured['calls'])}"
    )
    pytest_desc = captured["calls"][-1]
    assert "Track B entry 파일명 강제 (PR #86)" in pytest_desc, (
        "pytest_task description 에 PR #86 directive 미주입"
    )
    assert "import scrape" in pytest_desc
    assert "test_scrape.py" in pytest_desc


# ---------------------------------------------------------------------------
# PR #88 — entry .py 의 import path 강제 (PR #87 회귀 차단)
#
# 배경 (PR #87 검증에서 발견):
#   scrape.py: from playwright.async_api import ... (async)
#   test_scrape.py: _StubPW (sync_playwright 가정) → playwright 만 stub
#   → ModuleNotFoundError: 'playwright' is not a package
# 처방: code_task 산출에서 import 추출 → pytest_task description 에 명시
# ---------------------------------------------------------------------------


def test_extract_imports_from_python_block() -> None:
    """``code_task`` 산출 마크다운의 첫 ```python``` 블록에서 import 라인 추출."""
    md = (
        "## Track B 산출\n\n"
        "### 3. 단독 실행 코드\n\n"
        "```python\n"
        "# file: scrape.py\n"
        "from playwright.async_api import async_playwright, Browser\n"
        "import os\n"
        "from typing import Optional\n"
        "import asyncio\n"
        "\n"
        "async def main():\n"
        "    pass\n"
        "```\n"
    )
    imports = _extract_imports_from_track_b_code_block(md)
    assert "from playwright.async_api import async_playwright, Browser" in imports
    assert "import os" in imports
    assert "from typing import Optional" in imports
    assert "import asyncio" in imports
    assert len(imports) == 4


def test_extract_imports_returns_empty_for_no_python_block() -> None:
    """python fence 부재 → 빈 리스트."""
    md = "Just plain text with no python block."
    assert _extract_imports_from_track_b_code_block(md) == []


def test_extract_imports_returns_empty_for_empty_input() -> None:
    """빈 입력 / 공백 입력 → 빈 리스트 (방어적)."""
    assert _extract_imports_from_track_b_code_block("") == []
    assert _extract_imports_from_track_b_code_block("   ") == []


def test_extract_imports_picks_first_python_block_only() -> None:
    """여러 python 블록이 있어도 첫 블록 (entry .py 가정) 만 파싱."""
    md = (
        "```python\n"
        "import alpha\n"
        "```\n"
        "\n"
        "```python\n"
        "import beta\n"
        "```\n"
    )
    imports = _extract_imports_from_track_b_code_block(md)
    assert imports == ["import alpha"]
    # 두 번째 블록의 beta 는 추출 안 됨
    assert "import beta" not in imports


def test_inject_import_directive_includes_extracted_imports() -> None:
    """directive 본문에 추출된 import 라인 + 회귀 사례 + 경고 문구 포함."""
    imports = [
        "from playwright.async_api import async_playwright",
        "import os",
    ]
    result = _inject_track_b_import_directive("BASE\n", imports)
    assert "import path 강제 (PR #88)" in result
    assert "``from playwright.async_api import async_playwright``" in result
    assert "``import os``" in result
    # PR #87 회귀 사례 명시 (추적성)
    assert "PR #87" in result
    assert "playwright.async_api" in result
    assert "ModuleNotFoundError" in result


def test_inject_import_directive_skip_for_empty_imports() -> None:
    """빈 imports → 변경 없음 (방어적)."""
    original = "BASE\n"
    assert _inject_track_b_import_directive(original, []) == original


def test_inject_import_directive_truncates_long_lists() -> None:
    """imports > 12 → 첫 12개만 + ``... 외 N개`` 표기 (description 폭주 방지)."""
    imports = [f"import mod{i}" for i in range(20)]
    result = _inject_track_b_import_directive("BASE\n", imports)
    assert "``import mod0``" in result
    assert "``import mod11``" in result
    assert "... 외 8개" in result
    # 13번째 항목은 직접 표시 안 됨
    assert "``import mod12``" not in result


def test_qa_loop_actually_injects_import_directive_into_pytest_task(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """_run_track_b_qa_loop 가 PR #86 + PR #88 directive 모두 주입.

    FakeProvider 응답을 도메인 산출 형식으로 stub — `# file: scrape.py` +
    ``from playwright.async_api import ...`` 포함. _run_track_b_qa_loop 가
    이 응답을 code_task 출력으로 받아 import 추출 → pytest_task.description
    에 directive 주입.
    """
    # 도메인 task 의 산출에 specific imports 포함 (_extract_imports 가 추출 가능)
    _patch_llm_factory._response = (
        "Thought: Track B test stub.\n"
        "Final Answer: tool=fake, ok\n\n"
        "## Web Scraping 산출\n\n"
        "### 3. 단독 실행 코드\n\n"
        "```python\n"
        "# file: scrape.py\n"
        "from playwright.async_api import async_playwright\n"
        "import asyncio\n"
        "from typing import Optional\n"
        "\n"
        "async def main():\n"
        "    pass\n"
        "```\n"
    )

    captured: dict = {"calls": []}
    from src.workflows import automate_workflow as awm
    original_kickoff = awm.kickoff_with_converter_rescue

    def capturing_kickoff(crew, tasks):
        if tasks:
            captured["calls"].append(tasks[0].description)
        return original_kickoff(crew, tasks)

    monkeypatch.setattr(awm, "kickoff_with_converter_rescue", capturing_kickoff)

    run_automate_workflow(
        "네이버 쇼핑 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_qa_loop=True,
    )

    # 마지막 kickoff = pytest_task
    assert len(captured["calls"]) >= 2
    pytest_desc = captured["calls"][-1]
    # PR #86 directive 그대로 포함
    assert "Track B entry 파일명 강제 (PR #86)" in pytest_desc
    # PR #88 directive 추가 포함
    assert "import path 강제 (PR #88)" in pytest_desc
    # 추출된 imports 가 directive 본문에 포함
    assert "playwright.async_api" in pytest_desc
    assert "import asyncio" in pytest_desc
    # PR #100 directive — stub 심볼 enumeration + __getattr__ fallback
    assert "PR #100" in pytest_desc
    assert "__getattr__" in pytest_desc
    assert "_UNIVERSAL_NOOP" in pytest_desc


# ---------------------------------------------------------------------------
# PR #100 — _extract_imported_symbols_from_track_b_code_block (후보 O)
# ---------------------------------------------------------------------------


def test_extract_symbols_single_module_inline_comma_list() -> None:
    """``from playwright.async_api import async_playwright, expect, TimeoutError``
    → {모듈: [3 심볼]}."""
    md = (
        "## 5단\n"
        "```python\n"
        "# file: scrape.py\n"
        "from playwright.async_api import async_playwright, expect, TimeoutError\n"
        "import csv\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {
        "playwright.async_api": ["async_playwright", "expect", "TimeoutError"]
    }


def test_extract_symbols_strips_alias() -> None:
    """``import X as Y`` 의 alias 는 제거되고 원본 심볼명만 보존."""
    md = (
        "```python\n"
        "from playwright.async_api import async_playwright as ap, TimeoutError as PWT\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {
        "playwright.async_api": ["async_playwright", "TimeoutError"]
    }


def test_extract_symbols_multiline_parens() -> None:
    """``from X import (\\n    a,\\n    b,\\n    c,\\n)`` 멀티라인 괄호 import 도 파싱."""
    md = (
        "```python\n"
        "from playwright.async_api import (\n"
        "    async_playwright,\n"
        "    expect,\n"
        "    TimeoutError as PWTimeoutError,\n"
        ")\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {
        "playwright.async_api": ["async_playwright", "expect", "TimeoutError"]
    }


def test_extract_symbols_multiple_modules() -> None:
    """여러 ``from X import ...`` 라인 → 각 모듈 별 심볼 매핑."""
    md = (
        "```python\n"
        "from playwright.async_api import async_playwright, expect\n"
        "from urllib.parse import urljoin, urlparse\n"
        "from bs4 import BeautifulSoup\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {
        "playwright.async_api": ["async_playwright", "expect"],
        "urllib.parse": ["urljoin", "urlparse"],
        "bs4": ["BeautifulSoup"],
    }


def test_extract_symbols_dedupes_within_module() -> None:
    """같은 모듈에 같은 심볼 중복 등장 시 한 번만 등록."""
    md = (
        "```python\n"
        "from playwright.async_api import async_playwright\n"
        "from playwright.async_api import async_playwright, expect\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {"playwright.async_api": ["async_playwright", "expect"]}


def test_extract_symbols_ignores_plain_import_lines() -> None:
    """``import X`` (from 없음) 은 심볼 enumeration 의미 없음 → 제외."""
    md = (
        "```python\n"
        "import csv\n"
        "import sys\n"
        "import asyncio\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {}


def test_extract_symbols_empty_for_no_python_block() -> None:
    """python 블록 부재 / 빈 입력 → 빈 dict."""
    assert _extract_imported_symbols_from_track_b_code_block("") == {}
    assert _extract_imported_symbols_from_track_b_code_block("그냥 한국어") == {}
    md = "```js\nfrom x import y\n```\n"
    assert _extract_imported_symbols_from_track_b_code_block(md) == {}


def test_extract_symbols_skips_star_import() -> None:
    """``from X import *`` 는 enumeration 의미 없음 → 모듈 매핑 X."""
    md = (
        "```python\n"
        "from os.path import *\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert symbols == {}


# ---------------------------------------------------------------------------
# PR #100 — _inject_track_b_stub_getattr_directive (후보 O)
# ---------------------------------------------------------------------------


def test_inject_stub_getattr_directive_enumerates_module_and_symbols() -> None:
    """모듈 + 심볼들이 directive 본문에 명시되어야 한다."""
    symbol_map = {
        "playwright.async_api": ["async_playwright", "expect", "TimeoutError"],
    }
    result = _inject_track_b_stub_getattr_directive("BASE\n", symbol_map)
    assert result.startswith("BASE\n")
    assert "PR #100" in result
    assert "playwright.async_api" in result
    assert "``async_playwright``" in result
    assert "``expect``" in result
    assert "``TimeoutError``" in result


def test_inject_stub_getattr_directive_includes_universal_noop_template() -> None:
    """``__getattr__`` fallback + ``_UNIVERSAL_NOOP`` 클래스 템플릿이 포함되어야 한다."""
    result = _inject_track_b_stub_getattr_directive(
        "BASE\n", {"playwright.async_api": ["expect"]}
    )
    assert "__getattr__" in result
    assert "_UNIVERSAL_NOOP" in result
    assert "__aenter__" in result
    assert "__aexit__" in result


def test_inject_stub_getattr_directive_skip_for_empty_map() -> None:
    """빈 매핑 → directive 미추가 (방어적)."""
    assert _inject_track_b_stub_getattr_directive("BASE\n", {}) == "BASE\n"


def test_inject_stub_getattr_directive_truncates_long_lists() -> None:
    """심볼 > 12개 → 첫 12개만 + overflow 표기."""
    symbols = [f"sym{i}" for i in range(20)]
    result = _inject_track_b_stub_getattr_directive(
        "BASE\n", {"playwright.async_api": symbols}
    )
    assert "``sym0``" in result
    assert "``sym11``" in result
    assert "외 8개" in result
    assert "``sym12``" not in result


def test_inject_stub_getattr_directive_truncates_many_modules() -> None:
    """모듈 > 8개 → 첫 8 모듈만 enumerate + overflow 표기."""
    many_modules = {f"mod{i}": ["a"] for i in range(12)}
    result = _inject_track_b_stub_getattr_directive("BASE\n", many_modules)
    assert "``mod0``" in result
    assert "``mod7``" in result
    assert "외 4 모듈" in result
    # 9 번째 (index 8) 부터 직접 enumerate 안 됨
    assert "``mod8``: ``a``" not in result


def test_inject_stub_getattr_directive_is_idempotent_pure() -> None:
    """같은 입력 → 같은 출력 (deterministic, 부수효과 없음)."""
    sm1 = {"X": ["a", "b"]}
    sm2 = {"X": ["a", "b"]}
    r1 = _inject_track_b_stub_getattr_directive("BASE\n", sm1)
    r2 = _inject_track_b_stub_getattr_directive("BASE\n", sm2)
    assert r1 == r2
    # 입력 dict 변형 없음
    assert sm1 == {"X": ["a", "b"]}


def test_extract_symbols_pr99_iter2_real_payload() -> None:
    """PR #99 ITER 2 실제 산출 (`expect` 누락) 의 import 라인이 정확히 파싱되어야 한다.

    회귀 차단 — 본 테스트가 깨지면 PR #100 directive 가 실 LLM 산출에서
    심볼을 enumerate 하지 못함을 의미. PR #99 N-failure rule 재발 위험.
    """
    # ITER 2 attempt 1 의 실제 scrape.py:20 패턴
    md = (
        "본문\n"
        "```python\n"
        "# file: scrape.py\n"
        "from playwright.async_api import (\n"
        "    async_playwright,\n"
        "    expect,\n"
        "    TimeoutError as PWTimeoutError,\n"
        ")\n"
        "```\n"
    )
    symbols = _extract_imported_symbols_from_track_b_code_block(md)
    assert "playwright.async_api" in symbols
    assert "expect" in symbols["playwright.async_api"]
    assert "async_playwright" in symbols["playwright.async_api"]
    assert "TimeoutError" in symbols["playwright.async_api"]
