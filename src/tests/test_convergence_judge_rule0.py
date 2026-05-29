# -*- coding: utf-8 -*-
"""Convergence Judge Rule 0 단위 test (v13 Phase 6.2, PR #226).

검증 범위:
    1. _validate_domain_checklist — 결정론 키워드 매칭
    2. Rule 0 회귀 0 보장 — domain_checklist=None/[] 시 기존 Rule 1~5 그대로
    3. Rule 0 IMPROVE_NEEDED 강제 — must_fix=0 (Rule 1 COMPLETE 케이스) 도 override
    4. Rule 0 must_satisfy=False 항목 무시
    5. JudgmentDecision.domain_unsatisfied 채워짐
    6. BlockedCause.FAKE_PACKAGE enum 정의 (PR #228 대비)
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import ChecklistItem
from src.agents.c_level.convergence_judge import (
    NO_BUDGET_GATE,
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    _validate_domain_checklist,
    judge_convergence,
)


def _make_3d_checklist() -> list[ChecklistItem]:
    """테스트용 3D 체크리스트 — 2 항목."""
    return [
        ChecklistItem(
            id="3d-orbit",
            domain="3d_visualization",
            description="카메라 Orbit 회전",
            must_satisfy=True,
            detect_keywords=["OrbitControls", "rotate"],
        ),
        ChecklistItem(
            id="3d-real",
            domain="3d_visualization",
            description="진짜 3D",
            must_satisfy=True,
            detect_keywords=["PerspectiveCamera", "Vector3"],
        ),
    ]


# =============================================================================
# 1. _validate_domain_checklist 단위
# =============================================================================
class TestValidateDomainChecklist:
    def test_empty_checklist_returns_empty(self) -> None:
        assert _validate_domain_checklist([], "any", "any") == []

    def test_all_keywords_present_returns_empty(self) -> None:
        checklist = _make_3d_checklist()
        engineer_output = "OrbitControls + PerspectiveCamera + Vector3 setup"
        unsatisfied = _validate_domain_checklist(checklist, engineer_output, "")
        assert unsatisfied == []

    def test_missing_keywords_returns_unsatisfied(self) -> None:
        """결정론 매칭: 키워드 없는 항목만 반환."""
        checklist = _make_3d_checklist()
        # OrbitControls 만 있고 PerspectiveCamera/Vector3 없음
        engineer_output = "OrbitControls + rotate enabled"
        unsatisfied = _validate_domain_checklist(checklist, engineer_output, "")
        assert len(unsatisfied) == 1
        assert unsatisfied[0].id == "3d-real"

    def test_case_insensitive_matching(self) -> None:
        checklist = _make_3d_checklist()
        engineer_output = "orbitcontrols + PERSPECTIVECAMERA + vector3"
        assert _validate_domain_checklist(checklist, engineer_output, "") == []

    def test_qa_result_also_counted(self) -> None:
        """engineer_output 빈 채로 qa_result 에 키워드 → 충족."""
        checklist = _make_3d_checklist()
        qa_result = "OrbitControls + rotate + PerspectiveCamera + Vector3 verified"
        assert _validate_domain_checklist(checklist, "", qa_result) == []

    def test_must_satisfy_false_skipped(self) -> None:
        item = ChecklistItem(
            id="3d-optional",
            domain="3d_visualization",
            description="옵션 항목",
            must_satisfy=False,  # ← skip 대상
            detect_keywords=["MISSING_KW"],
        )
        unsatisfied = _validate_domain_checklist([item], "", "")
        assert unsatisfied == []  # must_satisfy=False 라서 검증 skip

    def test_item_without_detect_keywords_skipped(self) -> None:
        item = ChecklistItem(
            id="3d-no-kw",
            domain="3d_visualization",
            description="키워드 없는 항목",
            must_satisfy=True,
            detect_keywords=[],
        )
        unsatisfied = _validate_domain_checklist([item], "", "")
        assert unsatisfied == []  # 결정론 검증 불가 — skip


# =============================================================================
# 2. Rule 0 회귀 0 보장 — domain_checklist 미지정 시 기존 동작
# =============================================================================
class TestRule0BackwardCompatibility:
    """⭐ PM 가드라인: domain_checklist=None 방어 코드 검증."""

    def test_default_none_complete_path_preserved(self) -> None:
        """must_fix=0 + domain_checklist 미지정 → COMPLETE (Rule 1)."""
        gap = GapReport(satisfied_count=5, unsatisfied_blockers=0)
        decision = judge_convergence(gap)  # domain_checklist=None default
        assert decision.verdict == Verdict.COMPLETE
        assert decision.domain_unsatisfied == []  # 빈 list (default factory)

    def test_explicit_none_complete_path_preserved(self) -> None:
        gap = GapReport(unsatisfied_blockers=0)
        decision = judge_convergence(gap, domain_checklist=None)
        assert decision.verdict == Verdict.COMPLETE

    def test_explicit_empty_list_complete_path_preserved(self) -> None:
        gap = GapReport(unsatisfied_blockers=0)
        decision = judge_convergence(gap, domain_checklist=[])
        assert decision.verdict == Verdict.COMPLETE

    def test_default_none_improve_path_preserved(self) -> None:
        """must_fix > 0 + 안전 OK → IMPROVE_NEEDED (Rule 5)."""
        gap = GapReport(unsatisfied_blockers=1, iteration=1)
        decision = judge_convergence(gap)
        assert decision.verdict == Verdict.IMPROVE_NEEDED

    def test_default_none_stagnation_blocked_preserved(self) -> None:
        """Rule 2 STAGNATION 분기 그대로."""
        gap = GapReport(unsatisfied_blockers=1, stagnation=True)
        decision = judge_convergence(gap)
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.STAGNATION


# =============================================================================
# 3. Rule 0 IMPROVE_NEEDED 강제 — Rule 1 COMPLETE 도 override
# =============================================================================
class TestRule0OverridesComplete:
    """⭐ BIM 본질 — must_fix=0 인데 도메인 미충족 → 1회 종료 차단."""

    def test_rule_0_overrides_complete(self) -> None:
        """Gap Analyst 가 COMPLETE 라도 도메인 미충족 시 IMPROVE 강제."""
        gap = GapReport(satisfied_count=5, unsatisfied_blockers=0)
        checklist = _make_3d_checklist()
        # Engineer 산출에 키워드 0건 → 2 항목 모두 미충족
        decision = judge_convergence(
            gap,
            domain_checklist=checklist,
            engineer_output_excerpt="isometric 2D canvas drawing",
            qa_result_excerpt="passed",
        )
        # Rule 1 의 COMPLETE 대신 Rule 0 의 IMPROVE_NEEDED
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.blocked_cause == BlockedCause.NONE
        assert set(decision.domain_unsatisfied) == {"3d-orbit", "3d-real"}

    def test_rule_0_reason_includes_unsatisfied_preview(self) -> None:
        gap = GapReport(unsatisfied_blockers=0)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap, domain_checklist=checklist,
            engineer_output_excerpt="", qa_result_excerpt="",
        )
        assert "2/2 unsatisfied" in decision.reason
        assert "[3d-orbit]" in decision.reason
        assert "[3d-real]" in decision.reason

    def test_rule_0_next_action_includes_ids(self) -> None:
        """next_action 에 미충족 ID 명시 — 다음 iter Engineer prompt 주입용."""
        gap = GapReport(unsatisfied_blockers=0)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap, domain_checklist=checklist,
            engineer_output_excerpt="",
        )
        assert "3d-orbit" in decision.next_action
        assert "3d-real" in decision.next_action

    def test_rule_0_skipped_when_all_satisfied(self) -> None:
        """모든 도메인 항목 충족 → Rule 0 통과 → Rule 1 (COMPLETE) 진입."""
        gap = GapReport(unsatisfied_blockers=0)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap,
            domain_checklist=checklist,
            engineer_output_excerpt=(
                "Setup OrbitControls + rotate enabled + "
                "PerspectiveCamera + Vector3.set()"
            ),
            qa_result_excerpt="all green",
        )
        assert decision.verdict == Verdict.COMPLETE  # Rule 0 통과 → Rule 1
        assert decision.domain_unsatisfied == []

    def test_rule_0_with_must_fix_still_improves(self) -> None:
        """must_fix > 0 + domain 미충족 → IMPROVE (Rule 0 우선)."""
        gap = GapReport(unsatisfied_blockers=2, iteration=1)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap, domain_checklist=checklist,
            engineer_output_excerpt="",
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.must_fix_count == 2  # Rule 0 가 must_fix 도 반영


# =============================================================================
# 4. ★ P0 회귀 수정 (PR #234) — Rule 0 IMPROVE 가 iteration cap 을 선점하지 못함
# =============================================================================
class TestRule0VsIterationCap:
    """⭐ P0 회귀 수정 (crash 분석 2026-05-29): 이전엔 Rule 0(도메인 미충족 IMPROVE)가
    ITERATION_CAP 을 *선점* 해 종료 규칙이 dead code 가 되어 무한 IMPROVE →
    GraphRecursionError 크래시였다. 하드 종료 가드가 'IMPROVE + iter>=max →
    BLOCKED(ITERATION_CAP)' 로 강제 전환하되, COMPLETE override 와 iter<max 정상
    IMPROVE 는 보존한다.

    ⚠️ 회귀 노트: 본 클래스의 ``test_rule_0_overrides_iteration_cap`` (구버전)은
    버그 동작(iter==max 인데 IMPROVE)을 '정답'으로 박제하고 있어 pytest 가 크래시를
    못 잡은 통합 갭의 원인이었다. P0 수정으로 corrected 동작 검증으로 교체한다.
    """

    def test_domain_unsatisfied_at_cap_forces_blocked(self) -> None:
        """★ 핵심: 도메인 미충족 + iter==max → BLOCKED(ITERATION_CAP) (NOT IMPROVE)."""
        gap = GapReport(unsatisfied_blockers=1, iteration=5)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap,
            max_iterations=5,
            domain_checklist=checklist,
            engineer_output_excerpt="",  # 키워드 0매칭 → 영구 미충족
        )
        # 하드 가드 — Rule 0 의 IMPROVE 가 cap 에서 BLOCKED 로 강제 전환
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP
        # domain_unsatisfied 보존 (캡 종료라도 미충족 상태를 알게)
        assert len(decision.domain_unsatisfied) == 2

    def test_domain_unsatisfied_below_cap_still_improves(self) -> None:
        """iter < max → Rule 0 정상 IMPROVE (회귀 0 — 가드 미발동)."""
        gap = GapReport(unsatisfied_blockers=1, iteration=4)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap,
            max_iterations=5,
            domain_checklist=checklist,
            engineer_output_excerpt="",
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert len(decision.domain_unsatisfied) == 2

    def test_iteration_cap_when_domain_satisfied(self) -> None:
        """domain 충족 + iter cap → Rule 4 BLOCKED(ITERATION_CAP) 정상 동작."""
        gap = GapReport(unsatisfied_blockers=1, iteration=5)
        checklist = _make_3d_checklist()
        decision = judge_convergence(
            gap,
            max_iterations=5,
            domain_checklist=checklist,
            engineer_output_excerpt=(
                "OrbitControls + rotate + PerspectiveCamera + Vector3"
            ),
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP


# =============================================================================
# 5. BlockedCause.FAKE_PACKAGE enum 정의 (PR #228 대비)
# =============================================================================
class TestFakePackageEnum:
    """⭐ PR #228 의 PyPI 검증 대비 — enum 사전 정의 (절충안)."""

    def test_fake_package_enum_exists(self) -> None:
        assert BlockedCause.FAKE_PACKAGE.value == "FAKE_PACKAGE"
        # str enum 비교
        assert str(BlockedCause.FAKE_PACKAGE) == "BlockedCause.FAKE_PACKAGE"

    def test_existing_enums_preserved(self) -> None:
        """기존 enum 회귀 0 확인."""
        assert BlockedCause.BUILD_FAILED.value == "BUILD_FAILED"
        assert BlockedCause.STAGNATION.value == "STAGNATION"
        assert BlockedCause.BUDGET_EXHAUSTED.value == "BUDGET_EXHAUSTED"
        assert BlockedCause.ITERATION_CAP.value == "ITERATION_CAP"
        assert BlockedCause.NONE.value == "NONE"


# =============================================================================
# 6. JudgmentDecision.domain_unsatisfied schema 검증
# =============================================================================
class TestJudgmentDecisionSchema:
    def test_default_factory_empty_list(self) -> None:
        d = JudgmentDecision(
            verdict=Verdict.COMPLETE,
            blocked_cause=BlockedCause.NONE,
            reason="r",
            next_action="n",
            must_fix_count=0,
        )
        # default — 빈 list (회귀 0)
        assert d.domain_unsatisfied == []

    def test_explicit_unsatisfied_ids(self) -> None:
        d = JudgmentDecision(
            verdict=Verdict.IMPROVE_NEEDED,
            blocked_cause=BlockedCause.NONE,
            reason="r",
            next_action="n",
            must_fix_count=0,
            domain_unsatisfied=["3d-orbit", "3d-real"],
        )
        assert d.domain_unsatisfied == ["3d-orbit", "3d-real"]
