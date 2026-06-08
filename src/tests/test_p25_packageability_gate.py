# -*- coding: utf-8 -*-
"""v13 P25 — 산출물 배포성 게이트 회귀 test.

진단(웹 ERP 런 alpha_run_20260605_165644): server.js 가 dist 를 정적 서빙하지 않고 /api 만 제공
+ package.json 에 start 부재 → `node server.js` 후 루트 `/` = "Cannot GET /". 전체 앱은 dev 전용
`npm run dev`(concurrently+vite) 로만 떴다. P17 시각 QA 는 dist 를 *자체* Python 정적 서버로 띄워
통과 → 배포 산출물(프로덕션 단일 명령) 미검증.

검증:
  - 게이트는 *프로덕션 단일 명령*(npm start / node server.js)으로만 검증(dev 서버 아님).
  - 이번 런 형태(서버 dist 미서빙 / 단일 명령 부재 / dev 전용) → FAIL. 수정 형태 → PASS.
  - desktop/none → SKIPPED(P23 smoke + 단일 폼팩터 계약 담당). FAIL 만 COMPLETE 차단.
  - override 는 _apply_smoke_failure_override 형제(COMPLETE 만 차단, 예산 분기, P12 conduit 재사용).
  - best-iteration 이 배포성 FAIL 산출을 COMPLETE 로 강제하지 않음.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.workflows.iterative_loop as IL
from src.agents.runtime_verification import (
    PackageabilityResult,
    analyze_web_packageability,
    run_packageability_gate,
)
from src.agents.runtime_verification.packageability_gate import (
    WebAnalysis,
    _classify_npm_command,
    _detect_listen_port,
    _resolve_runtime_command,
    _server_serves_root,
)


# ── web 프로젝트 디렉터리 빌더 ─────────────────────────────────────────────
def _web_app(
    tmp: Path,
    *,
    scripts: dict,
    server_src: str | None = None,
    server_name: str = "server.js",
    dist: bool = True,
    readme: str | None = None,
    deps: dict | None = None,
) -> Path:
    code = tmp / "code"
    code.mkdir(parents=True, exist_ok=True)
    pkg = {"name": "app", "private": True, "type": "module", "version": "1.0.0", "scripts": scripts}
    if deps is not None:
        pkg["dependencies"] = deps
    (code / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    if server_src is not None:
        sp = code / server_name
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(server_src, encoding="utf-8")
    if dist:
        (code / "dist").mkdir(exist_ok=True)
        (code / "dist" / "index.html").write_text("<!DOCTYPE html><div id=app></div>", encoding="utf-8")
    if readme is not None:
        (code / "README.md").write_text(readme, encoding="utf-8")
    return code


# server.js 변형
_SERVER_NO_DIST = (
    "import express from 'express';\n"
    "const app = express();\n"
    "app.get('/api/x', (q,r)=>r.json({}));\n"
    "app.listen(8787, ()=>console.log('api'));\n"
)
_SERVER_SERVES_DIST = (
    "import express from 'express';\nimport path from 'node:path';\n"
    "const app = express();\n"
    "app.use(express.static(path.join('dist')));\n"
    "app.get('/api/x', (q,r)=>r.json({}));\n"
    "app.get('*', (q,r)=>r.sendFile('dist/index.html'));\n"
    "app.listen(8787, ()=>console.log('up'));\n"
)
_DEV_SCRIPTS = {"dev": "concurrently -k \"npm:dev:server\" \"npm:dev:client\"", "dev:server": "node server.js", "dev:client": "vite", "build": "vite build", "preview": "vite preview"}

# server.js 가 dist 정적 서빙은 안 하지만(루트 404) build dir 도 안 가리키는 express
_SERVER_PUBLIC = (
    "import express from 'express';\n"
    "const app = express();\n"
    "app.use('/up', express.static('public'));\n"
    "app.get('/api/x', (q,r)=>r.json({}));\n"
    "app.listen(8787);\n"
)
# 비-express 정적 서빙(정규식 망라 불가 → probe 권위)
_SERVER_HTTP_MANUAL = (
    "import http from 'node:http';\nimport fs from 'fs';\n"
    "http.createServer((req,res)=>res.end(fs.readFileSync('dist/index.html'))).listen(3000);\n"
)
# 구조 신호 폴백만 보도록 probe 를 unverified 로 고정(node 없는 환경 시뮬)
_PROBE_UNVERIFIED = lambda c, a: ("unverified", None, "no node (test)")  # noqa: E731


# =============================================================================
# 1. 구조 분석 — analyze_web_packageability (probe-authoritative 모델: FAIL/PROBE/SKIPPED)
# =============================================================================
class TestStructuralAnalysis:
    def test_this_run_defect_serves_dist_false(self, tmp_path: Path) -> None:
        """이번 런(express /api-only + start 없음) → command 존재(PROBE) + serves_dist=False(고신뢰 미서빙)."""
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE"  # 명령(node server.js)은 있음 → probe 위임
        assert a.serves_dist is False  # express 정적서빙 부재 = 고신뢰
        assert a.command == "node server.js"

    def test_fixed_form_serves_dist_true(self, tmp_path: Path) -> None:
        """수정 형태(start: node server.js + express.static(dist) + SPA fallback) → serves_dist=True."""
        code = _web_app(
            tmp_path,
            scripts={"start": "node server.js", "dev": _DEV_SCRIPTS["dev"], "build": "vite build"},
            server_src=_SERVER_SERVES_DIST, readme="실행: `npm start`",
        )
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE" and a.command == "npm start"
        assert a.serves_dist is True and a.has_readme_cmd is True

    def test_start_is_dev_only_hard_fail(self, tmp_path: Path) -> None:
        """start 가 dev 전용(concurrently/vite) → 프로덕션 단일 명령 아님 → 즉시 FAIL(dev_only)."""
        code = _web_app(
            tmp_path,
            scripts={"start": "concurrently \"node server.js\" \"vite\"", "build": "vite build"},
            server_src=_SERVER_SERVES_DIST,
        )
        a = analyze_web_packageability(code)
        assert a.verdict == "FAIL" and a.signal == "dev_only"

    def test_vite_preview_with_backend_hard_fail(self, tmp_path: Path) -> None:
        """start=vite preview + 백엔드 서버(최상위) → API 미기동 → 즉시 FAIL."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"}, server_src=_SERVER_NO_DIST)
        a = analyze_web_packageability(code)
        assert a.verdict == "FAIL" and a.signal == "preview_no_backend"

    def test_vite_preview_with_backend_in_src_hard_fail(self, tmp_path: Path) -> None:
        """R: 백엔드가 src/ 하위여도 탐지 → preview+backend FAIL (false-PASS 차단)."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"},
                        server_src=_SERVER_NO_DIST, server_name="src/api.js")
        a = analyze_web_packageability(code)
        assert a.verdict == "FAIL" and a.signal == "preview_no_backend"

    def test_pure_static_spa_preview_probe(self, tmp_path: Path) -> None:
        """백엔드 없는 순수 정적 SPA + preview → 단일 명령으로 dist 서빙 → PROBE(serves_dist=True)."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"})
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE" and a.serves_dist is True

    def test_no_command_hard_fail(self, tmp_path: Path) -> None:
        """start 없음 + 서버 엔트리 없음 → 단일 명령 부재 → 즉시 FAIL(no_command)."""
        code = _web_app(tmp_path, scripts={"build": "vite build"}, dist=True)
        a = analyze_web_packageability(code)
        assert a.verdict == "FAIL" and a.signal in ("no_command", "dev_only")

    def test_no_package_json_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "code").mkdir()
        assert analyze_web_packageability(tmp_path / "code").verdict == "SKIPPED"

    def test_public_dir_static_is_undetermined(self, tmp_path: Path) -> None:
        """R(false-PASS 해소): express.static('public')(엉뚱 dir, dist/루트 미확인) → serves_dist=None → probe 위임."""
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_PUBLIC)
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE" and a.serves_dist is None


