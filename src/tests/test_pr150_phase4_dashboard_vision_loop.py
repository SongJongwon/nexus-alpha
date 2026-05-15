# -*- coding: utf-8 -*-
"""PR #150 Phase 4 — 실시간 대시보드 + Vision QA → qa_feedback_loop 통합 회귀 차단.

배경 (본인 비전 통찰 5 — Observability 부재 + 통찰 6 D-3 Vision):
    친구 PC 베타 22~33min .exe 빌드 도중 PowerShell 화면이 *dead screen* →
    친구가 "멈춘 줄 알았다" → Quick Edit Mode 부작용으로 selection 시 정지 → Ctrl+C
    작업 손실. 이는 *시스템* 의 진행 상황 가시화 부재가 본질.

    PR #147 Phase 2 가 ``_run_vision_qa`` 를 Track A 에 wiring 했지만 결과를
    *그냥 print* — 다른 QA 도구들과 합산해 verdict 도출하는 ``qa_feedback_loop``
    에 연결되지 않음.

PR #150 처방:
    - ``PhaseTracker`` — 의존성 0, print 기반 단계 진행 표시
    - ``_run_vision_qa_full`` — 기존 ``_run_vision_qa`` (str 반환) 옆에 신설.
      ``GUITestResult`` 객체 자체를 반환 → ``qa_feedback_loop`` 입력 가능
    - ``_evaluate_vision_qa_via_feedback_loop`` — ``evaluate_qa_results`` 호출 →
      verdict 1줄
    - ``_print_result_summary`` 에 ``qa_verdict_summary`` 매개변수 추가
    - Track B 에도 PhaseTracker (Vision QA wiring 은 미적용 — 자동화 산출에 부적합)

본 테스트 목적:
    - 신규 helper 4종 정의 + 호출 와이어링 회귀 차단
    - import 시 syntax 오류 차단 (PR #147 partial work 단계에서 미정의 헬퍼 호출로
      ImportError 회귀가 있었음)
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr150", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr150"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. import 안정성 — partial work 단계의 미정의 헬퍼 호출 회귀 차단
# ---------------------------------------------------------------------------


def test_run_py_imports_cleanly_with_phase4_helpers(run_mod) -> None:
    """``scripts/run.py`` 가 syntax/NameError 없이 import 됨.

    PR #150 partial work 단계의 ``_run_vision_qa_full`` / ``_evaluate_vision_qa_via_feedback_loop``
    미정의 호출이 import 가 아닌 *런타임* 에러였지만 helper 정의가 누락되면
    static linter 단계에서 미참조 식별자 검출 → 회귀 차단.
    """
    assert hasattr(run_mod, "PhaseTracker")
    assert hasattr(run_mod, "_run_vision_qa")
    assert hasattr(run_mod, "_run_vision_qa_full")
    assert hasattr(run_mod, "_evaluate_vision_qa_via_feedback_loop")
    assert hasattr(run_mod, "_print_result_summary")


# ---------------------------------------------------------------------------
# 2. PhaseTracker — print 기반 단계 진행 표시
# ---------------------------------------------------------------------------


def test_phase_tracker_increments_index_on_start(run_mod) -> None:
    tracker = run_mod.PhaseTracker(total=3)
    assert tracker.current_index == 0
    tracker.start("phase A")
    assert tracker.current_index == 1
    tracker.end()
    tracker.start("phase B")
    assert tracker.current_index == 2


def test_phase_tracker_prints_phase_marker(run_mod, capsys) -> None:
    """``start`` 호출 시 ``▶ [i/N] name (누적 …s)`` 라인 출력."""
    tracker = run_mod.PhaseTracker(total=2)
    tracker.start("hello")
    captured = capsys.readouterr().out
    assert "▶" in captured
    assert "[1/2]" in captured
    assert "hello" in captured
    assert "누적" in captured


def test_phase_tracker_prints_end_marker_with_summary(run_mod, capsys) -> None:
    """``end(summary=...)`` 호출 시 ``✓`` + summary tail 출력."""
    tracker = run_mod.PhaseTracker(total=1)
    tracker.start("build")
    capsys.readouterr()  # discard start output
    tracker.end(summary="42 files")
    captured = capsys.readouterr().out
    assert "✓" in captured
    assert "[1/1]" in captured
    assert "42 files" in captured


def test_phase_tracker_end_without_start_is_noop(run_mod) -> None:
    """미시작 단계 ``end`` 호출 시 예외 없이 noop — defensive."""
    tracker = run_mod.PhaseTracker(total=1)
    tracker.end(summary="should be ignored")  # no AttributeError 등
    assert tracker._completed_phases == []


def test_phase_tracker_set_total_clamps_to_current(run_mod) -> None:
    """``set_total`` 가 ``current_index`` 보다 작은 값 → clamp.

    PR #150 — .exe 가 만들어진 줄 알았는데 미생성 시 분모 축소 시도해도 진행 단계
    뒤로 가지 않게 보호.
    """
    tracker = run_mod.PhaseTracker(total=3)
    tracker.start("phase A")
    tracker.end()
    tracker.set_total(0)  # clamp to current_index=1
    assert tracker.total == 1


def test_phase_tracker_total_elapsed_positive(run_mod) -> None:
    """``total_elapsed`` 가 양수 — 단조 증가하는 시계."""
    tracker = run_mod.PhaseTracker(total=1)
    assert tracker.total_elapsed() >= 0.0


# ---------------------------------------------------------------------------
# 3. _run_vision_qa_full — GUITestResult 객체 반환 (str 이 아닌)
# ---------------------------------------------------------------------------


class _FakeGUITestResult:
    """``run_gui_test`` mock 산출 — duck-typed GUITestResult 대용."""

    success = True
    skipped = False

    def summary_line(self) -> str:
        return "[GUI_TEST PASS] screenshots=1 critical=0 ui_issues=0 (0.50s)"


def test_run_vision_qa_full_returns_result_object_when_callable(
    run_mod, tmp_path, monkeypatch
) -> None:
    """``run_gui_test`` 정상 호출 → ``_run_vision_qa_full`` 가 result 객체 반환."""
    fake_result = _FakeGUITestResult()

    def _fake_run_gui_test(*, target_path, output_dir, skip_vision):
        return fake_result

    import src.agents.qa.gui_test_executor as gte
    monkeypatch.setattr(gte, "run_gui_test", _fake_run_gui_test)

    exe_path = tmp_path / "FakeApp.exe"
    exe_path.write_bytes(b"fake")
    result = run_mod._run_vision_qa_full(exe_path, tmp_path)
    assert result is fake_result


def test_run_vision_qa_full_returns_none_on_run_gui_test_exception(
    run_mod, tmp_path, monkeypatch
) -> None:
    """``run_gui_test`` 가 예외 발생 → None 반환 (워크플로 차단 X)."""
    def _boom(*, target_path, output_dir, skip_vision):
        raise RuntimeError("vision pipeline died")

    import src.agents.qa.gui_test_executor as gte
    monkeypatch.setattr(gte, "run_gui_test", _boom)

    exe_path = tmp_path / "FakeApp.exe"
    exe_path.write_bytes(b"fake")
    assert run_mod._run_vision_qa_full(exe_path, tmp_path) is None


def test_run_vision_qa_str_wrapper_returns_summary_line(
    run_mod, tmp_path, monkeypatch
) -> None:
    """Backward-compat: ``_run_vision_qa`` 는 여전히 str summary 반환."""
    fake_result = _FakeGUITestResult()

    def _fake_run_gui_test(*, target_path, output_dir, skip_vision):
        return fake_result

    import src.agents.qa.gui_test_executor as gte
    monkeypatch.setattr(gte, "run_gui_test", _fake_run_gui_test)

    exe_path = tmp_path / "FakeApp.exe"
    exe_path.write_bytes(b"fake")
    summary = run_mod._run_vision_qa(exe_path, tmp_path)
    assert isinstance(summary, str)
    assert "GUI_TEST PASS" in summary


# ---------------------------------------------------------------------------
# 4. _evaluate_vision_qa_via_feedback_loop — qa_feedback_loop 통합
# ---------------------------------------------------------------------------


def test_evaluate_vision_qa_via_feedback_loop_pass_verdict(run_mod) -> None:
    """Vision result success=True → QA_LOOP PASS verdict.

    PR #151: 반환이 ``(verdict_str, decision)`` 튜플로 변경됨. PR #150 회귀 테스트는
    첫 요소가 PR #150 verdict 형식 유지하는지 확인.
    """
    result = SimpleNamespace(
        success=True,
        skipped=False,
        summary_line=lambda: "[GUI_TEST PASS]",
    )
    verdict, decision = run_mod._evaluate_vision_qa_via_feedback_loop(result)
    assert "QA_LOOP PASS" in verdict
    assert decision is not None
    assert decision.overall_passed is True


def test_evaluate_vision_qa_via_feedback_loop_fail_verdict(run_mod) -> None:
    """Vision result success=False → BUDGET_EXHAUSTED (max_retries=0 기본).

    PR #150 의 의도적 선택 — verdict 가시화만, 자동 retry 미시작.
    PR #151: 호출 측이 ``max_retries=0`` 명시했을 때만 verdict 가시화 모드.
    """
    result = SimpleNamespace(
        success=False,
        skipped=False,
        summary_line=lambda: "[GUI_TEST FAIL] critical=2",
    )
    verdict, decision = run_mod._evaluate_vision_qa_via_feedback_loop(result)
    assert "BUDGET_EXHAUSTED" in verdict or "RETRY" in verdict
    assert decision is not None
    assert decision.overall_passed is False


# ---------------------------------------------------------------------------
# 5. _print_result_summary — qa_verdict_summary 매개변수 표시
# ---------------------------------------------------------------------------


def test_print_result_summary_accepts_qa_verdict(run_mod, capsys) -> None:
    """``_print_result_summary`` 가 ``qa_verdict_summary`` kwarg 수용 + 출력."""
    run_mod._print_result_summary(
        track="A",
        elapsed_sec=12.3,
        outputs_dir=None,
        exe_path=None,
        release_url=None,
        vision_qa_summary="[GUI_TEST PASS] critical=0",
        qa_verdict_summary="[QA_LOOP PASS] retry=0/0, failed=0, skipped=0",
    )
    captured = capsys.readouterr().out
    assert "QA loop" in captured
    assert "QA_LOOP PASS" in captured


def test_print_result_summary_signature_has_qa_verdict(run_mod) -> None:
    """``_print_result_summary`` 시그니처에 ``qa_verdict_summary`` 매개변수.

    File-text 검증 — 회귀 시 즉시 차단.
    """
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_print_result_summary\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "qa_verdict_summary" in match.group(0), (
        "_print_result_summary 가 qa_verdict_summary 매개변수 누락 — Phase 4 회귀"
    )


# ---------------------------------------------------------------------------
# 6. Track A / B 진입점이 PhaseTracker 사용
# ---------------------------------------------------------------------------


def test_track_a_uses_phase_tracker() -> None:
    """``_run_track_a`` 가 ``PhaseTracker`` 사용 — dashboard wiring."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "PhaseTracker" in body, (
        "Track A 가 PhaseTracker 사용 안 함 — Phase 4 dashboard wiring 회귀"
    )
    assert "_evaluate_vision_qa_via_feedback_loop" in body, (
        "Track A 가 _evaluate_vision_qa_via_feedback_loop 호출 안 함 — qa_feedback_loop 통합 회귀"
    )


def test_track_b_uses_phase_tracker() -> None:
    """``_run_track_b`` 도 ``PhaseTracker`` 사용 — Track 양쪽 일관 표시."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "PhaseTracker" in body, (
        "Track B 가 PhaseTracker 사용 안 함 — Phase 4 dashboard wiring 회귀"
    )
