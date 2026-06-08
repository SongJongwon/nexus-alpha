# -*- coding: utf-8 -*-
"""
analyze_and_implement — 4-agent 협업 워크플로우 + Phase 4 GUI 분기 옵션.

기본(Phase 2-P2 호환): CTO → Data Analyst → Python Engineer → Code Reviewer
    `enable_gui_branch=False` (기본). 4-agent 그대로. 기존 호출·테스트와 100%
    backward compatible — 동일 산출물·동일 파일 레이아웃·동일 결과 필드.

Phase 4 GUI 분기 (`enable_gui_branch=True`):
    1. UI/UX Analyst (planning) 가 먼저 실행 → ui_spec
    2. ui_spec 의 `need_gui` 를 파싱해 경로 결정
    3. 경로 분기:
         - `gui` : CTO → Analyst → GUI Designer → Theme Designer →
                   GUI Code Generator → Code Reviewer (디자인 본부 3명 + 1)
         - `cli` : CTO → Analyst → Python Engineer → Code Reviewer
                   (UI/UX context 만 추가, 나머진 기존 그대로)
    4. 산출 파일은 기존 `00~04` 유지 + GUI 활성 시 `10~13` 추가.

LangFuse 통합:
    단일 trace(`analyze_and_implement`) 아래에 모든 generation 이 기록되도록
    kickoff 전에 `log_trace` 호출, 종료 후 `end_trace + flush`. 자식 generation
    카운트는 활성 옵션에 따라 4 (기본) ~ 7 (GUI 분기) 사이.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional, Sequence

from crewai import Crew, Process, Task

from src.agents.analysis import create_data_analyst_agent
from src.agents.c_level import create_cto_agent
from src.agents.design import (
    create_gui_code_generator_agent,
    create_gui_designer_agent,
    create_theme_designer_agent,
)
from src.agents.engineering import create_python_engineer_agent
from src.agents.planning import create_uiux_analyst_agent
from src.agents.qa import create_code_reviewer_agent, create_pytest_author_agent
from src.monitoring import get_langfuse_client
from src.workflows._common import (
    SUSPICIOUS_OUTPUT_THRESHOLD as _SUSPICIOUS_OUTPUT_THRESHOLD,
    kickoff_with_converter_rescue,
    retry_short_tasks_in_chain,
    task_output_text as _task_output_text,
)
from src.workflows._schemas import (
    CodeReviewOutput,
    GUICodeOutput,
    GUIDesignOutput,
    PytestSuiteOutput,
    ThemeTokensOutput,
    UIUXSpecOutput,
    qa_review_body_is_empty,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"


@dataclass
class WorkflowResult:
    """4-agent (또는 Phase 4 활성 시 6~7-agent) 협업 워크플로우의 최종 산출물.

    Attributes:
        user_request: 사용자가 제출한 원본 자연어 요구사항.
        cto_strategy: CTO 전략 문서.
        analyst_brief: Data Analyst 분석 지시서.
        engineer_output: Python Engineer 산출. CLI 경로에서 채워짐. GUI 경로에선
            빈 문자열 (대신 `gui_code_output` 사용).
        qa_review: Code Reviewer 정적 리뷰 보고서. 마지막 줄에 `Final Answer:`
            APPROVED/NEEDS_REVISION 포함.
        saved_dir: 산출물이 저장된 디렉터리 경로.
        saved_code_files: 추출되어 저장된 `.py` 경로들. CLI 경로면 engineer_output
            에서, GUI 경로면 gui_code_output 에서 추출.

    Phase 4 추가 필드 (모두 기본값 — 기존 호출·테스트 backward compat):
        chosen_path: "cli" | "gui" | "" (Phase 4 미활성 시 빈 문자열).
        ui_spec: UI/UX Analyst 산출 마크다운. Phase 4 활성 시만 채워짐.
        gui_design: GUI Designer 산출 (와이어프레임 + 위젯 트리). GUI 경로만.
        design_tokens: Theme Designer 산출 (디자인 토큰 JSON). GUI 경로만.
        gui_code_output: GUI Code Generator 산출. GUI 경로만.

    Phase 4.5 추가 필드 (모두 기본값 — backward compat):
        dependency_report: Dependency Analyzer YAML 보고서.
        build_spec: Build Engineer 빌드 사양 (도구 선택 + spec/명령).
        asset_manifest: Asset Manager 자원 매니페스트.
        installer_spec: Installer Creator 인스톨러 스크립트.
        platform_test_report: Platform Tester narration 보고서.

    Phase 5 추가 필드 (모두 기본값 — backward compat):
        release_decision: Release Manager SemVer 결정 + RELEASE.md 초안.
        changelog_entry: Changelog Generator Keep a Changelog 항목.
        update_module_spec: Update Checker 자동 업데이트 모듈 사양.
        distribution_spec: Distribution Agent 배포 사양 (채널/URL/SHA256).

    PR #58 추가 필드 (backward compat — 기본 빈 문자열):
        pytest_suite: Pytest Author 산출 — workflow 안에서 entry 코드를 읽고
            ``test_<entry>.py`` 를 작성한 마크다운. ```python``` 블록은 같은
            ``code/`` 디렉터리에 ``test_*.py`` 로 저장되어 후속
            ``run_code_qa(target_dir=code/)`` 가 SKIPPED → ACTIVE 가 된다.
    """

    user_request: str
    cto_strategy: str
    analyst_brief: str
    engineer_output: str
    qa_review: str
    saved_dir: Path
    saved_code_files: list[Path] = field(default_factory=list)
    # Phase 4 — backward-compat 기본값
    chosen_path: str = ""
    ui_spec: str = ""
    gui_design: str = ""
    design_tokens: str = ""
    gui_code_output: str = ""
    # Phase 4.5 — backward-compat 기본값
    dependency_report: str = ""
    build_spec: str = ""
    asset_manifest: str = ""
    installer_spec: str = ""
    platform_test_report: str = ""
    # Phase 5 — backward-compat 기본값
    release_decision: str = ""
    changelog_entry: str = ""
    update_module_spec: str = ""
    distribution_spec: str = ""
    # PR #58 — Pytest Author 산출 (active code_qa 도달용)
    pytest_suite: str = ""
    # PR #36/#37 — PyInstaller executor 결과 (enable_executor=True 시만)
    executor_result: object = None  # ExecuteResult | None — circular import 회피용 object
    # PR #39 — GitHub Release publish 결과 (enable_publish=True 시만)
    publish_result: object = None  # PublishResult | None — 동일 사유


# ---------------------------------------------------------------------------
# 내부 헬퍼 — _task_output_text / SUSPICIOUS_OUTPUT_THRESHOLD 는 _common 으로 이동
# (PR #29, 이슈 6 fix). build_workflow / release_workflow 와 동일 구현 공유.
# ---------------------------------------------------------------------------


# v13 Phase 6.E P2-A (PR #236) — web 코드 추출 지원 (fence 언어 → 기본 확장자)
_FENCE_LANG_EXT: dict[str, str] = {
    "python": ".py", "py": ".py",
    "typescript": ".ts", "ts": ".ts", "tsx": ".tsx",
    "javascript": ".js", "js": ".js", "jsx": ".jsx",
    "html": ".html", "css": ".css", "json": ".json",
    # v13 Phase 6.E P10a(1) — LLM 이 manifest 를 ```jsonc / ```json5 로 fence 하는 경우
    # (// 주석 동반) 도 .json 으로 매핑해 인식 (P9 verdict: package.json/tsconfig 드롭 진범).
    "jsonc": ".json", "json5": ".json",
}
# Track A(CLI)/pytest/release 경로는 python-only (회귀 0). GUI web 경로만 확장.
_PY_ONLY_LANGS: tuple[str, ...] = ("python", "py")
_WEB_CODE_LANGS: tuple[str, ...] = (
    "python", "py", "typescript", "ts", "tsx",
    "javascript", "js", "jsx", "html", "css", "json",
    # P10a(1) — jsonc/json5 도 web 산출 언어로 허용 (언어 게이트 통과).
    "jsonc", "json5",
)
_WEB_FILE_EXTS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".json"}
)
# file: 헤더 — #(py) / //(ts,js) / <!--(html) / /*(css) 주석 스타일 모두 지원.
_FILE_HEADER_RE = re.compile(
    r"\s*(?:#|//|<!--|/\*)\s*file:\s*([^\s*>]+\.[A-Za-z0-9]+)", re.IGNORECASE
)
# v13 Phase 6.E P9 — fence-info 파일명 (```json package.json) / 앞줄 "package.json:" 류.
_INFO_FILENAME_RE = re.compile(r"[\w./\\-]+\.[A-Za-z0-9]+")
_LEADING_NAME_RE = re.compile(r"\s*([\w./\\-]+\.[A-Za-z0-9]+)\s*:\s*$")


def _wellknown_json_name(block: str) -> Optional[str]:
    """헤더 없는 ``` ```json ``` 블록을 *내용* 으로 well-known manifest 인식 (P9).

    JSON 은 주석(``//``/``#``)이 불법이라 LLM 이 ``file:`` 헤더를 못 붙이는 경우가
    있다. package.json / tsconfig.json 은 web 빌드 필수 manifest 이므로 예시 데이터와
    구분되는 고유 키로 식별해 파일명을 부여한다 (그 외 헤더리스 json 은 기존대로 드롭).
    """
    low = block.lower()
    if '"compileroptions"' in low:
        return "tsconfig.json"
    if (
        '"dependencies"' in low
        or '"devdependencies"' in low
        or ('"scripts"' in low and '"name"' in low)
    ):
        return "package.json"
    return None


def _resolve_block_filename(lang: str, info: str, block: str) -> tuple[Optional[str], bool]:
    """fenced 블록의 파일명 + 첫 줄(헤더) 제거 여부를 결정 (P9).

    우선순위: (1) 첫 줄 ``# file:`` / ``// file:`` / ``<!-- file:`` / ``/* file:`` 헤더
    (기존 1순위, 회귀 0) → (2) fence-info 파일명 (```json package.json) → (3) 앞줄
    "package.json:" 류 → (4) well-known headerless json (내용 식별). 어떤 신호도
    없으면 (None, False) → 호출부가 기존 동작(block01.<ext> / headerless json 드롭) 유지.

    Returns:
        (파일명 | None, strip_first_line) — strip_first_line=True 면 첫 줄이 헤더/마커라
        본문에서 제거 대상 (json 유효성 보장용; 비-json 은 호출부에서 보존).
    """
    first_line = block.splitlines()[0] if block.strip() else ""
    header = _FILE_HEADER_RE.match(first_line)
    if header:
        return header.group(1), True
    if info and _INFO_FILENAME_RE.fullmatch(info):
        return info, False
    leading = _LEADING_NAME_RE.match(first_line)
    if leading:
        return leading.group(1), True
    if lang in ("json", "jsonc", "json5"):  # P10a(1) — jsonc/json5 도 well-known 인식
        wk = _wellknown_json_name(block)
        if wk:
            return wk, False
    return None, False


def _normalize_jsonc_to_json(text: str) -> str:
    """jsonc/json5 본문을 strict JSON 으로 정규화 (P10a(2)).

    줄 ``//`` 주석 · ``/* */`` 블록 주석 · trailing comma(`,}`/`,]`) 제거.
    npm(package.json)·tsc(tsconfig.json)는 strict JSON 파서라 주석/trailing comma 거부 —
    (1)만으로 jsonc 를 .json 으로 저장해도 npm 이 파싱 실패할 수 있어 본 정규화가 필요.
    문자열 리터럴 안의 ``//``·``/*``·``,`` 는 상태머신으로 보존 (정규식 단독은 불안전).
    json5 의 single-quote/unquoted-key 변환은 범위 밖 (manifest 는 표준 JSON+주석 형태).
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str = True
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":  # 줄 주석
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":  # 블록 주석
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        if c == ",":  # trailing comma — 다음 비공백이 }/] 면 콤마 삭제
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _safe_rel_path(name: str) -> Optional[Path]:
    """``name`` 을 code_dir 내부 상대경로로 정규화 (P10b(i)).

    절대경로/드라이브/``..`` traversal 이면 None (호출부가 평탄화 fallback). 그 외엔
    선두 ``/`` 제거 + ``\\``→``/`` 정규화 후 깨끗한 상대 Path 반환. FS 미접근(순수 경로).
    """
    norm = name.replace("\\", "/").lstrip("/")
    parts = [p for p in PurePosixPath(norm).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if ":" in parts[0]:  # 드라이브 문자 (C:) 등 절대경로 잔재 차단
        return None
    return Path(*parts)


def _extract_code_blocks(
    markdown: str,
    code_dir: Path,
    *,
    languages: tuple[str, ...] = _PY_ONLY_LANGS,
    preserve_tree: bool = False,
) -> list[Path]:
    """fenced 코드 블록을 추출해 `code_dir` 아래에 파일로 저장한다.

    블록 첫 줄에 ``# file:`` / ``// file:`` / ``<!-- file:`` / ``/* file:`` 헤더가
    있으면 그 이름(확장자 포함)을 사용하고, 없으면 fence 언어 기본 확장자로
    ``block01.<ext>`` 순번을 매긴다.

    ``languages``: 추출 대상 fence 언어 집합. 기본 python-only (Track A CLI/pytest/
    release 경로 회귀 0). GUI web 경로는 ``_WEB_CODE_LANGS`` 를 넘겨 .ts/.html/.css
    등 web 산출을 정상 추출 — v13 Phase 6.E P2-A (PR #236): "완전한 Three.js SPA 를
    산출하고도 ```python 펜스만 추출해 web 코드를 0개 저장하던" 손실 수정.
    """
    code_dir.mkdir(parents=True, exist_ok=True)
    # v13 Phase 6.E P9 — 닫는 fence 들여쓰기 허용(`\n[ \t]*```) + fence-info(info string) 캡처.
    #   배경 (P3 verdict 확정): 들여쓰기된 ```bash 의존성 블록의 닫는 fence 가 `  ``` `
    #   (들여쓰기) 인데 기존 닫기 `\n``` ` 는 column-0 만 매칭 → 못 닫고 뒤를 삼킴 →
    #   직후 ```json (package.json/tsconfig.json) 페어링 desync → 드롭. 들여쓰기 허용으로
    #   페어링 복원. info string 캡처로 ```json package.json 형태 파일명도 인식.
    pattern = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*([^\n]*)\n(.*?)\n[ \t]*```", re.DOTALL)
    allowed = {lang.lower() for lang in languages}
    saved: list[Path] = []
    for idx, (lang_raw, info_raw, block) in enumerate(pattern.findall(markdown), start=1):
        lang = lang_raw.strip().lower()
        if lang not in allowed:
            continue
        name, strip_first_line = _resolve_block_filename(lang, info_raw.strip(), block)
        if name is None:
            ext = _FENCE_LANG_EXT.get(lang, ".py")
            # 헤더·파일명 신호 없는 headerless json 은 예시 데이터일 수 있어 저장 안 함.
            if ext == ".json":
                continue
            name = f"block{idx:02d}{ext}"
        # v13 Phase 6.E P10b(i) — web 경로(preserve_tree)면 실 디렉터리 트리로 작성
        # (src/main.ts → code/src/main.ts). 그 외엔 기존 평탄화(src__main.ts) 유지 — 회귀 0.
        # traversal 비정상 시 평탄화 fallback.
        if preserve_tree:
            rel = _safe_rel_path(name)
            file_path = (code_dir / rel) if rel is not None else (
                code_dir / name.replace("/", "__").replace("\\", "__")
            )
        else:
            file_path = code_dir / name.replace("/", "__").replace("\\", "__")
        content = block
        # json 산출은 주석(// 등)이 불법 → file: 헤더 줄 제거 + jsonc→strict JSON 정규화로
        # 유효 JSON 보장 (P9-3 + P10a(2)). 비-json(.ts/.html/.css/.py)은 본문 보존 — 회귀 0.
        if file_path.suffix.lower() == ".json":
            if strip_first_line:
                content = content.split("\n", 1)[1] if "\n" in content else ""
            content = _normalize_jsonc_to_json(content)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        saved.append(file_path)
    return saved


def _detect_extraction_loss(
    gui_code_output: str, saved_paths: list[Path]
) -> Optional[str]:
    """GUI web 산출에 web 파일 헤더가 다수인데 추출된 web 파일이 0개면 경고 반환.

    v13 Phase 6.E P2-A (PR #236) — "정답 web 코드를 조용히 버리는" 손실 방지.
    iter2 사례(완전한 Three.js SPA 산출 → code/ 에 web 0개, tkinter stub 만 남음)
    재발 시 가시화. 손실 없으면 None.
    """
    web_headers = [
        h
        for h in _FILE_HEADER_RE.findall(gui_code_output or "")
        if Path(h).suffix.lower() in _WEB_FILE_EXTS
    ]
    saved_web = [p for p in saved_paths if p.suffix.lower() in _WEB_FILE_EXTS]
    if len(web_headers) >= 2 and not saved_web:
        return (
            f"⚠ extraction loss — gui_code_output 에 web 파일 헤더 "
            f"{len(web_headers)}개({web_headers[:5]}) 인데 추출된 web 파일 0개. "
            "web 산출이 code/ 에 저장되지 못했습니다 (P2-A 손실 가드)."
        )
    # v13 Phase 6.E P9 — 부분 손실 가드: web 산출이 일부 저장됐어도(추출>0) web 빌드
    # 필수 manifest 인 package.json 이 *선언됐는데 미저장* 이면 경고 (npm build ENOENT
    # 직결). 기존 "추출 0개" 전손 경로는 위에서 이미 처리 (이 경로는 부분손실 전용).
    declared = {Path(h).name.lower() for h in _FILE_HEADER_RE.findall(gui_code_output or "")}
    saved_names = {p.name.lower() for p in saved_paths}
    if saved_web and "package.json" in declared and "package.json" not in saved_names:
        return (
            "⚠ partial extraction loss — web 산출에 package.json(manifest) 헤더가 "
            "선언됐으나 code/ 에 추출되지 않음 → npm build ENOENT 직결. "
            "web 파일 일부만 저장됨 (P9 manifest-loss 가드)."
        )
    return None


# v13 Phase 6.E P14 (수정3) — 코드젠 출력 무결성: 비현실적 단축 산출 = 생성 실패
_MIN_GUI_CODE_BYTES: int = 200  # 추출 코드 총 바이트가 이 미만이면 degenerate (예: 31 bytes)


def _is_degenerate_codegen(code_paths: list[Path], platform_intent: str) -> bool:
    """P14(수정3) — 코드 생성 산출이 비현실적으로 짧거나 entry/manifest 부재면 True.

    retry_short_tasks_in_chain 후에도 단축(예: block01.py 31 bytes)이거나, web 인데
    index.html·package.json 둘 다 부재면 '생성 실패' 로 판정 (깨진 출력이 유효 산출로
    빌드/COMPLETE 게이트를 통과하지 않게). test_*.py 는 entry 후보에서 제외하고 집계.
    """
    real = [p for p in code_paths if not p.name.lower().startswith("test_")]
    if not real:
        return True
    total = 0
    for p in real:
        try:
            total += p.stat().st_size
        except OSError:  # noqa: PERF203 — 파일 부재는 degenerate 신호
            continue
    if total < _MIN_GUI_CODE_BYTES:
        return True
    if platform_intent == "web":
        names = {p.name.lower() for p in code_paths}
        if "index.html" not in names and "package.json" not in names:
            return True
    return False


# v13 Phase 6.E P10a(3) — web 빌드 필수 manifest 보장 (salvage → synthesize, fail-loud)
_REQUIRED_WEB_MANIFESTS: tuple[str, ...] = ("package.json", "tsconfig.json")
# bare module import (상대/절대 경로 아님) — import X from 'pkg' / import('pkg') / from 'pkg'
_BARE_IMPORT_RE = re.compile(
    r"""(?:from|import)\s+(?:[^'"]*?\s+from\s+)?['"]([^'".][^'"]*)['"]"""
)


def _find_manifest_block(markdown: str, manifest_name: str) -> Optional[str]:
    """fence 언어 무관하게 ``// file: <manifest>`` 헤더 블록 본문을 찾아 반환 (salvage).

    P10a(1) 이 jsonc/json5 를 허용하지만, 미상장 fence(예: ``jsonc5`` 오타)·헤더만 다른
    경우까지 커버하기 위한 fence-agnostic 백업. 헤더 줄은 제거하고 본문만 반환.
    """
    pattern = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*[^\n]*\n(.*?)\n[ \t]*```", re.DOTALL)
    for block in pattern.findall(markdown or ""):
        first = block.splitlines()[0] if block.strip() else ""
        h = _FILE_HEADER_RE.match(first)
        if h and Path(h.group(1)).name.lower() == manifest_name.lower():
            return block.split("\n", 1)[1] if "\n" in block else ""
    return None


def _synthesize_package_json(code_paths: list[Path]) -> str:
    """code_paths 의 .ts/.js bare import 에서 deps 를 추론해 최소 package.json 합성 (최후수단)."""
    deps: set[str] = set()
    for p in code_paths:
        if p.suffix.lower() not in (".ts", ".tsx", ".js", ".jsx"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for spec in _BARE_IMPORT_RE.findall(text):
            if spec.startswith("@"):  # scoped: @scope/name
                pkg = "/".join(spec.split("/")[:2])
            else:  # subpath import (three/examples/...) → 최상위 패키지명
                pkg = spec.split("/")[0]
            if pkg:
                deps.add(pkg)
    dep_obj = {d: "*" for d in sorted(deps) if d not in ("typescript", "vite")}
    obj = {
        "name": "app",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "scripts": {"dev": "vite", "build": "tsc && vite build", "preview": "vite preview"},
        "dependencies": dep_obj,
        "devDependencies": {"typescript": "*", "vite": "*"},
    }
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _ensure_web_manifests(
    gui_code_output: str, code_dir: Path, code_paths: list[Path]
) -> list[Path]:
    """web 빌드 필수 manifest 를 code_dir 에 보장 (P10a(3)). 반환: 새로 추가된 Path 목록.

    동작 (web 프로젝트일 때만): ① salvage — 미저장 manifest 를 gui_code_output 의 ``// file:``
    블록(fence 무관)에서 건져 jsonc→strict 정규화 후 기록. ② synthesize — package.json 이
    그래도 없으면 .ts import 추론으로 최소본 합성. 둘 다 ``13c_manifest_recovery.txt`` 로
    fail-loud 기록. 비-web(데스크탑/.py) 이면 no-op (회귀 0).
    """
    saved_web = [p for p in code_paths if p.suffix.lower() in _WEB_FILE_EXTS]
    if not saved_web:  # web 산출 아님 → 보장 대상 아님 (데스크탑/CLI 불변)
        return []
    saved_names = {p.name.lower() for p in code_paths}
    added: list[Path] = []
    notes: list[str] = []
    # ① salvage
    for manifest in _REQUIRED_WEB_MANIFESTS:
        if manifest in saved_names:
            continue
        body = _find_manifest_block(gui_code_output, manifest)
        if body is None:
            continue
        content = _normalize_jsonc_to_json(body)
        try:
            json.loads(content)
        except Exception:  # noqa: BLE001 — 유효 JSON 아니면 salvage 보류 (synthesize 로)
            continue
        fp = code_dir / manifest
        fp.write_text(content, encoding="utf-8")
        added.append(fp)
        saved_names.add(manifest)
        notes.append(f"salvaged {manifest} (// file: 블록에서 복구 + jsonc→strict 정규화)")
    # ② synthesize package.json (최후수단)
    if "package.json" not in saved_names:
        fp = code_dir / "package.json"
        fp.write_text(_synthesize_package_json(code_paths + added), encoding="utf-8")
        added.append(fp)
        notes.append("SYNTHESIZED package.json (import 추론 최소본 — 버전 best-effort, 검증 요망)")
    if notes:
        (code_dir.parent / "13c_manifest_recovery.txt").write_text(
            "\n".join(notes), encoding="utf-8"
        )
    return added


# PR #66 — Update Checker 실 통합 (방어선 4 패턴 재사용)
_UPDATER_AUTOINJECT_MARKER = "# Auto-injected by Nexus Alpha PR #66 — Update Checker integration"
_UPDATER_AUTOINJECT_SNIPPET = (
    "\n\n" + _UPDATER_AUTOINJECT_MARKER + "\n"
    "# updater.py 가 같은 디렉터리에 있으면 import + start() 호출 시도.\n"
    "# silent failure (보안 7원칙 — 업데이트 체크 실패는 앱 동작과 독립).\n"
    "try:\n"
    "    import updater  # type: ignore[import-not-found]\n"
    "    if hasattr(updater, 'start'):\n"
    "        updater.start()\n"
    "except Exception:  # noqa: BLE001 — silent\n"
    "    pass\n"
)


def _ensure_updater_import_in_entry(code_dir: Path, extracted: list[Path]) -> list[Path]:
    """``code_dir`` 의 entry .py 파일에 ``import updater`` + ``updater.start()``
    호출 라인을 결정형으로 자동 삽입 (PR #66 — Update Checker 실 통합).

    배경:
        Update Checker 가 ``code/updater.py`` 를 산출하더라도 entry (calculator.py
        등) 가 그것을 *import* 하지 않으면 .exe 안에 포함은 되지만 실제 호출은 안 됨.
        GUI Code Generator backstory 에 LLM 지시로 처리하면 PR #61 fence 마커 회귀
        와 같은 비결정적 회귀 위험.

    처방 (방어선 4 패턴):
        deterministic 후처리. ``updater.py`` 가 ``extracted`` 에 있으면, 같은
        디렉터리의 *entry candidate* 파일들에 try/import 스니펫을 *파일 끝* 에
        추가. 이미 마커가 있으면 skip (idempotent). ``test_*.py`` / ``updater.py``
        는 후보에서 제외.

    Args:
        code_dir: ``code/`` 디렉터리 경로.
        extracted: ``_extract_code_blocks`` 가 반환한 추출 파일 목록.

    Returns:
        실제로 수정된 entry 파일 목록 (변경 없으면 빈 리스트).
    """
    if not any(p.name == "updater.py" for p in extracted):
        return []  # updater.py 미산출 → skip
    entry_candidates = [
        p for p in code_dir.glob("*.py")
        if p.name != "updater.py" and not p.name.startswith("test_")
    ]
    modified: list[Path] = []
    for entry in entry_candidates:
        content = entry.read_text(encoding="utf-8")
        if _UPDATER_AUTOINJECT_MARKER in content:
            continue  # 이미 주입됨 — idempotent
        entry.write_text(content + _UPDATER_AUTOINJECT_SNIPPET, encoding="utf-8")
        modified.append(entry)
    return modified


def _integrate_update_checker(workflow_dir: Path, update_module_spec: str) -> list[Path]:
    """``release_result.update_module_spec`` 의 ```python``` 블록을 ``code/`` 로
    추출하고, 산출 entry 파일들에 자동 import 라인을 삽입 (PR #66).

    Returns:
        새로 생성된 ``code/updater.py`` (있으면) + 수정된 entry 파일 목록.
        ``update_module_spec`` 이 비거나 추출 실패 시 빈 리스트.
    """
    if not update_module_spec:
        return []
    code_dir = workflow_dir / "code"
    extracted = _extract_code_blocks(update_module_spec, code_dir)
    if not extracted:
        return []
    modified = _ensure_updater_import_in_entry(code_dir, extracted)
    return extracted + modified


_GUI_FORM_FACTORS = ("single_window", "multi_window", "wizard", "dashboard")


def _parse_ui_ux_path(ui_ux_markdown: str) -> str:
    """UI/UX Analyst 산출 마크다운에서 `need_gui` 또는 `form_factor` 를 파싱.

    파싱 우선순위:
        1. 마지막 `Final Answer:` 줄의 `need_gui=<yes|no|true|false>`
        2. 같은 줄의 `form_factor=<cli|single_window|multi_window|wizard|dashboard>`
        3. 본문 YAML 의 `need_gui:` / `form_factor:` (같은 규칙)
        4. 아무 신호도 없으면 `cli` 로 안전 fallback — 비싼 GUI 사슬 회피

    E2E 이슈 (2026-04-21) 대응:
        초기 구현은 `need_gui=yes/no` 만 인식해 LLM 이 Korean/true/false 변형을
        쓰거나 need_gui 줄을 생략하면 즉시 cli fallback → GUI 분기 미실행 문제.
        해결: (a) true/false 변형 수용, (b) form_factor 가 GUI 계열이면 GUI 로
        간주 (need_gui 누락 방어), (c) 본문·Final Answer 모두 동일 규칙 적용.

    Returns:
        "gui" | "cli"
    """
    text = (ui_ux_markdown or "").lower()

    def _match_need_gui(segment: str) -> Optional[str]:
        """segment 에서 need_gui 시그널 추출. None 이면 신호 없음."""
        m = re.search(r"need_gui\s*[:=]\s*([a-z]+)", segment)
        if not m:
            return None
        v = m.group(1)
        if v in ("yes", "true"):
            return "gui"
        if v in ("no", "false"):
            return "cli"
        return None

    def _match_form_factor(segment: str) -> Optional[str]:
        """segment 에서 form_factor 시그널 추출. CLI/GUI 판정 또는 None."""
        m = re.search(r"form_factor\s*[:=]\s*([a-z_]+)", segment)
        if not m:
            return None
        v = m.group(1)
        if v in _GUI_FORM_FACTORS:
            return "gui"
        if v == "cli":
            return "cli"
        return None

    # 1) Final Answer 줄 — need_gui 우선, 그 다음 form_factor
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("final answer"):
            continue
        verdict = _match_need_gui(s) or _match_form_factor(s)
        if verdict is not None:
            return verdict

    # 2) 본문 YAML — need_gui 우선, 그 다음 form_factor
    body_verdict = _match_need_gui(text) or _match_form_factor(text)
    if body_verdict is not None:
        return body_verdict

    return "cli"  # 모호 시 안전한 기본 — 비싼 GUI 사슬 회피


# ---------------------------------------------------------------------------
# 공통 Task 빌더 (CTO + Analyst — 두 경로 모두 공유)
# ---------------------------------------------------------------------------
def _build_cto_task(user_request: str, cto, ui_spec_context: Optional[Task] = None) -> Task:
    """CTO 전략 Task. ui_spec_context 가 있으면 UI/UX 산출을 컨텍스트로 받음."""
    base_desc = (
        f"[사용자 요청]\n{user_request}\n\n"
        "위 요청을 분석하여 **기술 스택 / 구현 접근 / 리스크 / 권장 작업 순서** "
        "네 섹션으로 된 전략 문서를 한국어로 작성하세요. 엔지니어가 즉시 착수할 수 "
        "있을 만큼 구체적이어야 하며, 요구사항이 모호한 부분이 있다면 먼저 "
        "명확화 질문을 제시해 주세요."
    )
    if ui_spec_context is not None:
        base_desc += (
            "\n\n참고: UI/UX Analyst 가 별도로 산출한 ui_spec(form_factor, "
            "complexity, 5질문 답)이 이전 컨텍스트에 포함되어 있습니다. 그 결정을 "
            "전제로 기술 스택·접근을 선택하세요 (특히 GUI/CLI 형태)."
        )
    context = [ui_spec_context] if ui_spec_context is not None else None
    return Task(
        description=base_desc,
        expected_output=(
            "기술 스택 / 구현 접근 / 리스크 / 권장 순서 네 섹션의 한국어 전략 문서"
        ),
        agent=cto,
        context=context,
    )


def _build_analyst_task(analyst, cto_task: Task) -> Task:
    """Data Analyst 분석 지시서 Task — CTO 전략을 컨텍스트로."""
    return Task(
        description=(
            "CTO의 전략 문서(이전 컨텍스트)를 반영하여 입력 데이터에 대한 분석 "
            "지시서를 작성하세요. 다섯 섹션 구조:\n"
            "  1) 데이터 품질 체크포인트\n"
            "  2) 핵심 지표 5개 (이름·계산식·단위·의사결정 질문·표시 위치)\n"
            "  3) 추천 차트 3종 (유형·축 구성·메시지·디자인 주의사항)\n"
            "  4) 이상치 탐지 기준 (통계 기준 + 비즈니스 임계값)\n"
            "  5) 분석가 코멘트 (경영진 요약 강조 포인트 2~3개)\n\n"
            "엔지니어가 바로 코드로 옮길 수 있도록 지표·차트·이상치 기준을 모두 "
            "구체적으로 명시해 주세요."
        ),
        expected_output=(
            "데이터 품질 / 지표 5개 / 차트 3종 / 이상치 / 분석가 코멘트 다섯 섹션의 "
            "한국어 분석 지시서"
        ),
        agent=analyst,
        context=[cto_task],
    )


def _build_engineer_task(engineer, cto_task: Task, analyst_task: Task) -> Task:
    """Python Engineer 구현 Task (기존 4-agent 흐름).

    도메인 중립 — 데이터 분석·단순 CLI·유틸 스크립트 등 무엇이든 *사용자 요청에
    실제로 맞는* Python 구현을 생성하도록 지시한다. 분석 지시서가 데이터 품질/
    지표/차트 구조를 다루더라도, **요청이 데이터 분석이 아니면** Engineer 는
    분석 지시서를 무시하고 요청에 충실한 구현을 작성해야 한다.
    """
    return Task(
        description=(
            "CTO의 전략 문서(이전 컨텍스트)를 기반으로 **사용자 요청을 실제로 "
            "만족하는 바로 실행 가능한 Python 구현 산출물**을 작성하세요. Data "
            "Analyst 의 분석 지시서는 참고용 — 요청이 *데이터 분석이 아닌* "
            "경우(예: 계산기, 에디터, 유틸) 분석 지시서의 지표/차트 틀에 끼워 "
            "맞추지 말고 요청에 충실한 구현을 선택하세요.\n\n"
            "요구 사항:\n"
            "  - **단독 실행 가능 (self-contained)**: 엔트리 파일은 **반드시** "
            "    `python <entry>.py` 만으로 실행 가능해야 합니다. 추가 설치나 "
            "    `python -m <pkg>` 강제는 금지. (복잡하면 `python -m <pkg>` 도 "
            "    같이 가능하게 — 하지만 단일 파일 실행이 *기본 경로*.)\n"
            "  - **import 규칙**: 엔트리에서 `from .xxx import ...` 같은 **상대 "
            "    import 금지**. 같은 디렉터리 파일은 `from xxx import ...` (절대 "
            "    import) 또는 `import xxx` 로 참조. `sys.path` 조작 금지.\n"
            "  - **파일 분리 원칙**: 복잡도에 맞게 — 단순 요청이면 단일 파일, "
            "    복잡하면 역할 단위로 나누되 모든 파일이 한 디렉터리에 있어 "
            "    평면 import 가 가능한 구조로. 패키지 레이아웃 (`pkg/__init__.py`)이 "
            "    꼭 필요하면 `python -m pkg` 경로도 같이 제공.\n"
            "  - 모든 공개 함수에 타입 힌트와 docstring\n"
            "  - 핵심 로직에 최소 2~3건의 pytest 단위 테스트 (실제 로직 기준 — "
            "    계산기라면 계산 함수, 에디터라면 텍스트 처리)\n"
            "  - 경계 지점(I/O, CLI, GUI 이벤트)에만 예외 처리, 내부 함수는 "
            "    계약 신뢰\n\n"
            "산출 규약:\n"
            "  - 각 파일은 ```python 코드 블록으로 감싸고 첫 줄에 `# file: "
            "    <상대경로>` 헤더 주석 포함\n"
            "  - 마지막 섹션에 **설치·실행 방법** — 최소 한 줄의 `python "
            "    <entry>.py` 예시 명시"
        ),
        expected_output=(
            "요청에 충실한, 단독 실행 가능한 (python <entry>.py) Python 코드 세트와 "
            "pytest 테스트, 설치·실행 가이드를 포함한 완전한 구현 산출물. 상대 "
            "import 또는 sys.path 조작 없이 실행 가능해야 함."
        ),
        agent=engineer,
        context=[cto_task, analyst_task],
    )


def _build_pytest_author_task(
    pytest_author,
    code_task: Task,
    *,
    shared_kickoff_decisions=None,
    prior_agent_roles: Optional[Sequence[str]] = None,
) -> Task:
    """Pytest Author Task — code_task (Engineer 또는 GUI Code Generator) 의 산출
    코드를 컨텍스트로 받아 같은 디렉터리 배치 가능한 ``test_*.py`` 작성.

    PR #58 추가, PR #59 schema, PR #61 부하/엣지 시나리오 강제:
        - output_pydantic=PytestSuiteOutput 으로 schema 강제 (방어선 2, PR #59)
        - description 에 본문 분량 임계 (총 1200자, 코드 60줄, 10 def test_*)
          명시 + 4 카테고리 (happy/edge/load/error) 분포 강제 (PR #61)
        - pytest 환경에선 output_pydantic 미적용 (FakeProvider 호환)
        - 의도: functional/robustness executor 가 GUI 산출물에서 SKIPPED 되므로
          그 *의미* 를 pytest 안에 흡수 → code_qa 안에 부하/엣지 검증 포함

    PR #138 Phase 1 full (2026-05-15, 본인 비전 통찰 6):
        kickoff context + cross-agent consistency directive 를 description 에
        append. Pytest 가 코드 산출과 *다른 가정* (예: 환율 API vs 정적 dict) 으로
        테스트를 짜면 환율 변환기 사례 같은 비일관성이 묻혀 통과 — 본 directive
        가 그 사각지대 차단.
    """
    import sys

    from ._common import format_kickoff_context_directive

    base_description = (
        "이전 컨텍스트의 산출 코드 (`<entry>.py`) 를 읽고 같은 디렉터리에 "
        "배치 가능한 ``test_<entry>.py`` 를 백스토리에 명시된 3단 구조"
        "(테스트 전략 / 실 코드 / 검증 의도+한계)로 작성하세요.\n\n"
        "## 분량 임계 (PR #61 강화 + PR #64 fence 마커) 🚨\n"
        "  - 전체 출력 **최소 1200자** — Final Answer 한 줄만 출력하면 task 실패로 간주\n"
        "  - ``test_code_block`` 안에 **```python\\n 으로 시작하고 \\n``` 으로 "
        "    닫는 fence 마커** 반드시 포함 [PR #64] — fence 누락 시 "
        "    ``_extract_code_blocks`` 매치 실패로 ``test_*.py`` 추출 안 됨 "
        "    (10차 E2E 9차 회귀 사례). schema ``_ensure_python_fence`` 가 "
        "    자동 보정하지만 LLM 응답 자체에 포함이 1순위\n"
        "  - 코드 블록 첫 줄 ``# file: test_<entry>.py`` 헤더\n"
        "  - 코드 블록 안에 ``def test_*`` **최소 10개** (4 카테고리 분포)\n\n"
        "## 4 카테고리 분포 강제 (PR #61) — functional/robustness 의미 흡수\n"
        "GUI 산출물의 경우 functional/robustness executor 가 SKIPPED 되므로, "
        "본 pytest 가 그 *의미* 를 모두 흡수해야 합니다:\n"
        "  a) **Happy path** ≥ 3개: 기본 사칙연산, 결과 누적 등\n"
        "  b) **Edge cases** ≥ 4개 (functional 흡수): 0, 음수, 매우 큰 수 "
        "(10**15+), 빈 입력, 유니코드 (한글/이모지), 비-수치 입력\n"
        "  c) **Robustness/load** ≥ 3개 (robustness 흡수): 1000회 연속 호출 "
        "(`for _ in range(1000): ...`), 긴 표현식 chain (10+ 연산자), "
        "rapid_repeat (인스턴스 5회 재생성 후 idempotency)\n"
        "  d) **Error handling** ≥ 1개: ZeroDivisionError, OverflowError, "
        "ValueError 등 `with pytest.raises(...):` 패턴\n\n"
        "## 절대 규칙\n"
        "  1. ``pytest <code_dir>`` 만으로 standalone 실행 가능\n"
        "  2. GUI 윈도우 절대 미표시 (tkinter/customtkinter/PyQt 등은 "
        "     ``monkeypatch`` 로 ``__init__`` / ``mainloop`` no-op)\n"
        "  3. import 경로 보정: 테스트 상단에 ``sys.path.insert(0, str("
        "Path(__file__).parent))``\n"
        "  4. 결정론적 assertion (예상값을 코드에 박아넣음 — truthy-only 금지)\n"
        "  5. 함수명 prefix 권장: ``test_happy_*`` / ``test_edge_*`` / "
        "``test_load_*`` / ``test_error_*``\n\n"
        "## output_pydantic 강제\n"
        "본 task 는 ``PytestSuiteOutput`` schema 로 4개 필드 (summary / "
        "test_strategy / test_code_block / intent_and_limits) 모두 채워져야 "
        "완료됩니다. 누락 시 CrewAI 가 재호출 → 그래도 실패 시 PR #55 "
        "capture-before-rescue 로 raw 보존.\n"
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions,
        prior_agent_roles=list(prior_agent_roles or ["Engineer (코드 산출자)"]),
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "PytestSuiteOutput schema 4 필드 모두 채워진 마크다운 (전체 1200자+, "
            "```python``` 블록 1개+, def test_* 10개+ — happy/edge/load/error 4 "
            "카테고리 분포). 마지막 줄 `Final Answer: test_<entry>.py N scenarios`."
        ),
        agent=pytest_author,
        context=[code_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = PytestSuiteOutput
    return Task(**kwargs)


def _build_qa_task(
    reviewer,
    code_task: Task,
    *,
    shared_kickoff_decisions=None,
    prior_agent_roles: Optional[Sequence[str]] = None,
) -> Task:
    """Code Reviewer Task — code_task (Engineer 또는 GUI Code Generator) 컨텍스트로.

    PR #138 Phase 1 full (2026-05-15, 본인 비전 통찰 6):
        kickoff context + cross-agent consistency directive 추가. Reviewer 가
        *킥오프 합의된 가정* 과 *코드 산출* 의 일치 여부를 명시적으로 점검하도록
        강제 — 환율 변환기 사례의 "API 가정 vs 정적 dict 구현" 같은 불일치가
        Reviewer 의 5 점검 항목에 잡히지 않고 통과한 회귀 차단.
    """
    import sys

    from ._common import format_kickoff_context_directive

    base_description = (
        "이전 컨텍스트의 코드 산출물을 백스토리에 명시된 다섯 가지 정적 점검 "
        "항목 — 타입 힌트 / docstring / pytest 실행 가능성 / 경계 예외 처리 / "
        "모듈 분리 — 으로 점검하고, **5단 구조(종합 판정 / 항목별 결과표 / "
        "발견된 이슈 / 권장 보정 / 미검토 영역)** 의 한국어 마크다운 리뷰 "
        "보고서를 작성하세요.\n\n"
        "유의 사항:\n"
        "  - 코드를 실행하지 않습니다(정적 점검 전담).\n"
        "  - 발견 사항은 (파일:라인 — 인용 — 원칙 — 보정안) 형식으로 적습니다.\n"
        "  - **킥오프 합의 사항 일치 점검 필수** (PR #138 Phase 1 full):\n"
        "    아래 ``킥오프 회의 합의 사항`` 섹션에 명시된 공유 가정 (예: 외부 "
        "    API 호출 / 데이터 저장 방식) 과 코드 산출이 일치하는지 명시적으로 "
        "    검증하고, 불일치 발견 시 ``NEEDS_REVISION`` 으로 차단. 환율 변환기 "
        "    사례 (API 가정 vs 정적 dict 구현) 재발 차단.\n"
        "  - **NEEDS_REVISION 이면 반드시 실행가능 본문을 채웁니다 (P24):** §3 발견된 이슈에 "
        "    최소 1개 — `[BLOCKER|MAJOR|MINOR] 파일:라인 — 인용 + 원칙 + 보정안` 형식의 *구체* "
        "    항목, §4 권장 보정에 대응 보정안. '<본문>'·'...'·'해당 없음' 같은 플레이스홀더만 "
        "    있는 NEEDS_REVISION 은 *무효* (후속이 무엇을 고칠지 알 수 없음).\n"
        "  - 마지막 줄은 반드시 `Final Answer:` 로 시작하는 한 줄 종합 "
        "    판정(APPROVED / NEEDS_REVISION)이어야 합니다."
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions,
        prior_agent_roles=list(prior_agent_roles or ["Engineer (코드 산출자)"]),
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "5단 구조의 한국어 리뷰 보고서. 마지막 줄에 `Final Answer:`로 시작하는 "
            "종합 판정(APPROVED 또는 NEEDS_REVISION) 포함. NEEDS_REVISION 이면 §3 발견된 이슈·"
            "§4 권장 보정에 최소 1개 구체 수정 항목(파일:라인 — 증상 — 원인 — 조치)을 반드시 포함 "
            "(빈/플레이스홀더 본문 금지)."
        ),
        agent=reviewer,
        context=[code_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = CodeReviewOutput
    return Task(**kwargs)


# ---------------------------------------------------------------------------
# Phase 4 GUI 분기 Task 빌더
# ---------------------------------------------------------------------------
def _build_uiux_task(user_request: str, ui_ux) -> Task:
    """UI/UX Analyst Task — Phase 4 활성 시 첫 단계."""
    import sys

    kwargs: dict = dict(
        description=(
            f"[사용자 요청]\n{user_request}\n\n"
            "위 요청을 받아 백스토리에 명시된 2단 구조(YAML ui_spec + 분석가 노트)로 "
            "한국어 UI/UX 분석을 작성하세요. 5가지 질문(windows / data_unit / state / "
            "learning_curve / accessibility) 모두에 답하세요. **첫 1순위 결정은 "
            "need_gui (yes/no)** 입니다."
        ),
        expected_output=(
            "YAML ui_spec(need_gui/form_factor/complexity/questions/assumptions/"
            "recommended_framework_hint) + 분석가 노트. 마지막 줄 `Final Answer: "
            "form_factor=..., complexity=..., need_gui=...`."
        ),
        agent=ui_ux,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = UIUXSpecOutput
    return Task(**kwargs)


def _build_gui_designer_task(designer, uiux_task: Task) -> Task:
    """GUI Designer Task — UI/UX 산출 ui_spec 을 컨텍스트로."""
    import sys

    kwargs: dict = dict(
        description=(
            "이전 컨텍스트의 UI/UX ui_spec 을 받아, 백스토리에 명시된 4단 구조"
            "(와이어프레임 + 위젯 트리 + 인터랙션 흐름 + 디자이너 노트)로 한국어 "
            "GUI 설계서를 작성하세요. 색상·폰트는 다루지 마세요 (Theme Designer 책임)."
        ),
        expected_output=(
            "와이어프레임(ASCII) + 위젯 트리(yaml) + 인터랙션 흐름 + 디자이너 노트. "
            "마지막 줄 `Final Answer: GUI design — N개 윈도우, M개 위젯`."
        ),
        agent=designer,
        context=[uiux_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = GUIDesignOutput
    return Task(**kwargs)


def _build_theme_task(theme, uiux_task: Task, designer_task: Task) -> Task:
    """Theme Designer Task — ui_spec + GUI 설계를 컨텍스트로."""
    import sys

    kwargs: dict = dict(
        description=(
            "이전 컨텍스트의 ui_spec + GUI 설계를 받아, 백스토리에 명시된 3단 구조"
            "(JSON 토큰 + 적용 가이드 + 디자이너 노트)로 한국어 디자인 토큰을 "
            "산출하세요. WCAG AA 대비를 보장하세요."
        ),
        expected_output=(
            "JSON 디자인 토큰(theme_strategy/palette/typography/spacing/radii/"
            "accessibility) + 적용 가이드 + 디자이너 노트. 마지막 줄 `Final Answer: "
            "theme_strategy=..., modes=N개, palette=...`."
        ),
        agent=theme,
        context=[uiux_task, designer_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = ThemeTokensOutput
    return Task(**kwargs)


# ---------------------------------------------------------------------------
# v13 Phase 6.E P3 — GUI 플랫폼 드리프트 즉시 reject + 재생성
#   배경: 동일 web 안건인데 GUI Code Generator 가 런마다 PyQt 데스크탑으로 확률적
#         드리프트 (P7 verdict: web 4/5 → 1/5). 기존 P1 PLATFORM_DRIFT 는 judge 단계
#         (post-iteration) 라 IMPROVE 1라운드 소모. P3 는 gui_code 생성 *직후* 같은
#         iteration 안에서 detect_desktop_markers 로 즉시 reject → 코더 task 만 N회
#         hardened-directive 재생성 (iter 카운터 불변). 소진 시 기존 judge 백스톱.
#   회귀 0: platform_intent != "web" 이면 전부 no-op.
# ---------------------------------------------------------------------------
_P3_MAX_DRIFT_RETRIES = 2


def _build_web_platform_directive() -> str:
    """web intent GUI 생성 directive (PREVENTIVE 첫 생성 + CURATIVE 재생성 공통).

    데스크탑 프레임워크 금지 + 완전 web 프로젝트(index.html+package.json+src/) 강제 +
    "사용자가 PyQt 명시" / "schema 가 python 만 허용" 류 *날조 근거 거부*.
    """
    return (
        "\n\n## 🚫 플랫폼 제약 (P3, 최우선 — 데스크탑 기본값 무시)\n"
        "타겟 플랫폼 = **web / 브라우저** 로 *결정론적으로* 분류됐습니다. "
        "**반드시 Three.js + WebGL + HTML/JS/CSS (TypeScript + web-ifc-three + Vite 권장) "
        "로 *완전한 web 프로젝트* 를 산출**하세요:\n"
        "  - `index.html` (entry) + `package.json` (의존성 manifest) + `src/` 소스 "
        "(main.ts / viewer.ts 등) 를 **모두 포함**.\n"
        "  - 각 파일은 fence 코드 블록 + 첫 줄 `# file:` / `// file:` / `<!-- file: -->` 헤더.\n"
        "**PyQt / PySide / Tkinter / QApplication 등 데스크탑 GUI 프레임워크는 절대 금지** "
        "(.exe 데스크탑 셸 · `python app.py` 형태 entry 포함).\n"
        "근거 날조 거부: **'사용자가 PyQt/데스크탑을 지정·명시·요청했다'** 또는 "
        "**'출력 schema 가 python 코드만 허용한다'** 는 *거짓 근거* 입니다 — web 의도는 "
        "요청에서 결정론적으로 분류됐고, 산출 schema 의 code_blocks 는 *자유 형식* 이라 "
        "TypeScript/HTML/CSS 를 그대로 담을 수 있습니다. web 타겟에서 데스크탑 선택의 "
        "정당한 근거는 존재하지 않습니다."
        "\n\n## 📦 배포성 계약 (P25, 필수 — 비개발자 원클릭 실행)\n"
        "산출물은 **문서화된 *단일* 프로덕션 명령으로 비개발자가 그대로 실행**할 수 있어야 합니다 "
        "(빌드 후 배포성 게이트가 *프로덕션 경로* 로 검증 — dev 서버 아님):\n"
        "  - **서버가 빌드된 프론트(`dist/`)를 *정적 서빙* + SPA fallback** 으로 루트 `/` 에서 앱을 "
        "응답해야 합니다. 예(express): `app.use(express.static(path.join(dir,'dist')))` + (API 라우트 *뒤*) "
        "`app.use((q,r)=>r.sendFile(path.join(dir,'dist','index.html')))`. (Express 5 는 `app.get('*', …)` 가 "
        "에러이므로 *미들웨어형 fallback* 사용.) **서버가 `/api` 만 제공하고 dist 를 서빙하지 않으면 "
        "`node server.js` 후 루트가 'Cannot GET /' 가 되어 FAIL.**\n"
        "  - **단일 명령**: `package.json` 의 `\"start\"`(예: `\"start\": \"node server.js\"`) *하나* 로 "
        "프론트+API 가 **한 포트**에서 떠야 합니다. `npm run dev` / `concurrently` / `vite dev` 등 "
        "**dev 전용 도구 의존 금지** (dev 서버는 배포 산출물이 아님).\n"
        "  - **`README.md`** 에 그 *단일 실행 명령 1줄*(`npm start`)을 명시하세요.\n"
        "  - 빌드는 `npm run build → dist/` 그대로 두고, *프로덕션 서버가 그 dist 를 서빙* 하게 만드세요."
    )


def _build_drift_regen_directive(markers: list) -> str:
    """CURATIVE — 방금 산출된 gui_code 에서 데스크탑 마커 감지 시 재생성 directive."""
    preview = ", ".join(str(m) for m in list(markers)[:4])
    return (
        "\n\n## 🚨 재생성 directive (P3) — 플랫폼 드리프트 차단\n"
        f"방금 산출한 코드에서 데스크탑 GUI 마커({preview}) 가 감지됐습니다 — "
        "web 타겟 위반입니다. **직전 산출의 구조·식별자를 유지하지 말고 백지에서 "
        "Three.js + WebGL + HTML/JS/CSS 기반 web 프로젝트로 재작성**하세요."
        + _build_web_platform_directive()
    )


def _should_regenerate_for_drift(platform_intent: str, code_text: str) -> bool:
    """CURATIVE 재생성 트리거 판정 — web 의도 ∧ 데스크탑 마커 존재 시 True.

    desktop/unspecified 또는 마커 없으면 False (회귀 0). detect_desktop_markers 는
    지연 import (순환 import 회피) — P1 과 동일 마커 집합 재사용 (새 ad-hoc substring 금지).
    """
    if platform_intent != "web":
        return False
    from src.agents.c_level.convergence_judge import (  # noqa: PLC0415
        detect_desktop_markers,
    )

    return bool(detect_desktop_markers(code_text))


def _regenerate_until_clean(
    gui_code_output: str,
    *,
    platform_intent: str,
    regen_fn,
    max_retries: int = _P3_MAX_DRIFT_RETRIES,
) -> tuple:
    """web 의도 + 데스크탑 마커면 ``regen_fn`` 으로 최대 ``max_retries`` 재생성.

    Args:
        gui_code_output: 방금 생성된 gui_code 텍스트.
        platform_intent: "web" 일 때만 동작 (그 외 즉시 (입력, 0) 반환 — 회귀 0).
        regen_fn: ``(markers: list, attempt: int) -> str`` — 재생성된 코드 텍스트 반환.
            production 은 단독 코더 Crew kickoff, 테스트는 fake.
        max_retries: 같은 iteration 안 재생성 상한 (기본 2). 소진 시 마지막 산출 반환.

    Returns:
        (최종 gui_code_output, 실제 재생성 횟수). 예외 없음 (소진 시 fall-through →
        기존 judge PLATFORM_DRIFT 백스톱이 처리). iteration 카운터는 본 함수가
        만지지 않음 (카운터는 상위 ``_node_run_chain`` 소유 — 본 재생성은 단일
        iteration 내부에 중첩되어 loop-back 엣지를 넘지 않음).
    """
    from src.agents.c_level.convergence_judge import (  # noqa: PLC0415
        detect_desktop_markers,
    )

    if platform_intent != "web":
        return gui_code_output, 0
    attempts = 0
    for _ in range(max_retries):
        markers = detect_desktop_markers(gui_code_output)
        if not markers:
            break
        attempts += 1
        new_output = regen_fn(markers, attempts)
        if new_output:
            gui_code_output = new_output
    return gui_code_output, attempts


def _maybe_regenerate_on_platform_drift(
    gui_code_output: str,
    *,
    code_gen_task: Task,
    coder,
    context_tasks: list,
    platform_intent: str,
    verbose: bool,
    max_retries: int = _P3_MAX_DRIFT_RETRIES,
) -> str:
    """Production CURATIVE 래퍼 — pytest 환경에선 no-op (실 Crew 미호출, P3-T7).

    ``retry_short_tasks_in_chain`` 과 동일하게 pytest 중엔 즉시 입력 반환 (FakeProvider
    경로 보호). production 에서만 단독 코더 Crew 로 재생성.
    """
    import sys

    if platform_intent != "web" or "pytest" in sys.modules:
        return gui_code_output

    def _regen(markers, _attempt: int) -> str:
        regen_task = Task(
            description=code_gen_task.description + _build_drift_regen_directive(markers),
            expected_output=code_gen_task.expected_output,
            agent=coder,
            context=context_tasks,
        )
        Crew(
            agents=[coder],
            tasks=[regen_task],
            process=Process.sequential,
            verbose=verbose,
        ).kickoff()
        return _task_output_text(regen_task)

    new_output, _attempts = _regenerate_until_clean(
        gui_code_output,
        platform_intent=platform_intent,
        regen_fn=_regen,
        max_retries=max_retries,
    )
    return new_output


def _build_degenerate_regen_directive() -> str:
    """v13 P16 (수정1b) — 빈/단축 코드(degenerate) 재생성 교정 지시.

    HARNESS_AUDIT: 단축 가드가 to_markdown() 총길이를 재 산문만 길고 코드가 빈 산출을
    통과시킴 → 추출 코드 0 → degenerate. 본 directive 는 "설명 말고 *실제 코드*를 fenced
    block 으로 내라" 를 명시해 산문-only 회귀를 차단.
    """
    return (
        "\n\n## 🚨 재생성 directive (P16) — 빈 코드(degenerate) 차단\n"
        "이전 응답은 설명·산문만 있고 *사용 가능한 실제 코드가 없었습니다* (추출된 코드 0). "
        "각 파일의 **전체 내용을 fenced 코드 블록**(```lang + 첫 줄 `# file:` / `// file:` / "
        "`<!-- file: -->` 헤더) 안에 *실제 코드로* 출력하세요. 설명·요약·계획만 쓰지 말고 "
        "**코드를 내세요.** 최소한 entry 파일을 (web 이면 추가로 package.json · index.html · "
        "src/ 소스를) 실제 내용으로 포함하세요."
    )


def _maybe_regenerate_on_degenerate(
    gui_code_output: str,
    code_paths: list,
    *,
    code_gen_task: Task,
    coder,
    context_tasks: list,
    workflow_dir: Path,
    platform_intent: str,
    verbose: bool,
    max_retries: int = _P3_MAX_DRIFT_RETRIES,
) -> tuple:
    """v13 P16 (수정1b) — degenerate(빈/단축 코드) 산출이면 *우회 이전에* 코더 task 를
    최대 ``max_retries`` 회 '실제 코드 출력' 지시로 재호출 + 재추출. 비-degenerate 가 되면
    채택; 소진 시 마지막(여전히 degenerate)을 반환 → 기존 13d 마커 + P15 best-iteration 폴백.

    P14 감지 + P15 선택은 유지 — 본 함수는 *우회 전에* 원천 재생성을 끼워넣는 것.
    pytest 환경은 no-op (실 Crew 미호출 — FakeProvider 경로 보호, drift 재생성과 동일 관례).

    Returns:
        (gui_code_output, code_paths) — 회복 시 새 산출/추출, 아니면 입력 그대로.
    """
    import sys

    if "pytest" in sys.modules:
        return gui_code_output, code_paths
    if not _is_degenerate_codegen(code_paths, platform_intent):
        return gui_code_output, code_paths  # 정상 산출 — no-op (회귀 0)

    code_dir = workflow_dir / "code"
    for _attempt in range(max_retries):
        regen_task = Task(
            description=code_gen_task.description + _build_degenerate_regen_directive(),
            expected_output=code_gen_task.expected_output,
            agent=coder,
            context=context_tasks,
        )
        Crew(
            agents=[coder],
            tasks=[regen_task],
            process=Process.sequential,
            verbose=verbose,
        ).kickoff()
        new_output = _task_output_text(regen_task)
        if not new_output:
            continue
        # 원 GUI 추출과 동일 파라미터로 재추출 (web 서브트리 보존).
        new_paths = _extract_code_blocks(
            new_output, code_dir, languages=_WEB_CODE_LANGS, preserve_tree=True
        )
        gui_code_output, code_paths = new_output, new_paths
        if not _is_degenerate_codegen(new_paths, platform_intent):
            break  # 회복 — 채택
    return gui_code_output, code_paths


def _build_qa_empty_body_directive() -> str:
    """v13 P24 — NEEDS_REVISION 빈 본문 재생성 교정 지시 (구체 수정 항목 강제)."""
    return (
        "\n\n## 🚨 재생성 directive (P24) — 빈 본문 NEEDS_REVISION 차단\n"
        "이전 응답은 `NEEDS_REVISION` 판정만 있고 *실행가능한 수정 지침이 없었습니다* "
        "(§3 발견된 이슈·§4 권장 보정이 비었거나 플레이스홀더). 후속 오케스트레이션이 *무엇을* "
        "고쳐야 할지 알 수 없습니다. 다음을 *반드시* 채우세요:\n"
        "  - **§3 발견된 이슈**: 최소 1개 — `**[BLOCKER|MAJOR|MINOR]** \\`파일:라인\\` — 인용 + "
        "왜 문제(원칙) + 어떻게 고칠지(조치)` 형식의 *구체* 항목.\n"
        "  - **§4 권장 보정**: §3 의 각 이슈에 대응하는 *실행가능* 보정(우선순위 번호, 가능하면 "
        "코드 스니펫).\n"
        "'<본문>'·'...'·'해당 없음' 같은 플레이스홀더는 금지. APPROVED 라면 그대로 APPROVED 로 내세요."
    )


def _synthesize_qa_fallback_body(original: str) -> str:
    """v13 P24 — 재시도 소진 후에도 빈 본문이면 *비어있지 않은 실행가능* 보강 본문 합성.

    빈 verdict-only 를 다음 iteration(Gap Analyst) 에 *절대 전파하지 않기* 위함. 구체 결함은
    미상이지만 '스펙·킥오프 합의 대비 전면 대조 + 직전 빌드 신호 우선 must-fix' 라는 실행가능
    방향을 제공한다.
    """
    return (
        "NEEDS_REVISION\n\n"
        "## 코드 리뷰 보고서 (⚠️ 자동 보강 — QA 본문 누락 안전망 P24)\n\n"
        "### 1. 종합 판정\n\n"
        "QA 리뷰어가 `NEEDS_REVISION` 을 냈으나 구체 수정 항목 생성에 반복 실패(재시도 소진). "
        "빈 본문을 다음 iteration 에 전파하지 않기 위해 실행가능 지침으로 자동 보강함.\n\n"
        "### 3. 발견된 이슈\n\n"
        "- **[MAJOR]** `(파일 미상)` — QA 가 결함 위치를 특정하지 못함. 코드를 스펙·킥오프 합의"
        "(기술스택/데이터 저장/외부 API 가정)와 *전면 대조*해 불일치를 직접 식별할 것.\n\n"
        "### 4. 권장 보정\n\n"
        "1. 스펙·킥오프 합의 대비 코드의 표현/데이터/통신 계층을 재검토하고 불일치를 수정.\n"
        "2. 직전 빌드의 알려진 신호(빌드 실패·스모크 FAIL·gap 미충족)를 우선 must-fix 로 처리.\n"
        "3. 전체 코드를 fenced 블록으로 빠짐없이 재산출.\n\n"
        "### 5. 미검토 영역\n\n원본 QA 산출(verdict-only) 보존: "
        f"{(original or '').strip()[:200] or '(빈 산출)'}\n"
    )


def _maybe_regenerate_on_qa_empty_body(
    qa_review_task: Any,
    qa_review: str,
    *,
    workflow_dir: Path,
    verbose: bool,
    max_retries: int = 1,
    _regen_fn: Optional[Callable[[Any], str]] = None,
) -> str:
    """v13 P24 — QA verdict=NEEDS_REVISION 인데 *본문이 빈* 경우 안전망.

    진단(ERP 런 151255 = 14B "NEEDS_REVISION" 단독): LLM 이 비결정적으로 본문을 비움(layer ①).
    구조적 차단: ① 빈 본문 감지 → ② reviewer 를 *구체 항목 강제* 지시로 max_retries 회 재호출 →
    ③ 그래도 비면 *비어있지 않은* 보강 본문 합성 + fail-loud 아티팩트. **빈 본문을 다음 iteration
    에 절대 전파하지 않는다.** NEEDS_REVISION 아니면 즉시 입력 반환(회귀 0).

    pytest 는 실 Crew 미호출(degenerate 재생성과 동일 관례). 단위 테스트는 ``_regen_fn``
    (task→새 리뷰 텍스트) 을 주입해 재시도/폴백 루프를 결정론적으로 검증한다(retry_task_if_short
    의 kickoff_fn 주입과 동일 패턴).

    Returns:
        보강/회복된 qa_review (NEEDS_REVISION 인 경우 항상 비어있지 않은 본문 보장).
    """
    import sys

    if not qa_review_body_is_empty(qa_review):
        return qa_review  # APPROVED/정상 본문 — no-op (회귀 0)
    if _regen_fn is None and "pytest" in sys.modules:
        return qa_review  # 프로덕션 전용 (실 Crew). 테스트는 _regen_fn 주입으로 우회.

    for _attempt in range(max_retries):
        try:
            if _regen_fn is not None:
                new_review = _regen_fn(qa_review_task)
            else:
                reviewer = getattr(qa_review_task, "agent", None)
                if reviewer is None:
                    break
                regen_task = Task(
                    description=qa_review_task.description + _build_qa_empty_body_directive(),
                    expected_output=qa_review_task.expected_output,
                    agent=reviewer,
                    context=qa_review_task.context,
                    # 원본과 동일하게 layer ② validator 를 재시도에도 적용 (R6 #4 — output_pydantic 전파)
                    output_pydantic=getattr(qa_review_task, "output_pydantic", None),
                )
                Crew(
                    agents=[reviewer], tasks=[regen_task],
                    process=Process.sequential, verbose=verbose,
                ).kickoff()
                new_review = _task_output_text(regen_task)
        except Exception:  # noqa: BLE001 — 재생성 실패가 메인 흐름 차단 X
            continue
        if new_review and not qa_review_body_is_empty(new_review):
            return new_review  # 회복 — 채택
        if new_review:
            qa_review = new_review  # 여전히 비어도 마지막 시도 보존

    # 소진 — 여전히 빈 본문이면 fail-loud + 비어있지 않은 보강 본문 (전파 차단의 최후 보루).
    try:
        (workflow_dir / "04b_qa_empty_body.txt").write_text(
            "⚠️ P24 — QA NEEDS_REVISION 빈 본문 (재시도 소진). 자동 보강 본문으로 대체.\n\n"
            f"--- 원본 QA 산출 ---\n{qa_review}\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return _synthesize_qa_fallback_body(qa_review)


def _build_product_anchor(user_request: str) -> str:
    """v13 Phase 6.E P14 — 생성 제품의 *최상위 권위 앵커* + 시스템 컨텍스트 격리 directive.

    배경 (P13 런 iter4): 코드 생성기가 사용자 요청("3D BIM 뷰어")이 아니라 시스템(Nexus Alpha)
    자기 자신의 관제 대시보드(에이전트 명단 테이블 등)를 생성. 시스템 내부 컨텍스트가 제품
    생성 프롬프트에 새어들어 사용자 요청의 지배력을 잃은 앵커링 버그. 본 앵커는 사용자 요청을
    프롬프트 최상위 권위로 고정하고, 시스템 내부 정보(에이전트/아키텍처/자체 대시보드)는 제품
    내용이 아님을 명시한다. 빈 요청이면 빈 string (회귀 0).
    """
    req = (user_request or "").strip()
    if not req:
        return ""
    return (
        "## 🎯 [제품 명세 — 최상위 권위 앵커 (P14)]\n"
        "당신이 만들 제품은 아래 *사용자 요청 그 자체* 입니다. 이것이 유일한 진실의 원천이며 "
        "다른 모든 컨텍스트(킥오프/이전 산출/시스템 정보)보다 우선합니다:\n\n"
        f"```\n{req}\n```\n\n"
        "## ⚠️ [컨텍스트 격리 — 시스템 누수 금지 (CRITICAL)]\n"
        "당신을 실행하는 시스템(Nexus Alpha)의 내부 정보는 **생성할 제품의 내용이 절대 아닙니다**:\n"
        "- 내부 부서/에이전트 명단(Requirement Expander · GUI Designer · Theme Designer · "
        "Code Generator · Code Reviewer · Pytest Author · Deploy · Monitor 등), 시스템 "
        "아키텍처, 자체 관제/대시보드/파이프라인 UI 개념, 내부 문서·지식 — 이런 정보가 "
        "컨텍스트에 보여도 **제품에 절대 반영하지 마세요.**\n"
        "- 제품은 'Nexus Alpha 를 위한/관한' 것이 아니라, **위 [제품 명세]의 사용자 요청을 "
        "외부 신규 제품으로** 구현한 것이어야 합니다. ('활성 Agent / 진행 작업 / 성공률 / "
        "파이프라인' 류 시스템 자체 모니터링 대시보드를 만들지 마세요.)\n"
        "- 예: '3D BIM 뷰어: Three.js + BIM, 카메라 회전, 클릭 시 속성, 다크 관제센터' → 산출은 "
        "Three.js 3D 장면 + 다크 테마 + 클릭 가능한 건물 요소(속성 표출) 여야 하며, 에이전트 "
        "모니터링 대시보드가 아닙니다.\n\n"
    )


def _build_gui_code_gen_task(
    coder,
    uiux_task: Task,
    designer_task: Task,
    theme_task: Task,
    *,
    shared_kickoff_decisions=None,
    platform_intent: str = "unspecified",
    user_request: str = "",
) -> Task:
    """GUI Code Generator Task — 셋 모두 컨텍스트로.

    PR #138 Phase 1 minimal slice (2026-05-14, 본인 비전 통찰 6):
        ``format_consistency_directive`` 를 description 끝에 append.
        UI/UX Analyst + GUI Designer + Theme Designer 의 결정과 일치하는 코드
        작성을 *명시적으로* 강제. 환율 변환기 사례 (cross-agent inconsistency)
        재발 차단의 첫 시범 적용.

    PR #138 Phase 1 full (2026-05-15):
        ``format_consistency_directive`` → ``format_kickoff_context_directive``
        로 교체. ``shared_kickoff_decisions`` 가 None 이면 minimal slice 와 동일
        동작 (지시만), 채워져 있으면 *공유 가정 + 부서별 책임* 까지 description
        에 풀어 LLM 이 합의를 *사실* 로 인식하도록 강제.
    """
    import sys

    from ._common import format_kickoff_context_directive

    base_description = (
        "이전 컨텍스트의 ui_spec + GUI 설계 + 디자인 토큰을 모두 만족하는 "
        "**바로 실행 가능한 Python GUI 코드** 를 백스토리에 명시된 4단 구조"
        "(프레임워크 선택 + 코드 + 실행 방법 + 작성자 노트)로 작성하세요. "
        "각 파일은 ```python 블록 + `# file:` 헤더 포함."
    )
    # v13 Phase 6.E P3 (PREVENTIVE) — web 의도면 base_description 자체를 web 전용으로
    # 교체 + 데스크탑 금지/완전 web 프로젝트 강제 directive 주입. platform_intent !=
    # "web" 이면 위 문자열 그대로 (desktop/unspecified 경로 byte-for-byte 불변 — 회귀 0).
    if platform_intent == "web":
        base_description = (
            "이전 컨텍스트의 ui_spec + GUI 설계 + 디자인 토큰을 모두 만족하는 "
            "**바로 실행 가능한 web 프론트엔드 코드** 를 4단 구조(프레임워크 선택 근거 + "
            "코드 + 실행 방법 + 작성자 노트)로 작성하세요. 각 파일은 fence 코드 블록 + "
            "첫 줄 `# file:` / `// file:` / `<!-- file: -->` 헤더 포함."
        ) + _build_web_platform_directive()
    # v13 Phase 6.E P14 — 제품 코드 생성기는 시스템 내부 컨텍스트 누수 차단 (product_scoped):
    # 부서 명단/cross-agent 역할명/RAG recall 제거 → 사용자 요청만 제품으로 구현.
    consistency_directive = format_kickoff_context_directive(
        shared_kickoff_decisions,
        prior_agent_roles=["UI/UX Analyst", "GUI Designer", "Theme Designer"],
        product_scoped=True,
    )

    # v13 Phase 6.E P14 — 사용자 요청을 최상위 권위 앵커로 prepend (시스템 자기-생성 버그 차단).
    product_anchor = _build_product_anchor(user_request)

    kwargs: dict = dict(
        description=product_anchor + base_description + consistency_directive,
        expected_output=(
            "프레임워크 선택 근거 + Python GUI 코드(파일 여러 개) + 실행 방법 + "
            "작성자 노트. 마지막 줄 `Final Answer: framework=..., files=N개, entry=...`."
        ),
        agent=coder,
        context=[uiux_task, designer_task, theme_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = GUICodeOutput
    return Task(**kwargs)


# ---------------------------------------------------------------------------
# 공통 산출물 저장 헬퍼
# ---------------------------------------------------------------------------
def _save_classic_artifacts(
    workflow_dir: Path,
    user_request: str,
    cto_strategy: str,
    analyst_brief: str,
    engineer_output: str,
    qa_review: str,
    pytest_suite: str = "",
) -> list[Path]:
    """기존 4-agent 산출물 저장 (00~04 + code/). 반환은 추출된 .py 파일 목록.

    PR #58: ``pytest_suite`` 가 비지 않으면 ``05_pytest_suite.md`` 로 저장하고
    ```python``` 블록을 같은 ``code/`` 디렉터리에 ``test_*.py`` 로 추출 →
    반환 목록에 합산.
    """
    (workflow_dir / "00_user_request.txt").write_text(user_request, encoding="utf-8")
    (workflow_dir / "01_cto_strategy.md").write_text(cto_strategy, encoding="utf-8")
    (workflow_dir / "02_analyst_brief.md").write_text(analyst_brief, encoding="utf-8")
    (workflow_dir / "03_engineer_output.md").write_text(engineer_output, encoding="utf-8")
    (workflow_dir / "04_qa_review.md").write_text(qa_review, encoding="utf-8")
    code_paths = _extract_code_blocks(engineer_output, workflow_dir / "code")
    if pytest_suite:
        (workflow_dir / "05_pytest_suite.md").write_text(pytest_suite, encoding="utf-8")
        code_paths += _extract_code_blocks(pytest_suite, workflow_dir / "code")
    return code_paths


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_analyze_and_implement(
    user_request: str,
    outputs_dir: Optional[Path] = None,
    verbose: bool = True,
    enable_gui_branch: bool = False,
    enable_build_branch: bool = False,
    target_platform: str = "windows",
    enable_release_branch: bool = False,
    previous_version: str = "",
    repo_url: str = "",
    signing_available: bool = False,
    privacy_level: str = "public",
    enable_executor: bool = False,
    executor_timeout_sec: int = 300,
    enable_publish: bool = False,
    publish_as_draft: bool = True,
    publish_timeout_sec: int = 120,
    enable_automate_branch: bool = False,
    enable_automate_qa_loop: bool = False,
    enable_automate_build: bool = False,
    automate_build_timeout_sec: int = 300,
    enable_automate_release: bool = False,
    automate_repo_url: str = "",
    automate_release_tag: str = "",
    automate_release_title: str = "",
    automate_publish_as_draft: bool = True,
    automate_publish_timeout_sec: int = 120,
    shared_kickoff_decisions=None,
    enable_engineer_reviewer_delegation: bool = False,
    platform_intent: str = "unspecified",
) -> WorkflowResult:
    """사용자 요청을 받아 4-agent 협업 워크플로우 (Phase 4 GUI / Phase 4.5 빌드 옵션 포함)를 실행.

    Args:
        user_request: 사용자의 자연어 요구사항.
        outputs_dir: 산출물 저장 디렉터리. 기본은 프로젝트 루트의 `outputs/`.
        verbose: CrewAI의 중간 로그를 콘솔에 출력할지 여부.
        enable_gui_branch: Phase 4 토글. **기본 False — backward compat 보장**.
            True 면 UI/UX Analyst 가 먼저 실행되어 GUI/CLI 경로를 결정하고,
            GUI 경로면 디자인 본부 3명 (GUI Designer / Theme / Code Generator)
            이 Engineer 자리를 대체. CLI 경로면 기존 Engineer 그대로 + UI/UX
            컨텍스트만 CTO 에 추가.
        enable_build_branch: Phase 4.5 토글. **기본 False — backward compat 보장**.
            True 면 메인 체인(CTO→Analyst→Engineer/GUI→QA) 종료 후 빌드 5단 사슬
            (Dep Analyzer → Build Engineer → Asset Manager → Installer Creator →
            Platform Tester) 가 추가 실행되어 결과를 WorkflowResult 의 신규 필드
            (dependency_report / build_spec / asset_manifest / installer_spec /
            platform_test_report) 에 채운다. 산출 파일 20~24 가 추가됨.
        target_platform: Phase 4.5 빌드 사슬의 대상 플랫폼. windows / macos /
            linux / cross-platform. enable_build_branch=False 면 무시됨.
        enable_release_branch: Phase 5 토글. **기본 False — backward compat**.
            True 면 빌드 사슬 종료 후 릴리스 4단 사슬 (Release Manager →
            Changelog Generator → Update Checker → Distribution Agent) 가 추가
            실행되어 결과를 WorkflowResult 의 신규 4 필드 (release_decision /
            changelog_entry / update_module_spec / distribution_spec) 에 채운다.
            산출 파일 30~33 가 추가됨.
        previous_version: Phase 5 입력 — 이전 릴리스 버전 (없으면 첫 릴리스).
            enable_release_branch=False 면 무시됨.
        repo_url: Phase 5 입력 — GitHub repo URL (Update endpoint 자동 추출용).
        signing_available: Phase 5 입력 — 코드 서명 EV 인증서 보유 여부.
        privacy_level: Phase 5 입력 — public | corporate-internal | one-time-share.

    Returns:
        `WorkflowResult` — 신규 Phase 4/4.5 필드는 각 토글 비활성 시 빈 문자열.

    Raises:
        RuntimeError: Provider 초기화 등 체인 중간 장애가 발생했을 때 호출 측에서
            명확히 포착할 수 있도록 원본 예외를 그대로 전파한다.

    Phase 4.5 한계 (build branch):
        실제 PyInstaller 호출·setup.exe 빌드는 외부 도구 의존이라 통합하지 않음.
        본 토글은 *사양 산출만* (LLM 5건). Platform Tester 는 Phase 3 sandbox 의
        `run_python_package_in_sandbox` 결과를 narration 입력으로 활용.

    Phase 5 한계 (release branch):
        실제 Git 태그 생성·gh release create 호출·파일 업로드·SHA256 산출은 외부
        자동화 스크립트 또는 CI 가 본 사양 보고 수행해야 함. 본 토글은 *사양 산출만*
        (LLM 4건). Update Checker 의 `updater.py` 는 *참조 구현* — 실제 통합은
        Engineer 단계의 별도 작업.

    Phase 6 Track B (automate branch, PR #70):
        ``enable_automate_branch=True`` 시 **사용자 요청 도메인 휴리스틱 분류** 후
        Track A (CTO/Analyst/Engineer/QA 체인) 대신 ``run_automate_workflow`` 로
        디스패치. 5 도메인 (web_scraping / desktop_automation / api_integration /
        data_parser / devops) 중 1명 호출. 휴리스틱이 UNKNOWN 이면 Track A 로
        fallback (backward compat). Track A / B 의 결과는 같은 ``WorkflowResult``
        에 매핑되어 호출 측 인터페이스 일관성 유지.
    """
    target_outputs_dir = outputs_dir if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
    target_outputs_dir.mkdir(parents=True, exist_ok=True)

    monitor = get_langfuse_client()
    # Phase 라벨 — 가장 깊은 활성화 단계로
    if enable_release_branch:
        phase_label = "phase_5"
    elif enable_build_branch:
        phase_label = "phase_4_5"
    elif enable_gui_branch:
        phase_label = "phase_4"
    else:
        phase_label = "phase_1"

    monitor.log_trace(
        name="analyze_and_implement",
        user_id="local-dev",
        metadata={
            "phase": phase_label,
            "workflow": "analyze_and_implement",
            "user_request_preview": user_request[:160],
            "enable_gui_branch": enable_gui_branch,
            "enable_build_branch": enable_build_branch,
            "enable_release_branch": enable_release_branch,
            "target_platform": target_platform if enable_build_branch else None,
            "previous_version": previous_version if enable_release_branch else None,
        },
    )

    try:
        # ─── Phase 6 Track B 라우팅 (PR #70) ──────────────────────────────
        # enable_automate_branch=True 면 휴리스틱 분류 → Track B 단일 에이전트 호출.
        # UNKNOWN 시 Track A 로 fallback (backward compat).
        if enable_automate_branch:
            from src.workflows.automate_workflow import (
                AutomationDomain,
                detect_automation_domain,
                run_automate_workflow,
            )

            domain = detect_automation_domain(user_request)
            if domain is not AutomationDomain.UNKNOWN:
                automate_result = run_automate_workflow(
                    user_request,
                    outputs_dir=target_outputs_dir,
                    forced_domain=domain,
                    verbose=verbose,
                    enable_qa_loop=enable_automate_qa_loop,
                    enable_build=enable_automate_build,
                    build_timeout_sec=automate_build_timeout_sec,
                    enable_release=enable_automate_release,
                    repo_url=automate_repo_url,
                    release_tag=automate_release_tag,
                    release_title=automate_release_title,
                    publish_as_draft=automate_publish_as_draft,
                    publish_timeout_sec=automate_publish_timeout_sec,
                    target_platform=target_platform,
                )
                # AutomateWorkflowResult → WorkflowResult 매핑 (호출 측 일관성).
                # PR #90 — Track B 산출 5 필드 propagate (PR #81/#82/#83 결과를
                # 검증 스크립트가 정확히 인지하도록):
                #   - pytest_suite (PR #81 QA loop)
                #   - executor_result (PR #82 Build) → 5_executor_success 판정
                #   - update_module_spec (PR #83 Release Update Checker)
                #   - publish_result (PR #83 gh release create)
                return WorkflowResult(
                    user_request=user_request,
                    cto_strategy=f"(Track B routing — domain={domain.value})",
                    analyst_brief="",
                    engineer_output=automate_result.agent_output,
                    qa_review="",
                    saved_dir=automate_result.saved_dir or target_outputs_dir,
                    saved_code_files=list(automate_result.saved_code_files),
                    chosen_path=f"automate_{domain.value}",
                    pytest_suite=automate_result.pytest_suite,
                    executor_result=automate_result.executor_result,
                    update_module_spec=automate_result.update_module_spec,
                    publish_result=automate_result.publish_result,
                )
            # UNKNOWN → 그대로 Track A 진행 (fallback)

        # 산출 디렉터리 미리 만들어 모든 경로가 동일 워크디렉터리 사용
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workflow_dir = target_outputs_dir / f"workflow_{timestamp}"
        workflow_dir.mkdir(parents=True, exist_ok=True)

        # ─── 분기 0: Phase 4 비활성 — 기존 4-agent 그대로 ──────────────────────
        if not enable_gui_branch:
            result = _run_classic_chain(
                user_request,
                workflow_dir,
                verbose=verbose,
                shared_kickoff_decisions=shared_kickoff_decisions,
                enable_engineer_reviewer_delegation=enable_engineer_reviewer_delegation,
            )
        else:
            # ─── 분기 1: Phase 4 활성 — UI/UX 먼저 실행 ────────────────────────
            ui_ux = create_uiux_analyst_agent(verbose=verbose)
            uiux_task = _build_uiux_task(user_request, ui_ux)
            _uiux_crew = Crew(
                agents=[ui_ux],
                tasks=[uiux_task],
                process=Process.sequential,
                verbose=verbose,
            )
            # 이슈 6 방어선 3 (PR #53) — ConverterError 시 output_pydantic 벗기고 재시도
            kickoff_with_converter_rescue(_uiux_crew, [uiux_task])
            # 이슈 6 방어선 1 (PR #29) — LLM 이 본문 생략 시 자동 재시도
            retry_short_tasks_in_chain([uiux_task])
            ui_spec = _task_output_text(uiux_task)

            chosen_path = _parse_ui_ux_path(ui_spec)

            # ─── 분기 2-A: GUI 경로 ─────────────────────────────────────────────
            if chosen_path == "gui":
                result = _run_gui_branch_chain(
                    user_request=user_request,
                    workflow_dir=workflow_dir,
                    ui_spec=ui_spec,
                    uiux_task=uiux_task,
                    verbose=verbose,
                    shared_kickoff_decisions=shared_kickoff_decisions,
                    enable_engineer_reviewer_delegation=enable_engineer_reviewer_delegation,
                    platform_intent=platform_intent,
                )
            # ─── 분기 2-B: CLI 경로 ─────────────────────────────────────────────
            else:
                result = _run_cli_branch_chain_with_ui_context(
                    user_request=user_request,
                    workflow_dir=workflow_dir,
                    ui_spec=ui_spec,
                    uiux_task=uiux_task,
                    verbose=verbose,
                    shared_kickoff_decisions=shared_kickoff_decisions,
                    enable_engineer_reviewer_delegation=enable_engineer_reviewer_delegation,
                )

        # ─── Phase 4.5 — Build 사슬 (옵션) ──────────────────────────────────────
        if enable_build_branch:
            # 지연 import — 순환 import 회피 (build_workflow 가 다른 모듈 의존)
            from src.workflows.build_workflow import run_build_workflow

            build_result = run_build_workflow(
                code_files=result.saved_code_files,
                user_request=user_request,
                target_platform=target_platform,
                ui_spec=result.ui_spec,
                design_tokens=result.design_tokens,
                workflow_dir=result.saved_dir,
                enable_platform_test=True,
                enable_executor=enable_executor,
                executor_timeout_sec=executor_timeout_sec,
                verbose=verbose,
                shared_kickoff_decisions=shared_kickoff_decisions,
            )
            # Build 결과를 메인 WorkflowResult 에 merge
            result.dependency_report = build_result.dependency_report
            result.build_spec = build_result.build_spec
            result.asset_manifest = build_result.asset_manifest
            result.installer_spec = build_result.installer_spec
            result.platform_test_report = build_result.platform_test_report
            # PR #36/#37 — executor 결과 (있을 때만 채워짐)
            if build_result.executor_result is not None:
                result.executor_result = build_result.executor_result

        # ─── Phase 5 — Release 사슬 (옵션) ──────────────────────────────────────
        if enable_release_branch:
            from src.workflows.release_workflow import run_release_workflow

            # Release Manager 입력으로 메인 체인 + (있으면) 빌드 산출 요약
            change_summary_parts = [f"사용자 요청: {user_request}"]
            if result.engineer_output:
                change_summary_parts.append(
                    "Engineer 산출 (요약): " + result.engineer_output[:300] + "..."
                )
            if result.gui_code_output:
                change_summary_parts.append(
                    "GUI Code Generator 산출 (요약): " + result.gui_code_output[:300] + "..."
                )
            change_summary = "\n".join(change_summary_parts)

            build_summary_parts = []
            if result.build_spec:
                build_summary_parts.append("Build Engineer: " + result.build_spec[:300] + "...")
            if result.installer_spec:
                build_summary_parts.append(
                    "Installer Creator: " + result.installer_spec[:300] + "..."
                )
            build_summary = "\n".join(build_summary_parts) if build_summary_parts else ""

            # app_short_name 휴리스틱 — UI/UX assumptions 또는 기본값
            app_short_name = "NexusApp"

            # PR #36+39 — executor_result 가 있으면 artifact_summary 에 실 .exe 정보 포함
            executor_result = result.executor_result
            if executor_result is not None and getattr(executor_result, "success", False):
                artifact_summary_text = (
                    f"build_executor 산출 — {executor_result.exe_path.name}, "
                    f"{executor_result.exe_size_bytes:,} bytes ({executor_result.exe_size_bytes / (1024*1024):.2f} MB), "
                    f"sha256={executor_result.sha256[:16]}..."
                )
            else:
                artifact_summary_text = (
                    "Phase 4.5 빌드 사양 산출 — 실제 .exe 미생성 (외부 자동화 위임)"
                )

            release_result = run_release_workflow(
                previous_version=previous_version,
                change_summary=change_summary,
                change_sources=change_summary,  # 단일 패스라 history 부재 — summary 재사용
                breaking_flags="none",
                build_summary=build_summary,
                artifact_summary=artifact_summary_text,
                target_platform=target_platform,
                repo_url=repo_url,
                app_short_name=app_short_name,
                signing_available=signing_available,
                privacy_level=privacy_level,
                workflow_dir=result.saved_dir,
                enable_publish=enable_publish,
                publish_as_draft=publish_as_draft,
                publish_timeout_sec=publish_timeout_sec,
                executor_result=executor_result,
                verbose=verbose,
            )
            # Release 결과 merge
            result.release_decision = release_result.release_decision
            result.changelog_entry = release_result.changelog_entry
            result.update_module_spec = release_result.update_module_spec
            result.distribution_spec = release_result.distribution_spec
            # PR #39 — publish 결과 (있을 때만)
            if release_result.publish_result is not None:
                result.publish_result = release_result.publish_result
            # PR #66 — Update Checker 실 통합 (방어선 4 패턴)
            #   release_result.update_module_spec 의 ```python``` 블록을
            #   code/ 로 추출 → code/updater.py 자동 생성 → entry (.py) 에
            #   try/import 라인 자동 삽입. saved_code_files 에 합산.
            if result.saved_dir is not None and release_result.update_module_spec:
                integrated = _integrate_update_checker(
                    result.saved_dir, release_result.update_module_spec
                )
                # _extract_code_blocks 가 반환하는 path 와 modified entry 합산
                # (modified 는 이미 saved_code_files 에 들어있을 수 있어 dedup)
                seen = {p.resolve() for p in result.saved_code_files}
                for p in integrated:
                    if p.resolve() not in seen:
                        result.saved_code_files.append(p)
                        seen.add(p.resolve())

        return result

    finally:
        monitor.end_trace()
        monitor.flush()


# ---------------------------------------------------------------------------
# 내부 — 기존 4-agent 본문 (Phase 2-P2 그대로)
# ---------------------------------------------------------------------------
def _run_classic_chain(
    user_request: str,
    workflow_dir: Path,
    *,
    verbose: bool,
    shared_kickoff_decisions=None,
    enable_engineer_reviewer_delegation: bool = False,
) -> WorkflowResult:
    """`enable_gui_branch=False` (기본) 경로. 기존 동작 그대로 보존 + PR #58 Pytest Author.

    PR #141 Phase 2 (본인 비전 통찰 6 D-2):
        ``enable_engineer_reviewer_delegation=True`` 시 Python Engineer + Code Reviewer
        만 ``allow_delegation=True`` 로 생성 → CrewAI 가 둘 사이 양방향 위임 허용.
        Engineer 가 Reviewer 에게 "이 가정 검증 부탁" 요청 가능, Reviewer 가
        Engineer 에게 "이 부분 재작성 요청" 가능. 전체 ON 은 비용 폭증이라 *2 명만*.
    """
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    engineer = create_python_engineer_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )
    pytest_author = create_pytest_author_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )

    cto_task = _build_cto_task(user_request, cto)
    analyst_task = _build_analyst_task(analyst, cto_task)
    engineer_task = _build_engineer_task(engineer, cto_task, analyst_task)
    pytest_author_task = _build_pytest_author_task(
        pytest_author,
        engineer_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=["CTO", "Data Analyst", "Python Engineer"],
    )
    qa_review_task = _build_qa_task(
        reviewer,
        engineer_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=["CTO", "Data Analyst", "Python Engineer"],
    )

    _classic_tasks = [
        cto_task,
        analyst_task,
        engineer_task,
        pytest_author_task,
        qa_review_task,
    ]
    _classic_crew = Crew(
        agents=[cto, analyst, engineer, pytest_author, reviewer],
        tasks=_classic_tasks,
        process=Process.sequential,
        verbose=verbose,
    )
    # 이슈 6 방어선 3 (PR #53) — ConverterError 시 output_pydantic 벗기고 재시도
    crew_result = kickoff_with_converter_rescue(_classic_crew, _classic_tasks)
    # 이슈 6 방어선 1 (PR #29) — LLM 본문 누락 자동 재시도
    retry_short_tasks_in_chain(_classic_tasks)

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    engineer_output = _task_output_text(engineer_task)
    pytest_suite = _task_output_text(pytest_author_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
    )
    # v13 P24 — NEEDS_REVISION 빈 본문 안전망: 빈 본문이면 재생성 1회 → 그래도 비면 보강 본문.
    # 빈 verdict-only 를 04_qa_review.md / 다음 iteration 에 절대 전파하지 않음 (회귀 0: 정상 본문 no-op).
    qa_review = _maybe_regenerate_on_qa_empty_body(
        qa_review_task, qa_review, workflow_dir=workflow_dir, verbose=verbose
    )

    code_paths = _save_classic_artifacts(
        workflow_dir,
        user_request,
        cto_strategy,
        analyst_brief,
        engineer_output,
        qa_review,
        pytest_suite=pytest_suite,
    )

    return WorkflowResult(
        user_request=user_request,
        cto_strategy=cto_strategy,
        analyst_brief=analyst_brief,
        engineer_output=engineer_output,
        qa_review=qa_review,
        saved_dir=workflow_dir,
        saved_code_files=code_paths,
        pytest_suite=pytest_suite,
        # Phase 4 필드는 기본값 (빈 문자열) — backward compat
    )


# ---------------------------------------------------------------------------
# 내부 — Phase 4 CLI 경로 (UI/UX 만 추가, 기존 흐름 보존)
# ---------------------------------------------------------------------------
def _run_cli_branch_chain_with_ui_context(
    user_request: str,
    workflow_dir: Path,
    ui_spec: str,
    uiux_task: Task,
    *,
    verbose: bool,
    shared_kickoff_decisions=None,
    enable_engineer_reviewer_delegation: bool = False,
) -> WorkflowResult:
    """UI/UX 가 GUI 가 아니라고 판정한 경로. Engineer 그대로 + UI/UX context 만 추가 + PR #58 Pytest Author."""
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    engineer = create_python_engineer_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )
    pytest_author = create_pytest_author_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )

    cto_task = _build_cto_task(user_request, cto, ui_spec_context=uiux_task)
    analyst_task = _build_analyst_task(analyst, cto_task)
    engineer_task = _build_engineer_task(engineer, cto_task, analyst_task)
    pytest_author_task = _build_pytest_author_task(
        pytest_author,
        engineer_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=["UI/UX Analyst", "CTO", "Data Analyst", "Python Engineer"],
    )
    qa_review_task = _build_qa_task(
        reviewer,
        engineer_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=["UI/UX Analyst", "CTO", "Data Analyst", "Python Engineer"],
    )

    _cli_tasks = [
        cto_task,
        analyst_task,
        engineer_task,
        pytest_author_task,
        qa_review_task,
    ]
    _cli_crew = Crew(
        agents=[cto, analyst, engineer, pytest_author, reviewer],
        tasks=_cli_tasks,
        process=Process.sequential,
        verbose=verbose,
    )
    # 이슈 6 방어선 3 (PR #53) — ConverterError 시 output_pydantic 벗기고 재시도
    crew_result = kickoff_with_converter_rescue(_cli_crew, _cli_tasks)
    # 이슈 6 방어선 1 (PR #29) — LLM 본문 누락 자동 재시도
    retry_short_tasks_in_chain(_cli_tasks)

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    engineer_output = _task_output_text(engineer_task)
    pytest_suite = _task_output_text(pytest_author_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
    )
    # v13 P24 — NEEDS_REVISION 빈 본문 안전망: 빈 본문이면 재생성 1회 → 그래도 비면 보강 본문.
    # 빈 verdict-only 를 04_qa_review.md / 다음 iteration 에 절대 전파하지 않음 (회귀 0: 정상 본문 no-op).
    qa_review = _maybe_regenerate_on_qa_empty_body(
        qa_review_task, qa_review, workflow_dir=workflow_dir, verbose=verbose
    )

    code_paths = _save_classic_artifacts(
        workflow_dir,
        user_request,
        cto_strategy,
        analyst_brief,
        engineer_output,
        qa_review,
        pytest_suite=pytest_suite,
    )
    # Phase 4 활성 시 추가 산출
    (workflow_dir / "10_ui_ux_spec.md").write_text(ui_spec, encoding="utf-8")

    return WorkflowResult(
        user_request=user_request,
        cto_strategy=cto_strategy,
        analyst_brief=analyst_brief,
        engineer_output=engineer_output,
        qa_review=qa_review,
        saved_dir=workflow_dir,
        saved_code_files=code_paths,
        pytest_suite=pytest_suite,
        chosen_path="cli",
        ui_spec=ui_spec,
    )


# ---------------------------------------------------------------------------
# 내부 — Phase 4 GUI 경로 (디자인 본부 3명 사슬 + QA)
# ---------------------------------------------------------------------------
def _run_gui_branch_chain(
    user_request: str,
    workflow_dir: Path,
    ui_spec: str,
    uiux_task: Task,
    *,
    verbose: bool,
    shared_kickoff_decisions=None,
    enable_engineer_reviewer_delegation: bool = False,
    platform_intent: str = "unspecified",
) -> WorkflowResult:
    """UI/UX 가 GUI 라고 판정한 경로. Engineer 자리를 디자인 본부 3명이 대체 + PR #58 Pytest Author.

    PR #141 Phase 2:
        GUI 경로에서는 Python Engineer 자리를 GUI Code Generator 가 대체. delegation
        토글이 켜지면 GUI Code Generator + Code Reviewer 사이 양방향 위임 허용.
        (Engineer 가 *코드 산출자* 라는 역할 동일성 — Phase 2 의 paradigm shift 의도
        그대로 GUI 경로에서도 작동.)
    """
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    designer = create_gui_designer_agent(verbose=verbose)
    theme = create_theme_designer_agent(verbose=verbose)
    coder = create_gui_code_generator_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )
    pytest_author = create_pytest_author_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(
        verbose=verbose, allow_delegation=enable_engineer_reviewer_delegation
    )

    cto_task = _build_cto_task(user_request, cto, ui_spec_context=uiux_task)
    analyst_task = _build_analyst_task(analyst, cto_task)
    designer_task = _build_gui_designer_task(designer, uiux_task)
    theme_task = _build_theme_task(theme, uiux_task, designer_task)
    code_gen_task = _build_gui_code_gen_task(
        coder,
        uiux_task,
        designer_task,
        theme_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        platform_intent=platform_intent,
        user_request=user_request,  # P14 — 제품 최상위 권위 앵커
    )
    pytest_author_task = _build_pytest_author_task(
        pytest_author,
        code_gen_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=[
            "UI/UX Analyst",
            "GUI Designer",
            "Theme Designer",
            "GUI Code Generator",
        ],
    )
    qa_review_task = _build_qa_task(
        reviewer,
        code_gen_task,
        shared_kickoff_decisions=shared_kickoff_decisions,
        prior_agent_roles=[
            "UI/UX Analyst",
            "GUI Designer",
            "Theme Designer",
            "GUI Code Generator",
        ],
    )

    _gui_tasks = [
        cto_task,
        analyst_task,
        designer_task,
        theme_task,
        code_gen_task,
        pytest_author_task,
        qa_review_task,
    ]
    _gui_crew = Crew(
        agents=[cto, analyst, designer, theme, coder, pytest_author, reviewer],
        tasks=_gui_tasks,
        process=Process.sequential,
        verbose=verbose,
    )
    # 이슈 6 방어선 3 (PR #53) — ConverterError 시 output_pydantic 벗기고 재시도
    crew_result = kickoff_with_converter_rescue(_gui_crew, _gui_tasks)
    # 이슈 6 방어선 1 (PR #29) — LLM 본문 누락 자동 재시도 (GUI 체인 6 task)
    retry_short_tasks_in_chain(_gui_tasks)

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    gui_design = _task_output_text(designer_task)
    design_tokens = _task_output_text(theme_task)
    gui_code_output = _task_output_text(code_gen_task)
    # v13 Phase 6.E P3 (CURATIVE) — web 의도인데 데스크탑 GUI 마커 감지 시 코더 task 만
    # N회 hardened-directive 재생성 (iter 카운터 불변 — 단일 iteration 내부; pytest 중
    # no-op). 소진 시 fall-through → 기존 judge PLATFORM_DRIFT(P1) 백스톱이 처리.
    # platform_intent != "web" 이면 즉시 입력 반환 (desktop/unspecified 경로 불변 — 회귀 0).
    gui_code_output = _maybe_regenerate_on_platform_drift(
        gui_code_output,
        code_gen_task=code_gen_task,
        coder=coder,
        context_tasks=[uiux_task, designer_task, theme_task],
        platform_intent=platform_intent,
        verbose=verbose,
    )
    pytest_suite = _task_output_text(pytest_author_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
    )
    # v13 P24 — NEEDS_REVISION 빈 본문 안전망: 빈 본문이면 재생성 1회 → 그래도 비면 보강 본문.
    # 빈 verdict-only 를 04_qa_review.md / 다음 iteration 에 절대 전파하지 않음 (회귀 0: 정상 본문 no-op).
    qa_review = _maybe_regenerate_on_qa_empty_body(
        qa_review_task, qa_review, workflow_dir=workflow_dir, verbose=verbose
    )

    # 산출 저장 — 기존 00~02·04 유지 (engineer_output 자리는 빈 문자열)
    (workflow_dir / "00_user_request.txt").write_text(user_request, encoding="utf-8")
    (workflow_dir / "01_cto_strategy.md").write_text(cto_strategy, encoding="utf-8")
    (workflow_dir / "02_analyst_brief.md").write_text(analyst_brief, encoding="utf-8")
    (workflow_dir / "03_engineer_output.md").write_text(
        "(GUI 경로 — Python Engineer 미실행. gui_code_output 참고)",
        encoding="utf-8",
    )
    (workflow_dir / "04_qa_review.md").write_text(qa_review, encoding="utf-8")

    # Phase 4 GUI 추가 산출
    (workflow_dir / "10_ui_ux_spec.md").write_text(ui_spec, encoding="utf-8")
    (workflow_dir / "11_gui_design.md").write_text(gui_design, encoding="utf-8")
    (workflow_dir / "12_design_tokens.md").write_text(design_tokens, encoding="utf-8")
    (workflow_dir / "13_gui_code_output.md").write_text(gui_code_output, encoding="utf-8")
    if pytest_suite:
        (workflow_dir / "14_pytest_suite.md").write_text(pytest_suite, encoding="utf-8")

    # 코드 추출 — GUI Code Generator 산출 + (PR #58) Pytest Author 산출 합산
    # v13 Phase 6.E P2-A (PR #236) — GUI 산출은 web(.ts/.html/.css/...) 포함 추출.
    # P10b(i) — web 경로는 실 src/ 서브트리로 작성(평탄화 X) → index.html 의 /src/main.ts 및
    # 상대 import 가 vite/tsc 에서 네이티브 해소 (P9 verdict 의 둘째 벽 차단). preserve_tree
    # 는 *이 GUI web 호출에만* 적용 — Track A/CLI/pytest 추출은 평탄 유지 (회귀 0).
    code_paths = _extract_code_blocks(
        gui_code_output, workflow_dir / "code", languages=_WEB_CODE_LANGS, preserve_tree=True
    )
    # v13 P16 (수정1b) — degenerate(빈/단축 코드) 산출이면 *우회/manifest 합성 이전에* 코더를
    # N회 '실제 코드 출력' 지시로 재호출 + 재추출 (원천 재생성). 회복 시 채택, 소진 시 기존
    # 13d 마커 + P15 best-iteration 폴백. manifest 합성 전 검사라 합성 stub 에 가려지지 않음.
    gui_code_output, code_paths = _maybe_regenerate_on_degenerate(
        gui_code_output,
        code_paths,
        code_gen_task=code_gen_task,
        coder=coder,
        context_tasks=[uiux_task, designer_task, theme_task],
        workflow_dir=workflow_dir,
        platform_intent=platform_intent,
        verbose=verbose,
    )
    # 재생성으로 산출이 바뀌었을 수 있으니 13_gui_code_output.md 를 최종본으로 재기록.
    (workflow_dir / "13_gui_code_output.md").write_text(gui_code_output, encoding="utf-8")
    # P10a(3) — web 빌드 필수 manifest(package.json/tsconfig.json) salvage→synthesize 보장.
    # jsonc/json5 는 P10a(1) 로 이미 추출되나, 미상장 fence·완전 누락까지 fail-loud 로 커버.
    # 비-web(데스크탑) 산출이면 no-op (회귀 0).
    code_paths += _ensure_web_manifests(gui_code_output, workflow_dir / "code", code_paths)
    # P2-A 손실 가드 — web 산출인데 web 파일 0개 추출 시 경고 아티팩트 기록 (조용한 손실 방지).
    _loss_warning = _detect_extraction_loss(gui_code_output, code_paths)
    if _loss_warning:
        (workflow_dir / "13b_extraction_warning.txt").write_text(
            _loss_warning, encoding="utf-8"
        )
    # v13 Phase 6.E P14 (수정3) — 비현실적 단축/entry 부재 = 생성 실패 처리 (fail-loud 아티팩트).
    # Rule 0(도메인 마커 0매칭 → IMPROVE) + 빌드 실패(no-entry/manifest → P12 web 루프) 가
    # 자가수정을 잇고, 본 아티팩트가 '깨진 산출이 유효로 통과하지 않음' 을 가시화.
    if _is_degenerate_codegen(code_paths, platform_intent):
        (workflow_dir / "13d_generation_failed.txt").write_text(
            "⚠ 생성 실패(degenerate) — 코드 산출이 비현실적으로 짧거나 entry/manifest 부재. "
            "retry 후에도 유효 산출 미생성 → 빌드/COMPLETE 부적격, 다음 iteration 재생성 필요 "
            "(P14 수정3).",
            encoding="utf-8",
        )
    if pytest_suite:
        # pytest 산출은 python-only 유지 (test_*.py) — 평탄 (preserve_tree=False, 기본)
        code_paths += _extract_code_blocks(pytest_suite, workflow_dir / "code")

    return WorkflowResult(
        user_request=user_request,
        cto_strategy=cto_strategy,
        analyst_brief=analyst_brief,
        engineer_output="",
        qa_review=qa_review,
        saved_dir=workflow_dir,
        saved_code_files=code_paths,
        pytest_suite=pytest_suite,
        chosen_path="gui",
        ui_spec=ui_spec,
        gui_design=gui_design,
        design_tokens=design_tokens,
        gui_code_output=gui_code_output,
    )
