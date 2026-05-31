# -*- coding: utf-8 -*-
"""P11 npm 설치 --legacy-peer-deps 회귀 test (v13 Phase 6.E).

출처: P10 후속 격리 빌드 검증.

배경:
    P10 으로 package.json/tsconfig/src 서브트리 정상 산출 + npm install→vite build→dist/
    경로 확인. 단 LLM manifest 가 web-ifc-three(peer three@^0.149) ↔ three@0.160 처럼
    peer 범위 불일치를 흔히 내 기본 npm install 이 ERESOLVE 로 실패 → dist/ 미생성.
    `--legacy-peer-deps` 로 peer 충돌을 경고로 강등 → 설치 성공 → npm run build 성공 확인.

처방 (P11): _default_npm_build_runner 의 설치 명령(npm ci · npm install 폴백)에
    --legacy-peer-deps 추가. npm run build 단계 불변. web 빌드 경로 전용.

검증:
    P11-T1. npm ci 명령에 --legacy-peer-deps 포함.
    P11-T2. npm install 폴백(ci 실패 시) 명령에 --legacy-peer-deps 포함.
    P11-T3. npm run build 명령은 불변 (--legacy-peer-deps 없음).
    P11-T4. web-only — runner 는 _run_web_build(web 경로)만 사용; npm 미설치 graceful 불변.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.workflows.build_workflow as bw
from src.workflows.build_workflow import _default_npm_build_runner, _run_web_build


def _install_a_fake_npm(monkeypatch, *, ci_returncode: int):
    """shutil.which→'npm' + subprocess.run 레코더 주입. 기록된 argv 목록 반환."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        # ci 는 ci_returncode, install/build 는 성공(0)
        if "ci" in cmd:
            rc = ci_returncode
        else:
            rc = 0
        return SimpleNamespace(returncode=rc, stdout="ok", stderr="")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "npm")
    monkeypatch.setattr(bw.subprocess, "run", fake_run)
    return calls


# =============================================================================
# P11-T1. npm ci 에 --legacy-peer-deps
# =============================================================================
class TestT1CiLegacyPeerDeps:
    def test_npm_ci_has_legacy_peer_deps(self, tmp_path: Path, monkeypatch) -> None:
        calls = _install_a_fake_npm(monkeypatch, ci_returncode=0)  # ci 성공 → install 폴백 없음
        _default_npm_build_runner(tmp_path, 60)
        ci = next((c for c in calls if "ci" in c), None)
        assert ci is not None
        assert "--legacy-peer-deps" in ci
        # npm install 폴백은 실행 안 됨 (ci 성공)
        assert not any("install" in c for c in calls)


# =============================================================================
# P11-T2. npm install 폴백에 --legacy-peer-deps
# =============================================================================
class TestT2InstallFallbackLegacyPeerDeps:
    def test_install_fallback_has_legacy_peer_deps(self, tmp_path: Path, monkeypatch) -> None:
        calls = _install_a_fake_npm(monkeypatch, ci_returncode=1)  # ci 실패 → install 폴백
        _default_npm_build_runner(tmp_path, 60)
        install = next((c for c in calls if "install" in c), None)
        assert install is not None
        assert "--legacy-peer-deps" in install


# =============================================================================
# P11-T3. npm run build 불변
# =============================================================================
class TestT3BuildUnchanged:
    def test_build_command_has_no_legacy_peer_deps(self, tmp_path: Path, monkeypatch) -> None:
        calls = _install_a_fake_npm(monkeypatch, ci_returncode=0)
        _default_npm_build_runner(tmp_path, 60)
        build = next((c for c in calls if "run" in c and "build" in c), None)
        assert build is not None
        assert build[-2:] == ["run", "build"]  # [npm, run, build] — 플래그 미부착
        assert "--legacy-peer-deps" not in build


# =============================================================================
# P11-T4. web-only / graceful 불변
# =============================================================================
class TestT4WebOnlyAndGraceful:
    def test_npm_missing_graceful_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)  # npm 미설치
        ok, log, elapsed = _default_npm_build_runner(tmp_path, 60)
        assert ok is False
        assert "npm 미설치" in log
        assert elapsed == 0.0

    def test_runner_used_only_via_run_web_build(self, tmp_path: Path) -> None:
        # web 경로(_run_web_build)에 주입된 runner 만 호출 — 설치 명령 변경이 web 격리됨.
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        called = {"n": 0}

        def fake_runner(cd: Path, timeout: int):
            called["n"] += 1
            return False, "stub", 0.0

        _run_web_build([code_dir / "vite.config.ts"], tmp_path, npm_runner=fake_runner)
        assert called["n"] == 1  # 주입 runner 만 (실 npm 미경유)

    def test_install_success_returns_build_status(self, tmp_path: Path, monkeypatch) -> None:
        # ci 성공 + build 성공 → ok=True 반환 (정상 흐름 회귀 0)
        calls = _install_a_fake_npm(monkeypatch, ci_returncode=0)
        ok, log, elapsed = _default_npm_build_runner(tmp_path, 60)
        assert ok is True
        assert any("--legacy-peer-deps" in c for c in calls)
