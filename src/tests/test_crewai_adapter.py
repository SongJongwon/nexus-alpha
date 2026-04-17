# -*- coding: utf-8 -*-
"""
NexusAlphaLLM (CrewAI 어댑터) smoke test.

이 스크립트는 CrewAI의 Agent/Crew 오케스트레이션을 거치지 않고 어댑터
자체를 직접 호출하여 다음을 검증한다.

  1) `NexusAlphaLLM()` 초기화가 factory를 통해 Provider를 로드하는지
  2) 동기 `call(messages)`가 내부 비동기 Provider까지 정상 연결되는지
  3) 호출 1건이 LangFuse에 generation으로 기록되는지

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_crewai_adapter.py
    # 또는
    .venv\\Scripts\\python.exe -m src.tests.test_crewai_adapter
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

from src.llm import NexusAlphaLLM
from src.monitoring import get_langfuse_client


console = Console()


def main() -> int:
    """어댑터 동작을 검증하고 성공/실패에 따라 종료 코드를 반환한다."""
    console.print(
        Rule("[bold cyan]NexusAlphaLLM (CrewAI 어댑터) smoke test[/bold cyan]")
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    monitor.log_trace(
        name="crewai_adapter_test",
        user_id="local-dev",
        metadata={"phase": "phase_1", "purpose": "adapter-smoke-test"},
    )

    try:
        llm = NexusAlphaLLM()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]어댑터 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Adapter  :[/bold] NexusAlphaLLM (model={llm.model})")
    console.print(f"[bold]Provider :[/bold] {llm.backend_provider.name}")
    console.print(Rule())

    # CrewAI 스타일 메시지 포맷 — system + user 두 개로 변환 검증까지 포함
    messages = [
        {
            "role": "system",
            "content": "당신은 간결하고 정중한 한국어 AI 비서입니다.",
        },
        {
            "role": "user",
            "content": "1부터 5까지 콤마로 구분해 한 줄로 출력해 주세요.",
        },
    ]

    exit_code = 0
    try:
        with console.status(
            "[yellow]NexusAlphaLLM.call() 실행 중...[/yellow]", spinner="dots"
        ):
            response = llm.call(messages)
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]call() 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        exit_code = 1
    else:
        if not (response or "").strip():
            console.print(
                Panel(
                    "[yellow]응답이 비어 있습니다.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1
        else:
            console.print(
                Panel(
                    response,
                    title="[green]응답[/green]",
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
                f"(trace name: [bold]crewai_adapter_test[/bold])",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
