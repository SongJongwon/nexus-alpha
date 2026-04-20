# -*- coding: utf-8 -*-
"""
Platform Tester 테스트 — 결정론 함수 + Agent 양쪽 검증 (Phase 4.5 / v4 — 5/5).

본 파일은 두 계층을 모두 검증한다 (Sandbox Runner 패턴과 동일):

    1. **`test_executable_in_sandbox` 함수** — 실제 subprocess 를 띄워 PASS /
       CRASH / FAIL / TIMEOUT / 입력 검증 + verdict 자동 분류 8건.
       테스트 대상 실행 파일은 Python 인터프리터 자체(`sys.executable`)를 사용해
       `--version` / `-c <code>` 인자로 다양한 시나리오 시뮬레이션.
    2. **`create_platform_tester_agent` 팩토리** — 기존 다른 에이전트와 동일하게
       FakeProvider 패턴으로 CrewAI 통과만 검증 (1건).

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_platform_tester_agent.py
    .venv\\Scripts\\pytest.exe   src\\tests\\test_platform_tester_agent.py -v
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

from src.agents.build_release import (
    PlatformTestResult,
    create_platform_tester_agent,
    format_platform_test_result_for_task,
)
# pytest 가 함수명 prefix `test_` 를 모듈 스코프에서 collect 하려고 하므로
# 공개 함수 `test_executable_in_sandbox` 는 alias 로 import — collection 충돌 회피.
from src.agents.build_release.platform_tester import (
    test_executable_in_sandbox as run_executable_in_sandbox,
)
from src.monitoring import get_langfuse_client


console = Console()
PYTHON_EXE = Path(sys.executable)


# =============================================================================
# 1. 결정론 함수 — verdict 자동 분류 + 측정값
# =============================================================================
def test_pass_on_clean_normal_exit() -> None:
    """정상 종료(exit 0) → verdict=PASS."""
    result = run_executable_in_sandbox(PYTHON_EXE, args=["--version"], timeout_sec=10)

    assert isinstance(result, PlatformTestResult)
    assert result.verdict == "PASS"
    assert result.exit_code == 0
    assert not result.timed_out
    assert "Python" in result.stdout or "Python" in result.stderr  # python --version 위치 OS별 다름
    assert result.elapsed_sec < 5.0


def test_crash_on_immediate_nonzero_exit() -> None:
    """1초 이내 비정상 종료 → verdict=CRASH (가장 큰 위험 신호)."""
    result = run_executable_in_sandbox(
        PYTHON_EXE,
        args=["-c", "import sys; sys.exit(2)"],
        timeout_sec=10,
    )

    assert result.verdict == "CRASH"
    assert result.exit_code == 2
    assert not result.timed_out
    assert result.elapsed_sec < 1.0


def test_fail_on_delayed_nonzero_exit() -> None:
    """1초 이상 실행 후 비정상 종료 → verdict=FAIL (CRASH 와 구분)."""
    result = run_executable_in_sandbox(
        PYTHON_EXE,
        args=["-c", "import time; time.sleep(1.2); raise RuntimeError('boom')"],
        timeout_sec=10,
    )

    assert result.verdict == "FAIL"
    assert result.exit_code != 0
    assert result.elapsed_sec >= 1.0
    assert "RuntimeError" in result.stderr
    assert "boom" in result.stderr


def test_pass_on_long_running_gui_like_process() -> None:
    """타임아웃까지 살아있는 GUI 류 프로세스 → verdict=PASS (started_successfully).

    1초 timeout + 5초 sleep 코드. 강제 종료되지만 부팅엔 성공했으므로 PASS.
    """
    result = run_executable_in_sandbox(
        PYTHON_EXE,
        args=["-c", "import time; time.sleep(5)"],
        timeout_sec=1,
    )

    assert result.verdict == "PASS"  # GUI 류 — 부팅 성공 + timeout 도달은 정상
    assert result.timed_out is True
    assert result.started_successfully is True
    assert result.elapsed_sec < 4.0  # 1초 임계 + 강제 종료 여유


def test_validates_inputs() -> None:
    """잘못된 입력은 즉시 ValueError/TypeError/FileNotFoundError 로 거부."""
    with pytest.raises(FileNotFoundError):
        run_executable_in_sandbox(Path("nonexistent_xyz_123.exe"), timeout_sec=10)
    with pytest.raises(ValueError):
        run_executable_in_sandbox(PYTHON_EXE, timeout_sec=0)
    with pytest.raises(ValueError):
        run_executable_in_sandbox(PYTHON_EXE, timeout_sec=-5)
    with pytest.raises(TypeError):
        run_executable_in_sandbox("not a path", timeout_sec=10)  # type: ignore[arg-type]


def test_format_helper_includes_all_fields() -> None:
    """직렬화 헬퍼가 verdict/exit/startup/elapsed/timeout/stdout/stderr 모두 포함."""
    result = run_executable_in_sandbox(
        PYTHON_EXE, args=["-c", "print('hi'); import sys; print('warn', file=sys.stderr)"], timeout_sec=10
    )
    text = format_platform_test_result_for_task(result, max_lines=5)

    assert "verdict: PASS" in text
    assert "exit_code: 0" in text
    assert "startup_time_sec:" in text
    assert "elapsed_sec:" in text
    assert "started_successfully:" in text
    assert "exe_path:" in text
    assert "hi" in text   # stdout 인용 확인
    assert "warn" in text  # stderr 인용 확인


def test_started_successfully_true_for_long_running() -> None:
    """0.5초 이상 살아있는 프로세스는 started_successfully=True."""
    result = run_executable_in_sandbox(
        PYTHON_EXE, args=["-c", "import time; time.sleep(1.0)"], timeout_sec=5
    )

    assert result.started_successfully is True
    # 정상 종료 — verdict=PASS
    assert result.verdict == "PASS"


# =============================================================================
# 2. CrewAI Agent (FakeProvider 경유)
# =============================================================================
SAMPLE_RESULT = PlatformTestResult(
    exit_code=1,
    stdout="loading config...\n",
    stderr=(
        "Traceback (most recent call last):\n"
        '  File "calculator.exe", line 1, in <module>\n'
        "ImportError: DLL load failed while importing _ctypes: 지정된 모듈을 찾을 수 없습니다.\n"
    ),
    startup_time_sec=0.21,
    elapsed_sec=0.45,
    timed_out=False,
    timeout_sec=30,
    started_successfully=False,
    exe_path=Path("dist/calculator.exe"),
)

AGENT_TASK_DESCRIPTION = (
    "아래는 결정론 검증자(`test_executable_in_sandbox`) 가 산출한 PlatformTestResult "
    "입니다. 백스토리에 명시된 5단 구조(종합 판정 / 출력 인용 / 근본 원인 / 재현·"
    "다음 단계 / 미관찰 영역)로 한국어 보고서를 작성하세요. **verdict 는 절대 "
    "뒤집지 마세요.**\n\n"
    f"--- PlatformTestResult ---\n{format_platform_test_result_for_task(SAMPLE_RESULT)}\n"
    "[BUILD_CONTEXT]\nPyInstaller onefile, Windows, customtkinter 포함\n"
)

AGENT_TASK_EXPECTED_OUTPUT = (
    "5단 구조의 한국어 산출물 검증 보고서. 마지막 줄 `Final Answer: <verdict> "
    "(exit=<int>, startup=<X.X>s, elapsed=<X.X>s)`."
)


def test_platform_tester_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 경유로 Platform Tester Agent 가 CrewAI 통과."""
    agent = create_platform_tester_agent(verbose=False)
    assert agent.llm.backend_provider.name == "fake"

    task = Task(
        description=AGENT_TASK_DESCRIPTION,
        expected_output=AGENT_TASK_EXPECTED_OUTPUT,
        agent=agent,
    )
    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Platform Tester kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


