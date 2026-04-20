# -*- coding: utf-8 -*-
"""
Phase 4 — GUI 에이전트 4종 단독 smoke test (UI/UX Analyst + 디자인 본부 3명).

검증 항목:
    1) 각 팩토리가 `NexusAlphaLLM` 을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew` 로 단일 Task 실행 시 각 에이전트가 산출을 만들어 내는지
    3) pytest 경로(FakeProvider)에서 4종 모두 AgentFinish 로 수렴하는지

시나리오:
    Phase 4 흐름의 4단계를 순차로 검증:
        [1] UI/UX Analyst — "계산기 만들어줘" 한 줄에 GUI 필요 + form_factor 판정
        [2] GUI Designer — UI/UX 산출 ui_spec 을 받아 와이어프레임 + 위젯 트리
        [3] Theme Designer — ui_spec + 와이어프레임 받아 디자인 토큰 JSON
        [4] GUI Code Generator — 위 셋 모두 받아 실행 가능 Python GUI 코드

    pytest 경로에서는 FakeProvider 가 고정 응답을 돌려주므로 결과 *내용* 이 아닌
    *체인 통과* 만 검증. 실제 LLM 으로 결과 품질을 보려면 `python ... ` 직접 실행.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_gui_agents.py        # 4종 순차 (실제 LLM)
    .venv\\Scripts\\pytest.exe   src\\tests\\test_gui_agents.py -v   # FakeProvider 경로
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

from src.agents.design import (
    create_gui_code_generator_agent,
    create_gui_designer_agent,
    create_theme_designer_agent,
)
from src.agents.planning import create_uiux_analyst_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 입력 (사용자 요청 + 가상의 이전 단계 산출물)
# ---------------------------------------------------------------------------
USER_REQUEST = (
    "사칙연산 계산기 만들어줘. 비전공자 가족이 더블클릭해서 바로 쓸 수 있게."
)

UIUX_TASK_DESCRIPTION = (
    "아래 사용자 요청을 받아, 백스토리에 명시된 2단 구조(YAML ui_spec + 분석가 "
    "노트)로 한국어 UI/UX 분석을 작성하세요. 5가지 질문 모두에 답하세요.\n\n"
    f"--- 사용자 요청 ---\n{USER_REQUEST}\n--- 끝 ---"
)

UIUX_TASK_EXPECTED_OUTPUT = (
    "YAML ui_spec(need_gui/form_factor/complexity/questions/assumptions/"
    "recommended_framework_hint) + 분석가 노트. 마지막 줄 `Final Answer: "
    "form_factor=..., complexity=..., need_gui=...`."
)


# 가상의 ui_spec — Designer/Theme/CodeGen 입력으로 사용
SAMPLE_UI_SPEC = """\
```yaml
need_gui: yes
form_factor: single_window
complexity: simple
questions:
  windows: 단일 윈도우
  data_unit: 한 번에 한 수식 (str)
  state: volatile
  learning_curve_min: 1
  accessibility: basic
assumptions:
  - 비전공자 가족용 — Windows 데스크톱이 기본 (가족 환경 가정)
  - 키보드 + 마우스 모두 지원 (사용자 미명시, 일반 데스크톱 가정)
recommended_framework_hint:
  - tkinter
```
"""

DESIGNER_TASK_DESCRIPTION = (
    "아래 ui_spec 을 받아, 백스토리에 명시된 4단 구조(와이어프레임 + 위젯 트리 "
    "+ 인터랙션 흐름 + 디자이너 노트)로 한국어 GUI 설계서를 작성하세요. 색상·"
    "폰트는 다루지 마세요 (Theme Designer 책임).\n\n"
    f"[UI_UX_SPEC]\n{SAMPLE_UI_SPEC}"
)

DESIGNER_TASK_EXPECTED_OUTPUT = (
    "와이어프레임(ASCII) + 위젯 트리(yaml) + 인터랙션 흐름 + 디자이너 노트. "
    "마지막 줄 `Final Answer: GUI design — N개 윈도우, M개 위젯`."
)


# 가상의 GUI Design — Theme Designer/Code Generator 입력으로 사용
SAMPLE_GUI_DESIGN = """\
와이어프레임:
┌─────────────────────────────┐
│  계산기                     │
├─────────────────────────────┤
│        [   디스플레이   ]    │
├─────────────────────────────┤
│   7  8  9  /                │
│   4  5  6  *                │
│   1  2  3  -                │
│   0  C  =  +                │
└─────────────────────────────┘

