# -*- coding: utf-8 -*-
"""
Asset Manager 에이전트 단독 smoke test (Phase 4.5 / v4).

검증 항목:
    1) `create_asset_manager_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 자원 매니페스트 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [USER_REQUEST] + [PROJECT_LAYOUT] + [DESIGN_TOKENS] + [TARGET_PLATFORM]
    + [PROVIDED_ASSETS] 5블록을 입력. 사용자가 자원을 직접 안 준 케이스를 의도적
    으로 시나리오에 넣어, placeholder 사용 + 사후 교체 권고가 노트에 나오는지 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_asset_manager_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_asset_manager_agent.py -v
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

from src.agents.build_release import create_asset_manager_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — 자원 부재 케이스 (placeholder 동작 검증)
# ---------------------------------------------------------------------------
SAMPLE_USER_REQUEST = (
    "사칙연산 계산기 만들어줘. 가족용 — 더블클릭으로 바로 실행."
)

SAMPLE_PROJECT_LAYOUT = """\
src/calc/__init__.py
src/calc/__main__.py
src/calc/gui.py
src/calc/core.py
"""

SAMPLE_DESIGN_TOKENS = """\
{
  "theme_strategy": "native",
  "palette": {"primary": "#0078D4", "surface": "#FFFFFF", "on_surface": "#1F1F1F"},
  "typography": {"family_korean": "Pretendard"}
}
"""

TASK_DESCRIPTION = (
    "아래 5블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 매니페스트 + 처리 "
    "지시 + 매니저 노트)로 한국어 자원 매니페스트를 작성하세요. 사용자가 자원을 "
    "안 준 항목은 placeholder 로 채우고 사후 교체 권고를 노트에 명시하세요.\n\n"
    f"[USER_REQUEST]\n{SAMPLE_USER_REQUEST}\n\n"
    f"[PROJECT_LAYOUT]\n{SAMPLE_PROJECT_LAYOUT}\n\n"
    f"[DESIGN_TOKENS]\n```json\n{SAMPLE_DESIGN_TOKENS}\n```\n\n"
    f"[TARGET_PLATFORM]\nwindows\n\n"
    f"[PROVIDED_ASSETS]\nnone   # 사용자가 자원 미제공 — placeholder 처리 검증\n"
)

TASK_EXPECTED_OUTPUT = (
    "YAML 매니페스트(app_metadata/icons/fonts/images/locales/legal_texts) + 자원 "
    "처리 지시 + 매니저 노트 3단 구조. 마지막 줄 `Final Answer: assets — icons=N개, "
    "fonts=M개, images=I개, locales=L개, legal=L2개`."
)


def main() -> int:
    """Asset Manager 단독 실행 (실제 LLM)."""
    console.print(
        Rule("[bold cyan]Asset Manager smoke — 자원 부재 → placeholder 매니페스트[/bold cyan]")
    )

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_asset_manager",
        user_id="local-dev",
        metadata={"phase": "phase_4_5", "agent": "asset_manager"},
    )

    try:
        agent = create_asset_manager_agent(verbose=False)
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
        with console.status("[yellow]Asset Manager 매니페스트 작성 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]자원 매니페스트[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_asset_manager_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Asset Manager 가 CrewAI 를 통과하는지 검증."""
    agent = create_asset_manager_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Asset Manager kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
