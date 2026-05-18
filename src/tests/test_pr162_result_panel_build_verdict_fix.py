# -*- coding: utf-8 -*-
"""PR #162 — 결과 패널 build SKIPPED 진단 + iterative_loop verdict-reflects-build.

배경 (2026-05-18 E2E 재검증 발견):
    PR #160a+b 라이브 검증 목적으로 ``--auto-iterate --max-iterations 1`` 재실행
    (계산기 만들어줘). 결과:
        - iterative_loop verdict=COMPLETE iterations=1/1 (1855.9s)
        - 결과 패널 Iterate 라인 정상
        - **Vision/QA loop 라인 미표시** — PM 입장 "왜?" 디버깅 불가
        - 실 산출: PyInstaller SKIPPED (entry 미탐지 -7, test_calculator.py 만 산출)

    2 결함 노출:

    결함 #A — iterative_loop verdict 가 build 결과 미반영:
        ``judge_convergence`` 는 GapReport 만 입력 → Gap Analyst 가 "코드 잘 됨"
        이라 판정하면 verdict=COMPLETE. 그러나 PyInstaller .exe 산출이 실패한 경우
        (exit=-7 entry 미탐지 / -4 pip 실패 / -5 pre-validation / -6 attribute 검증)
        **사용자 손에 도달 가능한 산출물 없음** → COMPLETE 는 *사용자 관점 거짓*.

    결함 #B — 결과 패널 .exe SKIPPED reason 미표시 (fail-silent):
        ``_print_result_summary`` 가 ``exe_path=None`` 일 때 .exe 라인 자체를 출력 안
        함 → "왜 Vision/QA 가 없는가" PM 자가-디버깅 불가. PR #160b 의 retry 진단
        패턴과 동일한 fail-silent.

PR #162 처방:

    A. ``BlockedCause.BUILD_FAILED`` 신설 + ``_apply_build_failure_override`` 헬퍼:
        - verdict=COMPLETE 인데 ``chain_result.executor_result`` 가 build 실패 →
          BLOCKED(BUILD_FAILED) 로 override (deterministic, LLM 무관)
        - verdict=IMPROVE_NEEDED 면 다음 iter 가서 재시도 가능 → 그대로 유지
        - executor_result=None (build 비활성) 또는 success=True → 그대로 유지

    B. ``_format_build_skipped_line`` + ``_print_result_summary(executor_result=...)``:
        - exe_path=None 일 때 3 분기 진단 메시지 출력
        - Track A/B caller 모두 ``executor_result`` 전달

본 테스트:
    1. ``BlockedCause.BUILD_FAILED`` enum 존재
    2. ``_apply_build_failure_override`` 5 시나리오
    3. ``_node_judge_convergence`` 통합 — build 실패 → BLOCKED override
    4. ``_format_build_skipped_line`` 3 분기
    5. ``_print_result_summary`` — exe_path=None + executor_result 출력 cover (capsys)
    6. file-text — Track A/B caller 가 executor_result 전달
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr162", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr162"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. BlockedCause.BUILD_FAILED enum 존재 + 우선순위
# ---------------------------------------------------------------------------


def test_blocked_cause_build_failed_exists():
    """PR #162 — BUILD_FAILED enum 추가 (회귀 차단)."""
    from src.agents.c_level.convergence_judge import BlockedCause

    assert hasattr(BlockedCause, "BUILD_FAILED")
    assert BlockedCause.BUILD_FAILED.value == "BUILD_FAILED"
    # 기존 cause 보존
    assert BlockedCause.STAGNATION.value == "STAGNATION"
    assert BlockedCause.BUDGET_EXHAUSTED.value == "BUDGET_EXHAUSTED"
    assert BlockedCause.ITERATION_CAP.value == "ITERATION_CAP"
    assert BlockedCause.NONE.value == "NONE"


# ---------------------------------------------------------------------------
# 2. _apply_build_failure_override 5 시나리오
# ---------------------------------------------------------------------------


def _make_decision(verdict, cause=None, must_fix=0):
    from src.agents.c_level.convergence_judge import (
        BlockedCause,
        JudgmentDecision,
    )

    return JudgmentDecision(
        verdict=verdict,
        blocked_cause=cause if cause is not None else BlockedCause.NONE,
        reason="test fixture",
        next_action="test fixture",
        must_fix_count=must_fix,
    )


def _make_chain_result(*, executor_result):
    return SimpleNamespace(executor_result=executor_result)


def _make_failed_executor(exit_code=-7, error="entry 미탐지 — only test files"):
    return SimpleNamespace(
        success=False,
        exit_code=exit_code,
        error_message=error,
        exe_path=None,
    )


def _make_ok_executor(exe_path=None):
    return SimpleNamespace(
        success=True,
        exit_code=0,
        error_message=None,
        exe_path=exe_path or Path("/tmp/App.exe"),
    )