# =============================================================================
# 1b. false-FAIL 회귀 — 정규식이 못 잡는 *정당한* 배포형태는 probe 에 위임(즉시 FAIL 금지)
# =============================================================================
class TestNoFalseFail:
    """적대 리뷰 P25: 정규식-부재→FAIL 단정이 Next/SvelteKit/http.createServer 등을 영구 차단했음."""

    @pytest.mark.parametrize(
        "scripts,server,sname",
        [
            ({"dev": "next dev", "build": "next build", "start": "next start"}, None, "server.js"),  # Next.js
            ({"build": "vite build", "start": "node build"}, None, "server.js"),  # SvelteKit adapter-node
            ({"start": "node server.js"}, _SERVER_HTTP_MANUAL, "server.js"),  # http.createServer 수동
            ({"start": "tsx server.ts"}, _SERVER_SERVES_DIST, "server.ts"),  # TypeScript 엔트리
            ({"start": "vite build && node server.js"}, _SERVER_SERVES_DIST, "server.js"),  # 복합 명령
        ],
    )
    def test_legit_forms_not_hard_failed(self, tmp_path: Path, scripts, server, sname) -> None:
        """정당한 배포형태는 즉시 FAIL 되지 않고 PROBE 로 위임 → probe unverified 면 PASS(거짓 FAIL 0)."""
        code = _web_app(tmp_path, scripts=scripts, server_src=server, server_name=sname)
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE", f"{scripts} → {a.verdict}/{a.signal} (false-FAIL!)"
        # probe unverified(node 없음 시뮬) → serves_dist != False → PASS
        assert run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED).verdict == "PASS"


class TestCommandClassification:
    @pytest.mark.parametrize(
        "cmd,kind",
        [
            ("vite", "dev"),
            ("vite dev", "dev"),
            ("vite build", "build"),
            ("vite preview", "preview"),
            ("node server.js", "node-server"),
            ("concurrently \"a\" \"b\"", "dev"),
            ("nodemon server.js", "dev"),
            ("npm run dev", "dev"),
            ("serve dist", "static-server"),
            ("http-server dist", "static-server"),
            ("", "empty"),
            # 프레임워크 프로덕션 서버 / 복합 / TS — false-FAIL 방지
            ("next start", "framework"),
            ("astro preview", "framework"),
            ("nuxt start", "framework"),
            ("node build", "node-server"),
            ("tsx server.ts", "node-server"),
            ("vite build && node server.js", "node-server"),  # 복합 → 마지막 서빙 세그먼트
            ("vite build && vite preview", "preview"),
        ],
    )
    def test_classify(self, cmd: str, kind: str) -> None:
        assert _classify_npm_command(cmd) == kind


