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

import ast
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

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

# PR #158 — Track B run_automate_workflow 도 iterative_loop 안에서 호출 가능하게 지연 import.
# 순환 import 회피 + Track A 만 쓰는 경우 import 비용 0.


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
    # v13 P16 (수정2) — 그래프 실행 예외(GraphRecursionError 등)로 종단 시 예외 repr 보존.
    # None 이면 정상 종단 (회귀 0). blocked_cause=INTERNAL_ERROR 와 함께 채워짐.
    crash_reason: Optional[str] = None


def _format_blocked_partial_hint(cause: BlockedCause) -> str:
    """BLOCKED 별 partial output / next action 안내 (PR #174).

    PR #174 — BLOCKED 결과 패널 UX. blocked_cause 별로 사용자가 다음 행동을 알 수
    있도록 partial output 안내 + 재시도 옵션 surface.
    """
    if cause == BlockedCause.ITERATION_CAP:
        return " — partial output 산출 완료, --max-iterations 늘려 추가 개선 가능"
    if cause == BlockedCause.BUILD_FAILED:
        return " — .exe 산출 실패 (build 실패 — 04_executor_result.md 확인)"
    if cause == BlockedCause.BUDGET_EXHAUSTED:
        return " — 토큰 예산 소진 (--budget-tokens 늘려 재시도 가능)"
    if cause == BlockedCause.STAGNATION:
        return " — 진행 정체 (2 iter 연속 gap 변화 없음 — 요구사항 모호 가능)"
    if cause == BlockedCause.INTERNAL_ERROR:
        return " — 내부 오류로 중단 (그래프 실행 예외 — crash_reason 확인, 재시도 가능)"
    return ""


