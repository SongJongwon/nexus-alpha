# -*- coding: utf-8 -*-
"""
Data Analyst 에이전트 단독 smoke test.

검증 항목:
    1) `create_data_analyst_agent()`가 `NexusAlphaLLM`을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew`로 단일 Task를 실행할 때 분석 문서가 산출되는지
    3) 실행 전체가 LangFuse에 `test_data_analyst_agent` trace로 기록되는지

시나리오:
    CTO로부터 전달받은 전략(Excel → PDF 보고서 파이프라인)을 입력 맥락으로
    제공하고, 가상의 월별 매출 데이터에 대한 분석 지시서를 요청한다.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_data_analyst_agent.py
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

from src.agents.analysis import create_data_analyst_agent
from src.monitoring import get_langfuse_client


console = Console()


# CTO가 산출한 전략 문서의 요지(실제 체인에서는 선행 Task 산출물을 주입)
CTO_STRATEGY_SUMMARY = (
    "[CTO 전략 요약]\n"
    "- 목적: 월별 매출 Excel을 임원용 PDF 보고서로 자동 변환하는 파이프라인 구축.\n"
    "- 기술 스택: openpyxl + pandas (데이터), matplotlib/seaborn (차트), "
    "Jinja2 + WeasyPrint (PDF 렌더링).\n"
    "- 보고서 목표 독자: 경영진. 한 눈에 실적 하이라이트·경고 신호·"
    "추가 확인 필요 영역을 파악할 수 있어야 함.\n"
    "- 분석 산출물은 엔지니어링 팀이 즉시 시각화 코드로 옮길 수 있도록 "
    "지표 정의·차트 스펙·이상치 기준이 구체적으로 명시되어야 함."
)

DATASET_DESCRIPTION = (
    "[입력 데이터 설명]\n"
    "- 파일 형식: Excel (.xlsx), 단일 시트\n"
    "- 기간: 2024-01 ~ 2024-12 (월별 행)\n"
    "- 제품 카테고리 3개: 가전 / 생활용품 / 식품\n"
    "- 지역 5개: 서울 / 경기 / 부산 / 대구 / 기타\n"
    "- 컬럼(예상): year_month, category, region, sales_amount_krw, "
    "orders_count, avg_order_value, returns_count"
)

TASK_DESCRIPTION = (
    f"{CTO_STRATEGY_SUMMARY}\n\n"
    f"{DATASET_DESCRIPTION}\n\n"
    "위 맥락을 바탕으로 다음을 한국어로 제시해 주세요:\n"
    "  1. 데이터 품질 체크포인트 (결측·이상치·중복 관점에서 먼저 확인할 항목)\n"
    "  2. 핵심 지표 5개 (각 지표에 대해: 이름 · 계산식 · 단위 · 의사결정 "
    "     질문 · 표시 위치)\n"
    "  3. 추천 차트 3종 (각 차트에 대해: 유형 · 축 구성 · 전하려는 "
    "     메시지 · 주의할 디자인 포인트)\n"
    "  4. 주의해야 할 이상치 유형과 탐지 기준 (예: z-score, IQR, 비즈니스 "
    "     임계값 등 구체적 기준)\n"
    "  5. 분석가 코멘트 (경영진 보고 시 가장 먼저 강조해야 할 포인트 2~3개)"
)

TASK_EXPECTED_OUTPUT = (
    "데이터 품질 / 핵심 지표 5개 / 추천 차트 3종 / 이상치 / 분석가 코멘트 "
    "다섯 섹션으로 구성된 한국어 분석 지시서"
)


def main() -> int:
    """Data Analyst 에이전트를 실행하고 종료 코드를 반환한다."""
    console.print(
        Rule("[bold cyan]Data Analyst smoke test — 월별 매출 분석 지시서[/bold cyan]")
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    monitor.log_trace(
        name="test_data_analyst_agent",
        user_id="local-dev",
        metadata={
            "phase": "phase_1",
            "agent": "data_analyst",
            "scenario": "monthly_sales_2024",
        },
    )

    try:
        analyst = create_data_analyst_agent()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Data Analyst 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent    :[/bold] {analyst.role}")
    console.print(
        f"[bold]LLM      :[/bold] NexusAlphaLLM "
        f"(backend={analyst.llm.backend_provider.name})"
    )
    console.print(Rule())

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=analyst,
    )
    crew = Crew(agents=[analyst], tasks=[task], verbose=False)

    exit_code = 0
    try:
        with console.status(
            "[yellow]Data Analyst가 분석 지시서를 작성 중...[/yellow]",
            spinner="dots",
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
                    "[yellow]Data Analyst 응답이 비어 있습니다.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1
        else:
            console.print(
                Panel(
                    output_text,
                    title="[green]Data Analyst 분석 지시서[/green]",
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
                f"(trace: [bold]test_data_analyst_agent[/bold])",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return exit_code


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_data_analyst_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답을 CrewAI가 AgentFinish로 파싱해 Data Analyst가 동작하는지 검증."""
    analyst = create_data_analyst_agent(verbose=False)

    assert analyst.llm.backend_provider.name == "fake"

    task = Task(
        description=TASK_DESCRIPTION,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=analyst,
    )
    result = Crew(agents=[analyst], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Data Analyst kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
