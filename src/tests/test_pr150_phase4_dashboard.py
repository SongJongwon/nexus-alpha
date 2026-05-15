# -*- coding: utf-8 -*-
"""PR #150 Phase 4 — 실시간 대시보드 (PhaseTracker) + Vision QA × qa_feedback_loop 통합.

배경 (본인 비전 통찰 5 — Observability 부재):
    친구 PC 베타 22~33min 빌드 중 PowerShell 화면이 dead screen — 친구가 *멈춘 줄
    알고* Ctrl+C → 작업 잃음. Quick Edit Mode 부작용으로 selection 시 실 정지된 것도
    가시화 부재의 부수 효과.

배경 (본인 비전 통찰 6 D-3 — Vision QA 가시화 확장):
    PR #147 Phase 2 가 ``scripts/run.py`` 의 build 후 Vision QA 자동 호출만 wiring.
    본 PR 은 그 결과를 ``qa_feedback_loop.evaluate_qa_results`` 로 평가해 명시적
    verdict (PASS / RETRY / BUDGET_EXHAUSTED) 출력 — 사용자가 결함 즉시 인지.

본 테스트 목적:
    - PhaseTracker 단위: start/end + 누적 시간 + 카운터
    - _run_vision_qa_full / _run_vision_qa backward-compat
    - _evaluate_vision_qa_via_feedback_loop: PASS / FAIL 시 verdict 추출
    - scripts/run.py + install.ps1 file-text 회귀 차단
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"
INSTALL_PS1 = PROJECT_ROOT / "install.ps1"


# ---------------------------------------------------------------------------
# 1. PhaseTracker 단위
# ---------------------------------------------------------------------------


def _load_run_module():
    """scripts/run.py 를 module 로 import — 격리 namespace."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("scripts_run_under_test_p4", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_tracker_class_exists() -> None:
    """scripts/run.py 에 PhaseTracker 클래스 정의."""
    module = _load_run_module()
    assert hasattr(module, "PhaseTracker"), "PhaseTracker 클래스 누락 — 대시보드 회귀"


def test_phase_tracker_starts_and_ends_phase(capsys) -> None:
    """start() 후 end() — 콘솔 출력 + 누적 시간 누적."""
    module = _load_run_module()
    tracker = module.PhaseTracker(total=3)

    tracker.start("phase A")
    captured = capsys.readouterr()
    assert "[1/3]" in captured.out
    assert "phase A" in captured.out

    tracker.end(summary="ok")
    captured = capsys.readouterr()
    assert "[1/3]" in captured.out
    assert "완료" in captured.out
    assert "ok" in captured.out


def test_phase_tracker_increments_counter(capsys) -> None:
    """여러 단계 — counter 1/N → 2/N → 3/N."""
    module = _load_run_module()
    tracker = module.PhaseTracker(total=3)

    tracker.start("a"); tracker.end()
    tracker.start("b"); tracker.end()
    tracker.start("c"); tracker.end()

    out = capsys.readouterr().out
    assert "[1/3]" in out
    assert "[2/3]" in out
    assert "[3/3]" in out


def test_phase_tracker_total_elapsed_returns_positive() -> None:
    """total_elapsed() 양수 반환 — 시간 경과 측정."""
    module = _load_run_module()
    tracker = module.PhaseTracker(total=1)
    elapsed = tracker.total_elapsed()
    assert elapsed >= 0.0


def test_phase_tracker_end_without_start_is_noop(capsys) -> None:
    """end() 만 호출 — 예외 없이 무시."""
    module = _load_run_module()
    tracker = module.PhaseTracker(total=1)
    tracker.end()  # no preceding start
    # 어떤 동작이든 예외 안 던지면 OK
    captured = capsys.readouterr()
    assert "완료" not in captured.out  # 출력 없음 확인


# ---------------------------------------------------------------------------
# 2. _run_vision_qa_full + backward-compat
# ---------------------------------------------------------------------------


def test_run_vision_qa_full_exists() -> None:
    """``_run_vision_qa_full`` helper 정의 — 결과 객체 반환 버전."""
    module = _load_run_module()
    assert hasattr(module, "_run_vision_qa_full")


def test_run_vision_qa_backward_compat_wrapper_exists() -> None:
    """``_run_vision_qa`` (str summary 반환) 보존 — PR #141 회귀 차단."""
    module = _load_run_module()
    assert hasattr(module, "_run_vision_qa")


