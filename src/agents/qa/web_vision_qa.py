# -*- coding: utf-8 -*-
"""web(vite/SPA) 산출물 자동 시각 QA (v13 P17 — 수정1/2).

빌드된 ``dist/`` 를 로컬 정적 서버(SPA fallback)로 띄우고, headless 브라우저
(Playwright Chromium)로 랜딩 + 주요 라우트를 캡처한 뒤, 기존 vision 평가
(``gui_test_executor.analyze_screenshot`` — claude-code-default 우선)로 시각 결함을
판정한다. 결과는 데스크탑 GUI 검증과 동일한 ``GUITestResult`` 로 합산해 호출 측
(qa_feedback_loop)이 일관되게 소비한다.

graceful skip (수정2) — 다음 중 하나라도면 ``skipped=True`` (FAIL 아님) 반환 →
qa_feedback_loop 가 retry-rebuild 를 *발동하지 않는다*:
    - Playwright/브라우저 미설치 (import 실패 또는 launch 시 Executable 부재)
    - dist 부재 / 정적 서버 기동 실패
    - 캡처 0장 (navigate/screenshot 실패)
    - vision 평가 경로 전부 불가 (claude-code-default + ANTHROPIC_API_KEY 모두 부재)

데스크탑(.exe) 경로는 ``gui_test_executor.run_gui_test`` 가 담당하며 본 모듈과 무관
(불변). 캡처가 *실제로 성공*해 vision 이 결함을 찾으면 ``success=False`` (skipped 아님)
→ web 자가수정 retry(=web 재빌드)로 이어진다 (수정3).

테스트 안전성:
    - 모든 외부 호출(정적 서버 bind, Playwright launch)은 주입 가능한 함수
      (``serve_fn`` / ``capture_fn`` / ``analyze_fn``)로 분리 → 단위 테스트는 실
      소켓/브라우저 없이 mock 으로 검증. conftest 는 소켓을 차단하지 않으므로
      (Windows ProactorEventLoop 호환) 본 모듈 테스트는 반드시 주입/monkeypatch 로
      외부 호출을 막아야 한다.
"""

from __future__ import annotations

import functools
import os
import re
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

from src.agents.qa.gui_test_executor import (
    DEFAULT_VISION_MODEL,
    GUITestResult,
    VisionAnalysis,
    analyze_screenshot,
)

_DEFAULT_WAIT_MS = 1500
_DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
_DEFAULT_NAV_TIMEOUT_MS = 15000
_MAX_ROUTES = 5

# 캡처/서빙/분석 함수의 타입 별칭 (주입 가능 — 테스트에서 mock).
ServeFn = Callable[[Path], "tuple[Any, str]"]
CaptureFn = Callable[..., "tuple[list[Path], str, Optional[str]]"]
AnalyzeFn = Callable[..., VisionAnalysis]