# =============================================================================
# 3. 직접 실행 경로 (실제 LLM, 사람이 결과 보고)
# =============================================================================
def main() -> int:
    """실제 .exe 가 없으므로 Python 인터프리터로 시나리오 시뮬레이션 + LLM narration."""
    console.print(Rule("[bold cyan]Platform Tester smoke — 결정론 검증 + LLM narration[/bold cyan]"))

    # 1단계: 실제 subprocess 로 검증
    console.print(Rule("[cyan]1단계: test_executable_in_sandbox (LLM 무관)[/cyan]"))
    real_result = run_executable_in_sandbox(
        PYTHON_EXE,
        args=["-c", "print('NexusAlpha smoke OK'); import sys; print('warn one', file=sys.stderr)"],
        timeout_sec=10,
    )
    console.print(
        Panel(
            f"[bold]verdict[/bold]: {real_result.verdict}\n"
            f"[bold]exit_code[/bold]: {real_result.exit_code}\n"
            f"[bold]startup_time[/bold]: {real_result.startup_time_sec}s\n"
            f"[bold]elapsed[/bold]: {real_result.elapsed_sec}s\n"
            f"[bold]started_successfully[/bold]: {real_result.started_successfully}\n"
            f"[bold]stdout[/bold]: {real_result.stdout.rstrip() or '(empty)'}\n"
            f"[bold]stderr[/bold]: {real_result.stderr.rstrip() or '(empty)'}",
            title="[green]PlatformTestResult[/green]",
            border_style="green",
        )
    )

    # 2단계: LLM Agent narration
    console.print(Rule("[cyan]2단계: Platform Tester Agent narration[/cyan]"))
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="test_platform_tester_agent",
        user_id="local-dev",
        metadata={"phase": "phase_4_5", "agent": "platform_tester"},
    )

    try:
        agent = create_platform_tester_agent(verbose=False)
    except Exception as exc:
        console.print(Panel(f"[bold red]Agent 초기화 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    task_desc = (
        "아래 결정론 검증 결과를 받아 백스토리 5단 구조의 한국어 보고서를 작성하세요. "
        "verdict 는 절대 뒤집지 마세요.\n\n"
        f"--- PlatformTestResult ---\n{format_platform_test_result_for_task(real_result)}\n"
        "[BUILD_CONTEXT]\n실제 .exe 가 아닌 Python 인터프리터 시뮬레이션\n"
    )
    task = Task(
        description=task_desc,
        expected_output=AGENT_TASK_EXPECTED_OUTPUT,
        agent=agent,
    )

    try:
        with console.status("[yellow]Agent narration 중...[/yellow]", spinner="dots"):
            crew_result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        monitor.end_trace()
        monitor.flush()
        return 1

    output_text = getattr(crew_result, "raw", None) or str(crew_result)
    console.print(Panel(output_text, title="[green]Agent 보고서[/green]", border_style="green"))
    monitor.end_trace()
    monitor.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
