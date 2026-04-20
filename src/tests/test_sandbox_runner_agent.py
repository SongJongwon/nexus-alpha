# -*- coding: utf-8 -*-
"""
Sandbox Runner 테스트 — 결정론적 실행자 + CrewAI Agent 양쪽 검증.

본 파일은 두 계층을 다른 깊이로 검증한다:

    1. **`run_python_in_sandbox` 함수** — 실제 subprocess를 띄워 PASS / FAIL /
       TIMEOUT / 입력 검증 4가지 시나리오를 모두 통과시킨다. LLM 미사용.
    2. **`create_sandbox_runner_agent` 팩토리** — 기존 5개 에이전트와 동일하게
       FakeProvider 패턴으로 CrewAI 통과만 검증.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_sandbox_runner_agent.py        # 직접 실행 (실제 LLM)
    .venv\\Scripts\\pytest.exe   src\\tests\\test_sandbox_runner_agent.py -v   # FakeProvider 경로
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

import pytest
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

load_dotenv(PROJECT_ROOT / ".env")

from crewai import Crew, Task

from src.agents.operations import (
    SandboxResult,
    create_sandbox_runner_agent,
    format_sandbox_result_for_task,
    run_python_in_sandbox,
)
from src.monitoring import get_langfuse_client


console = Console()


# =============================================================================
# 1. 결정론적 실행자 테스트 (실제 subprocess, LLM 무관)
# =============================================================================
def test_run_python_in_sandbox_pass_simple_print() -> None:
    """단순 print 코드가 PASS로 분류되고 stdout이 캡처되는지."""
    result = run_python_in_sandbox("print('hello sandbox')", timeout_sec=10)

    assert isinstance(result, SandboxResult)
    assert result.verdict == "PASS"
    assert result.exit_code == 0
    assert not result.timed_out
    assert "hello sandbox" in result.stdout
    assert result.stderr == ""
    assert 0 < result.elapsed_sec < 10


def test_run_python_in_sandbox_fail_captures_exit_code_and_traceback() -> None:
    """SystemExit(1) 또는 예외로 죽은 코드가 FAIL로 분류되고 stderr에 traceback이 잡히는지."""
    result = run_python_in_sandbox("raise ValueError('intentional')", timeout_sec=10)

    assert result.verdict == "FAIL"
    assert result.exit_code != 0
    assert not result.timed_out
    assert "ValueError" in result.stderr
    assert "intentional" in result.stderr


def test_run_python_in_sandbox_timeout_kills_long_running() -> None:
    """타임아웃 초과 시 verdict=TIMEOUT, exit_code=-1, timed_out=True 가 되는지.

    1초 타임아웃 + 5초 sleep 코드. 약 1초 만에 강제 종료되어야 한다.
    """
    result = run_python_in_sandbox(
        "import time; time.sleep(5); print('should not reach')",
        timeout_sec=1,
    )

    assert result.verdict == "TIMEOUT"
    assert result.timed_out is True
    assert result.exit_code == -1
    assert "should not reach" not in result.stdout
    # 1초 임계 + 약간의 종료 처리 여유. 5초까진 절대 안 가야 함.
    assert result.elapsed_sec < 4.0


def test_run_python_in_sandbox_validates_inputs() -> None:
    """잘못된 입력은 즉시 ValueError/TypeError로 거부되는지."""
    with pytest.raises(ValueError):
        run_python_in_sandbox("print(0)", timeout_sec=0)
    with pytest.raises(ValueError):
        run_python_in_sandbox("print(0)", timeout_sec=-5)
    with pytest.raises(TypeError):
        run_python_in_sandbox(b"print(0)", timeout_sec=10)  # type: ignore[arg-type]


def test_format_sandbox_result_for_task_includes_all_fields() -> None:
    """헬퍼가 verdict / exit_code / elapsed / stdout / stderr를 모두 포함하는지."""
    result = run_python_in_sandbox("print('out'); import sys; print('err', file=sys.stderr)", timeout_sec=10)
    text = format_sandbox_result_for_task(result, max_lines=5)

    assert "verdict: PASS" in text
    assert "exit_code: 0" in text
    assert "elapsed_sec:" in text
    assert "out" in text  # stdout 인용 확인
    assert "err" in text  # stderr 인용 확인


# =============================================================================
# 2. CrewAI Agent 팩토리 테스트 (FakeProvider 경유)
# =============================================================================
SAMPLE_FAIL_RESULT = SandboxResult(
    exit_code=1,
    stdout="loading config...\n",
    stderr=(
        "Traceback (most recent call last):\n"
        '  File "_sandbox_main.py", line 3, in <module>\n'
        "    raise ValueError('config key missing: API_KEY')\n"
        "ValueError: config key missing: API_KEY\n"
    ),
    elapsed_sec=0.234,
    timed_out=False,
    timeout_sec=30,
)

AGENT_TASK_DESCRIPTION = (
    "아래는 결정론적 실행자(`run_python_in_sandbox`)가 산출한 SandboxResult입니다. "
    "백스토리에 명시된 5단 구조(종합 판정 / 출력 인용 / 근본 원인 / 재현·다음 단계 / "
    "미관찰 영역)로 한국어 마크다운 보고서를 작성하세요.\n\n"
    f"--- SandboxResult ---\n{format_sandbox_result_for_task(SAMPLE_FAIL_RESULT)}"
)

AGENT_TASK_EXPECTED_OUTPUT = (
    "5단 구조의 한국어 실행 보고서. 마지막 줄은 `Final Answer:`로 시작하는 한 줄 "
    "(`PASS|FAIL|TIMEOUT (exit=<int>, elapsed=<X.XXX>s)` 형식)."
)


def test_sandbox_runner_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 응답으로 Sandbox Runner Agent가 CrewAI를 통과하는지 검증한다."""
    runner = create_sandbox_runner_agent(verbose=False)
    assert runner.llm.backend_provider.name == "fake"

    task = Task(
        description=AGENT_TASK_DESCRIPTION,
        expected_output=AGENT_TASK_EXPECTED_OUTPUT,
        agent=runner,
    )
    result = Crew(agents=[runner], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Sandbox Runner kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


# =============================================================================
# 3. 직접 실행 경로 (실제 LLM, 사람이 결과 보고)
# =============================================================================
def main() -> int:
    """결정론적 실행 1건 + 그 결과를 LLM Agent에게 해석시키는 1건을 순차 실행."""
    console.print(Rule("[bold cyan]Sandbox Runner smoke — 결정론적 실행 + LLM 해석[/bold cyan]"))

    # ─── 1단계: 결정론적 실행 ─────────────────────────────────────────────────
    console.print(Rule("[cyan]1단계: run_python_in_sandbox (LLM 무관)[/cyan]"))
    sample_code = (
        "x = 7\n"
        "y = 6\n"
        "print(f'product = {x * y}')\n"
        "import sys; print('a warning', file=sys.stderr)\n"
    )
    real_result = run_python_in_sandbox(sample_code, timeout_sec=10)
    console.print(
        Panel(
            f"[bold]verdict[/bold]: {real_result.verdict}\n"
            f"[bold]exit_code[/bold]: {real_result.exit_code}\n"
            f"[bold]elapsed[/bold]: {real_result.elapsed_sec}s\n"
            f"[bold]stdout[/bold]: {real_result.stdout.rstrip() or '(empty)'}\n"
            f"[bold]stderr[/bold]: {real_result.stderr.rstrip() or '(empty)'}",
            title="[green]SandboxResult[/green]",
            border_style="green",
        )
    )

    # ─── 2단계: LLM Agent가 결과 해석 ─────────────────────────────────────────
    console.print(Rule("[cyan]2단계: Sandbox Runner Agent 해석[/cyan]"))
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_sandbox_runner_agent",
        user_id="local-dev",
        metadata={"phase": "phase_2_p4", "agent": "sandbox_runner"},
    )

    try:
        agent = create_sandbox_runner_agent(verbose=False)
    except Exception as exc:
        console.print(Panel(f"[bold red]Agent 초기화 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    task_description = (
        "아래는 방금 결정론적 실행자가 산출한 SandboxResult입니다. 백스토리에 명시된 "
        "5단 구조로 한국어 보고서를 작성하세요.\n\n"
        f"--- SandboxResult ---\n{format_sandbox_result_for_task(real_result)}"
    )
    task = Task(
        description=task_description,
        expected_output=AGENT_TASK_EXPECTED_OUTPUT,
        agent=agent,
    )

    exit_code = 0
    try:
        with console.status("[yellow]Agent가 결과 해석 중...[/yellow]", spinner="dots"):
            crew_result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        exit_code = 1
    else:
        output_text = getattr(crew_result, "raw", None) or str(crew_result)
        console.print(Panel(output_text, title="[green]Agent 보고서[/green]", border_style="green"))

    monitor.end_trace()
    monitor.flush()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
