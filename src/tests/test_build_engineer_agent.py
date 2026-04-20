# -*- coding: utf-8 -*-
"""
Build Engineer 에이전트 단독 smoke test (Phase 4.5 / v4).

검증 항목:
    1) `create_build_engineer_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 빌드 사양 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [PROJECT_LAYOUT] + [DEPENDENCY_REPORT] + [TARGET_PLATFORM] +
    [ENTRY_POINT] 4 블록을 입력으로 주고, 5단 구조(도구 선택 / 빌드 명령 /
    함정 / 검증 체크리스트 / 노트) 산출 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_build_engineer_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_build_engineer_agent.py -v
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

from src.agents.build_release import create_build_engineer_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 입력 — 가상의 4블록
# ---------------------------------------------------------------------------
SAMPLE_PROJECT_LAYOUT = """\
src/calc/__init__.py
src/calc/__main__.py     # 진입점
src/calc/core.py         # 사칙연산 로직
src/calc/gui.py          # tkinter 윈도우
"""

SAMPLE_DEPENDENCY_REPORT = """\
direct_dependencies:
  - tkinter (stdlib)
  - customtkinter >=5.2
hidden_imports:
  - module: customtkinter.windows.widgets.theme
    reason: "lazy import in customtkinter.CTk()"
    severity: must
data_files:
  - src: customtkinter/assets/themes
    dest: customtkinter/assets/themes
    purpose: "기본 테마 JSON — 실행 시 로드"
native_binaries: []
license_warnings: []
os_specific: []
unverified_areas:
  - 사용자가 추가할 수 있는 동적 plugin 경로
"""

SAMPLE_TARGET_PLATFORM = "windows"
SAMPLE_ENTRY_POINT = "src/calc/__main__.py"

TASK_DESCRIPTION = (
    "아래 4블록을 입력으로, 백스토리에 명시된 5단 구조(도구 선택 / 빌드 명령 / "
    "함정 / 검증 체크리스트 / 빌드 엔지니어 노트)로 한국어 빌드 사양을 작성하세요.\n\n"
    f"[PROJECT_LAYOUT]\n{SAMPLE_PROJECT_LAYOUT}\n\n"
    f"[DEPENDENCY_REPORT]\n```yaml\n{SAMPLE_DEPENDENCY_REPORT}\n```\n\n"
    f"[TARGET_PLATFORM]\n{SAMPLE_TARGET_PLATFORM}\n\n"
    f"[ENTRY_POINT]\n{SAMPLE_ENTRY_POINT}\n"
)

TASK_EXPECTED_OUTPUT = (
    "5단 구조의 한국어 빌드 사양 (도구 선택 / 빌드 명령 / 함정 / 검증 / 노트). "
    "마지막 줄 `Final Answer: tool=..., mode=..., hidden_imports=N개, est_size=~ZMB`."
)


def main() -> int:
    """Build Engineer 단독 실행 (실제 LLM)."""
    console.print(
        Rule("[bold cyan]Build Engineer smoke — 의존성 보고서 → 빌드 사양[/bold cyan]")
    )

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_build_engineer",
        user_id="local-dev",
        metadata={"phase": "phase_4_5", "agent": "build_engineer"},
    )

    try:
        agent = create_build_engineer_agent(verbose=False)
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
        with console.status("[yellow]Build Engineer 사양 작성 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]빌드 사양[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_build_engineer_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Build Engineer 가 CrewAI 를 통과하는지 검증."""
    agent = create_build_engineer_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Build Engineer kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
