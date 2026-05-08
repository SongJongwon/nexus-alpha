# -*- coding: utf-8 -*-
"""automate_workflow.py + analyze_and_implement.py Track B 라우팅 회귀 방지 (PR #70).

배경:
    PR #68 (옵션 6.A) 가 Phase 6 Track B 5 에이전트를 등록 ✅, 그러나 호출되지 않음.
    PR #70 (옵션 6.B) 가 별도 워크플로 (`automate_workflow.py`) 신설 + Track A
    (`analyze_and_implement.py`) 에 라우팅 토글 추가.

검증 항목:
    1. ``detect_automation_domain`` 휴리스틱 분류 — 5 도메인 + UNKNOWN
    2. ``run_automate_workflow`` factory 매핑 (forced_domain) — LLM 호출 시 FakeProvider
    3. ``_extract_track_b_code_blocks`` Python / Dockerfile / YAML 모두 추출
    4. ``analyze_and_implement.run_analyze_and_implement`` 의 ``enable_automate_branch``
       토글 — UNKNOWN 시 Track A fallback (backward compat 보장)
    5. ``__init__.py`` export 검증

LLM 호출 없는 정적·휴리스틱 검증만 — 풀체인 PASS 검증은 향후 E2E 에서.
"""

from __future__ import annotations

from pathlib import Path

from src.workflows.automate_workflow import (
    AutomationDomain,
    _DOMAIN_TO_FACTORY,
    _extract_track_b_code_blocks,
    detect_automation_domain,
)


# ---------------------------------------------------------------------------
# 1. detect_automation_domain — 5 도메인 + UNKNOWN
# ---------------------------------------------------------------------------


def test_detect_web_scraping_domain() -> None:
    assert detect_automation_domain("네이버 쇼핑 가격 크롤링 스크립트") == AutomationDomain.WEB_SCRAPING
    assert detect_automation_domain("Playwright 로 동적 페이지 스크래핑") == AutomationDomain.WEB_SCRAPING
    assert detect_automation_domain("Selenium 으로 로그인 자동 후 데이터 수집해") == AutomationDomain.WEB_SCRAPING


def test_detect_desktop_automation_domain() -> None:
    assert detect_automation_domain("PyAutoGUI 로 엑셀 자동 입력") == AutomationDomain.DESKTOP_AUTOMATION
    assert detect_automation_domain("PyWinAuto 로 outlook 자동화") == AutomationDomain.DESKTOP_AUTOMATION
    # NOTE: '메일 발송' 만으로는 잘 안 잡힐 수 있음 — 도구명 매칭이 더 강함


def test_detect_api_integration_domain() -> None:
    assert detect_automation_domain("Slack webhook 으로 알림 보내기") == AutomationDomain.API_INTEGRATION
    assert detect_automation_domain("Stripe API OAuth 인증 연동") == AutomationDomain.API_INTEGRATION
    assert detect_automation_domain("FastAPI 로 webhook 수신 endpoint") == AutomationDomain.API_INTEGRATION


def test_detect_data_parser_domain() -> None:
    assert detect_automation_domain("엑셀 파일 분석 PDF 보고서 변환") == AutomationDomain.DATA_PARSER
    assert detect_automation_domain("openpyxl 로 .xlsx 파싱") == AutomationDomain.DATA_PARSER
    assert detect_automation_domain("pdfplumber 로 PDF 테이블 추출") == AutomationDomain.DATA_PARSER


def test_detect_devops_domain() -> None:
    assert detect_automation_domain("Dockerfile multi-stage 빌드 작성") == AutomationDomain.DEVOPS
    assert detect_automation_domain("GitHub Actions CI/CD 파이프라인") == AutomationDomain.DEVOPS
    assert detect_automation_domain("docker-compose 로 멀티 서비스 구성") == AutomationDomain.DEVOPS


def test_detect_unknown_for_empty_or_ambiguous() -> None:
    assert detect_automation_domain("") == AutomationDomain.UNKNOWN
    assert detect_automation_domain("   ") == AutomationDomain.UNKNOWN
    # 단순 계산기 — Track A 영역 (Track B 신호 없음)
    assert detect_automation_domain("사칙연산 계산기 만들어줘") == AutomationDomain.UNKNOWN


