# -*- coding: utf-8 -*-
"""
Nexus Alpha 자율 반복 루프 (Phase 2.5 / v3 PR-C).

`run_iterative_loop(user_request)` — 자기 진화 엔진의 공개 진입점.

LangGraph `StateGraph` 기반으로 다음 흐름을 구현한다:

    expand_requirements (Requirement Expander)
            │
            ▼
        run_chain (analyze_and_implement: CTO→Analyst→Engineer→QA)
            │
            ▼
       analyze_gap (Gap Analyst)
            │
            ▼
    judge_convergence (결정표, LLM 무관)
            │
            ├── COMPLETE        → finalize → END
            ├── IMPROVE_NEEDED  → prepare_feedback → run_chain (재진입)
            └── BLOCKED         → escalate → END

각 노드는 `_LoopState` 의 partial dict 를 반환하고, LangGraph 가 메르지한다.

설계 메모 (`docs/architecture/nexus_alpha_v3.md` §3, §5, §7):
    - **Iteration Controller 자체는 LLM 을 호출하지 않는다** — 결정론
      오케스트레이션 레이어. node 함수들이 LLM 에이전트를 호출하지만,
      Controller 의 라우팅·예산·정체 검사는 모두 결정론적 Python.
    - **체인 호출은 비침습**: 기존 `run_analyze_and_implement(user_request)` 를
      그대로 재사용하고, 재진입 시에는 `user_request + 피드백` 을 연결해 전달.
    - **Stagnation 프록시**: 정확한 resolved_gaps_since_last 추적은 Gap
      Analyst 응답의 풍부도에 의존하므로 MVP 는 `satisfied_count` 증가 여부
      를 프록시로 사용. 2회 연속 비증가 → stagnation=True.
    - **Budget gate (coarse)**: iteration 당 5000 token 추정치 차감. LangFuse
      usage 정밀 집계는 Phase 3 이후. NO_BUDGET_GATE 면 검사 생략.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.analysis import (
    create_gap_analyst_agent,
    create_requirement_expander_agent,
)
from src.agents.c_level import (
    DEFAULT_MAX_ITERATIONS,
    NO_BUDGET_GATE,
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    judge_convergence,
    parse_gap_report_from_yaml,
)
from src.monitoring import get_langfuse_client
from src.workflows.analyze_and_implement import (
    WorkflowResult,
    run_analyze_and_implement,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# iteration 당 차감할 추정 토큰 — LangFuse 정밀 집계 도입 전 임시 프록시.
DEFAULT_TOKENS_PER_ITERATION: int = 5000


# ---------------------------------------------------------------------------
# 결과 dataclass + LangGraph state TypedDict
# ---------------------------------------------------------------------------
@dataclass
class LoopOutcome:
    """`run_iterative_loop` 의 최종 산출물.

    Attributes:
        user_request: 사용자가 제출한 원본 요청.
        verdict: 최종 종료 verdict (COMPLETE / BLOCKED).
        blocked_cause: BLOCKED 시 세부 원인 (그 외 NONE).
        iterations_run: 실제 실행된 iteration 횟수.
        spec_markdown: Requirement Expander 산출 (한 번만 실행됨).
        final_chain_result: 마지막 iteration 의 4-agent 체인 산출.
        final_gap_report_raw: 마지막 iteration 의 Gap Analyst 마크다운.
        final_gap_report: 마지막 iteration 의 정규화 GapReport.
        final_decision: 마지막 결정표 산출.
        feedback_history: 각 iteration 에서 다음 iteration 으로 넘긴 feedback 텍스트.
        iteration_artifacts: 각 iteration 의 outputs/workflow_<ts>/ 디렉터리 경로.
        budget_remaining_at_end: 종료 시점 잔여 예산 (NO_BUDGET_GATE 면 -1).
    """

    user_request: str
    verdict: Verdict
    blocked_cause: BlockedCause
    iterations_run: int
    spec_markdown: str
    final_chain_result: Optional[WorkflowResult]
    final_gap_report_raw: str
    final_gap_report: Optional[GapReport]
    final_decision: Optional[JudgmentDecision]
    feedback_history: list[str] = field(default_factory=list)
    iteration_artifacts: list[Path] = field(default_factory=list)
    budget_remaining_at_end: int = NO_BUDGET_GATE


class _LoopState(TypedDict, total=False):
    """LangGraph 가 노드 사이에서 전달하는 상태 컨테이너.

    각 노드는 변경할 키만 dict 로 반환한다 — LangGraph 가 자동 메르지.
    리스트 필드(satisfied_history, feedback_history 등)도 노드가 *전체 새 리스트*
    를 반환해야 LangGraph 가 교체. append 시 항상 기존 + 새 원소 패턴.
    """

    # 입력
    user_request: str
    max_iterations: int
    budget_tokens_remaining: int
    outputs_dir: str  # Path.as_posix() — TypedDict serialization friendly

    # Requirement Expander 산출 (1회만)
    spec_markdown: str

    # 매 iteration 마다 갱신
    iteration: int
    feedback: str  # 다음 iteration CTO 에게 줄 보정 지시 (첫 iter 는 빈 문자열)
    chain_result: Any  # WorkflowResult — TypedDict 라 Any 로 둠
    gap_report_raw: str
    gap_report: Any  # GapReport
    decision: Any  # JudgmentDecision

    # 누적 이력 (stagnation 감지·결과 요약용)
    satisfied_history: list[int]  # iteration 별 satisfied_count
    feedback_history: list[str]
    iteration_artifacts: list[str]  # Path.as_posix() 문자열


# ---------------------------------------------------------------------------
# Helper — Gap Analyst 입력 직렬화
# ---------------------------------------------------------------------------
def _format_gap_analyst_input(
    spec_markdown: str,
    chain_result: WorkflowResult,
    prev_gap_raw: str,
    iteration: int,
) -> str:
    """Gap Analyst 백스토리가 가정하는 5블록 형식으로 입력을 직렬화.

    호출 측 워크플로우에서 task description 본문에 그대로 사용한다.
    """
    prev_block = prev_gap_raw if prev_gap_raw else "(없음 — 첫 iteration)"
    return (
        f"본 iteration 번호: {iteration}\n\n"
        f"[REQUIREMENT_SPEC]\n{spec_markdown}\n\n"
        f"[ENGINEER_OUTPUT]\n{chain_result.engineer_output}\n\n"
        f"[QA_REVIEW]\n{chain_result.qa_review}\n\n"
        f"[EXECUTION_RESULT]\n(없음 — Sandbox Runner 미적용)\n\n"
        f"[PREVIOUS_GAP_REPORT]\n{prev_block}\n"
    )


def _format_feedback_for_next_iteration(gap: GapReport, decision: JudgmentDecision) -> str:
    """이전 iteration 의 갭 + 판정을 다음 iteration CTO 에게 줄 한국어 feedback 으로 변환.

    LLM 합성 없이 pure Python 템플릿. 향후 LLM-mediated 합성이 필요하면 별도
    feedback synthesizer 에이전트로 분리.
    """
    lines = ["## 이전 iteration 보정 지시"]
    lines.append(
        f"- must-fix 잔여: {gap.unsatisfied_blockers} blocker(s) + "
        f"{gap.unsatisfied_majors} major(s) (총 {decision.must_fix_count}건)"
    )
    if gap.ambiguous_count > 0:
        lines.append(
            f"- 모호 항목 {gap.ambiguous_count}건 — 이번 iteration 에서 명확화 우선."
        )
    lines.append(f"- Convergence Judge 권고: {decision.next_action}")
    lines.append(
        "\n**이번 iteration 은 위 must-fix 항목 해소를 최우선으로 잡고, "
        "기존에 충족된 요구는 회귀시키지 마세요.**"
    )
    return "\n".join(lines)


def _detect_stagnation(satisfied_history: list[int]) -> bool:
    """satisfied_count 가 2회 연속 비증가 시 True (정확한 resolved 추적 프록시).

    iteration 1·2: 비교 불가 → False
    iteration 3+: history[-1] <= history[-2] AND history[-2] <= history[-3]
    """
    if len(satisfied_history) < 3:
        return False
    last, mid, prev = satisfied_history[-1], satisfied_history[-2], satisfied_history[-3]
    return last <= mid and mid <= prev


# ---------------------------------------------------------------------------
# 노드 함수들 — 각각 LangGraph 의 한 노드를 구현
# ---------------------------------------------------------------------------
def _node_expand_requirements(state: _LoopState) -> dict[str, Any]:
    """Requirement Expander 호출. 1회만 실행."""
    from crewai import Crew, Task

    expander = create_requirement_expander_agent(verbose=False)
    task = Task(
        description=(
            "아래 사용자 요청을 받아, 백스토리에 명시된 2단 구조로 한국어 요구 "
            "스펙을 작성하세요.\n\n"
            f"--- 사용자 요청 ---\n{state['user_request']}\n--- 끝 ---"
        ),
        expected_output="YAML 요구 스펙 + 분석가 노트 + Final Answer 카운트.",
        agent=expander,
    )
    result = Crew(agents=[expander], tasks=[task], verbose=False).kickoff()
    spec_md = getattr(result, "raw", None) or str(result)
    return {
        "spec_markdown": spec_md,
        "iteration": 0,  # 곧 run_chain 에서 1로 증가
        "feedback": "",
        "satisfied_history": [],
        "feedback_history": [],
        "iteration_artifacts": [],
        "gap_report_raw": "",
    }


def _node_run_chain(state: _LoopState) -> dict[str, Any]:
    """analyze_and_implement 4-agent 체인 호출. iteration 마다 실행."""
    next_iter = state["iteration"] + 1
    feedback = state.get("feedback", "")
    if feedback:
        request_with_feedback = (
            f"{state['user_request']}\n\n{feedback}"
        )
    else:
        request_with_feedback = state["user_request"]

    outputs_dir = Path(state["outputs_dir"]) if state.get("outputs_dir") else DEFAULT_OUTPUTS_DIR

    chain_result = run_analyze_and_implement(
        request_with_feedback,
        outputs_dir=outputs_dir,
        verbose=False,
    )

    artifacts = list(state.get("iteration_artifacts", []))
    artifacts.append(chain_result.saved_dir.as_posix())

    return {
        "iteration": next_iter,
        "chain_result": chain_result,
        "iteration_artifacts": artifacts,
    }


def _node_analyze_gap(state: _LoopState) -> dict[str, Any]:
    """Gap Analyst 호출 → 마크다운 + 정규화 GapReport."""
    from crewai import Crew, Task

    chain_result: WorkflowResult = state["chain_result"]
    prev_raw = state.get("gap_report_raw", "")

    description = _format_gap_analyst_input(
        spec_markdown=state["spec_markdown"],
        chain_result=chain_result,
        prev_gap_raw=prev_raw,
        iteration=state["iteration"],
    )

    analyst = create_gap_analyst_agent(verbose=False)
    task = Task(
        description=(
            "아래 5블록을 입력으로, 백스토리에 명시된 2단 구조(YAML 갭 보고서 + "
            "분석가 코멘트)로 한국어 보고서를 작성하세요.\n\n" + description
        ),
        expected_output="YAML 갭 보고서 + 분석가 코멘트 + Final Answer 카운트.",
        agent=analyst,
    )
    result = Crew(agents=[analyst], tasks=[task], verbose=False).kickoff()
    gap_md = getattr(result, "raw", None) or str(result)

    # 파싱 시도. 실패 시 빈 GapReport 로 fallback (Judge 가 즉시 BLOCKED 판정 가능).
    try:
        gap = parse_gap_report_from_yaml(gap_md, iteration=state["iteration"])
    except ValueError:
        # FakeProvider 응답처럼 YAML 이 없거나 잘못된 경우 — 안전 기본값
        gap = GapReport(iteration=state["iteration"])

    # satisfied_history 누적 + stagnation 프록시 검사
    sat_history = list(state.get("satisfied_history", []))
    sat_history.append(gap.satisfied_count)
    if _detect_stagnation(sat_history):
        gap.stagnation = True

    return {
        "gap_report_raw": gap_md,
        "gap_report": gap,
        "satisfied_history": sat_history,
    }


def _node_judge_convergence(state: _LoopState) -> dict[str, Any]:
    """결정표 호출 (LLM 무관). budget 도 함께 차감."""
    gap: GapReport = state["gap_report"]
    budget = state.get("budget_tokens_remaining", NO_BUDGET_GATE)

    # iteration 1건 비용 차감 (예산 추적이 활성화된 경우만)
    if budget != NO_BUDGET_GATE:
        budget = max(0, budget - DEFAULT_TOKENS_PER_ITERATION) if budget > 0 else 0

    decision = judge_convergence(
        gap,
        max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
        budget_tokens_remaining=budget,
    )
    return {
        "decision": decision,
        "budget_tokens_remaining": budget,
    }


def _node_prepare_feedback(state: _LoopState) -> dict[str, Any]:
    """IMPROVE_NEEDED 시 다음 iteration CTO 컨텍스트로 보낼 feedback 생성."""
    gap: GapReport = state["gap_report"]
    decision: JudgmentDecision = state["decision"]
    feedback_text = _format_feedback_for_next_iteration(gap, decision)

    history = list(state.get("feedback_history", []))
    history.append(feedback_text)

    return {
        "feedback": feedback_text,
        "feedback_history": history,
    }


def _node_finalize(state: _LoopState) -> dict[str, Any]:
    """COMPLETE 도달 시 종결 노드 — state 변경 없이 그대로 통과."""
    return {}


def _node_escalate(state: _LoopState) -> dict[str, Any]:
    """BLOCKED 도달 시 종결 노드 — state 변경 없이 그대로 통과."""
    return {}


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------
def _route_after_judge(state: _LoopState) -> str:
    """Convergence Judge verdict 에 따라 다음 노드 결정.

    Returns:
        "finalize" | "prepare_feedback" | "escalate"
    """
    decision: JudgmentDecision = state["decision"]
    if decision.verdict == Verdict.COMPLETE:
        return "finalize"
    if decision.verdict == Verdict.IMPROVE_NEEDED:
        return "prepare_feedback"
    return "escalate"  # BLOCKED


# ---------------------------------------------------------------------------
# Graph 조립
# ---------------------------------------------------------------------------
def build_iterative_loop_graph():  # type: ignore[no-untyped-def]
    """LangGraph StateGraph 인스턴스를 조립해 compiled graph 를 반환한다.

    구조:
        expand_requirements → run_chain → analyze_gap → judge_convergence
            ├── COMPLETE → finalize → END
            ├── IMPROVE_NEEDED → prepare_feedback → run_chain (loop)
            └── BLOCKED → escalate → END
    """
    g = StateGraph(_LoopState)
    g.add_node("expand_requirements", _node_expand_requirements)
    g.add_node("run_chain", _node_run_chain)
    g.add_node("analyze_gap", _node_analyze_gap)
    g.add_node("judge_convergence", _node_judge_convergence)
    g.add_node("prepare_feedback", _node_prepare_feedback)
    g.add_node("finalize", _node_finalize)
    g.add_node("escalate", _node_escalate)

    g.set_entry_point("expand_requirements")
    g.add_edge("expand_requirements", "run_chain")
    g.add_edge("run_chain", "analyze_gap")
    g.add_edge("analyze_gap", "judge_convergence")
    g.add_conditional_edges(
        "judge_convergence",
        _route_after_judge,
        {
            "finalize": "finalize",
            "prepare_feedback": "prepare_feedback",
            "escalate": "escalate",
        },
    )
    g.add_edge("prepare_feedback", "run_chain")  # 루프 재진입
    g.add_edge("finalize", END)
    g.add_edge("escalate", END)

    return g.compile()


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_iterative_loop(
    user_request: str,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    budget_tokens_remaining: int = NO_BUDGET_GATE,
    outputs_dir: Optional[Path] = None,
) -> LoopOutcome:
    """자율 반복 루프 실행. 사용자 요청 → COMPLETE 또는 BLOCKED 도달까지.

    Args:
        user_request: 사용자 자연어 요청.
        max_iterations: 강제 종료 한도 (기본 5).
        budget_tokens_remaining: 토큰 예산. NO_BUDGET_GATE(-1) 면 검사 생략.
        outputs_dir: 각 iteration 의 산출물 디렉터리 부모. 기본 `outputs/`.
            테스트에서 `tmp_path` 주입 가능.

    Returns:
        LoopOutcome — 최종 verdict + 마지막 chain 결과 + 모든 iteration 의 산출 경로.

    Raises:
        RecursionError: LangGraph 가 안전 한도(기본 25) 초과 시. 일반적으로
            max_iterations<=5 이면 노드 사이클이 ~30 이라 안전 — 그래도 노드
            recursion_limit 을 명시적으로 max_iterations*6 으로 설정.

    Note:
        Iteration Controller 자체는 LLM 을 호출하지 않는다. 4 agent (Expander +
        Engineer/QA 체인 4명 + Gap Analyst + (선택) Judge narration) 만 LLM 호출.
    """
    target_outputs = outputs_dir if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
    target_outputs.mkdir(parents=True, exist_ok=True)

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="iterative_loop",
        user_id="local-dev",
        metadata={
            "phase": "phase_2_5_v3",
            "workflow": "iterative_loop",
            "user_request_preview": user_request[:160],
            "max_iterations": max_iterations,
            "budget_initial": budget_tokens_remaining,
        },
    )

    try:
        compiled = build_iterative_loop_graph()
        initial_state: _LoopState = {
            "user_request": user_request,
            "max_iterations": max_iterations,
            "budget_tokens_remaining": budget_tokens_remaining,
            "outputs_dir": target_outputs.as_posix(),
        }
        # recursion_limit: 노드 방문 횟수 한도. iteration 한 번에 6 노드 (run_chain →
        # analyze_gap → judge → prepare_feedback → run_chain ...) 이므로 max_iter*6
        # + 안전 여유 10.
        recursion_limit = max(50, max_iterations * 6 + 10)
        final_state = compiled.invoke(initial_state, config={"recursion_limit": recursion_limit})

        decision: JudgmentDecision = final_state["decision"]
        gap: GapReport = final_state.get("gap_report") or GapReport()

        return LoopOutcome(
            user_request=user_request,
            verdict=decision.verdict,
            blocked_cause=decision.blocked_cause,
            iterations_run=final_state.get("iteration", 0),
            spec_markdown=final_state.get("spec_markdown", ""),
            final_chain_result=final_state.get("chain_result"),
            final_gap_report_raw=final_state.get("gap_report_raw", ""),
            final_gap_report=gap,
            final_decision=decision,
            feedback_history=list(final_state.get("feedback_history", [])),
            iteration_artifacts=[Path(p) for p in final_state.get("iteration_artifacts", [])],
            budget_remaining_at_end=final_state.get("budget_tokens_remaining", NO_BUDGET_GATE),
        )

    finally:
        monitor.end_trace()
        monitor.flush()