# ---------------------------------------------------------------------------
# Optional 의존성 — Playwright 가용성
# ---------------------------------------------------------------------------
def _is_playwright_available() -> bool:
    """playwright(sync_api) 가 import 가능한지. 브라우저 바이너리 존재는 별도(launch 시 감지)."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401,PLC0415

        return True
    except Exception:  # noqa: BLE001 — 미설치/환경 문제 전부 graceful
        return False


# ---------------------------------------------------------------------------
# 라우트 도출 — 랜딩 + index.html 의 동일 출처 경로 (best-effort)
# ---------------------------------------------------------------------------
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def derive_routes(dist_dir: Path) -> list[str]:
    """캡처할 라우트 목록(항상 랜딩 "/" 포함). index.html 의 동일 출처 경로를 best-effort 추출.

    SPA 는 라우트가 JS 런타임에 정의돼 정적 추출이 제한적이므로, 랜딩을 최소 보장하고
    index.html 의 ``href`` 중 동일 출처(상대/절대/해시 라우트)만 보강한다. 외부 링크
    (http(s)://, mailto:)·앵커(#)·에셋(.js/.css/.png 등)은 제외. 최대 ``_MAX_ROUTES`` 개.
    """
    routes: list[str] = ["/"]
    index = dist_dir / "index.html"
    if not index.is_file():
        return routes
    try:
        html = index.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return routes
    seen = {"/"}
    for href in _HREF_RE.findall(html):
        h = href.strip()
        if not h or h.startswith(("http://", "https://", "mailto:", "tel:", "//")):
            continue
        # 같은 페이지 앵커(#, #features)는 랜딩과 동일 페이지 → 캡처 슬롯 낭비. 제외.
        # 단 해시 라우터 경로(#/about)는 별도 뷰이므로 유지.
        if h.startswith("#") and not h.startswith("#/"):
            continue
        # 해시 라우트(#/about) → /#/about 그대로, 절대(/about) 그대로, 상대(about) → /about
        if h.startswith("#"):
            route = "/" + h  # "/#/about"
        elif h.startswith("/"):
            route = h
        else:
            route = "/" + h
        # 에셋(확장자 있는 정적 파일)은 라우트 아님
        tail = route.split("#", 1)[0].split("?", 1)[0]
        if "." in Path(tail).name:
            continue
        if route in seen:
            continue
        seen.add(route)
        routes.append(route)
        if len(routes) >= _MAX_ROUTES:
            break
    return routes


# ---------------------------------------------------------------------------
# 정적 서버 (SPA fallback) — dist 를 127.0.0.1:<ephemeral> 로 서빙
# ---------------------------------------------------------------------------
class _SPARequestHandler(SimpleHTTPRequestHandler):
    """존재하지 않는(=클라이언트 라우트) 경로를 index.html 로 폴백 — history 라우팅 보존."""

    def log_message(self, *args: Any) -> None:  # noqa: D102 — 콘솔 소음 억제
        return

    def do_GET(self) -> None:  # noqa: N802
        fs_path = self.translate_path(self.path)
        # 실제 파일/디렉터리면 기본 처리(에셋·index 디렉터리 인덱스 정상 동작).
        if not os.path.isdir(fs_path) and not os.path.exists(fs_path):
            # 확장자 없는 경로(=SPA 클라이언트 라우트)만 index.html 로 폴백.
            tail = self.path.split("?", 1)[0].split("#", 1)[0]
            if "." not in Path(tail).name:
                self.path = "/index.html"
        return super().do_GET()


def _serve_dist(dist_dir: Path) -> tuple[Any, str]:
    """dist_dir 를 SPA-fallback 정적 서버로 127.0.0.1:<ephemeral> 에 서빙.

    Returns:
        (httpd, base_url) — 호출 측이 finally 에서 httpd.shutdown()/server_close() 책임.
    """
    handler = functools.partial(_SPARequestHandler, directory=str(dist_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{port}"


def _shutdown_server(httpd: Any) -> None:
    """서버 graceful 종료 (예외 무시)."""
    for method in ("shutdown", "server_close"):
        try:
            getattr(httpd, method)()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Playwright 캡처 — headless Chromium 으로 라우트별 스크린샷
# ---------------------------------------------------------------------------
def _capture_with_playwright(
    base_url: str,
    routes: list[str],
    output_dir: Path,
    *,
    wait_ms: int = _DEFAULT_WAIT_MS,
    viewport: Optional[dict] = None,
    nav_timeout_ms: int = _DEFAULT_NAV_TIMEOUT_MS,
) -> tuple[list[Path], str, Optional[str]]:
    """headless Chromium 으로 base_url+route 들을 navigate 해 PNG 캡처.

    Returns:
        (screenshot_paths, terminated_by, error). 브라우저 미설치/launch 실패 등은
        ([], "skipped", reason) 로 graceful 반환 (예외 전파 안 함).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    viewport = viewport or _DEFAULT_VIEWPORT
    paths: list[Path] = []
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport=viewport)
                for i, route in enumerate(routes):
                    url = base_url.rstrip("/") + (route if route.startswith("/") else "/" + route)
                    try:
                        page.goto(url, wait_until="networkidle", timeout=nav_timeout_ms)
                    except Exception:  # noqa: BLE001 — networkidle 미달 시 best-effort 재시도
                        try:
                            page.goto(url, timeout=nav_timeout_ms)
                        except Exception:  # noqa: BLE001 — 이 라우트 캡처 스킵
                            continue
                    page.wait_for_timeout(wait_ms)
                    shot = output_dir / f"web_screenshot_{i + 1:02d}.png"
                    page.screenshot(path=str(shot))
                    if shot.exists():
                        paths.append(shot)
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001 — launch 실패(브라우저 바이너리 부재 등) → graceful skip
        return [], "skipped", f"{type(e).__name__}: {e}"
    if not paths:
        return [], "skipped", "캡처 0장 — navigate/screenshot 실패"
    return paths, "natural_exit", None