def test_override_skipped_when_verdict_not_complete():
    """IMPROVE_NEEDED — 다음 iter 가서 재시도 가능 → override X."""
    from src.agents.c_level.convergence_judge import Verdict
    from src.workflows.iterative_loop import _apply_build_failure_override

    decision = _make_decision(Verdict.IMPROVE_NEEDED, must_fix=2)
    chain = _make_chain_result(executor_result=_make_failed_executor())
    result = _apply_build_failure_override(decision, chain)
    assert result.verdict == Verdict.IMPROVE_NEEDED
    assert result.must_fix_count == 2


def test_override_skipped_when_chain_result_none():
    """chain_result is None → override X (입력 부재)."""
    from src.agents.c_level.convergence_judge import Verdict
    from src.workflows.iterative_loop import _apply_build_failure_override

    decision = _make_decision(Verdict.COMPLETE)
    result = _apply_build_failure_override(decision, None)
    assert result.verdict == Verdict.COMPLETE


def test_override_skipped_when_executor_result_none():
    """build 비활성 (enable_executor=False) → executor_result=None → override X."""
    from src.agents.c_level.convergence_judge import Verdict
    from src.workflows.iterative_loop import _apply_build_failure_override

    decision = _make_decision(Verdict.COMPLETE)
    chain = _make_chain_result(executor_result=None)
    result = _apply_build_failure_override(decision, chain)
    assert result.verdict == Verdict.COMPLETE


def test_override_skipped_when_build_success():
    """build 성공 (success=True + exe_path 있음) → override X."""
    from src.agents.c_level.convergence_judge import Verdict
    from src.workflows.iterative_loop import _apply_build_failure_override

    decision = _make_decision(Verdict.COMPLETE)
    chain = _make_chain_result(executor_result=_make_ok_executor())
    result = _apply_build_failure_override(decision, chain)
    assert result.verdict == Verdict.COMPLETE


def test_override_applied_when_build_failed_with_complete():
    """핵심 케이스 — verdict=COMPLETE + build 실패 → BLOCKED(BUILD_FAILED)."""
    from src.agents.c_level.convergence_judge import BlockedCause, Verdict
    from src.workflows.iterative_loop import _apply_build_failure_override

    decision = _make_decision(Verdict.COMPLETE)
    chain = _make_chain_result(
        executor_result=_make_failed_executor(
            exit_code=-7,
            error="적합한 entry .py 파일 없음 — LLM 산출 코드 점검 필요.\nreason: ⚠ no valid entry",
        )
    )
    result = _apply_build_failure_override(decision, chain)
    assert result.verdict == Verdict.BLOCKED
    assert result.blocked_cause == BlockedCause.BUILD_FAILED
    # reason 에 exit code + error 첫 줄 포함
    assert "-7" in result.reason
    assert "적합한 entry" in result.reason
    # next_action 이 사용자 안내
    assert "재실행" in result.next_action or "executor_result" in result.next_action


# ---------------------------------------------------------------------------
# 3. _node_judge_convergence 통합 — build 실패 → BLOCKED override
# ---------------------------------------------------------------------------


def test_node_judge_convergence_applies_build_override():
    """_node_judge_convergence 가 chain_result 의 executor 실패를 반영."""
    from src.agents.c_level.convergence_judge import (
        BlockedCause,
        GapReport,
        Verdict,
    )
    from src.workflows.iterative_loop import _node_judge_convergence

    # GapReport: must_fix=0 → judge_convergence 가 COMPLETE 반환
    gap = GapReport(
        satisfied_count=5,
        unsatisfied_blockers=0,
        unsatisfied_majors=0,
        unsatisfied_minors=0,
        ambiguous_count=0,
        stagnation=False,
        iteration=1,
    )
    chain_result = _make_chain_result(
        executor_result=_make_failed_executor()
    )
    state = {
        "gap_report": gap,
        "chain_result": chain_result,
        "max_iterations": 5,
        "budget_tokens_remaining": -1,
    }
    out = _node_judge_convergence(state)
    decision = out["decision"]
    # build 실패로 verdict=BLOCKED override 적용
    assert decision.verdict == Verdict.BLOCKED
    assert decision.blocked_cause == BlockedCause.BUILD_FAILED


def test_node_judge_convergence_preserves_complete_when_build_ok():
    """build 성공 → COMPLETE 유지 (회귀 차단)."""
    from src.agents.c_level.convergence_judge import GapReport, Verdict
    from src.workflows.iterative_loop import _node_judge_convergence

    gap = GapReport(
        satisfied_count=5,
        unsatisfied_blockers=0,
        unsatisfied_majors=0,
        unsatisfied_minors=0,
        ambiguous_count=0,
        stagnation=False,
        iteration=1,
    )
    chain_result = _make_chain_result(executor_result=_make_ok_executor())
    state = {
        "gap_report": gap,
        "chain_result": chain_result,
        "max_iterations": 5,
        "budget_tokens_remaining": -1,
    }
    out = _node_judge_convergence(state)
    assert out["decision"].verdict == Verdict.COMPLETE