위젯 트리:
main_window:
  title: 계산기
  children:
    - widget: display_label
    - widget: keypad_grid
      children:
        - 16개 button (숫자 0~9 + 연산자 +/-/*/=, C)

톤 힌트: neutral (가족용, 자극적 색상 회피)
"""

THEME_TASK_DESCRIPTION = (
    "아래 ui_spec + GUI 설계를 받아, 백스토리에 명시된 3단 구조(JSON 토큰 + "
    "적용 가이드 + 디자이너 노트)로 한국어 디자인 토큰을 산출하세요. WCAG AA "
    "대비를 보장하세요.\n\n"
    f"[UI_UX_SPEC]\n{SAMPLE_UI_SPEC}\n\n"
    f"[GUI_DESIGN]\n{SAMPLE_GUI_DESIGN}"
)

THEME_TASK_EXPECTED_OUTPUT = (
    "JSON 디자인 토큰(theme_strategy/palette/typography/spacing/radii/"
    "accessibility) + 적용 가이드 + 디자이너 노트. 마지막 줄 `Final Answer: "
    "theme_strategy=..., modes=N개, palette=...`."
)


# 가상의 Theme tokens — Code Generator 입력으로 사용
SAMPLE_DESIGN_TOKENS = """\
```json
{
  "theme_strategy": "native",
  "reasoning": "단순 계산기 + 비전공자 가족 — 학습 비용 0 의 OS 룩&필 우선",
  "modes": ["light"],
  "palette": {
    "primary":    "#0078D4",
    "secondary":  "#106EBE",
    "surface":    "#FFFFFF",
    "on_surface": "#1F1F1F",
    "error":      "#D13438"
  },
  "typography": {
    "family_korean": "Pretendard",
    "family_latin":  "Segoe UI",
    "sizes": {"caption": 11, "body": 13, "subtitle": 15, "title": 18, "display": 24}
  },
  "spacing": [4, 8, 16, 24],
  "radii": {"small": 4, "medium": 8, "large": 16},
  "accessibility": {"min_contrast_ratio": 4.5, "focus_visible": true, "keyboard_nav": true}
}
```
"""

CODE_GEN_TASK_DESCRIPTION = (
    "아래 세 입력을 모두 만족하는 **바로 실행 가능한 Python GUI 코드** 를 "
    "백스토리에 명시된 4단 구조(프레임워크 선택 + 코드 + 실행 방법 + 작성자 "
    "노트)로 작성하세요. 파일은 ```python 블록 + `# file:` 헤더 포함.\n\n"
    f"[UI_UX_SPEC]\n{SAMPLE_UI_SPEC}\n\n"
    f"[GUI_DESIGN]\n{SAMPLE_GUI_DESIGN}\n\n"
    f"[DESIGN_TOKENS]\n{SAMPLE_DESIGN_TOKENS}"
)

CODE_GEN_TASK_EXPECTED_OUTPUT = (
    "프레임워크 선택 근거 + Python GUI 코드(파일 여러 개) + 실행 방법 + 작성자 "
    "노트. 마지막 줄 `Final Answer: framework=..., files=N개, entry=...`."
)


# ---------------------------------------------------------------------------
# 직접 실행 경로 (실제 LLM)
# ---------------------------------------------------------------------------
def _run_single_agent(
    title: str,
    factory_fn,
    task_description: str,
    task_expected_output: str,
    trace_name: str,
) -> int:
    """주어진 에이전트 팩토리·Task 1쌍 실행."""
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name=trace_name,
        user_id="local-dev",
        metadata={"phase": "phase_4_gui", "agent": trace_name},
    )

    try:
        agent = factory_fn()
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

    task = Task(description=task_description, expected_output=task_expected_output, agent=agent)
    crew = Crew(agents=[agent], tasks=[task], verbose=False)

    exit_code = 0
    try:
        with console.status("[yellow]에이전트 실행 중...[/yellow]", spinner="dots"):
            result = crew.kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        exit_code = 1
    else:
        output_text = getattr(result, "raw", None) or str(result)
        if not output_text.strip():
            console.print(Panel("[yellow]응답이 비어 있습니다.[/yellow]", border_style="yellow"))
            exit_code = 1
        else:
            console.print(Panel(output_text, title="[green]산출[/green]", border_style="green"))

    monitor.end_trace()
    monitor.flush()
    return exit_code


def main() -> int:
    """4종 에이전트를 순차로 실행 (실제 LLM)."""
    rc1 = _run_single_agent(
        title="UI/UX Analyst smoke — 사용자 요청 → ui_spec",
        factory_fn=lambda: create_uiux_analyst_agent(verbose=False),
        task_description=UIUX_TASK_DESCRIPTION,
        task_expected_output=UIUX_TASK_EXPECTED_OUTPUT,
        trace_name="test_uiux_analyst",
    )
    rc2 = _run_single_agent(
        title="GUI Designer smoke — ui_spec → 와이어프레임 + 위젯 트리",
        factory_fn=lambda: create_gui_designer_agent(verbose=False),
        task_description=DESIGNER_TASK_DESCRIPTION,
        task_expected_output=DESIGNER_TASK_EXPECTED_OUTPUT,
        trace_name="test_gui_designer",
    )
    rc3 = _run_single_agent(
        title="Theme Designer smoke — ui_spec + 디자인 → 디자인 토큰",
        factory_fn=lambda: create_theme_designer_agent(verbose=False),
        task_description=THEME_TASK_DESCRIPTION,
        task_expected_output=THEME_TASK_EXPECTED_OUTPUT,
        trace_name="test_theme_designer",
    )
    rc4 = _run_single_agent(
        title="GUI Code Generator smoke — 셋 모두 → 실행 가능 GUI 코드",
        factory_fn=lambda: create_gui_code_generator_agent(verbose=False),
        task_description=CODE_GEN_TASK_DESCRIPTION,
        task_expected_output=CODE_GEN_TASK_EXPECTED_OUTPUT,
        trace_name="test_gui_code_generator",
    )
    return rc1 or rc2 or rc3 or rc4


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_uiux_analyst_runs_through_crew_with_fake_provider() -> None:
    analyst = create_uiux_analyst_agent(verbose=False)
    assert analyst.llm.backend_provider.name == "fake"

    task = Task(
        description=UIUX_TASK_DESCRIPTION,
        expected_output=UIUX_TASK_EXPECTED_OUTPUT,
        agent=analyst,
    )
    result = Crew(agents=[analyst], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "UI/UX Analyst kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


def test_gui_designer_runs_through_crew_with_fake_provider() -> None:
    designer = create_gui_designer_agent(verbose=False)
    assert designer.llm.backend_provider.name == "fake"

    task = Task(
        description=DESIGNER_TASK_DESCRIPTION,
        expected_output=DESIGNER_TASK_EXPECTED_OUTPUT,
        agent=designer,
    )
    result = Crew(agents=[designer], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "GUI Designer kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


def test_theme_designer_runs_through_crew_with_fake_provider() -> None:
    theme = create_theme_designer_agent(verbose=False)
    assert theme.llm.backend_provider.name == "fake"

    task = Task(
        description=THEME_TASK_DESCRIPTION,
        expected_output=THEME_TASK_EXPECTED_OUTPUT,
        agent=theme,
    )
    result = Crew(agents=[theme], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Theme Designer kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


def test_gui_code_generator_runs_through_crew_with_fake_provider() -> None:
    coder = create_gui_code_generator_agent(verbose=False)
    assert coder.llm.backend_provider.name == "fake"

    task = Task(
        description=CODE_GEN_TASK_DESCRIPTION,
        expected_output=CODE_GEN_TASK_EXPECTED_OUTPUT,
        agent=coder,
    )
    result = Crew(agents=[coder], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "GUI Code Generator kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
