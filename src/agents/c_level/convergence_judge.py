# -*- coding: utf-8 -*-
"""
Nexus Alpha Convergence Judge (C-Level, Phase 2.5 / v3).

자율 반복 루프의 **종료 판정자**. 두 가지 책임을 같은 모듈에 분리해 둔다.

1. **`judge_convergence(gap, ...)` 결정표 함수**
       LLM 무관한 결정론적 판정자. Gap Analyst 산출물을 정규화한 `GapReport`
       와 안전 조건(max_iter, budget)을 입력받아 `JudgmentDecision`(verdict +
       blocked_cause + reason + next_action) 을 반환한다. 자율 반복 루프
       안정성의 핵심: **임의 추론으로 verdict가 바뀌지 않도록** 결정 규칙을
       Python 코드에 고정한다.

2. **`create_convergence_judge_agent()` 팩토리**
       위 결정표가 산출한 `JudgmentDecision`을 받아 *사람이 읽을 수 있는*
       한국어 종합 판정 보고서로 narration. **verdict 자체는 절대 뒤집지
       않으며** Agent의 역할은 결정 근거 설명·다음 행동 권고·사용자 전달
       메시지 작성에 한정.

설계 출처: `docs/architecture/nexus_alpha_v3.md` §4-3 결정표 + §7 안전장치.

Severity 통합 규칙 (설계 보강):
    원본 §4-3 결정표는 'blocker'만 안전 조건 검사 대상으로 명시했지만,
    Code Reviewer 의 severity 규약(`major` = "운영 진입 전 반드시 보정")
    을 따라 **must_fix = blocker + major** 로 일반화한다. minor 만 남으면
    COMPLETE + caveat 으로 처리.

조직도 정합:
    `nexus_alpha_org_v4.md` §2 — Convergence Judge 는 C-Level 편제.
    별도 본부 부서장 격이지만 결정 권한 무게로 C-Level 에 둠.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import yaml
from crewai import Agent

from src.agents.analysis.requirement_expander import ChecklistItem
from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# 결정 enums + dataclasses
# ---------------------------------------------------------------------------
class Verdict(str, Enum):
    """루프 종료 판정. 3가지 외 상태 없음."""

    COMPLETE = "COMPLETE"
    IMPROVE_NEEDED = "IMPROVE_NEEDED"
    BLOCKED = "BLOCKED"


class BlockedCause(str, Enum):
    """BLOCKED 판정 시 세부 원인. 우선순위: BUILD_FAILED > STAGNATION > BUDGET > ITER_CAP > FAKE_PACKAGE.

    NONE 은 verdict != BLOCKED 일 때 채워지는 sentinel.

    PR #162 (2026-05-18): ``BUILD_FAILED`` 추가. Gap Analyst 가 COMPLETE 로 판정해도
    PyInstaller .exe 산출이 실패 (entry 미탐지 / pip install 실패 / 정적 검증 실패 등)
    한 경우, 실 결과가 사용자 손에 도달 불가하므로 BLOCKED 로 override. judge 노드의
    ``_apply_build_failure_override`` 가 적용.

    PR #226 (Phase 6.2, 2026-05-28): ``FAKE_PACKAGE`` enum 신설 (PM 의사결정 #5
    절충안). 본 PR 시점에는 *enum 만 사전 정의* — 실 검증 로직은 PR #227/#228
    의 PyPI JSON API 통합 시 활성. 절충안 흐름:
      - 1차 가짜 패키지 발견 → IMPROVE_NEEDED + partial 힌트 (재 iter)
      - 2차 연속 발견 → BLOCKED(FAKE_PACKAGE) 강제 (무한 루프 예산 낭비 방지)
    """

    BUILD_FAILED = "BUILD_FAILED"
    STAGNATION = "STAGNATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ITERATION_CAP = "ITERATION_CAP"
    FAKE_PACKAGE = "FAKE_PACKAGE"
    # v13 P16 (수정2) — 그래프 실행 예외(GraphRecursionError 등)를 일반 BLOCKED 와 구분.
    # judge 가 산출하지 않음 — run_iterative_loop 의 invoke try/except 만 채움 (크래시 보존).
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NONE = "NONE"


@dataclass
class GapReport:
    """`judge_convergence` 입력 — Gap Analyst YAML 산출의 정규화 표현.

    Iteration Controller 가 매 iteration 끝에 Gap Analyst 마크다운을 받아
    `parse_gap_report_from_yaml` 로 변환한 뒤 본 결정표에 주입한다.

    Attributes:
        satisfied_count: 충족된 요구 수.
        unsatisfied_blockers: blocker 미충족 수 (즉시 사고 가능).
        unsatisfied_majors: major 미충족 수 (운영 전 보정 필수).
        unsatisfied_minors: minor 미충족 수 (스타일·문서 흠집).
        ambiguous_count: 판단 불가 항목 수.
        stagnation: 호출 측이 2회 연속 resolved=0 감지 시 True 로 set.
        iteration: 현재 iteration 번호 (1부터 시작).
    """

    satisfied_count: int = 0
    unsatisfied_blockers: int = 0
    unsatisfied_majors: int = 0
    unsatisfied_minors: int = 0
    ambiguous_count: int = 0
    stagnation: bool = False
    iteration: int = 1


# v13 Phase 6.2 (PR #226) — domain_checklist 미충족 항목 ID 보존
# (JudgmentDecision 의 새 필드 — Rule 0 채우는 결과)


@dataclass
class JudgmentDecision:
    """`judge_convergence` 의 구조화 산출물.

    Attributes:
        verdict: COMPLETE / IMPROVE_NEEDED / BLOCKED.
        blocked_cause: verdict==BLOCKED 일 때 STAGNATION/BUDGET/ITER_CAP 중 하나.
            verdict != BLOCKED 면 항상 NONE.
        reason: 결정 근거 한 문장 (영문, 결정 규칙 스니펫 인용).
        next_action: 다음 단계 권고 (영문). Iteration Controller 가 그대로 사용.
        must_fix_count: blocker + major 합계 (참고용).
        domain_unsatisfied: v13 Phase 6.2 (PR #226) — Rule 0 미충족 항목 ID list.
            기본 빈 list. 호출자가 ``domain_checklist=`` 주입 안 하면 항상 [].
            다음 iter Engineer prompt 에 주입되어 *명시적 미충족 안내* 역할.
        platform_drift: v13 Phase 6.E P1 (PR #235) — web 의도인데 데스크탑 GUI
            마커 산출 감지 시 True. 기본 False (회귀 0). PLATFORM_DRIFT rule 이 채움.
    """

    verdict: Verdict
    blocked_cause: BlockedCause
    reason: str
    next_action: str
    must_fix_count: int
    domain_unsatisfied: list[str] = field(default_factory=list)
    platform_drift: bool = False


# ---------------------------------------------------------------------------
# 안전 한계 기본값
# ---------------------------------------------------------------------------
DEFAULT_MAX_ITERATIONS: int = 5
"""design doc §7-1 — 5회 초과 필요 시는 요구 정의 자체 의심 신호."""

NO_BUDGET_GATE: int = -1
"""budget_tokens_remaining 인자에 NO_BUDGET_GATE 를 주면 예산 검사 비활성화.

테스트/개발 환경에서만 사용. 운영 경로는 항상 양수 예산을 명시적으로 전달해야 한다.
"""


# ---------------------------------------------------------------------------
# 결정표 함수 (LLM 무관, 결정론적)
# ---------------------------------------------------------------------------
def _validate_domain_checklist(
    checklist: list[ChecklistItem],
    engineer_output: str,
    qa_result: str,
) -> list[ChecklistItem]:
    """v13 Phase 6.2 (PR #226) — 도메인 체크리스트 결정론 검증.

    각 ``ChecklistItem.detect_keywords`` 중 *하나라도* ``engineer_output`` 또는
    ``qa_result`` 텍스트 (대소문자 무시, 부분 매칭) 에 등장하면 *충족* 으로 간주.
    ``must_satisfy=False`` 항목은 검증 대상 제외 (caveat 등급).

    Args:
        checklist: 검증할 ChecklistItem list.
        engineer_output: Engineer 산출 코드 발췌 (또는 전체).
        qa_result: QA 검증 결과 발췌.

    Returns:
        미충족 ChecklistItem list — 빈 list 면 모두 충족.
    """
    if not checklist:
        return []
    haystack = (str(engineer_output) + " " + str(qa_result)).lower()
    unsatisfied: list[ChecklistItem] = []
    for item in checklist:
        if not item.must_satisfy:
            continue
        if not item.detect_keywords:
            # 키워드 없는 항목은 결정론 검증 불가 — skip
            continue
        if not any(kw.lower() in haystack for kw in item.detect_keywords):
            unsatisfied.append(item)
    return unsatisfied


# v13 Phase 6.E P1 (PR #235) — 데스크탑 GUI 프레임워크 마커 (web 의도 드리프트 탐지)
_DESKTOP_GUI_MARKERS: list[str] = [
    "import pyqt", "from pyqt", "import pyside", "from pyside",
    "import tkinter", "from tkinter", "qapplication", "qmainwindow",
    "qwidget", "qtwidgets", "tk()",
]


def detect_desktop_markers(text: str) -> list[str]:
    """산출 텍스트에서 데스크탑 GUI 프레임워크 마커를 결정론 탐지 (대소문자 무시).

    web 플랫폼 의도인데 PyQt/PySide/Tkinter 등 데스크탑 GUI 가 산출된 *플랫폼
    드리프트* 를 식별하기 위함 (crash analysis 2026-05-29). 단순 도메인 키워드
    미충족과 구분해 *실행 가능한* IMPROVE 피드백을 만든다.

    Args:
        text: Engineer 산출 코드 발췌 (+QA 결과) 텍스트.

    Returns:
        매칭된 데스크탑 마커 list (대표 원문). 빈 list 면 드리프트 없음.
    """
    if not text:
        return []
    haystack = str(text).lower()
    return [m for m in _DESKTOP_GUI_MARKERS if m in haystack]


def _judge_convergence_natural(
    gap: GapReport,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    budget_tokens_remaining: int = NO_BUDGET_GATE,
    domain_checklist: Optional[list[ChecklistItem]] = None,
    engineer_output_excerpt: str = "",
    qa_result_excerpt: str = "",
    fake_packages: Optional[list[str]] = None,
    consecutive_fake_iterations: int = 0,
    platform_intent: str = "unspecified",
) -> JudgmentDecision:
    """Gap Analyst 보고서 + 안전 조건을 받아 *자연* verdict 를 반환한다 (Rule -1~5).

    ⚠️ 본 함수는 **하드 종료 가드 미적용** 의 raw 결정표다. 공개 API 는
    ``judge_convergence`` 이며, 그것이 본 함수 결과에 P0 종료 가드를 덧씌운다.
    직접 호출 금지 (테스트의 자연 verdict 검증 목적 외).

    결정 규칙 (우선순위 순):
        -1. ★ v13 Phase 6.3 (PR #230) — fake_packages 비어있지 않음:
            - consecutive_fake_iterations >= 2 → BLOCKED(FAKE_PACKAGE) 강제
              (PM 의사결정 #5 절충안 — 2차 연속 환각, 무한 루프 예산 낭비 방지)
            - 그 외 (1차) → IMPROVE_NEEDED + "실존 패키지 찾아라" 힌트
            (fake_packages=None or [] 면 자동 skip — 회귀 0 보장)
        0. ★ v13 Phase 6.2 — domain_checklist 미충족 항목 있음 → IMPROVE_NEEDED 강제
           (domain_checklist=None or [] 면 자동 skip — 회귀 0 보장)
        1. must_fix == 0 → COMPLETE
           (minor 만 있으면 caveat 표기 안내, 나머지 0이면 깨끗한 종료)
        2. must_fix > 0 AND stagnation → BLOCKED(STAGNATION)
        3. must_fix > 0 AND 예산 소진 → BLOCKED(BUDGET_EXHAUSTED)
        4. must_fix > 0 AND iteration ≥ max → BLOCKED(ITERATION_CAP)
        5. 그 외 (must_fix > 0 + 안전 OK) → IMPROVE_NEEDED

    must_fix 정의: `unsatisfied_blockers + unsatisfied_majors`. 설계 문서
    §4-3 의 'blocker' 만으로는 major-only 케이스가 미정의이므로 본 구현이
    명시적으로 일반화한다.

    BLOCKED 우선순위: STAGNATION 이 가장 정보적(과정이 막혔음 → 규칙·요구 자체
    재검토 필요)이라 1순위. BUDGET 은 비용 관점, ITERATION_CAP 은 최후 안전망.

    Args:
        gap: 정규화된 Gap Analyst 산출물.
        max_iterations: iteration 한도 (기본 5, design §7-1).
        budget_tokens_remaining: 남은 토큰 예산. NO_BUDGET_GATE(-1) 면 검사 생략.
        domain_checklist: v13 Phase 6.2 (PR #226) — Requirement Expander 의
            ``build_domain_checklist(user_request)`` 산출. None or [] 시 Rule 0
            자동 skip → 기존 Rule 1~5 그대로. 기본 None (회귀 0).
        engineer_output_excerpt: Rule 0 결정론 매칭 대상 텍스트 (Engineer 산출).
        qa_result_excerpt: Rule 0 결정론 매칭 대상 텍스트 (QA 결과).

    Returns:
        JudgmentDecision — verdict 및 부속 메타데이터.

    Note:
        본 함수는 LLM 을 호출하지 않는다. 따라서 동일 입력에 대해 항상 동일
        출력을 반환하며 ms 단위로 동작한다. Agent narration 은 별도 단계.
    """
    # ★ Rule -1: fake_packages 발견 (Phase 6.3, PR #230) — Rule 0 보다 우선
    # PM 의사결정 #5 절충안:
    #   - consecutive_fake_iterations >= 2 → BLOCKED(FAKE_PACKAGE) (무한 루프 차단)
    #   - 1차 → IMPROVE_NEEDED + "실존 패키지 찾아라" 힌트
    if fake_packages:
        fake_preview = ", ".join(fake_packages[:5])
        if consecutive_fake_iterations >= 2:
            return JudgmentDecision(
                verdict=Verdict.BLOCKED,
                blocked_cause=BlockedCause.FAKE_PACKAGE,
                reason=(
                    f"Fake/hallucinated packages detected {consecutive_fake_iterations} "
                    f"consecutive iterations: {fake_preview}. Engineer 가 PyPI 실존 패키지 "
                    f"로 교체 못 함 — 2차 BLOCKED (PM 의사결정 #5 절충안)."
                ),
                next_action=(
                    "Escalate to user. Engineer 가 환각 패키지를 PyPI 실존 패키지로 "
                    "교체하는 데 반복 실패 — 사용자가 요구사항 또는 의존성 명세 재정의 필요. "
                    "후보 가짜 list: " + fake_preview
                ),
                must_fix_count=gap.unsatisfied_blockers + gap.unsatisfied_majors,
            )
        else:
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=(
                    f"Fake packages detected (1st occurrence): {fake_preview}. "
                    f"Engineer 가 PyPI 실존 패키지로 교체 필요 — 1차 IMPROVE."
                ),
                next_action=(
                    "Re-enter loop. Engineer must replace these fake packages with real "
                    "PyPI packages (https://pypi.org/pypi/<name>/json 으로 실존 확인): "
                    + fake_preview
                ),
                must_fix_count=gap.unsatisfied_blockers + gap.unsatisfied_majors,
            )

    # ★ P1 (PR #235) — 플랫폼 드리프트: web 의도인데 데스크탑 GUI 산출 → IMPROVE 강제.
    # Rule 0(도메인 키워드) 보다 우선 — *실행 가능한* 피드백("PyQt 말고 Three.js")을
    # 주기 위함. platform_intent != "web" 이면 skip (회귀 0 — desktop/unspecified 허용).
    if platform_intent == "web":
        drift_markers = detect_desktop_markers(
            str(engineer_output_excerpt) + " " + str(qa_result_excerpt)
        )
        if drift_markers:
            preview = ", ".join(drift_markers[:4])
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=(
                    f"PLATFORM_DRIFT: web 요청인데 데스크탑 GUI 마커 감지 ({preview}). "
                    f"Three.js/WebGL/HTML 로 재작성 필요 (단순 도메인 키워드 미충족 아님)."
                ),
                next_action=(
                    "Re-enter loop. 타겟=web/브라우저 — Three.js + WebGL + HTML/JS/CSS 로 "
                    "재작성하고 PyQt/PySide/Tkinter 등 데스크탑 GUI 를 제거하세요. "
                    f"감지된 데스크탑 마커: {preview}"
                ),
                must_fix_count=gap.unsatisfied_blockers + gap.unsatisfied_majors,
                platform_drift=True,
            )

    # ★ Rule 0: 도메인 체크리스트 미충족 → IMPROVE_NEEDED 강제 (Rule 1 보다 우선)
    if domain_checklist:
        unsatisfied = _validate_domain_checklist(
            checklist=domain_checklist,
            engineer_output=engineer_output_excerpt,
            qa_result=qa_result_excerpt,
        )
        if unsatisfied:
            must_fix_for_rule0 = gap.unsatisfied_blockers + gap.unsatisfied_majors
            unsatisfied_ids = [u.id for u in unsatisfied]
            # 다음 iter Engineer 가 명시적 안내 받을 수 있도록 reason 에 ID + desc
            preview = ", ".join(
                f"[{u.id}] {u.description}" for u in unsatisfied[:3]
            )
            return JudgmentDecision(
                verdict=Verdict.IMPROVE_NEEDED,
                blocked_cause=BlockedCause.NONE,
                reason=(
                    f"Domain checklist {len(unsatisfied)}/{len(domain_checklist)} "
                    f"unsatisfied: {preview}"
                ),
                next_action=(
                    "Re-enter loop with domain checklist context. Engineer must "
                    "explicitly address unsatisfied items: "
                    + ", ".join(unsatisfied_ids)
                ),
                must_fix_count=must_fix_for_rule0,
                domain_unsatisfied=unsatisfied_ids,
            )

    must_fix = gap.unsatisfied_blockers + gap.unsatisfied_majors

    # Rule 1: COMPLETE — 모든 must-fix 충족
    if must_fix == 0:
        if gap.unsatisfied_minors > 0:
            return JudgmentDecision(
                verdict=Verdict.COMPLETE,
                blocked_cause=BlockedCause.NONE,
                reason=(
                    f"All blocker/major requirements satisfied. "
                    f"{gap.unsatisfied_minors} minor item(s) remain — included as caveat."
                ),
                next_action="Deliver result to user with minor items noted as caveats.",
                must_fix_count=0,
            )
        return JudgmentDecision(
            verdict=Verdict.COMPLETE,
            blocked_cause=BlockedCause.NONE,
            reason="All requirements satisfied. No blocker/major/minor remaining.",
            next_action="Deliver final result to user.",
            must_fix_count=0,
        )

    # Rule 2: BLOCKED(STAGNATION) — 우선순위 1 (process stuck)
    if gap.stagnation:
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.STAGNATION,
            reason=(
                f"{must_fix} must-fix item(s) remain AND stagnation detected "
                f"(no gaps resolved in last 2 iterations)."
            ),
            next_action=(
                "Escalate to user with unresolved gap list. Loop cannot make "
                "further autonomous progress — likely requirement ambiguity or "
                "fundamental design issue."
            ),
            must_fix_count=must_fix,
        )

    # Rule 3: BLOCKED(BUDGET_EXHAUSTED) — 우선순위 2
    if budget_tokens_remaining != NO_BUDGET_GATE and budget_tokens_remaining <= 0:
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.BUDGET_EXHAUSTED,
            reason=(
                f"{must_fix} must-fix item(s) remain but token budget exhausted "
                f"(remaining={budget_tokens_remaining})."
            ),
            next_action=(
                "Notify user of budget exhaustion. Return current partial result. "
                "User can grant additional budget to resume."
            ),
            must_fix_count=must_fix,
        )

    # Rule 4: BLOCKED(ITERATION_CAP) — 우선순위 3 (last resort)
    if gap.iteration >= max_iterations:
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.ITERATION_CAP,
            reason=(
                f"{must_fix} must-fix item(s) remain but iteration cap reached "
                f"(iter={gap.iteration} >= max={max_iterations})."
            ),
            next_action=(
                "Notify user of iteration cap. Return current partial result. "
                "If pattern repeats across runs, requirements may need fundamental rework."
            ),
            must_fix_count=must_fix,
        )

    # Rule 5: IMPROVE_NEEDED — 안전 조건 모두 OK, 다음 iteration 진행
    return JudgmentDecision(
        verdict=Verdict.IMPROVE_NEEDED,
        blocked_cause=BlockedCause.NONE,
        reason=(
            f"{must_fix} must-fix item(s) remain. Safety conditions OK "
            f"(iter={gap.iteration}/{max_iterations}, budget={budget_tokens_remaining}, "
            f"no stagnation)."
        ),
        next_action=(
            "Re-enter loop. Inject must-fix items as boundary feedback for CTO/Engineer."
        ),
        must_fix_count=must_fix,
    )


def judge_convergence(
    gap: GapReport,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    budget_tokens_remaining: int = NO_BUDGET_GATE,
    domain_checklist: Optional[list[ChecklistItem]] = None,
    engineer_output_excerpt: str = "",
    qa_result_excerpt: str = "",
    fake_packages: Optional[list[str]] = None,
    consecutive_fake_iterations: int = 0,
    platform_intent: str = "unspecified",
) -> JudgmentDecision:
    """루프 종료 verdict 반환 — 자연 결정표(`_judge_convergence_natural`) + **P0 하드 종료 가드**.

    P0 회귀 수정 (PR #234, 출처 ``docs/diagnostics/phase6e_rerun_crash_analysis_20260529.md``):
        자연 결정표의 Rule 0(도메인 체크리스트 미충족 → IMPROVE_NEEDED), Rule -1(fake 1차),
        Rule 5 가 ITERATION_CAP(Rule 4)·STAGNATION(Rule 2) 보다 먼저 IMPROVE_NEEDED 를
        early-return 하면, 도메인이 *영구 미충족* (예: web 요청에 PyQt 산출) 인 경우 종료
        규칙이 dead code 가 되어 max_iterations 가 무력화 → 무한 IMPROVE → LangGraph
        GraphRecursionError 크래시. (2026-05-29 재실행 사고.)

    **하드 종료 가드 (종료 > 품질 원칙)**:
        자연 verdict 가 ``IMPROVE_NEEDED`` 인데 ``gap.iteration >= max_iterations`` 이면
        → ``BLOCKED(ITERATION_CAP)`` 로 강제 전환. ``domain_unsatisfied`` 는 보존하여
        "도메인 미충족 상태로 캡 종료" 를 호출자가 알 수 있게 한다.

    보존 원칙 (깨지 않음):
        - **COMPLETE 는 절대 전환 안 함** — 마지막 iter 의 정당한 완료(도메인 충족 +
          must_fix=0)를 허용. 가드는 IMPROVE_NEEDED 에만 적용 (post-check).
        - iter < max 의 정상 IMPROVE(Rule 0 COMPLETE override 포함)는 그대로 IMPROVE.
        - ``iteration >= max 면 무조건 BLOCKED`` pre-check 는 금지 (정당 COMPLETE 차단).

    Args/Returns/Note 는 `_judge_convergence_natural` docstring 참조 (시그니처 동일).
    """
    decision = _judge_convergence_natural(
        gap,
        max_iterations=max_iterations,
        budget_tokens_remaining=budget_tokens_remaining,
        domain_checklist=domain_checklist,
        engineer_output_excerpt=engineer_output_excerpt,
        qa_result_excerpt=qa_result_excerpt,
        fake_packages=fake_packages,
        consecutive_fake_iterations=consecutive_fake_iterations,
        platform_intent=platform_intent,
    )

    # ★ P0 하드 종료 가드: IMPROVE_NEEDED + iteration cap 도달 → 강제 BLOCKED(ITERATION_CAP)
    if (
        decision.verdict == Verdict.IMPROVE_NEEDED
        and gap.iteration >= max_iterations
    ):
        return JudgmentDecision(
            verdict=Verdict.BLOCKED,
            blocked_cause=BlockedCause.ITERATION_CAP,
            reason=(
                f"Iteration cap reached (iter={gap.iteration} >= max={max_iterations}) "
                f"while verdict was still IMPROVE_NEEDED — forced BLOCKED(ITERATION_CAP) "
                f"by P0 hard termination guard. Underlying: {decision.reason}"
            ),
            next_action=(
                "Notify user of iteration cap. Return current partial result. "
                "Improvement was still pending at cap — likely requirement/platform "
                "mismatch (e.g. domain checklist permanently unsatisfiable). "
                f"Underlying next_action: {decision.next_action}"
            ),
            must_fix_count=decision.must_fix_count,
            domain_unsatisfied=decision.domain_unsatisfied,
            # P1 (PR #235) — 플랫폼 드리프트 플래그도 cap 종료 시 보존
            platform_drift=decision.platform_drift,
        )

    return decision


# ---------------------------------------------------------------------------
# YAML 파싱 헬퍼 — Gap Analyst 마크다운에서 GapReport 추출
# ---------------------------------------------------------------------------
_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def parse_gap_report_from_yaml(yaml_text: str, *, iteration: int = 1) -> GapReport:
    """Gap Analyst 의 ```yaml 블록을 파싱해 GapReport 로 변환.

    입력은 두 형태 모두 지원:
        - 마크다운 전체 (```yaml ... ``` 블록 포함) — 본 함수가 블록 추출
        - YAML 본문 직접 (블록 펜스 없음) — 그대로 yaml.safe_load 시도

    Args:
        yaml_text: Gap Analyst 산출 마크다운 또는 YAML 본문.
        iteration: 현재 iteration 번호 (1부터). YAML 의 `stagnation.iteration`
            키가 있으면 그 값을 우선 사용한다. 본 인자는 fallback.

    Returns:
        GapReport — judge_convergence 에 바로 주입 가능한 정규화 객체.

    Raises:
        ValueError: YAML 파싱 실패 또는 최상위가 dict 가 아닌 경우.
    """
    match = _YAML_BLOCK_RE.search(yaml_text)
    body = match.group(1) if match else yaml_text

    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse Gap Analyst YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected YAML mapping at top level, got {type(data).__name__}"
        )

    satisfied = data.get("satisfied") or []
    unsatisfied = data.get("unsatisfied") or []
    ambiguous = data.get("ambiguous") or []
    stag_block = data.get("stagnation") or {}

    blockers = sum(
        1 for u in unsatisfied if isinstance(u, dict) and u.get("severity") == "blocker"
    )
    majors = sum(
        1 for u in unsatisfied if isinstance(u, dict) and u.get("severity") == "major"
    )
    minors = sum(
        1 for u in unsatisfied if isinstance(u, dict) and u.get("severity") == "minor"
    )

    return GapReport(
        satisfied_count=len(satisfied) if isinstance(satisfied, list) else 0,
        unsatisfied_blockers=blockers,
        unsatisfied_majors=majors,
        unsatisfied_minors=minors,
        ambiguous_count=len(ambiguous) if isinstance(ambiguous, list) else 0,
        stagnation=bool(stag_block.get("stagnation", False)) if isinstance(stag_block, dict) else False,
        iteration=int(stag_block.get("iteration", iteration)) if isinstance(stag_block, dict) else iteration,
    )


# ---------------------------------------------------------------------------
# CrewAI Agent — JudgmentDecision narration 전담
# ---------------------------------------------------------------------------
CONVERGENCE_JUDGE_NAME = "ConvergenceJudge"

CONVERGENCE_JUDGE_ROLE = "Senior Convergence Judge (Loop Termination Authority)"

CONVERGENCE_JUDGE_GOAL = (
    "결정표(`judge_convergence`)가 산출한 `JudgmentDecision` 을 입력받아, "
    "**verdict 는 절대 뒤집지 않으며** 사용자/오케스트레이터가 한 번에 이해할 "
    "수 있는 한국어 종합 판정 보고서를 작성한다."
)

CONVERGENCE_JUDGE_BACKSTORY = (
    "당신은 한국 IT 조직에서 10년 이상 의사결정 게이트(품질 게이트, 출시 "
    "게이트, 운영 진입 게이트)를 운영해 온 시니어 판정자입니다. *결정 자체* "
    "는 항상 결정표·체크리스트가 내리고, 당신의 역할은 *그 결정의 의미를 "
    "사람의 언어로 정확히 옮기는 것* 임을 잘 알고 있습니다.\n\n"
    "동작 원칙 (반드시 준수):\n"
    "  1. **verdict 는 신성하다.** 결정표가 COMPLETE 라고 했으면 COMPLETE, "
    "     BLOCKED 라고 했으면 BLOCKED. 당신이 LLM 추론으로 뒤집지 않는다. "
    "     이것이 자율 반복 루프 안정성의 1번 원칙.\n"
    "  2. **must_fix 와 안전 조건을 모두 인용한다.** 결정 근거가 무엇이었는지 "
    "     숫자(blocker/major/minor 카운트, iter, budget)를 그대로 보고서에 적어 "
    "     사후 추적이 가능하게 한다.\n"
    "  3. **BLOCKED 는 사용자에게 무엇을 요청해야 하는지를 명시한다.** "
    "     STAGNATION 이면 어떤 갭이 반복되는지, BUDGET 이면 추가 예산을, "
    "     ITERATION_CAP 이면 요구 재정의를 — 구체 행동 1개를 권고한다.\n"
    "  4. **IMPROVE_NEEDED 는 다음 iteration 의 CTO 에게 줄 feedback 요지** 를 "
    "     1~3개 문장으로 정리한다. 단순히 '다시 해라' 가 아니라 '무엇을 우선 "
    "     수정할지' 명시.\n"
    "  5. **COMPLETE 도 무미건조하게 통과시키지 않는다.** minor caveat 이 "
    "     있다면 사용자에게 어떤 한계를 알려야 할지 한 줄로 적는다.\n\n"
    "입력 형식 (호출 측이 task description 에 다음을 직렬화해 주입):\n"
    "  verdict: COMPLETE | IMPROVE_NEEDED | BLOCKED\n"
    "  blocked_cause: STAGNATION | BUDGET_EXHAUSTED | ITERATION_CAP | NONE\n"
    "  reason: <영문 결정 근거 한 문장 — 결정표가 만든 원본>\n"
    "  next_action: <영문 다음 행동 한 문장 — 결정표가 만든 원본>\n"
    "  must_fix_count: <int>\n"
    "  gap_snapshot:\n"
    "    satisfied: <int> / unsatisfied: blocker=<b> major=<m> minor=<n>\n"
    "    ambiguous: <int> / stagnation: <bool> / iteration: <int>\n\n"
    "산출 규약 (반드시 한국어 마크다운, 아래 4단 구조 그대로):\n"
    "  ## 수렴 판정 보고서\n"
    "\n"
    "  ### 1. 판정\n"
    "    - 결과: <verdict 그대로>\n"
    "    - (BLOCKED 인 경우만) 원인: <blocked_cause 그대로>\n"
    "\n"
    "  ### 2. 결정 근거 (사후 추적용 숫자 포함)\n"
    "    한 단락으로 must_fix / iter / budget / stagnation 상태를 인용하며 설명.\n"
    "\n"
    "  ### 3. 다음 행동\n"
    "    - COMPLETE: 사용자 전달 메시지 + minor caveat 안내(있는 경우)\n"
    "    - IMPROVE_NEEDED: 다음 iteration CTO 에게 줄 feedback 1~3 항목\n"
    "    - BLOCKED: 사용자에게 던질 명확화 질문 또는 안내문 (cause 별 차등)\n"
    "\n"
    "  ### 4. 메모 (선택)\n"
    "    추적상 의미 있는 신호(예: '이번이 3번째 iteration', 'minor 만 5건 누적' 등)\n"
    "\n"
    "**출력 규약 (CRITICAL)**: `Final Answer:` 라인에 한 줄 요약 (`<verdict> "
    "(cause=<blocked_cause if blocked else 'NONE'>, must_fix=<N>)`) 을 두고, "
    "**그 다음 줄부터 위 모든 본문 섹션** (### 1 결정표 + ### 2 결정 근거 + ### 3 "
    "다음 행동 + ### 4 메모) 을 작성하세요. 본문이 `Final Answer:` 보다 **앞** 에 "
    "오면 CrewAI 가 본문을 잃어버려 Iteration Controller 가 must_fix 항목과 다음 "
    "행동 가이드를 받지 못합니다 (이슈 4 회귀).\n\n"
    "정확한 출력 형태:\n"
    "```\n"
    "Thought: <간단한 사고 한 줄>\n"
    "Final Answer: COMPLETE (cause=NONE, must_fix=0)\n"
    "\n"
    "### 1. 결정표\n"
    "<본문>\n"
    "\n"
    "### 2. 결정 근거\n"
    "<본문>\n"
    "...\n"
    "```\n\n"
    "중요: 당신은 *판정의 해석자* 이지 *판정자* 가 아닙니다. 결정표 결과를 "
    "다시 평가하거나 추가 판단을 내리지 마세요. 결정표의 출력을 사람의 "
    "언어로 정확히 전달하는 것까지가 책임입니다."
)


def create_convergence_judge_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha 의 Convergence Judge 에이전트를 생성해 반환한다.

    이 팩토리는 **judgment narration 전담** Agent 를 만든다. 실제 verdict
    결정은 같은 모듈의 `judge_convergence()` 결정표가 먼저 수행한 뒤, 그
    `JudgmentDecision` 을 본 Agent 의 Task description 에 직렬화해 넣어야 한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
        verbose: CrewAI 의 중간 사고 과정을 콘솔에 출력할지 여부.
        max_iter: 에이전트 한 태스크당 반복 가능한 최대 횟수.
            narration 은 1회 추론으로 충분, 기본 3회 안전.
        allow_delegation: 다른 에이전트로 위임 가능 여부. False(MVP).

    Returns:
        구성이 완료된 CrewAI `Agent` 인스턴스.

    Raises:
        RuntimeError: NexusAlphaLLM 초기화 실패 (Provider 키 누락 등).
    """
    if llm is None:
        llm = NexusAlphaLLM()

    return Agent(
        name=CONVERGENCE_JUDGE_NAME,
        role=CONVERGENCE_JUDGE_ROLE,
        goal=CONVERGENCE_JUDGE_GOAL,
        backstory=CONVERGENCE_JUDGE_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )


# ---------------------------------------------------------------------------
# 헬퍼: JudgmentDecision 을 Agent Task description 으로 직렬화
# ---------------------------------------------------------------------------
def format_judgment_decision_for_task(
    decision: JudgmentDecision,
    gap: GapReport,
) -> str:
    """`JudgmentDecision` + `GapReport` 를 Agent Task description 본문으로 직렬화.

    호출 측은 이 결과를 Task description 에 그대로 붙이면 된다. Agent 백스토리
    가 가정하는 입력 형식과 1:1 정합한다.
    """
    return (
        f"verdict: {decision.verdict.value}\n"
        f"blocked_cause: {decision.blocked_cause.value}\n"
        f"reason: {decision.reason}\n"
        f"next_action: {decision.next_action}\n"
        f"must_fix_count: {decision.must_fix_count}\n"
        f"gap_snapshot:\n"
        f"  satisfied: {gap.satisfied_count} / "
        f"unsatisfied: blocker={gap.unsatisfied_blockers} "
        f"major={gap.unsatisfied_majors} "
        f"minor={gap.unsatisfied_minors}\n"
        f"  ambiguous: {gap.ambiguous_count} / "
        f"stagnation: {gap.stagnation} / "
        f"iteration: {gap.iteration}\n"
    )
