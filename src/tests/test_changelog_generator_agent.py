# -*- coding: utf-8 -*-
"""
Changelog Generator 에이전트 단독 smoke test (Phase 5 / v4 — 7/9).

검증 항목:
    1) `create_changelog_generator_agent()` 가 NexusAlphaLLM 자동 주입해 정상 생성
    2) CrewAI Crew 단일 Task 실행 시 Keep a Changelog 형식 항목 산출
    3) pytest 경로(FakeProvider)에서 AgentFinish 수렴

시나리오:
    가상의 [VERSION_DECISION] (Release Manager 산출) + [CHANGE_SOURCES]
    (iteration_history + git_commits + build_change_summary) +
    [BREAKING_FLAGS] + [PREVIOUS_CHANGELOG] 5블록 입력. minor bump 시나리오
    (0.2.0 → 0.3.0, breaking 없음, 다중 카테고리).

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_changelog_generator_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_changelog_generator_agent.py -v
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

from src.agents.build_release import create_changelog_generator_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 — Release Manager 결정 + 다중 변경 소스 + Added/Changed/Fixed 카테고리
# ---------------------------------------------------------------------------
SAMPLE_VERSION_DECISION = """\
다음 버전: 0.3.0 / bump: minor / Git 태그: v0.3.0
근거: 신규 기능 3종 (% 연산자, 키보드 단축키, 다크 모드) — backward-compatible.
breaking 없음.
"""

SAMPLE_ITERATION_HISTORY = """\
iter 1 — 사용자 요청: 사칙연산 + 다크 모드. CTO: tkinter+customtkinter. Engineer:
  4 함수 + dispatch table. QA: APPROVED.
iter 2 — Gap Analyst: 키보드 단축키 부재 (must). Engineer: bind 추가. QA: APPROVED.
iter 3 — Gap Analyst: 0/0 토스트 부재 (should). Engineer: messagebox.showwarning
  추가. QA: APPROVED. → COMPLETE.
"""

SAMPLE_GIT_COMMITS = """\
- feat: % 연산자 추가
- feat: 키보드 단축키 (Enter, Backspace) 지원
- feat: 다크 모드 토글 추가
- fix: 0으로 나누기 시 토스트 메시지 표시
- chore: customtkinter 5.2.2 → 5.2.3 업데이트
"""

SAMPLE_BUILD_CHANGE_SUMMARY = """\
- 빌드 도구: 동일 (PyInstaller onefile)
- est_size: 25MB → 28MB (+3MB — customtkinter 신규 테마 자원)
- hidden_imports: 1 → 2 (CTkSwitch 의 lazy import 추가)
"""

SAMPLE_PREVIOUS_CHANGELOG = """\
## [0.2.0] - 2026-04-15

### Added
- 사칙연산 GUI 계산기 첫 릴리스 (tkinter+customtkinter)
- 0으로 나누기 안전 처리

### Fixed
- 입력 형식 오류 시 빨간 외곽선 표시
"""

TASK_DESCRIPTION = (
    "아래 5블록을 입력으로, 백스토리에 명시된 2단 구조(Keep a Changelog 형식 항목 + "
    "작성자 노트)로 한국어 CHANGELOG 항목을 작성하세요. 빈 카테고리는 헤더째 "
    "생략하고, 카테고리 키워드는 영문 표준(Added/Changed/...) 그대로 두세요.\n\n"
    f"[VERSION_DECISION]\n{SAMPLE_VERSION_DECISION}\n\n"
    f"[CHANGE_SOURCES]\n"
    f"--- iteration_history ---\n{SAMPLE_ITERATION_HISTORY}\n"
    f"--- git_commits ---\n{SAMPLE_GIT_COMMITS}\n"
    f"--- build_change_summary ---\n{SAMPLE_BUILD_CHANGE_SUMMARY}\n\n"
    f"[BREAKING_FLAGS]\nnone\n\n"
    f"[PREVIOUS_CHANGELOG]\n{SAMPLE_PREVIOUS_CHANGELOG}\n"
)

TASK_EXPECTED_OUTPUT = (
    "Keep a Changelog 형식 항목 (## [0.3.0] - 날짜 + 카테고리별 항목) + 작성자 "
    "노트. 마지막 줄 `Final Answer: version=0.3.0, entries=N개, breaking=0개, "
    "categories=Added, Fixed`."
)


def main() -> int:
    """Changelog Generator 단독 실행 (실제 LLM)."""
    console.print(
        Rule("[bold cyan]Changelog Generator smoke — 0.3.0 minor bump 항목 생성[/bold cyan]")
    )

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_changelog_generator",
        user_id="local-dev",
        metadata={"phase": "phase_5", "agent": "changelog_generator"},
    )

    try:
        agent = create_changelog_generator_agent(verbose=False)
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
            "[yellow]Changelog Generator 항목 작성 중...[/yellow]", spinner="dots"
        ):
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(result, "raw", None) or str(result)
    console.print(Panel(output_text, title="[green]CHANGELOG 항목[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_changelog_generator_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Changelog Generator 가 CrewAI 를 통과하는지 검증."""
    agent = create_changelog_generator_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Changelog Generator kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
