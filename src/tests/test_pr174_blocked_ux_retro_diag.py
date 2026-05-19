# -*- coding: utf-8 -*-
"""PR #174 — BLOCKED 결과 패널 UX 개선 + Retrospective 진단 surface.

배경 (2026-05-18 Track B E2E 17:04 분석):
    PR #170 + PR #172 라이브 검증 성공 후 산출 분석에서 2 결함 발견:

    결함 #A — BLOCKED verdict UX:
        ``verdict=BLOCKED iterations=1/1`` — PM 입장 .exe 산출 (Scrape.exe 45.23 MB)
        있는데 "BLOCKED" 만 보임 → 부정적 인상 + 다음 행동 미보임. blocked_cause
        (ITERATION_CAP / BUILD_FAILED / BUDGET / STAGNATION) 미표시 → 사용자가
        어떤 원인인지 미식별. **결함 아닌 정상 동작이지만 UX 갭**.
        Root-cause: judge_convergence Rule 4 (must_fix > 0 + iter=max=1 →
        ITERATION_CAP). 1 iter 만 돌면 LLM 산출이 perfect 안 되는 자연스러운 결과.

    결함 #B — Retrospective 빈 응답 (fail-silent 5번째 변형):
        ``retrospective.md`` 의 4 섹션 모두 "(없음)" → run_retrospective 의 4 list
        모두 빈 list. Root-cause 3 후보:
            a. ``_default_llm_call`` Exception (response="") → parse 빈 dict → 빈 list
            b. response 받았지만 JSON parsing 실패 → 빈 dict → 빈 list
            c. 정상 응답이지만 LLM 이 "딱히 ..." 판단 → 4 list 모두 빈 list
        이전 (PR #174 이전) 의 분기는 *어느* 시나리오인지 *진단 정보 미보존* —
        PR #160a (vision_unavailable) / PR #170 (CodeQASkipped) / PR #172 (도메인
        graceful fallback) 패턴의 5번째 변형.

PR #174 처방:

    A. ``format_iterative_summary`` 헬퍼 + ``_format_blocked_partial_hint``:
        - LoopOutcome 입력 → 결과 패널 Iterate 라인 한 줄 생성
        - BLOCKED 시 ``verdict=BLOCKED(<cause>) iterations=N/M — <partial hint>``
        - 4 cause 별 partial output / next action 안내
        - scripts/run.py 의 Track A + Track B caller 모두 호출

    B. ``run_retrospective`` 3 시나리오 진단 surface:
        - LLM Exception → wrong[0]/lessons[0] 에 type+msg surface
        - JSON parse 실패 → wrong[0] 에 raw response 일부 surface
        - 정상 응답 + 4 list 빈 → well[0] 에 LLM 판단 fallback

본 테스트:
    1. format_iterative_summary 5 분기 (COMPLETE + 4 BLOCKED cause)
    2. PM E2E 회귀 case (BLOCKED ITERATION_CAP + Scrape.exe partial hint)
    3. run_retrospective LLM Exception → wrong/lessons 진단 surface
    4. run_retrospective JSON parse 실패 → raw preview surface
    5. run_retrospective 정상 응답 빈 list → well fallback
    6. run_retrospective 정상 응답 + 채워진 list → 기존 동작 회귀 차단
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agents.c_level.convergence_judge import BlockedCause, Verdict
from src.agents.coordination.retrospective_lead import run_retrospective
from src.workflows.iterative_loop import (
    LoopOutcome,
    _format_blocked_partial_hint,
    format_iterative_summary,
)


# ---------------------------------------------------------------------------
# Fixture — LoopOutcome 빌더 (테스트 boilerplate 축소)
# ---------------------------------------------------------------------------


def _make_outcome(
    *,
    verdict: Verdict = Verdict.COMPLETE,
    blocked_cause: BlockedCause = BlockedCause.NONE,
    iterations_run: int = 1,
) -> LoopOutcome:
    return LoopOutcome(
        user_request="test",
        verdict=verdict,
        blocked_cause=blocked_cause,
        iterations_run=iterations_run,
        spec_markdown="",
        final_chain_result=None,
        final_execution_result=None,
        final_gap_report_raw="",
        final_gap_report=None,
        final_decision=None,
    )


# ---------------------------------------------------------------------------
# 1. format_iterative_summary — 5 분기
# ---------------------------------------------------------------------------


def test_format_summary_complete_omits_cause() -> None:
    """COMPLETE → 기존 형식 유지 (cause 표시 X, partial hint 없음)."""
    outcome = _make_outcome(verdict=Verdict.COMPLETE)
    summary = format_iterative_summary(outcome, max_iterations=1)
    assert "verdict=complete" in summary.lower()
    assert "iterations=1/1" in summary
    assert "BLOCKED" not in summary
    assert "—" not in summary  # partial hint 없음


def test_format_summary_blocked_iteration_cap_shows_partial_hint() -> None:
    """⭐ PM E2E 회귀 case — BLOCKED(ITERATION_CAP) + partial output 안내."""
    outcome = _make_outcome(
        verdict=Verdict.BLOCKED,
        blocked_cause=BlockedCause.ITERATION_CAP,
        iterations_run=1,
    )
    summary = format_iterative_summary(outcome, max_iterations=1)
    assert "verdict=BLOCKED(ITERATION_CAP)" in summary
    assert "iterations=1/1" in summary
    assert "partial output 산출 완료" in summary
    assert "--max-iterations" in summary  # next action 안내


def test_format_summary_blocked_build_failed_shows_executor_hint() -> None:
    """BLOCKED(BUILD_FAILED) — PR #162 verdict override 시 결과 패널 안내."""
    outcome = _make_outcome(
        verdict=Verdict.BLOCKED,
        blocked_cause=BlockedCause.BUILD_FAILED,
    )
    summary = format_iterative_summary(outcome, max_iterations=1)
    assert "verdict=BLOCKED(BUILD_FAILED)" in summary
    assert ".exe 산출 실패" in summary
    assert "04_executor_result.md" in summary


