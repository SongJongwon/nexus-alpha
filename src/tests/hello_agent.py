# -*- coding: utf-8 -*-
"""
Hello Agent 테스트 스크립트 (Provider + LangFuse 모니터링 버전)
================================================================

목적:
    `src.llm` Provider 시스템과 `src.monitoring` LangFuse 통합이 동시에
    동작하는지 가장 단순한 방식으로 검증한다. factory가 반환한 Provider로
    Claude를 호출하고, 한국어 인사·자기소개를 받아 rich 콘솔에 출력하며,
    전체 흐름을 LangFuse trace로 기록한다.

전환 방법:
    `.env`의 `LLM_PROVIDER` 값만 바꾸면 된다.
      - `LLM_PROVIDER=agent_sdk`  → Claude Code MAX 구독 사용 (기본, 무료)
      - `LLM_PROVIDER=api_key`    → Anthropic API Key 사용 (.env의 ANTHROPIC_API_KEY 필요)

모니터링:
    `.env`의 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`가 설정되어 있으면
    이 실행 전체가 LangFuse에 trace로 기록된다. 키가 없으면 자동으로
    모니터링이 비활성화되고, 메인 로직은 정상 실행된다.

실행 방법:
    프로젝트 루트(C:\\projects\\nexus-alpha)에서 아래 중 하나를 실행:
      .venv\\Scripts\\python.exe src\\tests\\hello_agent.py
      # 또는
      .venv\\Scripts\\python.exe -m src.tests.hello_agent
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows 콘솔(cp949)에서도 한글/이모지를 안전하게 출력하기 위한 가드.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# `python src/tests/hello_agent.py`로 직접 실행할 때도 `src.*` 를 찾을 수 있도록
# 프로젝트 루트를 sys.path에 추가한다. (src/tests/hello_agent.py 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import anyio
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

# .env를 먼저 로드해야 Provider/모니터링이 올바른 키로 초기화된다.
load_dotenv(PROJECT_ROOT / ".env")

from src.llm import get_llm_provider
from src.monitoring import get_langfuse_client


CONFIG: dict = {
    "agent_name": "HelloAgent",
    "agent_role": "인사하는 AI 비서",
    "trace_name": "hello_agent_test",
    "system_prompt": (
        "당신은 Nexus Alpha RPA 프로젝트의 HelloAgent입니다. "
        "따뜻하고 정중한 한국어 어조로 대답합니다."
    ),
    "task_prompt": (
        "한국어로 따뜻하게 인사하고, 당신이 어떤 에이전트인지 간단히 자기소개해 주세요. "
        "분량은 3~5문장으로 유지합니다."
    ),
}


console = Console()


async def run_hello_agent() -> int:
    """Provider 호출 흐름 전체를 LangFuse trace로 묶어 실행한다.

    Returns:
        성공 시 0, 실패 시 1. (`anyio.run`으로 감싸져 `sys.exit`에 전달됨)
    """
    console.print(Rule("[bold cyan]Hello Agent Test — Provider + LangFuse[/bold cyan]"))

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )

    # 1) trace 시작 — 이후 Provider 내부 generation은 이 trace에 매달린다.
    monitor.log_trace(
        name=CONFIG["trace_name"],
        user_id="local-dev",
        metadata={
            "phase": "phase_0",
            "agent_name": CONFIG["agent_name"],
            "agent_role": CONFIG["agent_role"],
        },
    )

    try:
        provider = get_llm_provider()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Provider 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Provider :[/bold] {provider.name}")
    console.print(
        f"[bold]Agent    :[/bold] {CONFIG['agent_name']} — {CONFIG['agent_role']}"
    )
    console.print(Rule())

    exit_code = 0
    try:
        with console.status(
            "[yellow]HelloAgent 응답 생성 중...[/yellow]", spinner="dots"
        ):
            text = await provider.generate(
                prompt=CONFIG["task_prompt"],
                system=CONFIG["system_prompt"],
            )
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]생성 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        exit_code = 1
    else:
        if not text.strip():
            console.print(
                Panel(
                    "[yellow]응답이 비어 있습니다. Provider 구현을 확인하세요.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1
        else:
            console.print(
                Panel(
                    text,
                    title=f"[green]{CONFIG['agent_name']} 응답[/green]",
                    border_style="green",
                )
            )

    # 2) trace 종료 + 버퍼 flush
    monitor.end_trace()
    monitor.flush()

    # 3) 대시보드 안내
    if monitor.enabled:
        console.print(Rule())
        console.print(
            Panel(
                f"실행 기록이 LangFuse로 전송되었습니다.\n"
                f"대시보드에서 확인하세요:\n"
                f"  [cyan]{monitor.host}[/cyan]\n"
                f"(이벤트가 대시보드에 반영되기까지 몇 초가 걸릴 수 있습니다.)",
                title="[green]LangFuse 모니터링[/green]",
                border_style="green",
            )
        )

    return exit_code


def main() -> int:
    """동기 진입점 — anyio로 비동기 코루틴을 실행한다."""
    return anyio.run(run_hello_agent)


if __name__ == "__main__":
    sys.exit(main())
