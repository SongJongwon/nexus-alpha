# -*- coding: utf-8 -*-
"""P0 종료 보장 회귀 test (PR #234) — Rule 0 종료조건 override 버그 수정.

출처: ``docs/diagnostics/phase6e_rerun_crash_analysis_20260529.md``

배경 (회귀 사고):
    2026-05-29 재실행이 GraphRecursionError 로 크래시. 근본원인 =
    ``convergence_judge.py`` 에서 Rule 0(도메인 체크리스트 미충족 → IMPROVE_NEEDED)가
    Rule 2(STAGNATION)·Rule 4(ITERATION_CAP) 보다 먼저 early-return → 종료 규칙이
    dead code → max_iterations 무력화 → 무한 IMPROVE → recursion_limit 초과 크래시.
    기존 단위 test 는 이 버그 동작(iter==max 에서 IMPROVE)을 '정답'으로 박제하고
    있어 pytest 가 크래시를 못 잡았다 (통합 갭).

본 파일은 그 통합 갭을 메운다:
    T1. 도메인 영구 미충족 — judge 를 iter 1..max 반복 호출 → max 도달 시 BLOCKED(ITERATION_CAP).
    T2. must_fix==0 + 도메인 미충족 + iter==max → BLOCKED(ITERATION_CAP) + domain_unsatisfied 보존.
    T3. 도메인 충족 + must_fix==0 + iter==max → COMPLETE (가드가 전환 안 함).
    T4. iter<max + 도메인 미충족 → 여전히 IMPROVE_NEEDED (Rule 0 정상 회귀 0).
    T5. 라우터 단위 — iter>=max + verdict=IMPROVE → 종료 라우팅(escalate).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import ChecklistItem
from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    judge_convergence,
)
from src.workflows.iterative_loop import _route_after_judge


MAX_ITER = 5


def _make_3d_checklist() -> list[ChecklistItem]:
    """테스트용 3D 체크리스트 — detect_keywords 는 Three.js/JS 전용 (PyQt 산출엔 0매칭)."""
    return [
        ChecklistItem(
            id="3d-orbit",
            domain="3d_visualization",
            description="카메라 Orbit 회전",
            must_satisfy=True,
            detect_keywords=["OrbitControls", "WebGLRenderer"],
        ),
        ChecklistItem(
            id="3d-real",
            domain="3d_visualization",
            description="진짜 3D",
            must_satisfy=True,
            detect_keywords=["PerspectiveCamera", "Vector3"],
        ),
    ]


# 매 iter 동일하게 산출되는 '플랫폼 드리프트' 코드 — Three.js 키워드 0매칭.
_PYQT_DRIFT_OUTPUT = "PyQt6 QMainWindow dashboard QLabel QPushButton 일반 대시보드"


# =============================================================================
# T1. 도메인 영구 미충족 루프 — max 도달 시 BLOCKED(ITERATION_CAP), NOT 무한 IMPROVE
# =============================================================================
class TestT1DomainPermanentlyUnsatisfied:
    """⭐ 'Rule 0 가 캡 선점 못 함' 직접 검증 — 크래시 재현 시나리오의 결정론 단면."""

    def test_loop_terminates_at_cap_not_infinite_improve(self) -> None:
        checklist = _make_3d_checklist()
        verdicts: list[Verdict] = []
        for it in range(1, MAX_ITER + 1):
            gap = GapReport(unsatisfied_blockers=1, iteration=it)
            decision = judge_convergence(
                gap,
                max_iterations=MAX_ITER,
                domain_checklist=checklist,
                engineer_output_excerpt=_PYQT_DRIFT_OUTPUT,  # 영구 미충족
            )
            verdicts.append(decision.verdict)

        # iter 1..max-1 은 IMPROVE (Rule 0 정상), iter==max 는 BLOCKED (하드 가드)
        assert verdicts[:-1] == [Verdict.IMPROVE_NEEDED] * (MAX_ITER - 1)
        assert verdicts[-1] == Verdict.BLOCKED

    def test_cap_verdict_is_iteration_cap(self) -> None:
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=MAX_ITER),
            max_iterations=MAX_ITER,
            domain_checklist=checklist,
            engineer_output_excerpt=_PYQT_DRIFT_OUTPUT,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP

    def test_beyond_cap_still_blocked(self) -> None:
        """iter 가 max 를 넘어선 비정상 상태에서도 BLOCKED (>= 비교)."""
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=MAX_ITER + 2),
            max_iterations=MAX_ITER,
            domain_checklist=checklist,
            engineer_output_excerpt=_PYQT_DRIFT_OUTPUT,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP


# =============================================================================
# T2. must_fix==0 + 도메인 미충족 + iter==max → BLOCKED + domain_unsatisfied 보존
# =============================================================================
class TestT2MustFixZeroDomainUnsatisfiedAtCap:
    def test_blocked_iteration_cap_with_domain_preserved(self) -> None:
        # must_fix==0 (Rule 1 COMPLETE 자연 후보) 이지만 도메인 미충족 → Rule 0 IMPROVE
        # → iter==max 하드 가드 → BLOCKED(ITERATION_CAP)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            GapReport(satisfied_count=3, unsatisfied_blockers=0, iteration=MAX_ITER),
            max_iterations=MAX_ITER,
            domain_checklist=checklist,
            engineer_output_excerpt=_PYQT_DRIFT_OUTPUT,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP
        # 캡 종료라도 어떤 도메인 항목이 미충족인지 보존
        assert set(decision.domain_unsatisfied) == {"3d-orbit", "3d-real"}


# =============================================================================
# T3. 도메인 충족 + must_fix==0 + iter==max → COMPLETE (가드가 전환 안 함)
# =============================================================================
class TestT3CompleteNotConvertedAtCap:
    def test_complete_survives_at_cap(self) -> None:
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            GapReport(satisfied_count=5, unsatisfied_blockers=0, iteration=MAX_ITER),
            max_iterations=MAX_ITER,
            domain_checklist=checklist,
            engineer_output_excerpt=(
                "OrbitControls + WebGLRenderer + PerspectiveCamera + Vector3 setup"
            ),
        )
        # 도메인 충족 + must_fix==0 → Rule 1 COMPLETE. iter==max 여도 전환 금지.
        assert decision.verdict == Verdict.COMPLETE
        assert decision.blocked_cause == BlockedCause.NONE

    def test_complete_no_domain_checklist_at_cap(self) -> None:
        """domain_checklist 없이 must_fix==0 + iter==max → COMPLETE (회귀 0)."""
        decision = judge_convergence(
            GapReport(satisfied_count=5, unsatisfied_blockers=0, iteration=MAX_ITER),
            max_iterations=MAX_ITER,
        )
        assert decision.verdict == Verdict.COMPLETE


# =============================================================================
# T4. iter<max + 도메인 미충족 → 여전히 IMPROVE_NEEDED (Rule 0 정상 회귀 0)
# =============================================================================
class TestT4Rule0RegressionZeroBelowCap:
    def test_improve_below_cap(self) -> None:
        checklist = _make_3d_checklist()
        for it in range(1, MAX_ITER):  # 1..max-1
            decision = judge_convergence(
                GapReport(unsatisfied_blockers=1, iteration=it),
                max_iterations=MAX_ITER,
                domain_checklist=checklist,
                engineer_output_excerpt=_PYQT_DRIFT_OUTPUT,
            )
            assert decision.verdict == Verdict.IMPROVE_NEEDED, f"iter={it}"
            assert decision.blocked_cause == BlockedCause.NONE


# =============================================================================
# T5. 라우터 단위 — 그래프 레벨 하드 iteration 가드 (이중 방어선)
# =============================================================================
class TestT5RouterHardGuard:
    """judge 가 (회귀로) IMPROVE 를 줘도 라우터가 cap 에서 종료로 라우팅."""

    @staticmethod
    def _improve_decision() -> JudgmentDecision:
        return JudgmentDecision(
            verdict=Verdict.IMPROVE_NEEDED,
            blocked_cause=BlockedCause.NONE,
            reason="r",
            next_action="n",
            must_fix_count=1,
        )

    def test_improve_at_cap_routes_to_escalate(self) -> None:
        """verdict=IMPROVE 인데 iter>=max → escalate (loop back 금지)."""
        state = {
            "decision": self._improve_decision(),
            "gap_report": GapReport(unsatisfied_blockers=1, iteration=MAX_ITER),
            "max_iterations": MAX_ITER,
        }
        assert _route_after_judge(state) == "escalate"

    def test_improve_beyond_cap_routes_to_escalate(self) -> None:
        state = {
            "decision": self._improve_decision(),
            "gap_report": GapReport(unsatisfied_blockers=1, iteration=MAX_ITER + 3),
            "max_iterations": MAX_ITER,
        }
        assert _route_after_judge(state) == "escalate"

    def test_improve_below_cap_routes_to_prepare_feedback(self) -> None:
        """iter<max + IMPROVE → prepare_feedback (정상 loop back, 회귀 0)."""
        state = {
            "decision": self._improve_decision(),
            "gap_report": GapReport(unsatisfied_blockers=1, iteration=2),
            "max_iterations": MAX_ITER,
        }
        assert _route_after_judge(state) == "prepare_feedback"

    def test_complete_at_cap_routes_to_finalize(self) -> None:
        """COMPLETE 는 cap 무관 finalize (가드보다 먼저 검사)."""
        state = {
            "decision": JudgmentDecision(
                verdict=Verdict.COMPLETE,
                blocked_cause=BlockedCause.NONE,
                reason="r",
                next_action="n",
                must_fix_count=0,
            ),
            "gap_report": GapReport(satisfied_count=5, iteration=MAX_ITER),
            "max_iterations": MAX_ITER,
        }
        assert _route_after_judge(state) == "finalize"

    def test_blocked_routes_to_escalate(self) -> None:
        state = {
            "decision": JudgmentDecision(
                verdict=Verdict.BLOCKED,
                blocked_cause=BlockedCause.ITERATION_CAP,
                reason="r",
                next_action="n",
                must_fix_count=1,
            ),
            "gap_report": GapReport(unsatisfied_blockers=1, iteration=MAX_ITER),
            "max_iterations": MAX_ITER,
        }
        assert _route_after_judge(state) == "escalate"
