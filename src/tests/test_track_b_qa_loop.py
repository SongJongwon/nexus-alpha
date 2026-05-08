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
    _QA_LOOP_SKIP_DOMAINS,
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