# ---------------------------------------------------------------------------
# 4. _format_build_skipped_line 3 분기
# ---------------------------------------------------------------------------


def test_format_build_skipped_line_executor_none(run_mod):
    """executor_result=None → '(build 미실행 — enable_executor=False)'."""
    line = run_mod._format_build_skipped_line(None)
    assert "build 미실행" in line
    assert "enable_executor" in line


def test_format_build_skipped_line_success_false(run_mod):
    """success=False → 'SKIPPED — exit=<N> reason=<first line>'."""
    er = _make_failed_executor(
        exit_code=-7,
        error="적합한 entry .py 파일 없음 — LLM 산출 코드 점검 필요.\n자세한 내용 ...",
    )
    line = run_mod._format_build_skipped_line(er)
    assert "SKIPPED" in line
    assert "-7" in line
    assert "적합한 entry" in line
    # 첫 줄만 출력 (다음 줄 미포함)
    assert "자세한 내용" not in line


def test_format_build_skipped_line_success_true_no_exe(run_mod):
    """success=True 인데 exe_path 부재 (비정상 케이스) → 산출 메타 부재 안내."""
    er = SimpleNamespace(success=True, exit_code=0, error_message=None, exe_path=None)
    line = run_mod._format_build_skipped_line(er)
    assert "exe" in line.lower() or "메타" in line


# ---------------------------------------------------------------------------
# 5. _print_result_summary — exe_path=None 시 SKIPPED 진단 출력 (capsys)
# ---------------------------------------------------------------------------


def test_print_result_summary_emits_skipped_when_executor_failed(run_mod, capsys):
    """결과 패널이 SKIPPED reason 을 출력 (PM 디버깅 가능)."""
    er = _make_failed_executor(
        exit_code=-7,
        error="적합한 entry .py 파일 없음 — LLM 산출 코드 점검 필요.",
    )
    run_mod._print_result_summary(
        track="A",
        elapsed_sec=120.0,
        outputs_dir=Path("/tmp/outputs"),
        exe_path=None,
        release_url=None,
        iterative_summary="verdict=BLOCKED iterations=1/1",
        executor_result=er,
    )
    captured = capsys.readouterr().out
    assert "SKIPPED" in captured
    assert "-7" in captured
    # iterative summary 도 정상 표시
    assert "BLOCKED" in captured


def test_print_result_summary_emits_not_run_when_executor_none(run_mod, capsys):
    """executor_result=None 일 때 '(build 미실행)' 표시."""
    run_mod._print_result_summary(
        track="A",
        elapsed_sec=10.0,
        outputs_dir=Path("/tmp/outputs"),
        exe_path=None,
        release_url=None,
        executor_result=None,
    )
    captured = capsys.readouterr().out
    assert "build 미실행" in captured


def test_print_result_summary_skips_skipped_line_when_exe_exists(
    run_mod, capsys, tmp_path
):
    """exe_path 가 실제 존재 → SKIPPED 라인 미출력 (회귀 차단)."""
    exe = tmp_path / "App.exe"
    exe.write_bytes(b"x" * 1024)  # 1 KB dummy
    er = _make_ok_executor(exe_path=exe)
    run_mod._print_result_summary(
        track="A",
        elapsed_sec=120.0,
        outputs_dir=tmp_path,
        exe_path=exe,
        release_url=None,
        executor_result=er,
    )
    captured = capsys.readouterr().out
    assert "SKIPPED" not in captured
    assert "build 미실행" not in captured
    # 정상 .exe 라인 표시
    assert "App.exe" in captured
    assert "MB" in captured


# ---------------------------------------------------------------------------
# 6. file-text — Track A/B caller 가 executor_result 전달 (회귀 차단)
# ---------------------------------------------------------------------------


def test_run_py_track_a_passes_executor_result():
    """scripts/run.py Track A 가 _print_result_summary 에 executor_result 전달."""
    text = RUN_PY.read_text(encoding="utf-8")
    # Track A _print_result_summary 호출에 executor_result kwarg
    track_a_section = text.split('"A", elapsed', 1)
    assert len(track_a_section) == 2
    # 첫 호출 (Track A) 바로 뒤에 executor_result= 가 들어 있어야 함
    track_a_call = track_a_section[1][:600]
    assert "executor_result=" in track_a_call


def test_run_py_track_b_passes_executor_result():
    """scripts/run.py Track B 가 _print_result_summary 에 executor_result 전달."""
    text = RUN_PY.read_text(encoding="utf-8")
    # Track B _print_result_summary 호출 ("B", ...) 직후에 executor_result kwarg
    assert text.count("executor_result=getattr(result, \"executor_result\", None)") >= 2