# ---------------------------------------------------------------------------
# 2. domain → factory 매핑 — 5 도메인 모두 매핑
# ---------------------------------------------------------------------------


def test_all_five_domains_have_factory_mapping() -> None:
    """5 도메인 모두 _DOMAIN_TO_FACTORY 에 등록 (UNKNOWN 제외)."""
    expected = {
        AutomationDomain.WEB_SCRAPING,
        AutomationDomain.DESKTOP_AUTOMATION,
        AutomationDomain.API_INTEGRATION,
        AutomationDomain.DATA_PARSER,
        AutomationDomain.DEVOPS,
    }
    assert set(_DOMAIN_TO_FACTORY.keys()) == expected


def test_factories_are_callable_with_default_args() -> None:
    """5 factory 모두 인자 없이 호출 가능 (NexusAlphaLLM 자동 주입)."""
    for domain, factory in _DOMAIN_TO_FACTORY.items():
        agent = factory(verbose=False)
        assert agent is not None
        assert agent.role  # role 비어있지 않음


# ---------------------------------------------------------------------------
# 3. _extract_track_b_code_blocks — Python / Dockerfile / YAML
# ---------------------------------------------------------------------------


def test_extract_python_block_with_file_header(tmp_path: Path) -> None:
    """```python``` 블록 + `# file: scrape.py` 헤더 → code/scrape.py 추출."""
    md = (
        "```python\n"
        "# file: scrape.py\n"
        "from playwright.sync_api import sync_playwright\n"
        "```\n"
    )
    saved = _extract_track_b_code_blocks(md, tmp_path / "code")
    names = {p.name for p in saved}
    assert "scrape.py" in names


def test_extract_dockerfile_block_with_file_header(tmp_path: Path) -> None:
    """```dockerfile``` 블록 + `# file: Dockerfile` 헤더 → code/Dockerfile 추출."""
    md = (
        "```dockerfile\n"
        "# file: Dockerfile\n"
        "FROM python:3.13-slim AS builder\n"
        "RUN pip install --user requests\n"
        "```\n"
    )
    saved = _extract_track_b_code_blocks(md, tmp_path / "code")
    names = {p.name for p in saved}
    assert "Dockerfile" in names


def test_extract_yaml_block_with_file_header(tmp_path: Path) -> None:
    """```yaml``` 블록 + `# file: .github/workflows/ci.yml` 헤더."""
    md = (
        "```yaml\n"
        "# file: .github/workflows/ci.yml\n"
        "name: CI\n"
        "on: [push]\n"
        "```\n"
    )
    saved = _extract_track_b_code_blocks(md, tmp_path / "code")
    # 슬래시는 __ 로 치환되어 단일 파일로 저장됨
    names = {p.name for p in saved}
    assert ".github__workflows__ci.yml" in names


def test_extract_no_blocks_returns_empty(tmp_path: Path) -> None:
    """fence 마커 없는 본문 → 빈 리스트, 부작용 없음."""
    md = "no python or dockerfile or yaml blocks here"
    saved = _extract_track_b_code_blocks(md, tmp_path / "code")
    assert saved == []


# ---------------------------------------------------------------------------
# 4. run_automate_workflow — UNKNOWN 시 ValueError
# ---------------------------------------------------------------------------


def test_run_automate_workflow_raises_on_unknown_without_forced_domain() -> None:
    """휴리스틱 UNKNOWN + forced_domain None → ValueError (명시적 에러)."""
    import pytest

    from src.workflows.automate_workflow import run_automate_workflow

    with pytest.raises(ValueError, match="자동화 도메인을 결정할 수 없습니다"):
        run_automate_workflow("ambiguous request", verbose=False)