# ---------------------------------------------------------------------------
# 묶음 실행 — serve + capture + vision (graceful skip 일관)
# ---------------------------------------------------------------------------
def run_web_vision_qa(
    dist_dir: Path,
    output_dir: Path,
    *,
    skip_vision: bool = False,
    vision_model: str = DEFAULT_VISION_MODEL,
    vision_api_key: Optional[str] = None,
    wait_ms: int = _DEFAULT_WAIT_MS,
    routes: Optional[list[str]] = None,
    serve_fn: Optional[ServeFn] = None,
    capture_fn: Optional[CaptureFn] = None,
    analyze_fn: Optional[AnalyzeFn] = None,
) -> GUITestResult:
    """web dist 를 서빙→캡처→vision 평가하여 ``GUITestResult`` 로 반환.

    Args:
        dist_dir: 빌드 산출 디렉터리 (``dist/index.html`` 포함). 보통
            ``executor_result.exe_path.parent``.
        output_dir: 스크린샷/결과 저장 디렉터리.
        skip_vision: True 면 캡처만 하고 vision 평가 생략(비용/테스트).
        vision_model: vision 모델 (기본 claude-haiku).
        routes: 캡처 라우트(미지정 시 derive_routes).
        serve_fn/capture_fn/analyze_fn: 주입 가능(테스트 mock). 기본은 실제 구현.

    Returns:
        ``GUITestResult`` — 캡처/평가 불가 시 ``skipped=True`` (FAIL 아님, retry 미발동).
        실제 평가에서 시각 결함이 있으면 ``success=False`` (skipped 아님 → web 재빌드 retry).
    """
    started = time.time()
    serve_fn = serve_fn or _serve_dist
    capture_fn = capture_fn or _capture_with_playwright
    analyze_fn = analyze_fn or analyze_screenshot

    def _skip(reason: str, *, shots: Optional[list[Path]] = None,
              analyses: Optional[list[VisionAnalysis]] = None) -> GUITestResult:
        return GUITestResult(
            success=False,
            skipped=True,
            elapsed_sec=time.time() - started,
            target_path=dist_dir,
            screenshot_paths=shots or [],
            process_terminated_by="skipped",
            vision_analyses=analyses or [],
            error_message=reason,
        )

    index = dist_dir / "index.html"
    if not index.is_file():
        return _skip(f"web dist 부재 — {index} 없음. SKIPPED (FAIL 아님).")

    # Playwright 미설치 → 캡처 불가 → SKIP (단, capture_fn 주입 시엔 가용성 검사 우회 = 테스트).
    if capture_fn is _capture_with_playwright and not _is_playwright_available():
        return _skip(
            "Playwright 미설치 — web headless 캡처 불가. "
            "`pip install playwright && playwright install chromium` 후 사용. SKIPPED (FAIL 아님)."
        )

    target_routes = routes if routes is not None else derive_routes(dist_dir)

    # 1) 정적 서버 기동 (실패 시 SKIP)
    httpd: Any = None
    try:
        try:
            httpd, base_url = serve_fn(dist_dir)
        except Exception as e:  # noqa: BLE001 — 서버 기동 실패 → SKIP
            return _skip(f"정적 서버 기동 실패 — {type(e).__name__}: {e}. SKIPPED (FAIL 아님).")

        # 2) headless 캡처
        try:
            screenshot_paths, terminated_by, capture_err = capture_fn(
                base_url, target_routes, output_dir, wait_ms=wait_ms
            )
        except Exception as e:  # noqa: BLE001 — 캡처 자체 예외 → SKIP
            return _skip(f"web 캡처 예외 — {type(e).__name__}: {e}. SKIPPED (FAIL 아님).")
    finally:
        if httpd is not None:
            _shutdown_server(httpd)

    if not screenshot_paths:
        return _skip(
            f"web 캡처 0장 — {capture_err or 'navigate/screenshot 실패'}. SKIPPED (FAIL 아님)."
        )

    # 3) vision 평가 (claude-code-default 우선 — analyze_screenshot 내부)
    vision_analyses: list[VisionAnalysis] = []
    if not skip_vision:
        for shot in screenshot_paths:
            vision_analyses.append(
                analyze_fn(shot, model=vision_model, api_key=vision_api_key)
            )

    elapsed = time.time() - started
    total_critical = sum(a.critical_issue_count for a in vision_analyses)

    # ★ 핵심 verdict 원칙 (P17 안전 불변식): **critical_issue_count > 0 (실 시각 결함)만
    # success=False(=web 재빌드 retry)를 정당화한다.** vision 호출 실패(success=False, critical 0)
    # 는 '실 시각 결함'이 아니라 '평가 인프라 불가/일시 오류'이므로 절대 FAIL 로 떨어뜨리지 않는다.
    #   - critical > 0          → success=False, skipped=False  (실 결함 → 재빌드)
    #   - critical == 0 + 평가 일부/전부 실패 → SKIP (FAIL 아님 → retry 미발동)  ← 부분 실패 보호
    #   - critical == 0 + 전부 평가 성공(or skip_vision) → PASS
    # (다중 라우트 중 1장만 transient 실패해도 멀쩡한 web 산출이 재빌드로 떠밀리던 회귀 차단.)
    if total_critical > 0:
        return GUITestResult(
            success=False,
            skipped=False,
            elapsed_sec=elapsed,
            target_path=dist_dir,
            screenshot_paths=screenshot_paths,
            process_exit_code=0,
            process_terminated_by="natural_exit",
            vision_analyses=vision_analyses,
        )

    # critical 0 — 실 시각 결함 없음. 단, 평가가 하나라도 실패했으면(전부/부분 미평가) 그건
    # 결함이 아니라 *미평가* → SKIP (FAIL 아님). 평가가 전부 성공했거나 skip_vision 이면 PASS.
    if vision_analyses and not all(a.success for a in vision_analyses):
        skip_reason: Optional[str] = None
        for a in vision_analyses:
            if not a.success and a.error_message:
                skip_reason = a.error_message
                break
        n_fail = sum(1 for a in vision_analyses if not a.success)
        return _skip(
            f"web vision 부분/전체 미평가 ({n_fail}/{len(vision_analyses)} 실패, 실 시각 결함 0) "
            f"— {skip_reason or '(unknown)'}. 캡처는 정상, qa_feedback_loop 는 SKIPPED 로 처리.",
            shots=screenshot_paths,
            analyses=vision_analyses,
        )

    # 캡처 OK + (전부 평가 성공 또는 skip_vision) + critical 0 → PASS.
    return GUITestResult(
        success=len(screenshot_paths) > 0,
        skipped=False,
        elapsed_sec=elapsed,
        target_path=dist_dir,
        screenshot_paths=screenshot_paths,
        process_exit_code=0,
        process_terminated_by="natural_exit",
        vision_analyses=vision_analyses,
    )
