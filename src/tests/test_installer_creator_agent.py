# -*- coding: utf-8 -*-
"""
Installer Creator 에이전트 단독 smoke test (Phase 4.5 / v4).

검증 항목:
    1) `create_installer_creator_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 인스톨러 사양 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [BUILD_RESULT] + [ASSET_MANIFEST] + [TARGET_PLATFORM] + [APP_METADATA]
    + [SIGNING_AVAILABLE] 5블록 입력. Windows / Inno Setup 시나리오 + 코드 서명
    미보유 케이스로 사용자 가이드(SmartScreen 안내) 가 노트에 나오는지 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_installer_creator_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_installer_creator_agent.py -v
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

from src.agents.build_release import create_installer_creator_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — Windows / Inno Setup / 코드 서명 미보유
# ---------------------------------------------------------------------------
SAMPLE_BUILD_RESULT = """\
도구: pyinstaller
모드: onefile
산출: dist/calculator.exe (~25MB)
hidden_imports: customtkinter.windows.widgets.theme
"""

SAMPLE_ASSET_MANIFEST = """\
```yaml
app_metadata:
  display_name: 사칙연산 계산기
  short_name: NexusCalc
  description_ko: 가족용 단순 계산기
  version: 0.1.0
icons:
  - source: placeholder (theme.primary 단색)
    formats:
      - {ext: ico, sizes: [16, 32, 48, 256]}
fonts:
  - {family: Pretendard, license: OFL-1.1, bundle: false}
locales:
  - {lang: ko-KR, strings_file: inline}
legal_texts:
  - {name: LICENSE, source: placeholder MIT, dest_in_installer: installer/LICENSE.txt}
```
"""

TASK_DESCRIPTION = (
    "아래 5블록을 입력으로, 백스토리에 명시된 4단 구조(도구 선택 / 인스톨러 "
    "스크립트 / 사용자 가이드 / 인스톨러 노트)로 한국어 인스톨러 사양을 작성하세요. "
    "코드 서명이 없으므로 SignTool 절은 비활성 주석으로만 남기고, SmartScreen 우회 "
    "안내를 사용자 가이드에 포함하세요.\n\n"
    f"[BUILD_RESULT]\n{SAMPLE_BUILD_RESULT}\n\n"
    f"[ASSET_MANIFEST]\n{SAMPLE_ASSET_MANIFEST}\n\n"
    f"[TARGET_PLATFORM]\nwindows\n\n"
    f"[APP_METADATA]\ndisplay_name: 사칙연산 계산기 / short_name: NexusCalc / "
    f"version: 0.1.0 / publisher: Nexus Alpha\n\n"
    f"[SIGNING_AVAILABLE]\nno\n"
)

TASK_EXPECTED_OUTPUT = (
    "4단 구조의 한국어 인스톨러 사양 (도구 선택 / Inno Setup .iss 스크립트 / 사용자 "
    "가이드 / 노트). 마지막 줄 `Final Answer: tool=Inno Setup, output=setup.exe, "
    "est_size=~NMB, signed=no`."
)


def main() -> int:
    """Installer Creator 단독 실행 (실제 LLM)."""
    console.print(
        Rule("[bold cyan]Installer Creator smoke — Inno Setup .iss 스크립트 산출[/bold cyan]")
    )

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_installer_creator",
        user_id="local-dev",
        metadata={"phase": "phase_4_5", "agent": "installer_creator"},
    )

    try:
        agent = create_installer_creator_agent(verbose=False)
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
        with console.status("[yellow]Installer Creator 사양 작성 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]인스톨러 사양[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_installer_creator_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Installer Creator 가 CrewAI 를 통과하는지 검증."""
    agent = create_installer_creator_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Installer Creator kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