def test_run_automate_workflow_with_forced_domain_runs_via_fake_provider(
    tmp_path: Path,
) -> None:
    """forced_domain 명시 → FakeProvider 통과해 산출 + 저장."""
    from src.workflows.automate_workflow import run_automate_workflow

    result = run_automate_workflow(
        "엑셀 파일에서 데이터 추출",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
    )
    assert result.detected_domain is AutomationDomain.DATA_PARSER
    assert result.agent_output  # FakeProvider 응답
    assert result.saved_dir is not None
    assert (result.saved_dir / "00_user_request.txt").exists()
    assert (result.saved_dir / "01_detected_domain.txt").read_text(encoding="utf-8") == "data_parser"
    assert (result.saved_dir / "02_agent_output.md").exists()


# ---------------------------------------------------------------------------
# 5. analyze_and_implement.run_analyze_and_implement — Track B 라우팅 토글
# ---------------------------------------------------------------------------


def test_analyze_and_implement_signature_has_enable_automate_branch() -> None:
    """run_analyze_and_implement 에 enable_automate_branch 파라미터 추가 (default False)."""
    import inspect

    from src.workflows.analyze_and_implement import run_analyze_and_implement

    sig = inspect.signature(run_analyze_and_implement)
    assert "enable_automate_branch" in sig.parameters
    # backward compat — 기본값 False
    assert sig.parameters["enable_automate_branch"].default is False


def test_analyze_and_implement_routes_to_automate_branch_when_domain_clear(
    tmp_path: Path,
) -> None:
    """enable_automate_branch=True + 명확한 도메인 → automate_workflow 호출 →
    chosen_path 가 'automate_<domain>'."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    # DevOps 단일 도메인 (Dockerfile + docker-compose + multi-stage 신호 다수)
    result = run_analyze_and_implement(
        "Dockerfile multi-stage + docker-compose + GitHub Actions 작성해줘",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
    )
    # 도메인 = devops → chosen_path 에 'automate_devops'
    assert result.chosen_path == "automate_devops", (
        f"chosen_path={result.chosen_path!r} (예상 'automate_devops')"
    )
    assert "Track B routing" in result.cto_strategy


def test_analyze_and_implement_falls_back_to_track_a_on_unknown_domain(
    tmp_path: Path,
) -> None:
    """enable_automate_branch=True + 모호한 도메인 (계산기) → Track A fallback.
    backward compat — 기존 풀체인 안 깨짐."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    result = run_analyze_and_implement(
        "사칙연산 계산기 만들어줘",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
    )
    # Track A 진행 — chosen_path 가 'automate_*' 가 아님
    assert not result.chosen_path.startswith("automate_")


# ---------------------------------------------------------------------------
# PR #90 — Track B 산출 4 필드 propagate (검증 스크립트 인지 강화)
#
# 배경: PR #89 검증에서 5_executor_success 가 False 로 나옴 — 검증 스크립트는
# `result.executor_result` 만 읽는데, run_analyze_and_implement 가 Track B
# 분기에서 WorkflowResult 매핑 시 executor_result / pytest_suite /
# update_module_spec / publish_result 4 필드 propagate 누락.
# 처방: 4 필드 모두 propagate.
# ---------------------------------------------------------------------------


