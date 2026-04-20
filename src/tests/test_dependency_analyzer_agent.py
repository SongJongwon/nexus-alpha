# -*- coding: utf-8 -*-
"""
Dependency Analyzer 에이전트 단독 smoke test (Phase 4.5 / v4).

검증 항목:
    1) `create_dependency_analyzer_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 의존성 보고서 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [PROJECT_LAYOUT] + [CODE_SAMPLES] (lazy import 패턴 포함) +
    [REQUIREMENTS] + [TARGET_PLATFORM] 4 블록을 입력으로 주고, 6축 YAML 보고서
    + 분석가 코멘트 + 미검토 영역 산출 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_dependency_analyzer_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_dependency_analyzer_agent.py -v
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

from src.agents.build_release import create_dependency_analyzer_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 입력 — 의도적으로 lazy import + data file 신호 포함
# ---------------------------------------------------------------------------
SAMPLE_PROJECT_LAYOUT = """\
src/myapp/__init__.py
src/myapp/__main__.py
src/myapp/loader.py
src/myapp/templates/report.html
src/myapp/data/config.json
"""

SAMPLE_CODE_SAMPLES = """\
[loader.py]
import json
import importlib
from pathlib import Path

import pandas as pd
import numpy as np

def load_plugin(name: str):
    # lazy/dynamic import — PyInstaller 가 자동 감지 못 함
    return importlib.import_module(f"myapp.plugins.{name}")

def read_template():
    # data file 참조 — relative path
    p = Path(__file__).parent / "templates" / "report.html"
    return p.read_text(encoding="utf-8")

def read_config():
    p = Path(__file__).parent / "data" / "config.json"
    return json.loads(p.read_text(encoding="utf-8"))
"""

SAMPLE_REQUIREMENTS = """\
pandas>=2.0
numpy>=1.24
jinja2>=3.1
"""

SAMPLE_TARGET_PLATFORM = "windows"

TASK_DESCRIPTION = (
    "아래 4블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 보고서 6축 + 분석가 "
    "코멘트 + 미검토 영역)로 한국어 의존성 보고서를 작성하세요. lazy import / "
    "data file / native binary 신호를 빠뜨리지 마세요.\n\n"
    f"[PROJECT_LAYOUT]\n{SAMPLE_PROJECT_LAYOUT}\n\n"
    f"[CODE_SAMPLES]\n{SAMPLE_CODE_SAMPLES}\n\n"
    f"[REQUIREMENTS]\n{SAMPLE_REQUIREMENTS}\n\n"
    f"[TARGET_PLATFORM]\n{SAMPLE_TARGET_PLATFORM}\n"
)

TASK_EXPECTED_OUTPUT = (
    "YAML 보고서 6축(direct_dependencies/hidden_imports/data_files/native_binaries/"
    "license_warnings/os_specific/unverified_areas) + 분석가 코멘트 + 미검토 영역. "
    "마지막 줄 `Final Answer: deps=N개, hidden=M개, license_warnings=L개, "
    "os_blockers=B개`."
)


def main() -> int:
    """Dependency Analyzer 단독 실행 (실제 LLM)."""
    console.print(
        Rule("[bold cyan]Dependency Analyzer smoke — 코드 → 의존성 보고서[/bold cyan]")
    )

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_dependency_analyzer",
        user_id="local-dev",
        metadata={"phase": "phase_4_5", "agent": "dependency_analyzer"},
    )

    try:
        agent = create_dependency_analyzer_agent(verbose=False)
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
        with console.status("[yellow]의존성 감사 중...[/yellow]", spinner="dots"):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]의존성 보고서[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_dependency_analyzer_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Dependency Analyzer 가 CrewAI 를 통과하는지 검증."""
    agent = create_dependency_analyzer_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Dependency Analyzer kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
