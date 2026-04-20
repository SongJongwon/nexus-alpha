# -*- coding: utf-8 -*-
"""
Release Workflow E2E test (Phase 5 통합 — v4 종착지).

검증 항목:
    1) `run_release_workflow(...)` 가 4-agent 사슬을 완주하는지
    2) ReleaseWorkflowResult 의 모든 필드가 채워지는지 (FakeProvider)
    3) `workflow_dir` 주입 시 산출 파일 4개(30~33)가 디스크 저장
    4) `_detect_default_endpoint` 헬퍼가 GitHub URL 파싱 정확
    5) 빈 입력(이전 버전 없음·repo_url 없음) 케이스 동작

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_release_workflow.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_release_workflow.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

load_dotenv(PROJECT_ROOT / ".env")

from src.monitoring import get_langfuse_client
from src.workflows import ReleaseWorkflowResult, run_release_workflow
from src.workflows.release_workflow import _detect_default_endpoint


console = Console()


# =============================================================================
# 1. _detect_default_endpoint 헬퍼 단위 테스트
# =============================================================================
def test_detect_endpoint_github_url() -> None:
    """GitHub URL 에서 api.github.com endpoint 자동 추출."""
    url = _detect_default_endpoint("https://github.com/SongJongwon/nexus-alpha")
    assert url == "https://api.github.com/repos/SongJongwon/nexus-alpha/releases/latest"


def test_detect_endpoint_github_url_with_trailing_slash() -> None:
    """trailing slash 있어도 정확 추출."""
    url = _detect_default_endpoint("https://github.com/owner/repo/")
    assert url == "https://api.github.com/repos/owner/repo/releases/latest"


def test_detect_endpoint_empty_repo_url_returns_placeholder() -> None:
    """repo_url 비어 있으면 placeholder 반환 (Distribution Agent 가 채움)."""
    url = _detect_default_endpoint("")
    assert "TBD" in url


def test_detect_endpoint_non_github_url_returns_generic() -> None:
    """GitHub 가 아닌 URL 은 generic placeholder."""
    url = _detect_default_endpoint("https://internal.company.com/repo")
    assert "releases/latest" in url
    assert "placeholder" in url


# =============================================================================
# 2. run_release_workflow E2E (FakeProvider)
# =============================================================================
def test_run_release_workflow_completes_with_fake_provider(tmp_path: Path) -> None:
    """4-agent 사슬이 FakeProvider 로 완주하고 ReleaseWorkflowResult 모든 필드가 채워짐."""
    workflow_dir = tmp_path / "outputs" / "workflow_test"
    result = run_release_workflow(
        previous_version="0.2.0",
        change_summary="신규 기능 추가 (% 연산자, 키보드 단축키, 다크 모드)",
        change_sources="iter 1: 사칙연산 + 다크모드 / iter 2: 키보드 단축키 추가",
        breaking_flags="none",
        build_summary="PyInstaller onefile, ~28MB, hidden_imports=2",
        artifact_summary="NexusCalc-0.3.0-setup.exe, ~28MB, windows",
        target_platform="windows",
        repo_url="https://github.com/SongJongwon/nexus-alpha",
        app_short_name="NexusCalc",
        signing_available=False,
        privacy_level="public",
        workflow_dir=workflow_dir,
        verbose=False,
    )

    assert isinstance(result, ReleaseWorkflowResult)
    assert result.previous_version == "0.2.0"
    assert result.target_platform == "windows"

    marker = "FakeProvider가 반환한 고정 응답"
    assert marker in result.release_decision
    assert marker in result.changelog_entry
    assert marker in result.update_module_spec
    assert marker in result.distribution_spec


def test_run_release_workflow_saves_4_artifact_files(tmp_path: Path) -> None:
    """workflow_dir 주입 시 30_~33_ prefix 파일 4개 디스크 저장."""
    workflow_dir = tmp_path / "outputs" / "workflow_test"
    result = run_release_workflow(
        previous_version="0.1.0",
        change_summary="첫 patch 릴리스",
        workflow_dir=workflow_dir,
        verbose=False,
    )

    expected_files = [
        "30_release_decision.md",
        "31_changelog_entry.md",
        "32_update_module_spec.md",
        "33_distribution_spec.md",
    ]
    for name in expected_files:
        assert (workflow_dir / name).exists(), f"{name} 가 저장되지 않았다"
    assert len(result.saved_files) == 4


def test_run_release_workflow_handles_first_release(tmp_path: Path) -> None:
    """previous_version 비어 있어도(첫 릴리스) 4-agent 사슬 완주."""
    result = run_release_workflow(
        previous_version="",  # 첫 릴리스
        change_summary="초기 출시",
        workflow_dir=tmp_path,
        verbose=False,
    )

    assert result.previous_version == ""
    marker = "FakeProvider가 반환한 고정 응답"
    assert marker in result.release_decision
    assert marker in result.changelog_entry


def test_release_workflow_result_dataclass_fields(tmp_path: Path) -> None:
    """ReleaseWorkflowResult 의 모든 핵심 필드 타입·기본값 sanity."""
    result = run_release_workflow(
        previous_version="0.2.0",
        change_summary="필드 sanity 검증",
        workflow_dir=tmp_path,
    )
    assert isinstance(result.release_decision, str) and result.release_decision
    assert isinstance(result.changelog_entry, str)
    assert isinstance(result.update_module_spec, str)
    assert isinstance(result.distribution_spec, str)
    assert isinstance(result.saved_files, list)
    assert result.target_platform in {"windows", "macos", "linux", "cross-platform"}


# =============================================================================
# 3. 직접 실행 경로 (실제 LLM)
# =============================================================================
def main() -> int:
    """실제 LLM 으로 4-agent 사슬 1바퀴."""
    console.print(Rule("[bold cyan]Release Workflow smoke — 4단 릴리스 사슬[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_release_workflow",
        user_id="local-dev",
        metadata={"phase": "phase_5_workflow"},
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        result = run_release_workflow(
            previous_version="0.2.0",
            change_summary=(
                "신규 기능: % 연산자, 키보드 단축키 (Enter/Backspace), 다크 모드 토글. "
                "버그 수정: 0으로 나누기 시 토스트 메시지."
            ),
            change_sources=(
                "iter 1: 사칙연산 + 다크모드 / iter 2: 키보드 단축키 / iter 3: % 연산자"
            ),
            breaking_flags="none",
            build_summary="PyInstaller onefile, est_size=~28MB, hidden_imports=2",
            artifact_summary="NexusCalc-0.3.0-setup.exe, ~28MB, windows",
            target_platform="windows",
            repo_url="https://github.com/SongJongwon/nexus-alpha",
            app_short_name="NexusCalc",
            signing_available=False,
            privacy_level="public",
            workflow_dir=tmp / "out",
            verbose=False,
        )

    console.print(
        Panel(
            f"[bold]previous_version[/bold]: {result.previous_version}\n"
            f"[bold]target_platform[/bold]: {result.target_platform}\n"
            f"[bold]saved_files[/bold]: {len(result.saved_files)}개\n"
            f"[bold]release_decision (앞 200자)[/bold]:\n{result.release_decision[:200]}\n"
            f"[bold]changelog_entry (앞 200자)[/bold]:\n{result.changelog_entry[:200]}",
            title="[green]ReleaseWorkflowResult[/green]",
            border_style="green",
        )
    )
    monitor.end_trace()
    monitor.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
