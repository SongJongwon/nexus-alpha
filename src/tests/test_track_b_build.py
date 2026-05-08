# -*- coding: utf-8 -*-
"""Track B + Build (PyInstaller) 통합 회귀 방지 테스트 (PR #82).

배경 (Track B 풀체인 시퀀스 2단계 — PR #81 QA 루프 다음):
    PR #81 까지 Track B 는 도메인 에이전트 호출 + (옵션) pytest_author + code_qa
    까지 도달. 그러나 *.exe 산출* 미동반 — Track A 의 Phase 4.5 빌드 사슬과
    같은 산출 안정성 부재.

PR #82 처방:
    1. ``run_automate_workflow(..., enable_build=False)`` 추가 (default — backward compat)
    2. enable_build=True 시 ``execute_pyinstaller`` 직접 호출 (Track A 의 5단 LLM
       사양 사슬은 생략 — Track B 단일 .py CLI 가정)
    3. devops 자동 skip (산출이 Dockerfile/yml — .exe 빌드 부적합)
    4. 도메인별 entry .py 결정론적 결정 (web → scrape.py / desktop → automate.py /
       api → api_client.py / parser → parser.py)
    5. ``AutomateWorkflowResult.executor_result`` 필드 추가 (ExecuteResult 또는 None)
    6. ``analyze_and_implement.run_analyze_and_implement(..., enable_automate_build=True)``
       plumbing

본 테스트는 ``execute_pyinstaller`` 를 monkeypatch 로 mock — 실 PyInstaller
호출은 ``test_build_executor.py`` 에서 별도 검증.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from src.workflows.automate_workflow import (
    AutomateWorkflowResult,
    AutomationDomain,
    _BUILD_SKIP_DOMAINS,
    _DOMAIN_TO_ENTRY_FILENAME,
    _resolve_track_b_entry_path,
    run_automate_workflow,
)


# ---------------------------------------------------------------------------
# 가짜 ExecuteResult — execute_pyinstaller mock 용
# ---------------------------------------------------------------------------


@dataclass
class _FakeExecuteResult:
    success: bool = True
    exit_code: int = 0
    elapsed_sec: float = 1.5
    command: list = None  # type: ignore[assignment]
    exe_path: Optional[Path] = None
    exe_size_bytes: Optional[int] = 1024 * 1024
    sha256: Optional[str] = "deadbeef" * 8
    stdout: str = "(fake stdout)"
    stderr: str = ""
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.command is None:
            self.command = ["pyinstaller", "--noconfirm", "scrape.py"]


def _mock_execute_pyinstaller(monkeypatch, return_value: _FakeExecuteResult) -> dict:
    """``execute_pyinstaller`` 를 monkeypatch — 호출 args 기록."""
    captured: dict[str, Any] = {"called": False, "kwargs": None}

    def fake_executor(**kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        return return_value

    monkeypatch.setattr(
        "src.agents.build_release.build_executor.execute_pyinstaller",
        fake_executor,
    )
    return captured


# ---------------------------------------------------------------------------
# 1. 시그니처 + backward compat
# ---------------------------------------------------------------------------


def test_run_automate_workflow_has_enable_build_param_default_false() -> None:
    sig = inspect.signature(run_automate_workflow)
    assert "enable_build" in sig.parameters
    assert sig.parameters["enable_build"].default is False
    assert "build_timeout_sec" in sig.parameters
    assert sig.parameters["build_timeout_sec"].default == 300


def test_automate_workflow_result_has_executor_result_field_default_none() -> None:
    fields = AutomateWorkflowResult.__dataclass_fields__
    assert "executor_result" in fields
    assert fields["executor_result"].default is None


def test_automate_workflow_result_can_be_constructed_without_executor_result() -> None:
    """기존 호출자는 ``executor_result`` 없이 생성 가능 (backward compat)."""
    result = AutomateWorkflowResult(
        user_request="x",
        detected_domain=AutomationDomain.WEB_SCRAPING,
        agent_output="x",
    )
    assert result.executor_result is None


# ---------------------------------------------------------------------------
# 2. _resolve_track_b_entry_path — 도메인별 결정론적 entry 결정
# ---------------------------------------------------------------------------


def test_resolve_entry_path_picks_domain_standard_filename(tmp_path: Path) -> None:
    """schema 의 ``# file: <name>.py`` 와 일치하는 표준 파일명 우선 선택."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "scrape.py").write_text("# scrape\n")
    (code_dir / "block02.py").write_text("# unused\n")

    entry = _resolve_track_b_entry_path(
        AutomationDomain.WEB_SCRAPING,
        [code_dir / "block02.py", code_dir / "scrape.py"],
    )
    assert entry is not None
    assert entry.name == "scrape.py"