def test_analyze_and_implement_propagates_track_b_pytest_suite(
    tmp_path: Path,
) -> None:
    """enable_automate_qa_loop=True → WorkflowResult.pytest_suite 채워짐."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    result = run_analyze_and_implement(
        "Dockerfile multi-stage + docker-compose + GitHub Actions 작성해줘",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_qa_loop=True,
    )
    assert result.chosen_path == "automate_devops"
    # devops 는 QA loop skip — pytest_suite 빈 문자열
    assert result.pytest_suite == ""

    # web_scraping 으로 다시 — QA loop 가 실행되므로 pytest_suite 비어있지 않음
    result2 = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_qa_loop=True,
    )
    assert result2.chosen_path == "automate_web_scraping"
    assert result2.pytest_suite, "Track B QA loop pytest_suite 미 propagate"


def test_analyze_and_implement_propagates_track_b_executor_result(
    tmp_path: Path, monkeypatch
) -> None:
    """enable_automate_build=True + .py entry 가 추출되면 executor_result propagate.

    실 ``execute_pyinstaller`` 호출은 monkeypatch 로 mock — Track B build helper
    까지 도달하면 fake ExecuteResult 가 WorkflowResult.executor_result 로 propagate.
    """
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    # FakeProvider 응답을 web_scraping schema 형식으로 stub (entry 추출 가능)
    from src.tests.test_track_b_build import (
        _FakeExecuteResult,
        _mock_execute_pyinstaller,
        _set_fake_response_for_domain,
    )

    # default_fake_provider 가 conftest fixture 이므로 _patch_llm_factory 직접 사용
    # (이 테스트에선 새 응답 inject 가 필요)
    fake_exec = _FakeExecuteResult()
    _mock_execute_pyinstaller(monkeypatch, fake_exec)

    # _patch_llm_factory autouse fixture 가 이미 setup 됨 — 직접 access
    import src.llm.factory as factory_module
    fake_provider = factory_module.get_llm_provider()
    fake_provider._response = (
        "Thought: Track B build stub.\n"
        "Final Answer: tool=fake\n\n"
        "## Web Scraping 산출\n\n"
        "### 3. 단독 실행 코드\n\n"
        "```python\n"
        "# file: scrape.py\n"
        "if __name__ == '__main__':\n"
        "    print('hello')\n"
        "```\n"
    )

    result = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_build=True,
    )
    assert result.chosen_path == "automate_web_scraping"
    # Track B 의 fake ExecuteResult 가 WorkflowResult.executor_result 로 propagate
    assert result.executor_result is fake_exec, (
        "Track B executor_result 가 WorkflowResult.executor_result 로 미 propagate "
        "(PR #90 회귀)"
    )
    # 검증 스크립트의 5_executor_success 판정 기준
    assert getattr(result.executor_result, "success", False) is True


def test_analyze_and_implement_propagates_track_b_update_module_spec_and_publish_result(
    tmp_path: Path,
) -> None:
    """enable_automate_release=True → update_module_spec + publish_result propagate."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    # web_scraping 도메인 — release 활성 시 Update Checker LLM 산출 + (옵션) publish
    result = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_release=True,
        # repo / tag 미제공 → Update Checker 만 실행, publish skip
    )
    assert result.chosen_path == "automate_web_scraping"
    # update_module_spec 은 LLM 산출이므로 비어있지 않음
    assert result.update_module_spec, (
        "Track B update_module_spec 미 propagate (PR #83+#90)"
    )
    # publish_result 는 repo/tag 미제공으로 None
    assert result.publish_result is None


def test_analyze_and_implement_track_b_unknown_domain_skips_propagation(
    tmp_path: Path,
) -> None:
    """UNKNOWN 도메인 → Track A fallback → Track B 필드들 default 유지 (backward compat)."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    result = run_analyze_and_implement(
        "사칙연산 계산기 만들어줘",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_qa_loop=True,
        enable_automate_build=True,
        enable_automate_release=True,
    )
    # Track A 진행 — chosen_path 가 'automate_*' 가 아님
    assert not result.chosen_path.startswith("automate_")
    # 본 path 는 Track A 의 own logic 으로 필드 채움 (Track B propagation 무관)


# ---------------------------------------------------------------------------
# 6. __init__.py export 검증
# ---------------------------------------------------------------------------


def test_workflows_init_exports_track_b_symbols() -> None:
    """src.workflows 에서 Track B 4 심볼 import 가능."""
    from src import workflows

    assert hasattr(workflows, "AutomateWorkflowResult")
    assert hasattr(workflows, "AutomationDomain")
    assert hasattr(workflows, "detect_automation_domain")
    assert hasattr(workflows, "run_automate_workflow")
    for sym in (
        "AutomateWorkflowResult",
        "AutomationDomain",
        "detect_automation_domain",
        "run_automate_workflow",
    ):
        assert sym in workflows.__all__, f"workflows.__all__ 에 {sym} 누락"


def test_workflows_init_preserves_track_a_exports() -> None:
    """기존 Track A export (run_analyze_and_implement / WorkflowResult) backward compat."""
    from src import workflows

    assert hasattr(workflows, "run_analyze_and_implement")
    assert hasattr(workflows, "WorkflowResult")
    assert "run_analyze_and_implement" in workflows.__all__
    assert "WorkflowResult" in workflows.__all__
