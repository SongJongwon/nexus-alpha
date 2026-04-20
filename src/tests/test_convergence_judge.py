# -*- coding: utf-8 -*-
"""
Convergence Judge 테스트 — 결정표 + YAML 파서 + Agent 양쪽 검증 (Phase 2.5 / v3).

본 파일은 세 계층을 모두 검증한다:

    1. **`judge_convergence` 결정표** — 모든 verdict 분기 (COMPLETE / IMPROVE /
       BLOCKED 3종) + BLOCKED 우선순위(STAGNATION > BUDGET > ITER_CAP) +
       must_fix 일반화 규칙(blocker + major). 8건.
    2. **`parse_gap_report_from_yaml` 파서** — Gap Analyst 마크다운 통째 파싱,
       YAML 본문 직접 파싱, 결측 필드, 잘못된 입력. 4건.
    3. **`create_convergence_judge_agent` 팩토리** — FakeProvider 패턴 (1건).

실행:
    .venv\\Scripts\\python.exe src\\tests\\test_convergence_judge.py        # 직접 실행
    .venv\\Scripts\\pytest.exe   src\\tests\\test_convergence_judge.py -v   # FakeProvider
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

from src.agents.c_level import (
    DEFAULT_MAX_ITERATIONS,
    NO_BUDGET_GATE,
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    create_convergence_judge_agent,
    format_judgment_decision_for_task,
    judge_convergence,
    parse_gap_report_from_yaml,
)


console = Console()


# =============================================================================
# 1. 결정표 — verdict 분기 검증
# =============================================================================
def test_judge_complete_clean_no_unsatisfied() -> None:
    """미충족 0건 → COMPLETE / NONE."""
    decision = judge_convergence(GapReport(satisfied_count=5, iteration=1))
    assert decision.verdict == Verdict.COMPLETE
    assert decision.blocked_cause == BlockedCause.NONE
    assert decision.must_fix_count == 0
    assert "satisfied" in decision.reason.lower()


def test_judge_complete_with_minor_caveat() -> None:
    """blocker/major 0이지만 minor 있음 → COMPLETE + caveat 안내."""
    decision = judge_convergence(GapReport(unsatisfied_minors=2, iteration=2))
    assert decision.verdict == Verdict.COMPLETE
    assert decision.must_fix_count == 0
    assert "minor" in decision.reason.lower() or "caveat" in decision.reason.lower()
    assert "caveat" in decision.next_action.lower() or "minor" in decision.next_action.lower()


def test_judge_improve_needed_blocker_safe() -> None:
    """blocker 있음 + 모든 안전 조건 OK → IMPROVE_NEEDED."""
    decision = judge_convergence(
        GapReport(unsatisfied_blockers=1, iteration=2),
        max_iterations=5,
        budget_tokens_remaining=10000,
    )
    assert decision.verdict == Verdict.IMPROVE_NEEDED
    assert decision.blocked_cause == BlockedCause.NONE
    assert decision.must_fix_count == 1


def test_judge_improve_needed_major_only_treated_as_must_fix() -> None:
    """blocker 0이지만 major 있음 → IMPROVE_NEEDED (major도 must_fix 로 일반화)."""
    decision = judge_convergence(GapReport(unsatisfied_majors=2, iteration=1))
    assert decision.verdict == Verdict.IMPROVE_NEEDED
    assert decision.must_fix_count == 2


# =============================================================================
# 결정표 — BLOCKED 우선순위 (STAGNATION > BUDGET > ITERATION_CAP)
# =============================================================================
def test_judge_blocked_stagnation_takes_priority() -> None:
    """STAGNATION 은 다른 모든 BLOCKED 원인보다 우선 — 동시 위반 시 STAGNATION 선택."""
    decision = judge_convergence(
        GapReport(unsatisfied_blockers=2, stagnation=True, iteration=5),
        max_iterations=5,
        budget_tokens_remaining=0,  # budget도 소진된 상태
    )
    assert decision.verdict == Verdict.BLOCKED
    assert decision.blocked_cause == BlockedCause.STAGNATION


def test_judge_blocked_budget_when_no_stagnation() -> None:
    """stagnation 없을 때 budget 소진은 BLOCKED(BUDGET_EXHAUSTED)."""
    decision = judge_convergence(
        GapReport(unsatisfied_blockers=1, iteration=2, stagnation=False),
        budget_tokens_remaining=0,
    )
    assert decision.verdict == Verdict.BLOCKED
    assert decision.blocked_cause == BlockedCause.BUDGET_EXHAUSTED


def test_judge_blocked_iteration_cap_last_resort() -> None:
    """stagnation·budget OK 일 때 iter cap 도달은 BLOCKED(ITERATION_CAP)."""
    decision = judge_convergence(
        GapReport(unsatisfied_blockers=1, iteration=5, stagnation=False),
        max_iterations=5,
        budget_tokens_remaining=10000,
    )
    assert decision.verdict == Verdict.BLOCKED
    assert decision.blocked_cause == BlockedCause.ITERATION_CAP


def test_judge_no_budget_gate_sentinel_skips_budget_check() -> None:
    """budget_tokens_remaining=NO_BUDGET_GATE(-1) 면 음수여도 budget 검사 안 함."""
    decision = judge_convergence(
        GapReport(unsatisfied_blockers=1, iteration=2),
        budget_tokens_remaining=NO_BUDGET_GATE,
    )
    # iter 2 / max 5, no stagnation, no budget gate → IMPROVE_NEEDED
    assert decision.verdict == Verdict.IMPROVE_NEEDED


# =============================================================================
# 2. YAML 파서
# =============================================================================
GAP_ANALYST_FULL_MARKDOWN = """\
## 갭 보고서

