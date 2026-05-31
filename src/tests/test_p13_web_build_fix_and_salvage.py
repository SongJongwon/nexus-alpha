# -*- coding: utf-8 -*-
"""P13 web 빌드 자가수정 강화 + vite-only salvage 우회 회귀 test (v13 Phase 6.E).

배경(P12 후속): build 실패→must_fix→재빌드 루프는 발동하나, 코드젠이 TS2345 류 타입
에러를 5 iter 내내 못 고쳐 ITERATION_CAP. 원인: (1) 되먹이는 must_fix 가 "에러 원문"만이라
막연, (2) 코드 산출 단축(42-char) 정황.

처방:
    수정1 — 피드백에 *구체적 수정 지시* 동봉 (_ts_fix_hint / _format_build_errors_with_hints):
        TS2345/TS2322/TS18046 등 → 명시적 타입 주석 또는 as 캐스트. 일반 TS → 최소 타입 레벨 변경.
        + "해당 파일 전체 패치 결과를 빠짐없이 반환(요약/축약 금지)" directive.
    수정2 — vite-only salvage (_is_type_only_failure / _maybe_salvage_web_build +
        build_workflow._default_vite_salvage_runner / _run_web_build(vite_only=True)):
        예산 소진 BLOCKED(BUILD_FAILED) 가 *타입체크 전용* 실패면 vite-only(tsc 게이트 제외)
        1회 빌드 → dist/ 산출 시 COMPLETE(타입경고 첨부). 번들/설치/런타임 실패는 BLOCKED 유지.

스코프: web-scoped (_is_web_build_result 게이트, desktop/Track A·B/python-only 불변).
검증: P13-T1~T13. 회귀 0.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.workflows.build_workflow as bw
from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
)
from src.workflows.build_workflow import _default_vite_salvage_runner, _run_web_build
from src.workflows.iterative_loop import (
    _apply_build_failure_override,
    _format_build_errors_with_hints,
    _is_type_only_failure,
    _maybe_salvage_web_build,
    _ts_fix_hint,
)

_TSC_ONLY = (
    "src/viewer.ts(42,10): error TS2345: Argument of type 'unknown' is not "
    "assignable to parameter of type 'Object3D'.\n"
    "src/state.ts(8,3): error TS18046: 'model' is of type 'unknown'.\n"
)
_TSC_PLUS_BUNDLE = (
    _TSC_ONLY + '[vite]: Rollup failed to resolve import "three" from "src/main.ts".\n'
)


def _web_exec(stderr: str, *, exit_code: int = -8, command=("npm", "ci")):
    return SimpleNamespace(
        success=False, exit_code=exit_code, exe_path=None,
        error_message="web build 실패 또는 dist/ 미생성.", stderr=stderr, command=list(command),
    )


def _chain(executor_result, *, code_files=None, saved_dir="/tmp/wf"):
    return SimpleNamespace(
        executor_result=executor_result, saved_code_files=code_files or [], saved_dir=saved_dir
    )


def _blocked_bf() -> JudgmentDecision:
    return JudgmentDecision(
        verdict=Verdict.BLOCKED, blocked_cause=BlockedCause.BUILD_FAILED,
        reason="WEB_BUILD_FAILED — 예산 소진", next_action="...", must_fix_count=1,
    )


# =============================================================================
# P13-T1. _ts_fix_hint — TS 코드별 수정 지시
# =============================================================================
class TestT1TsFixHint:
    def test_assignability_codes_suggest_cast(self) -> None:
        assert "캐스트" in _ts_fix_hint("src/x.ts(1,1): error TS2345: not assignable")
        assert "캐스트" in _ts_fix_hint("error TS18046: 'x' is of type 'unknown'")
        assert "캐스트" in _ts_fix_hint("error TS2322: Type X not assignable to Y")

    def test_generic_ts_suggests_minimal(self) -> None:
        hint = _ts_fix_hint("src/x.ts(2,2): error TS1005: ';' expected")
        assert "최소 타입 레벨" in hint

    def test_non_ts_empty(self) -> None:
        assert _ts_fix_hint("[vite]: Rollup failed to resolve import") == ""


# =============================================================================
# P13-T2. _format_build_errors_with_hints — 에러 + 수정지시 block
# =============================================================================
class TestT2FormatWithHints:
    def test_hints_appended(self) -> None:
        out = _format_build_errors_with_hints(
            ["src/x.ts(1,1): error TS2345: bad"], "fallback"
        )
        assert "TS2345" in out and "→ 수정:" in out

    def test_empty_uses_fallback(self) -> None:
        assert _format_build_errors_with_hints([], "fallback line") == "  - fallback line"


# =============================================================================
# P13-T3. override IMPROVE — 수정지시 + 전체파일 반환 directive 동봉
# =============================================================================
class TestT3OverrideImproveDirectives:
    def test_improve_next_action_has_hint_and_full_file_directive(self) -> None:
        complete = JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "ok", "ok", 0)
        res = _apply_build_failure_override(
            complete, _chain(_web_exec(_TSC_ONLY)), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res.verdict == Verdict.IMPROVE_NEEDED
        assert "→ 수정:" in res.next_action  # 구체 수정 지시
        assert "빠짐없이 반환" in res.next_action  # 전체 파일 반환 (요약/축약 금지)
        assert "TS2345" in res.next_action


# =============================================================================
# P13-T4. _is_type_only_failure — 타입전용 판정
# =============================================================================
class TestT4IsTypeOnlyFailure:
    def test_tsc_only_is_type_only(self) -> None:
        assert _is_type_only_failure(_TSC_ONLY) is True

    def test_tsc_plus_bundle_not_type_only(self) -> None:
        assert _is_type_only_failure(_TSC_PLUS_BUNDLE) is False  # rollup resolve 섞임

    def test_npm_err_not_type_only(self) -> None:
        assert _is_type_only_failure(
            "npm ERR! code ELIFECYCLE\nsrc/x.ts(1,1): error TS2345: x"
        ) is False

    def test_no_tsc_not_type_only(self) -> None:
        assert _is_type_only_failure("그냥 로그, TS 에러 없음") is False
        assert _is_type_only_failure("") is False


# =============================================================================
# P13-T5. _default_vite_salvage_runner — vite build (tsc 게이트 제외)
# =============================================================================
class TestT5ViteSalvageRunner:
    def test_runs_vite_build_not_npm_run_build(self, tmp_path: Path, monkeypatch) -> None:
        import shutil

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(shutil, "which", lambda n: "npm")
        monkeypatch.setattr(bw.subprocess, "run", fake_run)
        ok, log, elapsed = _default_vite_salvage_runner(tmp_path, 60)
        assert ok is True
        # vite build 실행 (npm run build = tsc && vite build 아님)
        assert any("vite" in c and "build" in c for c in calls)
        assert not any(("run" in c and "build" in c) for c in calls)
        # 설치는 --legacy-peer-deps 일관 (P11)
        assert any("--legacy-peer-deps" in c for c in calls)

    def test_npm_missing_graceful(self, tmp_path: Path, monkeypatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda n: None)
        ok, log, _ = _default_vite_salvage_runner(tmp_path, 60)
        assert ok is False and "salvage 불가" in log


# =============================================================================
# P13-T6. salvage 성공 → COMPLETE (타입경고 첨부)
# =============================================================================
class TestT6SalvageToComplete:
    def test_type_only_salvage_completes(self) -> None:
        calls: list = []

        def fake_salvage(code_files, saved_dir):
            calls.append((code_files, saved_dir))
            return True

        res = _maybe_salvage_web_build(
            _blocked_bf(), _chain(_web_exec(_TSC_ONLY)), salvage_fn=fake_salvage
        )
        assert res.verdict == Verdict.COMPLETE
        assert res.blocked_cause == BlockedCause.NONE
        assert "SALVAGED" in res.reason
        assert "TS2345" in res.next_action  # 타입 경고 첨부
        assert res.must_fix_count == 0
        assert calls  # salvage 시도됨


# =============================================================================
# P13-T7. salvage 실패 → BLOCKED 유지
# =============================================================================
class TestT7SalvageFailStaysBlocked:
    def test_salvage_fail_keeps_blocked(self) -> None:
        res = _maybe_salvage_web_build(
            _blocked_bf(), _chain(_web_exec(_TSC_ONLY)), salvage_fn=lambda c, s: False
        )
        assert res.verdict == Verdict.BLOCKED
        assert res.blocked_cause == BlockedCause.BUILD_FAILED


# =============================================================================
# P13-T8. 번들/설치 에러 → salvage 미발동, BLOCKED 유지
# =============================================================================
class TestT8BundleErrorNoSalvage:
    def test_bundle_error_not_salvaged(self) -> None:
        called = {"n": 0}

        def fake(c, s):
            called["n"] += 1
            return True

        res = _maybe_salvage_web_build(
            _blocked_bf(), _chain(_web_exec(_TSC_PLUS_BUNDLE)), salvage_fn=fake
        )
        assert res.verdict == Verdict.BLOCKED  # 실제 번들 실패 → 유지
        assert called["n"] == 0  # salvage 미호출


# =============================================================================
# P13-T9. desktop / 비-web → salvage 미발동 (web-scoped)
# =============================================================================
class TestT9DesktopNoSalvage:
    def test_desktop_blocked_not_salvaged(self) -> None:
        desktop = SimpleNamespace(
            success=False, exit_code=1, exe_path=None, error_message="PyInstaller 실패",
            stderr="src/x.ts(1,1): error TS2345: x",  # TS 가 있어도 desktop 이면 무시
            command=["pyinstaller", "app.py"],
        )
        res = _maybe_salvage_web_build(
            _blocked_bf(), _chain(desktop), salvage_fn=lambda c, s: True
        )
        assert res.verdict == Verdict.BLOCKED  # web-scoped — desktop 불변


# =============================================================================
# P13-T10. 비-BLOCKED verdict → salvage no-op
# =============================================================================
class TestT10NonBlockedNoop:
    def test_complete_unchanged(self) -> None:
        complete = JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "x", "x", 0)
        res = _maybe_salvage_web_build(
            complete, _chain(_web_exec(_TSC_ONLY)), salvage_fn=lambda c, s: True
        )
        assert res is complete

    def test_improve_unchanged(self) -> None:
        improve = JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "x", "x", 1)
        res = _maybe_salvage_web_build(
            improve, _chain(_web_exec(_TSC_ONLY)), salvage_fn=lambda c, s: True
        )
        assert res is improve


# =============================================================================
# P13-T11. _run_web_build(vite_only=True) — dist/ 인정 (injected runner)
# =============================================================================
class TestT11RunWebBuildViteOnly:
    def test_vite_only_dist_recognized(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()

        def fake(cd: Path, timeout: int):
            (cd / "dist").mkdir(parents=True, exist_ok=True)
            (cd / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            return True, "vite build ok", 1.0

        res = _run_web_build(
            [code_dir / "vite.config.ts"], tmp_path, npm_runner=fake, vite_only=True
        )
        assert res.success is True
        assert res.exe_path is not None and res.exe_path.name == "index.html"


# =============================================================================
# P13-T12. 회귀 — desktop override 경로 불변 (P12 보존)
# =============================================================================
class TestT12DesktopOverrideUnchanged:
    def test_desktop_build_failure_terminal_blocked(self) -> None:
        desktop = SimpleNamespace(
            success=False, exit_code=1, exe_path=None,
            error_message="PyInstaller 실패: Invalid hiddenimport", stderr="", command=["pyinstaller", "app.py"],
        )
        complete = JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "ok", "ok", 0)
        res = _apply_build_failure_override(
            complete, _chain(desktop), gap=GapReport(iteration=1), max_iterations=5
        )
        assert res.verdict == Verdict.BLOCKED
        assert res.blocked_cause == BlockedCause.BUILD_FAILED
        assert "PyInstaller" in res.reason  # desktop 메시지 경로 불변


# =============================================================================
# P13-T13. 회귀 — web cap BLOCKED 가 type-only 면 후속 salvage 로 COMPLETE 가능 (통합)
# =============================================================================
class TestT13CapThenSalvageIntegration:
    def test_override_cap_blocked_then_salvage_completes(self) -> None:
        # 1) override: web 빌드 실패 + cap(iter5/5) → BLOCKED(BUILD_FAILED)
        complete = JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "ok", "ok", 0)
        chain = _chain(_web_exec(_TSC_ONLY))
        blocked = _apply_build_failure_override(
            complete, chain, gap=GapReport(iteration=5), max_iterations=5
        )
        assert blocked.verdict == Verdict.BLOCKED
        assert blocked.blocked_cause == BlockedCause.BUILD_FAILED
        # 2) salvage: type-only → vite-only 성공 시 COMPLETE
        salvaged = _maybe_salvage_web_build(blocked, chain, salvage_fn=lambda c, s: True)
        assert salvaged.verdict == Verdict.COMPLETE
        assert "SALVAGED" in salvaged.reason