def test_format_summary_blocked_budget_exhausted_shows_budget_hint() -> None:
    """BLOCKED(BUDGET_EXHAUSTED) — 토큰 예산 소진 안내."""
    outcome = _make_outcome(
        verdict=Verdict.BLOCKED,
        blocked_cause=BlockedCause.BUDGET_EXHAUSTED,
    )
    summary = format_iterative_summary(outcome, max_iterations=3)
    assert "verdict=BLOCKED(BUDGET_EXHAUSTED)" in summary
    assert "토큰 예산 소진" in summary
    assert "--budget-tokens" in summary


def test_format_summary_blocked_stagnation_shows_ambiguity_hint() -> None:
    """BLOCKED(STAGNATION) — 진행 정체 안내."""
    outcome = _make_outcome(
        verdict=Verdict.BLOCKED,
        blocked_cause=BlockedCause.STAGNATION,
    )
    summary = format_iterative_summary(outcome, max_iterations=3)
    assert "verdict=BLOCKED(STAGNATION)" in summary
    assert "진행 정체" in summary
    assert "요구사항 모호" in summary


def test_format_blocked_partial_hint_none_cause_returns_empty() -> None:
    """``BlockedCause.NONE`` 또는 미정의 cause → 빈 문자열 (안전망)."""
    assert _format_blocked_partial_hint(BlockedCause.NONE) == ""


# ---------------------------------------------------------------------------
# 2. run_retrospective — 진단 surface (3 시나리오)
# ---------------------------------------------------------------------------


