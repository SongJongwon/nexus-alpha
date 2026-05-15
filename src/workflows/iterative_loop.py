# -*- coding: utf-8 -*-
"""
Nexus Alpha 자율 반복 루프 (Phase 2.5 / v3 + Phase 3 Sandbox 통합).

`run_iterative_loop(user_request)` — 자기 진화 엔진의 공개 진입점.

LangGraph `StateGraph` 기반으로 다음 흐름을 구현한다 (Phase 3 신규 노드 ★):

    expand_requirements (Requirement Expander)
            │
            ▼
        run_chain (analyze_and_implement: CTO→Analyst→Engineer→QA)
            │
            ▼
       run_sandbox ★ (run_python_in_sandbox — Engineer 산출 코드 동적 실행)
            │
            ▼
       analyze_gap (Gap Analyst — SandboxResult 를 입력으로 함께 받음)
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

Phase 3 (Sandbox 통합) 추가 메모:
    - **Single-file 한계**: `run_python_in_sandbox` 가 코드를 임시 디렉터리의
      `_sandbox_main.py` 단일 파일로만 기록·실행. Engineer 산출이 멀티파일
      패키지면 상대 import 가 실패해 SandboxResult.verdict=FAIL 로 떨어진다.
      Gap Analyst 가 이 신호를 받아 "실행 가능한 단일 파일로 재구성" 을 다음
      iteration 보정 지시로 만들 수 있다. 디렉터리 통째 복사·실행은 Phase 3
      후속 작업.
    - **Entry 선정 휴리스틱**: 단일 파일 / `__main__.py` / `cli.py` / `main.py`
      / `if __name__ == "__main__"` 보유 파일 순. 못 찾으면 실행 skip,
      execution_result=None 으로 Gap Analyst 에게 "(없음)" 안내.
    - **실패 격리**: 어떤 이유로든 sandbox 실행이 실패해도 루프 자체는 계속.
      execution_result=None 또는 verdict=FAIL/TIMEOUT 으로 다음 단계에 정보만 전달.
    - **enable_sandbox=False 토글**: 노드는 항상 그래프에 존재하되, flag 가
      False 면 노드가 즉시 None 반환 (그래프 분기 단순화).
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
from src.agents.coordination import (
    RetrospectiveReport,
    SharedKickoffDecisions,
    run_kickoff_meeting,
    run_retrospective,
)
from src.agents.knowledge import (
    KnowledgeEntry,
    curate_workflow,
    recall_past_entries,
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
from src.agents.operations import (
    SandboxResult,
    format_sandbox_result_for_task,
    run_python_in_sandbox,
    run_python_package_in_sandbox,
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

# Phase 3 — Sandbox 실행 기본 타임아웃(초). Engineer 산출 코드가 입력 대기·
# 무한 루프인 경우를 빠르게 끊는다. 더 긴 빌드·테스트가 필요하면 호출 측에서
# `run_iterative_loop(..., sandbox_timeout_sec=...)` 로 조정.
DEFAULT_SANDBOX_TIMEOUT_SEC: int = 30


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
        final_execution_result: 마지막 iteration 의 Sandbox 실행 결과.
            None 은 (a) enable_sandbox=False, (b) 실행 가능한 entry 부재,
            (c) 실행 자체 예외 중 하나. verdict 검사로 PASS/FAIL/TIMEOUT 구분.
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
    final_execution_result: Optional[SandboxResult]
    final_gap_report_raw: str
    final_gap_report: Optional[GapReport]
    final_decision: Optional[JudgmentDecision]
    feedback_history: list[str] = field(default_factory=list)
    iteration_artifacts: list[Path] = field(default_factory=list)
    budget_remaining_at_end: int = NO_BUDGET_GATE
    # PR #140 Phase 3 — Knowledge / RAG wiring (본인 비전 통찰 6, D-1)
    recalled_entries: list[KnowledgeEntry] = field(default_factory=list)
    curated_entry: Optional[KnowledgeEntry] = None
    curated_entry_path: Optional[Path] = None
    curated_index_path: Optional[Path] = None
    # PR #149 — Retrospective Lead (Phase 3 cycle 완성, 본부 10 두 번째 멤버)
    retrospective_report: Optional[RetrospectiveReport] = None
    retrospective_md_path: Optional[Path] = None


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
    enable_sandbox: bool  # Phase 3 — False 면 sandbox 노드가 즉시 None 반환
    sandbox_timeout_sec: int  # Phase 3
    enable_gui_branch: bool  # Phase 4 — analyze_and_implement 의 GUI 분기 토글
    enable_build_branch: bool  # Phase 4.5 — analyze_and_implement 의 빌드 사슬 토글
    target_platform: str  # Phase 4.5 — windows/macos/linux/cross-platform
    enable_release_branch: bool  # Phase 5 — analyze_and_implement 의 릴리스 사슬 토글
    previous_version: str  # Phase 5 — Release Manager 입력
    repo_url: str  # Phase 5 — Distribution Agent 입력
    signing_available: bool  # Phase 5 — Update Checker / Distribution Agent 입력
    privacy_level: str  # Phase 5 — Distribution Agent 입력
    enable_engineer_reviewer_delegation: bool  # PR #141 Phase 2 — Engineer↔Reviewer delegation

    # Requirement Expander 산출 (1회만)
    spec_markdown: str

    # PR #138 Phase 1 full — Meeting Facilitator 산출 (1회만, kickoff 회의 결과)
    shared_kickoff_decisions: Any  # SharedKickoffDecisions | None

    # PR #140 Phase 3 — Knowledge / RAG wiring (1회만)
    knowledge_index_dir: str  # outputs_dir / knowledge_index 의 Path.as_posix()
    recalled_entries: list[Any]  # list[KnowledgeEntry] — recall_past_entries 산출
    curated_entry: Any  # KnowledgeEntry | None — curate_workflow 산출
    curated_entry_path: str  # workflow_dir/knowledge_entry.yaml Path.as_posix(), "" 가능
    curated_index_path: str  # knowledge_index_dir/<workflow_id>.yaml, "" 가능

    # PR #149 — Retrospective Lead (Phase 3 cycle 완성, 종결 시 1회만)
    retrospective_report: Any  # RetrospectiveReport | None
    retrospective_md_path: str  # workflow_dir/retrospective.md 경로, "" 가능

    # 매 iteration 마다 갱신
    iteration: int
    feedback: str  # 다음 iteration CTO 에게 줄 보정 지시 (첫 iter 는 빈 문자열)
    chain_result: Any  # WorkflowResult — TypedDict 라 Any 로 둠
    execution_result: Any  # SandboxResult | None — Phase 3 sandbox 산출
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
    execution_result: Optional[SandboxResult] = None,
) -> str:
    """Gap Analyst 백스토리가 가정하는 5블록 형식으로 입력을 직렬화.

    호출 측 워크플로우에서 task description 본문에 그대로 사용한다.

    Phase 3 (2026-04-20): execution_result 파라미터 추가. None 이면 기존처럼
    "(없음)" 안내, SandboxResult 면 `format_sandbox_result_for_task` 로 직렬화한
    verdict/exit_code/elapsed/stdout/stderr 블록을 [EXECUTION_RESULT] 에 주입.
    """
    prev_block = prev_gap_raw if prev_gap_raw else "(없음 — 첫 iteration)"
    if execution_result is None:
        exec_block = "(없음 — Sandbox 비활성 또는 실행 가능 entry 미발견)"
    else:
        exec_block = format_sandbox_result_for_task(execution_result, max_lines=20)
    return (
        f"본 iteration 번호: {iteration}\n\n"
        f"[REQUIREMENT_SPEC]\n{spec_markdown}\n\n"
        f"[ENGINEER_OUTPUT]\n{chain_result.engineer_output}\n\n"
        f"[QA_REVIEW]\n{chain_result.qa_review}\n\n"
        f"[EXECUTION_RESULT]\n{exec_block}\n\n"
        f"[PREVIOUS_GAP_REPORT]\n{prev_block}\n"
    )


# ---------------------------------------------------------------------------
# Helper — Engineer 산출 코드 파일에서 실행 가능한 entry 1개를 휴리스틱으로 선정
# ---------------------------------------------------------------------------
# Phase 3 한계: `run_python_in_sandbox` 가 단일 파일만 지원하므로, 멀티파일
# 패키지 산출은 entry 파일을 1개 골라 그것만 실행한다. 상대 import 가 있는 패키지
# 는 ImportError 로 FAIL 처리되며, 이는 Gap Analyst 가 다음 iteration 의 보정
# 지시("실행 가능한 단일 파일로 재구성")로 변환하도록 의도된 신호다.

# 우선순위: 단일 파일 → __main__.py → cli.py / main.py / app.py / run.py →
# `if __name__ == "__main__"` 블록 보유 파일.
_PREFERRED_ENTRY_NAMES: tuple[str, ...] = (
    "__main__.py",
    "cli.py",
    "main.py",
    "app.py",
    "run.py",
)


def _pick_entry_file(code_files: list[Path]) -> Optional[Path]:
    """추출된 .py 파일 목록에서 sandbox 실행에 가장 적합한 1개를 반환.

    NOTE (Phase 3 보강): 본 함수는 단일 파일 entry 만 다루는 초기 휴리스틱이며,
    `_node_run_sandbox` 는 더 이상 이를 직접 호출하지 않는다 (멀티파일 패키지를
    제대로 다루는 `run_python_package_in_sandbox` 로 교체됨). 다만 회귀 테스트
    호환을 위해 모듈에 보존하며, 외부에서 단순 entry 후보를 묻는 용도로는
    여전히 유효.

    Args:
        code_files: `WorkflowResult.saved_code_files` (저장된 .py Path 목록).

    Returns:
        선정된 Path, 또는 None (목록 비어 있거나 후보 부재).
    """
    if not code_files:
        return None
    if len(code_files) == 1:
        return code_files[0]

    # `code_extract` 디렉터리 추출 시 파일명이 `src__pkg__cli.py` 같은 평탄화 형식.
    # 단순 endswith 매칭으로 처리.
    for preferred in _PREFERRED_ENTRY_NAMES:
        for p in code_files:
            if p.name.endswith(preferred):
                return p

    for p in code_files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'if __name__ == "__main__"' in text or "if __name__ == '__main__'" in text:
            return p

    return None  # 모든 휴리스틱 실패 — 실행 skip


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


def _node_recall_past_knowledge(state: _LoopState) -> dict[str, Any]:
    """PR #140 Phase 3 — RAG Searcher recall (본인 비전 통찰 6, D-1).

    워크플로 진입 시 1회만 실행. ``outputs/knowledge_index/`` 의 과거 entry 들에서
    현재 사용자 요청과 관련 높은 top-3 을 ``recalled_entries`` 로 state 에 저장 →
    Meeting Facilitator 의 spec_summary 또는 후속 task description 에 컨텍스트로
    주입 가능.

    인덱스 디렉터리 부재 시 빈 리스트 — 첫 빌드는 학습 자료 없이 진행.
    """
    outputs_dir = (
        Path(state["outputs_dir"]) if state.get("outputs_dir") else DEFAULT_OUTPUTS_DIR
    )
    index_dir = outputs_dir / "knowledge_index"

    try:
        entries = recall_past_entries(
            user_request=state["user_request"],
            knowledge_index_dir=index_dir,
            top_n=3,
        )
    except Exception:  # noqa: BLE001 — recall 실패는 워크플로 차단 X
        entries = []

    return {
        "knowledge_index_dir": index_dir.as_posix(),
        "recalled_entries": entries,
    }


def _node_retrospective(state: _LoopState) -> dict[str, Any]:
    """PR #149 — Retrospective Lead 회고 (본부 10 두 번째 멤버).

    워크플로 종료 시 1회만 실행 (curate_knowledge 직전). 본 빌드의:
        - 사용자 요청 + 킥오프 합의 (PR #146)
        - chain_result (Engineer/QA 산출)
        - execution_result (Sandbox)
        - 결정표 verdict
    을 입력으로 ``RetrospectiveReport`` 산출 → ``workflow_dir/retrospective.md`` 저장
    + state["retrospective_report"] 보존. 다음 노드 ``_node_curate_knowledge`` 가
    retrospective markdown 을 Curator prompt 에 추가 입력으로 사용 → entry 의
    summary/tags 가 *결함/성공 패턴* 으로 풍부해짐 (Phase 3 cycle 완성).
    """
    chain_result: Optional[WorkflowResult] = state.get("chain_result")
    workflow_id = ""
    if chain_result is not None and chain_result.saved_dir is not None:
        workflow_id = Path(chain_result.saved_dir).name

    decision: Optional[JudgmentDecision] = state.get("decision")
    verdict_str = "UNKNOWN"
    if decision is not None:
        v = getattr(decision, "verdict", None)
        if v is not None:
            verdict_str = getattr(v, "name", str(v))

    qa_review = ""
    if chain_result is not None:
        qa_review = getattr(chain_result, "qa_review", "") or ""

    try:
        report = run_retrospective(
            user_request=state["user_request"],
            workflow_id=workflow_id or "unknown",
            verdict=verdict_str,
            shared_kickoff_decisions=state.get("shared_kickoff_decisions"),
            chain_result=chain_result,
            execution_result=state.get("execution_result"),
            qa_review=qa_review,
        )
    except Exception:  # noqa: BLE001 — 회고 실패는 워크플로 차단 X
        return {
            "retrospective_report": None,
            "retrospective_md_path": "",
        }

    # workflow_dir 에 markdown 저장 (사람용)
    md_path_str = ""
    if chain_result is not None and chain_result.saved_dir is not None:
        workflow_dir = Path(chain_result.saved_dir)
        try:
            workflow_dir.mkdir(parents=True, exist_ok=True)
            md_path = workflow_dir / "retrospective.md"
            md_path.write_text(report.to_markdown(), encoding="utf-8")
            md_path_str = md_path.as_posix()
        except OSError:
            pass

    return {
        "retrospective_report": report,
        "retrospective_md_path": md_path_str,
    }


def _node_curate_knowledge(state: _LoopState) -> dict[str, Any]:
    """PR #140 Phase 3 — Knowledge Curator 색인 (본인 비전 통찰 6, D-1).

    워크플로 종료 시 1회만 실행 (finalize 또는 escalate 직전). 본 빌드의
    ``workflow_dir`` 산출물을 ``KnowledgeEntry`` 로 변환 → 분산 + 중앙 인덱스 저장.
    다음 빌드 진입 시 ``_node_recall_past_knowledge`` 가 이 entry 들에서 검색.

    BLOCKED 종결도 색인 — partial-output 태그로 향후 결함 패턴 학습.

    PR #149: ``state["retrospective_report"]`` 가 있으면 그 markdown 을
    ``curate_workflow`` 의 ``retrospective_md`` 인자로 전달 → entry summary/tags 가
    회고 기반으로 풍부해짐 (Phase 3 cycle 완성).
    """
    chain_result: Optional[WorkflowResult] = state.get("chain_result")
    if chain_result is None or chain_result.saved_dir is None:
        return {
            "curated_entry": None,
            "curated_entry_path": "",
            "curated_index_path": "",
        }

    workflow_dir = Path(chain_result.saved_dir)
    index_dir = (
        Path(state["knowledge_index_dir"])
        if state.get("knowledge_index_dir")
        else (
            Path(state["outputs_dir"]) / "knowledge_index"
            if state.get("outputs_dir")
            else DEFAULT_OUTPUTS_DIR / "knowledge_index"
        )
    )

    # judge 결과에서 qa_verdict_hint 추출 — APPROVED / NEEDS_REVISION
    decision: Optional[JudgmentDecision] = state.get("decision")
    qa_hint: Optional[str] = None
    if decision is not None:
        verdict_str = getattr(decision, "verdict", None)
        if verdict_str is not None:
            name = getattr(verdict_str, "name", str(verdict_str)).upper()
            if name == "COMPLETE":
                qa_hint = "APPROVED"
            elif name == "BLOCKED":
                qa_hint = "NEEDS_REVISION"

    # PR #149 — 회고 markdown 을 Curator prompt 에 추가 입력으로 전달
    retro_report: Optional[RetrospectiveReport] = state.get("retrospective_report")
    retro_md = retro_report.to_markdown() if retro_report is not None else ""

    try:
        entry, dist_path, idx_path = curate_workflow(
            workflow_dir=workflow_dir,
            user_request=state["user_request"],
            knowledge_index_dir=index_dir,
            qa_verdict_hint=qa_hint,
            retrospective_md=retro_md,
        )
    except Exception:  # noqa: BLE001 — curate 실패는 워크플로 차단 X
        return {
            "curated_entry": None,
            "curated_entry_path": "",
            "curated_index_path": "",
        }

    return {
        "curated_entry": entry,
        "curated_entry_path": dist_path.as_posix() if dist_path else "",
        "curated_index_path": idx_path.as_posix() if idx_path else "",
    }


def _node_kickoff_meeting(state: _LoopState) -> dict[str, Any]:
    """PR #138 Phase 1 full — Meeting Facilitator 킥오프 회의 1회 진행.

    설계 (본인 비전 통찰 6, 2026-05-15):
        expand_requirements 직후 / run_chain 진입 직전. 사용자 요청 +
        Requirement Expander 산출 YAML 을 받아 Meeting Facilitator 가
        ``SharedKickoffDecisions`` 산출. state 에 저장되어 후속 chain 의 모든
        task description 에 자동 주입됨 — 환율 변환기 사례 (cross-agent
        inconsistency) 재발 차단.

    iteration 재진입 시:
        ``prepare_feedback → run_chain`` 경로로 돌아오므로 본 노드는 skip.
        state 의 ``shared_kickoff_decisions`` 가 그대로 유지.
    """
    decisions = run_kickoff_meeting(
        user_request=state["user_request"],
        spec_markdown=state.get("spec_markdown", ""),
    )

    # outputs_dir 루트에 yaml 산출 — 후속 iteration 들 사이 공유. 1회만 작성.
    outputs_dir = (
        Path(state["outputs_dir"]) if state.get("outputs_dir") else DEFAULT_OUTPUTS_DIR
    )
    outputs_dir.mkdir(parents=True, exist_ok=True)
    try:
        (outputs_dir / "shared_kickoff_decisions.yaml").write_text(
            decisions.to_yaml(), encoding="utf-8"
        )
    except OSError:
        # 디스크 실패는 워크플로 차단 사유 아님 — state 의 객체만 유지
        pass

    return {"shared_kickoff_decisions": decisions}


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
        enable_gui_branch=state.get("enable_gui_branch", False),
        enable_build_branch=state.get("enable_build_branch", False),
        target_platform=state.get("target_platform", "windows"),
        enable_release_branch=state.get("enable_release_branch", False),
        previous_version=state.get("previous_version", ""),
        repo_url=state.get("repo_url", ""),
        signing_available=state.get("signing_available", False),
        privacy_level=state.get("privacy_level", "public"),
        shared_kickoff_decisions=state.get("shared_kickoff_decisions"),
        enable_engineer_reviewer_delegation=state.get(
            "enable_engineer_reviewer_delegation", False
        ),
    )

    artifacts = list(state.get("iteration_artifacts", []))
    artifacts.append(chain_result.saved_dir.as_posix())

    return {
        "iteration": next_iter,
        "chain_result": chain_result,
        "iteration_artifacts": artifacts,
        # 새 iteration 시작 — 이전 iter 의 sandbox 산출은 무효
        "execution_result": None,
    }


def _node_run_sandbox(state: _LoopState) -> dict[str, Any]:
    """Phase 3 — Engineer 산출 코드를 별도 프로세스에서 실행.

    Phase 3 보강 (2026-04-20):
        단일 파일 entry 만 다루던 초기 버전을 폐기하고, 멀티파일 패키지를
        디렉터리 트리째 재구성·실행하는 `run_python_package_in_sandbox` 로 위임.
        `# file: <relpath>` 헤더 기반 트리 재구성 → `__main__.py`/`cli.py` 등
        entry 자동 탐지 → `python -m <pkg>` 실행. 단일 파일도 동일 함수가 root
        에 배치하고 스크립트로 실행해 backward compat 유지.

    동작 요약:
        1. `enable_sandbox=False` → 즉시 None 반환 (skip)
        2. `saved_code_files` 비었음 → None (FakeProvider 시나리오 등)
        3. `run_python_package_in_sandbox` 호출:
             - 트리 재구성 + entry 탐지 + 실행
             - entry 미탐지 시 함수가 None 반환 → 그대로 전달
        4. 잘못된 입력 (TypeError/ValueError) → None fallback (루프 안전성 우선)

    Returns:
        {"execution_result": SandboxResult | None}
    """
    if not state.get("enable_sandbox", True):
        return {"execution_result": None}

    chain: WorkflowResult = state["chain_result"]
    if not chain or not chain.saved_code_files:
        return {"execution_result": None}

    try:
        result = run_python_package_in_sandbox(
            chain.saved_code_files,
            timeout_sec=state.get("sandbox_timeout_sec", DEFAULT_SANDBOX_TIMEOUT_SEC),
        )
    except (TypeError, ValueError):
        return {"execution_result": None}

    return {"execution_result": result}


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
        execution_result=state.get("execution_result"),
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
        expand_requirements → recall_past_knowledge → kickoff_meeting → run_chain →
            run_sandbox → analyze_gap → judge_convergence
                ├── COMPLETE → retrospective → curate_knowledge → finalize → END
                ├── IMPROVE_NEEDED → prepare_feedback → run_chain (loop)
                └── BLOCKED → retrospective_blocked → curate_knowledge_blocked → escalate → END

    PR #138 Phase 1 full (2026-05-15): kickoff_meeting 신설.
    PR #140 Phase 3 (2026-05-15): recall_past_knowledge + curate_knowledge 신설.
    PR #149 (2026-05-15, 본부 10 두 번째 멤버): retrospective 노드 신설 — Curator
        직전에 회고를 산출해 그 markdown 을 Curator prompt 입력으로 추가 →
        entry summary/tags 가 *결함/성공 패턴* 으로 풍부해짐 (Phase 3 cycle 완성).
    """
    g = StateGraph(_LoopState)
    g.add_node("expand_requirements", _node_expand_requirements)
    g.add_node("recall_past_knowledge", _node_recall_past_knowledge)  # PR #140
    g.add_node("kickoff_meeting", _node_kickoff_meeting)               # PR #138 full
    g.add_node("run_chain", _node_run_chain)
    g.add_node("run_sandbox", _node_run_sandbox)
    g.add_node("analyze_gap", _node_analyze_gap)
    g.add_node("judge_convergence", _node_judge_convergence)
    g.add_node("prepare_feedback", _node_prepare_feedback)
    g.add_node("retrospective", _node_retrospective)                   # PR #149
    g.add_node("curate_knowledge", _node_curate_knowledge)             # PR #140
    g.add_node("retrospective_blocked", _node_retrospective)           # PR #149 alias
    g.add_node("curate_knowledge_blocked", _node_curate_knowledge)     # PR #140 alias
    g.add_node("finalize", _node_finalize)
    g.add_node("escalate", _node_escalate)

    g.set_entry_point("expand_requirements")
    g.add_edge("expand_requirements", "recall_past_knowledge")
    g.add_edge("recall_past_knowledge", "kickoff_meeting")
    g.add_edge("kickoff_meeting", "run_chain")
    g.add_edge("run_chain", "run_sandbox")
    g.add_edge("run_sandbox", "analyze_gap")
    g.add_edge("analyze_gap", "judge_convergence")
    g.add_conditional_edges(
        "judge_convergence",
        _route_after_judge,
        {
            "finalize": "retrospective",                # PR #149 — finalize 전 회고
            "prepare_feedback": "prepare_feedback",
            "escalate": "retrospective_blocked",        # PR #149 — escalate 전 회고
        },
    )
    g.add_edge("retrospective", "curate_knowledge")
    g.add_edge("retrospective_blocked", "curate_knowledge_blocked")
    g.add_edge("curate_knowledge", "finalize")
    g.add_edge("curate_knowledge_blocked", "escalate")
    g.add_edge("prepare_feedback", "run_chain")
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
    enable_sandbox: bool = True,
    sandbox_timeout_sec: int = DEFAULT_SANDBOX_TIMEOUT_SEC,
    enable_gui_branch: bool = False,
    enable_build_branch: bool = False,
    target_platform: str = "windows",
    enable_release_branch: bool = False,
    previous_version: str = "",
    repo_url: str = "",
    signing_available: bool = False,
    privacy_level: str = "public",
    enable_engineer_reviewer_delegation: bool = False,
) -> LoopOutcome:
    """자율 반복 루프 실행. 사용자 요청 → COMPLETE 또는 BLOCKED 도달까지.

    Args:
        user_request: 사용자 자연어 요청.
        max_iterations: 강제 종료 한도 (기본 5).
        budget_tokens_remaining: 토큰 예산. NO_BUDGET_GATE(-1) 면 검사 생략.
        outputs_dir: 각 iteration 의 산출물 디렉터리 부모. 기본 `outputs/`.
            테스트에서 `tmp_path` 주입 가능.
        enable_sandbox: Phase 3 — Engineer 산출 코드 자동 실행 여부. 기본 True.
            False 면 sandbox 노드가 즉시 None 반환하고 Gap Analyst 입력에는
            "(없음)" 안내. 호환성·디버깅 목적의 우회 스위치.
        sandbox_timeout_sec: 자식 프로세스 강제 종료 임계 (초). 기본 30.
        enable_gui_branch: Phase 4 토글. True 면 매 iteration 의
            `run_analyze_and_implement` 호출에 동일 토글이 propagate 되어,
            UI/UX Analyst → (GUI 면) 디자인 본부 3명 / (CLI 면) Engineer 분기
            가 발동된다. 기본 False — backward compat.
        enable_build_branch: Phase 4.5 토글. True 면 매 iteration 의 메인 체인
            종료 후 빌드 5단 사슬(Dep Analyzer → Build Engineer → Asset Manager →
            Installer Creator → Platform Tester)이 추가 실행된다. 기본 False —
            backward compat.
        target_platform: Phase 4.5 빌드 사슬 대상 플랫폼. windows/macos/linux/
            cross-platform. enable_build_branch=False 면 무시.
        enable_release_branch: Phase 5 토글. True 면 매 iteration 의 메인 + 빌드
            사슬 종료 후 릴리스 4단 사슬(Release/Changelog/Update/Distribution)
            추가 실행. 매 iteration 마다 release 호출은 부적절할 수 있어 호출
            측이 신중히 사용. 기본 False.
        previous_version: Phase 5 입력 — 이전 릴리스 버전 (없으면 첫 릴리스).
        repo_url: Phase 5 입력 — GitHub repo URL.
        signing_available: Phase 5 입력 — 코드 서명 보유.
        privacy_level: Phase 5 입력 — public/corporate-internal/one-time-share.

    Returns:
        LoopOutcome — verdict + 4-agent chain 결과 + sandbox 실행 결과 + 산출 경로.

    Raises:
        RecursionError: LangGraph 안전 한도 초과 시. recursion_limit 은
            max_iterations*7 + 안전 여유 10 으로 자동 설정 (Phase 3 에서 한 iter 가
            7 노드: chain→sandbox→gap→judge→prepare_feedback→chain→sandbox 등).

    Note:
        Iteration Controller 자체는 LLM 을 호출하지 않는다. LLM 호출 주체는:
        - Requirement Expander (1회)
        - 4-agent chain (CTO/Analyst/Engineer/QA) — iteration 마다
        - Gap Analyst — iteration 마다
        - (선택) Convergence Judge narration — 본 함수에서는 결정표만 호출,
          narration 은 별도 호출 측 책임.

        Sandbox 실행은 LLM 호출 아닌 subprocess — 보안 한계는 Phase 2-P4 모듈
        docstring 참조 (호스트 격리 없음, 신뢰할 수 없는 코드 실행 금지).
    """
    target_outputs = outputs_dir if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
    target_outputs.mkdir(parents=True, exist_ok=True)

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="iterative_loop",
        user_id="local-dev",
        metadata={
            "phase": "phase_4_gui_integration" if enable_gui_branch else "phase_3_sandbox_integration",
            "workflow": "iterative_loop",
            "user_request_preview": user_request[:160],
            "max_iterations": max_iterations,
            "budget_initial": budget_tokens_remaining,
            "enable_sandbox": enable_sandbox,
            "enable_gui_branch": enable_gui_branch,
        },
    )

    try:
        compiled = build_iterative_loop_graph()
        initial_state: _LoopState = {
            "user_request": user_request,
            "max_iterations": max_iterations,
            "budget_tokens_remaining": budget_tokens_remaining,
            "outputs_dir": target_outputs.as_posix(),
            "enable_sandbox": enable_sandbox,
            "sandbox_timeout_sec": sandbox_timeout_sec,
            "enable_gui_branch": enable_gui_branch,
            "enable_build_branch": enable_build_branch,
            "target_platform": target_platform,
            "enable_release_branch": enable_release_branch,
            "previous_version": previous_version,
            "repo_url": repo_url,
            "signing_available": signing_available,
            "privacy_level": privacy_level,
            "enable_engineer_reviewer_delegation": enable_engineer_reviewer_delegation,
        }
        # recursion_limit: iteration 한 번이 7 노드 (Phase 3 에서 sandbox 추가) →
        # max_iter*7 + 안전 여유 10.
        recursion_limit = max(50, max_iterations * 7 + 10)
        final_state = compiled.invoke(initial_state, config={"recursion_limit": recursion_limit})

        decision: JudgmentDecision = final_state["decision"]
        gap: GapReport = final_state.get("gap_report") or GapReport()

        curated_entry_path_str = final_state.get("curated_entry_path", "")
        curated_index_path_str = final_state.get("curated_index_path", "")
        retro_md_path_str = final_state.get("retrospective_md_path", "")
        return LoopOutcome(
            user_request=user_request,
            verdict=decision.verdict,
            blocked_cause=decision.blocked_cause,
            iterations_run=final_state.get("iteration", 0),
            spec_markdown=final_state.get("spec_markdown", ""),
            final_chain_result=final_state.get("chain_result"),
            final_execution_result=final_state.get("execution_result"),
            final_gap_report_raw=final_state.get("gap_report_raw", ""),
            final_gap_report=gap,
            final_decision=decision,
            feedback_history=list(final_state.get("feedback_history", [])),
            iteration_artifacts=[Path(p) for p in final_state.get("iteration_artifacts", [])],
            budget_remaining_at_end=final_state.get("budget_tokens_remaining", NO_BUDGET_GATE),
            recalled_entries=list(final_state.get("recalled_entries", []) or []),
            curated_entry=final_state.get("curated_entry"),
            curated_entry_path=Path(curated_entry_path_str) if curated_entry_path_str else None,
            curated_index_path=Path(curated_index_path_str) if curated_index_path_str else None,
            retrospective_report=final_state.get("retrospective_report"),
            retrospective_md_path=Path(retro_md_path_str) if retro_md_path_str else None,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
