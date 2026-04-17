# -*- coding: utf-8 -*-
"""
Hello Agent 테스트 스크립트 (Provider 시스템 버전)
====================================================

목적:
    `src.llm` Provider 시스템이 정상 동작하는지 가장 단순한 방식으로 검증한다.
    factory가 반환한 Provider로 Claude를 호출하고, 한국어 인사·자기소개를
    받아서 rich 콘솔에 출력한다.

전환 방법:
    `.env`의 `LLM_PROVIDER` 값만 바꾸면 된다.
      - `LLM_PROVIDER=agent_sdk`  → Claude Code MAX 구독 사용 (기본, 무료)
      - `LLM_PROVIDER=api_key`    → Anthropic API Key 사용 (.env의 ANTHROPIC_API_KEY 필요)

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

# `python src/tests/hello_agent.py`로 직접 실행할 때도 `src.llm`을 찾을 수 있도록
# 프로젝트 루트를 sys.path에 추가한다. (src/tests/hello_agent.py 기준 2단계 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import anyio
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from src.llm import get_llm_provider

# 프로젝트 루트의 .env를 로드 (factory가 LLM_PROVIDER를 읽기 전에 필요)
load_dotenv(PROJECT_ROOT / ".env")


CONFIG: dict = {
    "agent_name": "HelloAgent",
    "agent_role": "인사하는 AI 비서",
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
    """Provider를 통해 HelloAgent를 실행하고 결과를 콘솔에 출력한다.

    Returns:
        성공 시 0, 실패 시 1. (`anyio.run`으로 감싸져 `sys.exit`에 전달됨)
    """
    console.print(Rule("[bold cyan]Hello Agent Test — Provider 시스템[/bold cyan]"))

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
        return 1

    console.print(f"[bold]Provider:[/bold] {provider.name}")
    console.print(
        f"[bold]Agent   :[/bold] {CONFIG['agent_name']} — {CONFIG['agent_role']}"
    )
    console.print(Rule())

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
        return 1

    if not text.strip():
        console.print(
            Panel(
                "[yellow]응답이 비어 있습니다. Provider 구현을 확인하세요.[/yellow]",
                title="경고",
                border_style="yellow",
            )
        )
        return 1

    console.print(
        Panel(
            text,
            title=f"[green]{CONFIG['agent_name']} 응답[/green]",
            border_style="green",
        )
    )
    return 0


def main() -> int:
    """동기 진입점 — anyio로 비동기 코루틴을 실행한다."""
    return anyio.run(run_hello_agent)


if __name__ == "__main__":
    sys.exit(main())
