# -*- coding: utf-8 -*-
"""
Distribution Agent 단독 smoke test (Phase 5 / v4 — 9/9 마지막).

검증 항목:
    1) `create_distribution_agent_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 배포 사양(채널 + 업로드 명령 + URL 패턴) 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    GitHub Releases 1순위 시나리오 — public repo + 코드 서명 미보유 + Windows.
    채널 선택 + gh CLI 자동화 + SmartScreen 안내 + SHA256 동봉 검증.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_distribution_agent_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_distribution_agent_agent.py -v
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

from src.agents.build_release import create_distribution_agent_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — GitHub Releases / public repo / 코드 서명 미보유 / Windows
# ---------------------------------------------------------------------------
TASK_DESCRIPTION = (
    "아래 5블록을 입력으로, 백스토리에 명시된 5단 구조(채널 선택 / 업로드 명령 / "
    "다운로드 URL+SHA256 / Update Checker endpoint 권고 / 배포 노트)로 한국어 "
    "배포 사양을 작성하세요. **GitHub Releases 1순위 권장 + 코드 서명 미보유라 "
    "SmartScreen 안내 포함, SHA256 manifest 동봉 필수.**\n\n"
    "[BUILD_ARTIFACT]\n"
    "filename: NexusCalc-0.3.0-setup.exe\n"
    "size: ~28MB\n"
    "platform: windows\n\n"
    "[VERSION]\n"
    "version: 0.3.0 / git_tag: v0.3.0 / bump: minor\n\n"
    "[REPO_URL]\n"
    "https://github.com/SongJongwon/nexus-alpha\n\n"
    "[SIGNING_AVAILABLE]\nno\n\n"
    "[PRIVACY_LEVEL]\npublic\n"
)

TASK_EXPECTED_OUTPUT = (
    "5단 구조의 한국어 배포 사양 (채널 선택 / 업로드 명령 (gh CLI) / 다운로드 URL "
    "테이블 + SHA256 + SmartScreen 안내 / Update Checker endpoint 권고 / 배포 노트). "
    "마지막 줄 `Final Answer: channel=github_releases, url_template=github.com, "
    "signed=no, sha256_in_manifest=yes`."
)


def main() -> int:
    """Distribution Agent 단독 실행 (실제 LLM)."""
    console.print(Rule("[bold cyan]Distribution Agent smoke — GitHub Releases 1순위[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_distribution_agent",
        user_id="local-dev",
        metadata={"phase": "phase_5", "agent": "distribution_agent"},
    )

    try:
        agent = create_distribution_agent_agent(verbose=False)
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
        with console.status(
            "[yellow]Distribution Agent 사양 작성 중...[/yellow]", spinner="dots"
        ):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]배포 사양[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_distribution_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Distribution Agent 가 CrewAI 를 통과하는지 검증."""
    agent = create_distribution_agent_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Distribution Agent kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
