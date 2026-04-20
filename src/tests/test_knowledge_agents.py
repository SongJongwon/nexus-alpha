# -*- coding: utf-8 -*-
"""
Knowledge 에이전트 2종 단독 smoke test (Knowledge Curator + RAG Searcher).

검증 항목:
    1) 각 팩토리(`create_knowledge_curator_agent`, `create_rag_searcher_agent`)가
       `NexusAlphaLLM`을 자동 주입해 정상 생성되는지
    2) CrewAI `Crew`로 단일 Task 실행 시 각 에이전트가 산출을 만들어 내는지
    3) 실행 전체가 LangFuse trace로 기록되는지
    4) pytest 경로(FakeProvider)에서 두 에이전트 모두 AgentFinish로 수렴하는지

시나리오:
    - **Curator**: 가상의 워크플로우 산출물 묶음(사용자 요청 + 4단 요약 + QA 판정)
      을 입력으로 주고, YAML entry + 큐레이션 노트가 나오는지 확인.
    - **Searcher**: 새 사용자 요청 + Curator entry 2건을 입력으로 주고, 추천
      목록이 나오는지 확인.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_knowledge_agents.py        # 2개 시나리오 순차 실행
    .venv\\Scripts\\pytest.exe   src\\tests\\test_knowledge_agents.py -v   # FakeProvider 경로
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

from src.agents.knowledge import (
    create_knowledge_curator_agent,
    create_rag_searcher_agent,
)
from src.monitoring import get_langfuse_client


console = Console()


# ---------------------------------------------------------------------------
# 시나리오 1 — Knowledge Curator: 가상 워크플로우 산출물 → YAML entry
# ---------------------------------------------------------------------------
CURATOR_SAMPLE_INPUT = """\
=== 입력: workflow_20260417_164414 ===

[00_user_request.txt]
사칙연산 계산기 Python 앱을 만들어줘. 덧셈, 뺄셈, 곱셈, 나눗셈 기능.
터미널에서 바로 실행 가능하게. 파일명: calculator.py

[01_cto_strategy.md (요약)]
Python 표준 라이브러리만 사용한 단일 파일 REPL. dispatch 테이블로 연산자
분기, ZeroDivisionError 처리, 입력 검증 분리.

[02_analyst_brief.md (요약)]
지표는 본 앱에 해당 없음. 단위 테스트 4종(add/subtract/multiply/divide)
권고. 사용자 입력 형식은 '<숫자> <연산자> <숫자>' 고정.

[03_engineer_output.md (요약)]
calculator.py 단일 파일. add/subtract/multiply/divide 함수 + dispatch
table OPERATIONS + parse_input + run_repl. 모든 함수에 타입 힌트 + docstring.

[04_qa_review.md (요약)]
APPROVED. 5단 점검 모두 통과. MINOR 1건(parse_input의 ValueError 메시지가
영문/한글 혼재).
"""

CURATOR_TASK_DESCRIPTION = (
    "아래는 한 워크플로우의 산출물 묶음입니다. 백스토리에 명시된 2단 구조"
    "(YAML entry + 큐레이션 노트)로 한국어 색인 entry를 작성하세요.\n\n"
    f"--- 입력 시작 ---\n{CURATOR_SAMPLE_INPUT}\n--- 입력 끝 ---"
)

CURATOR_TASK_EXPECTED_OUTPUT = (
    "YAML 형식 entry 1개 + 큐레이션 노트 한 단락. 마지막 줄은 `Final Answer:` "
    "로 시작하는 한 줄 카운트(`1 entry curated`)."
)


# ---------------------------------------------------------------------------
# 시나리오 2 — RAG Searcher: 새 요청 + 과거 entry 2건 → 추천 목록
# ---------------------------------------------------------------------------
SEARCHER_NEW_REQUEST = (
    "Python으로 간단한 단위 변환기(km↔mile, kg↔lb)를 터미널에서 쓰게 만들어줘. "
    "파일명은 converter.py."
)

SEARCHER_PAST_ENTRIES = """\
```yaml
workflow_id: workflow_20260417_164414
curated_at: 2026-04-17
user_request_oneline: 사칙연산 Python 계산기 (REPL, calculator.py)
summary: |
  Python 표준 라이브러리만 사용한 단일 파일 사칙연산 REPL. dispatch table 패턴.
tags:
  - calculator
  - python
  - cli-script
  - single-file
  - qa-approved
artifacts:
  - 03_engineer_output.md
  - code/calculator.py
qa_verdict: APPROVED
```

