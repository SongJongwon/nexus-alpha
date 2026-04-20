# -*- coding: utf-8 -*-
"""
v3 자율 반복 루프 — Requirement Expander + Gap Analyst 단독 smoke test (Phase 2.5).

검증 항목:
    1) 두 팩토리(`create_requirement_expander_agent`, `create_gap_analyst_agent`)가
       `NexusAlphaLLM` 을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew` 로 단일 Task 실행 시 각 에이전트가 산출을 만들어 내는지
    3) 실행 전체가 LangFuse trace 로 기록되는지
    4) pytest 경로(FakeProvider)에서 두 에이전트 모두 AgentFinish 로 수렴하는지

시나리오:
    - **Requirement Expander**: "사칙연산 계산기 만들어줘" 같은 짧은 요청을 입력으로
      주고, YAML 요구 스펙 + 분석가 노트가 나오는지 확인.
    - **Gap Analyst**: 가상의 [REQUIREMENT_SPEC] / [ENGINEER_OUTPUT] / [QA_REVIEW]
      블록 묶음을 입력으로 주고, satisfied/unsatisfied/ambiguous/stagnation 4개 축의
      YAML 갭 보고서가 나오는지 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_v3_spec_and_gap.py        # 직접 실행 (실제 LLM)
    .venv\\Scripts\\pytest.exe   src\\tests\\test_v3_spec_and_gap.py -v   # FakeProvider 경로
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

from src.agents.analysis import (
    create_gap_analyst_agent,
    create_requirement_expander_agent,
)
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 1 — Requirement Expander
# ---------------------------------------------------------------------------
EXPANDER_USER_REQUEST = (
    "사칙연산 계산기 Python 앱을 만들어줘. 덧셈/뺄셈/곱셈/나눗셈 가능, "
    "터미널에서 바로 실행. 파일명은 calculator.py."
)

EXPANDER_TASK_DESCRIPTION = (
    "아래 사용자 요청을 받아, 백스토리에 명시된 2단 구조(YAML 요구 스펙 + "
    "분석가 노트)로 한국어 요구 스펙을 작성하세요. 가정과 미해결 질문은 반드시 "
    "분리해 명시하세요.\n\n"
    f"--- 사용자 요청 ---\n{EXPANDER_USER_REQUEST}\n--- 끝 ---"
)

EXPANDER_TASK_EXPECTED_OUTPUT = (
    "YAML 요구 스펙(goal/deliverables/functional/nonfunctional/assumptions/"
    "open_questions) 1개 + 분석가 노트. 마지막 줄 `Final Answer: spec expanded "
    "with N functional, M nonfunctional, ...`."
)


# ---------------------------------------------------------------------------
# 시나리오 2 — Gap Analyst (가상의 4개 입력 블록)
# ---------------------------------------------------------------------------
GAP_INPUT_REQUIREMENT_SPEC = """\
goal: |
  사칙연산 계산기 Python 앱을 만들어줘. 파일명은 calculator.py.
deliverables:
  - type: script
    platform: cross-platform
    form_factor: CLI
    language: Python
functional:
  - id: F-001
    desc: 덧셈/뺄셈/곱셈/나눗셈 4종 연산 지원
    priority: must
  - id: F-002
    desc: 0으로 나누기 입력에 대한 안전한 오류 처리
    priority: must
nonfunctional:
  - id: N-001
    desc: 파일명 calculator.py 단일 파일
    priority: must
  - id: N-002
    desc: 추가 의존성 없이 표준 라이브러리만으로 동작
    priority: should
assumptions:
  - 입력 형식은 '<숫자> <연산자> <숫자>' (사용자 미명시, 일반적 REPL 가정)
open_questions:
  - 부동소수점 정밀도 요구 (Decimal vs float)는 명시되지 않음
"""

GAP_INPUT_ENGINEER_OUTPUT = """\
calculator.py 단일 파일 산출. add/subtract/multiply/divide 4 함수 + dispatch
table OPERATIONS + parse_input + run_repl. 모든 함수에 타입 힌트 + docstring.
ZeroDivisionError 처리 포함.
"""

GAP_INPUT_QA_REVIEW = """\
APPROVED. 5단 점검 모두 통과. MINOR 1건(parse_input ValueError 메시지가
영문/한글 혼재). 타입 힌트·docstring·pytest 가능성·경계 처리·모듈 분리
모두 합격.
"""

GAP_TASK_DESCRIPTION = (
    "아래 4개 블록을 입력으로, 백스토리에 명시된 2단 구조(YAML 갭 보고서 + "
    "분석가 코멘트)로 한국어 갭 분석 보고서를 작성하세요. 본 iteration 은 "
    "첫 회차이므로 stagnation 의 resolved_gaps_since_last 는 null 로 적습니다.\n\n"
    f"[REQUIREMENT_SPEC]\n```yaml\n{GAP_INPUT_REQUIREMENT_SPEC}\n```\n\n"
    f"[ENGINEER_OUTPUT]\n{GAP_INPUT_ENGINEER_OUTPUT}\n\n"
    f"[QA_REVIEW]\n{GAP_INPUT_QA_REVIEW}\n\n"
    f"[EXECUTION_RESULT]\n(없음 — Sandbox Runner 미적용)\n\n"
    f"[PREVIOUS_GAP_REPORT]\n(없음 — 첫 iteration)\n"
)

GAP_TASK_EXPECTED_OUTPUT = (
    "YAML 갭 보고서(satisfied/unsatisfied/ambiguous/stagnation) + 분석가 코멘트. "
    "마지막 줄 `Final Answer: gap report — N satisfied, ...`."
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
    """주어진 에이전트 팩토리·Task 1쌍을 실행하고 결과를 패널로 출력."""
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name=trace_name,
        user_id="local-dev",
        metadata={"phase": "phase_2_5_v3", "agent": trace_name},
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
    """Requirement Expander + Gap Analyst 두 시나리오를 순차 실행."""
    rc1 = _run_single_agent(
        title="Requirement Expander smoke — 사용자 요청 → YAML 스펙",
        factory_fn=lambda: create_requirement_expander_agent(verbose=False),
        task_description=EXPANDER_TASK_DESCRIPTION,
        task_expected_output=EXPANDER_TASK_EXPECTED_OUTPUT,
        trace_name="test_requirement_expander",
    )
    rc2 = _run_single_agent(
        title="Gap Analyst smoke — Spec ↔ 산출물 → 갭 보고서",
        factory_fn=lambda: create_gap_analyst_agent(verbose=False),
        task_description=GAP_TASK_DESCRIPTION,
        task_expected_output=GAP_TASK_EXPECTED_OUTPUT,
        trace_name="test_gap_analyst",
    )
    return rc1 or rc2


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_requirement_expander_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Requirement Expander 가 CrewAI 를 통과하는지 검증한다."""
    expander = create_requirement_expander_agent(verbose=False)
    assert expander.llm.backend_provider.name == "fake"

    task = Task(
        description=EXPANDER_TASK_DESCRIPTION,
        expected_output=EXPANDER_TASK_EXPECTED_OUTPUT,
        agent=expander,
    )
    result = Crew(agents=[expander], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Requirement Expander kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


def test_gap_analyst_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Gap Analyst 가 CrewAI 를 통과하는지 검증한다."""
    gap = create_gap_analyst_agent(verbose=False)
    assert gap.llm.backend_provider.name == "fake"

    task = Task(
        description=GAP_TASK_DESCRIPTION,
        expected_output=GAP_TASK_EXPECTED_OUTPUT,
        agent=gap,
    )
    result = Crew(agents=[gap], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Gap Analyst kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