# =============================================================================
# 2. 게이트 — run_packageability_gate (구조 + 주입 probe + 비대상 SKIP)
# =============================================================================
class TestRunGate:
    def test_hard_fail_no_probe(self, tmp_path: Path) -> None:
        """명령 자체 결함(dev_only)은 런타임 probe(spawn) 없이 즉시 FAIL — must-fix 본문 포함."""
        spawned = []
        code = _web_app(tmp_path, scripts={"start": "concurrently a b", "build": "vite build"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: spawned.append(1) or ("loaded", 1, ""))
        assert r.verdict == "FAIL" and r.signal == "dev_only"
        assert spawned == []  # 명령 결함 → probe 미호출
        assert "express.static" in r.error_excerpt

    def test_this_run_express_no_static_unverified_fail(self, tmp_path: Path) -> None:
        """이번 런(express 정적서빙 부재) + probe unverified(no-node) → 고신뢰 FAIL(결정론 catch)."""
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        r = run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED)
        assert r.verdict == "FAIL" and r.signal == "not_serving_dist"
        assert "Cannot GET" in r.reason  # 진단은 reason 에
        assert "express.static" in r.error_excerpt  # must-fix 계약은 excerpt 에

    def test_this_run_probe_cannot_get_fail(self, tmp_path: Path) -> None:
        """이번 런 + 실 probe 가 루트 404 확인 → FAIL(런타임 권위)."""
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("cannot_get", 8787, "HTTP 404: Cannot GET /"))
        assert r.verdict == "FAIL" and r.signal == "root_cannot_get"

    def test_probe_loaded_overrides_structural_false(self, tmp_path: Path) -> None:
        """런타임이 루트 로드를 확인하면(휴리스틱 False여도) PASS — probe 가 권위."""
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("loaded", 8787, "200 OK"))
        assert r.verdict == "PASS" and r.signal == "runtime_ok"

    def test_structural_ok_probe_loaded_pass(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("loaded", 8787, "200 OK"))
        assert r.verdict == "PASS" and r.signal == "runtime_ok" and r.root_status == "loaded"

    def test_structural_ok_probe_cannot_get_fail(self, tmp_path: Path) -> None:
        """구조는 그럴듯한데 런타임 루트가 Cannot GET → FAIL (probe 가 권위)."""
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("cannot_get", 8787, "HTTP 404: Cannot GET /"))
        assert r.verdict == "FAIL" and r.signal == "root_cannot_get"

    def test_structural_ok_probe_unverified_pass(self, tmp_path: Path) -> None:
        """probe 환경 불가(node/deps 부재)면 거짓 FAIL 금지 → 구조 PASS 유지."""
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("unverified", None, "node 미설치"))
        assert r.verdict == "PASS" and r.root_status == "unverified"

    def test_structural_ok_probe_server_error_fail(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", _probe=lambda c, a: ("server_error", 8787, "기동 직후 종료"))
        assert r.verdict == "FAIL" and r.signal == "server_error"

    def test_run_probe_false_structural_only(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        r = run_packageability_gate(code, "web", run_probe=False)
        assert r.verdict == "PASS" and r.root_status == "unverified"

    def test_desktop_and_none_skipped(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        assert run_packageability_gate(code, "desktop").verdict == "SKIPPED"
        assert run_packageability_gate(code, "unspecified").verdict == "SKIPPED"

    def test_missing_code_dir_skipped(self, tmp_path: Path) -> None:
        assert run_packageability_gate(tmp_path / "nope", "web").verdict == "SKIPPED"

    def test_gate_exception_graceful_skip(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)

        def _boom(c, a):
            raise RuntimeError("probe 폭발")

        r = run_packageability_gate(code, "web", _probe=_boom)
        # probe 예외는 게이트 try/except 가 흡수 → SKIPPED (cycle 비차단)
        assert r.verdict == "SKIPPED"

    def test_result_duck_typing_contract(self) -> None:
        """PackageabilityResult 가 smoke_result override duck-typing 계약을 만족."""
        r = PackageabilityResult("FAIL", reason="x", signal="s", error_excerpt="e", command="c")
        for attr in ("verdict", "error_excerpt", "reason", "signal", "exit_code"):
            assert hasattr(r, attr)
        assert r.failed and not r.passed


# =============================================================================
# 3. override — _apply_deployability_failure_override (smoke override 형제)
# =============================================================================
def _complete(must_fix=0):
    return IL.JudgmentDecision(
        verdict=IL.Verdict.COMPLETE, blocked_cause=IL.BlockedCause.NONE,
        reason="ok", next_action="", must_fix_count=must_fix,
    )


def _fail_result():
    return PackageabilityResult("FAIL", reason="서버 dist 미서빙", signal="not_serving_dist",
                                command="node server.js", error_excerpt="배포성 계약 미충족 ...")


class TestOverride:
    def test_complete_plus_fail_budget_improve(self) -> None:
        out = IL._apply_deployability_failure_override(
            _complete(), _fail_result(), gap=SimpleNamespace(iteration=1), max_iterations=5,
        )
        assert out.verdict == IL.Verdict.IMPROVE_NEEDED
        assert out.must_fix_count >= 1
        assert "배포성 계약" in out.next_action

    def test_complete_plus_fail_exhausted_blocked(self) -> None:
        out = IL._apply_deployability_failure_override(
            _complete(), _fail_result(), gap=SimpleNamespace(iteration=5), max_iterations=5,
        )
        assert out.verdict == IL.Verdict.BLOCKED
        assert out.blocked_cause == IL.BlockedCause.BUILD_FAILED

    @pytest.mark.parametrize("res", [None, PackageabilityResult("PASS"), PackageabilityResult("SKIPPED")])
    def test_complete_plus_pass_skip_none_unchanged(self, res) -> None:
        out = IL._apply_deployability_failure_override(_complete(), res, gap=SimpleNamespace(iteration=1), max_iterations=5)
        assert out.verdict == IL.Verdict.COMPLETE  # 회귀 0

    def test_non_complete_unchanged(self) -> None:
        """COMPLETE 아닌 decision 은 FAIL 이어도 건드리지 않는다 (오직 COMPLETE 만 차단)."""
        imp = IL.JudgmentDecision(verdict=IL.Verdict.IMPROVE_NEEDED, blocked_cause=IL.BlockedCause.NONE,
                                  reason="x", next_action="y", must_fix_count=2)
        out = IL._apply_deployability_failure_override(imp, _fail_result(), gap=SimpleNamespace(iteration=1), max_iterations=5)
        assert out is imp

    def test_override_exception_returns_original(self) -> None:
        bad = SimpleNamespace(verdict=IL.Verdict.COMPLETE)  # must_fix_count 없음 → AttributeError 경로
        # FAIL 결과지만 override 내부 예외 → 원본 반환 (cycle 비차단)
        res = PackageabilityResult("FAIL")
        out = IL._apply_deployability_failure_override(bad, res, gap=SimpleNamespace(iteration=1), max_iterations=5)
        assert out is bad


# =============================================================================
# 4. loop 노드 — _run_packageability_gate (게이팅·stale·web 한정)
# =============================================================================
def _web_chain(code_dir: Path, saved_dir: Path | None = None):
    exec_res = SimpleNamespace(
        success=True, exit_code=0, command=["npm", "run", "build"],
        exe_path=code_dir / "dist" / "index.html",
    )
    return SimpleNamespace(executor_result=exec_res, saved_dir=saved_dir)


class TestLoopNode:
    def test_disabled_pure_noop(self, tmp_path: Path) -> None:
        assert IL._run_packageability_gate({"enable_packageability": False}) == {}

    def test_non_web_intent_cleared(self, tmp_path: Path) -> None:
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        out = IL._run_packageability_gate({"platform_intent": "desktop", "chain_result": _web_chain(code)})
        assert out == {"deployability_result": None}

    def test_build_failed_cleared(self, tmp_path: Path) -> None:
        chain = SimpleNamespace(executor_result=SimpleNamespace(success=False), saved_dir=None)
        out = IL._run_packageability_gate({"platform_intent": "web", "chain_result": chain})
        assert out == {"deployability_result": None}

    def test_web_build_runs_gate_fail(self, tmp_path: Path) -> None:
        """web 빌드 성공 + 이번 런 결함 코드 → 게이트 FAIL 결과 보존 + artifact 작성."""
        code = _web_app(tmp_path, scripts=_DEV_SCRIPTS, server_src=_SERVER_NO_DIST)
        saved = tmp_path / "wf"
        saved.mkdir()
        out = IL._run_packageability_gate({
            "platform_intent": "web", "enable_packageability": True,
            "chain_result": _web_chain(code, saved_dir=saved),
        })
        assert out["deployability_result"].verdict == "FAIL"
        arts = list(saved.glob("28_deployability_*.md"))
        assert len(arts) == 1 and "fail" in arts[0].name

    def test_web_build_fixed_passes(self, tmp_path: Path) -> None:
        """수정 형태(node_modules 부재 → probe unverified) → 구조 PASS."""
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=_SERVER_SERVES_DIST)
        out = IL._run_packageability_gate({"platform_intent": "web", "chain_result": _web_chain(code)})
        assert out["deployability_result"].verdict == "PASS"

    def test_non_web_build_result_cleared(self, tmp_path: Path) -> None:
        """platform_intent=web 인데 빌드 산출이 .exe(데스크탑) → web 빌드 아님 → clear."""
        chain = SimpleNamespace(
            executor_result=SimpleNamespace(success=True, command=["pyinstaller"], exit_code=0,
                                            exe_path=tmp_path / "app.exe"),
            saved_dir=None,
        )
        out = IL._run_packageability_gate({"platform_intent": "web", "chain_result": chain})
        assert out == {"deployability_result": None}


# =============================================================================
# 5. best-iteration — 배포성 FAIL 을 COMPLETE 로 강제하지 않음
# =============================================================================
class TestBestIterationGate:
    def _record(self, deploy_fail_result):
        chain = SimpleNamespace(
            saved_code_files=[Path("a.ts")],
            executor_result=SimpleNamespace(success=True, exe_path=Path("dist/index.html")),
        )
        gap = SimpleNamespace(iteration=2, unsatisfied_blockers=0, unsatisfied_majors=0)
        dec = IL.JudgmentDecision(verdict=IL.Verdict.IMPROVE_NEEDED, blocked_cause=IL.BlockedCause.NONE,
                                  reason="배포성 FAIL override", next_action="fix", must_fix_count=1,
                                  domain_unsatisfied=[])
        return IL._iteration_quality(chain, gap, dec, "web", deployability_result=deploy_fail_result)

    def test_record_marks_deployability_fail(self) -> None:
        rec = self._record(PackageabilityResult("FAIL"))
        assert rec["deployability_fail"] is True
        rec_ok = self._record(PackageabilityResult("PASS"))
        assert rec_ok["deployability_fail"] is False
        assert rec["score"] < rec_ok["score"]  # FAIL 패널티

    def test_record_none_byte_identical(self) -> None:
        """deployability_result None → 기존 동작 (deployability_fail=False), 회귀 0."""
        rec = self._record(None)
        assert rec["deployability_fail"] is False

    def test_resolve_best_does_not_force_complete_on_deploy_fail(self) -> None:
        """build_ok+domain_ok 이어도 배포성 FAIL iteration 은 COMPLETE 로 강제되지 않는다."""
        rec = self._record(PackageabilityResult("FAIL"))
        rec["build_ok"] = True
        rec["domain_ok"] = True
        rec["degenerate"] = False
        final_state = {"chain_result": rec["chain_result"], "execution_result": None,
                       "iteration_records": [rec], "iteration": 2}
        gap = SimpleNamespace(iteration=2)
        _, _, _, sel = IL._resolve_best_output(final_state, _complete(), gap)
        assert sel.verdict != IL.Verdict.COMPLETE  # override 한 IMPROVE_NEEDED 유지

    def test_resolve_best_forces_complete_when_deployable(self) -> None:
        """대조군: 배포성 FAIL 아니면 기존대로 build_ok+domain_ok → COMPLETE 강제 (회귀 0)."""
        rec = self._record(PackageabilityResult("PASS"))
        rec["build_ok"] = True
        rec["domain_ok"] = True
        rec["degenerate"] = False
        final_state = {"chain_result": rec["chain_result"], "execution_result": None,
                       "iteration_records": [rec], "iteration": 2}
        gap = SimpleNamespace(iteration=2)
        _, _, _, sel = IL._resolve_best_output(final_state, _complete(), gap)
        assert sel.verdict == IL.Verdict.COMPLETE


# =============================================================================
# 6. codegen 계약 — 생성 지시 텍스트 존재 + 회귀 0
# =============================================================================
class TestContracts:
    def test_web_directive_has_packageability_contract(self) -> None:
        from src.workflows.analyze_and_implement import _build_web_platform_directive
        d = _build_web_platform_directive()
        for tok in ["배포성 계약", "express.static", "Cannot GET", "start", "dev 전용", "README"]:
            assert tok in d, tok

    def test_platform_constraint_web_mirror(self) -> None:
        c = IL._build_platform_constraint("web")
        for tok in ["배포성", "dist", "static", "dev 전용", "단일"]:
            assert tok in c, tok

    def test_platform_constraint_desktop_single_formfactor(self) -> None:
        c = IL._build_platform_constraint("desktop")
        assert "단일 폼팩터" in c and "혼재 금지" in c

    def test_platform_constraint_unspecified_empty(self) -> None:
        assert IL._build_platform_constraint("unspecified") == ""  # 회귀 0


# =============================================================================
# 7. 헬퍼 단위 — 포트 탐지 / 명령 해석 / 정적서빙 3-상태 / 정규식 ReDoS
# =============================================================================
class TestHelpers:
    @pytest.mark.parametrize(
        "src,port",
        [
            ("app.listen(8787)", 8787),
            ("app.listen(process.env.PORT || 3000)", 3000),
            ("app.listen(PORT)\nconst PORT=4000", 4000),
            ("server.listen( '8080' )", 8080),
            ("app.listen(process.env.PORT)", None),  # 리터럴 없음
        ],
    )
    def test_detect_listen_port(self, src: str, port) -> None:
        assert _detect_listen_port(src) == port

    def test_serves_dist_tristate(self) -> None:
        assert _server_serves_root(_SERVER_SERVES_DIST) is True  # express.static(dist)
        assert _server_serves_root(_SERVER_NO_DIST) is False  # express, 정적서빙 전무
        assert _server_serves_root(_SERVER_PUBLIC) is None  # static('public') 엉뚱 dir
        assert _server_serves_root(_SERVER_HTTP_MANUAL) in (True, None)  # 비-express → True/None(거짓 False 금지)

    def test_resolve_runtime_command(self) -> None:
        assert _resolve_runtime_command(WebAnalysis("PROBE", "", "", command="npm start"))[1:] == ["start"]
        assert _resolve_runtime_command(WebAnalysis("PROBE", "", "", command="node server.js")) == ["node", "server.js"]

    def test_regex_no_redos(self) -> None:
        """정규식 휴리스틱이 긴 적대 입력(공백/대시 런)에서 선형 — P24 ReDoS 4건 전력 대비."""
        big = ("a" * 60000) + (" " * 30000) + "\n.listen(" + ("9" * 20000)
        t0 = time.perf_counter()
        _server_serves_root(big)
        _detect_listen_port(big)
        _classify_npm_command(big)
        assert time.perf_counter() - t0 < 1.0


# =============================================================================
# 8. 실 런타임 probe 통합 — *문서화된 단일 명령* 실제 spawn (node 있을 때만)
# =============================================================================
_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not _NODE, reason="node 미설치 — 실 probe 통합 테스트 격리")
class TestRealProbeIntegration:
    """적대 리뷰 #11: 실 spawn 경로(_default_web_probe)가 단위테스트로 검증 안 됐음.

    의존성 없는 *순수 node* 서버로 실제 기동/루트 로드/종료를 검증 — express 불요(node_modules 없음).
    _node_modules_ready 가드를 통과시키려 더미 node_modules 를 둔다.
    """

    @staticmethod
    def _free_port() -> int:
        """ephemeral 빈 포트 할당(고정 포트 flaky 제거 — R3 #9)."""
        import socket
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
        finally:
            s.close()

    def _pure_node_app(self, tmp: Path, *, serves_root: bool, port: int) -> Path:
        code = tmp / "code"
        code.mkdir(parents=True, exist_ok=True)
        (code / "package.json").write_text(json.dumps(
            {"name": "p", "type": "commonjs", "scripts": {"start": "node server.js"}}), encoding="utf-8")
        (code / "dist").mkdir(exist_ok=True)
        (code / "dist" / "index.html").write_text("<!DOCTYPE html><div id=app>OK</div>", encoding="utf-8")
        (code / "node_modules").mkdir(exist_ok=True)  # _node_modules_ready 가드 통과용
        (code / "node_modules" / ".keep").write_text("", encoding="utf-8")
        if serves_root:
            body = (
                "const http=require('http');const fs=require('fs');const path=require('path');\n"
                f"http.createServer((req,res)=>{{if(req.url==='/'||req.url==='/index.html')"
                "{res.writeHead(200,{'Content-Type':'text/html'});res.end(fs.readFileSync(path.join(__dirname,'dist','index.html')));}"
                "else{res.writeHead(404);res.end('Cannot GET '+req.url);}})"
                f".listen({port});\n"
            )
        else:  # /api 만, 루트 404 (이번 런 결함 재현 — 순수 node)
            body = (
                "const http=require('http');\n"
                f"http.createServer((req,res)=>{{if(req.url==='/api')"
                "{res.writeHead(200);res.end('{}');}else{res.writeHead(404);res.end('Cannot GET '+req.url);}})"
                f".listen({port});\n"
            )
        (code / "server.js").write_text(body, encoding="utf-8")
        return code

    def test_probe_loaded_pass(self, tmp_path: Path) -> None:
        """실제 node 서버가 루트를 서빙 → 실 probe loaded → PASS (ephemeral 포트로 flaky 제거)."""
        code = self._pure_node_app(tmp_path, serves_root=True, port=self._free_port())
        r = run_packageability_gate(code, "web")  # 실 _default_web_probe
        assert r.verdict == "PASS" and r.root_status == "loaded"

    def test_probe_cannot_get_fail(self, tmp_path: Path) -> None:
        """실제 node 서버가 루트 404(Cannot GET) → 실 probe → FAIL. express+정적부재라 포트충돌해도 FAIL 유지."""
        port = self._free_port()
        code = self._pure_node_app(tmp_path, serves_root=False, port=port)
        # express+정적부재 서버를 추가해 EADDRINUSE→unverified 라도 serves_dist=False→FAIL 보장(포트 flaky 방지)
        (code / "package.json").write_text(json.dumps({"type": "module", "scripts": {"start": "node app.js"}}), encoding="utf-8")
        (code / "app.js").write_text(f"import express from 'express';\nconst app=express();app.get('/api',(q,r)=>r.json({{}}));app.listen({port});\n", encoding="utf-8")
        r = run_packageability_gate(code, "web")
        assert r.verdict == "FAIL" and r.signal in ("root_cannot_get", "not_serving_dist")

    def test_probe_cannot_get_live_404(self, tmp_path: Path) -> None:
        """R4 #9: 의존성 없는 *순수 node* /api-only 서버를 실제 spawn → 라이브 루트 404 → cannot_get FAIL.

        (express 대신 http.createServer 라 deps-missing 우회 → probe 의 live 200/404 판별 분기를 실제로 행사.)
        """
        code = self._pure_node_app(tmp_path, serves_root=False, port=self._free_port())
        r = run_packageability_gate(code, "web")  # 실 _default_web_probe (node 존재 시)
        assert r.verdict == "FAIL" and r.root_status == "cannot_get" and r.signal == "root_cannot_get"

    def test_probe_deps_missing_is_unverified_pass_non_express(self, tmp_path: Path) -> None:
        """R#19 정확화: 비-express 서버가 deps 부재로 크래시 → unverified → 구조폴백 PASS(정책상 거짓 FAIL 금지)."""
        code = tmp_path / "code"
        code.mkdir()
        (code / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8")
        (code / "node_modules").mkdir()
        (code / "node_modules" / ".keep").write_text("")
        (code / "dist").mkdir()
        (code / "dist" / "index.html").write_text("<div>x</div>")
        (code / "server.js").write_text("require('definitely-not-installed-xyz');\nrequire('http').createServer(()=>{}).listen(8914);\n")
        r = run_packageability_gate(code, "web")
        assert r.verdict == "PASS" and r.root_status == "unverified"  # 비-express serves_dist=None → 폴백 PASS

    def test_probe_express_no_root_deps_missing_still_fail(self, tmp_path: Path) -> None:
        """대조군: express+루트서빙 부재 서버가 deps 부재로 unverified → serves_dist=False → FAIL(결정론 catch)."""
        code = tmp_path / "code"
        code.mkdir()
        (code / "package.json").write_text(json.dumps({"type": "module", "scripts": {"start": "node server.js"}}), encoding="utf-8")
        (code / "node_modules").mkdir()
        (code / "node_modules" / ".keep").write_text("")
        (code / "dist").mkdir()
        (code / "dist" / "index.html").write_text("<div>x</div>")
        (code / "server.js").write_text("import express from 'express';\nconst app=express();app.get('/api',(q,r)=>r.json({}));app.listen(8915);\n")
        r = run_packageability_gate(code, "web")
        assert r.verdict == "FAIL" and r.signal == "not_serving_dist"


# =============================================================================
# 9. 라운드-2 적대 리뷰 회귀 — 의존성 백엔드·중첩·프런트 토큰·간접 참조·프레임워크 포트
# =============================================================================
class TestRound2Fixes:
    @pytest.mark.parametrize("loc", ["src/server/index.js", "server/routes/app.js", "services/api.js", "functions/handler.js"])
    def test_preview_with_nested_or_dep_backend_fails(self, tmp_path: Path, loc: str) -> None:
        """R#4/#17: 백엔드가 비-스캔/중첩 dir 이거나 의존성에만 선언돼도 preview+backend FAIL."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"},
                        server_src=_SERVER_NO_DIST, server_name=loc, deps={"express": "^4.19"})
        assert analyze_web_packageability(code).signal == "preview_no_backend"

    def test_pure_spa_with_frontend_listen_tokens_not_backend(self, tmp_path: Path) -> None:
        """R#9: 프런트엔드 토큰(socket.listen/emitter.serve)은 server 로 오인 안 됨 → preview PASS."""
        from src.agents.runtime_verification.packageability_gate import _find_server_files
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"}, deps={"vite": "^5"})
        (code / "src").mkdir(exist_ok=True)
        (code / "src" / "ws.js").write_text("const socket={listen:()=>{}};socket.listen(()=>{});export const x=1;\n", encoding="utf-8")
        (code / "src" / "store.js").write_text("const emitter={serve:()=>{}};emitter.serve({handler});\n", encoding="utf-8")
        assert len(_find_server_files(code)) == 0
        assert run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED).verdict == "PASS"

    @pytest.mark.parametrize(
        "start,scripts_extra,kind",
        [("npm run serve", {"serve": "vite"}, "dev"), ("npm run go", {"go": "node server.js"}, "node-server"),
         ("yarn prod", {"prod": "vite preview"}, "preview")],
    )
    def test_npm_run_indirection_resolved(self, start, scripts_extra, kind) -> None:
        """R#5: `npm run X` 간접 참조를 scripts[X] 로 해석해 재분류."""
        sc = {"start": start, **scripts_extra}
        assert _classify_npm_command(start, sc) == kind

    @pytest.mark.parametrize("start,port", [("astro preview", 4321), ("nuxt start", 3000), ("next start", 3000)])
    def test_framework_default_port_set(self, tmp_path: Path, start, port) -> None:
        """R#14/#16: framework start 가 기본 포트를 받아 probe 가 실제 spawn 가능."""
        code = _web_app(tmp_path, scripts={"start": start, "build": "x build"})
        assert analyze_web_packageability(code).listen_port == port

    @pytest.mark.parametrize(
        "listen,port",
        [("app.listen(Number(process.env.PORT)||8080)", 8080), ("app.listen(parseInt(process.env.PORT,10)||5000)", 5000),
         ("app.listen({ host:'0', port: 3000 })", 3000), ("app.listen(process.env.PORT ?? 4000)", 4000),
         ("const PORT=process.env.PORT||9090;\napp.listen(PORT)", 9090)],
    )
    def test_port_idioms(self, listen, port) -> None:
        """R#2: 흔한 포트 관용구를 모두 탐지(probe 가 실제 실행되게)."""
        assert _detect_listen_port(listen) == port

    def test_empty_start_subdir_relative_command(self, tmp_path: Path) -> None:
        """R#10: start 없는 단일 서버가 하위 dir 면 상대경로 명령(node src/server.js) 합성."""
        code = _web_app(tmp_path, scripts={"build": "vite build"}, server_src=_SERVER_SERVES_DIST, server_name="src/server.js")
        assert analyze_web_packageability(code).command == "node src/server.js"

    def test_custom_root_serving_not_false_fail(self, tmp_path: Path) -> None:
        """R#1: express 커스텀 루트 핸들러(res 변수명 무관)는 serves_dist=False 단정 안 함 → 거짓 FAIL 0."""
        custom = ("import express from 'express';import fs from 'fs';\nconst app=express();\n"
                  "app.get('/',(q,r)=>r.type('html').send(fs.readFileSync('dist/index.html')));\napp.listen(8787);\n")
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=custom)
        assert run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED).verdict == "PASS"


