# -*- coding: utf-8 -*-
"""v13 P23 — 데스크탑 .exe 런타임 스모크 게이트 회귀 test.

빌드된 .exe 를 판정 직전에 잠깐 띄워 크래시/치명 에러를 검출하고, FAIL 이면 COMPLETE 를 차단 +
에러를 다음 iteration must-fix 로 주입한다. P17(web 시각 QA)의 데스크탑 대응물.

검증:
  - _combine_smoke_verdict: CRASH/SILENT_FAIL/SPAWN_ERROR → FAIL, PASS+오류창/에러출력 → FAIL,
    PASS 무신호 → PASS, 알 수 없는 verdict → SKIPPED.
  - run_desktop_smoke_gate: PASS / FAIL(crash) / SKIPPED(.exe 미존재) / 예외 graceful / 오류창 감지.
  - _apply_smoke_failure_override: COMPLETE+FAIL → IMPROVE(예산 남음)/BLOCKED(소진) + 에러 must-fix,
    PASS/None/non-COMPLETE → 원본 유지 (회귀 0).
  - _run_desktop_smoke_gate(node): desktop .exe → smoke_result, web/none/빌드실패/.exe미존재/OFF → no-op {}.
  - 모두 subprocess/창 mock — CI(ubuntu)에서 실 .exe 없이 green.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.runtime_verification.desktop_smoke_gate import (  # noqa: E402
    DesktopSmokeResult,
    _combine_smoke_verdict,
    _match_error_window,
    run_desktop_smoke_gate,
)
from src.workflows import iterative_loop as IL  # noqa: E402


def _rt(verdict: str, *, exit_code=None, stderr: str = "", stdout: str = "", error_trace: str = ""):
    """RuntimeTestResult 형태 fake (getattr 기반 소비라 SimpleNamespace 로 충분)."""
    return SimpleNamespace(
        verdict=verdict, exit_code=exit_code, stderr=stderr, stdout=stdout, error_trace=error_trace
    )


def _make_fake_exe(tmp_path: Path, name: str = "ErpApp.exe") -> Path:
    exe = tmp_path / name
    exe.write_bytes(b"")
    return exe


# =============================================================================
# 1. _combine_smoke_verdict (순수 verdict 결합)
# =============================================================================
class TestCombineSmokeVerdict:
    def test_crash_exit_nonzero_is_fail(self) -> None:
        rt = _rt("CRASH", exit_code=1, stderr="OperationalError: no such column: active")
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "FAIL" and r.signal == "exit"
        assert "OperationalError" in r.error_excerpt

    def test_silent_fail_exit_zero_clean_is_skipped(self) -> None:
        """v13 P23 review fix — exit 0 즉시 종료 + 에러 출력 없음 → SKIPPED (CLI/단발 정상 가능,
        거짓 BLOCKED 회피). FAIL 아님."""
        rt = _rt("SILENT_FAIL", exit_code=0)
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "SKIPPED" and r.signal == "skipped"

    def test_silent_fail_with_error_output_is_fail(self) -> None:
        """exit 0 즉시 종료라도 stderr 에 에러 패턴이 있으면 FAIL."""
        rt = _rt("SILENT_FAIL", exit_code=0, stderr="Traceback ... OperationalError: no such column")
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "FAIL" and r.signal == "silent"

    def test_spawn_error_is_fail(self) -> None:
        rt = _rt("SPAWN_ERROR", stderr="Permission denied")
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "FAIL" and r.signal == "spawn"

    def test_pass_alive_no_signal_is_pass(self) -> None:
        rt = _rt("PASS", exit_code=None)
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "PASS" and r.signal == "alive"
        assert r.survived_sec == 8.0

    def test_pass_alive_with_error_window_is_fail(self) -> None:
        rt = _rt("PASS")
        r = _combine_smoke_verdict(rt, "치명적 오류 - ERP", timeout_sec=8)
        assert r.verdict == "FAIL" and r.signal == "window"
        assert r.window_title_hit == "치명적 오류 - ERP"

    def test_pass_alive_with_error_output_is_fail(self) -> None:
        rt = _rt("PASS", stderr="Traceback (most recent call last): ... OperationalError")
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "FAIL" and r.signal == "stderr"

    def test_unknown_verdict_is_skipped(self) -> None:
        rt = _rt("WEIRD")
        r = _combine_smoke_verdict(rt, "", timeout_sec=8)
        assert r.verdict == "SKIPPED"

    def test_pass_with_benign_error_text_is_not_fail(self) -> None:
        """v13 P23 review fix — 정상 출력의 'error' 단어가 거짓 FAIL 을 만들지 않음(정밀 regex).
        '0 errors found' / '오류 없음' / 'terror' / 'Error Console' 등은 PASS 유지."""
        for benign in ("0 errors found", "오류 없음", "terror game running", "Error Console ready",
                       "errorless mode on"):
            rt = _rt("PASS", stdout=benign)
            r = _combine_smoke_verdict(rt, "", timeout_sec=8)
            assert r.verdict == "PASS", f"benign 출력 오탐: {benign!r} → {r.verdict}"

    def test_pass_with_real_camelcase_exception_is_fail(self) -> None:
        """실제 CamelCase 예외(OperationalError/FooException)는 PASS 라도 FAIL 로 잡힘."""
        for real in ("OperationalError: no such column: active", "raise FooException('x')"):
            rt = _rt("PASS", stderr=real)
            r = _combine_smoke_verdict(rt, "", timeout_sec=8)
            assert r.verdict == "FAIL" and r.signal == "stderr", real


class TestMatchErrorWindow:
    def test_matches_korean_and_english_error_titles(self) -> None:
        assert _match_error_window(["치명적 오류"]) == "치명적 오류"
        assert _match_error_window(["Fatal Error"]) == "Fatal Error"
        assert _match_error_window(["Unhandled Exception"]) == "Unhandled Exception"

    def test_ignores_benign_titles(self) -> None:
        assert _match_error_window(["칸반 보드", "메모장", "Calculator"]) == ""

    def test_word_boundary_avoids_substring_falsepos(self) -> None:
        """v13 P23 review fix — 'Mirror'/'Terror' 같은 부분문자열은 매칭 안 함(단어경계)."""
        assert _match_error_window(["Mirror Edit", "Terror Game", "Errorless"]) == ""

    def test_benign_error_console_whitelisted(self) -> None:
        """v13 P23 review fix — 'Error Console/List/Log' 등 정상 개발도구 창은 제외."""
        assert _match_error_window(["Error Console", "JavaScript Error List"]) == ""
        # 단, 실제 오류 다이얼로그는 여전히 잡힘
        assert _match_error_window(["Application Error"]) == "Application Error"


class TestScopedErrorWindow:
    """v13 P23 live-fix v2 (review #4) — 실제 _scoped_error_window 의 창→PID 귀속·필터 로직 검증
    (가짜 win32gui/win32process 주입 — 결정론·크로스플랫폼)."""

    def _run(self, monkeypatch, pid_set, wins):
        """wins: [(hwnd, visible, pid, title)]. fake win32 으로 _scoped_error_window 호출."""
        import src.agents.runtime_verification.desktop_smoke_gate as M

        monkeypatch.setattr(M.sys, "platform", "win32")
        fake_gui = MagicMock()
        fake_gui.IsWindowVisible = lambda h: next(w[1] for w in wins if w[0] == h)
        fake_gui.GetWindowText = lambda h: next(w[3] for w in wins if w[0] == h)
        fake_gui.EnumWindows = lambda cb, ctx: [cb(w[0], ctx) for w in wins]
        fake_proc = MagicMock()
        fake_proc.GetWindowThreadProcessId = lambda h: (0, next(w[2] for w in wins if w[0] == h))
        with patch.dict("sys.modules", {"win32gui": fake_gui, "win32process": fake_proc}):
            return M._scoped_error_window(pid_set)

    def test_matches_only_owned_visible_error_window(self, monkeypatch) -> None:
        wins = [
            (1, True, 100, "정상 메인창"),            # owned, 정상 → 무시
            (2, True, 100, "치명적 오류 - DB"),        # owned + error → 매치
            (3, True, 999, "Application Error"),       # 다른 PID + error → 무시(스코핑)
            (4, False, 100, "치명적 오류 숨김"),        # owned + error 지만 invisible → 무시
        ]
        assert self._run(monkeypatch, {100}, wins) == "치명적 오류 - DB"

    def test_unowned_error_window_ignored(self, monkeypatch) -> None:
        """우리 Job 멤버(pid_set)에 없는 PID 의 오류창은 무시 → "" (stray false-FAIL 근절)."""
        wins = [(3, True, 999, "Application Error")]
        assert self._run(monkeypatch, {100, 101}, wins) == ""

    def test_owned_benign_title_ignored(self, monkeypatch) -> None:
        wins = [(2, True, 100, "Error Console")]  # owned 지만 benign → 무시
        assert self._run(monkeypatch, {100}, wins) == ""

    def test_owned_invisible_error_window_ignored(self, monkeypatch) -> None:
        """가시성 필터 discriminate — owned + error 지만 invisible 창은 무시 → ""."""
        wins = [(4, False, 100, "Application Error")]  # owned + error 이나 invisible
        assert self._run(monkeypatch, {100}, wins) == ""


# =============================================================================
# 2. run_desktop_smoke_gate (orchestration — subprocess/창 주입)
# =============================================================================
def _fake_runtime(verdict: str, *, sleep: float = 0.0, pid: int = 1234, owned=None, **rt_kw):
    """run_exe_runtime_test 스텁 — on_spawn(pid, owned_pids_fn) 통지 + (선택) sleep 후 verdict."""
    owned_set = set(owned) if owned is not None else {pid}

    def _fn(p, timeout_sec, on_spawn=None):
        if on_spawn is not None:
            on_spawn(pid, lambda: owned_set)
        if sleep:
            import time as _t

            _t.sleep(sleep)
        return _rt(verdict, **rt_kw)

    return _fn


class TestRunDesktopSmokeGate:
    def test_pass_when_runtime_alive(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        r = run_desktop_smoke_gate(
            exe, timeout_sec=0.2, settle_sec=0.0,
            _runtime_test=_fake_runtime("PASS"), _error_window_probe=lambda pids: "",
        )
        assert r.verdict == "PASS"

    def test_fail_when_runtime_crash(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        r = run_desktop_smoke_gate(
            exe, timeout_sec=0.2, settle_sec=0.0,
            _runtime_test=_fake_runtime("CRASH", exit_code=3, stderr="boom"),
            _error_window_probe=lambda pids: "",
        )
        assert r.verdict == "FAIL" and r.exit_code == 3

    def test_skipped_when_exe_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.exe"
        r = run_desktop_smoke_gate(
            missing, _runtime_test=_fake_runtime("PASS"), _error_window_probe=lambda pids: ""
        )
        assert r.verdict == "SKIPPED" and "미존재" in r.reason

    def test_exception_is_graceful_skip(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)

        def _boom(p, timeout_sec, on_spawn=None):
            raise RuntimeError("spawn explode")

        r = run_desktop_smoke_gate(
            exe, timeout_sec=0.2, settle_sec=0.0, _runtime_test=_boom,
            _error_window_probe=lambda pids: "",
        )
        assert r.verdict == "SKIPPED" and "예외" in r.reason

    def test_skipped_on_non_win32_without_injection(self, tmp_path: Path, monkeypatch) -> None:
        """비-win32 + 미주입 → graceful SKIP (헤드리스/CI 오탐 방지)."""
        exe = _make_fake_exe(tmp_path)
        monkeypatch.setattr(
            "src.agents.runtime_verification.desktop_smoke_gate.sys.platform", "linux"
        )
        r = run_desktop_smoke_gate(exe)  # 주입 없음 → 플랫폼 게이트
        assert r.verdict == "SKIPPED" and "win32" in r.reason

    def test_owned_error_window_detected_while_alive(self, tmp_path: Path) -> None:
        """우리 Job 멤버(owned PID)가 소유한 오류 다이얼로그 창 → FAIL (생존이라도). ERP 케이스 보존.
        (최종-probe 보장으로 스레드 타이밍 무관 결정론.)"""
        exe = _make_fake_exe(tmp_path)
        probe = lambda pids: "치명적 오류 - DB 연결 실패" if 1234 in pids else ""  # noqa: E731
        r = run_desktop_smoke_gate(
            exe, timeout_sec=0.3, settle_sec=0.0,
            _runtime_test=_fake_runtime("PASS", pid=1234, owned={1234}),
            _error_window_probe=probe,
        )
        assert r.verdict == "FAIL" and r.signal == "window"
        assert "치명적 오류" in r.window_title_hit

    def test_stray_error_window_ignored(self, tmp_path: Path) -> None:
        """v13 P23 live fix(#2) — *다른 앱*(우리 Job 밖 PID)의 오류성 창은 무시 → PASS.
        (직전 크래시 ERP 잔존 다이얼로그가 healthy 빌드를 false-FAIL 하던 문제 처방.)"""
        exe = _make_fake_exe(tmp_path)
        probe = lambda pids: "치명적 오류 (다른 앱)" if 9999 in pids else ""  # noqa: E731
        r = run_desktop_smoke_gate(
            exe, timeout_sec=0.3, settle_sec=0.0,
            _runtime_test=_fake_runtime("PASS", pid=1234, owned={1234}),
            _error_window_probe=probe,
        )
        assert r.verdict == "PASS" and r.window_title_hit == ""


# =============================================================================
# 3. _apply_smoke_failure_override (verdict 파이프라인 — COMPLETE 차단 + must-fix)
# =============================================================================
def _complete(must_fix: int = 0):
    return IL.JudgmentDecision(
        verdict=IL.Verdict.COMPLETE,
        blocked_cause=IL.BlockedCause.NONE,
        reason="ok",
        next_action="",
        must_fix_count=must_fix,
    )


def _smoke_fail(err: str = "OperationalError: no such column: active"):
    return DesktopSmokeResult(
        verdict="FAIL", reason="crash", error_excerpt=err, signal="exit", exit_code=1
    )


class TestApplySmokeFailureOverride:
    def test_complete_plus_fail_below_cap_becomes_improve_with_mustfix(self) -> None:
        gap = SimpleNamespace(iteration=1)
        out = IL._apply_smoke_failure_override(
            _complete(), _smoke_fail(), gap=gap, max_iterations=5
        )
        assert out.verdict == IL.Verdict.IMPROVE_NEEDED
        assert "OperationalError" in out.next_action  # 에러가 다음 iteration 으로 주입
        assert out.must_fix_count >= 1

    def test_complete_plus_fail_at_cap_becomes_blocked(self) -> None:
        gap = SimpleNamespace(iteration=5)
        out = IL._apply_smoke_failure_override(
            _complete(), _smoke_fail(), gap=gap, max_iterations=5
        )
        assert out.verdict == IL.Verdict.BLOCKED
        assert out.blocked_cause == IL.BlockedCause.BUILD_FAILED

    def test_complete_plus_pass_unchanged(self) -> None:
        gap = SimpleNamespace(iteration=1)
        passing = DesktopSmokeResult(verdict="PASS", signal="alive")
        out = IL._apply_smoke_failure_override(_complete(), passing, gap=gap, max_iterations=5)
        assert out.verdict == IL.Verdict.COMPLETE  # 회귀 0

    def test_complete_plus_skipped_unchanged(self) -> None:
        gap = SimpleNamespace(iteration=1)
        skipped = DesktopSmokeResult(verdict="SKIPPED", signal="skipped")
        out = IL._apply_smoke_failure_override(_complete(), skipped, gap=gap, max_iterations=5)
        assert out.verdict == IL.Verdict.COMPLETE

    def test_complete_plus_none_unchanged(self) -> None:
        gap = SimpleNamespace(iteration=1)
        out = IL._apply_smoke_failure_override(_complete(), None, gap=gap, max_iterations=5)
        assert out.verdict == IL.Verdict.COMPLETE

    def test_non_complete_plus_fail_is_noop(self) -> None:
        """이미 IMPROVE 면(build override 등) smoke override 는 no-op (verdict 보존)."""
        gap = SimpleNamespace(iteration=1)
        improve = IL.JudgmentDecision(
            verdict=IL.Verdict.IMPROVE_NEEDED,
            blocked_cause=IL.BlockedCause.NONE,
            reason="r",
            next_action="기존 피드백",
            must_fix_count=2,
        )
        out = IL._apply_smoke_failure_override(improve, _smoke_fail(), gap=gap, max_iterations=5)
        assert out is improve  # 원본 그대로

    def test_mustfix_delivered_via_feedback_formatter(self) -> None:
        """override → IMPROVE 의 next_action 이 _format_feedback_for_next_iteration 으로 전달됨."""
        gap = IL.GapReport(iteration=1)
        decision = IL._apply_smoke_failure_override(
            _complete(), _smoke_fail("OperationalError: no such column: active"),
            gap=gap, max_iterations=5,
        )
        feedback = IL._format_feedback_for_next_iteration(gap, decision)
        assert "OperationalError" in feedback


# =============================================================================
# 4. _run_desktop_smoke_gate / _node_runtime_verify (loop 노드 게이팅)
# =============================================================================
def _chain(exe_path, *, success=True, command=None, exit_code=0, saved_dir=None):
    exec_res = SimpleNamespace(
        success=success, exe_path=exe_path, command=command or ["pyinstaller"], exit_code=exit_code
    )
    return SimpleNamespace(executor_result=exec_res, saved_dir=saved_dir)


class TestRunDesktopSmokeGateNode:
    def _patch_smoke(self, result):
        return patch(
            "src.agents.runtime_verification.run_desktop_smoke_gate",
            return_value=result,
        )

    def test_desktop_exe_runs_smoke_and_returns_result(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        saved = tmp_path / "workflow"
        saved.mkdir()
        chain = _chain(exe, saved_dir=saved)
        state = {"enable_smoke": True, "smoke_timeout": 8, "chain_result": chain}
        fail = _smoke_fail()
        with self._patch_smoke(fail):
            out = IL._run_desktop_smoke_gate(state)
        assert out.get("smoke_result") is fail
        # 가시 artifact 작성 확인
        assert (saved / "27_desktop_smoke_fail.md").exists()

    def test_web_build_is_noop(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        chain = _chain(exe, command=["npm", "ci"])  # _is_web_build_result True
        state = {"enable_smoke": True, "chain_result": chain}
        with self._patch_smoke(_smoke_fail()) as m:
            out = IL._run_desktop_smoke_gate(state)
        assert out == {"smoke_result": None} and m.call_count == 0

    def test_build_failed_is_noop(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        chain = _chain(exe, success=False)
        state = {"enable_smoke": True, "chain_result": chain}
        with self._patch_smoke(_smoke_fail()) as m:
            out = IL._run_desktop_smoke_gate(state)
        assert out == {"smoke_result": None} and m.call_count == 0

    def test_missing_exe_is_noop(self, tmp_path: Path) -> None:
        chain = _chain(tmp_path / "nope.exe")
        state = {"enable_smoke": True, "chain_result": chain}
        with self._patch_smoke(_smoke_fail()) as m:
            out = IL._run_desktop_smoke_gate(state)
        assert out == {"smoke_result": None} and m.call_count == 0

    def test_non_exe_suffix_is_noop(self, tmp_path: Path) -> None:
        html = tmp_path / "index.html"
        html.write_text("<html></html>", encoding="utf-8")
        chain = _chain(html)  # command pyinstaller 이지만 .html → desktop 아님
        state = {"enable_smoke": True, "chain_result": chain}
        with self._patch_smoke(_smoke_fail()) as m:
            out = IL._run_desktop_smoke_gate(state)
        assert out == {"smoke_result": None} and m.call_count == 0

    def test_disabled_is_noop(self, tmp_path: Path) -> None:
        # enable_smoke=False → smoke 가 이 런에서 안 돎 → stale 없음 → 순수 {} (smoke_result 키 미설정).
        exe = _make_fake_exe(tmp_path)
        chain = _chain(exe)
        state = {"enable_smoke": False, "chain_result": chain}
        with self._patch_smoke(_smoke_fail()) as m:
            out = IL._run_desktop_smoke_gate(state)
        assert out == {} and m.call_count == 0

    def test_smoke_exception_is_noop(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        chain = _chain(exe)
        state = {"enable_smoke": True, "chain_result": chain}
        with patch(
            "src.agents.runtime_verification.run_desktop_smoke_gate",
            side_effect=RuntimeError("boom"),
        ):
            out = IL._run_desktop_smoke_gate(state)
        assert out == {"smoke_result": None}  # 예외도 stale 클리어

    def test_node_runtime_verify_runs_smoke_when_rv_off(self, tmp_path: Path) -> None:
        """enable_rv=False(기본)여도 desktop 스모크는 실행되어 smoke_result 를 반환 (RV 와 독립)."""
        exe = _make_fake_exe(tmp_path)
        saved = tmp_path / "wf"
        saved.mkdir()
        chain = _chain(exe, saved_dir=saved)
        state = {"enable_smoke": True, "smoke_timeout": 8, "chain_result": chain, "enable_rv": False}
        with self._patch_smoke(DesktopSmokeResult(verdict="PASS", signal="alive")):
            out = IL._node_runtime_verify(state)
        assert "smoke_result" in out
        assert "rv_result" not in out  # enable_rv=False → RV pass-through

    def test_stale_clear_across_iterations(self, tmp_path: Path) -> None:
        """v13 P23 review fix(#1) — 이전 desktop FAIL 후 web iteration 은 smoke_result=None 으로
        덮어써 stale FAIL 이 후속 COMPLETE 를 거짓 차단하지 않게 한다 (cross-iteration 누적 방지)."""
        exe = _make_fake_exe(tmp_path)
        saved = tmp_path / "wf"
        saved.mkdir()
        # iter N: desktop FAIL
        with self._patch_smoke(_smoke_fail()):
            out1 = IL._run_desktop_smoke_gate(
                {"enable_smoke": True, "smoke_timeout": 8, "chain_result": _chain(exe, saved_dir=saved)}
            )
        assert out1["smoke_result"].verdict == "FAIL"
        # iter N+1: web build → 게이트가 smoke_result 를 None 으로 *클리어* (덮어쓰기)
        out2 = IL._run_desktop_smoke_gate(
            {"enable_smoke": True, "chain_result": _chain(exe, command=["npm", "ci"])}
        )
        assert out2 == {"smoke_result": None}
        # 그 None 을 override 가 읽으면 COMPLETE 유지 (거짓 차단 없음)
        out = IL._apply_smoke_failure_override(
            _complete(), out2["smoke_result"], gap=SimpleNamespace(iteration=1), max_iterations=5
        )
        assert out.verdict == IL.Verdict.COMPLETE

    def test_node_runtime_verify_web_noop_when_rv_off(self, tmp_path: Path) -> None:
        exe = _make_fake_exe(tmp_path)
        chain = _chain(exe, command=["npm", "ci"])
        state = {"enable_smoke": True, "chain_result": chain, "enable_rv": False}
        with self._patch_smoke(_smoke_fail()):
            out = IL._node_runtime_verify(state)
        # web → 스모크 no-op(smoke_result=None, stale 클리어) + RV off
        assert out == {"smoke_result": None}