# ---------------------------------------------------------------------------
# 3. _evaluate_vision_qa_via_feedback_loop
# ---------------------------------------------------------------------------


class _FakeVisionPass:
    success = True
    skipped = False

    def summary_line(self) -> str:
        return "[GUI_TEST PASS]"


class _FakeVisionFail:
    success = False
    skipped = False

    def summary_line(self) -> str:
        return "[GUI_TEST FAIL] critical=2"


def test_evaluate_vision_qa_pass_returns_pass_verdict() -> None:
    """Vision PASS → qa_feedback_loop verdict 도 PASS.

    PR #151: 반환이 ``(verdict_str, decision)`` 튜플로 변경됨.
    """
    module = _load_run_module()
    summary, _decision = module._evaluate_vision_qa_via_feedback_loop(
        _FakeVisionPass()
    )
    assert "PASS" in summary


def test_evaluate_vision_qa_fail_returns_non_pass_verdict() -> None:
    """Vision FAIL → verdict 가 PASS 아님 (RETRY / BUDGET_EXHAUSTED 등).

    PR #151: 반환이 tuple 로 변경됨. 기본 ``max_retries=0`` 유지.
    """
    module = _load_run_module()
    summary, _decision = module._evaluate_vision_qa_via_feedback_loop(
        _FakeVisionFail()
    )
    assert "PASS" not in summary
    # max_retries=0 (기본) 으로 호출하므로 BUDGET_EXHAUSTED 가 정상
    assert "BUDGET_EXHAUSTED" in summary or "RETRY" in summary


# ---------------------------------------------------------------------------
# 4. Track A 가 PhaseTracker 사용 — file-text 회귀
# ---------------------------------------------------------------------------


def test_track_a_uses_phase_tracker() -> None:
    """_run_track_a 본문에 PhaseTracker 사용."""
    text = RUN_PY.read_text(encoding="utf-8")
    import re

    match = re.search(
        r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "PhaseTracker" in body, (
        "_run_track_a 가 PhaseTracker 사용 안 함 — 실시간 대시보드 회귀"
    )
    assert "tracker.start" in body and "tracker.end" in body


def test_track_a_evaluates_via_qa_feedback_loop() -> None:
    """_run_track_a 가 _evaluate_vision_qa_via_feedback_loop 호출."""
    text = RUN_PY.read_text(encoding="utf-8")
    import re

    match = re.search(
        r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "_evaluate_vision_qa_via_feedback_loop" in body, (
        "Track A 가 qa_feedback_loop 평가 호출 안 함 — Phase 4 확장 회귀"
    )


# ---------------------------------------------------------------------------
# 5. _print_result_summary 가 qa_verdict_summary 매개변수 수용
# ---------------------------------------------------------------------------


def test_print_result_summary_accepts_qa_verdict() -> None:
    """_print_result_summary 시그니처에 qa_verdict_summary 매개변수."""
    text = RUN_PY.read_text(encoding="utf-8")
    import re

    match = re.search(
        r"def\s+_print_result_summary\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "qa_verdict_summary" in match.group(0)


# ---------------------------------------------------------------------------
# 6. install.ps1 — Quick Edit 안내 추가
# ---------------------------------------------------------------------------


def test_install_ps1_has_quick_edit_warning_function() -> None:
    """install.ps1 에 Write-QuickEditWarning 함수 정의."""
    text = INSTALL_PS1.read_text(encoding="utf-8-sig")
    assert "function Write-QuickEditWarning" in text


def test_install_ps1_calls_quick_edit_warning_at_entry() -> None:
    """진입점에서 Write-QuickEditWarning 호출 (Write-Banner 직후)."""
    text = INSTALL_PS1.read_text(encoding="utf-8-sig")
    # Write-Banner 다음 줄에 Write-QuickEditWarning
    import re
    match = re.search(
        r"Write-Banner\s*\nWrite-QuickEditWarning",
        text,
    )
    assert match is not None, (
        "Write-Banner 직후 Write-QuickEditWarning 호출 누락"
    )


def test_install_ps1_warning_mentions_quick_edit_explicitly() -> None:
    """안내 문구에 *Quick Edit* + *Properties* 명시 (사용자 행동 가이드)."""
    text = INSTALL_PS1.read_text(encoding="utf-8-sig")
    assert "Quick Edit" in text or "QuickEdit" in text
    assert "Properties" in text  # 사용자가 어디서 끄는지 명시
