# -*- coding: utf-8 -*-
"""
v3 Iteration Controller 테스트 (Phase 2.5 / v3 PR-C).

본 파일은 두 계층을 검증한다:

    1. **결정론 헬퍼** — `_route_after_judge`, `_detect_stagnation`,
       `_format_feedback_for_next_iteration`. LLM 무관, 빠른 단위 테스트.
    2. **`run_iterative_loop` E2E** — FakeProvider 경유로 루프 한 바퀴 완주.
       FakeProvider 의 고정 응답이 Gap Analyst 에서 YAML 로 파싱되지 않아
       빈 `GapReport` 로 fallback → 0 unsatisfied → COMPLETE 로 1회 iter 만에
       종료. 이 경로를 통해 graph 조립·노드 메르지·종결 노드 라우팅을 검증.

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_iterative_loop.py        # 직접 실행 (실제 LLM)
    .venv\\Scripts\\pytest.exe   src\\tests\\test_iterative_loop.py -v   # FakeProvider 경로
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

from src.agents.c_level import (
    NO_BUDGET_GATE,
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
)
from src.workflows import (
    LoopOutcome,
    build_iterative_loop_graph,
    run_iterative_loop,
)
from src.workflows.iterative_loop import (
    _detect_stagnation,
    _format_feedback_for_next_iteration,
    _format_gap_analyst_input,
    _route_after_judge,
)


console = Console()


# =============================================================================
# 1. 결정론 헬퍼 단위 테스트
# =============================================================================
def test_route_after_judge_complete_dispatches_to_finalize() -> None:
    state = {
        "decision": JudgmentDecision(
            verdict=Verdict.COMPLETE,
            blocked_cause=BlockedCause.NONE,
            reason="ok",
            next_action="ok",
            must_fix_count=0,
        )
    }
    assert _route_after_judge(state) == "finalize"


def test_route_after_judge_improve_dispatches_to_feedback() -> None:
    state = {
        "decision": JudgmentDecision(
            verdict=Verdict.IMPROVE_NEEDED,
            blocked_cause=BlockedCause.NONE,
            reason="ok",
            next_action="ok",
            must_fix_count=2,
        )
    }
    assert _route_after_judge(state) == "prepare_feedback"


def test_route_after_judge_blocked_dispatches_to_escalate() -> None:
    state = {
        "decision": JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.STAGNATION,
            reason="ok",
            next_action="ok",
            must_fix_count=3,
        )
    }
    assert _route_after_judge(state) == "escalate"


# -- stagnation proxy --------------------------------------------------------
def test_detect_stagnation_needs_at_least_3_iterations() -> None:
    """history < 3 이면 항상 False (비교 불가)."""
    assert _detect_stagnation([]) is False
    assert _detect_stagnation([5]) is False
    assert _detect_stagnation([5, 6]) is False


def test_detect_stagnation_two_consecutive_non_increases() -> None:
    """satisfied_count 가 2회 연속 비증가 시 True."""
    # iter1=3, iter2=3, iter3=3 → 비증가 2회 (3→3, 3→3) → True
    assert _detect_stagnation([3, 3, 3]) is True
    # iter1=3, iter2=4, iter3=4 → 비증가 1회만 → False
    assert _detect_stagnation([3, 4, 4]) is False
    # iter1=5, iter2=4, iter3=3 → 감소 (비증가 2회) → True
    assert _detect_stagnation([5, 4, 3]) is True


def test_detect_stagnation_resumes_progress_resets_signal() -> None:
    """[3, 3, 4] — 마지막에 증가했으면 stagnation 아님."""
    assert _detect_stagnation([3, 3, 4]) is False


# -- feedback formatter ------------------------------------------------------
def test_format_feedback_includes_must_fix_counts_and_action() -> None:
    gap = GapReport(unsatisfied_blockers=2, unsatisfied_majors=1, ambiguous_count=1)
    decision = JudgmentDecision(
        verdict=Verdict.IMPROVE_NEEDED,
        blocked_cause=BlockedCause.NONE,
        reason="3 must-fix remain",
        next_action="Re-enter loop with focus on N-001",
        must_fix_count=3,
    )
    text = _format_feedback_for_next_iteration(gap, decision)

    assert "blocker" in text
    assert "major" in text
    assert "3건" in text
    assert "Re-enter loop" in text
    assert "회귀" in text  # 핵심 지시 키워드


def test_format_gap_analyst_input_has_all_5_blocks() -> None:
    """Gap Analyst 백스토리가 가정하는 5블록(SPEC/ENGINEER/QA/EXECUTION/PREVIOUS) 포함."""

    class FakeChain:
        engineer_output = "engineer text"
        qa_review = "qa text"

    text = _format_gap_analyst_input(
        spec_markdown="SPEC HERE",
        chain_result=FakeChain(),  # type: ignore[arg-type]
        prev_gap_raw="prev gap",
        iteration=2,
    )
    assert "[REQUIREMENT_SPEC]" in text
    assert "SPEC HERE" in text
    assert "[ENGINEER_OUTPUT]" in text
    assert "engineer text" in text
    assert "[QA_REVIEW]" in text
    assert "[EXECUTION_RESULT]" in text
    assert "[PREVIOUS_GAP_REPORT]" in text
    assert "prev gap" in text
    assert "본 iteration 번호: 2" in text


# =============================================================================
# 2. Graph 조립 — compile 가능한지
# =============================================================================
def test_build_iterative_loop_graph_compiles() -> None:
    compiled = build_iterative_loop_graph()
    nodes = set(compiled.get_graph().nodes)
    expected = {
        "__start__",
        "__end__",
        "expand_requirements",
        "run_chain",
        "analyze_gap",
        "judge_convergence",
        "prepare_feedback",
        "finalize",
        "escalate",
    }
    assert expected.issubset(nodes), f"missing nodes: {expected - nodes}"


# =============================================================================
# 3. E2E — FakeProvider 로 루프 1회 완주 (COMPLETE 경로)
# =============================================================================
def test_run_iterative_loop_completes_with_fake_provider(tmp_path: Path) -> None:
    """FakeProvider 응답에는 YAML 갭 정보가 없어 빈 GapReport 로 fallback →
    must_fix=0 → COMPLETE 1회 iter 만에 종료.

    `tmp_path` 로 outputs 격리.
    """
    outcome = run_iterative_loop(
        "FakeProvider 경유 단순 검증 요청",
        max_iterations=5,
        budget_tokens_remaining=NO_BUDGET_GATE,
        outputs_dir=tmp_path,
    )

    assert isinstance(outcome, LoopOutcome)
    assert outcome.verdict == Verdict.COMPLETE
    assert outcome.blocked_cause == BlockedCause.NONE
    assert outcome.iterations_run == 1, (
        f"FakeProvider 시나리오는 1회 iter 만에 COMPLETE 여야 한다. "
        f"실제: {outcome.iterations_run}"
    )
    # spec 마크다운에 FakeProvider 표지가 포함되어야 함
    assert "FakeProvider" in outcome.spec_markdown
    # 1회 iter 의 chain 산출물이 tmp_path 아래 생성되었어야 함
    assert len(outcome.iteration_artifacts) == 1
    assert outcome.iteration_artifacts[0].parent == tmp_path
    # 첫 iter 라 feedback 누적 없음
    assert outcome.feedback_history == []


def test_run_iterative_loop_outcome_dataclass_fields(tmp_path: Path) -> None:
    """LoopOutcome 의 모든 핵심 필드가 채워지는지."""
    outcome = run_iterative_loop(
        "단순 검증 요청 — 필드 채움 확인",
        outputs_dir=tmp_path,
    )
    assert outcome.user_request
    assert isinstance(outcome.verdict, Verdict)
    assert isinstance(outcome.blocked_cause, BlockedCause)
    assert outcome.iterations_run >= 1
    assert outcome.spec_markdown
    assert outcome.final_chain_result is not None
    assert outcome.final_decision is not None
    assert isinstance(outcome.final_gap_report, GapReport)


# =============================================================================
# 4. 직접 실행 경로 (실제 LLM)
# =============================================================================
def main() -> int:
    """실제 LLM 으로 루프 한 바퀴 — 사용자가 결과를 눈으로 확인하는 용도."""
    console.print(Rule("[bold cyan]Iterative Loop smoke — run_iterative_loop 1회[/bold cyan]"))
    console.print(
        "[yellow]주의: 실제 LLM 호출 — 수 분 소요 + LangFuse 기록.[/yellow]"
    )

    outcome = run_iterative_loop(
        "사칙연산 계산기 Python 앱을 만들어줘. 파일명: calculator.py",
        max_iterations=3,  # 직접 실행은 보수적으로
        budget_tokens_remaining=NO_BUDGET_GATE,
    )

    console.print(
        Panel(
            f"[bold]verdict[/bold]: {outcome.verdict.value}\n"
            f"[bold]blocked_cause[/bold]: {outcome.blocked_cause.value}\n"
            f"[bold]iterations_run[/bold]: {outcome.iterations_run}\n"
            f"[bold]final_decision.reason[/bold]: {outcome.final_decision.reason if outcome.final_decision else '(none)'}\n"
            f"[bold]artifacts[/bold]: {len(outcome.iteration_artifacts)} dir(s)",
            title="[green]LoopOutcome[/green]",
            border_style="green",
        )
    )
    for i, p in enumerate(outcome.iteration_artifacts, 1):
        console.print(f"  iter {i}: [cyan]{p.relative_to(PROJECT_ROOT)}[/cyan]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