class TestRound3Fixes:
    """3차 적대 리뷰 회귀 — express SSR(render)·마운트 라우터·다중라인 루트·devDeps·preview dist."""

    @pytest.mark.parametrize(
        "server",
        [
            "import express from 'express';const app=express();app.get('/',(q,r)=>r.render('home'));app.listen(8787);\n",  # SSR render
            "import express from 'express';const app=express();app.get('/',(req,res)=>res.status(200).render('i'));app.listen(8787);\n",
            "import express from 'express';import idx from './routes/index.js';const app=express();app.use('/',idx);app.listen(8787);\n",  # mounted root router
            "import express from 'express';const app=express();\napp.get('/', async (req,res)=>{\n  const h=await load();\n  res.send(h);\n});\napp.listen(8787);\n",  # multiline
        ],
    )
    def test_deployable_root_idioms_not_false_fail(self, tmp_path: Path, server: str) -> None:
        """R#1/#3/#8/#10: SSR render·마운트 라우터·다중라인 루트는 serves_dist=False 단정 안 함 → 거짓 FAIL 0."""
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=server)
        a = analyze_web_packageability(code)
        assert a.serves_dist is not False, server[:60]
        assert run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED).verdict == "PASS"

    @pytest.mark.parametrize(
        "middleware",
        ["", "app.use(logger);", "app.use(cors);", "app.use(apiRouter);", "app.use(express.json());app.use(helmet());"],
    )
    def test_this_run_still_false_no_root(self, tmp_path: Path, middleware: str) -> None:
        """대조군(R4 #2/#6/#8): 루트 라우트 전무 /api-only express 는 *흔한 미들웨어가 있어도* serves_dist=False.

        bare `app.use(logger)` 가 루트 마운트로 오인돼 원 ERP 결함류가 거짓 PASS 되던 회귀를 고정한다.
        """
        s = (f"import express from 'express';const app=express();{middleware}\n"
             "app.get('/api',(q,r)=>r.json({}));app.get('/health',(q,r)=>r.send('ok'));app.listen(8787);\n")
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=s)
        assert analyze_web_packageability(code).serves_dist is False
        assert run_packageability_gate(code, "web", _probe=_PROBE_UNVERIFIED).verdict == "FAIL"

    def test_devdeps_express_not_backend(self, tmp_path: Path) -> None:
        """R#7: devDependencies 의 express(dev-mock)는 백엔드 아님 → 순수 SPA preview FAIL 안 함."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"},
                        deps={"react": "^18"})
        # devDependencies 에 express 추가
        pkg = json.loads((code / "package.json").read_text(encoding="utf-8"))
        pkg["devDependencies"] = {"vite": "^5", "express": "^4"}
        (code / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        a = analyze_web_packageability(code)
        assert a.verdict == "PROBE"  # preview_no_backend 아님

    def test_preview_without_dist_defers_to_probe(self, tmp_path: Path) -> None:
        """R#4: dist 부재면 vite preview 가 기동 에러 → serves_dist=True 단정 안 함(None, probe 위임)."""
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"}, dist=False)
        a = analyze_web_packageability(code)
        assert a.serves_dist is None

    def test_R5_history_not_overbroad(self, tmp_path: Path) -> None:
        """R5 #1: bare `history()` 호출은 루트 신호 아님(app.use(history())만). /api-only + history() → False."""
        s = "import express from 'express';const app=express();function history(){return 1;}history();app.get('/api',(q,r)=>r.json({}));app.listen(8787);\n"
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=s)
        assert analyze_web_packageability(code).serves_dist is False

    def test_R5_commented_root_not_serving(self, tmp_path: Path) -> None:
        """R5 #2: 주석/죽은 코드의 루트 라우트는 무시 → /api-only + 주석 'app.get(/)' → 여전히 False."""
        s = ("import express from 'express';const app=express();\n"
             "// TODO later: app.get('/', (q,r)=>r.sendFile('dist/index.html'))\n"
             "app.get('/api',(q,r)=>r.json({}));app.listen(8787);\n")
        code = _web_app(tmp_path, scripts={"start": "node server.js"}, server_src=s)
        assert analyze_web_packageability(code).serves_dist is False

    @pytest.mark.parametrize("name", ["orders-gateway", "payment-handler", "auth-service"])
    def test_R5_odd_name_backend_hint_search(self, tmp_path: Path, name: str) -> None:
        """R5 #7: 접미 -gateway/-handler/-service odd-name 백엔드도 read(search) → preview_no_backend backstop."""
        from src.agents.runtime_verification.packageability_gate import _find_server_files
        code = _web_app(tmp_path, scripts={"start": "vite preview", "build": "vite build"},
                        server_src=_SERVER_NO_DIST, server_name=f"src/{name}.js")
        assert any(p.name == f"{name}.js" for p in _find_server_files(code))

    def test_R5_directive_express5_safe(self) -> None:
        """R5 #4: 계약/직선이 Express 5 호환 미들웨어형 fallback 을 권장(app.get('*') path-to-regexp 에러 회피)."""
        from src.workflows.analyze_and_implement import _build_web_platform_directive
        d = _build_web_platform_directive()
        assert "app.use((q,r)=>r.sendFile" in d or "미들웨어형 fallback" in d

    def test_find_server_files_perf_dedup(self, tmp_path: Path) -> None:
        """R#6: 큰 프런트엔드에서 _find_server_files 가 선형/서브초(겹치는 glob 2회 read 제거)."""
        import time
        from src.agents.runtime_verification.packageability_gate import _find_server_files
        code = tmp_path / "code"
        (code / "src").mkdir(parents=True)
        for i in range(1500):
            (code / "src" / f"c{i}.js").write_text("export const x=" + str(i) + ";\n", encoding="utf-8")
        (code / "src" / "server.js").write_text(_SERVER_SERVES_DIST, encoding="utf-8")
        t0 = time.perf_counter()
        files = _find_server_files(code)
        assert time.perf_counter() - t0 < 2.0
        assert any(p.name == "server.js" for p in files)
