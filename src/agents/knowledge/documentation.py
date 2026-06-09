# -*- coding: utf-8 -*-
"""v13 P27 — Documentation Lead (본부5 지식관리) 문서 생성 *결정론* 코어.

역할(진짜 가치 한정): 코드/빌드가 안정된 단계에서 *실 산출물*(생성 코드 + P25 단일 실행 계약)을
읽어, 비개발자가 셋업·실행·사용할 수 있는 문서를 산출물에 *묶어* 생산한다. **코드/계약에 실재하는
것만** 기술(보일러플레이트·환각 금지). P25 run-README 와 중복되면 *검증·보강*(덮어쓰기 금지), 진짜
가치가 없으면(안정 산출물 부재) skip.

설계(curate.py 형제 — 결정론 코어 + 선택적 LLM 보강):
  - `generate_documentation(code_dir, ...)` 가 **결정론**으로 사실(package.json scripts / 실행 계약 /
    listen 포트 / 파일 구조 / 진입점 / 의존성)을 추출해 정확한 문서를 만든다 — LLM 없이도 완전.
  - 산출: ``README.md``(루트, 셋업·실행 — P25 ``_README_RUN_RE`` 호환) + ``docs/USAGE.md``(사용) +
    ``docs/ARCHITECTURE.md``(구조, 선택). 모두 *실 산출물 디렉터리*(code_dir)에 배치 → 앱과 함께 배포.
  - 선택적 ``llm_call`` 보강(주입 가능, pytest 자동 skip): USAGE 개요 *산문* 만 사실에 근거해 다듬음.
    실패해도 결정론 문서는 그대로 — 셋업·실행(README)은 **항상 결정론**(정확성 보장, 환각 영향 0).

비차단/보존: 본 모듈은 파일 I/O 만 — 어떤 verdict/COMPLETE 판정도 만지지 않는다. 모든 디스크 작업은
OSError 격리(실패가 워크플로 차단 X). build_target web/desktop/none 별로 정확히 분기.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# 실행 명령 인식/보강 판정에 *정규식·마커·길이임계* 를 쓰지 않는다(적대 리뷰 P27 R2/R3): 정규식은
# 'node import' 오탐/'npm run serve' 미탐으로, 마커 substring 검사는 사용자 문서가 마커 문자열을 우연히
# 포함할 때 거짓 양성으로 *기존 README 를 덮어써 데이터를 잃는* 결함을 냈다. 대신 가장 안전한 불변식:
# **비어있지 않은 README 는 (우리 것이든 아니든) 절대 덮어쓰지 않는다** → 보존(augment) + docs/SETUP.md
# 로 정확한 셋업·실행을 보강. README 부재/공백뿐이면 새로 생성. (덮어쓰기 회피가 항상 안전.)

# 서버 파일에서 listen 포트 추출(보수적 — 확신될 때만). app.listen(3000) / PORT || 8080 / :5173 등.
_LISTEN_PORT_RE = re.compile(
    r"\.listen\s*\(\s*(\d{2,5})\b|"
    r"(?:PORT|port)\s*(?:\|\||\?\?|=|:)\s*[^\d\n]{0,8}(\d{2,5})\b|"
    r"localhost:(\d{2,5})\b",
)

# 문서/구조 나열에서 제외할 잡음(빌드 산출·VCS·의존성).
_TREE_IGNORE = {
    "node_modules", ".git", "dist", "build", "out", ".next", ".output", "__pycache__",
    ".venv", "venv", ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache", "target",
}

# 산출 문서 파일명(상대 경로).
README_NAME = "README.md"
SETUP_REL = "docs/SETUP.md"  # 보존(augment) 모드에서 README 를 안 건드리고 셋업·실행을 여기로
USAGE_REL = "docs/USAGE.md"
ARCH_REL = "docs/ARCHITECTURE.md"

# README 가 *우리 자동 생성본* 임을 식별하는 마커(이게 있으면 우리 것 → 최신 사실로 재생성).
_GENERATED_MARKER = "<!-- nexus-alpha:documentation-lead -->"


@dataclass
class DocumentationResult:
    """Documentation Lead 산출 결과(결정론, graceful — 예외 전파 없음)."""

    success: bool
    status: str  # "generated" | "augmented" | "skipped"
    reason: str = ""
    build_target: str = ""
    run_command: str = ""  # README 에 기술한 단일 실행 명령(없으면 "")
    generated_files: list[str] = field(default_factory=list)  # code_dir 기준 상대 경로
    warnings: list[str] = field(default_factory=list)  # 정확성 주의(불확실/누락) 정직 기록
    facts: dict = field(default_factory=dict)  # 추출 사실(투명성·테스트)
    elapsed_sec: float = 0.0
    error_message: str = ""


# ---------------------------------------------------------------------------
# 사실 추출 (결정론 — 실재 파일만)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _detect_listen_port(code_dir: Path) -> Optional[int]:
    """서버 소스에서 listen 포트 추출(확신될 때만, 보수적). 못 찾으면 None."""
    for name in ("server.js", "server.ts", "app.js", "app.ts", "index.js", "index.ts", "main.js"):
        p = code_dir / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = _LISTEN_PORT_RE.search(text)
        if m:
            for g in m.groups():
                if g and g.isdigit():
                    n = int(g)
                    if 1 <= n <= 65535:
                        return n
    return None


def _detect_python_entry(code_dir: Path) -> str:
    """none/desktop-소스 진입점(.py) 탐지 — 흔한 이름 우선, 없으면 __main__ 가드 보유 파일."""
    for name in ("main.py", "app.py", "__main__.py", "run.py", "cli.py"):
        if (code_dir / name).is_file():
            return name
    try:
        for p in sorted(code_dir.glob("*.py")):
            try:
                if "__main__" in p.read_text(encoding="utf-8", errors="ignore"):
                    return p.name
            except OSError:
                continue
    except OSError:
        pass
    return ""


def _top_level_tree(code_dir: Path, limit: int = 24) -> list[str]:
    """상위 레벨 파일/디렉터리(잡음 제외) — 구조 개요용."""
    out: list[str] = []
    try:
        for entry in sorted(code_dir.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name in _TREE_IGNORE or entry.name.startswith("."):
                continue
            out.append(entry.name + ("/" if entry.is_dir() else ""))
            if len(out) >= limit:
                break
    except OSError:
        pass
    return out


def _resolve_web_command(scripts: dict, run_contract: Any) -> tuple[str, str, list[str]]:
    """web 단일 실행 명령 결정(정확성 우선 — 실재 스크립트만, 발명 금지).

    Returns: (command, source, warnings). command 가 빈 문자열이면 신뢰 가능한 명령 미발견.
    """
    warnings: list[str] = []
    # 1) P25 배포성 게이트가 *검증* 한 명령(권위) — 단 *토큰 단위 검증* 후에만 신뢰(적대 리뷰 P27 R2:
    #    bare `npm`·`npm run`·`NPM start`·`yarn start`·미상 문자열을 무검증 신뢰하던 결함). 무효면 폴스루.
    contract_cmd = str(getattr(run_contract, "command", "") or "").strip()
    if contract_cmd:
        ok, warn, canonical = _validate_contract_command(contract_cmd, scripts)
        if ok:
            return canonical, "deployability_gate", warnings
        if warn:
            warnings.append(warn)
        # 무효 → package.json 기준 재해석으로 폴스루.
    # 2) package.json scripts — start 우선, 그 외 *서버 기동 의미* 스크립트(serve/preview)만(발명 0).
    if "start" in scripts:
        return "npm start", "package.json:start", warnings
    for cand in ("serve", "preview"):
        if cand in scripts:
            warnings.append(f"표준 `start` 스크립트 부재 — `{cand}` 스크립트를 실행 명령으로 기술.")
            return f"npm run {cand}", f"package.json:{cand}", warnings
    # 실행으로 볼 수 있는 스크립트가 없음 — *발명 금지*. 빈 명령 + 정직 안내(가용 스크립트 나열).
    if scripts:
        warnings.append(
            "표준 실행 스크립트(start/serve/preview)가 없어 단일 실행 명령을 확정하지 못함. "
            f"가용 스크립트: {', '.join(sorted(scripts))}."
        )
    else:
        warnings.append("package.json 에 실행 스크립트가 없어 단일 실행 명령을 확정하지 못함.")
    return "", "none", warnings


# 계약 명령으로 인정하는 직접 실행 런처(파일 인자 동반 시 실 명령으로 신뢰).
_DIRECT_LAUNCHERS = {"node", "python", "python3", "deno", "bun", "ts-node", "tsx"}
_PKG_MANAGERS = {"npm", "yarn", "pnpm"}


def _validate_contract_command(cmd: str, scripts: dict) -> tuple[bool, str, str]:
    """P25 계약 명령이 *실재 실행 명령* 인지 토큰 단위 검증(정규식 의존·발명 금지).

    Returns (ok, warning, canonical). ok=False 면 호출부가 package.json 기준으로 재해석.
      - npm/yarn/pnpm [run] <script>: 스크립트가 정확히 1개이고 start 이거나 scripts 에 실재해야 함
        (bare `npm`, `npm run`, `npm a b`, 미실재 스크립트 → 무효). canonical 은 패키지매니저명을
        소문자화('NPM start'→'npm start') — 나머지 토큰(run/스크립트)은 원형 보존.
      - node/python/deno/bun <파일>: 파일 인자가 있으면 인정(P25 가 실행으로 검증한 직접 명령, 그대로).
      - 그 외 미상 형식 → 무효(환각 방지).
    """
    toks = cmd.split()
    if not toks:
        return False, "", ""
    head = toks[0].lower()
    if head in _PKG_MANAGERS:
        rest = toks[1:]
        was_run = bool(rest) and rest[0].lower() == "run"
        if was_run:
            rest = rest[1:]
        if len(rest) != 1:  # bare 'npm', 'npm run', 'npm a b' 등 불완전/모호 → 무효
            return False, f"실행 계약 명령(`{cmd}`)이 불완전/모호(스크립트명 부재) — 무효 처리, package.json 기준 재해석.", ""
        # npm 스크립트명은 *case-sensitive* — 정확 일치만 인정(적대 리뷰 P27 R3: 대소문자 무시 매칭은
        # `npm build`↔`Build` 를 거짓 수용해 런타임에서 'Missing script' 로 실패하는 명령을 문서화했다).
        # 'start' 도 특례 없이 'start' 스크립트가 실재할 때만(없으면 fallback 의 동일 규칙으로 위임).
        script = rest[0]
        if script in scripts:
            # canonical: 패키지매니저명·run 키워드는 소문자화, *스크립트명은 원형(실제 키) 보존*.
            canon = [head, "run", script] if was_run else [head, script]
            return True, "", " ".join(canon)
        return False, f"실행 계약 명령(`{cmd}`)의 스크립트(`{script}`)가 package.json 에 없음 — 무효 처리, package.json 기준 재해석.", ""
    if head in _DIRECT_LAUNCHERS:
        if len(toks) >= 2:  # node <파일> 등 — 파일 인자 동반(P25 검증분, 경로 대소문자 보존)
            return True, "", cmd
        return False, f"실행 계약 명령(`{cmd}`)이 불완전(대상 파일 부재) — 무효 처리.", ""
    return False, f"실행 계약 명령(`{cmd}`)을 인식할 수 없음 — package.json 기준 재해석.", ""


def _extract_facts(code_dir: Path, build_target: str, run_contract: Any, exe_name: str) -> dict:
    """code_dir + 실행 계약에서 *결정론* 사실 추출(실재 파일만)."""
    bt = (build_target or "").strip().lower() or "unspecified"
    facts: dict[str, Any] = {
        "build_target": bt,
        "app_name": "",
        "description": "",
        "scripts": {},
        "dependencies": [],
        "run_command": "",
        "run_source": "",
        "listen_port": None,
        "python_entry": "",
        "exe_name": exe_name or "",
        "top_level": _top_level_tree(code_dir),
        "has_requirements_txt": (code_dir / "requirements.txt").is_file(),
        "existing_readme": (code_dir / README_NAME).is_file(),
    }
    warnings: list[str] = []

    pkg = _read_json(code_dir / "package.json")
    if pkg:
        facts["app_name"] = str(pkg.get("name") or "").strip()
        facts["description"] = str(pkg.get("description") or "").strip()
        scripts = pkg.get("scripts")
        if isinstance(scripts, dict):
            facts["scripts"] = {str(k): str(v) for k, v in scripts.items() if isinstance(k, str)}
        deps = pkg.get("dependencies")
        if isinstance(deps, dict):
            facts["dependencies"] = sorted(str(k) for k in deps.keys())[:20]

    if bt == "web":
        cmd, src, warns = _resolve_web_command(facts["scripts"], run_contract)
        facts["run_command"], facts["run_source"] = cmd, src
        warnings.extend(warns)
        port = _detect_listen_port(code_dir)
        if port is None:
            port = getattr(run_contract, "extras", {}).get("listen_port") if run_contract is not None else None
        facts["listen_port"] = port if isinstance(port, int) else None
    elif bt == "desktop":
        if exe_name:
            facts["run_command"], facts["run_source"] = exe_name, "build_artifact"
        else:
            warnings.append("desktop 빌드 산출(.exe) 경로 미확인 — 실행 명령 기술 제한.")
    else:  # none / unspecified
        entry = _detect_python_entry(code_dir)
        facts["python_entry"] = entry
        if entry:
            facts["run_command"], facts["run_source"] = f"python {entry}", "python_entry"
        else:
            warnings.append("Python 진입점(.py)을 확정하지 못해 실행 명령 기술 제한.")

    facts["_warnings"] = warnings
    return facts


# ---------------------------------------------------------------------------
# 문서 본문 생성 (결정론 — 사실만 기술)
# ---------------------------------------------------------------------------
def _setup_block(facts: dict) -> str:
    bt = facts["build_target"]
    if bt == "web":
        return "프로젝트 디렉터리에서 의존성을 설치합니다:\n\n```\nnpm install\n```"
    if bt == "desktop":
        exe = facts.get("exe_name") or "앱 실행 파일"
        return f"별도 설치가 필요 없습니다 — 빌드 산출물(`{exe}`)을 그대로 실행합니다."
    if facts.get("has_requirements_txt"):
        return "필요한 패키지를 설치합니다:\n\n```\npip install -r requirements.txt\n```"
    return "별도 의존성 설치 단계가 확인되지 않았습니다(코드 그대로 실행)."


def _run_block(facts: dict) -> str:
    bt = facts["build_target"]
    cmd = facts.get("run_command", "")
    if bt == "web":
        if cmd:
            url = ""
            if facts.get("listen_port"):
                url = f"\n\n실행 후 브라우저에서 `http://localhost:{facts['listen_port']}` 로 접속합니다."
            return f"아래 단일 명령으로 프로덕션 서버를 실행합니다:\n\n```\n{cmd}\n```{url}"
        return "⚠️ package.json 에서 신뢰할 수 있는 단일 실행 명령을 확인하지 못했습니다(아래 비고 참고)."
    if bt == "desktop":
        if cmd:
            return f"빌드 산출물을 실행합니다(더블클릭 또는):\n\n```\n.\\{cmd}\n```"
        return "빌드된 실행 파일(.exe)을 더블클릭해 실행합니다."
    if cmd:
        return f"아래 명령으로 실행합니다:\n\n```\n{cmd}\n```"
    return "⚠️ 실행 진입점을 확정하지 못했습니다(아래 비고 참고)."


def _usage_features(facts: dict) -> list[str]:
    """코드에 *실재* 하는 요소만 사용 항목으로 — 환각 금지."""
    items: list[str] = []
    if facts["build_target"] == "web" and facts.get("listen_port"):
        items.append(f"브라우저에서 `http://localhost:{facts['listen_port']}` 로 앱에 접속")
    scripts = facts.get("scripts") or {}
    for key in ("test", "build", "lint"):
        if key in scripts:
            items.append(f"`npm run {key}` — {key} 스크립트 (package.json 에 정의됨)")
    deps = facts.get("dependencies") or []
    if deps:
        items.append("주요 의존성: " + ", ".join(deps[:8]))
    return items


def _render_readme_body(facts: dict, app_name: str, description: str) -> str:
    lines = [
        _GENERATED_MARKER,
        f"# {app_name}",
        "",
        description,
        "",
        "> 이 문서는 Documentation Lead(본부5 지식관리)가 **실제 산출물(코드·빌드·실행 계약)을 읽어**",
        "> 자동 생성했습니다. 코드에 실재하는 명령·기능만 기술합니다.",
        "",
        "## 셋업",
        "",
        _setup_block(facts),
        "",
        "## 실행",
        "",
        _run_block(facts),
        "",
        "## 사용",
        "",
        "자세한 사용 가이드는 [docs/USAGE.md](docs/USAGE.md), 구조 개요는 "
        "[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 를 참고하세요.",
    ]
    warns = facts.get("_warnings") or []
    if warns:
        lines += ["", "## 비고", ""] + [f"- {w}" for w in warns]
    lines += [
        "",
        "---",
        f"_자동 생성: Documentation Lead · 빌드 타깃 `{facts['build_target']}` · 실행 명령 출처 "
        f"`{facts.get('run_source') or 'n/a'}`_",
        "",
    ]
    return "\n".join(lines)


def _render_usage_body(facts: dict, app_name: str, overview: str) -> str:
    lines = [f"# 사용 가이드 — {app_name}", ""]
    if overview:
        lines += ["## 개요", "", overview, ""]
    lines += ["## 시작하기", "", _run_block(facts), ""]
    features = _usage_features(facts)
    if features:
        lines += ["## 기능", ""] + [f"- {f}" for f in features] + [""]
    lines += [
        "## 비고",
        "",
        "이 가이드는 코드에 실재하는 요소(스크립트·포트·의존성)만 기술합니다. 추측 기능은 포함하지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def _render_architecture_body(facts: dict, app_name: str) -> str:
    lines = [f"# 구조 개요 — {app_name}", "", f"빌드 타깃: `{facts['build_target']}`", ""]
    deps = facts.get("dependencies") or []
    if deps:
        lines += ["## 기술 스택(주요 의존성)", ""] + [f"- `{d}`" for d in deps[:15]] + [""]
    entries: list[str] = []
    if facts.get("python_entry"):
        entries.append(f"`{facts['python_entry']}` (Python 진입점)")
    if facts.get("exe_name"):
        entries.append(f"`{facts['exe_name']}` (실행 파일)")
    scripts = facts.get("scripts") or {}
    for k, v in list(scripts.items())[:8]:
        entries.append(f"`npm run {k}` → `{v}`")
    if entries:
        lines += ["## 진입점 / 스크립트", ""] + [f"- {e}" for e in entries] + [""]
    tree = facts.get("top_level") or []
    if tree:
        lines += ["## 파일 구조(상위)", "", "```"] + tree + ["```", ""]
    return "\n".join(lines)


def _render_setup_body(facts: dict, app_name: str) -> str:
    """보존(augment) 모드 전용 — README 를 안 건드리고 *정확한 셋업·실행* 을 여기에 제공."""
    lines = [
        f"# 셋업 · 실행 — {app_name}",
        "",
        "> 기존 README 를 보존하고, Documentation Lead 가 실 산출물에서 확인한 *정확한* 셋업·실행 절차를 별도로 제공합니다.",
        "",
        "## 셋업",
        "",
        _setup_block(facts),
        "",
        "## 실행",
        "",
        _run_block(facts),
    ]
    warns = facts.get("_warnings") or []
    if warns:
        lines += ["", "## 비고", ""] + [f"- {w}" for w in warns]
    lines += ["", f"_빌드 타깃 `{facts['build_target']}` · 실행 명령 출처 `{facts.get('run_source') or 'n/a'}`_", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 선택적 LLM 보강 (사실 근거 — 주입 가능, pytest skip)
# ---------------------------------------------------------------------------
_OVERVIEW_PROMPT = (
    "당신은 정확성을 최우선하는 테크니컬 라이터입니다. 아래 *사실*(코드에서 추출)만 근거로, 이 앱이 "
    "무엇을 하는 앱인지 2~3문장 한국어 개요를 작성하세요. 사실에 없는 기능을 추측·발명하지 마세요. "
    "불확실하면 일반적 표현으로 축소하세요. 개요 문장만 출력(머리말·코드펜스 금지).\n\n"
    "[앱 이름] {app_name}\n[설명] {description}\n[빌드 타깃] {build_target}\n"
    "[실행 명령] {run_command}\n[주요 의존성] {dependencies}\n[원 요청] {user_request}\n"
)


def _build_overview(facts: dict, app_name: str, description: str, user_request: str,
                    llm_call: Optional[Callable[[str], str]]) -> str:
    """LLM 보강 개요(있을 때만). 실패/미주입/pytest → 결정론 description 으로 폴백."""
    fallback = description or f"`{app_name}` 앱입니다."
    if llm_call is None:
        return fallback
    prompt = _OVERVIEW_PROMPT.format(
        app_name=app_name, description=description or "(없음)", build_target=facts["build_target"],
        run_command=facts.get("run_command") or "(미확정)",
        dependencies=", ".join(facts.get("dependencies") or []) or "(없음)",
        user_request=(user_request or "").strip()[:500] or "(없음)",
    )
    try:
        out = (llm_call(prompt) or "").strip()
    except Exception:  # noqa: BLE001 — 보강 실패가 문서 생성을 막지 않음
        return fallback
    # 환각/형식 오염 방지: 코드펜스/머리말 제거, 과도 길이 컷.
    out = out.replace("```", "").strip()
    return out[:600] if out else fallback


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def _readme_exists_with_content(code_dir: Path) -> bool:
    """README 가 *비어있지 않게* 존재하면 True → 절대 덮어쓰지 않는다(데이터 손실 방지, 보존=augment).

    마커/길이임계/정규식에 의존하지 않는다 — 비어있지 않은 README 면 (우리 것이든 사용자 것이든) 보존이
    항상 안전하다(덮어쓰기 회피). 부재/공백뿐이면 False(새 README 생성). 존재하나 못 읽으면 *보수적 보존*.
    """
    p = code_dir / README_NAME
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True  # 존재하나 못 읽음 → 덮어쓰지 않음(보수적 보존)
    return bool(text.strip())


def generate_documentation(
    code_dir: Path,
    *,
    build_target: str = "unspecified",
    run_contract: Any = None,
    user_request: str = "",
    app_name: str = "",
    exe_name: str = "",
    llm_call: Optional[Callable[[str], str]] = None,
) -> DocumentationResult:
    """code_dir(실 산출물)에 셋업·실행·사용·구조 문서를 결정론으로 생성/보강.

    Args:
        code_dir: 생성 코드/빌드 산출 디렉터리(README·docs 를 여기에 배치 → 앱과 함께 배포).
        build_target: "web" | "desktop" | "none"/"unspecified". 셋업·실행 분기 + P25 호환.
        run_contract: P25 ``PackageabilityResult`` (있으면 검증된 단일 실행 명령 권위로 사용).
        user_request: 원 자연어 요청(LLM 개요 보강의 근거 1).
        app_name / exe_name: 호출 측이 알면 주입(없으면 package.json/계약에서 추출).
        llm_call: 선택적 LLM 보강(USAGE 개요 산문만). None+비-pytest → 기본 호출, pytest → skip.

    Returns:
        ``DocumentationResult`` — 항상 반환(예외 전파 없음). 안정 산출물 부재/디렉터리 없음 → skipped.
    """
    start = time.monotonic()
    try:
        if not isinstance(code_dir, Path) or not code_dir.is_dir():
            return DocumentationResult(
                success=False, status="skipped", reason="code_dir 미존재 — 안정 산출물 없음(문서 가치 없음).",
                build_target=(build_target or "").lower(),
            )

        facts = _extract_facts(code_dir, build_target, run_contract, exe_name)
        resolved_name = (app_name or facts.get("app_name") or code_dir.name or "앱").strip()
        description = facts.get("description") or (user_request or "").strip()[:200] or f"`{resolved_name}` 앱입니다."

        in_pytest = "pytest" in sys.modules
        if llm_call is None and not in_pytest:
            llm_call = _default_llm_call
        overview = _build_overview(facts, resolved_name, facts.get("description", ""), user_request, llm_call)

        # 중복 회피(덮어쓰기 회피 우선): 비어있지 않은 README 는 *절대 덮어쓰지 않고*(데이터 손실 방지)
        # docs/SETUP.md 로 정확한 셋업·실행을 보강. README 부재/공백뿐 → 새 README 생성.
        preserve = _readme_exists_with_content(code_dir)
        generated: list[str] = []
        docs_dir = code_dir / "docs"

        if preserve:
            # README 미접촉 — 셋업·실행은 docs/SETUP.md 로(보존하면서도 정확한 절차 전달).
            if _safe_write(code_dir / SETUP_REL, _render_setup_body(facts, resolved_name), parent=docs_dir):
                generated.append(SETUP_REL)
        else:
            body = _render_readme_body(facts, resolved_name, description)
            if _safe_write(code_dir / README_NAME, body):
                generated.append(README_NAME)

        if _safe_write(code_dir / USAGE_REL, _render_usage_body(facts, resolved_name, overview), parent=docs_dir):
            generated.append(USAGE_REL)
        if _safe_write(code_dir / ARCH_REL, _render_architecture_body(facts, resolved_name), parent=docs_dir):
            generated.append(ARCH_REL)

        # status/success 정합(적대 리뷰 P27 R3/R4): *핵심 문서*(생성=README, 보존=docs/SETUP)가 실제로
        # 기록됐을 때만 generated/augmented(+success). 핵심 문서 기록 실패(보조만/전무) → skipped+success=False.
        core_written = (SETUP_REL in generated) if preserve else (README_NAME in generated)
        if core_written and preserve:
            status, success_flag = "augmented", True
            reason = "기존 README 를 보존(덮어쓰기 금지)하고 docs/SETUP.md+docs/ 로 정확한 셋업·실행·사용·구조 보강."
        elif core_written:
            status, success_flag = "generated", True
            reason = "실 산출물을 읽어 셋업·실행·사용·구조 문서 생성."
        else:
            status, success_flag = "skipped", False
            reason = "핵심 문서(README/docs/SETUP) 디스크 기록 실패 — 신뢰할 산출 없음."
        warns = list(facts.get("_warnings") or [])
        # facts 에서 내부 키 제거(투명 공개용).
        public_facts = {k: v for k, v in facts.items() if not k.startswith("_")}
        return DocumentationResult(
            success=success_flag,
            status=status,
            reason=reason,
            build_target=facts["build_target"],
            run_command=facts.get("run_command", ""),
            generated_files=generated,
            warnings=warns,
            facts=public_facts,
            elapsed_sec=round(time.monotonic() - start, 4),
        )
    except Exception as exc:  # noqa: BLE001 — 문서 생성 실패가 워크플로 차단 X
        return DocumentationResult(
            success=False, status="skipped", reason="문서 생성 중 예외(무시, 비차단).",
            build_target=(build_target or "").lower(), error_message=repr(exc)[:300],
            elapsed_sec=round(time.monotonic() - start, 4),
        )


def _safe_write(path: Path, content: str, *, parent: Optional[Path] = None) -> bool:
    """파일 쓰기(OSError 격리). 성공 시 True."""
    try:
        (parent or path.parent).mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def _default_llm_call(prompt: str) -> str:
    """비-pytest 프로덕션 LLM 보강 — Documentation Lead 에이전트 경유(실패 격리)."""
    try:
        from crewai import Crew, Task  # noqa: PLC0415

        from .documentation_lead import create_documentation_lead_agent  # noqa: PLC0415

        agent = create_documentation_lead_agent()
        task = Task(description=prompt, expected_output="2~3문장 한국어 개요(사실 근거).", agent=agent)
        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        return str(crew.kickoff())
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "DocumentationResult",
    "generate_documentation",
    "README_NAME",
    "SETUP_REL",
    "USAGE_REL",
    "ARCH_REL",
]