def test_retrospective_llm_exception_surfaces_type_and_msg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 호출 Exception → wrong/lessons 에 type+msg surface (fail-silent 차단)."""
    # pytest 환경이라 자동 skip 분기 진입 → llm_call=None. 외부 주입으로 분기 활성화.
    def raising_llm_call(prompt: str) -> str:
        raise RuntimeError("API timeout after 30s")

    report = run_retrospective(
        user_request="test",
        workflow_id="wf_test",
        verdict="BLOCKED",
        llm_call=raising_llm_call,
    )

    assert report.what_went_wrong, "Exception 진단 메시지가 wrong 에 있어야 함"
    assert "Retrospective LLM 호출 실패" in report.what_went_wrong[0]
    assert "RuntimeError" in report.what_went_wrong[0]
    assert "API timeout after 30s" in report.what_went_wrong[0]
    assert report.lessons_learned
    assert "LLM API 안정성" in report.lessons_learned[0]


def test_retrospective_json_parse_failure_surfaces_raw_preview() -> None:
    """response 정상이지만 JSON 형식 아님 → wrong 에 raw 일부 surface."""

    def bad_json_llm_call(prompt: str) -> str:
        return (
            "이건 JSON 이 아니라 그냥 자유 텍스트 응답입니다. "
            "회고 잘했어요 라고 LLM 이 말함."
        )

    report = run_retrospective(
        user_request="test",
        workflow_id="wf_test",
        verdict="COMPLETE",
        llm_call=bad_json_llm_call,
    )

    assert report.what_went_wrong
    assert "JSON parse 실패" in report.what_went_wrong[0]
    assert "raw:" in report.what_went_wrong[0]
    assert "자유 텍스트 응답" in report.what_went_wrong[0]
    assert report.lessons_learned
    assert "JSON 형식 강제" in report.lessons_learned[0]


def test_retrospective_empty_lists_get_well_fallback() -> None:
    """정상 응답 + parse OK 인데 4 list 모두 빈 list → well 에 LLM 판단 fallback."""

    def empty_json_llm_call(prompt: str) -> str:
        return (
            '{"what_went_well": [], "what_went_wrong": [], "lessons_learned": []}'
        )

    report = run_retrospective(
        user_request="test",
        workflow_id="wf_test",
        verdict="COMPLETE",
        llm_call=empty_json_llm_call,
    )

    assert report.what_went_well
    assert "LLM 정상 응답" in report.what_went_well[0]
    assert "회고 항목 없음" in report.what_went_well[0]
    # wrong / lessons 는 그대로 빈 (LLM 판단)
    assert report.what_went_wrong == []
    assert report.lessons_learned == []


def test_retrospective_silent_empty_response_surfaces_diagnosis() -> None:
    """⭐ PR #176 hot-fix 회귀 차단 — response="" *예외 없이* 반환 시 진단 surface.

    2026-05-19 Track B E2E 재검증 (8.40min PASS) 에서 PR #174 의 fix B 가 *분기 갭* 으로
    인해 라이브 미발동 — retrospective.md 여전히 4 섹션 (없음). Root-cause: PR #174 의
    3 분기 (Exception / parse 실패 / 빈 list well fallback) 모두 *response 또는 parsed
    가 비어있지 않다* 는 전제. ``response="" + llm_error_reason=None`` (silent timeout /
    공백 응답) 케이스 미cover → 4번째 분기 추가 필요.

    fail-silent 5번째 변형의 *6번째 sub-variant* — 본 PR 자체가 진단 surface 추가했지만
    분기 갭으로 surface 안 됨. 자기 진화 cycle 의 self-correction 반복 evidence.
    """

    def silent_empty_llm_call(prompt: str) -> str:
        return ""  # 예외 없이 빈 문자열 반환 (LLM provider silent failure 시뮬레이션)

    report = run_retrospective(
        user_request="네이버 쇼핑 크롤러",
        workflow_id="wf_silent_empty",
        verdict="BLOCKED",
        llm_call=silent_empty_llm_call,
    )

    assert report.what_went_wrong, "분기 갭 회귀 — silent 빈 응답이 wrong 에 surface 안 됨"
    assert "빈 문자열" in report.what_went_wrong[0]
    assert "silent" in report.what_went_wrong[0]
    assert report.lessons_learned
    assert "LLM provider" in report.lessons_learned[0]


def test_retrospective_whitespace_only_response_surfaces_diagnosis() -> None:
    """공백/newline 만 있는 응답도 동일 분기 — strip() 후 빈."""

    def whitespace_llm_call(prompt: str) -> str:
        return "   \n\t   \n"

    report = run_retrospective(
        user_request="test",
        workflow_id="wf_whitespace",
        verdict="BLOCKED",
        llm_call=whitespace_llm_call,
    )

    assert report.what_went_wrong
    assert "빈 문자열" in report.what_went_wrong[0]


def test_retrospective_normal_response_passes_through() -> None:
    """LLM 이 well/wrong/lessons 채워서 응답 → 그대로 사용 (회귀 차단)."""

    def good_llm_call(prompt: str) -> str:
        return (
            '{"what_went_well": ["pytest 100% PASS"], '
            '"what_went_wrong": ["타임아웃 5s 부족"], '
            '"lessons_learned": ["타임아웃 30s 권장"]}'
        )

    report = run_retrospective(
        user_request="test",
        workflow_id="wf_test",
        verdict="COMPLETE",
        llm_call=good_llm_call,
    )

    assert report.what_went_well == ["pytest 100% PASS"]
    assert report.what_went_wrong == ["타임아웃 5s 부족"]
    assert report.lessons_learned == ["타임아웃 30s 권장"]


def test_retrospective_pytest_env_skips_llm_call() -> None:
    """pytest 환경 (``sys.modules`` 에 'pytest') → llm_call=None 자동 skip.

    본 PR 의 진단 분기는 llm_call != None 일 때만 진입 → 회귀 차단.
    pytest 환경에서는 결정론 골격 (delta + verdict) 만 반환.
    """
    report = run_retrospective(
        user_request="test",
        workflow_id="wf_test",
        verdict="COMPLETE",
    )
    # llm_call None + pytest 환경 → well/wrong/lessons 모두 빈 list
    # (진단 분기 안 진입 → 5번째 변형의 진단 surface 안 발동)
    assert report.what_went_well == []
    assert report.what_went_wrong == []
    assert report.lessons_learned == []


# ---------------------------------------------------------------------------
# 3. file-text — scripts/run.py 가 format_iterative_summary import (회귀 차단)
# ---------------------------------------------------------------------------


def test_runpy_imports_format_iterative_summary() -> None:
    """``scripts/run.py`` 의 Track A + Track B caller 가 ``format_iterative_summary``
    를 import 하는지 file-text 회귀 차단 (PR #174)."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    runpy_text = (repo_root / "scripts" / "run.py").read_text(encoding="utf-8")
    assert runpy_text.count("format_iterative_summary") >= 2, (
        "Track A + Track B 양쪽 caller 가 format_iterative_summary 호출해야 함"
    )
