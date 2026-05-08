# -*- coding: utf-8 -*-
"""Track B + Release (Update Checker + gh release create) 통합 회귀 방지 테스트 (PR #83).

배경 (Track B 풀체인 시퀀스 3단계 — PR #82 Build 다음):
    PR #81 (QA 루프) + PR #82 (Build) 까지 Track B 는 도메인 에이전트 +
    pytest_author + code_qa + .exe 산출. 그러나 *Update Checker 통합* 과
    *Draft Release 발행* 미동반 — Track A 의 Phase 5 와 같은 산출 안정성 부재.

PR #83 처방:
    1. ``run_automate_workflow(..., enable_release=False, ...)`` 추가 (default — backward compat)
    2. enable_release=True 시:
       a. Update Checker LLM (1 task) — ``UpdateModuleSpecOutput`` schema 강제로
          ``updater.py`` fence + ``# file:`` 헤더 자동 (PR #66 패턴 재사용)
       b. ``_integrate_update_checker`` 호출 → ``code/updater.py`` 추출 + entry .py
          에 자동 import 라인 주입
       c. ``executor_result.exe_path`` + repo_url + release_tag 모두 있을 때만
          ``execute_gh_release`` 호출 → Draft Release 발행
    3. devops 자동 skip (산출이 Dockerfile/yml — .exe 없음)
    4. ``AutomateWorkflowResult.update_module_spec`` + ``publish_result`` 필드 추가
    5. ``analyze_and_implement.run_analyze_and_implement(...,
       enable_automate_release=True, automate_repo_url=..., automate_release_tag=...)`` plumbing

본 테스트는 ``execute_gh_release`` 를 monkeypatch 로 mock — 실 gh CLI 호출은
``test_distribution_executor.py`` 에서 별도 검증.
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
    _RELEASE_SKIP_DOMAINS,
    run_automate_workflow,
)


# ---------------------------------------------------------------------------
# 가짜 dataclass — execute_pyinstaller / execute_gh_release mock 용
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
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.command is None:
            self.command = ["pyinstaller", "--noconfirm", "scrape.py"]


@dataclass
class _FakePublishResult:
    success: bool = True
    exit_code: int = 0
    elapsed_sec: float = 3.0
    tag: str = "v0.1.0"
    is_draft: bool = True
    release_url: Optional[str] = "https://github.com/owner/repo/releases/tag/v0.1.0"
    download_urls: list = None  # type: ignore[assignment]
    files_uploaded: list = None  # type: ignore[assignment]
    command: list = None  # type: ignore[assignment]
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.download_urls is None:
            self.download_urls = [
                "https://github.com/owner/repo/releases/download/v0.1.0/Scrape.exe"
            ]
        if self.files_uploaded is None:
            self.files_uploaded = []
        if self.command is None:
            self.command = ["gh", "release", "create", "v0.1.0", "--draft"]


def _mock_execute_pyinstaller(monkeypatch, return_value: _FakeExecuteResult) -> dict:
    captured: dict[str, Any] = {"called": False, "kwargs": None}

    def fake(**kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        # exe_path 가 실제 존재해야 publish 단계가 작동
        out = kwargs.get("output_dir")
        if out is not None and return_value.exe_path is None:
            (out / "dist").mkdir(parents=True, exist_ok=True)
            real_exe = out / "dist" / f"{kwargs.get('app_name', 'App')}.exe"
            real_exe.write_bytes(b"fake exe bytes")
            return_value.exe_path = real_exe
            return_value.exe_size_bytes = real_exe.stat().st_size
        return return_value

    monkeypatch.setattr(
        "src.agents.build_release.build_executor.execute_pyinstaller",
        fake,
    )
    return captured


def _mock_execute_gh_release(monkeypatch, return_value: _FakePublishResult) -> dict:
    captured: dict[str, Any] = {"called": False, "kwargs": None}

    def fake(**kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        return return_value

    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor.execute_gh_release",
        fake,
    )
    return captured


def _set_fake_response_with_python_entry(_patch_llm_factory, entry_filename: str) -> None:
    """FakeProvider 응답에 entry .py + updater.py 두 ```python``` 블록 모두 포함.

    Update Checker 의 schema (UpdateModuleSpecOutput) to_markdown 도 자동 처리하지만,
    FakeProvider 가 schema 통과 응답을 만들 수 없으므로 raw markdown 그대로 사용
    (pytest 환경에선 output_pydantic 미적용).
    """
    _patch_llm_factory._response = (
        "Thought: Track B sample 테스트 응답.\n"
        "Final Answer: tool=fake, summary=ok\n\n"
        "## Track B 산출 (test stub)\n\n"
        "### 3. 단독 실행 코드\n\n"
        f"```python\n"
        f"# file: {entry_filename}\n"
        "if __name__ == '__main__':\n"
        "    print('hello')\n"
        "```\n\n"
        "### 2. updater.py 참조 구현\n\n"
        "```python\n"
        "# file: updater.py\n"
        "def check_update():\n"
        "    return None\n"
        "```\n"
    )


# ---------------------------------------------------------------------------
# 1. 시그니처 + backward compat
# ---------------------------------------------------------------------------


def test_run_automate_workflow_has_release_params_default_disabled() -> None:
    sig = inspect.signature(run_automate_workflow)
    assert "enable_release" in sig.parameters
    assert sig.parameters["enable_release"].default is False
    assert "repo_url" in sig.parameters
    assert sig.parameters["repo_url"].default == ""
    assert "release_tag" in sig.parameters
    assert sig.parameters["release_tag"].default == ""
    assert sig.parameters["publish_as_draft"].default is True
    assert sig.parameters["publish_timeout_sec"].default == 120


def test_automate_workflow_result_has_release_fields_default_empty() -> None:
    fields = AutomateWorkflowResult.__dataclass_fields__
    assert "update_module_spec" in fields
    assert fields["update_module_spec"].default == ""
    assert "publish_result" in fields
    assert fields["publish_result"].default is None


def test_automate_workflow_result_can_be_constructed_without_release_fields() -> None:
    """기존 호출자는 release 필드 없이 생성 가능 (backward compat)."""
    result = AutomateWorkflowResult(
        user_request="x",
        detected_domain=AutomationDomain.WEB_SCRAPING,
        agent_output="x",
    )
    assert result.update_module_spec == ""
    assert result.publish_result is None


# ---------------------------------------------------------------------------
# 2. enable_release=False (default) — backward compat
# ---------------------------------------------------------------------------


def test_release_disabled_default_skips_update_checker_and_publish(
    tmp_path: Path, monkeypatch
) -> None:
    """default enable_release=False → Update Checker + publish 모두 미실행."""
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())
    result = run_automate_workflow(
        "엑셀 파일 파싱",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
    )
    assert result.update_module_spec == ""
    assert result.publish_result is None
    assert captured_publish["called"] is False
    assert result.saved_dir is not None
    assert not (result.saved_dir / "05_update_module_spec.md").exists()


# ---------------------------------------------------------------------------
# 3. enable_release=True — Update Checker LLM 호출 + 05_*.md 저장
# ---------------------------------------------------------------------------


def test_release_enabled_runs_update_checker_for_python_domain(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """4 Python 도메인 중 1개 — enable_release=True 가 Update Checker LLM 실행 + 05_*.md 저장."""
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_release=True,
    )
    assert result.update_module_spec  # 비어있지 않음
    assert result.saved_dir is not None
    assert (result.saved_dir / "05_update_module_spec.md").exists()


def test_release_integrates_updater_into_entry_py(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """Update Checker 산출의 ``updater.py`` 가 ``code/`` 에 추출 + entry .py 에
    auto-inject 마커 삽입 (PR #66 패턴 재사용)."""
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_release=True,
    )
    code_dir = result.saved_dir / "code"
    # updater.py 추출됨
    updater_py = code_dir / "updater.py"
    assert updater_py.exists()
    # entry .py 에 auto-inject 마커 (PR #66) 존재
    entry_py = code_dir / "scrape.py"
    if entry_py.exists():
        content = entry_py.read_text(encoding="utf-8")
        assert "Auto-injected by Nexus Alpha" in content or "import updater" in content


