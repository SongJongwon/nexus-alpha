# -*- coding: utf-8 -*-
"""
Python Engineer 에이전트 단독 smoke test.

검증 항목:
    1) `create_python_engineer_agent()`가 `NexusAlphaLLM`을 자동 주입해 생성되는지
    2) CrewAI `Crew`로 단일 Task 실행 시 실제 Python 코드가 산출되는지
    3) 실행 전체가 LangFuse에 `test_python_engineer_agent` trace로 기록되는지
    4) 생성된 산출물이 `outputs/` 폴더에 저장되는지

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_python_engineer_agent.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
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

from src.agents.engineering import create_python_engineer_agent
from src.monitoring import get_langfuse_client


console = Console()
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


# ---------------------------------------------------------------------------
# 선행 에이전트 산출물(요약) — 실제 워크플로우에서는 Task 체인으로 주입됨
# ---------------------------------------------------------------------------
CTO_STRATEGY_SUMMARY = (
    "[CTO 전략 요약]\n"
    "- 목적: 월별 매출 Excel(.xlsx)을 임원용 PDF 보고서로 자동 변환.\n"
    "- 기술 스택: openpyxl + pandas (데이터), matplotlib (차트, Noto Sans KR), "
    "Jinja2 + WeasyPrint (PDF 렌더링).\n"
    "- 디렉터리 규약: loader / transform / chart / render / cli 모듈 분리.\n"
    "- 품질 요구: 타입 힌트, docstring, pytest 단위 테스트 동반."
)

ANALYST_BRIEF_SUMMARY = (
    "[Data Analyst 지시서 핵심 요약]\n"
    "1) 데이터 품질: 7개 컬럼 스키마 검증, 결측치 비율 ≥1% 시 경고, "
    "(year_month, category, region) 복합키 중복 체크.\n"
    "2) 핵심 지표 5개:\n"
    "   ① 월 매출 총액 (sales_amount_krw 월 합계, 단위: 백만 원)\n"
    "   ② MoM 성장률 ((당월-전월)/전월 × 100, 단위 %, 소수점 첫째 자리)\n"
    "   ③ 카테고리별 매출 비중 (카테고리 합계 / 전체 합계 × 100)\n"
    "   ④ 지역별 매출 & 반품률 (returns_count / orders_count)\n"
    "   ⑤ 객단가 AOV (sales_amount_krw / orders_count)\n"
    "3) 추천 차트 3종:\n"
    "   - 월별 매출 라인차트 (추세 메시지)\n"
    "   - 카테고리×지역 히트맵 (구조 메시지)\n"
    "   - 지역 버블차트: X=매출, Y=반품률, 버블크기=주문수 (사분면 해석)\n"
    "4) 이상치: IQR 1차 + z-score≥3 2차, 반품률 5% 초과 시 경고 플래그.\n"
    "5) 분석가 코멘트 배치:\n"
    "   - Executive Summary 1페이지 상단에 KPI 카드 + 추세 화살표\n"
    "   - 반품률 경고 팝업 (임계 초과 시 자동 렌더)\n"
    "   - 데이터 품질 디스클레이머(누락 조합 수 명시)."
)

TASK_REQUEST = (
    "위 전략과 지시서를 모두 만족하는, **월별 매출 Excel → PDF 보고서 "
    "변환 Python 스크립트 세트**를 작성하세요.\n\n"
    "구현 요구:\n"
    "  - `openpyxl`/`pandas`로 Excel 로드 (경로를 인자로 받음)\n"
    "  - 5개 지표 계산 함수를 별도 모듈(`metrics.py`)에 분리, 각 함수는 "
    "    순수 함수로 pandas DataFrame을 입력받음\n"
    "  - `matplotlib`로 3종 차트를 PNG(300 dpi)로 저장. 한글 폰트 설정 포함\n"
    "  - `Jinja2` 템플릿 + `WeasyPrint`로 PDF 렌더 (차트 이미지 embed)\n"
    "  - 모든 공개 함수에 타입 힌트와 한국어/영문 docstring\n"
    "  - `pytest` 단위 테스트 최소 3건 (지표 계산 함수 중심)\n"
    "  - `python -m excel2pdf --input sample.xlsx --output report.pdf` "
    "    형태로 실행 가능한 CLI (`typer` 또는 `argparse` 택1)\n"
    "  - 외부 I/O 지점에만 예외 처리, 내부 계산 함수는 입력 계약을 신뢰\n\n"
    "산출 규약(필수):\n"
    "  - 각 파일은 ```python 블록으로 감싸고, 맨 첫 줄에 "
    "    `# file: <상대경로>` 헤더 주석 포함\n"
    "  - 마지막 섹션에 설치·실행 방법을 한국어로 정리"
)

TASK_EXPECTED_OUTPUT = (
    "모듈별로 분리된 실행 가능한 Python 코드(파일 여러 개)와 pytest 테스트, "
    "설치·실행 가이드를 포함한 완전한 구현 산출물"
)


# ---------------------------------------------------------------------------
# 산출물 저장 헬퍼
# ---------------------------------------------------------------------------
def save_artifacts(raw_output: str, timestamp: str) -> tuple[Path, list[Path]]:
    """Engineer의 응답을 `outputs/`에 저장한다.

    Args:
        raw_output: 에이전트가 산출한 마크다운 전체 텍스트.
        timestamp: 파일명에 사용할 타임스탬프(`YYYYMMDD_HHMMSS`).

    Returns:
        (마크다운 파일 경로, [추출된 코드 파일 경로, ...])
    """
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUTS_DIR / f"python_engineer_{timestamp}.md"
    md_path.write_text(raw_output, encoding="utf-8")

    # ```python 코드 블록 추출 → 각 블록을 .py로 저장
    code_paths: list[Path] = []
    pattern = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
    for idx, block in enumerate(pattern.findall(raw_output), start=1):
        # 파일명 힌트가 있으면(`# file: ...py`) 해당 이름 사용
        first_line = block.splitlines()[0] if block.strip() else ""
        name_match = re.match(r"#\s*file:\s*(\S+\.py)", first_line)
        if name_match:
            safe_name = name_match.group(1).replace("/", "__").replace("\\", "__")
            file_path = OUTPUTS_DIR / f"python_engineer_{timestamp}__{safe_name}"
        else:
            file_path = OUTPUTS_DIR / f"python_engineer_{timestamp}__block{idx:02d}.py"
        file_path.write_text(block, encoding="utf-8")
        code_paths.append(file_path)

    return md_path, code_paths


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def main() -> int:
    """Python Engineer 에이전트를 실행하고 종료 코드를 반환한다."""
    console.print(
        Rule("[bold cyan]Python Engineer smoke test — Excel → PDF 코드 생성[/bold cyan]")
    )

    monitor = get_langfuse_client()
    console.print(
        f"[bold]Monitoring:[/bold] "
        f"{'[green]LangFuse 활성[/green]' if monitor.enabled else '[yellow]LangFuse 비활성 (키 누락)[/yellow]'}"
    )
    monitor.log_trace(
        name="test_python_engineer_agent",
        user_id="local-dev",
        metadata={
            "phase": "phase_1",
            "agent": "python_engineer",
            "scenario": "excel_to_pdf_code_gen",
        },
    )

    try:
        engineer = create_python_engineer_agent()
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Python Engineer 초기화 실패:[/bold red] {exc}",
                title="오류",
                border_style="red",
            )
        )
        monitor.end_trace()
        monitor.flush()
        return 1

    console.print(f"[bold]Agent    :[/bold] {engineer.role}")
    console.print(
        f"[bold]LLM      :[/bold] NexusAlphaLLM "
        f"(backend={engineer.llm.backend_provider.name})"
    )
    console.print(Rule())

    task_description = (
        f"{CTO_STRATEGY_SUMMARY}\n\n{ANALYST_BRIEF_SUMMARY}\n\n{TASK_REQUEST}"
    )
    task = Task(
        description=task_description,
        expected_output=TASK_EXPECTED_OUTPUT,
        agent=engineer,
    )
    crew = Crew(agents=[engineer], tasks=[task], verbose=False)

    exit_code = 0
    raw_output = ""
    try:
        with console.status(
            "[yellow]Python Engineer가 코드를 작성 중... (긴 응답 예상)[/yellow]",
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
        raw_output = getattr(result, "raw", None) or str(result)
        if not raw_output.strip():
            console.print(
                Panel(
                    "[yellow]Engineer 응답이 비어 있습니다.[/yellow]",
                    title="경고",
                    border_style="yellow",
                )
            )
            exit_code = 1

    # LangFuse는 먼저 flush
    monitor.end_trace()
    monitor.flush()

    # 산출물 저장 (성공한 경우만)
    saved_md: Path | None = None
    saved_code: list[Path] = []
    if exit_code == 0 and raw_output.strip():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_md, saved_code = save_artifacts(raw_output, ts)

    # 응답 요약 출력 (너무 길 수 있으므로 앞부분만)
    if raw_output.strip():
        preview = raw_output if len(raw_output) <= 4000 else raw_output[:4000] + "\n\n... (중략 — 전체는 outputs/에 저장됨) ..."
        console.print(
            Panel(
                preview,
                title="[green]Engineer 응답 (미리보기)[/green]",
                border_style="green",
            )
        )

    # 저장 경로 안내
    if saved_md is not None:
        console.print(Rule())
        rel_md = saved_md.relative_to(PROJECT_ROOT)
        lines = [f"[bold]마크다운 전체:[/bold] [cyan]{rel_md}[/cyan]"]
        if saved_code:
            lines.append(
                f"[bold]추출된 코드 파일:[/bold] {len(saved_code)}개"
            )
            for p in saved_code:
                lines.append(f"  - [cyan]{p.relative_to(PROJECT_ROOT)}[/cyan]")
        else:
            lines.append("[yellow]```python 코드 블록을 추출하지 못했습니다.[/yellow]")
        console.print(Panel("\n".join(lines), title="[green]산출물 저장[/green]", border_style="green"))

    if monitor.enabled:
        console.print(Rule())
        console.print(
            Panel(
                f"실행 기록이 LangFuse로 전송되었습니다.\n"
                f"대시보드: [cyan]{monitor.host}[/cyan]\n"
                f"(trace: [bold]test_python_engineer_agent[/bold])",
                title="[green]LangFuse[/green]",
                border_style="green",
            )
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
