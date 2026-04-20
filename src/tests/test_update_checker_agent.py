# -*- coding: utf-8 -*-
"""
Update Checker 에이전트 단독 smoke test (Phase 5 / v4 — 8/9).

검증 항목:
    1) `create_update_checker_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 자동 업데이트 모듈 사양 + 참조 구현 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    GitHub Releases endpoint + Windows + 코드 서명 미보유 시나리오. 보안 5원칙
    (HTTPS / TLS 검증 / 화이트리스트 / SHA256 검증 / 자동 적용 금지) 준수 사양 산출
    검증.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_update_checker_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_update_checker_agent.py -v
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

from src.agents.build_release import create_update_checker_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — GitHub Releases + Windows + 코드 서명 미보유
# ---------------------------------------------------------------------------
TASK_DESCRIPTION = (
    "아래 4블록을 입력으로, 백스토리에 명시된 5단 구조(동작 흐름 / 참조 구현 / "
    "메인 앱 통합 위치 / 보안 체크리스트 / 작성자 노트)로 한국어 자동 업데이트 "
    "모듈 사양을 작성하세요. **보안 5원칙 (HTTPS / TLS 검증 / 화이트리스트 / "
    "SHA256 검증 / 자동 적용 금지) 모두 준수해야 합니다.**\n\n"
    "[APP_METADATA]\n"
    "short_name: NexusCalc\n"
    "current_version: 0.3.0\n"
    "installer_path: dist/NexusCalc-0.3.0-setup.exe\n\n"
    "[UPDATE_ENDPOINT]\n"
    "https://api.github.com/repos/SongJongwon/nexus-alpha/releases/latest\n\n"
    "[TARGET_PLATFORM]\nwindows\n\n"
    "[SIGNING_AVAILABLE]\nno\n"
)

TASK_EXPECTED_OUTPUT = (
    "5단 구조의 한국어 자동 업데이트 모듈 사양 (동작 흐름 / 참조 구현 / 통합 / "
    "보안 체크리스트 / 노트). 마지막 줄 `Final Answer: updater module — "
    "endpoint=<도메인>, sha256_check=yes, signing_check=no, check_interval=24h`."
)


def main() -> int:
    """Update Checker 단독 실행 (실제 LLM)."""
    console.print(Rule("[bold cyan]Update Checker smoke — GitHub Releases endpoint[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_update_checker",
        user_id="local-dev",
        metadata={"phase": "phase_5", "agent": "update_checker"},
    )

    try:
        agent = create_update_checker_agent(verbose=False)
    except Exception as exc:
        console.print(Panel(f"[bold red]초기화 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent[/bold]: {agent.role}")
    console.print(
        f"[bold]LLM[/bold]: NexusAlphaLLM (backend={agent.llm.backend_provider.name})"
    )
    console.print(Rule())

    task = Task(description=TASK_DESCRIPTION, expected_output=TASK_EXPECTED_OUTPUT, agent=agent)
    try:
        with console.status("[yellow]Update Checker 사양 작성 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]자동 업데이트 모듈 사양[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_update_checker_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Update Checker 가 CrewAI 를 통과하는지 검증."""
    agent = create_update_checker_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Update Checker kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
