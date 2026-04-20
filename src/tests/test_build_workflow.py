# -*- coding: utf-8 -*-
"""
Build Workflow E2E test (Phase 4.5 통합 — v4).

검증 항목:
    1) `run_build_workflow(code_files, ...)` 가 5-agent 사슬을 완주하는지
    2) BuildWorkflowResult 의 모든 필드가 채워지는지 (FakeProvider 기준)
    3) `workflow_dir` 주입 시 산출 파일 5개(20~24)가 디스크에 저장되는지
    4) `enable_platform_test=False` 토글 동작 — Platform Tester skip 안내 문자열 포함
    5) `code_files` 비어 있어도 함수 동작 (Platform Tester 가 sandbox skip 처리)

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_build_workflow.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_build_workflow.py -v
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
from src.workflows import BuildWorkflowResult, run_build_workflow


console = Console()


# ---------------------------------------------------------------------------
# 헬퍼 — 임시 코드 파일 1개 생성 (단일 파일 entry — sandbox 가 발견 가능)
# ---------------------------------------------------------------------------
def _make_minimal_code_files(tmp_path: Path) -> list[Path]:
    """단일 파일 calculator.py 작성 — `# file:` 헤더 포함, print 1줄."""
    p = tmp_path / "calculator.py"
    p.write_text("# file: calculator.py\nprint('build workflow smoke ok')\n", encoding="utf-8")
    return [p]


# ---------------------------------------------------------------------------
# pytest 진입점 (FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_run_build_workflow_completes_with_fake_provider(tmp_path: Path) -> None:
    """5-agent 사슬이 FakeProvider 로 완주하고 BuildWorkflowResult 의 모든 필드가 채워짐."""
    code_files = _make_minimal_code_files(tmp_path)

    workflow_dir = tmp_path / "outputs" / "workflow_test"
    result = run_build_workflow(
        code_files=code_files,
        user_request="사칙연산 계산기 빌드 워크플로우 검증",
        target_platform="windows",
        ui_spec="",  # Phase 4 미사용
        design_tokens="",
        workflow_dir=workflow_dir,
        enable_platform_test=True,
        verbose=False,
    )

    assert isinstance(result, BuildWorkflowResult)
    assert result.target_platform == "windows"

    marker = "FakeProvider가 반환한 고정 응답"
    assert marker in result.dependency_report
    assert marker in result.build_spec
    assert marker in result.asset_manifest
    assert marker in result.installer_spec
    assert marker in result.platform_test_report  # Platform Tester narration


def test_run_build_workflow_saves_5_artifact_files(tmp_path: Path) -> None:
    """workflow_dir 주입 시 20_~24_ prefix 파일 5개가 디스크에 저장."""
    code_files = _make_minimal_code_files(tmp_path)

    workflow_dir = tmp_path / "outputs" / "workflow_test"
    result = run_build_workflow(
        code_files=code_files,
        user_request="검증용 요청",
        workflow_dir=workflow_dir,
        verbose=False,
    )

    expected_files = [
        "20_dependency_report.md",
        "21_build_spec.md",
        "22_asset_manifest.md",
        "23_installer_spec.md",
        "24_platform_test_report.md",
    ]
    for name in expected_files:
        assert (workflow_dir / name).exists(), f"{name} 가 저장되지 않았다"
    assert len(result.saved_files) == 5


def test_run_build_workflow_with_platform_test_disabled(tmp_path: Path) -> None:
    """`enable_platform_test=False` 면 Platform Tester skip 안내 문자열 포함."""
    code_files = _make_minimal_code_files(tmp_path)

    result = run_build_workflow(
        code_files=code_files,
        user_request="skip 검증",
        workflow_dir=tmp_path,
        enable_platform_test=False,
        verbose=False,
    )

    assert "SKIPPED" in result.platform_test_report
    assert "enable_platform_test=False" in result.platform_test_report


def test_run_build_workflow_handles_empty_code_files(tmp_path: Path) -> None:
    """code_files 비어 있어도 4-agent 사양 산출은 완주 — Platform Tester 만 sandbox skip."""
    result = run_build_workflow(
        code_files=[],
        user_request="빈 코드 시나리오",
        workflow_dir=tmp_path,
        enable_platform_test=True,
        verbose=False,
    )

    marker = "FakeProvider가 반환한 고정 응답"
    assert marker in result.dependency_report
    assert marker in result.build_spec
    assert marker in result.asset_manifest
    assert marker in result.installer_spec
    # Platform Tester narration 도 FakeProvider 응답 (sandbox 부재여도 Agent 자체는 호출됨)
    assert marker in result.platform_test_report


def test_build_workflow_result_dataclass_fields(tmp_path: Path) -> None:
    """BuildWorkflowResult 의 모든 핵심 필드 타입·기본값 sanity."""
    result = run_build_workflow(
        code_files=_make_minimal_code_files(tmp_path),
        user_request="필드 sanity",
        workflow_dir=tmp_path,
    )
    assert isinstance(result.dependency_report, str) and result.dependency_report
    assert isinstance(result.build_spec, str)
    assert isinstance(result.asset_manifest, str)
    assert isinstance(result.installer_spec, str)
    assert isinstance(result.platform_test_report, str)
    assert isinstance(result.saved_files, list)
    assert result.target_platform in {"windows", "macos", "linux", "cross-platform"}


# ---------------------------------------------------------------------------
# 직접 실행 경로 (실제 LLM)
# ---------------------------------------------------------------------------
def main() -> int:
    """실제 LLM 으로 5-agent 사슬 1바퀴."""
    console.print(Rule("[bold cyan]Build Workflow smoke — 5단 빌드 사슬[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_build_workflow",
        user_id="local-dev",
        metadata={"phase": "phase_4_5_workflow"},
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # 단일 파일 entry — sandbox 가 발견 가능
        p = tmp / "calculator.py"
        p.write_text("# file: calculator.py\nprint('hello build')\n", encoding="utf-8")

        result = run_build_workflow(
            code_files=[p],
            user_request="사칙연산 계산기 — 가족용 데스크톱",
            target_platform="windows",
            workflow_dir=tmp / "out",
            enable_platform_test=True,
            verbose=False,
        )

    console.print(
        Panel(
            f"[bold]target_platform[/bold]: {result.target_platform}\n"
            f"[bold]saved_files[/bold]: {len(result.saved_files)}개\n"
            f"[bold]dependency_report (앞 200자)[/bold]:\n{result.dependency_report[:200]}\n"
            f"[bold]build_spec (앞 200자)[/bold]:\n{result.build_spec[:200]}",
            title="[green]BuildWorkflowResult[/green]",
            border_style="green",
        )
    )
    monitor.end_trace()
    monitor.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