def test_resolve_entry_path_falls_back_to_any_py_excluding_test(tmp_path: Path) -> None:
    """표준 파일명 부재 시 임의 .py (test_*.py 제외)."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "test_scrape.py").write_text("# test\n")
    (code_dir / "custom.py").write_text("# custom\n")

    entry = _resolve_track_b_entry_path(
        AutomationDomain.WEB_SCRAPING,
        [code_dir / "test_scrape.py", code_dir / "custom.py"],
    )
    assert entry is not None
    assert entry.name == "custom.py"


def test_resolve_entry_path_returns_none_when_no_py(tmp_path: Path) -> None:
    """``.py`` 부재 (예: devops 의 Dockerfile + ci.yml 만) → None."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "Dockerfile").write_text("FROM scratch\n")
    (code_dir / ".github__workflows__ci.yml").write_text("name: CI\n")

    entry = _resolve_track_b_entry_path(
        AutomationDomain.DEVOPS,
        [code_dir / "Dockerfile", code_dir / ".github__workflows__ci.yml"],
    )
    assert entry is None


@pytest.mark.parametrize(
    "domain, expected_filename",
    [
        (AutomationDomain.WEB_SCRAPING, "scrape.py"),
        (AutomationDomain.DESKTOP_AUTOMATION, "automate.py"),
        (AutomationDomain.API_INTEGRATION, "api_client.py"),
        (AutomationDomain.DATA_PARSER, "parser.py"),
    ],
)
def test_domain_to_entry_filename_mapping_matches_schema(domain, expected_filename) -> None:
    """4 도메인 entry 파일명이 PR #78 schema 의 ``# file:`` 와 일치."""
    assert _DOMAIN_TO_ENTRY_FILENAME[domain] == expected_filename


# ---------------------------------------------------------------------------
# 3. enable_build=False (default) — backward compat
# ---------------------------------------------------------------------------


def test_build_disabled_default_skips_pyinstaller(tmp_path: Path, monkeypatch) -> None:
    """default enable_build=False → execute_pyinstaller 미호출."""
    captured = _mock_execute_pyinstaller(monkeypatch, _FakeExecuteResult())
    result = run_automate_workflow(
        "엑셀 파일 파싱",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
    )
    assert captured["called"] is False
    assert result.executor_result is None
    assert result.saved_dir is not None
    assert not (result.saved_dir / "04_executor_result.md").exists()


# ---------------------------------------------------------------------------
# 4. enable_build=True — 4 Python 도메인 (parametrize)
# ---------------------------------------------------------------------------


def _set_fake_response_for_domain(_patch_llm_factory, entry_filename: str) -> None:
    """FakeProvider 응답에 ```python``` fence + ``# file: <entry>`` 헤더 포함.

    autouse 의 _patch_llm_factory 는 FakeProvider 인스턴스 — ``_response`` 속성
    교체로 본 테스트만의 도메인별 산출 시뮬레이션 가능.
    """
    _patch_llm_factory._response = (
        "Thought: 도메인 분석 후 5단 본문 산출.\n"
        "Final Answer: tool=fake, summary=ok\n\n"
        "## Track B 산출 (test stub)\n\n"
        "### 3. 단독 실행 코드\n\n"
        f"```python\n"
        f"# file: {entry_filename}\n"
        "if __name__ == '__main__':\n"
        "    print('hello from track b stub')\n"
        "```\n"
    )


