# -*- coding: utf-8 -*-
"""
Nexus Alpha 인터랙티브 CLI (Phase 2-P5).

사용자 자연어 요청을 받아 라우터로 의도를 분류하고, 적절한 워크플로우로
디스패치하는 단일 엔트리. 진행 상황은 Rich 라이브러리의 status spinner로
표시하고, 산출물은 Panel로 요약 출력한다.

실행:
    .venv\\Scripts\\python.exe src\\ui\\cli.py                     # 인터랙티브
    .venv\\Scripts\\python.exe src\\ui\\cli.py --request "..."     # 1회 실행
    .venv\\Scripts\\python.exe -m src.ui.cli                       # module 형식

흐름:
    1. 사용자 입력 (인자 또는 Prompt)
    2. `route_request` 휴리스틱 분류 → RoutingDecision 표시
    3. 사용자 확인 (Y/n)
    4. 의도별 디스패치:
         - IMPLEMENTATION/ANALYSIS → `run_analyze_and_implement` 4-agent 실행
         - SEARCH → "Knowledge 검색 워크플로우 미구축" 안내
         - UNKNOWN → 명확화 질문 후 종료
    5. 산출물 미리보기 + 저장 경로 안내
"""

from __future__ import annotations

import argparse
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
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

load_dotenv(PROJECT_ROOT / ".env")

from src.workflows import Intent, RoutingDecision, route_request, run_analyze_and_implement


console = Console()