def format_iterative_summary(outcome: LoopOutcome, max_iterations: int) -> str:
    """결과 패널 Iterate 라인 — verdict + blocked_cause + partial output 안내 (PR #174).

    이전 (PR #174 이전):
        ``verdict=BLOCKED iterations=1/1`` — PM 입장 .exe 산출 있는데 BLOCKED 만 보임
        → 부정적 인상 + 다음 행동 미보임.

    본 PR 이후:
        ``verdict=BLOCKED(ITERATION_CAP) iterations=1/1 — partial output 산출 완료,
        --max-iterations 늘려 추가 개선 가능``

    Args:
        outcome: ``LoopOutcome`` — verdict / blocked_cause / iterations_run 사용.
        max_iterations: CLI ``--max-iterations`` 값 (분모 표시용).

    Returns:
        결과 패널 Iterate 라인용 한 줄 문자열.
    """
    verdict_str = getattr(outcome.verdict, "value", str(outcome.verdict))
    iterations = f"iterations={outcome.iterations_run}/{max_iterations}"
    if outcome.verdict == Verdict.BLOCKED:
        cause_str = getattr(outcome.blocked_cause, "value", str(outcome.blocked_cause))
        partial_hint = _format_blocked_partial_hint(outcome.blocked_cause)
        return f"verdict=BLOCKED({cause_str}) {iterations}{partial_hint}"
    return f"verdict={verdict_str} {iterations}"


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
    # PR #157 — production wire: 매 iteration 의 analyze_and_implement 에 propagate
    enable_executor: bool  # PyInstaller .exe 실 빌드 활성
    executor_timeout_sec: int  # PyInstaller subprocess 타임아웃
    enable_publish: bool  # gh release create 실 발행 활성
    publish_as_draft: bool  # Draft 로 발행할지 (안전 기본 True)
    publish_timeout_sec: int  # gh CLI 타임아웃
    verbose: bool  # CrewAI 중간 로그 출력
    # PR #158 — Track B 지원 (chain 분기)
    track: str  # "A" (analyze_and_implement) | "B" (automate_workflow)
    release_tag: str  # Track B run_automate_workflow 의 release_tag
    # PR #183 — Track B 도메인 자동 분류 우회 (CLI --forced-domain)
    forced_domain: Any  # AutomationDomain | None — Track B 전용, None 이면 휴리스틱
    # v13 P20 — codegen 직전 사람 개입 체크포인트 (opt-in, 기본 OFF)
    intervene: bool  # True 면 첫 codegen 직전 1회 체크포인트 (파일/콘솔). False 면 no-op.
    intervene_timeout: int  # 개입 대기 타임아웃 (초). 무입력 시 자동 진행.

    # v13 Phase 1 2단계 (PR #217) — 본부 9 Runtime Verification opt-in wire
    enable_rv: bool  # --enable-rv flag. False (default) 면 _node_runtime_verify pass-through
    rv_result: Any  # RuntimeTestResult | None — Exe Runtime Tester 산출
    rv_failure_detected: bool  # silent fail / crash 감지 시 True → prepare_feedback 분기 trigger
    # v13 Phase 2 (PR #219) — 본부 1 System Refactoring Strategist opt-in wire
    enable_strategist: bool  # --enable-strategist flag. False (default) 면 escalate 시에도 Strategist 호출 X
    consecutive_rv_failures: int  # 연속 RV 실패 카운트 (escalate threshold 5)
    strategist_proposal_path: Any  # Path | None — 발제된 안건 markdown 경로
    # v13 Phase 3 (PR #221) — 본부 10 Boardroom 회의실 인프라 opt-in wire
    enable_boardroom: bool  # --enable-boardroom flag. False (default) 면 안건 발제해도 회의 X
    boardroom_session_path: Any  # Path | None — 회의록 markdown 경로
    # v13 Phase 5.4 (PR #224) — 양방향 티키타카 라운드 opt-in wire
    enable_tikitaka: bool  # --enable-tikitaka flag. False (default) 면 직렬 의결 (Phase 4 모드)
    # v13 Phase 6.3 (PR #230) — Tech Scout PyPI 가짜 패키지 가드 opt-in wire
    enable_tech_scout: bool  # --enable-tech-scout flag. False (default) 면 requirements.txt 검증 skip
    fake_packages: Any  # list[str] | None — 이번 iter 의 가짜 패키지 list (Rule -1 입력)
    consecutive_fake_iterations: int  # 가짜 패키지 연속 iter 카운트 — 2차 도달 시 BLOCKED(FAKE_PACKAGE)
    # v13 Phase 6.E (PR #231) — Rule 0 workflow wire (PM 진단 처방 A)
    # build_domain_checklist(user_request) 가 expand_requirements 시 1회 산출 → judge 매 iter 입력.
    # 3D 같은 도메인 키워드 매칭 시 채워짐. 아니면 [] → Rule 0 skip → 회귀 0.
    domain_checklist: Any  # list[ChecklistItem] | None
    # v13 Phase 6.E P1 (PR #235) — 플랫폼 의도 (web/desktop/unspecified).
    # expand_requirements 가 _detect_platform 으로 1회 산출. web 이면 엔지니어
    # 프롬프트에 데스크탑 GUI 금지 제약 주입 + judge PLATFORM_DRIFT 탐지 활성.
    platform_intent: str

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
    # v13 P23 — desktop .exe 런타임 스모크 게이트 (기본 ON, desktop 빌드만). enable_rv 와 독립.
    # enable_smoke: 게이트 토글 (기본 True — sibling enable_* 와 달리 ON-by-default).
    # smoke_timeout: .exe 생존 판정 대기(초, 기본 8). smoke_result: DesktopSmokeResult | None.
    enable_smoke: bool
    smoke_timeout: int
    smoke_result: Any  # DesktopSmokeResult | None — judge 의 _apply_smoke_failure_override 가 소비
    # v13 P25 — 산출물 배포성 게이트 (기본 ON; web 빌드 한정, desktop/none 자동 SKIP).
    # deployability_result: PackageabilityResult | None — judge 의 _apply_deployability_failure_override 가 소비.
    enable_packageability: bool
    deployability_result: Any

    # 누적 이력 (stagnation 감지·결과 요약용)
    satisfied_history: list[int]  # iteration 별 satisfied_count
    feedback_history: list[str]
    iteration_artifacts: list[str]  # Path.as_posix() 문자열
    # v13 Phase 6.E P15 — iteration 별 품질 기록 (best-iteration 선택용).
    # 루프가 깨진 마지막 iteration 으로 종단하지 않고, 빌드 성공+도메인 충족한 *최고*
    # iteration 산출을 최종으로 채택하기 위함. judge 노드가 매 iter 1건씩 append.
    iteration_records: list[Any]


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
    # ★ v13 Phase 6.E P5 (PR #237) — GUI 경로 판정기 입력 배선 수정.
    # GUI 경로(analyze_and_implement._run_gui_workflow)는 engineer_output="" 고정이고
    # 실제 산출은 gui_code_output(+저장 코드)에 있다. 그대로 두면 [ENGINEER_OUTPUT]
    # 이 공란 → 완벽한 web 산출도 Gap Analyst 가 "0 satisfied" 오판 → COMPLETE 영영
    # 불가 (P0P1P2 verdict 1차 원인). 폴백 순서: engineer_output → gui_code_output →
    # 저장 코드 발췌(code/*.py + 13_gui_code_output.md). engineer_output 이 있으면
    # 기존 동작 그대로 (회귀 0).
    engineer_block = chain_result.engineer_output
    if not (engineer_block and engineer_block.strip()):
        gui_output = getattr(chain_result, "gui_code_output", "") or ""
        if gui_output.strip():
            engineer_block = gui_output
        else:
            # 마지막 가드 — 디스크 저장 코드 산출(code/*.py + 13_gui_code_output.md 등).
            disk_excerpt = _extract_engineer_output_excerpt(chain_result)
            if disk_excerpt.strip():
                engineer_block = disk_excerpt
    return (
        f"본 iteration 번호: {iteration}\n\n"
        f"[REQUIREMENT_SPEC]\n{spec_markdown}\n\n"
        f"[ENGINEER_OUTPUT]\n{engineer_block}\n\n"
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
    """Requirement Expander 호출. 1회만 실행.

    v13 Phase 6.E (PR #231) — 도메인 체크리스트 동시 산출:
        user_request 키워드 매칭 (예: BIM/3D/Three.js) → 3D 도메인 4 항목 체크리스트.
        Rule 0 가 매 iter 의 judge 시점에 활용. 매칭 0 시 빈 list → Rule 0 skip.
    """
    from crewai import Crew, Task

    from src.agents.analysis import (  # noqa: PLC0415
        _detect_platform,
        build_domain_checklist,
    )

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
    # Phase 6.E ★ — 도메인 체크리스트 산출 (LLM 무관 결정론, 항상 안전)
    try:
        domain_checklist = build_domain_checklist(state["user_request"])
    except Exception:  # noqa: BLE001
        domain_checklist = []  # 결정론 매처 결함도 회귀 0 보장
    # Phase 6.E P1 (PR #235) ★ — 플랫폼 의도 산출 (web/desktop/unspecified, 결정론)
    try:
        platform_intent = _detect_platform(state["user_request"])
    except Exception:  # noqa: BLE001
        platform_intent = "unspecified"  # 결함도 회귀 0 (제약 미주입)
    return {
        "spec_markdown": spec_md,
        "iteration": 0,  # 곧 run_chain 에서 1로 증가
        "feedback": "",
        "satisfied_history": [],
        "feedback_history": [],
        "iteration_artifacts": [],
        "gap_report_raw": "",
        "domain_checklist": domain_checklist,
        "platform_intent": platform_intent,
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

    # PR #179 — raw 진단 file 위치 (workflow_dir/retrospective_llm_raw.json)
    retro_workflow_dir: Optional[Path] = None
    if chain_result is not None and chain_result.saved_dir is not None:
        retro_workflow_dir = Path(chain_result.saved_dir)

    try:
        report = run_retrospective(
            user_request=state["user_request"],
            workflow_id=workflow_id or "unknown",
            verdict=verdict_str,
            shared_kickoff_decisions=state.get("shared_kickoff_decisions"),
            chain_result=chain_result,
            execution_result=state.get("execution_result"),
            qa_review=qa_review,
            workflow_dir=retro_workflow_dir,
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

    PR #152 (본인 비전 통찰 6 Phase 3 cycle wiring, 2026-05-15):
        ``_node_recall_past_knowledge`` 가 state 에 저장한 ``recalled_entries`` 를
        ``format_recalled_entries_for_context`` 로 markdown 변환 → decisions 의
        ``recalled_knowledge_markdown`` 필드에 주입. 결과로 모든 task description
        끝에 *과거 빌드 학습* 섹션이 자동 append 됨 (기존 shared_kickoff_decisions
        주입 회로 재사용).
    """
    decisions = run_kickoff_meeting(
        user_request=state["user_request"],
        spec_markdown=state.get("spec_markdown", ""),
    )

    # PR #152 — recall 산출을 kickoff 결정에 흡수 (next-build prompt 주입)
    from src.agents.knowledge import format_recalled_entries_for_context

    recalled = list(state.get("recalled_entries", []) or [])
    if recalled:
        decisions.recalled_knowledge_markdown = format_recalled_entries_for_context(
            recalled
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


def _adapt_automate_to_chain_result(automate_result: Any) -> Any:
    """PR #158 — ``AutomateWorkflowResult`` 를 ``WorkflowResult``-like duck type 으로 변환.

    iterative_loop 의 Gap Analyst / sandbox / retry helper 는 다음 attr 접근:
        - ``engineer_output`` / ``qa_review`` (Gap Analyst 입력)
        - ``saved_dir`` / ``saved_code_files`` (산출 경로 + sandbox 입력)
        - ``executor_result`` / ``publish_result`` (Vision QA + 결과 패널)
        - ``gui_code_output`` / ``ui_spec`` / ``design_tokens`` (retry GUI 분기)

    Track B 의 AutomateWorkflowResult 는 ``agent_output`` (engineer_output 대신) +
    ``code_qa_result`` (qa_review 대신) 만 가짐. 본 어댑터가 그 mapping 을 수행 →
    iterative_loop 가 Track A/B 무관하게 동작 가능.
    """
    # PR #170 — 4 케이스 차별화 진단 (이전: 모든 falsy 케이스 단일 fallback 메시지)
    qa_review = ""
    code_qa = getattr(automate_result, "code_qa_result", None)
    if code_qa is None:
        qa_review = "(no QA review — Track B 자동화 산출)"
    elif not hasattr(code_qa, "summary_line"):
        qa_review = (
            f"(no QA review — code_qa type={type(code_qa).__name__} "
            f"has no summary_line)"
        )
    else:
        try:
            qa_review = code_qa.summary_line()
        except Exception as exc:  # noqa: BLE001 — 예외 type+msg surface (caller 진단)
            qa_review = (
                f"(no QA review — summary_line 호출 실패: "
                f"{type(exc).__name__}: {exc})"
            )
    if not qa_review:
        qa_review = "(no QA review — summary_line 빈 문자열)"

    from types import SimpleNamespace

    return SimpleNamespace(
        saved_dir=getattr(automate_result, "saved_dir", None),
        saved_code_files=list(getattr(automate_result, "saved_code_files", []) or []),
        engineer_output=getattr(automate_result, "agent_output", ""),
        qa_review=qa_review,
        executor_result=getattr(automate_result, "executor_result", None),
        publish_result=getattr(automate_result, "publish_result", None),
        # Track B 는 GUI/UI 디자인 산출이 없음 — retry helper 의 GUI 분기 판정이 CLI 로
        gui_code_output="",
        ui_spec="",
        design_tokens="",
        # WorkflowResult 의 기타 필드 — 빈 기본값
        dependency_report="",
        build_spec="",
        asset_manifest="",
        installer_spec="",
        platform_test_report="",
        release_decision="",
        changelog_entry="",
        update_module_spec=getattr(automate_result, "update_module_spec", "") or "",
    )


def _build_prev_code_context(
    prev_chain_result: Any, *, max_chars: int = 15_000, platform_intent: str = "unspecified"
) -> str:
    """v13 Phase 6.E (PR #232) — 이전 iter 코드 발췌 prompt 텍스트.

    PR 1 의 ``_extract_engineer_output_excerpt`` 재사용 — 이전 iter chain_result
    의 ``saved_dir/code/*.py + 13_gui_code_output.md + 03_engineer_output.md``
    를 합쳐 prompt 에 첨부 가능한 한국어 wrapper 로 포장.

    반환:
        - 발췌 0 (chain_result None / saved_dir 없음 / 파일 없음): 빈 string
        - 발췌 있음: "## 이전 iteration 산출 코드..." prefix + 코드 본문

    의도:
        Engineer 가 *이전 iter 에서 뭘 만들던 중* 이었는지 prompt 컨텍스트로
        받아, 다음 iter 에서 *전체를 백지에서 다시 작성하지 않게* 차단.
        Phase 6.E 라이브 검증의 iter 2 퇴행 (BIM viewport.py → Nexus GUI
        복사본) 원인 = 코드 컨텍스트 손실. 본 helper 가 그 갭 해결.
    """
    excerpt = _extract_engineer_output_excerpt(
        prev_chain_result, max_chars=max_chars
    )
    if not excerpt:
        return ""
    # ★ P2-B (PR #236) — platform-aware: web 의도인데 직전 산출이 데스크탑(PyQt/
    # PySide/Tkinter)이면 stale 코드 *재주입 금지* + "백지 web 재작성" 경고로 대체.
    # 옵션 B(#232)의 "구조 유지=퇴행 방지" 가 P1(#235)의 "데스크탑 금지"를 무력화해
    # web→PyQt 재드리프트를 고착시키던 충돌(P0P1 verdict 하류결함 B) 제거.
    # platform_intent != "web" 이면 기존 동작 그대로 (회귀 0).
    if platform_intent == "web":
        from src.agents.c_level.convergence_judge import (  # noqa: PLC0415
            detect_desktop_markers,
        )

        drift = detect_desktop_markers(excerpt)
        if drift:
            preview = ", ".join(drift[:4])
            return (
                "\n\n## ⚠️ 직전 iteration 산출 = 플랫폼 위반 (데스크탑 GUI 감지)\n\n"
                f"직전 iter 산출에서 데스크탑 GUI 마커({preview})가 감지됐습니다 — "
                "web 타겟 위반입니다.\n"
                "**직전 코드의 구조/식별자를 유지하지 마세요.** 백지에서 "
                "**Three.js + WebGL + HTML/JS/CSS** 기반 web 앱으로 재작성하세요.\n"
                "(PyQt/PySide/Tkinter 데스크탑 코드는 참고 대상이 아니며, 재사용 시 "
                "동일 플랫폼 위반이 반복됩니다.)\n"
            )
    return (
        "\n\n## 이전 iteration 산출 코드 (참고 — 유지/개선 기준)\n\n"
        "아래는 직전 iteration 에서 Engineer 가 산출한 코드입니다.\n"
        "**기존 구조와 식별자(파일명/클래스/함수 시그니처)를 최대한 유지** 하면서 "
        "보정 지시의 must-fix 항목만 개선하세요.\n"
        "전체를 백지에서 다시 작성하는 것은 **퇴행** 이며 사용자가 이전 결과를 "
        "잃습니다 (Phase 6.E PR #232 명세).\n\n"
        "--- 이전 iter 코드 발췌 ---\n"
        f"{excerpt}\n"
        "--- 끝 ---\n"
    )


def _build_platform_constraint(platform_intent: str) -> str:
    """v13 Phase 6.E P1 (PR #235) — 플랫폼 드리프트 예방 제약 텍스트.

    ``platform_intent == "web"`` 이면 엔지니어 프롬프트에 *데스크탑 GUI 금지 +
    Three.js/WebGL 강제* 하드 제약을 반환한다. iter 1 부터 주입되어 Track A/B 의
    데스크탑 .exe 기본값(특히 Track A "Calculator-style" 데스크탑 편향)보다 우선한다.

    Args:
        platform_intent: ``_detect_platform`` 산출 ("web" | "desktop" | "unspecified").

    Returns:
        web 면 제약 텍스트, 그 외엔 빈 string (회귀 0 — 기존 동작 불변).

    배경:
        crash analysis 2026-05-29 — "Three.js BIM 뷰어"(web) 요청에 엔지니어가
        7/7 PyQt 데스크탑으로 드리프트. 명시 플랫폼(web)이 Track 기본값을 이기게 함.
    """
    if platform_intent == "desktop":
        # v13 P25 — desktop 단일 폼팩터 계약(콘솔/GUI 혼재 금지). 콘솔+Tk 혼재 산출 방지.
        return (
            "\n\n## 🖥️ 폼팩터 계약 (P25, 데스크탑 — 단일 폼팩터)\n"
            "타겟 = **데스크탑 단일 `.exe`**. **하나의 폼팩터만** 선택하세요 — *콘솔(argparse/"
            "print/input) 과 GUI(Tkinter/PySide) 를 혼재 금지*. 엔트리는 선택한 폼팩터로 일관되게 "
            "(GUI면 창이 뜨고, 콘솔이면 콘솔로) 동작해야 하며, 빌드 후 스모크 게이트가 *실행되는 "
            "단일 산출물* 을 검증합니다."
        )
    if platform_intent != "web":
        return ""
    return (
        "\n\n## 🚫 플랫폼 제약 (P1, 최우선 — Track 기본값 무시)\n"
        "타겟 = **web / 브라우저**. 반드시 **Three.js + WebGL + HTML/JS/CSS** 로 "
        "구현하세요.\n"
        "**PyQt / PySide / Tkinter 등 데스크탑 GUI 프레임워크는 절대 금지** "
        "(.exe 데스크탑 셸 포함).\n"
        "Track A/B 의 데스크탑 산출 기본값보다 *이 플랫폼 제약이 우선* 합니다."
        "\n\n## 📦 배포성 (P25, web — 단일 명령 실행)\n"
        "프로덕션 서버가 빌드된 `dist/` 를 *정적 서빙*(express.static + SPA fallback) 하고, "
        "`package.json` 의 단일 `start`(예: `node server.js`) 로 프론트+API 가 한 포트에서 떠야 "
        "합니다. `npm run dev`/`vite dev`/`concurrently` 등 **dev 전용 의존 금지**. `README` 에 "
        "단일 실행 명령 명시. (server 가 dist 미서빙 → 루트 'Cannot GET /' → 배포성 게이트 FAIL.)"
    )


def _resolve_prev_build_artifact(state: _LoopState) -> tuple[str, str]:
    """v13 P22 — iter 2+ 체크포인트용 직전 iteration 빌드 아티팩트 경로(읽기 전용, best-effort).

    직전 ``state["chain_result"].executor_result.exe_path`` 만 읽는다(실행·수정 없음). 반환:
        (path, category) — category 는 확장자 기준 "web"(.html/.htm) | "desktop".
        빌드 미존재/실패/경로 부재 시 ("", "") → GUI '빌드 열어보기' 비활성 + 안내.
    """
    try:
        prev = state.get("chain_result")
        exec_res = getattr(prev, "executor_result", None) if prev is not None else None
        exe = getattr(exec_res, "exe_path", None) if exec_res is not None else None
        if not exe:
            return ("", "")
        p = Path(str(exe))
        if not p.exists():  # 빌드 SKIP/실패 → dist/ 또는 .exe 미생성
            return ("", "")
        category = "web" if p.suffix.lower() in (".html", ".htm") else "desktop"
        return (str(p), category)
    except Exception:  # noqa: BLE001 — best-effort, 실패해도 체크포인트는 그대로 진행
        return ("", "")


def _build_checkpoint_plan_summary(
    state: _LoopState, *, prev_build_path: str = "", prev_build_category: str = ""
) -> str:
    """v13 P20 — codegen 직전 체크포인트에서 사람에게 보여줄 계획/스펙 요약 조립.

    이 시점(run_chain 진입, 첫 codegen 직전)에 확정된 재료: 요청 + 플랫폼 의도 +
    스펙(expand_requirements 산출) + 킥오프 계획(kickoff_meeting 산출). 코드는 아직 미생성.

    v13 P22 — iter 2+(state["iteration"]>=1) 진입 시 직전 iteration 의 gap·피드백 / QA /
    빌드 경로를 *추가*로 덧붙인다. iter 1(iteration==0) 진입 시엔 아래 블록 전체 skip →
    P20 요약과 byte 동일(회귀 0).
    """
    parts: list[str] = []
    req = (state.get("user_request") or "").strip()
    if req:
        parts.append(f"[요청]\n{req[:400]}")
    parts.append(f"[플랫폼 의도] {state.get('platform_intent', 'unspecified')}")
    spec = (state.get("spec_markdown") or "").strip()
    if spec:
        parts.append(f"[스펙 (Requirement Expander)]\n{spec[:1500]}")
    skd = state.get("shared_kickoff_decisions")
    if skd is not None:
        try:
            parts.append(f"[킥오프 계획]\n{str(skd)[:800]}")
        except Exception:  # noqa: BLE001
            pass

    # ★ v13 P22 — iter 2+ 전용 컨텍스트(직전 빌드/ gap / QA). iter 1 은 진입 안 함.
    if state.get("iteration", 0) >= 1:
        prev_fb = (state.get("feedback") or "").strip()
        if prev_fb:
            parts.append(f"[직전 iteration gap·피드백]\n{prev_fb[:1200]}")
        prev = state.get("chain_result")
        qa = (getattr(prev, "qa_review", "") or "").strip() if prev is not None else ""
        if qa:
            parts.append(f"[직전 QA 요약]\n{qa[:800]}")
        if prev_build_path:
            cat = prev_build_category or "unknown"
            parts.append(
                f"[직전 빌드 ({cat})]\n{prev_build_path}\n"
                "→ 패널의 '빌드 열어보기'로 실제 앱을 확인한 뒤 피드백을 주입하세요."
            )
        else:
            parts.append("[직전 빌드] (없음 또는 실패 — '빌드 열어보기' 비활성. gap·피드백은 그대로 가능)")
    return "\n\n".join(parts)


def _node_run_chain(state: _LoopState) -> dict[str, Any]:
    """analyze_and_implement (Track A) 또는 automate_workflow (Track B) 체인 호출.

    iteration 마다 실행. PR #158 — ``state["track"]`` 가 "B" 면 Track B 분기 (Track A
    의 WorkflowResult 와 호환되는 SimpleNamespace 로 어댑터).

    v13 Phase 6.E (PR #232) — iter 2+ 진입 시 ``state["chain_result"]`` (이전
    iter 의 산출) 를 발췌해 prompt 에 첨부. *백지 재시작 차단*.
    """
    next_iter = state["iteration"] + 1
    feedback = state.get("feedback", "")

    # ★ v13 P20→P22 — codegen 직전 사람 개입 체크포인트 (opt-in).
    # 그래프 순서상 expand_requirements(스펙)+kickoff_meeting(계획)이 이미 끝났고 codegen
    # 체인은 아직 미실행 = "계획·스펙 확정 후, 코드 생성 전". intervene=False(기본)면 완전 no-op
    # (import 조차 없음 → 회귀 0). 입력 시 P12 conduit(feedback→request_with_feedback)로 주입.
    #
    # P22 일반화: max_iterations>=2 면 *매 iteration* codegen 직전에 발동(iter 2+ 는 직전
    # 빌드 + gap 요약 포함). MAX-ITER=1 은 next_iter==1 만 발동 = P20 와 100% 동일(iter 2+ 없음).
    max_iter = state.get("max_iterations", DEFAULT_MAX_ITERATIONS)
    if state.get("intervene", False) and (next_iter == 1 or max_iter >= 2):
        from src.workflows._intervention import (  # noqa: PLC0415
            DEFAULT_INTERVENE_TIMEOUT_SEC,
            format_intervention_directive,
            request_codegen_intervention,
        )

        # iter 2+ — 직전 iteration 빌드 아티팩트(읽기 전용). iter 1 은 빌드 전이라 ("", "").
        prev_build_path, prev_build_category = (
            _resolve_prev_build_artifact(state) if next_iter >= 2 else ("", "")
        )
        human_feedback = request_codegen_intervention(
            _build_checkpoint_plan_summary(
                state,
                prev_build_path=prev_build_path,
                prev_build_category=prev_build_category,
            ),
            intervene=True,
            timeout_sec=state.get("intervene_timeout", DEFAULT_INTERVENE_TIMEOUT_SEC),
            iteration=next_iter,
            prev_build_path=prev_build_path,
        )
        if human_feedback:
            directive = format_intervention_directive(human_feedback)
            feedback = (feedback + directive) if feedback else directive

    # ★ Phase 6.E (PR #232) — iter 2+ 진입 시 이전 chain_result 의 코드 첨부.
    # iter 1 진입 시 state["chain_result"] = None → 빈 context → 회귀 0.
    prev_code_context = ""
    if next_iter > 1:
        prev_code_context = _build_prev_code_context(
            state.get("chain_result"),
            platform_intent=state.get("platform_intent", "unspecified"),
        )
    # ★ Phase 6.E P1 (PR #235) — 플랫폼 드리프트 예방: web 의도면 데스크탑 GUI 금지
    # 하드 제약을 iter 1 부터 주입. Track A/B 데스크탑 기본값보다 우선.
    # platform_intent != "web" 이면 빈 문자열 → 회귀 0 (기존 동작 불변).
    platform_constraint = _build_platform_constraint(state.get("platform_intent", "unspecified"))
    base_request = f"{state['user_request']}{platform_constraint}"
    if feedback or prev_code_context:
        request_with_feedback = f"{base_request}\n\n{feedback}{prev_code_context}"
    else:
        request_with_feedback = base_request

    outputs_dir = Path(state["outputs_dir"]) if state.get("outputs_dir") else DEFAULT_OUTPUTS_DIR

    track = state.get("track", "A")
    if track == "B":
        # PR #158 — Track B 분기: run_automate_workflow 호출 → 어댑터 → chain_result
        from src.workflows.automate_workflow import run_automate_workflow

        enable_build = state.get("enable_executor", False) or state.get(
            "enable_build_branch", False
        )
        enable_release = state.get("enable_publish", False) or state.get(
            "enable_release_branch", False
        )
        automate_result = run_automate_workflow(
            request_with_feedback,
            outputs_dir=outputs_dir,
            verbose=state.get("verbose", False),
            enable_qa_loop=enable_build,  # Track B QA loop 는 build 와 함께 활성
            enable_build=enable_build,
            build_timeout_sec=state.get("executor_timeout_sec", 300),
            enable_release=enable_release,
            repo_url=state.get("repo_url", ""),
            release_tag=state.get("release_tag", ""),
            publish_as_draft=state.get("publish_as_draft", True),
            publish_timeout_sec=state.get("publish_timeout_sec", 120),
            target_platform=state.get("target_platform", "windows"),
            # PR #183 — CLI --forced-domain 전달 (Track B 도메인 자동 분류 우회)
            forced_domain=state.get("forced_domain"),
        )
        chain_result = _adapt_automate_to_chain_result(automate_result)
    else:
        chain_result = run_analyze_and_implement(
            request_with_feedback,
            outputs_dir=outputs_dir,
            verbose=state.get("verbose", False),
            enable_gui_branch=state.get("enable_gui_branch", False),
            enable_build_branch=state.get("enable_build_branch", False),
            target_platform=state.get("target_platform", "windows"),
            enable_release_branch=state.get("enable_release_branch", False),
            previous_version=state.get("previous_version", ""),
            repo_url=state.get("repo_url", ""),
            signing_available=state.get("signing_available", False),
            privacy_level=state.get("privacy_level", "public"),
            # PR #157 — production wire: 실 .exe 빌드 + Draft Release 발행 propagate.
            # 기본 False 유지 (기존 호출 측 backward compat).
            enable_executor=state.get("enable_executor", False),
            executor_timeout_sec=state.get("executor_timeout_sec", 300),
            enable_publish=state.get("enable_publish", False),
            publish_as_draft=state.get("publish_as_draft", True),
            publish_timeout_sec=state.get("publish_timeout_sec", 120),
            shared_kickoff_decisions=state.get("shared_kickoff_decisions"),
            enable_engineer_reviewer_delegation=state.get(
                "enable_engineer_reviewer_delegation", False
            ),
            # v13 Phase 6.E P3 — GUI Code Generator 의 인-이터레이션 드리프트 reject+
            # 재생성 게이트 활성화용 (web 의도일 때만 동작). default "unspecified" 라
            # 기존 호출 측·desktop/unspecified 경로 불변 (회귀 0).
            platform_intent=state.get("platform_intent", "unspecified"),
        )

    artifacts = list(state.get("iteration_artifacts", []))
    # PR #158 — Track B 의 saved_dir 이 None 일 수 있음 (outputs_dir=None 인 경우).
    # outputs_dir 폴백으로 안전성 보장.
    saved_dir = getattr(chain_result, "saved_dir", None) or outputs_dir
    artifacts.append(saved_dir.as_posix() if hasattr(saved_dir, "as_posix") else str(saved_dir))

    return {
        "iteration": next_iter,
        "chain_result": chain_result,
        "iteration_artifacts": artifacts,
        # 새 iteration 시작 — 이전 iter 의 sandbox 산출은 무효
        "execution_result": None,
    }


# GUI 프레임워크의 *최상위 모듈 이름* — AST `import X` / `from X import ...` 매칭용.
# PR #209 의 substring grep 을 PR (본 PR) 에서 AST 기반으로 강화.
# 4회 BLOCKED 사고 (계산기 / 유튜브 녹화기 / theme.py entry / 칸반 보드) 차단.
_GUI_TOP_LEVEL_MODULES: frozenset[str] = frozenset({
    "tkinter",
    "flet",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "customtkinter",
    "kivy",
    "wx",
    "dearpygui",
    "ttkbootstrap",  # tkinter 기반 — 동일 mainloop 문제
    "pygame",        # event loop 동일
})


def _ast_detect_gui_in_code(code: str) -> bool:
    """단일 .py 코드 문자열에 GUI framework import 가 있는지 AST 로 검사.

    `ast.walk` 로 모든 노드 순회 → `ast.Import` / `ast.ImportFrom` 의 *top-level
    module 이름* 을 `_GUI_TOP_LEVEL_MODULES` 와 매칭. 주석/문자열 안의 marker
    는 *false positive* — AST 방식은 *실제 import 만* 검출 (PR #209 substring
    grep 의 한계 극복).

    Args:
        code: Python source 코드 문자열.

    Returns:
        True 면 GUI framework import 발견. AST parse 실패 (SyntaxError) 시는
        보수적으로 **substring fallback** 으로 한 번 더 검사.
    """
    if not code:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        # AST parse 실패 — substring fallback (보수적 양성 판정).
        return _substring_detect_gui_in_code(code)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = (alias.name or "").split(".", 1)[0]
                if top in _GUI_TOP_LEVEL_MODULES:
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".", 1)[0]
            if module in _GUI_TOP_LEVEL_MODULES:
                return True
    return False


def _substring_detect_gui_in_code(code: str) -> bool:
    """AST 실패 시 fallback — substring grep. PR #209 패턴 유지 (보수적)."""
    markers = (
        "import tkinter", "from tkinter",
        "import flet", "from flet",
        "import PyQt5", "import PyQt6", "from PyQt5", "from PyQt6",
        "import PySide2", "import PySide6", "from PySide2", "from PySide6",
        "import customtkinter", "from customtkinter",
        "import kivy", "from kivy",
        "import wx", "from wx",
        "import dearpygui", "from dearpygui",
        "import ttkbootstrap", "from ttkbootstrap",
        "import pygame", "from pygame",
    )
    return any(m in code for m in markers)


def _detect_gui_in_saved_files(saved_code_files: Any) -> bool:
    """saved_code_files (dict of path → code) 중 *어느 한 file* 에라도 GUI
    framework import 가 있으면 True.

    2026-05-26 강화 (4회 BLOCKED 사고 처방):
        - 기존 substring grep → AST `ast.walk` + `ast.Import` / `ast.ImportFrom` 매칭
        - GUI module 추가: ttkbootstrap (tkinter 기반), pygame (event loop)
        - AST parse 실패 시 substring fallback
    """
    if not saved_code_files:
        return False
    try:
        values = saved_code_files.values()
    except AttributeError:
        return False
    for code in values:
        try:
            code_str = str(code) if code is not None else ""
        except (TypeError, ValueError):
            continue
        if _ast_detect_gui_in_code(code_str):
            return True
    return False


def _make_gui_skip_sandbox_result() -> Any:
    """GUI 앱 감지 시 sandbox 실행을 skip 하면서도 *PASS 시뮬레이션* SandboxResult.

    SandboxResult.verdict 는 ``field(init=False)`` 라 ``__post_init__`` 가
    derive — exit_code=0 + timed_out=False → ``"PASS"``. 후속 Convergence Judge
    가 sandbox PASS 로 인식해 QA 차단 없이 통과. stderr 에 SKIP 사유 명시.
    """
    from src.agents.operations.sandbox_runner import SandboxResult

    return SandboxResult(
        exit_code=0,
        stdout="",
        stderr=(
            "[GUI_SKIP] GUI 앱 감지 (tkinter/flet/PyQt/PySide/customtkinter/kivy/wx) — "
            "mainloop() 가 헤드리스 sandbox 에서 종료되지 않아 TIMEOUT 회피 위해 "
            "sandbox 실행 SKIP. PyInstaller 빌드 단계에서 .exe 산출."
        ),
        elapsed_sec=0.0,
        timed_out=False,
        timeout_sec=0,
    )


def _node_run_sandbox(state: _LoopState) -> dict[str, Any]:
    """Phase 3 — Engineer 산출 코드를 별도 프로세스에서 실행.

    Phase 3 보강 (2026-04-20):
        단일 파일 entry 만 다루던 초기 버전을 폐기하고, 멀티파일 패키지를
        디렉터리 트리째 재구성·실행하는 `run_python_package_in_sandbox` 로 위임.

    GUI 자동 SKIP (2026-05-26):
        saved_code_files 의 코드에 GUI 프레임워크 import 가 있으면 sandbox 실행
        없이 PASS 시뮬레이션 SandboxResult 반환. Tkinter mainloop TIMEOUT 으로
        앱 빌드가 BLOCKED 되는 사고 (kanban 앱 사례) 차단용.

    동작 요약:
        1. `enable_sandbox=False` → 즉시 None 반환 (skip)
        2. `saved_code_files` 비었음 → None (FakeProvider 시나리오 등)
        3. **GUI 마커 감지 → PASS 시뮬레이션 SandboxResult 반환** (2026-05-26)
        4. `run_python_package_in_sandbox` 호출:
             - 트리 재구성 + entry 탐지 + 실행
             - entry 미탐지 시 함수가 None 반환 → 그대로 전달
        5. 잘못된 입력 (TypeError/ValueError) → None fallback (루프 안전성 우선)

    Returns:
        {"execution_result": SandboxResult | None}
    """
    if not state.get("enable_sandbox", True):
        return {"execution_result": None}

    chain: WorkflowResult = state["chain_result"]
    if not chain or not chain.saved_code_files:
        return {"execution_result": None}

    # GUI 자동 SKIP (kanban 앱 BLOCKED 사고 처방).
    if _detect_gui_in_saved_files(chain.saved_code_files):
        return {"execution_result": _make_gui_skip_sandbox_result()}

    try:
        result = run_python_package_in_sandbox(
            chain.saved_code_files,
            timeout_sec=state.get("sandbox_timeout_sec", DEFAULT_SANDBOX_TIMEOUT_SEC),
        )
    except (TypeError, ValueError):
        return {"execution_result": None}

    return {"execution_result": result}


def _write_desktop_smoke_artifact(saved_dir: Path, result: Any, exe_path: Path) -> None:
    """v13 P23 — `27_desktop_smoke_<verdict>.md` 작성 (25_executor_result.md 직후 가시 증거)."""
    verdict_lower = str(getattr(result, "verdict", "unknown")).lower()
    artifact_path = saved_dir / f"27_desktop_smoke_{verdict_lower}.md"
    body_lines = [
        "# Desktop .exe Runtime Smoke (v13 P23)",
        "",
        f"- **verdict**: `{getattr(result, 'verdict', '?')}`",
        f"- **signal**: `{getattr(result, 'signal', '')}`",
        f"- **exe**: `{exe_path.name}`",
        f"- **exit_code**: {getattr(result, 'exit_code', None)}",
        f"- **survived_sec**: {getattr(result, 'survived_sec', 0.0)}",
        f"- **reason**: {getattr(result, 'reason', '')}",
        "",
        "## error_excerpt",
        "",
        "```",
        (getattr(result, "error_excerpt", "") or "(없음)").strip()[:2000],
        "```",
    ]
    artifact_path.write_text("\n".join(body_lines), encoding="utf-8")


def _emit_smoke_event(result: Any, exe_path: Path) -> None:
    """v13 P23 — SmokeEvent 를 events.jsonl 에 emit (telemetry 활성 시만, fail-safe)."""
    from src.monitoring import SmokeEvent, get_telemetry_emitter  # noqa: PLC0415

    emitter = get_telemetry_emitter()
    if getattr(emitter, "enabled", False):
        ec = getattr(result, "exit_code", None)
        emitter.emit(
            SmokeEvent(
                verdict=str(getattr(result, "verdict", "")),
                reason=(getattr(result, "reason", "") or "")[:500],
                signal=str(getattr(result, "signal", "")),
                exit_code=ec if isinstance(ec, int) else 0,
                exe_path=exe_path.name,
                survived_sec=float(getattr(result, "survived_sec", 0.0) or 0.0),
            )
        )


def _run_desktop_smoke_gate(state: _LoopState) -> dict[str, Any]:
    """v13 P23 — 빌드된 desktop .exe 런타임 스모크 (기본 ON, desktop+.exe 한정).

    ``enable_rv``(opt-in)와 *독립* — 기본 ON. 빌드 후 판정 직전 .exe 를 잠깐 띄워 실행 즉시/
    실행 중 크래시·치명 에러를 검출, 결과를 ``state["smoke_result"]`` 에 보존한다. judge 노드의
    ``_apply_smoke_failure_override`` 가 이를 읽어 FAIL 시 COMPLETE 를 차단하고 에러를 다음
    iteration must-fix 로 주입한다.

    no-op 조건 (기존 동작 보존 — 회귀 0). **stale 방지**: no-op 도 ``{}`` 가 아니라
    ``{"smoke_result": None}`` 을 반환해 *매 iteration* 직전 값을 명시적으로 비운다 — 어떤
    iteration 의 desktop FAIL 이 이후 web/none/skip iteration 의 COMPLETE 를 거짓 차단하지 않게:
        - ``enable_smoke`` False (--no-smoke).
        - executor_result 없음 / 빌드 실패(success=False) → 기존 build override 에 위임(이중 실패 X).
        - web 빌드(_is_web_build_result) → P17 web 시각 QA 가 커버.
        - exe_path 가 .exe 가 아니거나(.html 등) 디스크에 없음 → skip.
        - 스모크 실행 예외 → silent (검증 실패가 cycle 차단 X).
    """
    # enable_smoke=False(--no-smoke) → smoke 가 이 런에서 한 번도 안 돎 → stale 없음 → 순수 no-op({}).
    if not state.get("enable_smoke", True):
        return {}
    # 이하 no-op 분기는 smoke 가 *켜진* 런의 비대상(web/none/.exe 부재) iteration —
    # 직전 desktop FAIL 의 stale 을 None 으로 덮어써 후속 COMPLETE 거짓 차단 방지.
    cleared = {"smoke_result": None}
    chain = state.get("chain_result")
    exec_res = getattr(chain, "executor_result", None) if chain is not None else None
    if exec_res is None:
        return cleared
    if not getattr(exec_res, "success", False):
        return cleared  # 빌드 실패 → _apply_build_failure_override 가 처리
    if _is_web_build_result(exec_res):
        return cleared  # web → P17 커버
    exe = getattr(exec_res, "exe_path", None)
    if not exe:
        return cleared
    p = Path(str(exe))
    if p.suffix.lower() != ".exe" or not p.exists():
        return cleared

    try:
        from src.agents.runtime_verification import run_desktop_smoke_gate  # noqa: PLC0415

        result = run_desktop_smoke_gate(p, timeout_sec=float(state.get("smoke_timeout", 8)))
    except Exception:  # noqa: BLE001 — 스모크 실패가 메인 cycle 차단 X
        return cleared

    saved_dir = getattr(chain, "saved_dir", None)
    if isinstance(saved_dir, Path) and saved_dir.exists():
        try:
            _write_desktop_smoke_artifact(saved_dir, result, p)
        except Exception:  # noqa: BLE001
            pass  # artifact 실패가 메인 cycle 차단 X
    try:
        _emit_smoke_event(result, p)
    except Exception:  # noqa: BLE001
        pass  # emit 실패가 메인 cycle 차단 X

    return {"smoke_result": result}


def _write_deployability_artifact(saved_dir: Path, result: Any) -> None:
    """v13 P25 — `28_deployability_<verdict>.md` 작성 (27_desktop_smoke 옆, 가시 배포성 증거)."""
    verdict_lower = str(getattr(result, "verdict", "unknown")).lower()
    artifact_path = saved_dir / f"28_deployability_{verdict_lower}.md"
    body_lines = [
        "# 산출물 배포성 게이트 (v13 P25)",
        "",
        f"- **verdict**: `{getattr(result, 'verdict', '?')}`",
        f"- **signal**: `{getattr(result, 'signal', '')}`",
        f"- **command**: `{getattr(result, 'command', '') or '(없음)'}`",
        f"- **serves_dist**: {getattr(result, 'serves_dist', None)}",
        f"- **dev_only**: {getattr(result, 'dev_only', None)}",
        f"- **root_status**: `{getattr(result, 'root_status', '')}`",
        f"- **reason**: {getattr(result, 'reason', '')}",
        "",
        "## error_excerpt (must-fix)",
        "",
        "```",
        (getattr(result, "error_excerpt", "") or getattr(result, "reason", "") or "(없음)").strip()[:2000],
        "```",
    ]
    artifact_path.write_text("\n".join(body_lines), encoding="utf-8")


def _run_packageability_gate(state: _LoopState) -> dict[str, Any]:
    """v13 P25 — 빌드된 *web* 산출물이 문서화된 단일 프로덕션 명령으로 동작하는지 검증(기본 ON).

    P23 desktop smoke 의 형제 게이트. P17 시각 QA 가 dist 를 *자체* 정적 서버로 띄워 통과하던
    사각지대(배포 산출물 미검증)를 메운다 — 본 게이트는 *프로덕션 단일 명령*(npm start / node
    server.js) 으로 프로덕션 서버를 띄워 루트 `/` 가 앱으로 로드되는지 확인(dev 서버 아님). 결과를
    ``state["deployability_result"]`` 에 보존 → judge 의 ``_apply_deployability_failure_override`` 가
    FAIL 시 COMPLETE 를 차단하고 배포성 must-fix 를 다음 iteration 에 주입한다.

    no-op (기존 동작 보존, stale 방지 — smoke 와 동일 2단 분기):
        - ``enable_packageability`` False → 순수 no-op({}).
        - executor_result 없음 / 빌드 실패 → build override 에 위임.
        - desktop(web 아님) → P23 smoke + 단일 폼팩터 계약이 담당 → clear.
        - web 코드 디렉터리(dist/index.html → dist → code) 미탐 → clear.
        - 게이트 예외 → silent (검증 실패가 cycle 차단 X).
    """
    if not state.get("enable_packageability", True):
        return {}  # OFF → 이 런에서 한 번도 안 돎 → stale 없음 → 순수 no-op
    cleared = {"deployability_result": None}  # 비대상 iteration: 직전 FAIL 의 stale 을 명시 클리어
    if (state.get("platform_intent", "unspecified") or "").lower() != "web":
        return cleared  # web 의도 아님 → 비대상 (desktop/none 은 smoke/계약 담당)
    chain = state.get("chain_result")
    exec_res = getattr(chain, "executor_result", None) if chain is not None else None
    if exec_res is None or not getattr(exec_res, "success", False):
        return cleared  # 빌드 실패 → _apply_build_failure_override 가 처리
    if not _is_web_build_result(exec_res):
        return cleared  # web 빌드 산출 아님
    # web 빌드: exe_path = code_dir/dist/index.html → code_dir = exe_path.parent.parent.
    exe = getattr(exec_res, "exe_path", None)
    if not exe:
        return cleared
    index = Path(str(exe))
    code_dir = index.parent.parent if index.parent.name == "dist" else index.parent
    if not code_dir.is_dir():
        return cleared

    try:
        from src.agents.runtime_verification import run_packageability_gate  # noqa: PLC0415

        result = run_packageability_gate(code_dir, "web")
    except Exception:  # noqa: BLE001 — 게이트 실패가 메인 cycle 차단 X
        return cleared

    saved_dir = getattr(chain, "saved_dir", None)
    if isinstance(saved_dir, Path) and saved_dir.exists():
        try:
            _write_deployability_artifact(saved_dir, result)
        except Exception:  # noqa: BLE001
            pass  # artifact 실패가 메인 cycle 차단 X

    return {"deployability_result": result}


def _node_runtime_verify(state: _LoopState) -> dict[str, Any]:
    """v13 Phase 1 2단계 — 본부 9 Runtime Verification opt-in 노드.

    `run_sandbox` 직후 진입. 빌드 산출 .exe 가 있고 `enable_rv=True` 면
    `Exe Runtime Tester` 가 silent fail / crash 자율 감지. 감지 결과를 state
    의 ``rv_result`` + ``rv_failure_detected`` 에 보존하여 후속 ``prepare_feedback``
    분기에서 활용 가능 (Phase 3 wire 시점에 *직접 라우팅* 으로 확장).

    안전성 — default OFF:
        ``enable_rv=False`` (default) 면 즉시 빈 dict 반환 (no-op). LangGraph
        state 변경 0 → 기존 1477 PASS 안정성 회귀 위험 0.

    v13 P23 — 진입 시 *항상* desktop .exe 런타임 스모크 게이트를 먼저 실행한다(기본 ON,
    enable_rv 와 독립). 스모크 결과는 ``smoke_result`` 로 보존되어 judge 가 소비한다. 이후
    기존 RV(opt-in) 경로는 그대로 — enable_rv=False 면 스모크 결과만 반환.

    Returns:
        ``{**smoke_update}`` (enable_rv=False) — desktop 스모크 결과(있으면) + RV pass-through
        ``{**smoke_update, "rv_result": RuntimeTestResult, "rv_failure_detected": bool, ...}``
    """
    # v13 P23 — desktop 런타임 스모크 게이트 (기본 ON, enable_rv 와 독립).
    smoke_update = _run_desktop_smoke_gate(state)
    # v13 P25 — web 배포성 게이트 (기본 ON, smoke 와 형제). web 빌드만 평가, desktop/none SKIP.
    pkg_update = _run_packageability_gate(state)
    gate_update = {**smoke_update, **pkg_update}

    if not state.get("enable_rv", False):
        return gate_update

    # 빌드된 .exe 경로 추출 — chain_result 의 executor_result 또는 saved_dir 기반.
    chain: WorkflowResult = state.get("chain_result")  # type: ignore
    exe_path: Optional[Path] = None
    if chain is not None:
        executor_result = getattr(chain, "executor_result", None)
        if executor_result is not None:
            candidate = getattr(executor_result, "exe_path", None)
            if isinstance(candidate, Path) and candidate.exists():
                exe_path = candidate

    if exe_path is None:
        # 빌드 산출물 없음 — RV 실행 불가, no-op (회귀 0)
        return gate_update

    try:
        from src.agents.runtime_verification import run_exe_runtime_test

        rv_result = run_exe_runtime_test(exe_path, timeout_sec=3.0)
    except Exception:  # noqa: BLE001
        # RV 실패가 메인 cycle 차단 X — silent + no-op
        return gate_update

    failure_detected = rv_result.verdict in ("SILENT_FAIL", "CRASH")

    # PR #217 follow-up — 가시 artifact (26_runtime_verify_*.md) 보장.
    # events.jsonl 외에 outputs/ 폴더에서도 RV 결과를 즉시 확인 가능.
    saved_dir = getattr(chain, "saved_dir", None)
    if isinstance(saved_dir, Path) and saved_dir.exists():
        try:
            _write_runtime_verify_artifact(saved_dir, rv_result, exe_path)
        except Exception:  # noqa: BLE001
            pass  # artifact 실패가 메인 cycle 차단 X

    # v13 Phase 2 (PR #219) — Auto-Fix Coordinator escalate hook → Strategist 호출
    consecutive = int(state.get("consecutive_rv_failures", 0))
    if failure_detected:
        consecutive += 1
    else:
        consecutive = 0  # PASS 시 카운트 reset

    proposal_path = state.get("strategist_proposal_path")
    boardroom_session_path = state.get("boardroom_session_path")
    if state.get("enable_strategist", False) and failure_detected:
        try:
            new_proposal_path = _maybe_trigger_strategist(
                rv_result=rv_result,
                consecutive_failures=consecutive,
                outputs_dir=state.get("outputs_dir", ""),
            )
            if new_proposal_path is not None:
                proposal_path = new_proposal_path
                # v13 Phase 3 — Strategist 안건 작성 직후 Boardroom 회의 자동 소집
                # (enable_boardroom=True 시만; 의결권은 Phase 4 활성화)
                # v13 Phase 5.4 (PR #224) — enable_tikitaka 면 라운드 sequence 진행
                if state.get("enable_boardroom", False):
                    try:
                        new_session_path = _maybe_convene_boardroom(
                            proposal_path=new_proposal_path,
                            outputs_dir=state.get("outputs_dir", ""),
                            enable_tikitaka=state.get("enable_tikitaka", False),
                        )
                        if new_session_path is not None:
                            boardroom_session_path = new_session_path
                    except Exception:  # noqa: BLE001
                        pass  # Boardroom 실패가 메인 cycle 차단 X
        except Exception:  # noqa: BLE001
            pass  # Strategist 실패가 메인 cycle 차단 X

    return {
        **gate_update,  # v13 P23 desktop 스모크 + P25 web 배포성 결과 보존 (enable_rv 경로에서도)
        "rv_result": rv_result,
        "rv_failure_detected": failure_detected,
        "consecutive_rv_failures": consecutive,
        "strategist_proposal_path": proposal_path,
        "boardroom_session_path": boardroom_session_path,
    }


def _maybe_trigger_strategist(
    rv_result: Any,
    consecutive_failures: int,
    outputs_dir: str,
) -> Optional[Path]:
    """Auto-Fix Coordinator escalate 결정 시 Strategist 호출 → proposal md 저장.

    v13 Phase 2 (PR #219) — Phase 1 의 ``decide_auto_fix`` hook 을 활용한 wire.

    Strategist 입력 구성:
        1. events.jsonl (있으면) — 라이브 telemetry stream
        2. *in-memory 합성 events* — events.jsonl 부재 시 (test 환경 / telemetry
           OFF) 에도 결정론 패턴 매처가 동작하도록 ``consecutive_failures`` 개수
           만큼 SILENT_FAIL/CRASH 합성 event 를 주입.
    """
    from src.agents.runtime_verification.auto_fix_coordinator import decide_auto_fix
    from src.agents.analysis.system_refactoring_strategist import (
        analyze_runtime_patterns,
        write_proposal_markdown,
    )

    # Auto-Fix Coordinator 호출 → escalate 여부 판정
    decision = decide_auto_fix(
        runtime_result=rv_result,
        failure_analysis=None,
        ui_result=None,
        consecutive_failures=consecutive_failures,
    )

    if decision.action != "escalate":
        return None

    # events.jsonl path — env var 에서 추출 (--emit-events 가 set 한 경로)
    events: list[dict[str, Any]] = []
    raw = (os.environ.get("NEXUS_TELEMETRY_PATH") or "").strip()
    if raw:
        candidate = Path(raw)
        if candidate.exists():
            try:
                import json as _json
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(_json.loads(line))
                    except _json.JSONDecodeError:
                        continue
            except Exception:  # noqa: BLE001
                pass

    # in-memory 합성 events — events.jsonl 부재 또는 silent_fail 카운트 부족 시
    # ``consecutive_failures`` 만큼 verdict 시그널을 주입 (결정론 매처 활성화).
    synthetic_verdict = (
        rv_result.verdict if rv_result and rv_result.verdict in ("SILENT_FAIL", "CRASH")
        else "SILENT_FAIL"
    )
    for _ in range(consecutive_failures):
        events.append({
            "agent": "exe_runtime_tester",
            "status": "done",
            "detail": f"verdict={synthetic_verdict}",
        })

    proposal = analyze_runtime_patterns(events=events, recent_verdicts=None)

    if outputs_dir:
        output_dir = Path(outputs_dir) / "_refactoring_proposals"
    else:
        output_dir = Path("outputs") / "_refactoring_proposals"

    return write_proposal_markdown(proposal, output_dir)


def _maybe_convene_boardroom(
    proposal_path: Path,
    outputs_dir: str,
    enable_tikitaka: bool = False,
) -> Optional[Path]:
    """v13 Phase 3+4+5.4 — Strategist 안건 작성 후 Boardroom 회의 자동 소집.

    동작:
        1. proposal markdown 첫 줄 (# title) 추출 → duck-typed proposal 구성
           (estimated_cost / proposed_changes 는 기본값 — Phase 4 budget 평가용)
        2. ``convene_full_boardroom_cycle`` 호출 — boardroom_trigger →
           (옵션: tikitaka 3 라운드) → goal_alignment_check → budget_brake →
           FinalDecision
        3. 회의록 markdown ``outputs/_boardroom_sessions/`` + 의결 YAML
           ``outputs/board_decisions/`` 양쪽 저장 (schema v2)

    Args:
        proposal_path: Strategist 가 발제한 안건 markdown 경로.
        outputs_dir: 산출 디렉터리 부모.
        enable_tikitaka: True 면 Phase 5.4 양방향 라운드 진행. default False —
            Phase 4 직렬 의결 모드.

    Returns:
        회의록 markdown 경로 (실패 시 None).
    """
    from src.agents.coordination import convene_full_boardroom_cycle

    proposal_title = "(미지정 안건)"
    try:
        first_line = proposal_path.read_text(encoding="utf-8").splitlines()[0]
        if first_line.startswith("# "):
            proposal_title = first_line[2:].strip()
    except Exception:  # noqa: BLE001
        pass

    class _DuckProposal:
        title = proposal_title
        # Phase 4 의결 평가용 default — markdown 파싱 확장 시 채울 필드
        estimated_cost = "medium"
        proposed_changes: list[str] = []

    if outputs_dir:
        base = Path(outputs_dir)
        boardroom_dir = base / "_boardroom_sessions"
        decision_dir = base / "board_decisions"
    else:
        boardroom_dir = Path("outputs") / "_boardroom_sessions"
        decision_dir = Path("outputs") / "board_decisions"

    _, md_path, _yaml_path = convene_full_boardroom_cycle(
        proposal=_DuckProposal(),
        proposal_path=str(proposal_path),
        output_dir=boardroom_dir,
        decision_output_dir=decision_dir,
        enable_tikitaka=enable_tikitaka,
    )
    return md_path


def _write_runtime_verify_artifact(
    saved_dir: Path, rv_result: Any, exe_path: Path
) -> None:
    """`26_runtime_verify_<verdict>.md` 작성 — 사용자 가시 RV 증거.

    분석 reasoning: events.jsonl 만으로는 RV 동작이 *비가시* (CLI 사용자가
    텔레메트리를 직접 grep 해야 함). outputs/workflow/ 의 numbered .md 시퀀스에
    RV 결과를 끼워넣어 25_executor_result.md 직후 자연스럽게 확인 가능.
    """
    verdict_lower = str(rv_result.verdict).lower()
    artifact_path = saved_dir / f"26_runtime_verify_{verdict_lower}.md"
    body_lines = [
        "# Runtime Verification (본부 9 RV)",
        "",
        f"- **verdict**: `{rv_result.verdict}`",
        f"- **exe_path**: `{exe_path.name}`",
        f"- **exit_code**: {rv_result.exit_code}",
        f"- **startup_time_ms**: {rv_result.startup_time_ms:.1f}",
        f"- **memory_peak_mb**: {rv_result.memory_peak_mb}",
        f"- **timed_out**: {rv_result.timed_out}",
        "",
        "## stderr (excerpt)",
        "",
        "```",
        (rv_result.stderr or "(빈 stderr)").strip()[:2000],
        "```",
        "",
        "## error_trace",
        "",
        "```",
        (rv_result.error_trace or "(없음)").strip()[:2000],
        "```",
    ]
    artifact_path.write_text("\n".join(body_lines), encoding="utf-8")


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


# v13 Phase 6.E P12 — web 빌드 실패 자가수정 루프 (build error → must-fix → 재빌드)
# tsc: `src/foo.ts(12,5): error TS2304: Cannot find name 'Foo'.`
_TSC_ERROR_RE = re.compile(
    r"(?P<file>[^\s(]+\.\w+)\((?P<line>\d+),(?P<col>\d+)\):\s*(?P<msg>error\s+TS\d+:.*)"
)
# esbuild/vite: `✘ [ERROR] ...` 다음 줄 `    src/foo.ts:10:3:` / rollup `file.ts (10:3)`
_VITE_FILELOC_RE = re.compile(r"(?P<file>[\w./\\-]+\.\w+):(?P<line>\d+):(?P<col>\d+)")
_VITE_ROLLUP_RE = re.compile(r"(?P<file>[\w./\\-]+\.\w+)\s*\((?P<line>\d+):(?P<col>\d+)\)")
_VITE_KEYWORDS = (
    "error during build",
    "rollup failed to resolve",
    "could not resolve",
    "[vite]",
    "failed to resolve import",
    "transform failed",
)


def _parse_web_build_errors(text: str) -> list[str]:
    """web 빌드 stderr 에서 컴파일러/번들러 에러를 file:line 메시지로 파싱 (P12).

    tsc(``file(line,col): error TSxxxx: msg``) + vite/esbuild/rollup(``file:line:col`` /
    ``file (line:col)`` + 키워드 라인) 둘 다 인식. 중복 제거 + 최대 10건. 빈 입력/무매칭은
    빈 list (호출부가 error_message 첫 줄로 폴백).
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            found.append(key)

    for m in _TSC_ERROR_RE.finditer(text):
        _add(f"{m.group('file')}({m.group('line')},{m.group('col')}): {m.group('msg').strip()}")
    # vite/esbuild — 키워드 포함 라인 + 동반 file:line 위치
    for raw in text.splitlines():
        low = raw.lower()
        if not any(kw in low for kw in _VITE_KEYWORDS):
            continue
        loc = _VITE_FILELOC_RE.search(raw) or _VITE_ROLLUP_RE.search(raw)
        prefix = (
            f"{loc.group('file')}:{loc.group('line')}:{loc.group('col')} - " if loc else ""
        )
        _add(f"{prefix}{raw.strip()[:200]}")
        if len(found) >= 10:
            break
    # 키워드는 없지만 file:line:col 만 있는 esbuild 위치 라인도 보강 (tsc 미매칭 시)
    if not found:
        for m in _VITE_FILELOC_RE.finditer(text):
            _add(f"{m.group('file')}:{m.group('line')}:{m.group('col')}")
            if len(found) >= 10:
                break
    return found[:10]


def _is_web_build_result(executor_result: Any) -> bool:
    """ExecuteResult 가 web(npm/vite) 빌드 산출인지 판정 (P12 — web-scoped 게이트).

    web 러너는 command=[npm, ci, ...] + 실패 시 exit_code=-8. desktop(PyInstaller) 은
    command[0] 가 python/pyinstaller, exit_code 가 -1/-2/-4..-7. command[0]=='npm' 또는
    exit_code==-8 이면 web. (둘 다 아니면 desktop → 기존 BLOCKED 경로 불변.)
    """
    command = getattr(executor_result, "command", None) or []
    if command and str(command[0]).lower() == "npm":
        return True
    return getattr(executor_result, "exit_code", None) == -8


# v13 Phase 6.E P13 — 빌드 에러에 *구체적 수정 지시* 동봉 (코드젠이 무엇을 어떻게 고칠지)
# assignability / unknown 류 — 명시적 타입 주석 또는 as 캐스트로 타입 레벨 최소 수정.
_ASSIGNABILITY_TS_CODES: frozenset[str] = frozenset(
    {"TS2345", "TS2322", "TS18046", "TS2531", "TS2532", "TS2769", "TS2739", "TS2740"}
)
# 번들/설치/런타임 실패 마커 — 존재하면 "타입체크 전용 실패" 아님 (vite salvage 부적격).
_NON_TYPE_FAIL_MARKERS: tuple[str, ...] = (
    "npm err", "eresolve", "enoent", "rollup failed to resolve", "could not resolve",
    "failed to resolve import", "cannot find module", "module not found",
    "command not found", "is not recognized", "npm 미설치",
)


def _ts_fix_hint(error_line: str) -> str:
    """TS 에러 코드에 따른 구체적 수정 지시 (P13). 비-TS 면 빈 string."""
    m = re.search(r"\bTS(\d+)\b", error_line)
    if not m:
        return ""
    code = "TS" + m.group(1)
    if code in _ASSIGNABILITY_TS_CODES:
        return (
            " → 수정: 해당 심볼에 명시적 타입 주석(`: <Type>`) 또는 `as <Type>` 캐스트를 "
            "적용하세요 (런타임 동작은 정상 — 타입 레벨 최소 수정)."
        )
    return " → 수정: tsc 를 만족시키는 최소 타입 레벨 변경(주석/캐스트/시그니처)을 적용하세요."


def _format_build_errors_with_hints(errors: list[str], fallback: str) -> str:
    """파싱된 빌드 에러 목록을 file:line + 메시지 + 수정지시 block 으로 직렬화 (P13)."""
    if not errors:
        return f"  - {fallback}"
    return "\n".join(f"  - {e}{_ts_fix_hint(e)}" for e in errors[:10])


def _is_type_only_failure(stderr: str) -> bool:
    """web 빌드 실패가 *타입체크 전용*(tsc error) 인지 — 번들/설치/런타임 에러 부재 (P13).

    True 면 vite-only salvage 적격(esbuild 가 타입 무시 transpile → dist/ 가능). 번들 resolve
    /설치 ERESOLVE/런타임 module-not-found 등이 섞여 있으면 False (salvage 해도 실패 → BLOCKED).
    """
    if not stderr or not _TSC_ERROR_RE.search(stderr):
        return False
    low = stderr.lower()
    return not any(m in low for m in _NON_TYPE_FAIL_MARKERS)


def _apply_build_failure_override(
    decision: JudgmentDecision,
    chain_result: Any,
    *,
    gap: Optional[GapReport] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> JudgmentDecision:
    """PR #162 (2026-05-18) — PyInstaller build 실패 시 verdict 를 BLOCKED 로 override.

    이유 (2026-05-18 E2E 발견):
        ``judge_convergence`` 는 Gap Analyst 의 GapReport 만 입력으로 받음 → LLM 산출
        코드/QA review 가 "잘 됨" 이면 verdict=COMPLETE. 그러나 PyInstaller .exe 산출이
        실패한 경우 (entry 미탐지 -7, pip install 실패 -4, pre-validation 실패 -5,
        attribute 검증 실패 -6) **사용자 손에 도달 가능한 산출물이 없음** → COMPLETE
        는 *사용자 관점 거짓*. 본 override 가 deterministic 으로 BLOCKED 로 변환.

    적용 조건 (모두 충족):
        - ``decision.verdict == Verdict.COMPLETE`` (Judge 가 ok 라 한 케이스만)
          → IMPROVE_NEEDED 면 다음 iteration 가서 재시도 가능 → 그대로 둠.
          → BLOCKED 면 이미 차단된 상태 → cause 우선순위 유지.
        - ``chain_result`` 가 not None
        - ``chain_result.executor_result`` 가 not None (build 시도됨)
        - ``executor_result.success`` 가 False OR ``executor_result.exe_path`` 가 None

    Returns:
        새 JudgmentDecision (override 시) 또는 원본 (해당 사항 없음).
    """
    if decision.verdict != Verdict.COMPLETE:
        return decision
    if chain_result is None:
        return decision
    executor_result = getattr(chain_result, "executor_result", None)
    if executor_result is None:
        # build 비활성 또는 build 단계 미진입 — override 대상 아님
        return decision
    success = getattr(executor_result, "success", True)
    exe_path = getattr(executor_result, "exe_path", None)
    if success and exe_path is not None:
        # build 성공 — override 불필요
        return decision

    # build 시도됐는데 실패 → override
    exit_code = getattr(executor_result, "exit_code", "?")
    error_msg = getattr(executor_result, "error_message", None) or "unknown"
    error_first_line = error_msg.splitlines()[0] if error_msg else "unknown"

    # v13 Phase 6.E P12 — web 타깃 빌드 실패는 *즉시 terminal BLOCKED 로 강등하지 말고*
    # iterate 루프로 되먹여 자가수정. 빌드 stderr 의 tsc/vite 에러를 high-priority must-fix
    # 로 주입(file:line+메시지) → next_action → feedback → GUI Code Generator 가 해당 파일
    # 패치 → 다음 iteration 재빌드. iteration 예산 소진 시에만 BLOCKED(BUILD_FAILED).
    # desktop(PyInstaller) 은 아래 기존 경로 그대로 (web-scoped — 회귀 0).
    if _is_web_build_result(executor_result):
        stderr = getattr(executor_result, "stderr", "") or ""
        build_errors = _parse_web_build_errors(stderr) or _parse_web_build_errors(error_msg)
        # v13 Phase 6.E P13 — 에러 원문 + *구체적 수정 지시*(TS 코드별 타입주석/캐스트 안내) 동봉.
        errs_block = _format_build_errors_with_hints(build_errors, error_first_line)
        cur_iter = getattr(gap, "iteration", 0) if gap is not None else 0
        if cur_iter < max_iterations:
            # 예산 남음 → IMPROVE_NEEDED (라우터가 prepare_feedback → run_chain 으로 루프백).
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=(
                    f"WEB_BUILD_FAILED (exit={exit_code}) — Gap Analyst 는 COMPLETE 였으나 "
                    f"npm/tsc/vite 빌드가 실패. 자가수정 루프 계속 (iter {cur_iter}/{max_iterations})."
                ),
                next_action=(
                    "다음 web 빌드 에러를 *최우선 must-fix* 로 해당 파일을 패치하세요 "
                    "(각 에러의 '→ 수정:' 지시를 그대로 적용) — 그 다음 빌드 재시도. "
                    "**해당 파일 전체 패치 결과를 빠짐없이 반환하세요 (요약·축약·생략 금지, "
                    "Final Answer 뒤 본문에 전체 코드 블록 포함).** 기존 충족 요구는 회귀 금지:\n"
                    + errs_block
                ),
                must_fix_count=max(decision.must_fix_count, len(build_errors) or 1),
            )
        # 예산 소진 → BLOCKED(BUILD_FAILED) + 마지막 빌드 에러 첨부.
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.BUILD_FAILED,
            reason=(
                f"WEB_BUILD_FAILED (exit={exit_code}) — iteration 예산 소진(iter "
                f"{cur_iter}/{max_iterations})으로 자가수정 중단. dist/ 미산출."
            ),
            next_action="마지막 web 빌드 에러 (예산 소진 — 추가 자가수정 위해 --max-iterations 증액):\n"
            + errs_block,
            must_fix_count=decision.must_fix_count,
        )

    # desktop(PyInstaller) — 기존 BLOCKED(BUILD_FAILED) 경로 불변 (회귀 0)
    return JudgmentDecision(
        verdict=Verdict.BLOCKED,
        blocked_cause=BlockedCause.BUILD_FAILED,
        reason=(
            f"PyInstaller .exe 산출 실패 — Gap Analyst 는 COMPLETE 판정했으나 build "
            f"단계가 차단됨 (exit={exit_code}): {error_first_line}"
        ),
        next_action=(
            "executor_result.error_message 의 진단 메시지를 따라 LLM 산출 코드 또는 "
            "자연어 요청을 보정 후 재실행. 사용자 손에 도달 가능한 .exe 가 없으므로 "
            "COMPLETE 로 종료하지 않음."
        ),
        must_fix_count=decision.must_fix_count,
    )


def _apply_smoke_failure_override(
    decision: JudgmentDecision,
    smoke_result: Any,
    *,
    gap: Optional[GapReport] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> JudgmentDecision:
    """v13 P23 — desktop 런타임 스모크 FAIL 시 COMPLETE 를 차단하고 에러를 must-fix 로 주입.

    ``_apply_build_failure_override`` 의 형제 override (같은 자리·order discipline 으로 judge
    노드에서 호출). 빌드 .exe 산출은 성공했지만 *실행하면 크래시/치명 에러* 인 경우 — Gap
    Analyst 가 COMPLETE 라 해도 사용자 손에서 동작하지 않으므로 COMPLETE 는 거짓.

    적용 조건 (모두 충족):
        - ``decision.verdict == Verdict.COMPLETE`` (COMPLETE 만 차단; IMPROVE/BLOCKED 는 그대로).
        - ``smoke_result`` 가 not None 이고 ``verdict == "FAIL"`` (PASS/SKIPPED/미실행 → 원본 유지).

    동작:
        - 예산 남음(iter < max) → IMPROVE_NEEDED. 에러를 ``next_action`` 에 실어 P12 conduit
          (next_action → _format_feedback_for_next_iteration → feedback → run_chain)로 다음
          iteration CTO/Engineer 에 must-fix 주입 (자체 주입 로직 신설 0).
        - 예산 소진 → BLOCKED(BUILD_FAILED) + 마지막 런타임 에러 첨부.
    예외는 원본 decision 반환 (override 실패가 cycle 차단 X).
    """
    try:
        if decision is None or decision.verdict != Verdict.COMPLETE:
            return decision
        if smoke_result is None or getattr(smoke_result, "verdict", None) != "FAIL":
            return decision  # PASS / SKIPPED / 미실행 → COMPLETE 유지 (회귀 0)

        err = (
            getattr(smoke_result, "error_excerpt", "")
            or getattr(smoke_result, "reason", "")
            or "(런타임 에러 상세 없음)"
        )[:1500]
        signal = getattr(smoke_result, "signal", "")
        exit_code = getattr(smoke_result, "exit_code", None)
        cur_iter = getattr(gap, "iteration", 0) if gap is not None else 0
        head = (
            f"🖥️ 데스크탑 런타임 스모크 FAIL (signal={signal}, exit={exit_code}) — 빌드된 .exe 가 "
            "실행 즉시/실행 중 크래시 또는 치명 에러. Gap Analyst 는 COMPLETE 였으나 사용자가 앱을 "
            "열면 동작하지 않음."
        )
        if cur_iter < max_iterations:
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=f"{head} 자가수정 루프 계속 (iter {cur_iter}/{max_iterations}).",
                next_action=(
                    "아래 런타임 에러를 *최우선 must-fix* 로 수정한 뒤 재빌드하세요 (원인 코드/쿼리/"
                    "초기화 경로를 직접 패치). 기존 충족 요구는 회귀 금지:\n" + err
                ),
                must_fix_count=max(decision.must_fix_count, 1),
            )
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.BUILD_FAILED,
            reason=f"{head} iteration 예산 소진(iter {cur_iter}/{max_iterations}) — 종료.",
            next_action=(
                "마지막 런타임 스모크 에러 (예산 소진 — --max-iterations 증액 시 자가수정 계속):\n" + err
            ),
            must_fix_count=max(decision.must_fix_count, 1),
        )
    except Exception:  # noqa: BLE001 — override 실패가 cycle 차단 X
        return decision


def _apply_deployability_failure_override(
    decision: JudgmentDecision,
    deployability_result: Any,
    *,
    gap: Optional[GapReport] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> JudgmentDecision:
    """v13 P25 — web 배포성 게이트 FAIL 시 COMPLETE 를 차단하고 배포성 must-fix 를 주입.

    ``_apply_smoke_failure_override`` 의 정확한 형제(desktop smoke → web 배포성). 빌드(dist/)는
    성공했지만 *문서화된 단일 프로덕션 명령으로 루트가 안 뜨는*(server 가 dist 미서빙 / 단일 명령
    부재 / dev 전용) 경우 — Gap Analyst 가 COMPLETE 라 해도 비개발자가 원클릭으로 못 돌리므로 거짓.

    적용 조건 (모두 충족 — smoke 와 동일 불변식):
        - ``decision.verdict == Verdict.COMPLETE`` (COMPLETE 만 차단; IMPROVE/BLOCKED 는 그대로).
        - ``deployability_result.verdict == "FAIL"`` (PASS/SKIPPED/미실행 → 원본 유지, 회귀 0).

    동작: 예산 남음(iter < max) → IMPROVE_NEEDED (배포성 에러를 next_action 에 실어 P12 conduit 로
    다음 iteration codegen must-fix 주입). 예산 소진 → BLOCKED(BUILD_FAILED). 예외는 원본 반환.
    """
    try:
        if decision is None or decision.verdict != Verdict.COMPLETE:
            return decision
        if (
            deployability_result is None
            or getattr(deployability_result, "verdict", None) != "FAIL"
        ):
            return decision  # PASS / SKIPPED / 미실행 → COMPLETE 유지 (회귀 0)

        err = (
            getattr(deployability_result, "error_excerpt", "")
            or getattr(deployability_result, "reason", "")
            or "(배포성 에러 상세 없음)"
        )[:1800]
        signal = getattr(deployability_result, "signal", "")
        command = getattr(deployability_result, "command", "") or "(단일 명령 부재)"
        cur_iter = getattr(gap, "iteration", 0) if gap is not None else 0
        head = (
            f"📦 배포성 게이트 FAIL (signal={signal}, command=`{command}`) — 빌드는 성공했으나 "
            "*문서화된 단일 프로덕션 명령* 으로 루트 앱이 뜨지 않습니다(server 가 dist 미서빙 / 단일 "
            "명령 부재 / dev 전용 의존). Gap Analyst 는 COMPLETE 였으나 비개발자가 원클릭으로 못 돌림."
        )
        if cur_iter < max_iterations:
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=f"{head} 자가수정 루프 계속 (iter {cur_iter}/{max_iterations}).",
                next_action=(
                    "아래 배포성 계약을 *최우선 must-fix* 로 충족한 뒤 재빌드하세요 (프로덕션 서버가 "
                    "빌드된 dist 를 정적 서빙 + 단일 명령 + dev-only 금지). 기존 충족 요구는 회귀 금지:\n"
                    + err
                ),
                must_fix_count=max(decision.must_fix_count, 1),
            )
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.BUILD_FAILED,
            reason=f"{head} iteration 예산 소진(iter {cur_iter}/{max_iterations}) — 종료.",
            next_action=(
                "마지막 배포성 에러 (예산 소진 — --max-iterations 증액 시 자가수정 계속):\n" + err
            ),
            must_fix_count=max(decision.must_fix_count, 1),
        )
    except Exception:  # noqa: BLE001 — override 실패가 cycle 차단 X
        return decision


def _maybe_salvage_web_build(
    decision: JudgmentDecision,
    chain_result: Any,
    *,
    salvage_fn=None,
) -> JudgmentDecision:
    """v13 Phase 6.E P13 — 예산 소진 BLOCKED(BUILD_FAILED) salvage 우회.

    web 빌드 실패가 *타입체크 전용*(tsc error, 번들/설치/런타임 에러 부재) 이면 vite-only
    (tsc 게이트 제외) 빌드를 1회 실행해 dist/ 를 산출하고 COMPLETE(타입 경고 첨부)로 수렴시킨다.
    번들/설치/런타임 등 실제 실패는 종전대로 BLOCKED 유지. desktop/비-web 은 무조건 불변.

    Args:
        decision: ``_apply_build_failure_override`` 산출 (BLOCKED(BUILD_FAILED) 일 때만 동작).
        chain_result: ``executor_result`` + ``saved_code_files`` + ``saved_dir`` 보유.
        salvage_fn: ``(code_files, saved_dir) -> bool`` — vite-only 빌드 성공 여부. None 이면
            production 경로 (``_run_web_build(vite_only=True)``). 테스트 주입용.

    Returns:
        salvage 성공 시 COMPLETE JudgmentDecision, 그 외 원본 ``decision``.
    """
    if decision.verdict != Verdict.BLOCKED or decision.blocked_cause != BlockedCause.BUILD_FAILED:
        return decision
    if chain_result is None:
        return decision
    executor_result = getattr(chain_result, "executor_result", None)
    if executor_result is None or not _is_web_build_result(executor_result):
        return decision  # desktop/비-web — 불변
    stderr = getattr(executor_result, "stderr", "") or ""
    if not _is_type_only_failure(stderr):
        return decision  # 번들/설치/런타임 실제 실패 — BLOCKED 유지

    code_files = list(getattr(chain_result, "saved_code_files", None) or [])
    saved_dir = getattr(chain_result, "saved_dir", None)
    ok = False
    try:
        if salvage_fn is not None:
            ok = bool(salvage_fn(code_files, saved_dir))
        elif saved_dir is not None:
            from src.workflows.build_workflow import _run_web_build  # noqa: PLC0415

            res = _run_web_build(code_files, Path(saved_dir), vite_only=True)
            ok = bool(getattr(res, "success", False)) and getattr(res, "exe_path", None) is not None
    except Exception:  # noqa: BLE001 — salvage 실패는 graceful (BLOCKED 유지)
        ok = False
    if not ok:
        return decision

    warn = _format_build_errors_with_hints(
        _parse_web_build_errors(stderr), "타입 경고 (런타임 영향 없음)"
    )
    return JudgmentDecision(
        verdict=Verdict.COMPLETE,
        blocked_cause=BlockedCause.NONE,
        reason=(
            "WEB_BUILD_SALVAGED — 타입체크 전용 에러만 잔존하나 vite-only(tsc 게이트 제외) "
            "빌드로 dist/ 산출 성공. 런타임 동작 정상, 타입 경고는 후속 정리."
        ),
        next_action="잔존 TS 타입 경고 (vite salvage 로 dist/ 산출됨, 후속 정리 권장):\n" + warn,
        must_fix_count=0,
    )


def _iteration_quality(
    chain_result: Any,
    gap: Optional[GapReport],
    decision: Optional[JudgmentDecision],
    platform_intent: str,
    *,
    deployability_result: Any = None,
) -> dict:
    """v13 Phase 6.E P15 — iteration 품질 메타 산출 (best-iteration 선택 점수).

    품질 신호: degenerate(단축/엔트리 부재, P14 _is_degenerate_codegen 재사용) /
    build_ok(executor 성공 + 산출물 경로 = web dist/ 또는 .exe) / domain_ok(도메인
    체크리스트 충족) / must_fix(낮을수록 좋음). degenerate 는 큰 음수로 disqualify →
    유효 iteration 이 하나라도 있으면 degenerate 를 최종으로 채택하지 않는다.
    """
    code_files = list(getattr(chain_result, "saved_code_files", None) or []) if chain_result else []
    degenerate = True
    if chain_result is not None:
        try:
            from src.workflows.analyze_and_implement import (  # noqa: PLC0415
                _is_degenerate_codegen,
            )

            degenerate = _is_degenerate_codegen(code_files, platform_intent or "unspecified")
        except Exception:  # noqa: BLE001 — 안전 폴백: 코드 파일 없으면 degenerate
            degenerate = not code_files
    exec_res = getattr(chain_result, "executor_result", None) if chain_result else None
    build_ok = bool(getattr(exec_res, "success", False)) and (
        getattr(exec_res, "exe_path", None) is not None
    )
    domain_ok = not bool(getattr(decision, "domain_unsatisfied", []) or [])
    must_fix = (getattr(gap, "unsatisfied_blockers", 0) or 0) + (
        getattr(gap, "unsatisfied_majors", 0) or 0
    )
    # v13 P25 — 배포성 게이트 FAIL 신호. best-iteration 이 빌드 성공·도메인 충족만으로 COMPLETE 를
    # 강제(_resolve_best_output:2130)해 배포 불가 산출을 surface 하지 않도록, FAIL 을 점수에 반영 +
    # COMPLETE 강제 게이트에 사용한다. (deployability_result None → False → 기존 동작 byte-불변, 회귀 0.)
    deployability_fail = getattr(deployability_result, "verdict", None) == "FAIL"
    iteration = getattr(gap, "iteration", 0) or 0
    score = 0.0
    if degenerate:
        score -= 1000.0  # disqualify — 유효 iteration 보다 항상 낮게
    if build_ok:
        score += 100.0
    if domain_ok:
        score += 50.0
    if deployability_fail:
        score -= 80.0  # 배포 가능한 iteration 을 선호(단, degenerate 보다는 높게 유지)
    score -= float(must_fix)
    score += iteration * 0.01  # 동점 시 후기(더 정제된) iteration 선호
    return {
        "iteration": iteration,
        "chain_result": chain_result,
        "gap": gap,
        "decision": decision,
        "execution_result": None,  # judge 노드가 채움
        "build_ok": build_ok,
        "domain_ok": domain_ok,
        "degenerate": degenerate,
        "deployability_fail": deployability_fail,
        "must_fix": must_fix,
        "score": score,
    }


def _select_best_iteration(records: list) -> Optional[dict]:
    """v13 Phase 6.E P15 — 최고 품질 iteration record 반환 (degenerate/회귀 종단 금지).

    점수 최대 record 선택. 유효 iteration 이 있으면 degenerate 보다 항상 우선되고,
    빌드 성공 + 도메인 충족 iteration 이 가장 높은 점수를 받는다. 빈 입력 → None
    (호출부가 현행 '마지막 iteration' 동작으로 폴백).
    """
    if not records:
        return None
    return max(records, key=lambda r: r.get("score", float("-inf")))


def _resolve_best_output(
    final_state: dict, decision: JudgmentDecision, gap: GapReport
) -> tuple:
    """v13 Phase 6.E P15 — 최종 산출로 *최고 iteration* 을 채택.

    반환 ``(sel_chain, sel_exec, sel_gap, sel_decision)``:
      - 유효 iteration record 가 없으면 현행(마지막) 그대로 폴백.
      - 최고 iteration 이 빌드 성공(dist/.exe) + 도메인 충족 → verdict=COMPLETE (후속
        회귀/degenerate note 첨부).
      - 그 외 → 최고 *유효* iteration 의 산출/결정을 surface (깨진 stub 말고), gap 유지.
    루프는 절대 degenerate/회귀 상태로 종단하지 않는다 (유효 iteration 이 하나라도 있으면).
    """
    sel_chain = final_state.get("chain_result")
    sel_exec = final_state.get("execution_result")
    best = _select_best_iteration(final_state.get("iteration_records", []))
    # 유효(non-degenerate) iteration 이 없으면 현행(마지막) 폴백 — 회귀 0.
    # (best 가 degenerate 면 모든 iter 가 degenerate → 마지막을 그대로 surface.)
    if best is None or best.get("chain_result") is None or best.get("degenerate"):
        return sel_chain, sel_exec, gap, decision

    sel_chain = best["chain_result"]
    sel_exec = best.get("execution_result")
    sel_gap = best.get("gap") or gap
    best_dec = best.get("decision") or decision
    last_iter = final_state.get("iteration", best["iteration"])
    # v13 P25 — 배포성 FAIL iteration 은 빌드/도메인 충족이어도 COMPLETE 로 강제하지 않는다
    # (override 가 IMPROVE/BLOCKED 로 강등한 decision 을 best_dec 로 그대로 surface). 비-web/None → False.
    if best["build_ok"] and best["domain_ok"] and not best.get("deployability_fail"):
        note = (
            f" (후속 iteration(들)이 회귀/degenerate — iter {best['iteration']} 산출을 최종 채택)"
            if best["iteration"] < last_iter
            else ""
        )
        sel_decision = JudgmentDecision(
            verdict=Verdict.COMPLETE,
            blocked_cause=BlockedCause.NONE,
            reason=(
                f"BEST_ITERATION_ADOPTED — iter {best['iteration']} 빌드 성공 + 도메인 충족 "
                f"→ COMPLETE{note}"
            ),
            next_action=getattr(best_dec, "next_action", "") or "최고 iteration 산출 채택.",
            must_fix_count=best["must_fix"],
            domain_unsatisfied=list(getattr(best_dec, "domain_unsatisfied", []) or []),
        )
    else:
        sel_decision = best_dec
    return sel_chain, sel_exec, sel_gap, sel_decision


def _extract_engineer_output_excerpt(
    chain_result: Any, *, max_chars: int = 30_000
) -> str:
    """v13 Phase 6.E (PR #231) — Engineer 산출 코드 발췌 (Rule 0 매칭 대상).

    saved_dir 의 ``code/*.py`` (Track A) + ``13_gui_code_output.md`` (GUI 분기) +
    ``03_engineer_output.md`` (Track B) 를 합쳐 첫 ``max_chars`` 까지 반환.
    실패 silent — 빈 string. Rule 0 가 빈 string 시 모든 항목 미충족 판정 →
    *3D 요구 시 IMPROVE_NEEDED 강제* (의도된 동작).
    """
    if chain_result is None:
        return ""
    saved_dir = getattr(chain_result, "saved_dir", None)
    if saved_dir is None:
        return ""
    try:
        saved_path = Path(saved_dir)
    except Exception:  # noqa: BLE001
        return ""
    if not saved_path.is_dir():
        return ""
    parts: list[str] = []
    total = 0
    code_dir = saved_path / "code"
    if code_dir.is_dir():
        for py in sorted(code_dir.glob("*.py")):
            if total >= max_chars:
                break
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
                parts.append(f"# {py.name}\n{text}")
                total += len(text)
            except Exception:  # noqa: BLE001
                continue
    for md_name in ("13_gui_code_output.md", "03_engineer_output.md"):
        if total >= max_chars:
            break
        md_path = saved_path / md_name
        if md_path.is_file():
            try:
                text = md_path.read_text(encoding="utf-8", errors="ignore")
                parts.append(f"## {md_name}\n{text}")
                total += len(text)
            except Exception:  # noqa: BLE001
                continue
    full = "\n\n".join(parts)
    return full[:max_chars]


def _extract_qa_review_excerpt(
    chain_result: Any, *, max_chars: int = 10_000
) -> str:
    """v13 Phase 6.E (PR #231) — QA review 발췌 (Rule 0 보조 매칭 대상)."""
    if chain_result is None:
        return ""
    saved_dir = getattr(chain_result, "saved_dir", None)
    if saved_dir is None:
        return ""
    try:
        saved_path = Path(saved_dir)
    except Exception:  # noqa: BLE001
        return ""
    if not saved_path.is_dir():
        return ""
    parts: list[str] = []
    for md_name in ("04_qa_review.md", "14_pytest_suite.md"):
        md_path = saved_path / md_name
        if md_path.is_file():
            try:
                text = md_path.read_text(encoding="utf-8", errors="ignore")
                parts.append(f"## {md_name}\n{text}")
            except Exception:  # noqa: BLE001
                continue
    full = "\n\n".join(parts)
    return full[:max_chars]


def _node_tech_scout(state: _LoopState) -> dict[str, Any]:
    """v13 Phase 6.3 (PR #230) — Engineer 산출 requirements.txt PyPI 검증.

    enable_tech_scout=True 시 _node_run_chain 직후 진입. chain_result.saved_dir/
    requirements.txt 를 파싱 + 각 패키지 PyPI 실존 검증. 가짜 발견 시:
        - consecutive_fake_iterations += 1
        - state["fake_packages"] = [가짜 list]
    가짜 없으면:
        - consecutive_fake_iterations = 0 (reset — IMPROVE 누적 해제)
        - state["fake_packages"] = []

    enable_tech_scout=False 면 즉시 return (회귀 0).
    """
    if not state.get("enable_tech_scout", False):
        return {}  # 기존 state 보존 (default OFF)

    chain_result = state.get("chain_result")
    if chain_result is None:
        return {"fake_packages": []}

    saved_dir = getattr(chain_result, "saved_dir", None)
    if saved_dir is None:
        return {"fake_packages": []}

    req_path = Path(saved_dir) / "requirements.txt"
    if not req_path.exists():
        # requirements.txt 미산출 — 가짜 없음 (검증 대상 부재)
        return {"fake_packages": [], "consecutive_fake_iterations": 0}

    try:
        from src.agents.research import (
            extract_fake_packages,
            validate_requirements_txt,
        )

        results = validate_requirements_txt(req_path)
        fake_list = extract_fake_packages(results)
    except Exception:  # noqa: BLE001 — Tech Scout 실패가 메인 cycle 차단 X
        return {"fake_packages": [], "consecutive_fake_iterations": state.get(
            "consecutive_fake_iterations", 0
        )}

    if fake_list:
        prev_count = state.get("consecutive_fake_iterations", 0)
        return {
            "fake_packages": fake_list,
            "consecutive_fake_iterations": prev_count + 1,
        }
    # 가짜 없음 — 카운터 reset
    return {"fake_packages": [], "consecutive_fake_iterations": 0}


def _node_judge_convergence(state: _LoopState) -> dict[str, Any]:
    """결정표 호출 (LLM 무관). budget 도 함께 차감.

    PR #162 (2026-05-18): build 실패 시 verdict override 추가 — ``_apply_build_failure_override``
    참조. Gap Analyst 가 COMPLETE 라 해도 PyInstaller .exe 산출 실패면 BLOCKED(BUILD_FAILED).

    PR #230 (Phase 6.3): fake_packages + consecutive_fake_iterations 전달.
        - Rule -1 발동 시 1차 IMPROVE / 2차 BLOCKED(FAKE_PACKAGE).
        - 둘 다 default 0 / None 이면 회귀 0.
    """
    gap: GapReport = state["gap_report"]
    budget = state.get("budget_tokens_remaining", NO_BUDGET_GATE)

    # iteration 1건 비용 차감 (예산 추적이 활성화된 경우만)
    if budget != NO_BUDGET_GATE:
        budget = max(0, budget - DEFAULT_TOKENS_PER_ITERATION) if budget > 0 else 0

    # Phase 6.E (PR #231) — Rule 0 wire: 매 iter chain_result 의 코드/QA 발췌
    chain_result_for_excerpt = state.get("chain_result")
    engineer_excerpt = _extract_engineer_output_excerpt(chain_result_for_excerpt)
    qa_excerpt = _extract_qa_review_excerpt(chain_result_for_excerpt)

    decision = judge_convergence(
        gap,
        max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
        budget_tokens_remaining=budget,
        # Phase 6.3 (PR #230) — Tech Scout fake_packages 전달
        fake_packages=state.get("fake_packages"),
        consecutive_fake_iterations=state.get("consecutive_fake_iterations", 0),
        # Phase 6.E (PR #231) — Rule 0 wire: 도메인 체크리스트 + 산출 발췌
        domain_checklist=state.get("domain_checklist"),
        engineer_output_excerpt=engineer_excerpt,
        qa_result_excerpt=qa_excerpt,
        # Phase 6.E P1 (PR #235) — 플랫폼 드리프트 탐지 (web 의도 시 데스크탑 마커 검사)
        platform_intent=state.get("platform_intent", "unspecified"),
    )
    # PR #162 — build 실패 시 BLOCKED override.
    # v13 Phase 6.E P12 — web 빌드 실패는 예산 남으면 IMPROVE(루프백)·cap 이면 BLOCKED.
    decision = _apply_build_failure_override(
        decision,
        state.get("chain_result"),
        gap=gap,
        max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
    )
    # v13 Phase 6.E P13 — cap 도달 web 타입체크 전용 실패면 vite-only salvage → dist/ 시 COMPLETE.
    decision = _maybe_salvage_web_build(decision, state.get("chain_result"))
    # v13 P23 — desktop 런타임 스모크 FAIL 시 COMPLETE 차단 + must-fix 주입.
    # salvage *이후* 적용 — salvage 가 COMPLETE 로 되살린 빌드라도 실 런타임 크래시면 재차단.
    decision = _apply_smoke_failure_override(
        decision,
        state.get("smoke_result"),
        gap=gap,
        max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
    )
    # v13 P25 — web 배포성 게이트 FAIL 시 COMPLETE 차단 + 배포성 must-fix 주입.
    # smoke *이후*(마지막) 적용 — 실 실행 가능 산출이 확정된 뒤 배포 가능성(단일 명령·dist 서빙) 검사.
    decision = _apply_deployability_failure_override(
        decision,
        state.get("deployability_result"),
        gap=gap,
        max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
    )
    # v13 Phase 6.E P15 — iteration 품질 기록 (best-iteration 선택용). 깨진 마지막
    # iteration 으로 종단하지 않고 빌드 성공+도메인 충족한 최고 iteration 을 채택하기 위함.
    record = _iteration_quality(
        state.get("chain_result"), gap, decision, state.get("platform_intent", "unspecified"),
        deployability_result=state.get("deployability_result"),
    )
    record["execution_result"] = state.get("execution_result")
    records = list(state.get("iteration_records", []))
    records.append(record)
    return {
        "decision": decision,
        "budget_tokens_remaining": budget,
        "iteration_records": records,
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

    P0 회귀 수정 (PR #234) — 그래프 레벨 **하드 iteration 가드 (이중 방어선)**:
        judge 가 (결함·회귀로) IMPROVE_NEEDED 를 줘도 ``iteration >= max_iterations``
        이면 loop back 을 막고 종료 노드(escalate)로 라우팅한다. convergence_judge 의
        post-가드가 1차 방어, 본 라우터 가드가 2차 방어 — judge 가 우회/회귀되어도
        무한 IMPROVE → GraphRecursionError 크래시(2026-05-29 사고)를 차단한다.
        COMPLETE 는 cap 무관 정상 종료(finalize) 허용 — 가드보다 먼저 검사.

    Returns:
        "finalize" | "prepare_feedback" | "escalate"
    """
    decision: JudgmentDecision = state["decision"]
    if decision.verdict == Verdict.COMPLETE:
        return "finalize"

    # ★ P0 하드 iteration 가드 (defense-in-depth): cap 도달 시 verdict 무관 종료.
    gap = state.get("gap_report")
    current_iter = getattr(gap, "iteration", 0) if gap is not None else 0
    max_iter = state.get("max_iterations", DEFAULT_MAX_ITERATIONS)
    if current_iter >= max_iter:
        return "escalate"  # cap 도달 — IMPROVE 라도 loop back 금지

    if decision.verdict == Verdict.IMPROVE_NEEDED:
        return "prepare_feedback"
    return "escalate"  # BLOCKED


# ---------------------------------------------------------------------------
# Telemetry node wrapper (PR #187, Sprint 4)
# ---------------------------------------------------------------------------
def _telemetry_wrap(node_name: str, fn: Callable[[Any], dict[str, Any]]) -> Callable[[Any], dict[str, Any]]:
    """LangGraph 노드 함수를 wrap 해 AgentStatusEvent (working/done/error) 를 emit.

    Telemetry 가 비활성 (``NEXUS_TELEMETRY_PATH`` 미 set) 일 때는 원본 fn 을 그대로
    호출 — 0 overhead. 활성 시:
        - 진입 → ``agent_working``
        - 정상 종료 → ``agent_done``
        - 예외 발생 → ``agent_error`` 후 re-raise (원본 동작 보존)

    노드 함수 자체는 *수정하지 않는다* — wrap 만 build_iterative_loop_graph 에서 적용.
    """
    def inner(state: dict[str, Any]) -> dict[str, Any]:
        # 지연 import — circular dependency 회피 + monitoring 미설치 환경 보호
        try:
            from src.monitoring import get_telemetry_emitter
            emitter = get_telemetry_emitter()
        except Exception:  # noqa: BLE001
            return fn(state)

        if not emitter.enabled:
            return fn(state)

        iteration = state.get("iteration", 0) if isinstance(state, dict) else 0
        try:
            emitter.agent_working(node_name, detail=f"iter={iteration}")
        except Exception:  # noqa: BLE001
            pass

        try:
            result = fn(state)
        except Exception as exc:
            try:
                emitter.agent_error(node_name, error_msg=repr(exc))
            except Exception:  # noqa: BLE001
                pass
            raise

        try:
            emitter.agent_done(node_name, detail=f"iter={iteration}")
        except Exception:  # noqa: BLE001
            pass
        return result

    inner.__name__ = f"_telemetry__{node_name}"
    return inner


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
    # PR #187 Sprint 4 — 각 노드를 _telemetry_wrap 으로 감싸 AgentStatusEvent emit.
    # Telemetry 비활성 (default) 시 원본 fn 그대로 호출 — 0 overhead.
    g.add_node("expand_requirements", _telemetry_wrap("expand_requirements", _node_expand_requirements))
    g.add_node("recall_past_knowledge", _telemetry_wrap("recall_past_knowledge", _node_recall_past_knowledge))  # PR #140
    g.add_node("kickoff_meeting", _telemetry_wrap("kickoff_meeting", _node_kickoff_meeting))                    # PR #138 full
    g.add_node("run_chain", _telemetry_wrap("run_chain", _node_run_chain))
    # v13 Phase 6.3 (PR #230) — Tech Scout PyPI 가짜 패키지 가드 노드
    g.add_node("tech_scout", _telemetry_wrap("tech_scout", _node_tech_scout))
    g.add_node("run_sandbox", _telemetry_wrap("run_sandbox", _node_run_sandbox))
    # v13 Phase 1 2단계 — 본부 9 Runtime Verification opt-in 노드 (default OFF).
    g.add_node("runtime_verify", _telemetry_wrap("runtime_verify", _node_runtime_verify))
    g.add_node("analyze_gap", _telemetry_wrap("analyze_gap", _node_analyze_gap))
    g.add_node("judge_convergence", _telemetry_wrap("judge_convergence", _node_judge_convergence))
    g.add_node("prepare_feedback", _telemetry_wrap("prepare_feedback", _node_prepare_feedback))
    g.add_node("retrospective", _telemetry_wrap("retrospective", _node_retrospective))                          # PR #149
    g.add_node("curate_knowledge", _telemetry_wrap("curate_knowledge", _node_curate_knowledge))                 # PR #140
    g.add_node("retrospective_blocked", _telemetry_wrap("retrospective_blocked", _node_retrospective))          # PR #149 alias
    g.add_node("curate_knowledge_blocked", _telemetry_wrap("curate_knowledge_blocked", _node_curate_knowledge)) # PR #140 alias
    g.add_node("finalize", _telemetry_wrap("finalize", _node_finalize))
    g.add_node("escalate", _telemetry_wrap("escalate", _node_escalate))

    g.set_entry_point("expand_requirements")
    g.add_edge("expand_requirements", "recall_past_knowledge")
    g.add_edge("recall_past_knowledge", "kickoff_meeting")
    g.add_edge("kickoff_meeting", "run_chain")
    # v13 Phase 6.3 (PR #230) — run_chain 직후 tech_scout (requirements.txt PyPI 검증).
    # enable_tech_scout=False (default) 면 _node_tech_scout 가 즉시 return {} — 회귀 0.
    g.add_edge("run_chain", "tech_scout")
    g.add_edge("tech_scout", "run_sandbox")
    # v13 Phase 1 2단계 — run_sandbox → runtime_verify → analyze_gap.
    # enable_rv=False (default) 면 runtime_verify 가 즉시 pass-through.
    g.add_edge("run_sandbox", "runtime_verify")
    g.add_edge("runtime_verify", "analyze_gap")
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
    enable_rv: bool = False,  # v13 Phase 1 2단계 — 본부 9 RV opt-in (default OFF, 1477 PASS 보호)
    enable_strategist: bool = False,  # v13 Phase 2 — 본부 1 Strategist opt-in (default OFF)
    enable_boardroom: bool = False,  # v13 Phase 3 — 본부 10 Boardroom opt-in (default OFF)
    enable_tikitaka: bool = False,  # v13 Phase 5.4 — 양방향 라운드 토론 opt-in (default OFF, --enable-boardroom 함께 필요)
    enable_tech_scout: bool = False,  # v13 Phase 6.3 — Tech Scout PyPI 가짜 패키지 가드 opt-in (default OFF)
    target_platform: str = "windows",
    enable_release_branch: bool = False,
    previous_version: str = "",
    repo_url: str = "",
    signing_available: bool = False,
    privacy_level: str = "public",
    enable_engineer_reviewer_delegation: bool = False,
    # PR #157 — production wire: scripts/run.py 의 --auto-iterate 진입 시 필요
    enable_executor: bool = False,
    executor_timeout_sec: int = 300,
    enable_publish: bool = False,
    publish_as_draft: bool = True,
    publish_timeout_sec: int = 120,
    verbose: bool = False,
    # PR #158 — Track B 지원 (chain 분기)
    track: str = "A",
    release_tag: str = "",
    # PR #183 — CLI --forced-domain 전달 (Track B 도메인 자동 분류 우회)
    forced_domain: Any = None,
    # v13 P20 — codegen 직전 사람 개입 체크포인트 (opt-in, 기본 OFF — 회귀 0)
    intervene: bool = False,
    intervene_timeout: int = 90,
    # v13 P23 — desktop .exe 런타임 스모크 게이트 (기본 ON — desktop 빌드만; web/none/헤드리스 자동 SKIP)
    enable_smoke: bool = True,
    smoke_timeout: int = 8,
    # v13 P25 — web 산출물 배포성 게이트 (기본 ON — web 빌드만; desktop/none 자동 SKIP)
    enable_packageability: bool = True,
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

    # PR #187 Sprint 4 — Tauri 데스크탑 앱 telemetry. 비활성 (default) 시 0 overhead.
    from src.monitoring import (
        IterationProgressEvent,
        ResultEvent,
        get_telemetry_emitter,
    )
    telemetry = get_telemetry_emitter()
    run_started_at = time.monotonic()
    if telemetry.enabled:
        telemetry.begin_run(max_iterations=max_iterations)
        try:
            telemetry.emit(IterationProgressEvent(
                phase="run_start",
                iteration=0,
                max_iterations=max_iterations,
                detail=user_request[:160],
            ))
        except Exception:  # noqa: BLE001
            pass

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
            "enable_rv": enable_rv,
            "rv_failure_detected": False,
            # v13 Phase 2 (PR #219) — Strategist opt-in 초기 state
            "enable_strategist": enable_strategist,
            "consecutive_rv_failures": 0,
            "strategist_proposal_path": None,
            # v13 Phase 3 (PR #221) — Boardroom 회의실 인프라 초기 state
            "enable_boardroom": enable_boardroom,
            "boardroom_session_path": None,
            # v13 Phase 5.4 (PR #224 + #225) — 양방향 티키타카 라운드 초기 state
            "enable_tikitaka": enable_tikitaka,
            # v13 Phase 6.3 (PR #230) — Tech Scout 가짜 패키지 가드 초기 state
            "enable_tech_scout": enable_tech_scout,
            "fake_packages": None,
            "consecutive_fake_iterations": 0,
            # v13 Phase 6.E (PR #231) — Rule 0 wire. expand_requirements 가 채움.
            "domain_checklist": None,
            # v13 Phase 6.E P1 (PR #235) — 플랫폼 의도. expand_requirements 가 채움.
            "platform_intent": "unspecified",
            "target_platform": target_platform,
            "enable_release_branch": enable_release_branch,
            "previous_version": previous_version,
            "repo_url": repo_url,
            "signing_available": signing_available,
            "privacy_level": privacy_level,
            "enable_engineer_reviewer_delegation": enable_engineer_reviewer_delegation,
            # PR #157 — production wire propagate
            "enable_executor": enable_executor,
            "executor_timeout_sec": executor_timeout_sec,
            "enable_publish": enable_publish,
            "publish_as_draft": publish_as_draft,
            "publish_timeout_sec": publish_timeout_sec,
            "verbose": verbose,
            # PR #158 — Track B 지원
            "track": track,
            "release_tag": release_tag,
            # PR #183 — CLI --forced-domain 전달 (Track B 도메인 자동 분류 우회)
            "forced_domain": forced_domain,
            # v13 P20 — 사람 개입 체크포인트 (기본 OFF)
            "intervene": intervene,
            "intervene_timeout": intervene_timeout,
            # v13 P23 — desktop 런타임 스모크 게이트 (기본 ON)
            "enable_smoke": enable_smoke,
            "smoke_timeout": smoke_timeout,
            # v13 P25 — web 배포성 게이트 (기본 ON)
            "enable_packageability": enable_packageability,
        }
        # recursion_limit: iteration 한 번이 7 노드 (Phase 3 에서 sandbox 추가) →
        # max_iter*7 + 안전 여유 10.
        recursion_limit = max(50, max_iterations * 7 + 10)
        # v13 P16 (수정2) — 그래프 실행 예외(GraphRecursionError 등)를 구조화 LoopOutcome 으로.
        # 이전엔 except 부재로 예외가 LoopOutcome 없이 루프를 탈출(2026-05-29 크래시). 이제
        # *항상* 구조화 결과 반환 — verdict=BLOCKED(INTERNAL_ERROR) + crash_reason 에 예외 보존.
        # finally 블록(텔레메트리 run_end/정리)은 early-return 에도 실행됨.
        try:
            final_state = compiled.invoke(
                initial_state, config={"recursion_limit": recursion_limit}
            )
        except Exception as exc:  # noqa: BLE001 — 크래시를 구조화 verdict 로 변환 (COMPLETE 오보 금지)
            crash_repr = f"{type(exc).__name__}: {exc}"
            crash_decision = JudgmentDecision(
                verdict=Verdict.BLOCKED,
                blocked_cause=BlockedCause.INTERNAL_ERROR,
                reason=f"그래프 실행 예외로 중단: {crash_repr}",
                next_action=(
                    "내부 오류 — LLM/provider 오류, GraphRecursionError, OSError 등. "
                    "로그/crash_reason 확인 후 재시도. (COMPLETE 아님 — 산출물 미보장.)"
                ),
                must_fix_count=0,
            )
            crash_outcome = LoopOutcome(
                user_request=user_request,
                verdict=Verdict.BLOCKED,
                blocked_cause=BlockedCause.INTERNAL_ERROR,
                iterations_run=0,
                spec_markdown="",
                final_chain_result=None,
                final_execution_result=None,
                final_gap_report_raw="",
                final_gap_report=GapReport(),
                final_decision=crash_decision,
                budget_remaining_at_end=NO_BUDGET_GATE,
                crash_reason=crash_repr,
            )
            if telemetry.enabled:
                try:
                    telemetry.emit(ResultEvent(
                        verdict="BLOCKED",
                        blocked_cause="INTERNAL_ERROR",
                        iterations_run=0,
                        max_iterations=max_iterations,
                        exe_path="",
                        duration_sec=round(time.monotonic() - run_started_at, 3),
                        saved_dir="",
                        summary_line=f"verdict=BLOCKED(INTERNAL_ERROR) — {crash_repr}",
                    ))
                except Exception:  # noqa: BLE001
                    pass
            return crash_outcome  # finally(텔레메트리 정리) 실행 후 반환

        decision: JudgmentDecision = final_state["decision"]
        gap: GapReport = final_state.get("gap_report") or GapReport()

        # v13 Phase 6.E P15 — 최고 iteration 채택 (깨진/회귀 마지막 iteration 종단 금지).
        #   루프가 어떤 사유로 끝나든(특히 ITERATION_CAP), 마지막이 아니라 빌드 성공+도메인
        #   충족한 *최고* iteration 산출을 최종 결과로 surface (degenerate 는 유효 iter 있으면 제외).
        sel_chain, sel_exec, gap, decision = _resolve_best_output(final_state, decision, gap)

        curated_entry_path_str = final_state.get("curated_entry_path", "")
        curated_index_path_str = final_state.get("curated_index_path", "")
        retro_md_path_str = final_state.get("retrospective_md_path", "")
        outcome = LoopOutcome(
            user_request=user_request,
            verdict=decision.verdict,
            blocked_cause=decision.blocked_cause,
            iterations_run=final_state.get("iteration", 0),
            spec_markdown=final_state.get("spec_markdown", ""),
            final_chain_result=sel_chain,
            final_execution_result=sel_exec,
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

        # PR #187 Sprint 4 — ResultEvent emit (결과 패널). exe path 추출은 best-effort:
        # chain_result.executor_result.exe_path 가 표준 위치이나 환경에 따라 다를 수 있어 안전 추출.
        if telemetry.enabled:
            exe_path = ""
            saved_dir = ""
            chain = sel_chain  # P15 — 채택된 최고 iteration 의 산출 기준 (마지막 아님)
            if chain is not None:
                exec_res = getattr(chain, "executor_result", None)
                if exec_res is not None:
                    exe_path = str(getattr(exec_res, "exe_path", "") or "")
                saved = getattr(chain, "saved_dir", None)
                if saved:
                    saved_dir = str(saved)
            try:
                summary_line = format_iterative_summary(outcome, max_iterations)
            except Exception:  # noqa: BLE001
                summary_line = ""
            try:
                telemetry.emit(ResultEvent(
                    verdict=getattr(decision.verdict, "value", str(decision.verdict)),
                    blocked_cause=getattr(decision.blocked_cause, "value", str(decision.blocked_cause)),
                    iterations_run=outcome.iterations_run,
                    max_iterations=max_iterations,
                    exe_path=exe_path,
                    duration_sec=round(time.monotonic() - run_started_at, 3),
                    saved_dir=saved_dir,
                    summary_line=summary_line,
                ))
            except Exception:  # noqa: BLE001
                pass

        return outcome

    finally:
        monitor.end_trace()
        monitor.flush()
        # PR #187 Sprint 4 — run_end progress + run_id 정리. 예외 흐름에도 안전.
        if telemetry.enabled:
            try:
                telemetry.emit(IterationProgressEvent(
                    phase="run_end",
                    iteration=0,
                    max_iterations=max_iterations,
                    detail=f"duration_sec={round(time.monotonic() - run_started_at, 3)}",
                ))
            except Exception:  # noqa: BLE001
                pass
            try:
                telemetry.end_run()
            except Exception:  # noqa: BLE001
                pass
