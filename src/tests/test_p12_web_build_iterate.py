# -*- coding: utf-8 -*-
"""P12 web 빌드 실패 자가수정 루프 회귀 test (v13 Phase 6.E).

배경 (P7~P11 후속): web 타깃이 npm/vite 빌드에 실패하면 Gap Analyst 가 COMPLETE 여도
``_apply_build_failure_override`` 가 즉시 terminal BLOCKED(BUILD_FAILED)로 강등 → 자가수정
기회 없이 종료. P12: web 빌드 실패를 iterate 루프로 되먹여 GUI Code Generator 가 빌드
에러를 패치하고 다음 iteration 에서 재빌드하게 한다 (예산 소진 시에만 BLOCKED).

처방:
    - _parse_web_build_errors: tsc(file(line,col): error TSxxxx) + vite/esbuild 에러 파싱.
    - _is_web_build_result: command[0]=='npm' 또는 exit_code==-8 → web (desktop 구분).
    - _apply_build_failure_override: web 빌드 실패 + 예산(iter<max) → IMPROVE_NEEDED + 에러를
      next_action(=feedback) 에 must-fix 주입. cap → BLOCKED(BUILD_FAILED) + 마지막 에러.
      desktop(PyInstaller) 은 기존 BLOCKED 경로 불변 (web-scoped).

검증: P12-T1~T10. 회귀 0.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
)
from src.workflows.iterative_loop import (
    _apply_build_failure_override,
    _format_feedback_for_next_iteration,
    _is_web_build_result,
    _parse_web_build_errors,
)

_TSC_STDERR = (
    "src/viewer.ts(42,10): error TS2304: Cannot find name 'Foo'.\n"
    "src/main.ts(8,3): error TS2554: Expected 1 arguments, but got 0.\n"
)
_VITE_STDERR = (
    "error during build:\n"
    '[vite]: Rollup failed to resolve import "three" from "src/main.ts".\n'
    "src/main.ts:5:0: ERROR: Could not resolve './missing'\n"
)


def _web_exec(stderr: str, *, exit_code: int = -8, command=("npm", "ci", "&&", "npm", "run", "build")):
    return SimpleNamespace(
        success=False,
        exit_code=exit_code,
        exe_path=None,
        error_message="web build 실패 또는 dist/ 미생성. npm 미설치/빌드 에러 가능.",
        stderr=stderr,
        command=list(command),
    )


def _chain(executor_result):
    return SimpleNamespace(executor_result=executor_result)


def _complete(must_fix: int = 0) -> JudgmentDecision:
    return JudgmentDecision(
        verdict=Verdict.COMPLETE,
        blocked_cause=BlockedCause.NONE,
        reason="ok",
        next_action="ok",
        must_fix_count=must_fix,
    )


# =============================================================================
# P12-T1. tsc 에러 파싱
# =============================================================================
class TestT1ParseTsc:
    def test_tsc_errors_parsed(self) -> None:
        errs = _parse_web_build_errors(_TSC_STDERR)
        assert any("src/viewer.ts(42,10)" in e and "TS2304" in e for e in errs)
        assert any("src/main.ts(8,3)" in e and "TS2554" in e for e in errs)


# =============================================================================
# P12-T2. vite/esbuild 에러 파싱
# =============================================================================
class TestT2ParseVite:
    def test_vite_errors_parsed(self) -> None:
        errs = _parse_web_build_errors(_VITE_STDERR)
        assert errs  # 비어있지 않음
        assert any("main.ts" in e or "resolve" in e.lower() for e in errs)

    def test_empty_returns_empty(self) -> None:
        assert _parse_web_build_errors("") == []
        assert _parse_web_build_errors("그냥 평범한 로그 한 줄") == []


# =============================================================================
# P12-T3. web 빌드 결과 판정 (desktop 구분)
# =============================================================================
class TestT3IsWebBuildResult:
    def test_npm_command_is_web(self) -> None:
        assert _is_web_build_result(SimpleNamespace(command=["npm", "ci"], exit_code=-8)) is True

    def test_exit_minus8_is_web(self) -> None:
        assert _is_web_build_result(SimpleNamespace(command=[], exit_code=-8)) is True

    def test_pyinstaller_is_not_web(self) -> None:
        assert _is_web_build_result(SimpleNamespace(command=["pyinstaller", "app.py"], exit_code=1)) is False
        assert _is_web_build_result(SimpleNamespace(command=[], exit_code=-7)) is False


# =============================================================================
# P12-T4. web 빌드 실패 + 예산 남음 → IMPROVE_NEEDED + 에러 must-fix 주입
# =============================================================================
class TestT4WebFailBudgetImprove:
    def test_improve_with_errors(self) -> None:
        res = _apply_build_failure_override(
            _complete(), _chain(_web_exec(_TSC_STDERR)), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res.verdict == Verdict.IMPROVE_NEEDED
        assert res.blocked_cause == BlockedCause.NONE
        # 빌드 에러가 next_action(=feedback) 에 file:line+메시지로 주입
        assert "TS2304" in res.next_action
        assert "src/viewer.ts(42,10)" in res.next_action
        assert res.must_fix_count >= 1


# =============================================================================
# P12-T5. web 빌드 실패 + 예산 소진(cap) → BLOCKED(BUILD_FAILED) + 마지막 에러
# =============================================================================
class TestT5WebFailCapBlocked:
    def test_blocked_at_cap_with_last_error(self) -> None:
        res = _apply_build_failure_override(
            _complete(), _chain(_web_exec(_TSC_STDERR)), gap=GapReport(iteration=5), max_iterations=5
        )
        assert res.verdict == Verdict.BLOCKED
        assert res.blocked_cause == BlockedCause.BUILD_FAILED
        assert "예산 소진" in res.reason
        assert "TS2304" in res.next_action  # 마지막 빌드 에러 첨부


# =============================================================================
# P12-T6. desktop(PyInstaller) 빌드 실패 → 기존 BLOCKED 불변 (회귀 0)
# =============================================================================
class TestT6DesktopUnchanged:
    def test_pyinstaller_failure_still_terminal_blocked(self) -> None:
        desktop = SimpleNamespace(
            success=False,
            exit_code=1,
            exe_path=None,
            error_message="PyInstaller 실패: Invalid hiddenimport",
            stderr="ERROR: ...",
            command=["pyinstaller", "app.py"],
        )
        # 예산이 남아도(iter=1) desktop 은 루프백 안 함 — terminal BLOCKED 유지
        res = _apply_build_failure_override(
            _complete(), _chain(desktop), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res.verdict == Verdict.BLOCKED
        assert res.blocked_cause == BlockedCause.BUILD_FAILED
        assert "PyInstaller" in res.reason  # 기존 desktop 메시지 경로


# =============================================================================
# P12-T7. build 성공 → COMPLETE 통과 (override no-op)
# =============================================================================
class TestT7BuildSuccessPassthrough:
    def test_success_keeps_complete(self) -> None:
        ok = SimpleNamespace(
            success=True, exit_code=0, exe_path=Path("dist/index.html"),
            command=["npm"], stderr="", error_message=None,
        )
        res = _apply_build_failure_override(
            _complete(), _chain(ok), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res.verdict == Verdict.COMPLETE


# =============================================================================
# P12-T8. 비-COMPLETE verdict → override no-op (원본 그대로)
# =============================================================================
class TestT8NonCompleteNoop:
    def test_improve_input_unchanged(self) -> None:
        improve = JudgmentDecision(
            verdict=Verdict.IMPROVE_NEEDED, blocked_cause=BlockedCause.NONE,
            reason="x", next_action="x", must_fix_count=2,
        )
        res = _apply_build_failure_override(
            improve, _chain(_web_exec(_TSC_STDERR)), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res is improve


# =============================================================================
# P12-T9. feedback 가 빌드 에러를 표면화 (next_action → feedback)
# =============================================================================
class TestT9FeedbackSurfacesErrors:
    def test_feedback_includes_build_errors(self) -> None:
        res = _apply_build_failure_override(
            _complete(), _chain(_web_exec(_VITE_STDERR)), gap=GapReport(iteration=2), max_iterations=5
        )
        fb = _format_feedback_for_next_iteration(
            GapReport(iteration=2, unsatisfied_blockers=1), res
        )
        assert "must-fix" in fb or "must_fix" in fb.lower()
        # vite 에러가 feedback 본문에 등장 (Convergence Judge 권고 = next_action 경유)
        assert "main.ts" in fb or "resolve" in fb.lower()


# =============================================================================
# P12-T10. 파싱 가능한 에러 없음 → error_message 폴백으로 IMPROVE (예산 남음)
# =============================================================================
class TestT10NoParseableFallback:
    def test_opaque_error_falls_back_to_message(self) -> None:
        res = _apply_build_failure_override(
            _complete(),
            _chain(_web_exec("npm ERR! code ELIFECYCLE\nnpm ERR! exit 1")),
            gap=GapReport(iteration=1),
            max_iterations=5,
        )
        assert res.verdict == Verdict.IMPROVE_NEEDED
        assert res.must_fix_count >= 1
        # 폴백: error_message 첫 줄이 next_action 에 포함
        assert "web build 실패" in res.next_action