# ---------------------------------------------------------------------------
# UI 헬퍼
# ---------------------------------------------------------------------------
def _render_decision(decision: RoutingDecision) -> None:
    """RoutingDecision을 사용자가 한눈에 볼 수 있는 표 + 패널로 출력."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("k", style="bold cyan", justify="right")
    table.add_column("v")
    table.add_row("의도", f"{decision.intent.value}")
    table.add_row("신뢰도", f"{decision.confidence:.2f} / 1.00")
    table.add_row("권장 워크플로우", decision.recommended_workflow or "(없음)")
    table.add_row("근거", decision.reasoning)

    if decision.matched_keywords:
        keyword_lines = [
            f"  • {intent.value}: {', '.join(kws)}"
            for intent, kws in decision.matched_keywords.items()
        ]
        table.add_row("매칭 키워드", "\n".join(keyword_lines))

    console.print(Panel(table, title="[green]라우팅 결정[/green]", border_style="green"))


def _preview(text: str, limit: int = 600) -> str:
    """긴 결과물을 콘솔 패널용으로 축약."""
    stripped = (text or "").strip()
    if not stripped:
        return "(비어 있음)"
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "\n\n... (중략 — 전체는 outputs/ 에 저장됨) ..."


# ---------------------------------------------------------------------------
# 의도별 디스패처
# ---------------------------------------------------------------------------
def _dispatch_implementation_or_analysis(request: str) -> int:
    """`analyze_and_implement` 4-agent 워크플로우 실행."""
    if not Confirm.ask("이대로 4-agent 워크플로우(CTO→Analyst→Engineer→QA)를 실행할까요?", default=True):
        console.print("[yellow]취소되었습니다.[/yellow]")
        return 0

    try:
        with console.status("[yellow]4명 에이전트 협업 중... (수 분 소요)[/yellow]", spinner="dots"):
            result = run_analyze_and_implement(request, verbose=False)
    except Exception as exc:
        console.print(Panel(f"[bold red]실행 실패:[/bold red] {exc}", border_style="red"))
        return 1

    # 산출물 미리보기 (각 단계 1패널씩)
    console.print(Rule("[green]산출물 미리보기[/green]"))
    for title, body in (
        ("① CTO 전략", result.cto_strategy),
        ("② Data Analyst 분석 지시서", result.analyst_brief),
        ("③ Python Engineer 구현", result.engineer_output),
        ("④ Code Reviewer 정적 리뷰", result.qa_review),
    ):
        console.print(Panel(_preview(body), title=f"[green]{title}[/green]", border_style="green"))

    # 저장 경로 요약
    rel_saved = result.saved_dir.relative_to(PROJECT_ROOT)
    summary = (
        f"[bold]저장 디렉터리:[/bold] [cyan]{rel_saved}[/cyan]\n"
        f"[bold]추출된 코드 파일:[/bold] {len(result.saved_code_files)}개"
    )
    console.print(Panel(summary, title="[green]저장 완료[/green]", border_style="green"))
    return 0


def _dispatch_search(_request: str) -> int:
    """검색형 — Knowledge 검색 워크플로우는 아직 미구축."""
    console.print(
        Panel(
            "[yellow]검색형 의도가 감지되었지만, Knowledge 검색 워크플로우는 "
            "아직 별도 엔트리로 구축되지 않았습니다.[/yellow]\n\n"
            "현재 상태:\n"
            "  • [bold]Knowledge Curator[/bold] — `outputs/workflow_*` 색인 가능 (Phase 2-P3)\n"
            "  • [bold]RAG Searcher[/bold] — Curator entry 목록을 받으면 추천 가능\n"
            "  • [bold]미구축[/bold]: 디렉터리 자동 스캔 + 색인 일괄 적재 + 검색 진입점\n\n"
            "임시 해결책: `python src/tests/test_knowledge_agents.py` 로 두 에이전트의 "
            "단독 동작을 확인할 수 있습니다.\n"
            "후속 작업으로 본 워크플로우 구축이 필요합니다.",
            title="[yellow]지원 예정[/yellow]",
            border_style="yellow",
        )
    )
    return 0


def _dispatch_unknown(decision: RoutingDecision) -> int:
    """UNKNOWN — 사용자에게 명확화 요청."""
    console.print(
        Panel(
            f"[yellow]요청의 의도를 명확히 분류하지 못했습니다.[/yellow]\n\n"
            f"근거: {decision.reasoning}\n\n"
            "다음 중 어느 형태에 가까운지 다시 입력해 주세요:\n"
            "  • [bold]구현형[/bold]  예: '계산기를 만들어줘', 'Excel→PDF 스크립트 작성해줘'\n"
            "  • [bold]분석형[/bold]  예: '월별 매출을 분석해줘', '이상치를 찾아줘'\n"
            "  • [bold]검색형[/bold]  예: '이전에 만든 PDF 변환기를 찾아줘'",
            title="[yellow]명확화 필요[/yellow]",
            border_style="yellow",
        )
    )
    return 0


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Nexus Alpha CLI 메인 진입점."""
    parser = argparse.ArgumentParser(
        prog="nexus-alpha",
        description="Nexus Alpha — 자연어 요청을 받아 적절한 에이전트 워크플로우로 자동 분기 실행",
    )
    parser.add_argument(
        "--request", "-r",
        type=str,
        default=None,
        help="실행할 사용자 요청 (생략 시 인터랙티브 프롬프트가 뜸)",
    )
    args = parser.parse_args(argv)

    console.print(Rule("[bold cyan]Nexus Alpha CLI[/bold cyan]"))

    # 1) 요청 수집
    if args.request is not None:
        request = args.request.strip()
        console.print(Panel(request, title="[cyan]사용자 요청 (인자)[/cyan]", border_style="cyan"))
    else:
        request = Prompt.ask("[bold cyan]요청을 입력하세요[/bold cyan]").strip()

    if not request:
        console.print("[red]요청이 비어 있습니다. 종료합니다.[/red]")
        return 1

    # 2) 라우팅
    decision = route_request(request)
    _render_decision(decision)

    # 3) 의도별 디스패치
    if decision.intent in (Intent.IMPLEMENTATION, Intent.ANALYSIS):
        return _dispatch_implementation_or_analysis(request)
    if decision.intent == Intent.SEARCH:
        return _dispatch_search(request)
    return _dispatch_unknown(decision)


if __name__ == "__main__":
    sys.exit(main())