```yaml
satisfied:
  - id: F-001
    evidence: calculator.py:add — 덧셈 함수 구현
  - id: F-002
    evidence: calculator.py:divide — ZeroDivisionError 처리
unsatisfied:
  - id: N-001
    severity: blocker
    reason: GUI 미구현, CLI 만 산출
  - id: N-002
    severity: major
    reason: 단위 테스트 0건
  - id: F-003
    severity: minor
    reason: 에러 메시지 영문/한글 혼재
ambiguous:
  - id: F-004
    reason: "정밀도 요구 미명시 — Decimal vs float 판단 불가"
stagnation:
  iteration: 3
  resolved_gaps_since_last: 0
  new_gaps_since_last: 1
  stagnation: false
```

## 분석가 코멘트
가장 시급한 N-001(GUI 미구현)을 다음 iteration에서 잡아야 함.
"""


def test_parse_gap_report_from_full_markdown() -> None:
    """Gap Analyst 산출 마크다운 통째에서 ```yaml 블록 추출 + 파싱."""
    gap = parse_gap_report_from_yaml(GAP_ANALYST_FULL_MARKDOWN)

    assert gap.satisfied_count == 2
    assert gap.unsatisfied_blockers == 1
    assert gap.unsatisfied_majors == 1
    assert gap.unsatisfied_minors == 1
    assert gap.ambiguous_count == 1
    assert gap.iteration == 3
    assert gap.stagnation is False


def test_parse_gap_report_from_raw_yaml_body() -> None:
    """블록 펜스 없는 YAML 본문도 지원."""
    yaml_body = (
        "satisfied: []\n"
        "unsatisfied:\n"
        "  - id: F-001\n"
        "    severity: blocker\n"
    )
    gap = parse_gap_report_from_yaml(yaml_body)
    assert gap.unsatisfied_blockers == 1
    assert gap.satisfied_count == 0


def test_parse_gap_report_handles_missing_fields() -> None:
    """선택적 필드 누락 시 기본값으로 채워지는지."""
    yaml_body = "satisfied: []\nunsatisfied: []\n"  # ambiguous, stagnation 누락
    gap = parse_gap_report_from_yaml(yaml_body, iteration=7)
    assert gap.satisfied_count == 0
    assert gap.unsatisfied_blockers == 0
    assert gap.ambiguous_count == 0
    assert gap.stagnation is False
    assert gap.iteration == 7  # fallback iteration 인자 사용


def test_parse_gap_report_invalid_yaml_raises() -> None:
    """파싱 불가 입력은 ValueError."""
    with pytest.raises(ValueError):
        parse_gap_report_from_yaml("- this is\n  : not valid: : yaml [{")
    with pytest.raises(ValueError):
        # YAML 은 파싱되지만 최상위가 list (dict 아님)
        parse_gap_report_from_yaml("- one\n- two\n")


# =============================================================================
# 3. 직렬화 헬퍼
# =============================================================================
def test_format_judgment_decision_includes_all_fields() -> None:
    """Agent Task description 직렬화가 모든 필드를 포함하는지."""
    gap = GapReport(
        satisfied_count=3,
        unsatisfied_blockers=1,
        unsatisfied_majors=2,
        unsatisfied_minors=1,
        ambiguous_count=0,
        stagnation=False,
        iteration=2,
    )
    decision = judge_convergence(gap, max_iterations=5, budget_tokens_remaining=5000)
    text = format_judgment_decision_for_task(decision, gap)

    assert "verdict: IMPROVE_NEEDED" in text
    assert "blocked_cause: NONE" in text
    assert "must_fix_count: 3" in text
    assert "iteration: 2" in text
    assert "blocker=1" in text
    assert "major=2" in text


# =============================================================================
# 4. CrewAI Agent (FakeProvider 경유)
# =============================================================================
SAMPLE_DECISION = JudgmentDecision(
    verdict=Verdict.BLOCKED,
    blocked_cause=BlockedCause.STAGNATION,
    reason="2 must-fix item(s) remain AND stagnation detected",
    next_action="Escalate to user with unresolved gap list.",
    must_fix_count=2,
)
SAMPLE_GAP = GapReport(
    satisfied_count=4,
    unsatisfied_blockers=2,
    unsatisfied_majors=0,
    unsatisfied_minors=1,
    ambiguous_count=1,
    stagnation=True,
    iteration=4,
)

AGENT_TASK_DESCRIPTION = (
    "아래는 결정표(`judge_convergence`)가 산출한 JudgmentDecision 입니다. "
    "백스토리에 명시된 4단 구조(판정 / 결정 근거 / 다음 행동 / 메모)로 한국어 "
    "보고서를 작성하세요. **verdict 는 절대 뒤집지 마세요.**\n\n"
    f"--- JudgmentDecision ---\n{format_judgment_decision_for_task(SAMPLE_DECISION, SAMPLE_GAP)}"
)

AGENT_TASK_EXPECTED_OUTPUT = (
    "4단 구조의 한국어 수렴 판정 보고서. 마지막 줄은 `Final Answer:` 로 시작 "
    "(`<verdict> (cause=<cause>, must_fix=<N>)` 형식)."
)


def test_convergence_judge_agent_runs_through_crew_with_fake_provider() -> None:
    """FakeProvider 경유로 Convergence Judge Agent 가 CrewAI 통과."""
    judge = create_convergence_judge_agent(verbose=False)
    assert judge.llm.backend_provider.name == "fake"

    task = Task(
        description=AGENT_TASK_DESCRIPTION,
        expected_output=AGENT_TASK_EXPECTED_OUTPUT,
        agent=judge,
    )
    result = Crew(agents=[judge], tasks=[task], verbose=False).kickoff()
    output_text = getattr(result, "raw", None) or str(result)

    assert output_text.strip(), "Convergence Judge kickoff 결과가 비어 있으면 안 된다"
    assert "FakeProvider가 반환한 고정 응답" in output_text


# =============================================================================
# 5. 직접 실행 경로 (실제 LLM)
# =============================================================================
def main() -> int:
    """샘플 BLOCKED(STAGNATION) 결정을 실제 LLM 으로 narration 시킴."""
    console.print(Rule("[bold cyan]Convergence Judge smoke — 결정표 + LLM narration[/bold cyan]"))

    # 1) 결정표 단독 (LLM 없음)
    console.print(Rule("[cyan]1단계: judge_convergence 결정표 (LLM 무관)[/cyan]"))
    decision = judge_convergence(SAMPLE_GAP, max_iterations=DEFAULT_MAX_ITERATIONS)
    console.print(
        Panel(
            f"[bold]verdict[/bold]: {decision.verdict.value}\n"
            f"[bold]blocked_cause[/bold]: {decision.blocked_cause.value}\n"
            f"[bold]must_fix_count[/bold]: {decision.must_fix_count}\n"
            f"[bold]reason[/bold]: {decision.reason}\n"
            f"[bold]next_action[/bold]: {decision.next_action}",
            title="[green]JudgmentDecision[/green]",
            border_style="green",
        )
    )

    # 2) LLM Agent 가 narration
    console.print(Rule("[cyan]2단계: Convergence Judge Agent narration[/cyan]"))
    try:
        agent = create_convergence_judge_agent(verbose=False)
    except Exception as exc:
        console.print(Panel(f"[bold red]초기화 실패:[/bold red] {exc}", border_style="red"))
        return 1

    task_desc = (
        "아래 결정표 산출을 받아 백스토리 4단 구조의 한국어 보고서를 작성하세요. "
        "verdict 는 절대 뒤집지 마세요.\n\n"
        f"--- JudgmentDecision ---\n{format_judgment_decision_for_task(decision, SAMPLE_GAP)}"
    )
    task = Task(description=task_desc, expected_output=AGENT_TASK_EXPECTED_OUTPUT, agent=agent)
    try:
        with console.status("[yellow]Agent narration 중...[/yellow]", spinner="dots"):
            crew_result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    except Exception as exc:
        console.print(Panel(f"[bold red]Crew 실행 실패:[/bold red] {exc}", border_style="red"))
        return 1

    output_text = getattr(crew_result, "raw", None) or str(crew_result)
    console.print(Panel(output_text, title="[green]Agent 보고서[/green]", border_style="green"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
