# -*- coding: utf-8 -*-
"""
analyze_and_implement 워크플로우 엔드투엔드 smoke test.

단일 사용자 요청을 입력해 CTO → Data Analyst → Python Engineer 체인이
순차적으로 동작하고, 최종 산출물이 `outputs/workflow_<ts>/`에 저장되는지
확인한다. LangFuse에는 `analyze_and_implement` trace 1건 아래에 3개의
generation이 함께 기록된다.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_workflow_analyze_and_implement.py
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
from src.workflows import run_analyze_and_implement


console = Console()


USER_REQUEST = (
    "매장별 월간 매출 Excel 파일을 분석하여 핵심 KPI 대시보드와 "
    "PDF 보고서를 자동으로 생성하는 Python 스크립트를 만들어줘. "
    "매장 수는 10개 내외이고, 월별로 제품 카테고리별 매출·주문수·반품수가 "
    "담긴 .xlsx가 매월 업데이트된다. "
    "경영진이 한 눈에 실적 변화와 이상 신호를 파악할 수 있도록 해 줘."
)


def _preview(text: str, limit: int = 800) -> str:
    """긴 결과물을 콘솔 패널용으로 축약한다."""
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped or "(비어 있음)"
    return stripped[:limit] + "\n\n... (중략 — 전체는 outputs/에 저장됨) ..."


def main() -> int:
    """워크플로우 실행 후 각 에이전트의 결과 preview와 저장 경로를 출력한다."""
    console.print(
        Rule(
            "[bold cyan]analyze_and_implement 엔드투엔드 smoke test[/bold cyan]"
        )
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    console.print(
        Panel(
            USER_REQUEST,
            title="[cyan]사용자 요청[/cyan]",
            border_style="cyan",
        )
    )
    console.print(Rule())

    try:
        with console.status(
            "[yellow]3명 에이전트 협업 중... (3단계 순차 실행, 몇 분 소요)[/yellow]",
            spinner="dots",
        ):
            result = run_analyze_and_implement(
                USER_REQUEST,
                verbose=False,  # 콘솔 노이즈 억제 — 상세 로그는 LangFuse 참조
            )
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]워크플로우 실행 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        return 1

    # 각 에이전트의 산출물 preview
    console.print(
        Panel(
            _preview(result.cto_strategy),
            title="[green]① CTO 전략 문서 (preview)[/green]",
            border_style="green",
        )
    )
    console.print(
        Panel(
            _preview(result.analyst_brief),
            title="[green]② Data Analyst 분석 지시서 (preview)[/green]",
            border_style="green",
        )
    )
    console.print(
        Panel(
            _preview(result.engineer_output),
            title="[green]③ Python Engineer 구현 산출물 (preview)[/green]",
            border_style="green",
        )
    )
    console.print(
        Panel(
            _preview(result.qa_review),
            title="[green]④ Code Reviewer 정적 리뷰 (preview)[/green]",
            border_style="green",
        )
    )

    # 저장 경로 요약
    rel_saved = result.saved_dir.relative_to(PROJECT_ROOT)
    file_list_lines = [f"[bold]저장 디렉터리:[/bold] [cyan]{rel_saved}[/cyan]"]
    file_list_lines.append(
        f"[bold]추출된 코드 파일:[/bold] {len(result.saved_code_files)}개"
    )
    for p in result.saved_code_files[:12]:
        file_list_lines.append(f"  - [cyan]{p.relative_to(PROJECT_ROOT)}[/cyan]")
    if len(result.saved_code_files) > 12:
        file_list_lines.append(
            f"  ... 외 {len(result.saved_code_files) - 12}개"
        )

    console.print(
        Panel(
            "\n".join(file_list_lines),
            title="[green]산출물 저장[/green]",
            border_style="green",
        )
    )

    if monitor.enabled:
        console.print(Rule())
        console.print(
            Panel(
                f"LangFuse 대시보드: [cyan]{monitor.host}[/cyan]\n"
                f"(trace: [bold]analyze_and_implement[/bold] — 아래에 4개 "
                f"generation이 함께 기록됩니다.)",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_run_analyze_and_implement_produces_four_stage_artifacts(tmp_path) -> None:
    """4명 체인 워크플로우가 FakeProvider로 완주하고 산출물 디렉터리가 생기는지 검증.

    Phase 2-P2에서 Code Reviewer가 4번째 단계로 추가됨. `tmp_path`로 `outputs_dir`을
    격리해 저장소에 쓰레기 디렉터리가 남지 않도록 한다. FakeProvider는 4번의 Task
    각각에 동일한 "Final Answer: ..." 응답을 돌려주므로, 4개 md 산출물(cto/analyst/
    engineer/qa)이 모두 동일한 표지 문자열을 포함해야 한다.
    """
    result = run_analyze_and_implement(
        "pytest 하네스 smoke test용 더미 요청",
        outputs_dir=tmp_path,
        verbose=False,
    )

    assert result.saved_dir.exists() and result.saved_dir.is_dir()
    assert result.saved_dir.parent == tmp_path

    for filename in (
        "00_user_request.txt",
        "01_cto_strategy.md",
        "02_analyst_brief.md",
        "03_engineer_output.md",
        "04_qa_review.md",
    ):
        assert (result.saved_dir / filename).exists(), f"{filename} 가 저장되지 않았다"

    marker = "FakeProvider가 반환한 고정 응답"
    assert marker in result.cto_strategy
    assert marker in result.analyst_brief
    assert marker in result.engineer_output
    assert marker in result.qa_review

    # Phase 4 신규 필드 — backward compat 기본값 확인 (enable_gui_branch=False)
    assert result.chosen_path == ""  # Phase 4 미활성 시 빈 문자열
    assert result.ui_spec == ""
    assert result.gui_design == ""
    assert result.design_tokens == ""
    assert result.gui_code_output == ""


# ---------------------------------------------------------------------------
# Phase 4 — 파서 단위 테스트 (LLM 무관)
# ---------------------------------------------------------------------------
def test_parse_ui_ux_path_gui_via_final_answer() -> None:
    from src.workflows.analyze_and_implement import _parse_ui_ux_path

    md = "## UI/UX 분석\n... 일부 본문 ...\nFinal Answer: form_factor=single_window, complexity=simple, need_gui=yes\n"
    assert _parse_ui_ux_path(md) == "gui"


def test_parse_ui_ux_path_cli_via_final_answer() -> None:
    from src.workflows.analyze_and_implement import _parse_ui_ux_path

    md = "Final Answer: form_factor=cli, complexity=simple, need_gui=no\n"
    assert _parse_ui_ux_path(md) == "cli"


def test_parse_ui_ux_path_gui_via_yaml_body() -> None:
    """Final Answer 줄이 없어도 YAML 본문에서 need_gui: yes 인식."""
    from src.workflows.analyze_and_implement import _parse_ui_ux_path

    md = "```yaml\nneed_gui: yes\nform_factor: dashboard\ncomplexity: medium\n```\n"
    assert _parse_ui_ux_path(md) == "gui"


def test_parse_ui_ux_path_fallback_to_cli_when_unknown() -> None:
    """모호하거나 신호가 없으면 안전한 cli 로 fallback (비싼 GUI 사슬 회피)."""
    from src.workflows.analyze_and_implement import _parse_ui_ux_path

    assert _parse_ui_ux_path("") == "cli"
    assert _parse_ui_ux_path("Final Answer: 이것은 FakeProvider가 반환한 고정 응답입니다.") == "cli"
    assert _parse_ui_ux_path("어떤 임의 텍스트") == "cli"


# ---------------------------------------------------------------------------
# Phase 4 — enable_gui_branch=True E2E (FakeProvider → CLI 경로 fallback)
# ---------------------------------------------------------------------------
def test_run_with_build_branch_enabled_appends_build_artifacts(tmp_path) -> None:
    """`enable_build_branch=True` (기본 GUI 비활성) → 메인 4-agent 후 빌드 5단 사슬
    실행 → WorkflowResult 의 build 필드 5종 + 산출 파일 20~24 채워짐.

    검증:
        - 기존 4단 산출(00~04)도 그대로 존재 (backward compat)
        - 새 5필드(dependency_report/build_spec/asset_manifest/installer_spec/
          platform_test_report) 모두 marker 포함
        - 산출 파일 20_~24_ prefix 5개 디스크에 존재
    """
    result = run_analyze_and_implement(
        "Phase 4.5 빌드 통합 검증 — FakeProvider",
        outputs_dir=tmp_path,
        verbose=False,
        enable_build_branch=True,
    )

    marker = "FakeProvider가 반환한 고정 응답"
    # 기존 4-agent 산출 보존
    assert marker in result.cto_strategy
    assert marker in result.engineer_output
    assert marker in result.qa_review
    # Phase 4.5 신규 5 필드
    assert marker in result.dependency_report
    assert marker in result.build_spec
    assert marker in result.asset_manifest
    assert marker in result.installer_spec
    assert marker in result.platform_test_report
    # 산출 파일 — 기존 + 신규
    assert (result.saved_dir / "01_cto_strategy.md").exists()
    assert (result.saved_dir / "04_qa_review.md").exists()
    for name in (
        "20_dependency_report.md",
        "21_build_spec.md",
        "22_asset_manifest.md",
        "23_installer_spec.md",
        "24_platform_test_report.md",
    ):
        assert (result.saved_dir / name).exists(), f"{name} 가 저장되지 않았다"


def test_run_with_gui_branch_enabled_falls_back_to_cli(tmp_path) -> None:
    """`enable_gui_branch=True` + FakeProvider 응답에 need_gui 마커 없음
    → 파서가 cli 로 안전 fallback → Engineer 가 그대로 실행되되 UI/UX 컨텍스트
    가 추가로 채워진 결과 반환.

    검증:
        - chosen_path == "cli"
        - ui_spec 비어 있지 않음 (UI/UX Analyst 가 실행됨)
        - engineer_output 비어 있지 않음 (CLI 경로라 Engineer 그대로)
        - gui_* 필드는 빈 문자열 (GUI 경로 미실행)
        - 10_ui_ux_spec.md 파일 존재
        - 11~13 GUI 파일은 존재하지 않음 (CLI 경로라 미생성)
    """
    result = run_analyze_and_implement(
        "FakeProvider 시나리오 — GUI 분기 활성, but need_gui 마커 없음 → cli fallback",
        outputs_dir=tmp_path,
        verbose=False,
        enable_gui_branch=True,
    )

    assert result.chosen_path == "cli"
    assert result.ui_spec.strip()  # UI/UX Analyst 산출 채워짐
    assert "FakeProvider가 반환한 고정 응답" in result.ui_spec
    assert result.engineer_output.strip()  # Engineer 가 실행됨
    assert result.gui_design == ""  # GUI 경로 미실행
    assert result.design_tokens == ""
    assert result.gui_code_output == ""

    # 파일 시스템 확인
    assert (result.saved_dir / "10_ui_ux_spec.md").exists()
    assert (result.saved_dir / "03_engineer_output.md").exists()  # CLI 경로 — Engineer 산출 보존
    # GUI 전용 파일은 미생성
    assert not (result.saved_dir / "11_gui_design.md").exists()
    assert not (result.saved_dir / "12_design_tokens.md").exists()
    assert not (result.saved_dir / "13_gui_code_output.md").exists()


if __name__ == "__main__":
    sys.exit(main())
