# -*- coding: utf-8 -*-
"""산출물 배포성(packageability) 게이트 — v13 P25.

목표: verdict=COMPLETE 인데도 *비개발자가 문서화된 단일 명령으로 실제로 못 돌리는* 산출물을 막는다.

진단(웹 ERP 런 alpha_run_20260605_165644): ``server.js`` 가 빌드된 프론트(``dist/``)를 정적 서빙하지
않고 ``/api`` 만 제공 + ``package.json`` 에 ``start`` 스크립트 부재 → ``node server.js`` 후 루트(``/``)는
"Cannot GET /". 전체 앱을 띄우려면 dev 전용 ``npm run dev``(concurrently + vite dev) 가 유일 경로였다.
**P17 시각 QA 는 dist 를 *자체* Python 정적 서버(``web_vision_qa._serve_dist``)로 띄워 통과** — 즉
배포 산출물(프로덕션 단일 명령)이 아니라 dev/정적 우회 경로로 검증해 "배포 불가"를 놓쳤다.

본 게이트는 **프로덕션/배포 실행 경로**(문서화된 단일 명령으로 프로덕션 서버 기동 → 루트 로드)로만
검증한다 — dev 서버 아님. **권위는 런타임 루트 로드**, 정규식은 보조 휴리스틱:

1. **구조 분석(결정론)**: ``package.json`` scripts + 의존성 + 서버 소스를 읽어 (a) 프로덕션 단일
   명령이 있는가, (b) dev 전용/실행 불가인가, (c) 프로덕션 서버가 *루트를* 서빙하는지를 *세 값
   (True/False/None)* 으로 판정. **명령 자체가 깨진 경우만**(단일 명령 부재 / start 가 dev 전용 /
   preview 인데 백엔드 의존성 존재) 프로세스 없이 즉시 FAIL.
2. **런타임 probe(권위, graceful)**: 명령이 있으면 *문서화된 단일 명령* 으로 프로덕션 서버를 띄워
   루트 ``/`` 가 HTML 앱으로 로드되는지 확인 — loaded→PASS, Cannot GET/404→FAIL. node/deps/포트
   부재 등 probe 환경 문제는 ``unverified`` → 구조 신호로 폴백.

정규식 *부재* 를 함부로 FAIL 로 단정하지 않는다(적대 리뷰 P25): ``serves_dist=False`` 는 *express 인데
정적 서빙·루트 핸들러·sendFile·res.send 가 모두 전무* 한 *극히 좁은 고신뢰* 케이스(=원 ERP 런)로만
한정한다. 그 외(non-express / 커스텀 서빙 / 프레임워크 SSR / 인식 못 한 idiom)는 None → probe 권위.

데스크탑/none 은 P23 desktop smoke + 단일 폼팩터 *계약* 이 담당 → 본 게이트는 ``SKIPPED``.
결과 ``PackageabilityResult`` 는 ``DesktopSmokeResult`` 와 동일 duck-typing 을 따라 judge override 가 소비.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class PackageabilityResult:
    """배포성 게이트 결과. verdict=='FAIL' 만 COMPLETE 를 차단한다(PASS/SKIPPED 불차단)."""

    verdict: str  # PASS | FAIL | SKIPPED
    reason: str = ""
    signal: str = ""  # no_command | dev_only | preview_no_backend | not_serving_dist | root_cannot_get | server_error | runtime_ok | structural_ok | skipped
    command: str = ""
    serves_dist: Optional[bool] = None
    dev_only: Optional[bool] = None
    root_status: str = ""  # loaded | cannot_get | server_error | unverified
    error_excerpt: str = ""
    exit_code: Optional[int] = None
    extras: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"

    @property
    def failed(self) -> bool:
        return self.verdict == "FAIL"


# ---------------------------------------------------------------------------
# 정규식 (모두 경계 한정 — ReDoS 무관)
# ---------------------------------------------------------------------------
_EXPRESS_RE = re.compile(r"require\(\s*['\"]express['\"]|from\s+['\"]express['\"]|\bexpress\s*\(\s*\)", re.IGNORECASE)
# *임의의* 정적/루트 서빙 신호(망라 불가 — express-False 를 좁히는 용도). express.static(alias 포함 `.static(`),
# sendFile, serveStatic, sirv/koa-static, createReadStream(...index), 그리고 루트 핸들러 + res.send/end/type/write.
_STATIC_SERVE_RE = re.compile(
    r"express\.static|\.static\s*[(;=]|serveStatic\s*\(|@fastify/static|koa-?static|\bsirv\s*\(|connect\.static|"
    r"createReadStream\s*\([^)\n]{0,200}index|"
    # 루트(정확히 '/' 또는 '*') 핸들러 본문의 응답 전송(변수명 무관: r/res/response …)
    r"\.get\s*\(\s*['\"](?:/|\*)['\"]\s*,[^\n]{0,200}\.(?:send|sendFile|end|type|write)\s*\(|"
    r"req\.(?:path|url)\s*===?\s*['\"]/['\"][^\n]{0,160}\.(?:send|sendFile|end|type|write)\s*\(",
    re.IGNORECASE,
)
# 서빙 대상이 *빌드 산출*(dist/build/out/.next/.output)인지. (public 은 vite 의 정적 *소스* 디렉터리라
# 빌드 산출이 아님 → 제외: express.static('public') 은 dist 미서빙으로 보아 probe 에 위임.)
_SERVES_BUILD_DIR_RE = re.compile(
    r"(?:static|sendFile|createReadStream|readFileSync|join)\s*\([^)\n]{0,200}(?:dist|build|\bout\b|\.output|\.next)",
    re.IGNORECASE,
)
# 루트 서빙 *신호*(라우트 선언/마운트/SPA fallback). 본문(send/render/sendFile/다중라인) 무관 —
# *루트 라우트가 존재* 하면 express-False 미서빙 단정을 회피하고 probe 에 위임한다(적대 리뷰 P25 R3:
# res.render SSR·마운트 라우터·다중라인 핸들러를 거짓 FAIL 하던 문제).
_ROOT_FALLBACK_RE = re.compile(
    r"\.get\s*\(\s*['\"]\*|\.get\s*\(\s*['\"]/['\"]|"            # app.get('/'|'*'
    r"\.all\s*\(\s*['\"][/*]['\"]|\.route\s*\(\s*['\"]/['\"]|"   # app.all('/'|'*'), app.route('/')
    r"\.use\s*\(\s*['\"]/['\"]\s*,|"                            # app.use('/', router) — *경로 한정* 루트 마운트만
    r"sendFile\s*\([^)\n]{0,200}index\.html|"
    r"req\.(?:path|url)\s*===?\s*['\"]/['\"]|"
    r"connect-history-api-fallback|\.use\s*\(\s*history\s*\(",   # SPA history fallback 미들웨어(app.use(history()) 한정 — R5 #1)
    re.IGNORECASE,
)
# 주의(적대 리뷰 P25 R4): bare `app.use(<ident>)` 는 *루트 마운트 신호로 쓰지 않는다* — app.use(logger)/
# app.use(cors)/app.use(apiRouter) 같은 *비-루트 미들웨어* 를 루트 서빙으로 오인해 원 ERP 결함류(express
# /api-only + 미들웨어)를 거짓 PASS 시켰음. 경로 한정 `app.use('/', …)` 만 루트 마운트로 인정한다.
# (bare 라우터 마운트가 실제 루트를 서빙하면 런타임 probe 가 loaded 로 PASS — 권위는 probe.)
# 서버 *프레임워크* 식별(프런트엔드 토큰 오탐 방지 — listen 토큰만으로는 server 로 인정 안 함).
_SERVER_FRAMEWORK_RE = re.compile(
    r"require\(\s*['\"](?:express|fastify|koa|@hapi/hapi|hono|@hono/node-server|node:http|node:https|http|https|polka|connect|restify)['\"]|"
    r"from\s+['\"](?:express|fastify|koa|hono|polka|connect)['\"]|"
    r"http\.createServer|https\.createServer|\bfastify\s*\(|new\s+Koa\s*\(|Bun\.serve|Deno\.serve",
    re.IGNORECASE,
)
_LISTEN_OR_CREATE_RE = re.compile(r"\.listen\s*\(|\.createServer\s*\(|Bun\.serve|Deno\.serve", re.IGNORECASE)
# listen 포트(리터럴 / env 폴백 `X || N`·`X ?? N` / 객체형 `{port: N}`).
_LISTEN_PORT_RE = re.compile(
    r"\.listen\s*\(\s*"
    r"(?:\{[^{}]{0,60}?port\s*:\s*)?"
    r"(?:[^|?{}\n]{0,40}(?:\|\||\?\?)\s*)?"
    r"['\"]?(\d{2,5})\b",
    re.IGNORECASE,
)
_README_RUN_RE = re.compile(r"npm\s+(?:run\s+)?start|node\s+[\w./\\-]+|npm\s+start", re.IGNORECASE)
_FRAMEWORK_PROD_RE = re.compile(
    r"\bnext\s+start\b|\bnuxt\s+start\b|\bnuxi\s+preview\b|\bastro\s+preview\b|"
    r"\bremix-serve\b|\bremix\s+start\b|\bgatsby\s+serve\b|\bpm2\s+start\b|\bsvelte-kit\b",
    re.IGNORECASE,
)
_DEV_TOOL_RE = re.compile(
    r"\bconcurrently\b|\bnodemon\b|\b(?:npm\s+run|yarn|pnpm|bun)\s+dev\b|\bnext\s+dev\b|"
    r"\bng\s+serve\b|react-scripts\s+start|webpack(?:-dev-server|\s+serve)|\bparcel\b(?!\s+build)",
    re.IGNORECASE,
)
# package.json 의존성에 선언되면 '백엔드 서버 존재'(파일 위치 무관) — preview/static 단일명령으론 미기동.
_BACKEND_DEP_RE = re.compile(
    r"^(?:express|fastify|koa|@hapi/hapi|hapi|hono|@hono/node-server|@nestjs/core|restify|polka|connect|micro)$",
    re.IGNORECASE,
)
_FRAMEWORK_PORT = {"next": 3000, "nuxt": 3000, "astro": 4321, "gatsby": 9000, "vite": 4173, "serve": 3000, "remix-serve": 3000}


def _find_package_json(code_dir: Path) -> Optional[Path]:
    p = code_dir / "package.json"
    return p if p.is_file() else None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except (OSError, ValueError):
        return {}


def _resolve_script(cmd: str, scripts: dict, _depth: int = 0) -> str:
    """``npm run X`` 간접 참조를 scripts[X] 로 1~2단계 해석(순환 가드)."""
    m = re.match(r"(?:npm\s+run|yarn|pnpm\s+run|pnpm|bun\s+run)\s+([\w:.\-]+)\s*$", (cmd or "").strip(), re.IGNORECASE)
    if m and _depth < 2:
        target = scripts.get(m.group(1))
        if target and target != cmd:
            return _resolve_script(str(target), scripts, _depth + 1)
    return cmd or ""


def _classify_npm_command(cmd: str, scripts: Optional[dict] = None) -> str:
    """npm script 명령을 프로덕션 적격성 관점에서 분류.

    dev | build | preview | node-server | static-server | framework | empty | other.
    복합 명령(`&&`/`;`)은 마지막 *실행* 세그먼트로 분류. `npm run X` 간접 참조는 scripts 로 해석.
    """
    raw = (cmd or "").strip()
    if not raw:
        return "empty"
    if scripts is not None:
        raw = _resolve_script(raw, scripts).strip()
        if not raw:
            return "empty"
    segs = [s.strip() for s in re.split(r"&&|;", raw) if s.strip()]
    if len(segs) > 1:
        for seg in reversed(segs):
            k = _classify_npm_command(seg, scripts)
            if k != "build":
                return k
        return "build"
    c = " ".join(raw.lower().split())
    if _FRAMEWORK_PROD_RE.search(c):
        return "framework"
    if _DEV_TOOL_RE.search(c):
        return "dev"
    if re.search(r"\bvite\b", c):
        if re.search(r"\bvite\s+build\b", c):
            return "build"
        if re.search(r"\bvite\s+preview\b", c):
            return "preview"
        return "dev"
    if re.search(r"\b(?:node|tsx|ts-node|bun)\b", c):
        return "node-server"
    if re.search(r"\b(?:serve|http-server|sirv)\b", c):
        return "static-server"
    return "other"


def _is_server_file(src: str) -> bool:
    """서버 엔트리인가 — *프레임워크 신호* + listen/createServer 동반(프런트 토큰 오탐 방지)."""
    return bool(_SERVER_FRAMEWORK_RE.search(src)) and bool(_LISTEN_OR_CREATE_RE.search(src))


_SERVER_HEAD_BYTES = 32768  # 서버 신호(require('express')/.listen()) 는 파일 상단 → head 만 읽어 성능 보호
# 서버 엔트리로 *읽어볼 가치* 가 있는 파일명(stem). 큰 프런트엔드(수천 컴포넌트)에서 모든 .js 를
# stat+read 하지 않도록 — 명백한 서버 엔트리명 + 최상위 파일만 읽는다(R3 #6 perf). 백엔드 존재
# 자체는 _has_backend_dependency(의존성)가 독립 backstop 이라 odd-name 서버 누락은 안전.
# 정확 stem(app/index/main/api/…) + *접미* server/gateway/backend/handler/service(orders-gateway,
# payment-handler 등 odd-name 백엔드도 read 대상 — R4 #4/#7 preview_no_backend backstop 보강).
_SERVER_NAME_HINT = re.compile(
    r"^(?:server|app|index|main|api|http|https|backend|entry|bootstrap|www|gateway)$"
    r"|(?:server|gateway|backend|handler|service)s?$",
    re.IGNORECASE,
)


def _find_server_files(code_dir: Path) -> list[Path]:
    """서버 엔트리 후보 — 최상위 + 흔한 서버 디렉터리(2-depth), .ts 포함. 프레임워크 동반 필수.

    성능(적대 리뷰 P25 R3 #6): 문자열 dedup(겹치는 glob 2회 read 제거) + *서버명 힌트/최상위* 만
    stat+read(head 32KB) → 수천 파일 프런트엔드에서도 선형·서브초.
    """
    out: list[Path] = []
    seen: set[str] = set()
    roots = [code_dir] + [code_dir / d for d in ("src", "server", "api", "backend", "lib", "app", "functions", "routes", "services", "controllers", "handlers")]
    exts = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}
    for base in roots:
        if not base.is_dir():
            continue
        for p in sorted(set(base.glob("*")) | set(base.glob("*/*"))):
            if p.suffix.lower() not in exts:
                continue
            n = p.name.lower()
            if n.startswith((".", "vite.config", "vitest", "rollup.config")) or n.startswith("test") or n.endswith((".test.js", ".test.ts", ".spec.js", ".spec.ts", ".d.ts")):
                continue
            # 읽기 전 *값싼* 필터: 서버명 힌트 또는 최상위(code_dir 직계) 파일만 — 프런트 컴포넌트 read 회피.
            # *search* (match 아님) — 접미 -gateway/-handler 등 odd-name 백엔드도 잡도록(R5 #7).
            if not (_SERVER_NAME_HINT.search(p.stem) or p.parent == code_dir):
                continue
            parts = {x.lower() for x in p.parts}
            if "node_modules" in parts or "dist" in parts or ".git" in parts:
                continue
            key = os.path.normcase(str(p))
            if key in seen:
                continue
            seen.add(key)
            try:
                if not p.is_file():
                    continue
                with p.open("r", encoding="utf-8", errors="ignore") as fh:
                    src = fh.read(_SERVER_HEAD_BYTES)
            except OSError:
                continue
            if _is_server_file(src):
                out.append(p)
    return out


_COMMENT_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")  # 주석 제거(죽은 라우트 오인 방지 — R5 #2). 경계 한정.


def _server_serves_root(src: str) -> Optional[bool]:
    """서버 소스가 빌드 프론트를 *루트에서* 서빙하는지 — 3-상태.

    True  = 빌드 dir(dist/build/out) 정적 서빙 또는 루트 핸들러/SPA fallback 확인(고신뢰).
    False = express 인데 *어떤 정적/루트/sendFile/res.send 서빙 신호도 전무*(원 ERP 런 = 고신뢰 미서빙).
    None  = 판정 불가(non-express / 엉뚱 dir / 인식 못 한 idiom) → 런타임 probe 에 위임.
    """
    src = _COMMENT_RE.sub(" ", src)  # 주석 속 'app.get(\"/\")' 가 루트 신호로 오인되지 않게(R5 #2)
    has_static = bool(_STATIC_SERVE_RE.search(src))
    has_root = bool(_ROOT_FALLBACK_RE.search(src))
    is_express = bool(_EXPRESS_RE.search(src))
    if has_static:
        if _SERVES_BUILD_DIR_RE.search(src) or has_root:
            return True
        return None  # 정적 신호는 있으나 dist/루트 미확인(예: public 만) → probe 권위
    if is_express:
        # express 인데 정적 전무 — *루트 라우트/마운트* 가 어떤 형태로든 있으면(res.render SSR·다중라인·
        # 마운트 라우터) 미서빙 단정 회피 → probe 권위. 루트 신호가 *전무* 할 때만(원 ERP 런) False.
        return None if has_root else False
    return None  # non-express → 정규식으로 못 잡음 → probe 권위


def _detect_listen_port(src: str) -> Optional[int]:
    m = _LISTEN_PORT_RE.search(src or "")
    if m:
        return int(m.group(1))
    # 2줄 idiom: const PORT = <env || N> ... listen(PORT)
    m2 = re.search(r"\b(?:const|let|var)\s+\w*(?i:port)\w*\s*=\s*(?:[^|?{}\n]{0,40}(?:\|\||\?\?)\s*)?['\"]?(\d{2,5})\b", src or "")
    return int(m2.group(1)) if m2 else None


def _framework_default_port(start_cmd: str) -> Optional[int]:
    c = re.sub(r"\s+", " ", (start_cmd or "").lower()).split("&&")[-1].strip()
    first = c.split()[0] if c.split() else ""
    return _FRAMEWORK_PORT.get(first)


def _resolve_start_server_file(start_cmd: str, server_files: list[Path], code_dir: Path) -> Optional[Path]:
    """``node X``(X 는 .js 또는 디렉터리/확장자 없음)의 X 를 server_files 에서 찾는다."""
    m = re.search(r"(?:node|tsx|ts-node|bun)\s+([\w./\\-]+)", start_cmd or "", re.IGNORECASE)
    if m:
        cand = code_dir / m.group(1)
        cands = [cand]
        if cand.suffix == "":
            cands += [cand / "index.js", cand / "index.mjs", Path(str(cand) + ".js")]
        for c in cands:
            try:
                rc = c.resolve()
            except OSError:
                continue
            for sf in server_files:
                try:
                    if sf.resolve() == rc:
                        return sf
                except OSError:
                    continue
            if c.is_file():
                return c
    return server_files[0] if len(server_files) == 1 else None


def _rel_cmd(server_file: Path, code_dir: Path) -> str:
    try:
        return f"node {server_file.relative_to(code_dir).as_posix()}"
    except ValueError:
        return f"node {server_file.name}"


@dataclass
class WebAnalysis:
    verdict: str  # FAIL(명령 자체 결함) | PROBE(명령 존재→probe) | SKIPPED
    reason: str
    signal: str
    command: str = ""
    server_file: Optional[Path] = None
    serves_dist: Optional[bool] = None  # True/False/None 3-상태
    dev_only: Optional[bool] = None
    listen_port: Optional[int] = None
    has_readme_cmd: Optional[bool] = None
    start_kind: str = ""


def _has_readme_run_command(code_dir: Path) -> bool:
    for name in ("README.md", "README", "readme.md", "Readme.md"):
        p = code_dir / name
        if p.is_file():
            try:
                if _README_RUN_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except OSError:
                continue
    return False


def _has_backend_dependency(pkg: dict) -> bool:
    # *프로덕션* dependencies 만(devDependencies 의 dev-mock express 등은 백엔드 아님 — R3 #7).
    return any(_BACKEND_DEP_RE.match(str(k)) for k in (pkg.get("dependencies") or {}))


def _read(p: Optional[Path]) -> str:
    if p is None:
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def analyze_web_packageability(code_dir: Path) -> WebAnalysis:
    """web 산출물의 *프로덕션 단일 명령 + 루트 서빙* 구조 분석(권위는 런타임 probe).

    즉시 FAIL(명령 자체 결함, probe 불요): ① 단일 명령 부재/ dev 전용, ② preview 인데 백엔드 서버
    의존성/파일 존재(API 미기동). 그 외 명령이 있으면 PROBE(serves_dist 3-상태). 정규식 부재를
    함부로 FAIL 로 단정하지 않는다(express 외/커스텀 서빙 false-FAIL 방지).
    """
    pkg_path = _find_package_json(code_dir)
    if pkg_path is None:
        return WebAnalysis("SKIPPED", "package.json 부재 — node web 프로젝트 아님.", "skipped")
    pkg = _load_json(pkg_path)
    scripts = pkg.get("scripts") or {}
    start = str(scripts.get("start", "") or "")
    dev = str(scripts.get("dev", "") or "")
    start_kind = _classify_npm_command(start, scripts)
    dev_only_run = _classify_npm_command(dev, scripts) == "dev"
    server_files = _find_server_files(code_dir)
    has_backend = bool(server_files) or _has_backend_dependency(pkg)
    has_readme = _has_readme_run_command(code_dir)

    command = ""
    server_file: Optional[Path] = None
    serves_dist: Optional[bool] = None
    listen_port: Optional[int] = None

    if start_kind == "node-server":
        server_file = _resolve_start_server_file(start, server_files, code_dir)
        src = _read(server_file)
        command = "npm start"
        serves_dist = _server_serves_root(src) if src else None
        listen_port = _detect_listen_port(src) if src else None
    elif start_kind == "framework":
        command = "npm start"
        serves_dist = None  # 프레임워크 내부 서빙 → probe 권위
        listen_port = _framework_default_port(start)
    elif start_kind in ("static-server", "preview"):
        command = "npm start"
        # dist 자체 서빙 — 단, 빌드 산출이 실제로 있을 때만 고신뢰 True(없으면 preview 가 기동 에러 →
        # probe 권위로 위임, R3 #4 latent false-PASS 방지).
        serves_dist = True if (code_dir / "dist" / "index.html").is_file() else None
        listen_port = _framework_default_port(start)
    elif start_kind == "empty":
        if len(server_files) == 1:
            server_file = server_files[0]
            src = _read(server_file)
            command = _rel_cmd(server_file, code_dir)
            serves_dist = _server_serves_root(src)
            listen_port = _detect_listen_port(src)
    # start_kind in (dev, build, other) → command 미설정 → 아래 no_command/dev_only

    base = dict(command=command, server_file=server_file, serves_dist=serves_dist,
                dev_only=dev_only_run, listen_port=listen_port, has_readme_cmd=has_readme, start_kind=start_kind)

    if not command:
        is_dev = dev_only_run or start_kind == "dev"
        why = ("프로덕션 단일 명령 부재 — `start` 스크립트가 없거나 dev 전용(`%s`)이고, 전체 앱(프론트+API)을 "
               "한 명령으로 띄울 경로가 없습니다." % (dev or start or "(없음)"))
        if is_dev:
            why += " 유일/문서화 실행 경로가 dev 전용(`npm run dev` / concurrently / vite dev)입니다 — 비개발자 원클릭 불가."
        return WebAnalysis("FAIL", why, "dev_only" if is_dev else "no_command", **base)

    if start_kind in ("preview", "static-server") and has_backend:
        return WebAnalysis(
            "FAIL",
            "`%s` 는 빌드된 dist 만 서빙하고 백엔드 서버(API)를 기동하지 않습니다 — 백엔드 프레임워크가 "
            "선언/존재하는데 단일 명령으로 전체 앱(프론트+API)이 한 포트에서 뜨지 않습니다." % start,
            "preview_no_backend", **base,
        )

    return WebAnalysis("PROBE", "프로덕션 단일 명령(`%s`) 존재 — 런타임 루트 로드로 확정." % command, "probe", **base)


# ---------------------------------------------------------------------------
# 런타임 probe — *문서화된 단일 명령* 으로 프로덕션 서버 기동 → 루트 / 로드 확인
# ---------------------------------------------------------------------------
# (status, port, excerpt). status ∈ loaded | cannot_get | server_error | unverified
ProbeFn = Callable[[Path, WebAnalysis], "tuple[str, Optional[int], str]"]
_PROBE_BIND_WAIT_SEC = 8.0
_PROBE_POLL_INTERVAL = 0.25
_CANNOT_GET_RE = re.compile(r"Cannot\s+GET\s+/", re.IGNORECASE)
_DEPS_MISSING_RE = re.compile(r"Cannot find module|ERR_MODULE_NOT_FOUND|MODULE_NOT_FOUND", re.IGNORECASE)


def _node_available() -> bool:
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _node_modules_ready(code_dir: Path) -> bool:
    nm = code_dir / "node_modules"
    if not nm.is_dir():
        return False
    try:
        return any(True for _ in nm.iterdir())
    except OSError:
        return False


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """프로세스 *그룹* 종료 — Windows: taskkill /T /F, POSIX: killpg(세션 리더).

    `npm start` 는 node 자식을 fork 하므로 부모 PID 만 죽이면 node 손자가 좀비/포트 누수로 남는다
    (R3 #5, Linux CI 경로). Popen 시 start_new_session=True 로 세션을 분리하고 여기서 그룹 전체를 종료.
    """
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)  # 세션/그룹 전체(npm + node 자식)
            except (OSError, ProcessLookupError):
                proc.terminate()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=5)  # SIGKILL 후 직계 자식 즉시 회수(좀비 창 닫기 — R4 #5)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _resolve_runtime_command(analysis: WebAnalysis) -> Optional[list[str]]:
    cmd = (analysis.command or "").strip()
    if cmd == "npm start":
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        return [npm, "start"]
    m = re.match(r"node\s+(.+)$", cmd)
    if m:
        return ["node", m.group(1).strip()]
    return None


def _default_web_probe(code_dir: Path, analysis: WebAnalysis) -> "tuple[str, Optional[int], str]":
    """프로덕션 단일 명령으로 서버 기동 후 루트 ``/`` 로드 확인 (graceful).

    node/deps 부재·포트 미탐·바인드 실패·deps 미설치 등은 ``unverified``(거짓 FAIL 안 함). stdout 은
    임시 파일로 리다이렉트(파이프 버퍼 데드락 방지 — 로그 많은 서버도 안전).
    """
    if not _node_available():
        return "unverified", None, "node 미설치 — 런타임 probe 생략(구조 신호로 폴백)."
    if not _node_modules_ready(code_dir):
        return "unverified", None, "node_modules 부재/미설치 — 의존성 없음(구조 신호로 폴백)."
    port = analysis.listen_port
    if port is None:
        return "unverified", None, "서버 포트 미탐 — 런타임 probe 생략(구조 신호로 폴백)."
    cmd = _resolve_runtime_command(analysis)
    if cmd is None:
        return "unverified", None, "실행 명령 해석 실패 — probe 생략."

    proc: Optional[subprocess.Popen] = None
    logf = tempfile.TemporaryFile(mode="w+b")
    try:
        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            popen_kwargs["start_new_session"] = True  # 세션 분리 → killpg 로 node 자식까지 정리(R3 #5)
        proc = subprocess.Popen(
            cmd, cwd=str(code_dir), stdout=logf, stderr=subprocess.STDOUT, **popen_kwargs,
        )

        def _log_tail() -> str:
            try:
                logf.seek(0)
                return logf.read().decode("utf-8", errors="ignore")
            except OSError:
                return ""

        deadline = time.time() + _PROBE_BIND_WAIT_SEC
        url = f"http://127.0.0.1:{port}/"
        last_err = ""
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = _log_tail()
                if "EADDRINUSE" in tail:
                    return "unverified", port, f"포트 {port} 사용 중 — probe 환경 충돌(구조 신호로 폴백)."
                if _DEPS_MISSING_RE.search(tail):
                    return "unverified", port, "의존성/경로 미확인(Cannot find module) — probe 환경 결함(구조 신호로 폴백)."
                return "server_error", port, f"서버가 기동 직후 종료(exit={proc.returncode}). {tail[-400:]}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 — 127.0.0.1 로컬
                    body = resp.read(2048).decode("utf-8", errors="ignore")
                    code = resp.getcode()
                    if code == 200 and not _CANNOT_GET_RE.search(body):
                        return "loaded", port, f"루트 200 OK ({len(body)}B)."
                    return "cannot_get", port, f"루트 HTTP {code}: {body[:200]}"
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read(2048).decode("utf-8", errors="ignore")
                except Exception:  # noqa: BLE001
                    pass
                if he.code == 404 or _CANNOT_GET_RE.search(body):
                    return "cannot_get", port, f"루트 HTTP {he.code}: {body[:200] or 'Cannot GET /'}"
                last_err = f"HTTP {he.code}"
            except (urllib.error.URLError, OSError):
                last_err = "연결 대기"
            time.sleep(_PROBE_POLL_INTERVAL)
        tail = _log_tail()
        if "EADDRINUSE" in tail:
            return "unverified", port, f"포트 {port} 사용 중(EADDRINUSE) — probe 환경 충돌."
        return "unverified", port, f"루트 응답 대기 시간 초과 — {last_err or '미응답'}(구조 신호로 폴백)."
    except (OSError, subprocess.SubprocessError) as e:
        return "unverified", port, f"probe 기동 실패 — {type(e).__name__}: {e}(구조 신호로 폴백)."
    finally:
        if proc is not None:
            _kill_process_tree(proc)
        try:
            logf.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 공개 게이트
# ---------------------------------------------------------------------------
def run_packageability_gate(
    code_dir: Path,
    platform_intent: str = "web",
    *,
    _probe: Optional[ProbeFn] = None,
    run_probe: bool = True,
) -> PackageabilityResult:
    """빌드 후 산출물이 *문서화된 단일 프로덕션 명령* 으로 실제 동작하는지 검증.

    web → 구조 분석 + 런타임 probe(프로덕션 경로, 권위적). desktop/none → SKIPPED. FAIL 만 COMPLETE 차단.

    흐름: 명령 자체 결함(no_command/dev_only/preview_no_backend) → 즉시 FAIL. 명령 존재 → 런타임
    probe: loaded→PASS / cannot_get·server_error→FAIL / unverified→구조 폴백(serves_dist=False[express
    루트서빙 전무]→FAIL, True/None→PASS, 거짓 FAIL 방지).
    """
    try:
        if (platform_intent or "").lower() != "web":
            return PackageabilityResult("SKIPPED", reason="web 타겟 아님 — 데스크탑 배포성은 P23 smoke + 단일 폼팩터 계약이 담당.", signal="skipped")
        if not code_dir or not Path(code_dir).is_dir():
            return PackageabilityResult("SKIPPED", reason=f"code_dir 부재({code_dir}) — 배포성 판정 불가.", signal="skipped")
        code_dir = Path(code_dir)
        a = analyze_web_packageability(code_dir)

        if a.verdict == "SKIPPED":
            return PackageabilityResult("SKIPPED", reason=a.reason, signal="skipped")
        if a.verdict == "FAIL":
            return PackageabilityResult(
                "FAIL", reason=a.reason, signal=a.signal, command=a.command, serves_dist=a.serves_dist,
                dev_only=a.dev_only, error_excerpt=_fail_excerpt(a),
                extras={"start_kind": a.start_kind, "has_readme_cmd": a.has_readme_cmd},
            )

        if not run_probe:
            ok = a.serves_dist is not False
            return PackageabilityResult(
                "PASS" if ok else "FAIL",
                reason=a.reason + (" (probe 생략 — 구조 신호)." if ok else " 그러나 express 루트 서빙 전무 → 루트 Cannot GET 예상."),
                signal="structural_ok" if ok else "not_serving_dist",
                command=a.command, serves_dist=a.serves_dist, dev_only=a.dev_only,
                root_status="unverified", error_excerpt="" if ok else _fail_excerpt(a),
            )
        probe = _probe or _default_web_probe
        status, port, excerpt = probe(code_dir, a)
        if status == "loaded":
            return PackageabilityResult(
                "PASS", reason=f"프로덕션 단일 명령(`{a.command}`)으로 루트가 정상 로드됨. {excerpt}",
                signal="runtime_ok", command=a.command, serves_dist=True, dev_only=a.dev_only, root_status="loaded",
            )
        if status in ("cannot_get", "server_error"):
            return PackageabilityResult(
                "FAIL", reason=f"프로덕션 단일 명령(`{a.command}`) 기동 후 루트 로드 실패 — {excerpt}",
                signal="root_cannot_get" if status == "cannot_get" else "server_error",
                command=a.command, serves_dist=a.serves_dist, dev_only=a.dev_only, root_status=status,
                error_excerpt=(_fail_excerpt(a) + "\n\n■ 런타임: " + excerpt)[:1800],
            )
        # unverified — 구조 신호 폴백. express 루트서빙 전무(False)만 FAIL, True/None 은 PASS(거짓 FAIL 방지).
        if a.serves_dist is False:
            return PackageabilityResult(
                "FAIL",
                reason=f"express 서버가 dist 정적 서빙·루트 핸들러 신호 전무 → 루트 Cannot GET 고신뢰(런타임 미검증: {excerpt}).",
                signal="not_serving_dist", command=a.command, serves_dist=False, dev_only=a.dev_only,
                root_status="unverified", error_excerpt=_fail_excerpt(a),
            )
        return PackageabilityResult(
            "PASS", reason=f"{a.reason} 런타임 probe 미검증({excerpt}) — 구조상 차단 신호 없음.",
            signal="structural_ok", command=a.command, serves_dist=a.serves_dist, dev_only=a.dev_only, root_status="unverified",
        )
    except Exception as e:  # noqa: BLE001 — 게이트 결함이 메인 cycle 차단 X
        return PackageabilityResult("SKIPPED", reason=f"배포성 게이트 예외 — {type(e).__name__}: {e}. SKIPPED.", signal="skipped")


def _fail_excerpt(a: WebAnalysis) -> str:
    """FAIL 시 must-fix 로 주입될 실행가능 수정 지침(P12 conduit 입력)."""
    lines = [a.reason, "", "■ 배포성 계약(web) — 다음을 충족해야 COMPLETE 가능:"]
    lines.append("  1. 프로덕션 서버(예: server.js)가 빌드된 `dist/` 를 정적 서빙 + SPA fallback 으로 "
                 "루트 `/` 에서 index.html 을 응답하게 하세요: "
                 "`app.use(express.static(path.join(dir,'dist')))` + (API 라우트 *뒤*) "
                 "`app.use((req,res)=>res.sendFile(path.join(dir,'dist','index.html')))`. "
                 "※ Express 5 에서는 `app.get('*', …)` 가 path-to-regexp 에러를 내므로 *미들웨어형 fallback* 을 쓰세요.")
    lines.append("  2. `package.json` 에 `\"start\": \"node server.js\"` (또는 동급) *단일 명령* 을 추가 — "
                 "`concurrently`/`vite dev` 등 dev 전용 의존 금지. 한 포트에서 프론트+API 모두 제공.")
    lines.append("  3. `README.md` 에 단일 실행 명령 1줄(`npm start`)을 명시.")
    lines.append("  ※ 빌드(`npm run build → dist/`)는 그대로 두고, *프로덕션 서버가 그 dist 를 서빙* 하게만 고치세요.")
    return "\n".join(lines)
