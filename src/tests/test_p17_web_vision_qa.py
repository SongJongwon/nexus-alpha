# -*- coding: utf-8 -*-
"""P17 web 자동 시각 QA 회귀 test (v13 — HARNESS_AUDIT/P16 修正4 마무리).

목표: web 타깃의 시각 QA 를 *실제로* 작동(headless 캡처 + vision 평가)시키고,
평가 불가 시 *우아하게 SKIP*(FAIL 아님)해 파괴적 retry-rebuild 를 막는다.

수정1 — web 실제 시각 QA:
    web_vision_qa.run_web_vision_qa 가 dist 를 정적 서버(SPA fallback)로 띄우고
    headless 브라우저로 캡처 → vision 평가(claude-code-default 우선). 서빙/캡처/분석은
    주입 가능(테스트는 실 소켓/브라우저 없이 mock). vision 인증은 공통 Provider
    (supports_vision/generate_vision) 우선, ANTHROPIC_API_KEY raw SDK 폴백.

수정2 — 견고한 graceful skip:
    Playwright/브라우저 미설치 · 서빙/캡처 실패 · vision 경로 불가 → skipped=True
    (FAIL 아님). + run_gui_test 의 web(.html) 심층 방어선(SKIPPED). → retry 미발동.

수정3 — retry 는 web 면 web 재빌드:
    run.py _retry_engineer_with_vision_feedback(is_web=True) 가 web 코드 추출/프롬프트
    로 재생성 → _is_web_project 가 npm 재빌드로 라우팅 (본 파일은 시그니처/배선 검증).

절대 보존: 데스크탑(.exe) run_gui_test 경로 불변, P16 4건 + 기존 verdict 의미.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.qa import web_vision_qa as WV  # noqa: E402
from src.agents.qa.gui_test_executor import (  # noqa: E402
    GUITestResult,
    VisionAnalysis,
    analyze_screenshot,
    run_gui_test,
)
from src.agents.qa.web_vision_qa import (  # noqa: E402
    derive_routes,
    run_web_vision_qa,
)
from src.llm.base_provider import BaseLLMProvider  # noqa: E402
from src.workflows.qa_feedback_loop import evaluate_qa_results  # noqa: E402


# ---------------------------------------------------------------------------
# 테스트 헬퍼 — 주입용 fake serve/capture/analyze + fake httpd
# ---------------------------------------------------------------------------
class _FakeHttpd:
    """_shutdown_server 가 호출하는 shutdown/server_close 추적."""

    def __init__(self) -> None:
        self.shutdown_called = False
        self.closed = False

    def shutdown(self) -> None:
        self.shutdown_called = True

    def server_close(self) -> None:
        self.closed = True


def _fake_serve_factory(httpd: _FakeHttpd):
    def _serve(dist_dir: Path):
        return httpd, "http://127.0.0.1:65000"
    return _serve


def _fake_capture_factory(shots: list[Path], terminated_by: str = "natural_exit",
                          error: Optional[str] = None):
    calls: dict = {}

    def _capture(base_url, routes, output_dir, *, wait_ms=1500):
        calls["base_url"] = base_url
        calls["routes"] = routes
        return list(shots), terminated_by, error
    _capture.calls = calls  # type: ignore[attr-defined]
    return _capture


def _vision(success: bool, critical: int = 0, error: Optional[str] = None) -> VisionAnalysis:
    return VisionAnalysis(
        screenshot_path=Path("s.png"), model="m", success=success,
        critical_issue_count=critical, error_message=error,
    )


# =============================================================================
# 수정1-A. derive_routes — 랜딩 보장 + 동일출처 경로 추출 + 외부/에셋 제외
# =============================================================================
class TestDeriveRoutes:
    def test_landing_always_present_even_without_index(self, tmp_path: Path) -> None:
        assert derive_routes(tmp_path) == ["/"]

    def test_extracts_same_origin_routes_excludes_external_and_assets(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(
            "<a href='/about'>a</a><a href='dashboard'>b</a>"
            "<a href='#/settings'>c</a>"
            "<a href='https://x.com/ext'>ext</a><a href='mailto:a@b.c'>m</a>"
            "<a href='/logo.png'>asset</a><a href='#'>anchor</a>",
            encoding="utf-8",
        )
        routes = derive_routes(tmp_path)
        # 결정적 정확 매칭 — 동일 출처(절대/상대→절대/해시 라우트)만 포함하고 외부 링크
        # (https://...)·mailto·에셋(.png)·빈 앵커(#)는 결과 목록에 *아예 없음*.
        # (URL 부분문자열 검사 대신 리스트 동등성으로 검증 — 포함+제외를 동시에 잠금.)
        assert routes == ["/", "/about", "/dashboard", "/#/settings"]

    def test_routes_capped(self, tmp_path: Path) -> None:
        links = "".join(f"<a href='/r{i}'>x</a>" for i in range(20))
        (tmp_path / "index.html").write_text(links, encoding="utf-8")
        assert len(derive_routes(tmp_path)) <= WV._MAX_ROUTES


# =============================================================================
# 수정1-B. run_web_vision_qa 정상 경로 — serve+capture+vision (주입 mock)
# =============================================================================
class TestRunWebVisionHappyPath:
    def _dist(self, tmp_path: Path) -> Path:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
        return dist

    def test_serves_captures_and_evaluates_pass(self, tmp_path: Path) -> None:
        dist = self._dist(tmp_path)
        httpd = _FakeHttpd()
        shots = [tmp_path / "web_screenshot_01.png"]
        cap = _fake_capture_factory(shots)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(httpd),
            capture_fn=cap,
            analyze_fn=lambda shot, **kw: _vision(success=True, critical=0),
        )
        assert res.skipped is False
        assert res.success is True  # vision 통과
        assert res.screenshot_paths == shots
        assert len(res.vision_analyses) == 1
        # 서버는 반드시 종료
        assert httpd.shutdown_called and httpd.closed
        # base_url 이 capture 로 전달됨
        assert cap.calls["base_url"].startswith("http://127.0.0.1")

    def test_real_visual_defect_fails_not_skipped(self, tmp_path: Path) -> None:
        """캡처 성공 + vision 이 critical 결함 발견 → success=False, skipped=False
        → qa_feedback_loop 가 retry(=web 재빌드) 발동 (수정3 전제)."""
        dist = self._dist(tmp_path)
        httpd = _FakeHttpd()
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(httpd),
            capture_fn=_fake_capture_factory([tmp_path / "s.png"]),
            analyze_fn=lambda shot, **kw: _vision(success=True, critical=2),
        )
        assert res.skipped is False
        assert res.success is False  # 실 시각 결함 → FAIL
        assert res.total_critical_issues == 2

    def test_skip_vision_captures_only(self, tmp_path: Path) -> None:
        dist = self._dist(tmp_path)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            skip_vision=True,
            serve_fn=_fake_serve_factory(_FakeHttpd()),
            capture_fn=_fake_capture_factory([tmp_path / "s.png"]),
            analyze_fn=lambda shot, **kw: pytest.fail("skip_vision 인데 analyze 호출됨"),
        )
        assert res.skipped is False
        assert res.success is True  # 캡처 OK + vision 미수행 → critical 0
        assert res.vision_analyses == []


# =============================================================================
# 수정2. graceful skip — 어떤 불가 케이스든 skipped=True (FAIL 아님)
# =============================================================================
class TestGracefulSkip:
    def _dist(self, tmp_path: Path) -> Path:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
        return dist

    def test_dist_missing_skips(self, tmp_path: Path) -> None:
        res = run_web_vision_qa(tmp_path / "nope", tmp_path / "out")
        assert res.skipped is True
        assert res.success is False

    def test_playwright_missing_skips(self, tmp_path: Path, monkeypatch) -> None:
        """기본 capture_fn + playwright 미설치 → SKIP (브라우저/모듈 부재 graceful)."""
        dist = self._dist(tmp_path)
        monkeypatch.setattr(WV, "_is_playwright_available", lambda: False)
        res = run_web_vision_qa(dist, tmp_path / "out",
                                serve_fn=_fake_serve_factory(_FakeHttpd()))
        assert res.skipped is True
        assert "Playwright" in (res.error_message or "")

    def test_serve_failure_skips_and_no_crash(self, tmp_path: Path) -> None:
        dist = self._dist(tmp_path)

        def _boom_serve(_d):
            raise OSError("port bind 실패")

        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_boom_serve,
            capture_fn=_fake_capture_factory([tmp_path / "s.png"]),
        )
        assert res.skipped is True
        assert "서버" in (res.error_message or "")

    def test_capture_zero_screenshots_skips(self, tmp_path: Path) -> None:
        """브라우저 launch 실패 등으로 0장 → SKIP (FAIL 아님)."""
        dist = self._dist(tmp_path)
        httpd = _FakeHttpd()
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(httpd),
            capture_fn=_fake_capture_factory([], terminated_by="skipped",
                                             error="Executable doesn't exist"),
        )
        assert res.skipped is True
        assert httpd.shutdown_called  # 서버는 그래도 종료
        assert "캡처" in (res.error_message or "")

    def test_capture_exception_skips(self, tmp_path: Path) -> None:
        dist = self._dist(tmp_path)
        httpd = _FakeHttpd()

        def _boom_capture(base_url, routes, output_dir, *, wait_ms=1500):
            raise RuntimeError("playwright 내부 오류")

        res = run_web_vision_qa(dist, tmp_path / "out",
                                serve_fn=_fake_serve_factory(httpd),
                                capture_fn=_boom_capture)
        assert res.skipped is True
        assert httpd.shutdown_called  # finally 종료 보장

    def test_vision_unavailable_skips_not_fail(self, tmp_path: Path) -> None:
        """캡처는 성공했으나 vision 평가 경로 전부 불가(키/claude-code 부재) → SKIP."""
        dist = self._dist(tmp_path)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(_FakeHttpd()),
            capture_fn=_fake_capture_factory([tmp_path / "s.png"]),
            analyze_fn=lambda shot, **kw: _vision(success=False, error="키 미설정"),
        )
        assert res.skipped is True
        assert res.success is False
        assert "미평가" in (res.error_message or "")


# =============================================================================
# 수정2 (통합). web 시각 QA 결과 → qa_feedback_loop: skip→retry 미발동, 실결함→retry
# =============================================================================
class TestQAFeedbackIntegration:
    def test_skipped_web_vision_does_not_trigger_retry(self) -> None:
        """web 캡처 불가(skipped=True) → should_retry False (파괴적 재빌드 차단). 키 'vision_qa'."""
        skipped_result = GUITestResult(success=False, skipped=True, target_path=Path("dist"))
        decision = evaluate_qa_results(
            results={"vision_qa": skipped_result},
            retry_count=0, max_retries=1, artifact_category="web",
        )
        assert "vision_qa" in decision.skipped_qa_tools
        assert decision.overall_passed is True
        assert decision.should_retry is False

    def test_real_web_visual_defect_triggers_retry(self) -> None:
        """web 실 시각 결함(success=False, skipped=False) → should_retry True → web 재빌드."""
        fail_result = GUITestResult(
            success=False, skipped=False, target_path=Path("dist"),
            screenshot_paths=[Path("s.png")],
            vision_analyses=[_vision(success=True, critical=1)],
        )
        decision = evaluate_qa_results(
            results={"vision_qa": fail_result},
            retry_count=0, max_retries=1, artifact_category="web",
        )
        assert "vision_qa" in decision.failed_qa_tools
        assert decision.overall_passed is False
        assert decision.should_retry is True


# =============================================================================
# 수정2 (심층 방어). run_gui_test 가 web(.html) 을 받으면 SKIP (데스크탑 경로 오용 차단)
# =============================================================================
class TestRunGuiTestWebDefense:
    def test_html_target_skipped(self, tmp_path: Path) -> None:
        html = tmp_path / "index.html"
        html.write_text("<!doctype html>", encoding="utf-8")
        res = run_gui_test(html, tmp_path / "out")
        assert res.skipped is True
        assert res.success is False
        assert "web" in (res.error_message or "").lower()

    def test_exe_target_not_short_circuited(self, tmp_path: Path, monkeypatch) -> None:
        """.exe 는 web 방어선에 안 걸리고 기존 캡처 경로로 진행 (데스크탑 불변)."""
        exe = tmp_path / "App.exe"
        exe.write_bytes(b"MZ")
        import src.agents.qa.gui_test_executor as G
        monkeypatch.setattr(G, "_is_pyautogui_available", lambda: True)
        monkeypatch.setattr(
            G, "launch_and_capture",
            lambda *a, **kw: ([tmp_path / "shot.png"], 0, "terminated_after_capture"),
        )
        monkeypatch.setattr(G, "analyze_screenshot",
                            lambda shot, **kw: _vision(success=True, critical=0))
        # shot 파일 생성 (run_gui_test 는 screenshot_paths 비었는지만 검사)
        (tmp_path / "shot.png").write_bytes(b"x")
        res = run_gui_test(exe, tmp_path / "out")
        assert res.skipped is False
        assert res.success is True


# =============================================================================
# 수정1 (인증). Provider vision capability + analyze_screenshot 라우팅/폴백
# =============================================================================
class _FakeVisionProvider(BaseLLMProvider):
    """claude-code-default 흉내 — supports_vision True, generate_vision 이 JSON 반환."""

    def __init__(self, response_json: str) -> None:
        self._resp = response_json
        self.called = False

    @property
    def name(self) -> str:
        return "fake-vision"

    async def _generate_impl(self, prompt: str, system=None) -> str:
        return ""

    def supports_vision(self) -> bool:
        return True

    async def generate_vision(self, prompt, images, system=None, *, model=None, max_tokens=512) -> str:
        self.called = True
        return self._resp


class TestVisionAuthRouting:
    def test_base_provider_vision_defaults_safe(self) -> None:
        """BaseLLMProvider 기본 — supports_vision False, generate_vision NotImplementedError."""
        from src.tests.conftest import FakeProvider

        p = FakeProvider()
        assert p.supports_vision() is False
        import anyio

        async def _call():
            await p.generate_vision("x", [("b64", "image/png")])

        with pytest.raises(NotImplementedError):
            anyio.run(_call)

    def test_agent_sdk_provider_supports_vision(self) -> None:
        """AgentSDKProvider 는 claude-code-default 멀티모달 지원 선언 (실호출은 integration)."""
        from src.llm.agent_sdk_provider import AgentSDKProvider

        assert AgentSDKProvider().supports_vision() is True
        assert hasattr(AgentSDKProvider(), "generate_vision")

    def test_analyze_screenshot_uses_provider_when_supported(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """claude-code-default(Provider) 경유 — 별도 ANTHROPIC_API_KEY 없이 평가 성공."""
        shot = tmp_path / "s.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n fake")
        provider = _FakeVisionProvider(
            '{"summary":"ok","is_window_visible":true,"ui_issues":[],"critical_issue_count":0}'
        )
        import src.llm.factory as factory
        monkeypatch.setattr(factory, "get_llm_provider", lambda: provider)
        # 키가 없어도(=raw SDK 폴백 불가) Provider 경로로 성공해야 함
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = analyze_screenshot(shot)
        assert provider.called is True
        assert result.success is True
        assert result.critical_issue_count == 0

    def test_analyze_screenshot_falls_back_to_raw_sdk(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Provider 가 vision 미지원이면 기존 ANTHROPIC_API_KEY raw SDK 경로 폴백 (회귀 0)."""
        shot = tmp_path / "s.png"
        shot.write_bytes(b"\x89PNG fake")
        import src.agents.qa.gui_test_executor as G
        # conftest 의 FakeProvider 는 supports_vision False → provider 경로 None → 폴백
        monkeypatch.setattr(G, "_is_anthropic_available", lambda: True)
        monkeypatch.setattr(G, "_resolve_anthropic_api_key", lambda explicit=None: "fake-key")

        class _Block:
            type = "text"
            text = '{"summary":"ok","is_window_visible":true,"ui_issues":[],"critical_issue_count":0}'

        class _Msg:
            content = [_Block()]

        class _Client:
            def __init__(self, **kw):
                self.messages = SimpleNamespace(create=lambda **kw: _Msg())

        fake_anthropic = SimpleNamespace(Anthropic=_Client)
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        result = analyze_screenshot(shot)
        assert result.success is True

    def test_analyze_screenshot_skips_when_no_path_available(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Provider 미지원 + 키 부재 → success=False (→ VISION_UNAVAILABLE/SKIP, FAIL 아님)."""
        shot = tmp_path / "s.png"
        shot.write_bytes(b"\x89PNG fake")
        import src.agents.qa.gui_test_executor as G
        monkeypatch.setattr(G, "_is_anthropic_available", lambda: True)
        monkeypatch.setattr(G, "_resolve_anthropic_api_key", lambda explicit=None: None)
        result = analyze_screenshot(shot)
        assert result.success is False
        assert "미설정" in (result.error_message or "") or "불가" in (result.error_message or "")


# =============================================================================
# 수정1/2/4 (배선). scripts/run.py — web 디스패치 + artifact_category 전달
# =============================================================================
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_p17", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_p17"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


class TestRunPyWiring:
    def test_is_web_vision_target(self, run_mod) -> None:
        assert run_mod._is_web_vision_target(Path("dist/index.html")) is True
        assert run_mod._is_web_vision_target(Path("page.htm")) is True
        assert run_mod._is_web_vision_target(Path("App.exe")) is False
        assert run_mod._is_web_vision_target(Path("main.py")) is False

    def test_run_vision_qa_full_dispatches_web(self, run_mod, tmp_path, monkeypatch) -> None:
        """web 타깃(dist/index.html) → run_web_vision_qa(dist_dir=부모) 디스패치."""
        dist = tmp_path / "dist"
        dist.mkdir()
        index = dist / "index.html"
        index.write_text("<!doctype html>", encoding="utf-8")
        captured: dict = {}

        def _fake_web(dist_dir, output_dir, **kw):
            captured["dist_dir"] = dist_dir
            return GUITestResult(success=True, skipped=False, target_path=dist_dir)

        import src.agents.qa.web_vision_qa as WVmod
        monkeypatch.setattr(WVmod, "run_web_vision_qa", _fake_web)
        # 데스크탑 경로가 잘못 불리면 실패하도록
        import src.agents.qa.gui_test_executor as G
        monkeypatch.setattr(
            G, "run_gui_test",
            lambda **kw: pytest.fail("web 타깃인데 desktop run_gui_test 호출됨"),
        )
        result = run_mod._run_vision_qa_full(index, tmp_path / "out")
        assert result is not None and result.success is True
        assert captured["dist_dir"] == dist  # exe_path.parent

    def test_run_vision_qa_full_dispatches_desktop(self, run_mod, tmp_path, monkeypatch) -> None:
        """desktop(.exe) → 기존 run_gui_test 경로 (불변)."""
        exe = tmp_path / "App.exe"
        exe.write_bytes(b"MZ")
        captured: dict = {}

        def _fake_gui(*, target_path, output_dir, **kw):
            captured["target_path"] = target_path
            return GUITestResult(success=True, skipped=False, target_path=target_path)

        import src.agents.qa.gui_test_executor as G
        monkeypatch.setattr(G, "run_gui_test", _fake_gui)
        import src.agents.qa.web_vision_qa as WVmod
        monkeypatch.setattr(
            WVmod, "run_web_vision_qa",
            lambda **kw: pytest.fail("desktop 타깃인데 web vision 호출됨"),
        )
        result = run_mod._run_vision_qa_full(exe, tmp_path / "out")
        assert result is not None and result.success is True
        assert captured["target_path"] == exe

    def test_evaluate_passes_artifact_category(self, run_mod, monkeypatch) -> None:
        """_evaluate_vision_qa_via_feedback_loop 가 artifact_category 를 evaluate 로 전달."""
        captured: dict = {}

        def _fake_eval(*, results, retry_count, max_retries, artifact_category=None):
            captured["artifact_category"] = artifact_category
            return SimpleNamespace(summary_line=lambda: "ok", should_retry=False)

        import src.workflows.qa_feedback_loop as QF
        monkeypatch.setattr(QF, "evaluate_qa_results", _fake_eval)
        run_mod._evaluate_vision_qa_via_feedback_loop(
            GUITestResult(success=True, target_path=Path("dist")),
            retry_count=0, max_retries=1, artifact_category="web",
        )
        assert captured["artifact_category"] == "web"

    def test_retry_signature_accepts_is_web(self, run_mod) -> None:
        """_retry_engineer_with_vision_feedback 가 is_web kwarg 수용 (수정3 배선)."""
        import inspect

        sig = inspect.signature(run_mod._retry_engineer_with_vision_feedback)
        assert "is_web" in sig.parameters
        assert sig.parameters["is_web"].default is False


# =============================================================================
# 리뷰 후속 — 부분 vision 실패는 결함이 아니라 미평가 → SKIP (핵심 안전 불변식)
# =============================================================================
def _seq_analyze(*results: VisionAnalysis):
    """샷마다 다른 VisionAnalysis 를 반환하는 analyze_fn (순차 소비)."""
    it = iter(results)

    def _fn(shot, **kw):
        try:
            return next(it)
        except StopIteration:
            return _vision(success=True, critical=0)
    return _fn


class TestPartialVisionFailure:
    def _dist(self, tmp_path: Path) -> Path:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
        return dist

    def test_partial_failure_no_critical_skips_not_fail(self, tmp_path: Path) -> None:
        """다중 샷 중 일부만 vision 실패(critical 0) → 실 결함 아님 → SKIP (success=False 금지).

        리뷰 confirmed: 이전엔 vision_all_succeeded=False → overall_success=False(skipped=False)
        → 멀쩡한 web 산출이 파괴적 재빌드로 떠밀림. 수정: critical>0 만 FAIL.
        """
        dist = self._dist(tmp_path)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(_FakeHttpd()),
            capture_fn=_fake_capture_factory([tmp_path / "s1.png", tmp_path / "s2.png"]),
            analyze_fn=_seq_analyze(
                _vision(success=True, critical=0),
                _vision(success=False, error="transient API timeout"),
            ),
        )
        assert res.skipped is True   # 미평가로 분류 (FAIL 아님)
        assert res.success is False
        assert "미평가" in (res.error_message or "")

    def test_critical_defect_surfaces_even_with_partial_failure(self, tmp_path: Path) -> None:
        """샷 하나가 critical>0(실 결함)이면 다른 샷이 실패해도 FAIL → 재빌드 (불변식 (2))."""
        dist = self._dist(tmp_path)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(_FakeHttpd()),
            capture_fn=_fake_capture_factory([tmp_path / "s1.png", tmp_path / "s2.png"]),
            analyze_fn=_seq_analyze(
                _vision(success=True, critical=1),
                _vision(success=False, error="timeout"),
            ),
        )
        assert res.skipped is False
        assert res.success is False  # 실 결함 → FAIL
        assert res.total_critical_issues == 1

    def test_partial_failure_end_to_end_no_retry(self, tmp_path: Path) -> None:
        """end-to-end: 부분 실패 결과를 evaluate_qa_results 로 흘려 should_retry=False 잠금."""
        dist = self._dist(tmp_path)
        res = run_web_vision_qa(
            dist, tmp_path / "out",
            serve_fn=_fake_serve_factory(_FakeHttpd()),
            capture_fn=_fake_capture_factory([tmp_path / "s1.png", tmp_path / "s2.png"]),
            analyze_fn=_seq_analyze(
                _vision(success=True, critical=0),
                _vision(success=False, error="timeout"),
            ),
        )
        decision = evaluate_qa_results(
            results={"vision_qa": res}, retry_count=0, max_retries=3,
            artifact_category="web",
        )
        assert "vision_qa" in decision.skipped_qa_tools
        assert decision.should_retry is False  # ★ 파괴적 재빌드 미발동


# =============================================================================
# 리뷰 후속 — derive_routes 엣지 (앵커 제외 + dedup)
# =============================================================================
class TestDeriveRoutesEdges:
    def test_same_page_anchor_excluded_hash_route_kept(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(
            "<a href='#features'>f</a><a href='#pricing'>p</a>"
            "<a href='#/about'>about</a>",
            encoding="utf-8",
        )
        routes = derive_routes(tmp_path)
        assert "/#features" not in routes  # 같은 페이지 앵커 제외
        assert "/#pricing" not in routes
        assert "/#/about" in routes  # 해시 라우터 경로는 유지

    def test_dedup_relative_and_absolute(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(
            "<a href='about'>a</a><a href='/about'>b</a><a href='/about'>c</a>",
            encoding="utf-8",
        )
        routes = derive_routes(tmp_path)
        assert routes.count("/about") == 1  # 정규화 후 중복 제거


# =============================================================================
# 리뷰 후속 — _SPARequestHandler.do_GET SPA fallback 라우팅 (실 소켓 없이)
# =============================================================================
class TestSPAHandlerRouting:
    def test_client_route_falls_back_to_index(self, monkeypatch) -> None:
        """확장자 없는 경로(=클라이언트 라우트)가 파일 부재면 /index.html 로 폴백."""
        h = object.__new__(WV._SPARequestHandler)
        h.path = "/dashboard"
        monkeypatch.setattr(WV._SPARequestHandler, "translate_path",
                            lambda self, p: "/srv/dashboard")
        monkeypatch.setattr(WV.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(WV.os.path, "exists", lambda p: False)
        monkeypatch.setattr(WV.SimpleHTTPRequestHandler, "do_GET", lambda self: None)
        WV._SPARequestHandler.do_GET(h)
        assert h.path == "/index.html"

    def test_existing_asset_not_rewritten(self, monkeypatch) -> None:
        """존재하는 에셋(app.js)은 폴백 안 함 (정적 파일 그대로 서빙)."""
        h = object.__new__(WV._SPARequestHandler)
        h.path = "/assets/app.js"
        monkeypatch.setattr(WV._SPARequestHandler, "translate_path",
                            lambda self, p: "/srv/assets/app.js")
        monkeypatch.setattr(WV.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(WV.os.path, "exists", lambda p: True)
        monkeypatch.setattr(WV.SimpleHTTPRequestHandler, "do_GET", lambda self: None)
        WV._SPARequestHandler.do_GET(h)
        assert h.path == "/assets/app.js"  # 변경 없음

    def test_missing_asset_with_extension_not_rewritten(self, monkeypatch) -> None:
        """확장자 있는 경로(에셋)는 부재여도 폴백 안 함 → 정상 404 (SPA 라우트 아님)."""
        h = object.__new__(WV._SPARequestHandler)
        h.path = "/missing.css"
        monkeypatch.setattr(WV._SPARequestHandler, "translate_path",
                            lambda self, p: "/srv/missing.css")
        monkeypatch.setattr(WV.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(WV.os.path, "exists", lambda p: False)
        monkeypatch.setattr(WV.SimpleHTTPRequestHandler, "do_GET", lambda self: None)
        WV._SPARequestHandler.do_GET(h)
        assert h.path == "/missing.css"  # 확장자 있음 → 폴백 안 함


# =============================================================================
# 리뷰 후속 — AgentSDKProvider.generate_vision streaming-dict 멀티모달 (修正1 핵심)
# =============================================================================
class TestGenerateVisionStreaming:
    def test_image_and_text_blocks_streamed_and_text_returned(self, monkeypatch) -> None:
        """generate_vision 이 image+text content block 을 streaming-dict 로 흘리고 TextBlock 을 반환."""
        pytest.importorskip("claude_agent_sdk")
        import anyio

        import src.llm.agent_sdk_provider as ASP

        captured: dict = {}

        class _FakeTextBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class _FakeAssistant:
            def __init__(self, content) -> None:
                self.content = content

        async def _fake_query(*, prompt, options):
            # streaming-input(AsyncIterable[dict]) 소비 → 메시지 캡처
            async for msg in prompt:
                captured["message"] = msg
            captured["options"] = options
            yield _FakeAssistant(content=[_FakeTextBlock('{"summary":"ok"}')])

        monkeypatch.setattr(ASP, "query", _fake_query)
        monkeypatch.setattr(ASP, "AssistantMessage", _FakeAssistant)
        monkeypatch.setattr(ASP, "TextBlock", _FakeTextBlock)

        provider = ASP.AgentSDKProvider(model="claude-haiku-4-5-20251001")

        async def _run() -> str:
            return await provider.generate_vision(
                "스크린샷 평가", [("QkFTRTY0", "image/png")]
            )

        text = anyio.run(_run)
        assert text == '{"summary":"ok"}'
        # streaming-dict 구조 검증
        msg = captured["message"]
        assert msg["type"] == "user"
        content = msg["message"]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] == "QkFTRTY0"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[-1]["type"] == "text"
        assert "스크린샷 평가" in content[-1]["text"]


# =============================================================================
# 리뷰 후속 — 修正3 web retry 행위 검증 (web 코드 추출/프롬프트/재빌드 라우팅)
# =============================================================================
class TestRetryWebRebuild:
    def test_is_web_retry_uses_web_extraction_and_prompt(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """is_web=True → GUI Code Generator + web revision 프롬프트 + web 언어 추출 → web 재빌드."""
        run_mod = _load_run_module()
        import crewai

        from src.tests.conftest import FakeProvider  # noqa: F401 (autouse 보장용)

        # prev_result: web 산출 (gui_code_output = web markdown)
        prev = SimpleNamespace(
            saved_code_files=[],
            saved_dir=tmp_path,
            gui_code_output="```ts\n// file: src/main.ts\nconsole.log('x');\n```",
            ui_spec="", design_tokens="", engineer_output="",
        )
        vision = SimpleNamespace(success=False, skipped=False,
                                 summary_line=lambda: "[GUI_TEST FAIL] critical=1")

        # build_feedback_message_for_engineer → 고정 문자열
        import src.workflows.qa_feedback_loop as QF
        monkeypatch.setattr(QF, "build_feedback_message_for_engineer",
                            lambda decision, full_qa_reports=None: "# feedback\n- 결함\n")

        # CrewAI Task/Crew mock — revision_task.description 캡처
        captured: dict = {}

        def _fake_task(**kwargs):
            captured["description"] = kwargs.get("description", "")
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(crewai, "Task", _fake_task)
        fake_crew = SimpleNamespace(kickoff=lambda: None)
        monkeypatch.setattr(crewai, "Crew", lambda **kw: fake_crew)

        # engineer factory — gui generator 가 선택돼야 함
        called: list[str] = []
        import src.agents.design.gui_code_generator as gcg
        import src.agents.engineering as eng
        monkeypatch.setattr(gcg, "create_gui_code_generator_agent",
                            lambda **kw: (called.append("gui"), SimpleNamespace(role="gui"))[1])
        monkeypatch.setattr(eng, "create_python_engineer_agent",
                            lambda **kw: (called.append("cli"), SimpleNamespace(role="cli"))[1])

        # task_output_text → web markdown
        import src.workflows._common as common
        monkeypatch.setattr(common, "task_output_text",
                            lambda task: "```ts\n// file: src/main.ts\nconsole.log('fixed');\n```")

        # _extract_code_blocks → languages/preserve_tree 캡처 + dist/index.html 생성
        import src.workflows.analyze_and_implement as AAI

        def _fake_extract(md, code_dir, *, languages=None, preserve_tree=False):
            captured["languages"] = languages
            captured["preserve_tree"] = preserve_tree
            Path(code_dir).mkdir(parents=True, exist_ok=True)
            f = Path(code_dir) / "main.ts"
            f.write_text("console.log('fixed');", encoding="utf-8")
            return [f]

        monkeypatch.setattr(AAI, "_extract_code_blocks", _fake_extract)

        # run_build_workflow → web dist/index.html 산출 (web 재빌드 결과)
        dist_index = tmp_path / "retry_01" / "code" / "dist" / "index.html"
        dist_index.parent.mkdir(parents=True, exist_ok=True)
        dist_index.write_text("<!doctype html>", encoding="utf-8")
        import src.workflows.build_workflow as bw
        monkeypatch.setattr(
            bw, "run_build_workflow",
            lambda **kw: SimpleNamespace(
                executor_result=SimpleNamespace(exe_path=dist_index, success=True)
            ),
        )

        ret = run_mod._retry_engineer_with_vision_feedback(
            prev_result=prev, vision_result=vision, user_request="3D 뷰어",
            outputs_dir=tmp_path, retry_index=1, max_retries=1, is_web=True,
        )

        # ① web 재빌드 산출(dist/index.html) 반환
        assert ret == dist_index
        # ② GUI Code Generator 선택 (python_engineer 아님)
        assert called == ["gui"]
        # ③ web 언어 + 서브트리 보존 추출
        assert captured["languages"] == AAI._WEB_CODE_LANGS
        assert captured["preserve_tree"] is True
        # ④ web revision 프롬프트 (npm 빌드 + // file: 규약, python <entry>.py 아님)
        assert "npm run build" in captured["description"]
        assert "// file:" in captured["description"]
        # gui_code_output 본문이 prior context 로 전달됨
        assert "src/main.ts" in captured["description"]
