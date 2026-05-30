# -*- coding: utf-8 -*-
"""P7 빌드/Executor 체인 web-awareness 회귀 test (PR #238).

출처: ``docs/diagnostics/phase6e_rerun_P5_verdict_20260530.md`` — web COMPLETE 의 결정적 1순위

배경:
    P5 적용 런에서 시스템이 진짜 web BIM SPA(Three.js+web-ifc-three)를 산출했으나,
    빌드 체인이 `vite.config.ts`(TS 설정)를 Python entry 로 골라 `python vite.config.ts`
    실행 → SyntaxError → .exe SKIP. web 은 `npm run build → dist/` 인데 PyInstaller→.exe
    만 알았다. .exe 가 나온 유일한 iter 는 PyQt 드리프트(iter4) — 배포물 얻으려면 플랫폼
    위반해야 하는 구조.

수정 (P7): web 프로젝트 감지 → npm build → dist/ 경로 라우팅. desktop(.py) 은 PyInstaller 보존.

검증:
    P7-T1. web 프로젝트(package.json/vite.config.ts/.ts) → _is_web_project True (PyInstaller 경로 회피).
    P7-T2. web build → dist/ 산출을 배포물로 인정(success, exe_path=dist/index.html).
    P7-T3. Build Spec tool=Vite/npm run build → web 라우팅 (Spec 존중).
    P7-T4. desktop(PyQt .py entry) → _is_web_project False (PyInstaller 경로 보존, 회귀 0).
    P7-T5. vite.config.ts → web 라우팅 + 실패 시 web 전용 메시지(Python SyntaxError/PyInstaller 오진 아님).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.build_workflow import (
    _format_web_build_md,
    _is_web_project,
    _run_web_build,
)


# =============================================================================
# P7-T1. web 프로젝트 감지 → PyInstaller 경로 회피
# =============================================================================
class TestT1WebDetection:
    def test_web_spa_files_detected(self) -> None:
        files = [Path("code/package.json"), Path("code/vite.config.ts"), Path("code/src__main.ts")]
        assert _is_web_project(files) is True

    def test_ts_file_alone_detected(self) -> None:
        assert _is_web_project([Path("code/vite.config.ts")]) is True

    def test_index_html_detected(self) -> None:
        assert _is_web_project([Path("code/index.html"), Path("code/app.js")]) is True

    def test_run_web_build_uses_runner_not_python(self, tmp_path: Path) -> None:
        """web build 는 주입된 npm runner 만 호출 — python/PyInstaller 미경유."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        called = {"n": 0}

        def fake_runner(cd: Path, timeout: int):
            called["n"] += 1
            called["cd"] = cd
            return False, "stub", 0.0

        _run_web_build([code_dir / "vite.config.ts"], tmp_path, npm_runner=fake_runner)
        assert called["n"] == 1  # npm runner 경유 (python entry 실행 아님)
        assert called["cd"] == code_dir


# =============================================================================
# P7-T2. web build → dist/ 배포물 인정
# =============================================================================
class TestT2DistRecognized:
    def test_dist_index_html_is_deliverable(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()

        def fake_runner(cd: Path, timeout: int):
            (cd / "dist").mkdir(parents=True, exist_ok=True)
            (cd / "dist" / "index.html").write_text(
                "<!DOCTYPE html><div id='root'></div>", encoding="utf-8"
            )
            return True, "vite build ok", 2.5

        res = _run_web_build(
            [code_dir / "package.json", code_dir / "vite.config.ts"],
            tmp_path,
            npm_runner=fake_runner,
        )
        assert res.success is True
        assert res.exit_code == 0
        assert res.exe_path is not None and res.exe_path.name == "index.html"
        assert res.exe_size_bytes and res.exe_size_bytes > 0
        # summary_line() 의 success-assert(exe_path+exe_size_bytes+sha256) 통과
        assert "BUILD SUCCESS" in res.summary_line()

    def test_no_dist_is_failure(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()

        def fake_runner(cd: Path, timeout: int):
            return True, "ran but no dist", 1.0  # dist 미생성

        res = _run_web_build([code_dir / "vite.config.ts"], tmp_path, npm_runner=fake_runner)
        assert res.success is False
        assert res.exit_code == -8


# =============================================================================
# P7-T3. Build Spec tool=Vite → web 라우팅 (Spec 존중)
# =============================================================================
class TestT3BuildSpecHonored:
    def test_build_spec_vite_routes_web(self) -> None:
        spec = "도구 선택: tool=vite, entry=index.html, 빌드 명령: npm run build → dist/"
        assert _is_web_project([], build_spec=spec) is True

    def test_build_spec_web_ifc_three(self) -> None:
        assert _is_web_project([], build_spec="web-ifc-three SPA") is True

    def test_build_spec_overrides_no_files(self) -> None:
        # code_files 없어도 Spec 만으로 web 판정 (Executor 가 Spec 결정 따름)
        assert _is_web_project([], build_spec="vite") is True
        assert _is_web_project([], build_spec="PyInstaller onefile") is False


# =============================================================================
# P7-T4. desktop(PyQt) → PyInstaller 경로 보존 (회귀 0)
# =============================================================================
class TestT4DesktopPreserved:
    def test_pyqt_app_not_web(self) -> None:
        files = [Path("code/app.py"), Path("code/main_window.py"), Path("code/theme.py")]
        assert _is_web_project(files) is False

    def test_cli_single_py_not_web(self) -> None:
        assert _is_web_project([Path("code/calculator.py")]) is False

    def test_hybrid_pyqt_with_html_stays_desktop(self) -> None:
        """PyQt(app.py) + 내장 webview(index.html) hybrid → Python entry 있으니 desktop 유지."""
        files = [Path("code/app.py"), Path("code/index.html"), Path("code/viewport.py")]
        assert _is_web_project(files) is False  # app.py entry → PyInstaller 경로

    def test_web_with_only_test_py_still_web(self) -> None:
        """web 프로젝트에 test_*.py 만 섞여도(non-entry) web 유지."""
        files = [Path("code/vite.config.ts"), Path("code/package.json"), Path("code/test_main.py")]
        assert _is_web_project(files) is True


# =============================================================================
# P7-T5. vite.config.ts python 실행 오류 경로 차단 + web 전용 메시지
# =============================================================================
class TestT5PythonOnTsBlocked:
    def test_vite_config_routes_web_not_python(self) -> None:
        # 이전 버그: vite.config.ts → python entry → SyntaxError. 이제 web 라우팅.
        assert _is_web_project([Path("code/vite.config.ts")]) is True

    def test_web_failure_message_is_web_specific(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()

        def fail_runner(cd: Path, timeout: int):
            return False, "npm 미설치", 0.0

        res = _run_web_build([code_dir / "vite.config.ts"], tmp_path, npm_runner=fail_runner)
        assert res.success is False
        msg = res.error_message or ""
        # web 전용 진단 — Python SyntaxError/PyInstaller 오진 아님
        assert "SyntaxError" not in msg
        assert "npm run build" in msg
        assert "dist/" in msg

    def test_format_web_build_md(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()

        def ok_runner(cd: Path, timeout: int):
            (cd / "dist").mkdir(parents=True, exist_ok=True)
            (cd / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            return True, "ok", 1.0

        res = _run_web_build([code_dir / "package.json"], tmp_path, npm_runner=ok_runner)
        md = _format_web_build_md(res)
        assert "web build" in md
        assert "npm run build → dist/" in md
        assert "SUCCESS" in md