@pytest.mark.parametrize(
    "domain, expected_entry_filename, expected_app_name",
    [
        (AutomationDomain.WEB_SCRAPING, "scrape.py", "Scrape"),
        (AutomationDomain.DESKTOP_AUTOMATION, "automate.py", "Automate"),
        (AutomationDomain.API_INTEGRATION, "api_client.py", "Api_Client"),
        (AutomationDomain.DATA_PARSER, "parser.py", "Parser"),
    ],
)
def test_build_enabled_calls_execute_pyinstaller_for_python_domains(
    tmp_path: Path,
    monkeypatch,
    _patch_llm_factory,
    domain,
    expected_entry_filename,
    expected_app_name,
) -> None:
    """4 Python 도메인 모두 enable_build=True → execute_pyinstaller 정확한 args 호출."""
    _set_fake_response_for_domain(_patch_llm_factory, expected_entry_filename)
    fake_result = _FakeExecuteResult(
        exe_path=tmp_path / "build_output" / "dist" / f"{expected_app_name}.exe",
    )
    captured = _mock_execute_pyinstaller(monkeypatch, fake_result)

    result = run_automate_workflow(
        f"{domain.value} sample request",
        outputs_dir=tmp_path,
        forced_domain=domain,
        verbose=False,
        enable_build=True,
    )

    assert result.detected_domain is domain
    assert captured["called"] is True, (
        f"{domain.value}: execute_pyinstaller 미호출 — entry .py 추출 실패 가능"
    )
    kwargs = captured["kwargs"]
    # entry_path 가 도메인 표준 파일명
    assert kwargs["entry_path"].name == expected_entry_filename
    # CLI 스크립트 → windowed=False
    assert kwargs["windowed"] is False
    assert kwargs["onefile"] is True
    assert kwargs["app_name"] == expected_app_name
    # output_dir 이 saved_dir/build_output 하위
    assert kwargs["output_dir"].name == "build_output"
    # 결과 + 04_executor_result.md 저장
    assert result.executor_result is fake_result
    assert (result.saved_dir / "04_executor_result.md").exists()


# ---------------------------------------------------------------------------
# 5. devops — Build 자동 skip
# ---------------------------------------------------------------------------


def test_build_skipped_for_devops_domain(tmp_path: Path, monkeypatch) -> None:
    """devops + enable_build=True → execute_pyinstaller 미호출 (Dockerfile/yml)."""
    captured = _mock_execute_pyinstaller(monkeypatch, _FakeExecuteResult())
    result = run_automate_workflow(
        "Docker multi-stage Dockerfile GitHub Actions 작성",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DEVOPS,
        verbose=False,
        enable_build=True,
    )
    assert captured["called"] is False
    assert result.executor_result is None
    assert not (result.saved_dir / "04_executor_result.md").exists()


def test_build_skip_domains_constant_includes_devops() -> None:
    assert AutomationDomain.DEVOPS in _BUILD_SKIP_DOMAINS
    for d in (
        AutomationDomain.WEB_SCRAPING,
        AutomationDomain.DESKTOP_AUTOMATION,
        AutomationDomain.API_INTEGRATION,
        AutomationDomain.DATA_PARSER,
    ):
        assert d not in _BUILD_SKIP_DOMAINS


# ---------------------------------------------------------------------------
# 6. outputs_dir=None 자동 우회
# ---------------------------------------------------------------------------


def test_build_skipped_when_outputs_dir_none(monkeypatch) -> None:
    """outputs_dir=None (디스크 저장 skip) → enable_build=True 라도 우회."""
    captured = _mock_execute_pyinstaller(monkeypatch, _FakeExecuteResult())
    result = run_automate_workflow(
        "엑셀 파싱",
        outputs_dir=None,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
        enable_build=True,
    )
    assert captured["called"] is False
    assert result.executor_result is None


# ---------------------------------------------------------------------------
# 7. analyze_and_implement plumbing
# ---------------------------------------------------------------------------


def test_analyze_and_implement_has_enable_automate_build_param() -> None:
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    sig = inspect.signature(run_analyze_and_implement)
    assert "enable_automate_build" in sig.parameters
    assert sig.parameters["enable_automate_build"].default is False
    assert "automate_build_timeout_sec" in sig.parameters
    assert sig.parameters["automate_build_timeout_sec"].default == 300


def test_analyze_and_implement_passes_build_flag_to_track_b(
    tmp_path: Path,
    monkeypatch,
    _patch_llm_factory,
) -> None:
    """``enable_automate_build=True`` 가 Track B 까지 전달 → execute_pyinstaller 호출."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    _set_fake_response_for_domain(_patch_llm_factory, "scrape.py")
    fake_result = _FakeExecuteResult(
        exe_path=tmp_path / "build_output" / "dist" / "Scrape.exe",
    )
    captured = _mock_execute_pyinstaller(monkeypatch, fake_result)

    result = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_build=True,
    )
    assert result.chosen_path == "automate_web_scraping"
    assert captured["called"] is True
    assert (result.saved_dir / "04_executor_result.md").exists()
