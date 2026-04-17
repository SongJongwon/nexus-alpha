# -*- coding: utf-8 -*-
"""
CTO 에이전트 단독 smoke test.

검증 항목:
    1) `create_cto_agent()`가 `NexusAlphaLLM`을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew`로 단일 Task를 실행할 때 전략 문서가 산출되는지
    3) 실행 전체가 LangFuse에 `test_cto_agent` trace로 기록되는지

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_cto_agent.py
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

from crewai import Crew, Task

from src.agents.c_level import create_cto_agent
from src.monitoring import get_langfuse_client


console = Console()


TASK_DESCRIPTION = (
    "Excel 파일을 PDF 보고서로 변환하는 Python 스크립트가 필요합니다. "
    "다음 네 가지를 모두 한국어로 정리해 주세요:\n"
    "  1. 권장 기술 스택 (라이브러리 3개 이상)\n"
    "  2. 구현 접근 방법 (단계별 절차)\n"
    "  3. 예상 리스크와 대응 방안\n"
    "  4. 권장 작업 순서 (엔지니어에게 전달할 체크리스트 형태)"
)

TASK_EXPECTED_OUTPUT = (
    "기술 스택 / 구현 접근 / 리스크 / 권장 순서 네 섹션으로 구성된 한국어 전략 문서"
)


def main() -> int:
    """CTO 에이전트를 실행하고 종료 코드를 반환한다."""
    console.print(
        Rule("[bold cyan]CTO Agent smoke test — Excel → PDF 전략[/bold cyan]")
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    monitor.log_trace(
        name="test_cto_agent",
        user_id="local-dev",
        metadata={
            "phase": "phase_1",
            "agent": "cto",
            "scenario": "excel_to_pdf",
        },
    )

    try:
        cto = create_cto_agent()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]CTO 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent    :[/bold] {cto.role}")
    console.print(
        f"[bold]LLM      :[/bold] NexusAlphaLLM "
        f"(backend={cto.llm.backend_provider.name})"
    )
    console.print(Rule())

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=cto,
    )
    crew = Crew(agents=[cto], tasks=[task], verbose=False)

    exit_code = 0
    try:
        with console.status(
            "[yellow]CTO가 기술 전략을 작성 중...[/yellow]", spinner="dots"
        ):
            result = crew.kickoff()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Crew 실행 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        exit_code = 1
    else:
        # CrewAI 버전에 따라 kickoff() 반환은 CrewOutput 또는 str.
        output_text = getattr(result, "raw", None) or str(result)
        if not output_text.strip():
            console.print(
                Panel(
                    "[yellow]CTO 응답이 비어 있습니다.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1
        else:
            console.print(
                Panel(
                    output_text,
                    title="[green]CTO 전략 문서[/green]",
                    border_style="green",
                )
            )

    monitor.end_trace()
    monitor.flush()

    if monitor.enabled:
        console.print(Rule())
        console.print(
            Panel(
                f"실행 기록이 LangFuse로 전송되었습니다.\n"
                f"대시보드: [cyan]{monitor.host}[/cyan]\n"
                f"(trace: [bold]test_cto_agent[/bold])",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