# ---------------------------------------------------------------------------
# 4. publish: enable_release=True + .exe + repo_url + tag → execute_gh_release 호출
# ---------------------------------------------------------------------------


def test_publish_called_when_exe_and_repo_and_tag_all_provided(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """.exe (executor_result) + repo_url + release_tag 모두 있을 때 gh release 호출."""
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    fake_exe = _FakeExecuteResult()
    captured_build = _mock_execute_pyinstaller(monkeypatch, fake_exe)
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_build=True,
        enable_release=True,
        repo_url="owner/repo",
        release_tag="v0.1.0-track-b",
    )
    assert captured_build["called"] is True
    assert captured_publish["called"] is True
    publish_kwargs = captured_publish["kwargs"]
    assert publish_kwargs["repo"] == "owner/repo"
    assert publish_kwargs["tag"] == "v0.1.0-track-b"
    assert publish_kwargs["draft"] is True
    # files_to_upload 에 exe_path 포함
    assert any(p.suffix == ".exe" for p in publish_kwargs["files_to_upload"])
    # 06_publish_result.md 저장
    assert (result.saved_dir / "06_publish_result.md").exists()
    assert result.publish_result is not None


def test_publish_skipped_when_repo_url_missing(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """repo_url 부재 시 Update Checker 만 실행, publish skip."""
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    fake_exe = _FakeExecuteResult()
    _mock_execute_pyinstaller(monkeypatch, fake_exe)
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_build=True,
        enable_release=True,
        # repo_url, release_tag 미제공
    )
    assert captured_publish["called"] is False
    assert result.publish_result is None
    # Update Checker 는 여전히 실행
    assert (result.saved_dir / "05_update_module_spec.md").exists()