```yaml
workflow_id: workflow_20260417_162709
curated_at: 2026-04-17
user_request_oneline: 매장 매출 Excel → 임원 PDF 보고서 자동화
summary: |
  pandas + matplotlib + Jinja2 + WeasyPrint으로 월간 매출 Excel을 PDF로 변환.
tags:
  - excel-to-pdf
  - python
  - pandas
  - reporting
  - qa-approved
artifacts:
  - 03_engineer_output.md
  - code/cli.py
qa_verdict: APPROVED
```
"""

SEARCHER_TASK_DESCRIPTION = (
    "아래 새 사용자 요청과 Knowledge Curator가 색인한 과거 entry 2건을 입력으로, "
    "백스토리에 명시된 4단 구조(검색 요약 / 추천 / 보조 후보 / 검색자 코멘트)로 "
    "한국어 추천 보고서를 작성하세요.\n\n"
    f"--- 새 사용자 요청 ---\n{SEARCHER_NEW_REQUEST}\n\n"
    f"--- 과거 entry 목록 ---\n{SEARCHER_PAST_ENTRIES}"
)

SEARCHER_TASK_EXPECTED_OUTPUT = (
    "검색 요약 / 추천 (점수 내림차순) / 보조 후보 / 검색자 코멘트 4단 구조의 "
    "한국어 추천 보고서. 마지막 줄은 `Final Answer:` 로 시작하는 카운트."
)


# ---------------------------------------------------------------------------
# 직접 실행 경로 (실제 LLM 호출)
# ---------------------------------------------------------------------------
def _run_single_agent(
    title: str,
    factory_fn,
    task_description: str,
    task_expected_output: str,
    trace_name: str,
) -> int:
    """주어진 에이전트 팩토리·Task 1쌍을 실행하고 결과를 패널로 출력한다."""
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))

    monitor = get_langfuse_client()
    monitor.log_trace(
        name=trace_name,
        user_id="local-dev",
        metadata={"phase": "phase_2_p3", "agent": trace_name},
    )

    try:
        agent = factory_fn()
    except Exception as exc:
        console.print(Panel(f"[bold red]에이전트 초기화 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent    :[/bold] {agent.role}")
    console.print(
        f"[bold]LLM      :[/bold] NexusAlphaLLM "
        f"(backend={agent.llm.backend_provider.name})"
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
    """Curator + Searcher 두 시나리오를 순차 실행한다."""
    rc1 = _run_single_agent(
        title="Knowledge Curator smoke — 가상 워크플로우 → YAML entry",
        factory_fn=lambda: create_knowledge_curator_agent(verbose=False),
        task_description=CURATOR_TASK_DESCRIPTION,
        task_expected_output=CURATOR_TASK_EXPECTED_OUTPUT,
        trace_name="test_knowledge_curator",
    )
    rc2 = _run_single_agent(
        title="RAG Searcher smoke — 새 요청 + entry 2건 → 추천",
        factory_fn=lambda: create_rag_searcher_agent(verbose=False),
        task_description=SEARCHER_TASK_DESCRIPTION,
        task_expected_output=SEARCHER_TASK_EXPECTED_OUTPUT,
        trace_name="test_rag_searcher",
    )
    return rc1 or rc2


# ---------------------------------------------------------------------------
# pytest 하네스 진입점 (네트워크 없이 FakeProvider 경유)
# ---------------------------------------------------------------------------
def test_knowledge_curator_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Knowledge Curator가 CrewAI를 통과하는지 검증한다."""
    curator = create_knowledge_curator_agent(verbose=False)
    assert curator.llm.backend_provider.name == "fake"

    task = Task(
        description=CURATOR_TASK_DESCRIPTION,
        expected_output=CURATOR_TASK_EXPECTED_OUTPUT,
        agent=curator,
    )
    result = Crew(agents=[curator], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Knowledge Curator kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


def test_rag_searcher_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 RAG Searcher가 CrewAI를 통과하는지 검증한다."""
    searcher = create_rag_searcher_agent(verbose=False)
    assert searcher.llm.backend_provider.name == "fake"

    task = Task(
        description=SEARCHER_TASK_DESCRIPTION,
        expected_output=SEARCHER_TASK_EXPECTED_OUTPUT,
        agent=searcher,
    )
    result = Crew(agents=[searcher], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "RAG Searcher kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


if __name__ == "__main__":
    sys.exit(main())
