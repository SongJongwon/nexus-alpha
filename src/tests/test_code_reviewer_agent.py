# -*- coding: utf-8 -*-
"""
Code Reviewer 에이전트 단독 smoke test.

검증 항목:
    1) `create_code_reviewer_agent()`가 `NexusAlphaLLM`을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew`로 단일 Task 실행 시 정적 리뷰 보고서가 산출되는지
    3) 실행 전체가 LangFuse에 `test_code_reviewer_agent` trace로 기록되는지

시나리오:
    Engineer가 산출했다고 가정하는 작은 Python 모듈(의도적 결함 3종 포함)을
    리뷰어에게 입력으로 주고, 5단 구조(종합 판정 / 항목별 / 이슈 / 보정 / 미검토)의
    한국어 보고서가 나오는지 확인한다. pytest 경로에서는 FakeProvider가 고정 응답을
    반환하므로 결함 인지 여부와 무관하게 체인 통과만 검증한다.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_code_reviewer_agent.py
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

from src.agents.qa import create_code_reviewer_agent
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 리뷰 대상 — Engineer 산출물 흉내 (의도적 결함 포함)
# ---------------------------------------------------------------------------
ENGINEER_SAMPLE_OUTPUT = """\
아래는 사칙연산 계산기 모듈입니다.

```python
# file: calc.py
def add(a, b):
    return a + b

def divide(a, b):
    try:
        return a / b
    except Exception:
        return None

def main():
    print(add(1, 2))
    print(divide(10, 0))

if __name__ == "__main__":
    main()
```

설치/실행: `python calc.py`
"""

# 의도적 결함 (리뷰어가 짚어야 할 항목 — 실제 LLM 경로 검증용 힌트):
#   ① 타입 힌트 전무 (add/divide/main)
#   ② docstring 전무
#   ③ pytest 파일 동봉 없음
#   ④ 내부 함수 divide()에 광범위 except — 경계 처리 원칙 위반


TASK_DESCRIPTION = (
    "아래는 Python Engineer가 제출한 마크다운 산출물입니다. 본 산출물에 대해 "
    "정적 점검 리뷰를 수행하고, 백스토리에 명시된 5단 구조(종합 판정 / 항목별 / "
    "이슈 / 권장 보정 / 미검토)의 한국어 보고서를 작성하세요.\n\n"
    f"--- Engineer 산출물 시작 ---\n{ENGINEER_SAMPLE_OUTPUT}\n--- Engineer 산출물 끝 ---"
)

TASK_EXPECTED_OUTPUT = (
    "종합 판정(APPROVED/NEEDS_REVISION) + 항목별 표 + 이슈 목록 + 권장 보정 + "
    "미검토 영역 5단 구조의 한국어 마크다운 리뷰 보고서. 마지막 줄은 `Final Answer:`로 시작."
)


def main() -> int:
    """Code Reviewer 에이전트를 실행하고 종료 코드를 반환한다."""
    console.print(
        Rule("[bold cyan]Code Reviewer Agent smoke test — 의도적 결함 검토[/bold cyan]")
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    monitor.log_trace(
        name="test_code_reviewer_agent",
        user_id="local-dev",
        metadata={
            "phase": "phase_2",
            "agent": "code_reviewer",
            "scenario": "calc_with_intentional_defects",
        },
    )

    try:
        reviewer = create_code_reviewer_agent()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Code Reviewer 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent    :[/bold] {reviewer.role}")
    console.print(
        f"[bold]LLM      :[/bold] NexusAlphaLLM "
        f"(backend={reviewer.llm.backend_provider.name})"
    )
    console.print(Rule())

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=reviewer,
    )
    crew = Crew(agents=[reviewer], tasks=[task], verbose=False)

    exit_code = 0
    try:
        with console.status(
            "[yellow]Code Reviewer가 정적 점검 중...[/yellow]", spinner="dots"
        ):
            result = crew.kickoff()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Crew 실행 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        exit_code = 1
    else:
        output_text = getattr(result, "raw", None) or str(result)
        if not output_text.strip():
            console.print(
                Panel(
                    "[yellow]Code Reviewer 응답이 비어 있습니다.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1
        else:
            console.print(
                Panel(
                    output_text,
                    title="[green]Code Reviewer 보고서[/green]",
                    border_style="green",
                )
            )

    monitor.end_trace()
    monitor.flush()

    if monitor.enabled:
        console.print(Rule())
        console.print(
            Panel(
                f"실행 기록이 LangFuse로 전송되었습니다.\n"
                f"대시보드: [cyan]{monitor.host}[/cyan]\n"
                f"(trace: [bold]test_code_reviewer_agent[/bold])",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return exit_code


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_code_reviewer_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답이 CrewAI 파서를 거쳐 AgentFinish로 정상 수렴하는지 검증한다."""
    reviewer = create_code_reviewer_agent(verbose=False)

    # FakeProvider가 factory 레벨에서 자동 주입되었는지 확인
    assert reviewer.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=reviewer,
    )
    result = Crew(agents=[reviewer], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Code Reviewer kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