def test_publish_skipped_when_no_executor_result(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """enable_build=False 면 .exe 없음 → publish skip (Update Checker 만)."""
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_automate_workflow(
        "네이버 쇼핑 가격 크롤링",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.WEB_SCRAPING,
        verbose=False,
        enable_build=False,  # .exe 안 만듦
        enable_release=True,
        repo_url="owner/repo",
        release_tag="v0.1.0",
    )
    assert captured_publish["called"] is False
    assert result.publish_result is None
    assert (result.saved_dir / "05_update_module_spec.md").exists()


# ---------------------------------------------------------------------------
# 5. devops — Release 자동 skip
# ---------------------------------------------------------------------------


def test_release_skipped_for_devops_domain(tmp_path: Path, monkeypatch) -> None:
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())
    result = run_automate_workflow(
        "Docker multi-stage Dockerfile GitHub Actions 작성",
        outputs_dir=tmp_path,
        forced_domain=AutomationDomain.DEVOPS,
        verbose=False,
        enable_release=True,
        repo_url="owner/repo",
        release_tag="v0.1.0",
    )
    assert captured_publish["called"] is False
    assert result.update_module_spec == ""
    assert result.publish_result is None
    assert not (result.saved_dir / "05_update_module_spec.md").exists()


def test_release_skip_domains_constant_includes_devops() -> None:
    assert AutomationDomain.DEVOPS in _RELEASE_SKIP_DOMAINS
    for d in (
        AutomationDomain.WEB_SCRAPING,
        AutomationDomain.DESKTOP_AUTOMATION,
        AutomationDomain.API_INTEGRATION,
        AutomationDomain.DATA_PARSER,
    ):
        assert d not in _RELEASE_SKIP_DOMAINS


# ---------------------------------------------------------------------------
# 6. outputs_dir=None 자동 우회
# ---------------------------------------------------------------------------


def test_release_skipped_when_outputs_dir_none(monkeypatch, _patch_llm_factory) -> None:
    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    captured_publish = _mock_execute_gh_release(monkeypatch, _FakePublishResult())
    result = run_automate_workflow(
        "엑셀 파싱",
        outputs_dir=None,
        forced_domain=AutomationDomain.DATA_PARSER,
        verbose=False,
        enable_release=True,
    )
    assert captured_publish["called"] is False
    assert result.update_module_spec == ""
    assert result.publish_result is None


# ---------------------------------------------------------------------------
# 7. analyze_and_implement plumbing
# ---------------------------------------------------------------------------


def test_analyze_and_implement_has_release_params() -> None:
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    sig = inspect.signature(run_analyze_and_implement)
    assert "enable_automate_release" in sig.parameters
    assert sig.parameters["enable_automate_release"].default is False
    assert "automate_repo_url" in sig.parameters
    assert sig.parameters["automate_repo_url"].default == ""
    assert "automate_release_tag" in sig.parameters
    assert sig.parameters["automate_release_tag"].default == ""


def test_analyze_and_implement_passes_release_flag_to_track_b(
    tmp_path: Path, monkeypatch, _patch_llm_factory
) -> None:
    """``enable_automate_release=True`` 가 Track B 까지 전달 → 05_*.md 저장."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    _set_fake_response_with_python_entry(_patch_llm_factory, "scrape.py")
    _mock_execute_gh_release(monkeypatch, _FakePublishResult())

    result = run_analyze_and_implement(
        "네이버 쇼핑 가격 크롤링 스크립트",
        outputs_dir=tmp_path,
        verbose=False,
        enable_automate_branch=True,
        enable_automate_release=True,
    )
    assert result.chosen_path == "automate_web_scraping"
    assert result.saved_dir is not None
    assert (result.saved_dir / "05_update_module_spec.md").exists()
