# -*- coding: utf-8 -*-
"""P20 런 중 사람 개입(체크포인트) 회귀 test (v13).

codegen 직전 1회 멈춰 계획/스펙을 보여주고(checkpoint 이벤트) 피드백을 받아 P12
메커니즘으로 codegen 입력에 반영, 무입력이면 타임아웃 자동 진행. **기본 OFF**.

검증:
  - OFF(intervene=False) → 즉시 None (회귀 0, 외부 접근 없음).
  - 파일 모드(GUI): intervention_in.json 존재 → feedback 반환 / action=continue → None.
  - 타임아웃: 무입력 → None (결정론 clock/sleeper 주입).
  - 헤드리스(pytest, no emitter, no tty) → None (자동 진행, 블록 없음).
  - CheckpointEvent emit (telemetry 활성 시 events.jsonl 에 type=checkpoint).
  - _node_run_chain 통합: intervene ON + 첫 codegen + 파일 → feedback 가 codegen 요청에 주입.
                          intervene OFF → 요청 불변(기존 경로 100% 동일).
  - 플래그 전파: run_iterative_loop 가 intervene/intervene_timeout kwarg 수용.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows import iterative_loop as IL  # noqa: E402
from src.workflows._intervention import (  # noqa: E402
    DEFAULT_INTERVENE_TIMEOUT_SEC,
    _poll_intervention_file,
    _read_intervention_file,
    format_intervention_directive,
    request_codegen_intervention,
)


def _write_intervention(path: Path, feedback: str, action: str = "inject") -> None:
    path.write_text(json.dumps({"feedback": feedback, "action": action}), encoding="utf-8")


# =============================================================================
# 1. OFF (기본) — 즉시 None, 외부 접근 없음 (회귀 0)
# =============================================================================
class TestOffByDefault:
    def test_intervene_false_returns_none(self) -> None:
        assert request_codegen_intervention("plan", intervene=False) is None

    def test_intervene_false_does_not_touch_run_root(self, tmp_path: Path) -> None:
        # OFF 면 file_poll/stdin_read 가 주어져도 호출되지 않음 (즉시 반환).
        called = {"poll": False}

        def _poll():
            called["poll"] = True
            return "should-not-be-used"

        out = request_codegen_intervention(
            "plan", intervene=False, run_root=tmp_path, file_poll=_poll
        )
        assert out is None
        assert called["poll"] is False


# =============================================================================
# 2. 파일 모드 (GUI) — intervention_in.json 폴링
#    실제 시퀀스: 훅 진입 시 stale 제거 → checkpoint emit → (GUI 가 파일 기록) → 폴링이 잡음.
# =============================================================================
class TestFileMode:
    def test_file_poll_result_returned(self, tmp_path: Path) -> None:
        """파일 모드 → 폴링 결과를 그대로 반환 (plumbing)."""
        out = request_codegen_intervention(
            "plan", intervene=True, run_root=tmp_path, file_poll=lambda: "다크 테마로"
        )
        assert out == "다크 테마로"

    def test_file_appears_during_poll(self, tmp_path: Path) -> None:
        """실제 흐름 — stale 제거 후 폴링 중 GUI 가 파일을 기록하면 잡아 읽는다 (백그라운드 thread)."""
        import threading
        import time

        f = tmp_path / "intervention_in.json"

        def _writer() -> None:
            time.sleep(0.15)
            _write_intervention(f, "좌측 필터 추가", "inject")

        t = threading.Thread(target=_writer, daemon=True)
        t.start()
        out = request_codegen_intervention(
            "plan", intervene=True, timeout_sec=5, run_root=tmp_path
        )
        t.join(timeout=2)
        assert out == "좌측 필터 추가"
        assert not f.exists()  # 읽은 뒤 소비(삭제)

    def test_stale_file_removed_before_wait(self, tmp_path: Path) -> None:
        """파일 모드 진입 시 스테일 파일(이전 런 잔존) 제거 후 *새* 입력을 기다린다.

        file_poll 주입으로 폴링은 None(타임아웃) 모사 — 진입부에서 stale 이 지워졌는지 확인.
        (실제로는 GUI 가 checkpoint 이벤트 *수신 후* 기록하므로 stale 자동 주입 방지가 핵심.)
        """
        stale = tmp_path / "intervention_in.json"
        _write_intervention(stale, "이전 런 잔존", "inject")
        out = request_codegen_intervention(
            "plan", intervene=True, run_root=tmp_path, file_poll=lambda: None
        )
        assert out is None
        assert not stale.exists()  # 스테일 제거됨 (자동 주입 방지)


# =============================================================================
# 3. _read_intervention_file / _poll_intervention_file 단위
# =============================================================================
class TestReadAndPoll:
    def test_read_inject(self, tmp_path: Path) -> None:
        f = tmp_path / "i.json"
        _write_intervention(f, "hello", "inject")
        assert _read_intervention_file(f) == "hello"
        assert not f.exists()  # 읽은 뒤 소비(삭제) — 누수 방지

    def test_read_continue_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "i.json"
        _write_intervention(f, "무시될 텍스트", "continue")
        assert _read_intervention_file(f) is None  # '그냥 계속'
        assert not f.exists()

    def test_read_empty_feedback_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "i.json"
        _write_intervention(f, "   ", "inject")
        assert _read_intervention_file(f) is None

    def test_read_bad_json_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "i.json"
        f.write_text("{not valid json", encoding="utf-8")
        assert _read_intervention_file(f) is None

    def test_poll_timeout_returns_none_deterministic(self, tmp_path: Path) -> None:
        """결정론 clock — 파일 없으면 deadline 초과 시 None (실 sleep 없음)."""
        ticks = iter([0.0, 0.3, 0.6, 0.9, 1.2, 1.5, 99.0])
        out = _poll_intervention_file(
            tmp_path / "none.json", timeout_sec=1,
            sleeper=lambda _s: None, clock=lambda: next(ticks),
        )
        assert out is None

    def test_poll_finds_file_immediately(self, tmp_path: Path) -> None:
        f = tmp_path / "i.json"
        _write_intervention(f, "즉시", "inject")
        out = _poll_intervention_file(
            f, timeout_sec=5, sleeper=lambda _s: None, clock=lambda: 0.0
        )
        assert out == "즉시"

    def test_grace_catches_arrival_after_timeout(self, tmp_path: Path) -> None:
        """리뷰 confirmed — grace 가 timeout_sec 직후(GUI 카운트다운 잔여 표시 중) 도착 제출을 잡는다.

        파일이 t>=2.0(=timeout_sec 1 초과)에 도착. grace=3 이면 deadline=4 라 잡고,
        grace=0 이면 deadline=1 이라 놓친다 (desync 막판 제출 유실 시나리오).
        """
        f = tmp_path / "i.json"

        def _clock_arriving_at_2():
            seq = iter([0.0, 0.5, 1.5, 2.5, 99.0])

            def _c():
                t = next(seq)
                if t >= 2.0 and not f.exists():
                    _write_intervention(f, "막판 제출", "inject")
                return t

            return _c

        # grace 有 → 늦은 도착도 잡음
        out = _poll_intervention_file(
            f, timeout_sec=1, grace_sec=3, sleeper=lambda _s: None, clock=_clock_arriving_at_2()
        )
        assert out == "막판 제출"

        # grace 無 → 동일 늦은 도착을 놓침 (None)
        f2 = tmp_path / "i2.json"

        def _clock2():
            seq = iter([0.0, 0.5, 1.5, 2.5, 99.0])

            def _c():
                t = next(seq)
                if t >= 2.0 and not f2.exists():
                    _write_intervention(f2, "막판 제출", "inject")
                return t

            return _c

        out2 = _poll_intervention_file(
            f2, timeout_sec=1, grace_sec=0, sleeper=lambda _s: None, clock=_clock2()
        )
        assert out2 is None


# =============================================================================
# 4. 헤드리스 (pytest, no emitter, no tty) — None (자동 진행, 블록 없음)
# =============================================================================
class TestHeadless:
    def test_no_runroot_no_emitter_returns_none(self) -> None:
        # pytest 환경: _run_root_from_emitter()=None(telemetry OFF), stdin 비-tty, pytest in sys.modules
        # → 콘솔/파일 모두 불가 → None (자동 진행). 절대 블록 안 함.
        out = request_codegen_intervention("plan", intervene=True, timeout_sec=2)
        assert out is None

    def test_injected_stdin_read_used_when_no_runroot(self) -> None:
        # 콘솔 모드 주입 — run_root 없을 때 stdin_read 가 쓰임.
        out = request_codegen_intervention(
            "plan", intervene=True, stdin_read=lambda: "콘솔 피드백"
        )
        assert out == "콘솔 피드백"


# =============================================================================
# 5. format_intervention_directive
# =============================================================================
class TestDirective:
    def test_directive_wraps_feedback(self) -> None:
        d = format_intervention_directive("좌측에 필터 추가")
        assert "사용자 개입 지시 (P20" in d
        assert "좌측에 필터 추가" in d
        assert "최우선 반영" in d


# =============================================================================
# 6. CheckpointEvent emit (telemetry 활성 시 events.jsonl)
# =============================================================================
class TestCheckpointEmit:
    def test_emits_checkpoint_event(self, tmp_path: Path, monkeypatch) -> None:
        from src.monitoring import telemetry as T

        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(events_path))
        T.TelemetryEmitter.reset_for_tests()
        try:
            # 파일 모드 진입 → checkpoint emit + 폴링(즉시 타임아웃 file_poll).
            request_codegen_intervention(
                "[스펙] 칸반 보드", intervene=True, run_root=tmp_path,
                file_poll=lambda: None, timeout_sec=3,
            )
            assert events_path.exists()
            lines = [json.loads(ln) for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            cps = [e for e in lines if e.get("type") == "checkpoint"]
            assert len(cps) == 1
            assert cps[0]["checkpoint_id"] == "pre_codegen"
            assert "칸반 보드" in cps[0]["plan_summary"]
            assert cps[0]["intervention_file"].endswith("intervention_in.json")
            assert cps[0]["timeout_sec"] == 3
        finally:
            T.TelemetryEmitter.reset_for_tests()

    def test_iter2_event_carries_prev_build_path_and_iteration(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """v13 P22 — iter 2+ 체크포인트 이벤트가 prev_build_path + iteration 을 함께 실어
        GUI 가 '직전 빌드 검토' 패널로 분기하고 '빌드 열어보기' 대상 경로를 얻게 한다."""
        from src.monitoring import telemetry as T

        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(events_path))
        T.TelemetryEmitter.reset_for_tests()
        try:
            request_codegen_intervention(
                "[직전 빌드 (web)] x", intervene=True, run_root=tmp_path,
                file_poll=lambda: None, timeout_sec=3,
                iteration=2, prev_build_path=r"C:\out\code\dist\index.html",
            )
            lines = [
                json.loads(ln)
                for ln in events_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            cps = [e for e in lines if e.get("type") == "checkpoint"]
            assert len(cps) == 1
            assert cps[0]["iteration"] == 2
            assert cps[0]["prev_build_path"] == r"C:\out\code\dist\index.html"
        finally:
            T.TelemetryEmitter.reset_for_tests()

    def test_iter1_event_prev_build_path_empty(self, tmp_path: Path, monkeypatch) -> None:
        """v13 P22 보존 — iter 1(빌드 전) 이벤트는 prev_build_path 가 빈 문자열(기본값)."""
        from src.monitoring import telemetry as T

        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(events_path))
        T.TelemetryEmitter.reset_for_tests()
        try:
            request_codegen_intervention(
                "[스펙] x", intervene=True, run_root=tmp_path,
                file_poll=lambda: None, timeout_sec=3, iteration=1,
            )
            lines = [
                json.loads(ln)
                for ln in events_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            cps = [e for e in lines if e.get("type") == "checkpoint"]
            assert len(cps) == 1
            assert cps[0]["prev_build_path"] == ""
            assert cps[0]["iteration"] == 1  # iter1 = next_iter, 와이어 값 박제
        finally:
            T.TelemetryEmitter.reset_for_tests()

    def test_off_emits_nothing(self, tmp_path: Path, monkeypatch) -> None:
        from src.monitoring import telemetry as T

        events_path = tmp_path / "events.jsonl"
        monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(events_path))
        T.TelemetryEmitter.reset_for_tests()
        try:
            request_codegen_intervention("plan", intervene=False, run_root=tmp_path)
            # OFF → emit 없음 (파일 미생성 또는 checkpoint 라인 0).
            if events_path.exists():
                lines = [
                    json.loads(ln)
                    for ln in events_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                ]
                assert not any(e.get("type") == "checkpoint" for e in lines)
        finally:
            T.TelemetryEmitter.reset_for_tests()


# =============================================================================
# 7. _node_run_chain 통합 — 주입 / OFF 회귀
# =============================================================================
class TestNodeRunChainIntegration:
    def _base_state(self, tmp_path: Path, **over) -> dict:
        st = {
            "iteration": 0,
            "user_request": "칸반 보드 웹앱",
            "feedback": "",
            "platform_intent": "web",
            "outputs_dir": str(tmp_path),
            "track": "A",
            "verbose": False,
            "iteration_artifacts": [],
        }
        st.update(over)
        return st

    def test_intervene_on_injects_feedback_into_request(self, tmp_path: Path, monkeypatch) -> None:
        """intervene ON + 첫 codegen → 훅 반환 feedback 이 directive 로 codegen 요청에 주입(P12 conduit).

        훅(request_codegen_intervention) 은 monkeypatch 로 결정론화 — 훅 자체(파일/타임아웃)는
        TestFileMode/TestReadAndPoll 가 검증. 여기선 *_node_run_chain 배선* 만 본다.
        """
        import src.workflows._intervention as INT

        monkeypatch.setattr(INT, "request_codegen_intervention", lambda *a, **k: "다크 테마 + 좌측 필터")

        captured = {}

        def _fake_run(req, **kw):
            captured["request"] = req
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)
        IL._node_run_chain(self._base_state(tmp_path, intervene=True, intervene_timeout=5))

        assert "다크 테마 + 좌측 필터" in captured["request"]
        assert "사용자 개입 지시 (P20" in captured["request"]

    def test_intervene_off_request_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        """OFF(기본) → 체크포인트 미발동, 요청에 개입 directive 없음 (기존 경로 100% 동일)."""
        captured = {}

        def _fake_run(req, **kw):
            captured["request"] = req
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)
        IL._node_run_chain(self._base_state(tmp_path))  # intervene 미지정 → False
        assert "사용자 개입 지시" not in captured["request"]
        assert captured["request"].startswith("칸반 보드 웹앱")

    def test_max_iter1_no_iter2_checkpoint(self, tmp_path: Path, monkeypatch) -> None:
        """v13 P22 보존 — MAX-ITER=1 이면 iter 2+ (next_iter>1) 미발동 = P20 와 100% 동일.

        (P22 일반화 게이트: ``next_iter==1 or max_iter>=2``. max_iterations=1 + next_iter=2 →
        둘 다 False → 훅 미호출. MAX-ITER=1 런은 애초에 iter 2 에 도달하지 않지만, 게이트 자체를
        단위로 박제한다.)
        """
        import src.workflows._intervention as INT

        hook_calls = {"n": 0}

        def _hook(*a, **k):
            hook_calls["n"] += 1
            return "이건 안 주입돼야"

        monkeypatch.setattr(INT, "request_codegen_intervention", _hook)

        captured = {}

        def _fake_run(req, **kw):
            captured["request"] = req
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)
        # iteration=1 → next_iter=2, max_iterations=1 → 체크포인트 스킵 (P20 동일).
        st = self._base_state(tmp_path, iteration=1, intervene=True, max_iterations=1,
                              chain_result=SimpleNamespace(saved_code_files=[]))
        IL._node_run_chain(st)
        assert hook_calls["n"] == 0  # MAX-ITER=1 의 iter2 → 훅 미호출
        assert "사용자 개입 지시" not in captured["request"]

    def test_max_iter1_still_fires_iter1_checkpoint(self, tmp_path: Path, monkeypatch) -> None:
        """v13 P22 보존(P20 parity) — MAX-ITER=1 이어도 iter 1 체크포인트는 P20 처럼 발동.

        (게이트 ``next_iter==1 or max_iter>=2`` 의 next_iter==1 분기 — max_iter 무관하게 첫
        codegen 직전 1회 발동. iter1 발동이 default max_iter 로만 검증되던 갭을 메운다.)
        """
        import src.workflows._intervention as INT

        hook_calls = {"n": 0}

        def _hook(*a, **k):
            hook_calls["n"] += 1
            return "iter1 지시"

        monkeypatch.setattr(INT, "request_codegen_intervention", _hook)

        def _fake_run(req, **kw):
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)
        # iteration=0 → next_iter=1, max_iterations=1 → 발동(P20 동일).
        st = self._base_state(tmp_path, iteration=0, intervene=True, max_iterations=1)
        IL._node_run_chain(st)
        assert hook_calls["n"] == 1  # MAX-ITER=1 의 iter1 → 발동

    def test_iter2_fires_and_injects_when_max_iter_ge2(self, tmp_path: Path, monkeypatch) -> None:
        """v13 P22 — MAX-ITER>=2 면 iter 2 codegen 직전에도 체크포인트 발동 + 피드백 주입.

        직전 빌드 경로(executor_result.exe_path) 가 hook 에 prev_build_path 로 전달되고,
        반환 피드백이 P12 conduit 로 iter2 codegen 요청에 주입됨을 함께 검증.
        """
        import src.workflows._intervention as INT

        captured_hook = {}

        def _hook(plan_summary, **k):
            captured_hook["plan_summary"] = plan_summary
            captured_hook["iteration"] = k.get("iteration")
            captured_hook["prev_build_path"] = k.get("prev_build_path")
            return "iter2 직접 지시 — 헤더 색을 빨강으로"

        monkeypatch.setattr(INT, "request_codegen_intervention", _hook)

        captured = {}

        def _fake_run(req, **kw):
            captured["request"] = req
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)

        # 직전(iter1) 빌드 = 실재 web 산출물(dist/index.html) → category web, 경로 전달돼야.
        dist = tmp_path / "code" / "dist"
        dist.mkdir(parents=True)
        index = dist / "index.html"
        index.write_text("<html></html>", encoding="utf-8")
        prev = SimpleNamespace(executor_result=SimpleNamespace(exe_path=index),
                               qa_review="QA: 버튼 클릭 OK", saved_code_files=[])
        st = self._base_state(tmp_path, iteration=1, intervene=True, max_iterations=3,
                              feedback="이전 gap: 폼 검증 누락", chain_result=prev)
        IL._node_run_chain(st)

        assert captured_hook.get("iteration") == 2  # next_iter
        assert captured_hook.get("prev_build_path") == str(index)  # 직전 빌드 경로 전달
        assert "iter2 직접 지시" in captured["request"]  # P12 주입
        assert "사용자 개입 지시" in captured["request"]
        # plan_summary 에 직전 gap·빌드 컨텍스트가 실렸는지
        assert "직전 빌드" in captured_hook["plan_summary"]
        assert "폼 검증 누락" in captured_hook["plan_summary"]

    def test_iter2_build_missing_is_graceful(self, tmp_path: Path, monkeypatch) -> None:
        """v13 P22 — iter 2+ 인데 직전 빌드 미존재(executor_result None) → 예외 없이 진행 +
        prev_build_path "" 전달(=GUI '빌드 열어보기' 비활성). gap·피드백은 그대로."""
        import src.workflows._intervention as INT

        captured_hook = {}

        def _hook(plan_summary, **k):
            captured_hook["plan_summary"] = plan_summary
            captured_hook["prev_build_path"] = k.get("prev_build_path")
            return None  # '그냥 계속'

        monkeypatch.setattr(INT, "request_codegen_intervention", _hook)

        def _fake_run(req, **kw):
            return SimpleNamespace(saved_dir=tmp_path, engineer_output="", qa_review="",
                                   executor_result=None)

        monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)
        prev = SimpleNamespace(executor_result=None, qa_review="", saved_code_files=[])
        st = self._base_state(tmp_path, iteration=1, intervene=True, max_iterations=2,
                              feedback="이전 gap 텍스트", chain_result=prev)
        # 예외 없이 완료돼야 한다.
        IL._node_run_chain(st)
        assert captured_hook.get("prev_build_path") == ""  # 빌드 없음 → 빈 경로
        assert "없음 또는 실패" in captured_hook["plan_summary"]


# =============================================================================
# 8. 플래그 전파 — run_iterative_loop 시그니처
# =============================================================================
class TestFlagPropagation:
    def test_run_iterative_loop_accepts_intervene_kwargs(self) -> None:
        import inspect

        sig = inspect.signature(IL.run_iterative_loop)
        assert "intervene" in sig.parameters
        assert sig.parameters["intervene"].default is False
        assert "intervene_timeout" in sig.parameters
        assert sig.parameters["intervene_timeout"].default == DEFAULT_INTERVENE_TIMEOUT_SEC

    def test_run_py_has_intervene_flags(self) -> None:
        text = (PROJECT_ROOT / "scripts" / "run.py").read_text(encoding="utf-8")
        assert "--intervene" in text
        assert "--intervene-timeout" in text
