# -*- coding: utf-8 -*-
"""
Release Manager 에이전트 단독 smoke test (Phase 5 / v4 — 6/9).

검증 항목:
    1) `create_release_manager_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 SemVer 결정 + RELEASE.md 초안 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [PREVIOUS_VERSION] + [CHANGE_SUMMARY] + [BREAKING_FLAGS] +
    [BUILD_RESULT] + [TARGET_PLATFORM] 5블록 입력. minor bump 시나리오
    (0.2.0 → 0.3.0, breaking 없음).

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_release_manager_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_release_manager_agent.py -v
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

from src.agents.build_release import create_release_manager_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — 0.2.0 → 0.3.0 (minor bump, breaking 없음)
# ---------------------------------------------------------------------------
TASK_DESCRIPTION = (
    "아래 5블록을 입력으로, 백스토리에 명시된 4단 구조(버전 결정 / RELEASE.md "
    "초안 / 사용자 친화 요약 / 매니저 노트)로 한국어 릴리스 결정을 작성하세요. "
    "Breaking 없는 신규 기능 추가 시나리오 — minor bump 권장.\n\n"
    "[PREVIOUS_VERSION]\n0.2.0\n\n"
    "[CHANGE_SUMMARY]\n"
    "- 사칙연산에 % (퍼센트) 연산 추가\n"
    "- 키보드 단축키(Enter, Backspace) 지원\n"
    "- 다크 모드 토글 추가\n"
    "- 0으로 나누기 시 토스트 메시지 표시\n\n"
    "[BREAKING_FLAGS]\nnone\n\n"
    "[BUILD_RESULT]\n"
    "tool=pyinstaller, mode=onefile, hidden_imports=2개, est_size=~28MB\n\n"
    "[TARGET_PLATFORM]\nwindows\n"
)

TASK_EXPECTED_OUTPUT = (
    "4단 구조의 한국어 릴리스 결정 (버전 결정 / RELEASE.md / 사용자 요약 / 노트). "
    "마지막 줄 `Final Answer: version=0.3.0, bump=minor, tag=v0.3.0`."
)


def main() -> int:
    """Release Manager 단독 실행 (실제 LLM)."""
    console.print(Rule("[bold cyan]Release Manager smoke — 0.2.0 → 0.3.0 minor bump[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_release_manager",
        user_id="local-dev",
        metadata={"phase": "phase_5", "agent": "release_manager"},
    )

    try:
        agent = create_release_manager_agent(verbose=False)
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
        with console.status("[yellow]Release Manager 결정 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]릴리스 결정[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_release_manager_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Release Manager 가 CrewAI 를 통과하는지 검증."""
    agent = create_release_manager_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Release Manager kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
