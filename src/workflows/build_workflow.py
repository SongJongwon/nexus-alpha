# -*- coding: utf-8 -*-
"""
Nexus Alpha 빌드 워크플로우 (Phase 4.5 통합 — v4).

`run_build_workflow(code_files, user_request, ...)` — 빌드 & 배포 본부의 5명 사슬을
한 번에 호출하는 공개 진입점. analyze_and_implement 산출(코드)을 입력으로
받아 빌드 사양·자원 매니페스트·인스톨러 스크립트·산출물 검증을 순차로 산출.

5단계 사슬 (org_v4 §3-8 — 빌드 & 배포 본부):
    1. Dependency Analyzer  → 의존성 6축 보고서 (hidden imports / data files /
       native binaries / license / OS-specific 등)
    2. Build Engineer       → PyInstaller / Nuitka / cx_Freeze 중 도구 선택 +
       spec/명령
    3. Asset Manager        → 비-코드 자원 매니페스트 (icons / fonts / locales /
       LICENSE 등)
    4. Installer Creator    → Inno Setup / WiX / pkgbuild / AppImage 인스톨러
       스크립트
    5. Platform Tester      → Phase 3 sandbox 결과를 받아 부팅 smoke 검증 narration

⚠️ MVP 한계 (모든 호출 측에 명시):
    - 본 워크플로우는 *사양만* 산출. 실제 PyInstaller 호출·setup.exe 빌드·
      더블클릭 실행은 외부 도구 의존이라 통합하지 않음 (v5 또는 별도 후속 작업).
    - Platform Tester 는 *Engineer 산출 .py 코드의 부팅 smoke* (Phase 3
      `run_python_package_in_sandbox`) 를 검증 입력으로 사용. 실제 .exe 가 아님.
      따라서 "코드는 적어도 부팅됨" 정도의 약한 검증만 가능.
    - 진짜 빌드·실행 검증은 별도 외부 도구(PyInstaller, Inno Setup, Windows
      Sandbox) 호출 통합 작업 필요.

호출 측 사용 예:
    from src.workflows import run_build_workflow

    build_result = run_build_workflow(
        code_files=[Path("dist/calc.py"), ...],
        user_request="사칙연산 계산기",
        target_platform="windows",
        ui_spec="<UI/UX Analyst 산출 — 있으면>",
        design_tokens="<Theme Designer 산출 — 있으면>",
        workflow_dir=Path("outputs/workflow_..."),
    )
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from crewai import Crew, Process, Task

from src.agents.build_release import (
    PlatformTestResult,
    create_asset_manager_agent,
    create_build_engineer_agent,
    create_dependency_analyzer_agent,
    create_installer_creator_agent,
    create_platform_tester_agent,
    format_platform_test_result_for_task,
)
from src.agents.build_release.build_executor import (
    ExecuteResult,
    _validate_windowed_bootloader,
    execute_pyinstaller,
)
from src.agents.operations import run_python_package_in_sandbox
from src.monitoring import get_langfuse_client
from src.workflows._common import (
    format_kickoff_context_directive,
    kickoff_with_converter_rescue,
    retry_short_tasks_in_chain,
    task_output_text as _task_output_text,
)
from src.workflows._schemas import (
    AssetManifestOutput,
    BuildSpecOutput,
    DependencyReportOutput,
    InstallerSpecOutput,
    PlatformTestReportOutput,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 결과 dataclass
# ---------------------------------------------------------------------------
@dataclass
class BuildWorkflowResult:
    """`run_build_workflow` 의 최종 산출물.

    Attributes:
        dependency_report: Dependency Analyzer 산출 (YAML 6축).
        build_spec: Build Engineer 산출 (도구 선택 + spec/명령).
        asset_manifest: Asset Manager 산출 (icons/fonts/legal_texts).
        installer_spec: Installer Creator 산출 (Inno Setup .iss 등).
        platform_test_report: Platform Tester narration 보고서.
        sandbox_result: Phase 3 결정론 검증 결과 (있을 때만 채워짐).
            None 이면 (a) enable_platform_test=False, (b) code_files 비었음, (c)
            entry 미탐지 중 하나.
        saved_files: 산출 파일들 (20~24 prefix). workflow_dir 가 None 이면 빈 리스트.
        target_platform: 빌드 대상 플랫폼 (windows / macos / linux 등) — 입력 echo.
        executor_result: PR #36 — PyInstaller 실제 호출 결과. ``enable_executor=True``
            이고 entry 가 탐지됐을 때만 채워짐. 그 외엔 None (graceful — 사양 사슬은
            여전히 작동).
    """

    dependency_report: str
    build_spec: str
    asset_manifest: str
    installer_spec: str
    platform_test_report: str
    sandbox_result: Optional[PlatformTestResult]
    saved_files: list[Path] = field(default_factory=list)
    target_platform: str = "windows"
    executor_result: Optional["ExecuteResult"] = None


# ---------------------------------------------------------------------------
# Task 빌더 (5명 각자)
# ---------------------------------------------------------------------------
def _build_dependency_analyzer_task(
    agent,
    code_summary: str,
    target_platform: str,
    *,
    shared_kickoff_decisions=None,
) -> Task:
    """Track B 첫 task — kickoff context only (no prior LLM task)."""
    import sys

    base_description = (
        "아래 4블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 보고서 6축 + "
        "분석가 코멘트 + 미검토 영역)로 한국어 의존성 보고서를 작성하세요. "
        "lazy import / data file / native binary 신호를 빠뜨리지 마세요.\n\n"
        f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
        f"[CODE_SAMPLES]\n(상위 호출 측이 코드 본문을 별도로 첨부하지 않은 경우, "
        f"PROJECT_LAYOUT 의 파일명·역할만으로 lazy import 가능성 추정)\n\n"
        f"[REQUIREMENTS]\n(상위 호출 측 미제공 — 코드에서 추론)\n\n"
        f"[TARGET_PLATFORM]\n{target_platform}\n"
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions, prior_agent_roles=()
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "YAML 6축 보고서 + 분석가 코멘트 + 미검토 영역. 마지막 줄 `Final Answer: "
            "deps=N개, hidden=M개, license_warnings=L개, os_blockers=B개`."
        ),
        agent=agent,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = DependencyReportOutput
    return Task(**kwargs)


def _build_build_engineer_task(
    agent,
    code_summary: str,
    target_platform: str,
    entry_hint: str,
    dep_task: Task,
    *,
    shared_kickoff_decisions=None,
) -> Task:
    # 이슈 6 방어선 2 (PR #31) — production 에서만 output_pydantic 활성.
    # pytest 환경에선 FakeProvider 응답이 JSON 스키마와 맞지 않아 false 실패 방지.
    import sys

    base_description = (
        "이전 컨텍스트의 의존성 보고서 + 아래 3블록을 받아, 백스토리에 명시된 "
        "5단 구조(도구 선택 / 빌드 명령 / 함정 / 검증 체크리스트 / 빌드 엔지니어 "
        "노트)로 한국어 빌드 사양을 작성하세요.\n\n"
        f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
        f"[TARGET_PLATFORM]\n{target_platform}\n\n"
        f"[ENTRY_POINT]\n{entry_hint}\n"
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions, prior_agent_roles=["Dependency Analyzer"]
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "5단 한국어 빌드 사양. 마지막 줄 `Final Answer: tool=X, mode=Y, "
            "hidden_imports=N개, est_size=~ZMB`."
        ),
        agent=agent,
        context=[dep_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = BuildSpecOutput
    return Task(**kwargs)


def _build_asset_manager_task(
    agent,
    user_request: str,
    code_summary: str,
    design_tokens: str,
    target_platform: str,
    *,
    shared_kickoff_decisions=None,
) -> Task:
    import sys

    base_description = (
        "아래 5블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 매니페스트 + "
        "처리 지시 + 매니저 노트)로 한국어 자원 매니페스트를 작성하세요. "
        "사용자가 자원을 안 준 항목은 placeholder 로 채우고 사후 교체 권고를 "
        "노트에 명시하세요.\n\n"
        f"[USER_REQUEST]\n{user_request}\n\n"
        f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
        f"[DESIGN_TOKENS]\n{design_tokens or '(없음 — Phase 4 GUI 분기 미사용)'}\n\n"
        f"[TARGET_PLATFORM]\n{target_platform}\n\n"
        f"[PROVIDED_ASSETS]\nnone   # 사용자 자원 미제공 — placeholder 처리\n"
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions, prior_agent_roles=()
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "YAML 매니페스트 + 처리 지시 + 매니저 노트 3단 구조. 마지막 줄 "
            "`Final Answer: assets — icons=N개, fonts=M개, images=I개, locales=L개, "
            "legal=L2개`."
        ),
        agent=agent,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = AssetManifestOutput
    return Task(**kwargs)


def _build_installer_creator_task(
    agent,
    target_platform: str,
    user_request: str,
    build_task: Task,
    asset_task: Task,
    *,
    shared_kickoff_decisions=None,
) -> Task:
    import sys

    base_description = (
        "이전 컨텍스트의 빌드 사양 + 자원 매니페스트 + 아래 3블록을 받아, "
        "백스토리에 명시된 4단 구조(도구 선택 / 인스톨러 스크립트 / 사용자 가이드 / "
        "노트)로 한국어 인스톨러 사양을 작성하세요. 코드 서명이 없으므로 SignTool "
        "절은 비활성 주석으로만 남기고, SmartScreen 우회 안내를 사용자 가이드에 "
        "포함하세요.\n\n"
        f"[TARGET_PLATFORM]\n{target_platform}\n\n"
        f"[APP_METADATA]\n사용자 요청: {user_request}\n"
        f"display_name·short_name·publisher 는 자원 매니페스트의 app_metadata 값 사용\n\n"
        f"[SIGNING_AVAILABLE]\nno\n"
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions,
        prior_agent_roles=["Build Engineer", "Asset Manager"],
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "4단 한국어 인스톨러 사양. 마지막 줄 `Final Answer: tool=<X>, "
            "output=<setup.exe|...>, est_size=<N>MB, signed=no`."
        ),
        agent=agent,
        context=[build_task, asset_task],
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = InstallerSpecOutput
    return Task(**kwargs)


def _build_platform_tester_task(
    agent,
    sandbox_summary: str,
    build_context_summary: str,
    *,
    shared_kickoff_decisions=None,
) -> Task:
    import sys

    base_description = (
        "아래는 Phase 3 의 결정론 sandbox(`run_python_package_in_sandbox`) "
        "산출물입니다. 진짜 .exe 검증이 아니라 **Engineer 산출 .py 코드의 부팅 "
        "smoke** 임을 인지하고, 백스토리에 명시된 5단 구조(종합 판정 / 출력 "
        "인용 / 근본 원인 / 재현·다음 단계 / 미관찰 영역)로 한국어 보고서를 "
        "작성하세요. **verdict 는 절대 뒤집지 마세요.**\n\n"
        f"--- PlatformTestResult (sandbox 결과 차용) ---\n{sandbox_summary}\n\n"
        f"[BUILD_CONTEXT]\n{build_context_summary}\n\n"
        "주의: 본 검증은 *.py 코드 실행* 이며, 실제 PyInstaller 빌드 산출 .exe 가 "
        "아닙니다. '미관찰 영역' 섹션에 이 한계를 반드시 명시하세요."
    )
    directive = format_kickoff_context_directive(
        shared_kickoff_decisions, prior_agent_roles=()
    )

    kwargs: dict = dict(
        description=base_description + directive,
        expected_output=(
            "5단 한국어 산출물 검증 보고서. 마지막 줄 `Final Answer: <verdict> "
            "(exit=<int>, startup=<X.X>s, elapsed=<X.X>s)`."
        ),
        agent=agent,
    )
    if "pytest" not in sys.modules:
        kwargs["output_pydantic"] = PlatformTestReportOutput
    return Task(**kwargs)


# ---------------------------------------------------------------------------
# 헬퍼 — _task_output_text 는 PR #29 부터 _common 에서 import
# ---------------------------------------------------------------------------


def _format_code_layout(code_files: list[Path]) -> str:
    """code_files 목록을 인간이 읽을 수 있는 트리 요약으로."""
    if not code_files:
        return "(코드 파일 없음)"
    lines = []
    for p in code_files[:30]:
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = p
        lines.append(f"- {rel.as_posix()}")
    if len(code_files) > 30:
        lines.append(f"  ... 외 {len(code_files) - 30}개")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v13 Phase 6.E P7 (PR #238) — web 프로젝트 감지 + web build 경로
#
# 배경 (P5 verdict, phase6e_rerun_P5_verdict_20260530.md): 시스템이 진짜 web BIM
# SPA(Three.js+web-ifc-three)를 산출해도, 빌드 체인이 `vite.config.ts`(TS 설정)를
# Python entry 로 골라 `python vite.config.ts` 실행 → SyntaxError → .exe SKIP. web 은
# `npm run build → dist/` 인데 체인은 PyInstaller→.exe 만 알았다. P7 = web 이면 npm
# build 로 라우팅, desktop(.py) 은 기존 PyInstaller 보존(회귀 0).
# ---------------------------------------------------------------------------
_WEB_MARKER_FILES: frozenset[str] = frozenset(
    {"package.json", "vite.config.ts", "vite.config.js", "tsconfig.json", "index.html"}
)
_WEB_MARKER_EXTS: frozenset[str] = frozenset({".ts", ".tsx", ".jsx"})
_DESKTOP_ENTRY_NAMES: tuple[str, ...] = (
    "app.py", "main.py", "__main__.py", "run.py", "entry.py",
)


def _is_web_project(code_files: list[Path], build_spec: str = "") -> bool:
    """code_files / Build Spec 으로 web(npm/vite) 프로젝트 여부 판정 (P7).

    web 마커: package.json / vite.config.* / tsconfig.json / index.html / .ts·.tsx·.jsx,
    또는 Build Spec 이 vite/npm run build/web-ifc-three 지정. 단 **non-test Python
    entry(app.py/main.py/__main__.py/run.py/entry.py)가 있으면 desktop/hybrid 로 보고
    web 라우팅 안 함** (PyInstaller 경로 보존 — 회귀 0).
    """
    if not code_files:
        # code_files 없이 Build Spec 만으로 판정 (T3 — Spec 존중)
        low = build_spec.lower()
        return any(k in low for k in ("vite", "npm run build", "web-ifc-three"))
    names = {p.name.lower() for p in code_files}
    has_marker = bool(names & _WEB_MARKER_FILES) or any(
        p.suffix.lower() in _WEB_MARKER_EXTS for p in code_files
    )
    if not has_marker and build_spec:
        low = build_spec.lower()
        has_marker = any(k in low for k in ("vite", "npm run build", "web-ifc-three"))
    if not has_marker:
        return False
    # desktop/hybrid 가드 — 진짜 Python entry 가 있으면 PyInstaller 경로 유지.
    for p in code_files:
        nm = p.name.lower()
        if nm.startswith("test_") or nm.endswith("_test.py"):
            continue
        if p.suffix.lower() == ".py" and any(nm.endswith(e) for e in _DESKTOP_ENTRY_NAMES):
            return False
    return True


def _default_npm_build_runner(code_dir: Path, timeout_sec: int) -> tuple[bool, str, float]:
    """실 npm 빌드 실행 — (ok, log, elapsed). npm 미설치/실패는 graceful (예외 X).

    ``npm ci`` (lockfile 없으면 ``npm install`` 폴백) → ``npm run build``. P7 default;
    테스트는 ``_run_web_build(npm_runner=...)`` 로 주입해 실 npm 호출 회피.
    """
    import shutil
    import time

    npm = shutil.which("npm")
    if npm is None:
        return False, "npm 미설치 — web build 불가 (node/npm 필요).", 0.0
    t0 = time.monotonic()
    try:
        inst = subprocess.run(
            [npm, "ci"], cwd=str(code_dir), capture_output=True, text=True,
            timeout=timeout_sec, encoding="utf-8", errors="replace",
        )
        if inst.returncode != 0:
            inst = subprocess.run(
                [npm, "install"], cwd=str(code_dir), capture_output=True, text=True,
                timeout=timeout_sec, encoding="utf-8", errors="replace",
            )
        bld = subprocess.run(
            [npm, "run", "build"], cwd=str(code_dir), capture_output=True, text=True,
            timeout=timeout_sec, encoding="utf-8", errors="replace",
        )
        elapsed = time.monotonic() - t0
        log = (
            (inst.stdout or "")[-1500:] + (inst.stderr or "")[-1500:]
            + (bld.stdout or "")[-3000:] + (bld.stderr or "")[-3000:]
        )
        return bld.returncode == 0, log, elapsed
    except Exception as exc:  # noqa: BLE001 — graceful
        return False, f"web build 예외: {exc!r}", 0.0


def _run_web_build(
    code_files: list[Path],
    workflow_dir: Path,
    build_spec: str = "",
    *,
    npm_runner=None,
    timeout_sec: int = 600,
) -> ExecuteResult:
    """web 프로젝트를 ``npm run build`` 로 빌드해 dist/ 산출을 ExecuteResult 로 반환 (P7).

    성공 기준 = ``dist/index.html`` 생성 (.exe 아님). 실패 시 web 전용 진단 메시지
    (PyInstaller/SyntaxError 오진 아님). ``npm_runner`` 주입 시 실 npm 회피(테스트).
    """
    import hashlib

    # v13 Phase 6.E P10b(i) — code_dir 를 추출 루트(workflow_dir/"code")로 고정.
    #   기존 ``code_files[0].parent`` 는 P10b(i) 서브트리(code/src/main.ts)에서 첫 파일이
    #   하위 디렉터리면 잘못된 빌드 디렉터리(code/src/)를 가리킬 수 있음. 추출은 항상
    #   workflow_dir/"code" 로 쓰므로 이 루트가 정답. (기존 테스트는 workflow_dir=tmp_path·
    #   파일 tmp_path/"code" 라 동일값 → 회귀 0.)
    code_dir = (workflow_dir / "code") if workflow_dir is not None else (
        code_files[0].parent if code_files else Path("code")
    )
    runner = npm_runner or _default_npm_build_runner
    ok, log, elapsed = runner(code_dir, timeout_sec)
    dist = code_dir / "dist"
    index = dist / "index.html"
    cmd = ["npm", "ci", "&&", "npm", "run", "build"]
    if ok and index.is_file():
        data = index.read_bytes()
        return ExecuteResult(
            success=True, exit_code=0, elapsed_sec=elapsed, command=cmd,
            exe_path=index, exe_size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            stdout=log[-4000:],
        )
    return ExecuteResult(
        success=False, exit_code=-8, elapsed_sec=elapsed, command=cmd,
        error_message=(
            "web build 실패 또는 dist/ 미생성. web 타겟은 PyInstaller(.exe) 가 아니라 "
            "`npm run build → dist/` 로 빌드됩니다 (P7). npm 미설치/빌드 에러 가능."
        ),
        stderr=log[-4000:],
    )


def _format_web_build_md(result: ExecuteResult) -> str:
    """web build ExecuteResult 를 25_executor_result.md 본문으로 직렬화 (P7)."""
    status = "✅ SUCCESS" if result.success else "🔴 FAILED"
    dist = f"`{result.exe_path}`" if result.exe_path else "(없음)"
    return (
        "## v13 Phase 6.E P7 (PR #238) — web build 결과 (npm run build → dist/)\n\n"
        "> web 프로젝트 감지 → PyInstaller(.exe) 경로 스킵, npm build 로 라우팅.\n\n"
        f"**상태**: {status}\n"
        f"**Exit Code**: `{result.exit_code}`\n"
        f"**산출 (dist)**: {dist}"
        + (f" ({result.exe_size_bytes} bytes)\n" if result.success else "\n")
        + (f"**에러**: {result.error_message}\n" if result.error_message else "")
        + f"\n```\n{(result.stdout or result.stderr or '')[-2000:]}\n```\n"
    )


def _select_entry_point(
    code_files: list[Path], entry_hint: str
) -> tuple[Optional[Path], str]:
    """Entry .py 파일 선택 + 선택 이유 반환 (PR #133 fixup #12 — test 파일 배제).

    배경 (사용자 라이브 검증 6회차, 2026-05-13):
        LLM 이 app.py + test_calculator.py 둘 다 생성 + 둘 다 __main__ block 보유.
        fixup #9 의 entry 휴리스틱이 test_calculator.py 채택 → 빈 .exe.

    우선순위:
        절대경로 entry_hint 가 직접 존재하면 무조건 사용 (호출 측 확신 escape hatch).
        그 외:
          PRIORITY 1: non-test 파일 중 __main__ block 보유 (entry_hint > name 휴리스틱 > 첫 파일)
          PRIORITY 2: non-test 파일 중 entry_hint 매칭
          PRIORITY 3: non-test 파일 중 name 휴리스틱
          PRIORITY 4: non-test 파일 중 첫 파일
          PRIORITY 5 (FALLBACK): test 파일 (다른 후보 전혀 없을 때만)

    Returns:
        (path, reason). reason 은 25_executor_result.md 감사 추적용.
        excluded test file 정보도 reason 끝에 포함.
    """
    if not code_files:
        return None, "no code_files provided"

    existing = [p for p in code_files if p.exists()]
    if not existing:
        return None, "no existing code_files"

    # 절대경로 entry_hint 가 직접 존재하면 모든 휴리스틱 무시 (호출 측 확신)
    if entry_hint:
        candidate = Path(entry_hint)
        if candidate.is_absolute() and candidate.exists():
            return candidate, f"explicit absolute entry_hint: {candidate}"

    hint_name = Path(entry_hint).name if entry_hint else ""

    # PR #133 fixup #12 — test 파일 분리
    non_test_files = [p for p in existing if not _is_test_file(p)]
    test_files = [p for p in existing if _is_test_file(p)]
    excluded_test_names = [p.name for p in test_files]
    excluded_suffix = (
        f" | excluded test files: {excluded_test_names}" if excluded_test_names else ""
    )

    NAME_PRIORITY = ['app.py', 'main.py', '__main__.py', 'run.py', 'entry.py']

    # ────────────────────────────────────────────────
    # PRIORITY 1: non-test 파일 중 __main__ block 보유
    # ────────────────────────────────────────────────
    non_test_main = [p for p in non_test_files if _has_main_block(p)]
    if non_test_main:
        # ①-a entry_hint 가 non_test_main 중 하나와 매칭
        if hint_name:
            for p in non_test_main:
                if p.name == hint_name:
                    return p, (
                        f"non-test + has __main__ block + matches entry_hint: {p.name}"
                        + excluded_suffix
                    )
        # ①-b 이름 휴리스틱
        files_by_name = {p.name.lower(): p for p in non_test_main}
        for name in NAME_PRIORITY:
            if name in files_by_name:
                return files_by_name[name], (
                    f"non-test + has __main__ block + name heuristic: {name}"
                    + excluded_suffix
                )
        # ①-c 첫 non_test_main
        return non_test_main[0], (
            f"non-test + has __main__ block (first of {len(non_test_main)})"
            + excluded_suffix
        )

    # ────────────────────────────────────────────────
    # PRIORITY 2: non-test entry_hint 매칭 (main block 없을 때)
    # ────────────────────────────────────────────────
    if hint_name:
        for p in non_test_files:
            if p.name == hint_name:
                return p, (
                    f"non-test + entry_hint match (no __main__ block): {p.name}"
                    + excluded_suffix
                )

    # ────────────────────────────────────────────────
    # PRIORITY 3: non-test name 휴리스틱
    # ────────────────────────────────────────────────
    files_by_name = {p.name.lower(): p for p in non_test_files}
    for name in NAME_PRIORITY:
        if name in files_by_name:
            return files_by_name[name], (
                f"non-test + name heuristic (no __main__ or hint match): {name}"
                + excluded_suffix
            )

    # ────────────────────────────────────────────────
    # PRIORITY 4: non-test 첫 파일
    # ────────────────────────────────────────────────
    if non_test_files:
        return non_test_files[0], (
            f"non-test + first file (no __main__ / hint / name match): {non_test_files[0].name}"
            + excluded_suffix
        )

    # ────────────────────────────────────────────────
    # PR #133 fixup #15 — FALLBACK 제거: test 파일만 있으면 build 거부.
    # 배경 (사용자 라이브 검증 5회차, 2026-05-14):
    #   LLM 이 test_clock_widget.py 만 (그것도 __main__ block 없이) 생성 →
    #   이전 FALLBACK 분기가 어쩔 수 없이 그걸로 .exe 빌드 → 더블클릭 시 즉시 종료
    #   (mainloop 없음 + test 코드는 unittest.main() 호출 안 함).
    #   사용자 PC 에 useless .exe 가 배포되는 것보다 명시적 build 실패가 훨씬 도움.
    # 처방: None 반환 → caller 가 build 중단 + 명확한 에러 메시지로 LLM 재생성 유도.
    # ────────────────────────────────────────────────
    return None, (
        f"⚠ no valid entry — only test files in code_files ({len(test_files)}). "
        f"LLM may have misunderstood the request (expected app entry, "
        f"got test scaffold). Test files: {[p.name for p in test_files]}"
    )


def _resolve_entry_path(code_files: list[Path], entry_hint: str) -> Optional[Path]:
    """Backward-compat wrapper — _select_entry_point 의 path 만 반환.

    Reason 도 필요하면 _select_entry_point 직접 호출.
    """
    path, _reason = _select_entry_point(code_files, entry_hint)
    return path


# ---------------------------------------------------------------------------
# PR #133 — Dependency Analyzer 보고서 파싱 + 빌드 직전 pip install (B안)
# ---------------------------------------------------------------------------
# 배경 (사용자 라이브 검증, 2026-05-12):
#   Dependency Analyzer LLM 이 ``direct_dependencies`` / ``hidden_imports`` 를
#   YAML 보고서로 정확히 산출하지만, 그 결과를 *markdown 파일에만 저장* 하고 빌드
#   파이프라인은 사용하지 않음. 결과:
#     - calculator.py 가 ``import customtkinter`` 인데 .venv 에 customtkinter 미설치
#     - PyInstaller 가 모듈 못 찾고 warning 만 띄운 채 빈 껍데기 .exe 생성
#     - 사용자 실행 시 ``ModuleNotFoundError: No module named 'customtkinter'``
# 처방 (PR #133):
#   ``execute_pyinstaller`` 호출 직전에 dependency_report 파싱 → 필요한 패키지를
#   현재 venv 에 ``pip install`` → ``hidden_imports`` 도 함께 전달. 자연어 →
#   .exe 풀체인 자동화의 핵심 끊어진 고리 복원.


# Build 도구 자체 / 표준 라이브러리는 pip install 대상에서 제외 (이미 설치되어 있음).
_BUILD_DEP_BLOCKLIST: set[str] = {
    'pyinstaller', 'pyinstaller_hooks_contrib',
    'pip', 'setuptools', 'wheel',
    'pytest', 'pytest_cov', 'pytest_mock',
    'crewai', 'langchain', 'langgraph',
    'pydantic', 'pydantic_core',
}


# PR #133 fixup #8 — 상호 배타 패키지 그룹.
# 같은 그룹에서 2개 이상 검출 시 1개만 채택 + 나머지는 PyInstaller --exclude-module.
# 배경 (사용자 라이브 검증, 2026-05-13):
#   LLM 보고서 + AST UNION 결과로 PySide6 + PyQt6 둘 다 direct_deps 에 포함 →
#   PyInstaller 가 "attempt to collect multiple Qt bindings packages" 로 abort.
_MUTEX_GROUPS: list[set[str]] = [
    {'PyQt5', 'PyQt6', 'PySide2', 'PySide6'},
    {'opencv-python', 'opencv-python-headless', 'opencv-contrib-python'},
    {'tensorflow', 'tensorflow-cpu', 'tensorflow-gpu'},
    {'protobuf', 'protobuf3'},
]

# 동률 시 우선순위 (높은 숫자 우선). AST 등장 횟수 동률일 때만 사용.
_MUTEX_PRIORITY: dict[str, int] = {
    # Qt: 신버전 우선 (PySide6 = official Qt for Python)
    'PySide6': 4, 'PyQt6': 3, 'PySide2': 2, 'PyQt5': 1,
    # OpenCV: 일반 빌드 우선 (headless 는 서버용)
    'opencv-python': 3, 'opencv-contrib-python': 2, 'opencv-python-headless': 1,
    # tensorflow: GPU > CPU > base
    'tensorflow-gpu': 3, 'tensorflow-cpu': 2, 'tensorflow': 1,
}


# PR #133 fixup #8 — PyInstaller --collect-all 화이트리스트.
# 기본 hook 가 약한 패키지만 --collect-all 적용. 그 외는 PyInstaller 내장 hook 에 위임.
# 배경:
#   PySide6/PyQt6/numpy/pandas/scipy 등은 PyInstaller 정교한 hook 보유 — 무차별
#   --collect-all 는 오히려 부작용 (예: PySide6.scripts.deploy_lib 가 'project_lib'
#   동적 import 시도 → "ModuleNotFoundError: No module named 'project_lib'" 경고).
_COLLECT_ALL_WHITELIST: set[str] = {
    'flet',            # Flutter 바이너리
    'customtkinter',   # theme JSON / 이미지 파일
    'dearpygui',       # C 확장 + 리소스
    'kivy',            # 많은 리소스 파일
    'pygame',          # C 라이브러리
    'ttkbootstrap',    # 테마 파일
    'pillow',          # 일부 codec plugin
}


# PR #133 fixup #10 — Multi-package 라이브러리의 runtime extras 매핑.
# 일부 패키지는 분할 구조 (예: flet 0.21+ 는 flet / flet-desktop / flet-web 로 분리).
# AST 스캔은 사용자 코드의 ``import flet`` 만 catch → flet-desktop 같은 transitive
# runtime dependency 는 자동 설치 안 됨 → .exe 가 ``ModuleNotFoundError: flet_desktop`` 으로 실패.
#
# 매핑 키: AST 가 검출하는 top-level import name (lowercase)
# 매핑 값: 추가로 필요한 pip 패키지 + PyInstaller --collect-all 대상 모듈명
#
# TODO: 매핑 항목이 많아지면 별도 yaml/json 파일로 분리 (사용자 PR 리뷰 제안).
@dataclass
class RuntimeExtras:
    """Multi-package 라이브러리의 추가 런타임 패키지."""
    pip_install: list[str]
    """pip install 인자에 추가할 패키지명 (dash 형식 — flet-desktop)."""
    collect_all: list[str]
    """PyInstaller --collect-all 인자에 추가할 모듈명 (underscore 형식 — flet_desktop)."""


_PACKAGE_RUNTIME_EXTRAS: dict[str, RuntimeExtras] = {
    # flet 0.21+ multi-package 분할:
    #   - flet (코어 API)
    #   - flet-desktop (Windows/Mac/Linux 데스크톱 런타임 — flet 내부에서 동적 import)
    #   - flet-web (웹 런타임, 옵션)
    # 사용자 라이브 검증 (2026-05-13): flet.app() 호출 시
    #   ``from flet_desktop import close_flet_view`` 가 .exe 에서 실패.
    'flet': RuntimeExtras(
        pip_install=['flet-desktop'],
        collect_all=['flet_desktop'],
    ),
    # 추후 발견되는 multi-package 라이브러리는 여기에 추가.
    # 예시 (검증되지 않음 — 발견 시 enable):
    #   'streamlit': RuntimeExtras(
    #       pip_install=['streamlit-extras'],
    #       collect_all=['streamlit_extras'],
    #   ),
}


def _parse_deps_from_report(dependency_report: str) -> tuple[list[str], list[str]]:
    """Dependency Analyzer 산출 markdown 에서 ``direct_dependencies`` + ``hidden_imports`` 추출.

    LLM 산출 형식 (``dependency_analyzer.py`` 산출 규약):
        ```yaml
        direct_dependencies:
          - name: pandas
            version: ">=2.0"
            source: requirements.txt
        hidden_imports:
          - module: customtkinter.windows.widgets.theme
            reason: ...
            severity: must
        ```

    LLM 변동성 흡수:
        - ```yaml``` 블록이 없으면 raw 텍스트에서 직접 추출 시도
        - PyYAML 파싱 실패 시 regex fallback
        - 패키지명만 반환 (version/source/reason 메타 무시)
        - stdlib / build 도구 자체 제외

    Returns:
        (direct_deps, hidden_imports) — 둘 다 빈 리스트 가능.
        각 항목은 pip install 인자로 직접 사용 가능한 패키지명.
    """
    if not dependency_report:
        return [], []

    direct_deps: list[str] = []
    hidden_imports: list[str] = []

    # ① ```yaml...``` 블록 추출 (있으면)
    yaml_block = ''
    m = re.search(r'```(?:yaml|yml)?\s*\n(.*?)\n```', dependency_report, re.DOTALL)
    if m:
        yaml_block = m.group(1)

    # ② PyYAML 파싱 (선호) — graceful: 실패 시 regex 로 fallback
    if yaml_block:
        try:
            import yaml as _yaml  # type: ignore
            data = _yaml.safe_load(yaml_block) or {}
            if isinstance(data, dict):
                for item in (data.get('direct_dependencies') or []):
                    if isinstance(item, dict):
                        name = item.get('name') or item.get('module') or item.get('package')
                        if name:
                            direct_deps.append(str(name).strip())
                    elif isinstance(item, str):
                        direct_deps.append(item.strip())
                for item in (data.get('hidden_imports') or []):
                    if isinstance(item, dict):
                        name = item.get('module') or item.get('name')
                        if name:
                            hidden_imports.append(str(name).strip())
                    elif isinstance(item, str):
                        hidden_imports.append(item.strip())
        except Exception:
            # YAML parse 실패 — regex fallback 사용 (아래)
            direct_deps = []
            hidden_imports = []

    # ③ regex fallback — YAML 블록이 없거나 파싱 실패한 경우 본문에서 직접 추출
    if not direct_deps and not hidden_imports:
        for section_key, target in (
            ('direct_dependencies', direct_deps),
            ('hidden_imports', hidden_imports),
        ):
            # 섹션 헤더부터 다음 헤더 또는 ``` 까지 캡처
            section_re = re.compile(
                rf'(?ms)^\s*{re.escape(section_key)}\s*:\s*\n(.+?)(?=\n\s*[A-Za-z_][\w_]*\s*:\s*\n|\n\s*```|\Z)'
            )
            sm = section_re.search(dependency_report)
            if not sm:
                continue
            body = sm.group(1)
            for line in body.splitlines():
                # ``- name: foo`` 또는 ``- module: foo``
                kv = re.match(r'\s*-\s+(?:name|module|package)\s*:\s*([^\s,#]+)', line)
                if kv:
                    pkg = kv.group(1).strip().strip('"\'')
                    if pkg:
                        target.append(pkg)
                    continue
                # 단순 ``- foo`` (메타 없는 한 줄 형식)
                simple = re.match(r'\s*-\s+([A-Za-z_][\w\-]*(?:\.[\w\-]+)*)\s*$', line)
                if simple:
                    pkg = simple.group(1).strip()
                    if pkg:
                        target.append(pkg)

    # ④ stdlib + build 도구 자체 제외 (direct_deps 에만 적용 — hidden_imports 는 stdlib 도 OK)
    stdlib = set(getattr(sys, 'stdlib_module_names', ()))  # Python 3.10+
    filtered_direct: list[str] = []
    for pkg in direct_deps:
        # 패키지명의 top-level 만 검사 (예: customtkinter.windows.widgets.theme → customtkinter)
        top = pkg.split('.')[0].split('[')[0].lower()
        if not top:
            continue
        if top in _BUILD_DEP_BLOCKLIST:
            continue
        if top in {s.lower() for s in stdlib}:
            continue
        filtered_direct.append(pkg)

    # dedupe (preserve order)
    direct_deps = list(dict.fromkeys(filtered_direct))
    hidden_imports = list(dict.fromkeys([h for h in hidden_imports if h]))

    return direct_deps, hidden_imports


def _scan_imports_from_py(entry_path: Path) -> list[str]:
    """Entry .py 의 top-level import 문 정적 스캔 → 외부 패키지명 추출 (PR #133 fixup #6 공용).

    AST walk 로 ``import X``, ``from X import Y`` 의 X 를 모두 수집 후 top-level
    (점 앞부분) 만 남김. stdlib + build 도구 제외.

    배경:
        PR #133 fixup #6 — Track A 의 LLM dependency_report 가 일부 패키지를
        빠뜨릴 수 있음 (예: flet 을 명시 안 함). entry .py 의 AST 스캔으로
        보완. Track B 는 이미 이 함수를 사용 중.

    Args:
        entry_path: 스캔할 .py 파일 경로.

    Returns:
        외부 패키지명 목록 (dedupe + stdlib 제외).
    """
    if not entry_path.exists():
        return []
    try:
        tree = ast.parse(entry_path.read_text(encoding='utf-8', errors='replace'))
    except (SyntaxError, ValueError):
        return []

    pkgs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                pkgs.append(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module:
                pkgs.append(node.module.split('.')[0])

    stdlib = set(getattr(sys, 'stdlib_module_names', ()))
    blocklist = {
        'pyinstaller', 'pip', 'setuptools', 'wheel',
        'pytest', 'pytest_cov', 'pytest_mock',
    }
    third_party = [
        p for p in pkgs
        if p
        and p not in stdlib
        and p.lower() not in blocklist
        and not p.startswith('_')
    ]
    return list(dict.fromkeys(third_party))


# Import name (Python module) → pip install name 매핑. PR #133 fixup #6:
# AST 스캔이 추출하는 건 import 이름이지만 pip install 은 패키지 이름이 다를 수 있음.
_IMPORT_TO_PIP_NAME: dict[str, str] = {
    'PIL': 'pillow',
    'cv2': 'opencv-python',
    'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4',
    'yaml': 'pyyaml',
    'OpenSSL': 'pyOpenSSL',
    'docx': 'python-docx',
    'pptx': 'python-pptx',
    'magic': 'python-magic',
    'dotenv': 'python-dotenv',
    'serial': 'pyserial',
    'win32com': 'pywin32',
    'win32api': 'pywin32',
}


def _normalize_pip_names(deps: list[str]) -> list[str]:
    """Import 이름을 pip install 이름으로 정규화 (PR #133 fixup #6).

    예: ``PIL`` → ``pillow``, ``cv2`` → ``opencv-python``.
    매핑 없는 패키지는 그대로 반환.
    """
    return [_IMPORT_TO_PIP_NAME.get(d, d) for d in deps]


@dataclass
class BuildDepsResolution:
    """PR #133 fixup #8 — 빌드 의존성 해상도 결과 (구조화).

    이전: _resolve_build_deps 가 (direct_deps, hidden_imports) 2-tuple 반환.
    문제: --collect-all 화이트리스트, mutex 제외 모듈 등 추가 정보가 caller 에 전달 안 됨.
    해결: 4개 필드를 가진 dataclass.
    """
    direct_deps_to_install: list[str]
    """pip install 인자. AST 스캔 ground truth (LLM 의 거짓 양성 차단)."""

    hidden_imports: list[str]
    """PyInstaller --hidden-import 인자. LLM 보고서의 hidden_imports 만."""

    collect_all_packages: list[str]
    """PyInstaller --collect-all 인자. direct_deps 중 화이트리스트에 속한 패키지만."""

    excluded_modules: list[str]
    """PyInstaller --exclude-module 인자. mutex group 의 비채택 패키지."""


def _count_import_occurrences(name: str, files: list[Path]) -> int:
    """주어진 top-level 패키지 이름이 files 의 AST import 에 몇 번 등장하는지 카운트.

    Mutex group 충돌 시 "AST 등장 횟수 더 많은 쪽" 채택 위한 헬퍼.
    """
    if not files:
        return 0
    target = name.split('.')[0].lower()
    count = 0
    for f in files:
        if not f.exists():
            continue
        try:
            tree = ast.parse(f.read_text(encoding='utf-8', errors='replace'))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0].lower() == target:
                        count += 1
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module and node.module.split('.')[0].lower() == target:
                    count += 1
    return count


def _resolve_mutex_groups(
    direct_deps: list[str],
    code_files: list[Path],
) -> tuple[list[str], list[str]]:
    """Mutex group 충돌 해소 — 1개 채택 + 나머지 제외 (PR #133 fixup #8).

    각 그룹에서 2개 이상 검출 시:
      ① AST 등장 횟수 더 많은 쪽 채택
      ② 동률 시 _MUTEX_PRIORITY 우선순위 적용

    Returns:
        (kept, excluded). kept 는 입력 순서 유지, excluded 는 --exclude-module 인자.
    """
    if not direct_deps:
        return [], []

    excluded: list[str] = []
    deps_set = set(direct_deps)

    for group in _MUTEX_GROUPS:
        in_group = [d for d in direct_deps if d in group]
        if len(in_group) <= 1:
            continue
        # AST 등장 횟수 계산
        counts = {d: _count_import_occurrences(d, code_files) for d in in_group}
        max_count = max(counts.values())
        candidates = [d for d, c in counts.items() if c == max_count]
        if len(candidates) == 1:
            winner = candidates[0]
        else:
            # priority table tiebreaker
            winner = max(candidates, key=lambda d: _MUTEX_PRIORITY.get(d, 0))
        for d in in_group:
            if d != winner:
                excluded.append(d)
                deps_set.discard(d)

    kept = [d for d in direct_deps if d in deps_set]
    return kept, excluded


_TEST_FILE_PATTERNS = [
    re.compile(r'^test_', re.IGNORECASE),
    re.compile(r'_test\.py$', re.IGNORECASE),
    re.compile(r'^tests_', re.IGNORECASE),
    re.compile(r'^conftest\.py$', re.IGNORECASE),
]


def _is_test_file(path: Path) -> bool:
    """파일명이 test 파일 패턴에 매칭되는지 (PR #133 fixup #12).

    배경 (사용자 라이브 검증 6회차, 2026-05-13):
        LLM 이 app.py + test_calculator.py 둘 다 생성 + 둘 다 __main__ block 보유.
        fixup #9 의 entry 선택 휴리스틱이 test_calculator.py 채택 → 빈 .exe.

    검출 패턴:
        ① test_*.py
        ② *_test.py
        ③ tests_*.py
        ④ conftest.py
        ⑤ TODO: pytest_*, setup.py 도 후보 (필요 시 추가)
    """
    name = path.name
    for pattern in _TEST_FILE_PATTERNS:
        if pattern.search(name):
            return True
    return False


def _has_main_block(path: Path) -> bool:
    """``if __name__ == '__main__':`` 블록이 .py 에 있는지 검사 (PR #133 fixup #8).

    Entry point 휴리스틱 — main block 가진 파일이 진짜 entry 일 가능성 큼.
    """
    if not path.exists():
        return False
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        # if __name__ == '__main__' or '__main__' == __name__
        for side in (test.left, *test.comparators):
            if isinstance(side, ast.Name) and side.id == '__name__':
                return True
    return False


def _collect_local_modules(
    entry_path: Optional[Path],
    code_files: Optional[list[Path]],
) -> set[str]:
    """code_files / entry 디렉토리에서 로컬 모듈명 수집 (PR #133 fixup #7).

    배경 (사용자 라이브 검증, 2026-05-13):
        LLM 이 calculator.py 안에서 ``from theme import COLORS`` 같은 로컬 import
        를 사용하면 AST 스캔이 ``theme`` 을 외부 pip 패키지로 오인 → pip install
        실패 → fail-fast 정상 작동하지만 진짜 외부 deps (flet 등) 까지 함께 차단.

    처방:
        같은 디렉토리의 ``.py`` 파일 + 하위 패키지 디렉토리 (``__init__.py`` 있거나
        ``.py`` 가 들어있는 디렉토리) 를 모두 local module 로 수집. 후속 필터에서
        외부 패키지 후보에서 제외.

    Returns:
        local module names (lowercase) 집합.
    """
    local_modules: set[str] = set()

    candidates: list[Path] = []
    if code_files:
        candidates.extend(code_files)
    if entry_path and entry_path not in candidates:
        candidates.append(entry_path)

    dirs_to_scan: set[Path] = set()
    for f in candidates:
        if not f.exists():
            continue
        dirs_to_scan.add(f.parent)
        # 파일명 자체 (확장자 제외) — __main__ / __init__ 등 dunder 제외
        stem = f.stem
        if stem and not stem.startswith('_'):
            local_modules.add(stem.lower())

    # 각 디렉토리 안의 .py 파일 + 하위 폴더 (패키지) 스캔
    for d in dirs_to_scan:
        try:
            for item in d.iterdir():
                if item.is_file() and item.suffix == '.py':
                    stem = item.stem
                    if stem and not stem.startswith('_'):
                        local_modules.add(stem.lower())
                elif item.is_dir():
                    name = item.name
                    if not name or name.startswith('.') or name.startswith('_'):
                        continue
                    # 패키지 (__init__.py 있음) → 명확히 local
                    if (item / '__init__.py').exists():
                        local_modules.add(name.lower())
                        continue
                    # __init__.py 없어도 .py 파일이 있으면 namespace 패키지로 취급
                    try:
                        has_py = any(
                            p.suffix == '.py' for p in item.iterdir() if p.is_file()
                        )
                        if has_py:
                            local_modules.add(name.lower())
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            continue

    return local_modules


def _filter_llm_hidden_imports(
    hidden_imports: list[str],
    entry_path: Optional[Path],
    code_files: Optional[list[Path]] = None,
) -> list[str]:
    """LLM advisory hidden_imports 노이즈 필터 (PR #133 fixup #11).

    배경 (사용자 라이브 검증 5회차, 2026-05-13):
        flet 앱 빌드에 LLM 이 PySide6.QtSvg, PySide6.QtPrintSupport, decimal 추천.
        - PySide6.* — flet 앱과 무관 (다른 GUI framework)
        - decimal — stdlib, PyInstaller 가 자동 처리
        무차별 ``--hidden-import`` 전달 시 .exe 비대화 + 가끔 충돌 위험.

    필터 정책:
        ① stdlib top-level 제외 (PyInstaller 가 자동 처리)
        ② 사용자 코드 AST 스캔으로 *실제 import 된* top-level 패키지 set 수집
        ③ LLM 추천 hidden_import 의 top-level 이 set 에 있는 경우만 통과
           (예: PySide6 가 코드에 없으면 PySide6.QtSvg 도 제외)

    Returns:
        검증된 hidden_imports (LLM 노이즈 제거됨).
    """
    if not hidden_imports:
        return []

    stdlib = set(getattr(sys, 'stdlib_module_names', ()))
    stdlib_lower = {s.lower() for s in stdlib}

    actual_imports: set[str] = set()
    if entry_path:
        for p in _scan_imports_from_py(entry_path):
            actual_imports.add(p.lower())
    if code_files:
        for f in code_files:
            if f.exists():
                for p in _scan_imports_from_py(f):
                    actual_imports.add(p.lower())

    filtered: list[str] = []
    for hi in hidden_imports:
        top = hi.split('.')[0].lower()
        if not top:
            continue
        if top in stdlib_lower:
            continue
        if top not in actual_imports:
            continue
        filtered.append(hi)
    return filtered


def _resolve_build_deps(
    dependency_report: str,
    entry_path: Optional[Path],
    code_files: Optional[list[Path]] = None,
) -> "BuildDepsResolution":
    """빌드 의존성 해상도 (PR #133 fixup #8 — AST primary + Mutex + Whitelist).

    배경 (사용자 라이브 검증, 2026-05-13):
        fixup #6 의 LLM + AST UNION 이 LLM 거짓 양성 흡수 → PySide6 + PyQt6
        동시 등장 → PyInstaller abort ("multiple Qt bindings packages").

    처방 (fixup #8):
        - direct_deps: **AST 스캔만** (LLM 의 direct_dependencies 는 신뢰 안 함)
        - hidden_imports: LLM 보고서의 hidden_imports 만 유지 (PyInstaller --hidden-import)
        - Mutex group: PyQt5/6 vs PySide2/6, opencv variants 등 1개만 채택
        - --collect-all 화이트리스트: flet/customtkinter 등만 (PyInstaller hook 약한 패키지)

    Args:
        dependency_report: LLM 산출 markdown. hidden_imports 추출용으로만 사용.
        entry_path: 빌드 entry .py.
        code_files: 전체 코드 파일 목록 (AST 스캔 대상 + local module 추출).

    Returns:
        BuildDepsResolution — direct_deps / hidden_imports / collect_all / excluded.
    """
    # 1) LLM 보고서에서 hidden_imports 만 추출 (direct_deps 는 버림)
    _llm_direct_discarded, hidden_imports_raw = _parse_deps_from_report(dependency_report)
    # PR #133 fixup #11 — LLM hidden_imports 노이즈 필터 (stdlib + unrelated framework)
    hidden_imports = _filter_llm_hidden_imports(hidden_imports_raw, entry_path, code_files)

    # 2) AST 스캔 — entry + code_files 의 모든 .py 의 top-level import
    scanned: list[str] = []
    if entry_path:
        scanned.extend(_scan_imports_from_py(entry_path))
    if code_files:
        for f in code_files:
            if f != entry_path and f.exists():
                scanned.extend(_scan_imports_from_py(f))

    # 3) 로컬 프로젝트 모듈 수집 (fixup #7) — theme.py / views.py 등 제외 위함
    local_modules = _collect_local_modules(entry_path, code_files)

    # 4) 필터 체인 — stdlib + blocklist + 로컬 모듈 + dunder/점 prefix 제외
    stdlib = set(getattr(sys, 'stdlib_module_names', ()))
    stdlib_lower = {s.lower() for s in stdlib}
    filtered: list[str] = []
    for pkg in scanned:
        top = pkg.split('.')[0].split('[')[0].lower()
        if not top:
            continue
        if top.startswith('_') or top.startswith('.'):
            continue
        if top in _BUILD_DEP_BLOCKLIST:
            continue
        if top in stdlib_lower:
            continue
        if top in local_modules:
            continue
        filtered.append(pkg)

    # 5) pip name 정규화 (PIL → pillow 등) + dedupe
    normalized = _normalize_pip_names(filtered)
    direct_deps = list(dict.fromkeys(normalized))

    # 6) Mutex group 충돌 해소 — 1개 채택 + 나머지 --exclude-module
    files_for_count = list(code_files) if code_files else []
    if entry_path and entry_path not in files_for_count:
        files_for_count.append(entry_path)
    direct_deps_resolved, excluded = _resolve_mutex_groups(direct_deps, files_for_count)

    # 7) PR #133 fixup #10 — multi-package runtime extras 확장 (flet → flet-desktop 등)
    extras_pip_added: list[str] = []
    extras_collect_added: list[str] = []
    for dep in list(direct_deps_resolved):
        extras = _PACKAGE_RUNTIME_EXTRAS.get(dep.lower())
        if not extras:
            continue
        for pip_extra in extras.pip_install:
            if pip_extra not in direct_deps_resolved and pip_extra not in extras_pip_added:
                extras_pip_added.append(pip_extra)
        for collect_extra in extras.collect_all:
            if collect_extra not in extras_collect_added:
                extras_collect_added.append(collect_extra)
    direct_deps_resolved = direct_deps_resolved + extras_pip_added

    # 8) --collect-all 화이트리스트 — direct_deps 중 명시된 것만 + extras 의 collect_all 추가
    collect_all = [d for d in direct_deps_resolved if d.lower() in _COLLECT_ALL_WHITELIST]
    # extras 의 collect_all 은 화이트리스트 무관 무조건 포함 (의도된 runtime 추가)
    for c in extras_collect_added:
        if c not in collect_all:
            collect_all.append(c)

    return BuildDepsResolution(
        direct_deps_to_install=direct_deps_resolved,
        hidden_imports=hidden_imports,
        collect_all_packages=collect_all,
        excluded_modules=excluded,
    )


def _extract_module_aliases(tree: ast.Module) -> dict[str, str]:
    """``import X``, ``import X as Y`` 의 alias 매핑 추출 (PR #133 fixup #14 helper).

    Returns:
        local_name → actual_module_name (예: {'ft': 'flet', 'np': 'numpy'}).
        ``from X import Y`` 는 처리 X (Y 가 module 가 아닐 수 있어 검증 불가).
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias_node in node.names:
                local_name = alias_node.asname or alias_node.name.split('.')[0]
                aliases[local_name] = alias_node.name
    return aliases


def _extract_attribute_chains(tree: ast.Module) -> list[tuple[str, ...]]:
    """모든 attribute access chain 추출 (PR #133 fixup #14 helper).

    AST 의 Attribute 노드를 walk:
        ``flet.colors.RED``  → ('flet', 'colors', 'RED')
        ``np.array.shape``    → ('np', 'array', 'shape')
        ``self.x.y``          → ('self', 'x', 'y')  (filter 단계에서 제거)
        ``f().attr``          → 시작이 Name 아님 → skip

    Returns:
        chain tuples list (각 chain 의 첫 element 는 Name).
    """
    chains: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain: list[str] = []
        curr: Optional[ast.AST] = node
        while isinstance(curr, ast.Attribute):
            chain.insert(0, curr.attr)
            curr = curr.value
        if isinstance(curr, ast.Name):
            chain.insert(0, curr.id)
            if len(chain) >= 2:
                chains.append(tuple(chain))
    return chains


def _validate_module_attributes(
    entry_path: Optional[Path],
    code_files: Optional[list[Path]] = None,
) -> tuple[bool, list[str]]:
    """LLM 코드의 attribute access 를 실제 설치된 모듈과 정적 검증 (PR #133 fixup #14).

    배경 (사용자 라이브 검증, 2026-05-13):
        LLM 이 ``flet.colors.XXX`` 사용 → 설치된 Flet 버전엔 ``colors`` 없음
        → .exe 가 사용자 PC 에서 AttributeError popup. fixup #11 의 subprocess
        validation 은 Flet 의 internal error handler 가 catch 해 popup 으로만
        표시하므로 못 잡음.

    처방:
        1) 모든 code file 의 ``import X`` / ``import X as Y`` alias 매핑 수집
        2) 모든 Attribute 노드의 chain 추출 (e.g., ``flet.colors.RED``)
        3) Chain top-level 이 import 된 module alias 인 경우만 검증
        4) importlib.import_module + walk hasattr/getattr → 누락 시 broken 추가

    *Conservative* — false positive 위험 최소화 (사용자 명시 요구사항):
        - top-level 이 import 된 module alias 가 아니면 skip
          (instance attr 'self.x.y' / 함수 결과 등은 검증 X)
        - module 이 import 안 되면 skip (local module / 미설치)
        - hasattr/getattr 중 예외 발생 시 valid 로 간주 (dynamic __getattr__ 등)
        - stdlib 자동 skip (PyInstaller 가 처리)

    Returns:
        (ok, broken_chains). ok=False 면 build 중단 권고 (사용자 PC 빈 .exe 회피).
    """
    import importlib
    import sys as _sys

    files: list[Path] = []
    if entry_path:
        files.append(entry_path)
    if code_files:
        for f in code_files:
            if f and f.exists() and f not in files:
                files.append(f)
    if not files:
        return True, []

    # ① import alias + attribute chain 수집 (모든 파일 합산)
    all_aliases: dict[str, str] = {}
    all_chains: list[tuple[str, ...]] = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding='utf-8', errors='replace'))
        except (SyntaxError, ValueError):
            continue
        all_aliases.update(_extract_module_aliases(tree))
        all_chains.extend(_extract_attribute_chains(tree))

    if not all_chains:
        return True, []

    # ② chains 를 import 된 module 별로 group
    stdlib = set(getattr(_sys, 'stdlib_module_names', ()))
    chains_by_module: dict[str, list[tuple[str, ...]]] = {}
    for chain in all_chains:
        top = chain[0]
        if top.startswith('_'):
            continue
        # 핵심 필터: top 이 import 된 module 의 alias 여야 함
        # (instance attr, 함수 결과 등은 정적 검증 불가 → 안전하게 skip)
        if top not in all_aliases:
            continue
        actual_module = all_aliases[top]
        actual_top = actual_module.split('.')[0]
        if actual_top in stdlib:
            continue
        chains_by_module.setdefault(actual_module, []).append(chain)

    if not chains_by_module:
        return True, []

    # ③ 각 module 의 chain 검증
    broken: list[str] = []
    for module_name, module_chains in chains_by_module.items():
        try:
            mod = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 — import 실패 = local module 또는 미설치 → skip
            continue
        seen_chains: set[str] = set()
        for chain in module_chains:
            obj = mod
            chain_so_far = chain[0]
            broken_here = False
            for attr in chain[1:]:
                chain_so_far = f"{chain_so_far}.{attr}"
                try:
                    has = hasattr(obj, attr)
                except Exception:  # noqa: BLE001 — dynamic __getattr__ 등 → valid 로 간주
                    has = True
                    break
                if not has:
                    broken_here = True
                    full_chain = '.'.join(chain)
                    if chain_so_far not in seen_chains:
                        seen_chains.add(chain_so_far)
                        broken.append(
                            f"'{module_name}' has no attribute path '{chain_so_far}' "
                            f"(used in code as '{full_chain}')"
                        )
                    break
                try:
                    obj = getattr(obj, attr)
                except Exception:  # noqa: BLE001
                    break
            if broken_here and len(broken) >= 20:
                # 너무 많은 broken chain 시 잘라냄 (UX)
                return False, broken

    return (len(broken) == 0), broken


def _pre_pyinstaller_validation(
    entry_path: Path,
    timeout_sec: int = 5,
) -> tuple[bool, str]:
    """Pre-PyInstaller validation — venv python 으로 entry .py 실행 → 코드 결함 사전 검출.

    배경 (사용자 라이브 검증 5회차, 2026-05-13):
        LLM 이 생성한 flet 앱 코드가 ``flet.controls.padding.symmetric(...)`` 호출.
        설치된 flet 버전에 해당 attribute 없음 → .exe 빌드는 성공하지만 런타임에
        AttributeError 다이얼로그. 빈 껍데기 .exe 양산. 패키징 레이어는 정상이나
        LLM 코드 자체가 결함.

    동작:
        - venv python (sys.executable) 으로 entry .py 실행
        - GUI 앱은 mainloop 가 timeout 까지 살아있음 (정상)
        - 코드 결함 시 timeout 전 exit + stderr 에 에러 메시지
        - 에러 패턴 (AttributeError / ImportError / SyntaxError / NameError 등) 검출

    Returns:
        (ok, log). ok=False → build 중단해야 함.
    """
    if not entry_path.exists():
        return True, "skipped: entry_path missing"
    if not Path(sys.executable).exists():
        return True, "skipped: sys.executable missing"

    try:
        proc = subprocess.run(
            [sys.executable, str(entry_path)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_sec,
            cwd=str(entry_path.parent),
        )
    except subprocess.TimeoutExpired:
        # Timeout = GUI mainloop 정상 실행 중 → OK
        return True, f"pre-build validation passed (mainloop running, timeout {timeout_sec}s)"
    except Exception as e:  # noqa: BLE001 — defensive
        return True, f"pre-build validation skipped (exception: {type(e).__name__}: {e})"

    stderr_tail = (proc.stderr or '')[-3000:]
    stdout_tail = (proc.stdout or '')[-500:]

    # 코드 결함 패턴 검출
    error_patterns = [
        'AttributeError', 'ImportError', 'ModuleNotFoundError',
        'NameError', 'SyntaxError', 'TypeError',
        'IndentationError', 'TabError',
        'Traceback (most recent call last)',
    ]
    for pattern in error_patterns:
        if pattern in stderr_tail:
            return False, (
                f"pre-build validation: 코드 자체 결함 감지 ({pattern}). "
                f"PyInstaller 호출해도 .exe 가 런타임 실패할 것이므로 build 중단.\n"
                f"stderr (마지막 3000자):\n{stderr_tail}"
            )

    # exit code 검사 — non-zero AND 명시적 error 없으면 일반 실패
    if proc.returncode != 0:
        return False, (
            f"pre-build validation: exit code {proc.returncode} (>0). "
            f"명시적 에러 패턴은 없으나 비정상 종료.\n"
            f"stderr:\n{stderr_tail}\nstdout:\n{stdout_tail}"
        )

    # exit code 0 — CLI 스크립트가 정상 완료 (예: Track B 의 데이터 처리 후 종료)
    return True, "pre-build validation passed (script completed cleanly, exit=0)"


def _install_dependencies_for_build(
    deps: list[str],
    timeout_sec: int = 180,
) -> tuple[bool, str]:
    """Build 직전에 ``pip install <deps>`` 호출 — PR #133 자연어 → .exe 자동화의 핵심 연결.

    현재 실행 중인 Python (sys.executable) 의 venv 에 직접 설치 — ``execute_pyinstaller``
    가 같은 venv 의 ``pyinstaller.exe`` 를 사용하므로 일관성 보장.

    graceful failure — 실패해도 예외 propagate 안 함. caller 가 결과 로깅 후 PyInstaller
    호출 계속 (워크플로 전체 실패 회피).

    Args:
        deps: 패키지명 목록 (``["customtkinter", "pillow"]`` 등). 빈 리스트면 즉시 success.
        timeout_sec: subprocess 타임아웃 (기본 180s = 3분).

    Returns:
        (success, log_message). log_message 는 인간이 읽을 수 있는 한 줄 요약.
    """
    if not deps:
        return True, "no deps to install"

    # 현재 venv 의 pip 경로 추정 (Windows: Scripts/pip.exe, *nix: bin/pip)
    pip_path = Path(sys.executable).parent / ("pip.exe" if sys.platform == "win32" else "pip")
    if pip_path.exists():
        cmd = [str(pip_path), "install", "--quiet", "--no-warn-script-location"] + deps
    else:
        # fallback: python -m pip (venv 의 pip stub 이 없는 경우)
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--no-warn-script-location"] + deps

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0:
            return True, f"pip install OK: {', '.join(deps)}"
        tail_err = (proc.stderr or proc.stdout or '')[-500:].strip()
        return False, f"pip install failed (exit={proc.returncode}): {tail_err}"
    except subprocess.TimeoutExpired:
        return False, f"pip install timeout ({timeout_sec}s) for: {', '.join(deps)}"
    except Exception as e:  # pragma: no cover — 방어망
        return False, f"pip install exception: {type(e).__name__}: {e}"


def _format_executor_result_md(result: ExecuteResult) -> str:
    """ExecuteResult → 25_executor_result.md 형식 markdown."""
    lines = ["# PyInstaller 실행 결과", "", f"**상태**: {'✅ SUCCESS' if result.success else '🔴 FAILED'}", ""]
    lines.append(f"**Exit Code**: `{result.exit_code}`")
    lines.append(f"**Elapsed**: {result.elapsed_sec:.2f}초")
    if result.exe_path:
        lines.append(f"**산출 파일**: `{result.exe_path}`")
    if result.exe_size_bytes is not None:
        lines.append(f"**크기**: {result.exe_size_bytes:,} bytes ({result.exe_size_bytes / (1024 * 1024):.2f} MB)")
    if result.sha256:
        lines.append(f"**SHA256**: `{result.sha256}`")
    if result.error_message:
        lines.append("")
        lines.append(f"**에러 메시지**: {result.error_message}")
    if result.command:
        lines.append("")
        lines.append("## 실행 명령")
        lines.append("```")
        lines.append(" ".join(result.command))
        lines.append("```")
    if result.stdout:
        lines.append("")
        lines.append("## stdout (tail)")
        lines.append("```")
        lines.append(result.stdout)
        lines.append("```")
    if result.stderr:
        lines.append("")
        lines.append("## stderr (tail)")
        lines.append("```")
        lines.append(result.stderr)
        lines.append("```")
    return "\n".join(lines) + "\n"


def _detect_entry_hint(code_files: list[Path]) -> str:
    """단순 휴리스틱 — 우선순위 키워드 매칭으로 entry 후보 1개 추정."""
    if not code_files:
        return "(미정)"
    for preferred in ("__main__.py", "cli.py", "main.py", "calculator.py"):
        for p in code_files:
            if p.name.endswith(preferred):
                try:
                    return p.relative_to(PROJECT_ROOT).as_posix()
                except ValueError:
                    return p.as_posix()
    # fallback — 첫 파일
    p = code_files[0]
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _maybe_run_sandbox(
    code_files: list[Path], timeout_sec: int
) -> tuple[Optional[PlatformTestResult], str]:
    """Phase 3 sandbox 활용해 코드 부팅 smoke 검증.

    Returns:
        (PlatformTestResult-like 또는 None, sandbox 직렬화 문자열)
        - None 이면 코드 부재 또는 entry 미탐지로 검증 skip.
        - 직렬화 문자열은 Platform Tester Agent task 에 주입.

    Note:
        SandboxResult 는 PlatformTestResult 와 다른 dataclass 지만, 두 클래스 모두
        verdict 필드(PASS/FAIL/TIMEOUT vs PASS/FAIL/CRASH/TIMEOUT)를 가져 narration
        Agent 에 직렬화하기엔 충분히 호환됨. format_platform_test_result_for_task 가
        받는 객체는 동등한 인터페이스만 필요.
    """
    if not code_files:
        return None, "(없음 — code_files 비었음)"

    # PR #133 fixup #13 — sandbox 단계 예외가 빌드 전체를 죽이지 않도록 wrap.
    # sandbox 는 *advisory* 검증이지 hard gate 아님. 실패해도 PyInstaller 호출은 계속.
    try:
        sb = run_python_package_in_sandbox(code_files, timeout_sec=timeout_sec)
    except Exception as e:  # noqa: BLE001
        return None, f"(sandbox 실행 중 예외 — graceful skip: {type(e).__name__}: {e})"
    if sb is None:
        return None, "(없음 — entry 파일 미탐지로 sandbox 실행 skip)"

    # SandboxResult → PlatformTestResult 와 거의 동일 인터페이스이므로, 직렬화 헬퍼는
    # platform_tester 의 것을 그대로 활용 가능 (필드명 일치 — exit_code, stdout,
    # stderr, elapsed_sec, timed_out, timeout_sec, verdict). 다만 startup_time_sec /
    # started_successfully 는 SandboxResult 에 없으므로 모킹.
    serialized = (
        f"verdict: {sb.verdict}\n"
        f"exit_code: {sb.exit_code}\n"
        f"startup_time_sec: (n/a — sandbox 모드)\n"
        f"elapsed_sec: {sb.elapsed_sec}\n"
        f"timeout_sec: {sb.timeout_sec}\n"
        f"timed_out: {sb.timed_out}\n"
        f"started_successfully: (n/a — sandbox 모드)\n"
        f"exe_path: (n/a — .py code, not .exe)\n"
        f"--- stdout ---\n{(sb.stdout or '(empty)').rstrip()}\n"
        f"--- stderr ---\n{(sb.stderr or '(empty)').rstrip()}\n"
    )
    # 호출 측이 sandbox_result 필드에 넣을 수 있도록 SandboxResult 그대로 반환은
    # 타입 mismatch (PlatformTestResult 가 아님) — None 으로 두고 직렬화 문자열만
    # 반환. BuildWorkflowResult.sandbox_result 필드는 PlatformTestResult 만 받게.
    return None, serialized


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_build_workflow(
    code_files: list[Path],
    user_request: str,
    *,
    target_platform: str = "windows",
    ui_spec: str = "",
    design_tokens: str = "",
    workflow_dir: Optional[Path] = None,
    enable_platform_test: bool = True,
    sandbox_timeout_sec: int = 30,
    enable_executor: bool = False,
    executor_timeout_sec: int = 300,
    verbose: bool = False,
    shared_kickoff_decisions=None,
) -> BuildWorkflowResult:
    """5-agent 빌드 사슬을 한 번에 실행. analyze_and_implement 산출 직후 호출 가정.

    Args:
        code_files: Engineer/GUI Code Generator 산출 .py 파일들 (
            보통 `WorkflowResult.saved_code_files`).
        user_request: 사용자 원 요청 (자원 매니페스트의 브랜드성 단서).
        target_platform: windows | macos | linux | cross-platform.
        ui_spec: UI/UX Analyst 산출 (Phase 4 활성 시). Asset Manager 입력에 활용.
        design_tokens: Theme Designer 산출 (Phase 4 활성 시). 동일.
        workflow_dir: 산출 파일 저장 디렉터리. None 이면 디스크 저장 skip.
        enable_platform_test: Platform Tester 단계 실행 여부. False 면 narration
            보고서가 "Platform Tester skip" 안내.
        sandbox_timeout_sec: Phase 3 sandbox 타임아웃.
        enable_executor: PR #36 — PyInstaller 실제 호출 활성. False (기본) 면
            backward compat. True + workflow_dir 제공 시 실 빌드 → ``.exe`` 산출 →
            SHA256. ``BuildWorkflowResult.executor_result`` 에 결과 채워짐.
        executor_timeout_sec: PyInstaller subprocess 타임아웃 (기본 300s = 5분).
        verbose: CrewAI 중간 로그.

    Returns:
        BuildWorkflowResult — 5개 에이전트 산출 + (선택) sandbox 결과.

    Raises:
        ValueError: code_files 가 비어 있고 enable_platform_test=True 일 때
            (Platform Tester 입력 부재 — 호출 의도가 명확하면 빈 list 도 허용해야
            하나, 현재 MVP 는 명시적 차단으로 호출 측 실수 방지).

    Note:
        본 워크플로우는 LLM 호출 5건 (Dep/Build/Asset/Installer/Platform) +
        선택적 subprocess 1건 (sandbox)을 수행. 토큰·시간 비용이 analyze_and_implement
        4건 + (Phase 4 GUI 6건) 위에 추가됨에 유의.
    """
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="build_workflow",
        user_id="local-dev",
        metadata={
            "phase": "phase_4_5_workflow",
            "workflow": "build_workflow",
            "target_platform": target_platform,
            "n_code_files": len(code_files),
            "enable_platform_test": enable_platform_test,
            "ui_spec_provided": bool(ui_spec),
            "design_tokens_provided": bool(design_tokens),
        },
    )

    try:
        code_summary = _format_code_layout(code_files)
        entry_hint = _detect_entry_hint(code_files)

        # 1~4: LLM 사양 산출 사슬 (CrewAI sequential)
        dep_agent = create_dependency_analyzer_agent(verbose=verbose)
        build_agent = create_build_engineer_agent(verbose=verbose)
        asset_agent = create_asset_manager_agent(verbose=verbose)
        installer_agent = create_installer_creator_agent(verbose=verbose)

        dep_task = _build_dependency_analyzer_task(
            dep_agent,
            code_summary,
            target_platform,
            shared_kickoff_decisions=shared_kickoff_decisions,
        )
        build_task = _build_build_engineer_task(
            build_agent,
            code_summary,
            target_platform,
            entry_hint,
            dep_task,
            shared_kickoff_decisions=shared_kickoff_decisions,
        )
        asset_task = _build_asset_manager_task(
            asset_agent,
            user_request,
            code_summary,
            design_tokens,
            target_platform,
            shared_kickoff_decisions=shared_kickoff_decisions,
        )
        installer_task = _build_installer_creator_task(
            installer_agent,
            target_platform,
            user_request,
            build_task,
            asset_task,
            shared_kickoff_decisions=shared_kickoff_decisions,
        )

        _build_chain_tasks = [dep_task, build_task, asset_task, installer_task]
        _build_chain_crew = Crew(
            agents=[dep_agent, build_agent, asset_agent, installer_agent],
            tasks=_build_chain_tasks,
            process=Process.sequential,
            verbose=verbose,
        )
        # 이슈 6 방어선 3 (PR #53) — ConverterError 시 output_pydantic 벗기고 1회 재시도
        kickoff_with_converter_rescue(_build_chain_crew, _build_chain_tasks)
        # 이슈 6 방어선 1 (PR #29) — LLM 본문 누락 자동 재시도 (Build 4 task)
        retry_short_tasks_in_chain(_build_chain_tasks)

        dependency_report = _task_output_text(dep_task)
        build_spec = _task_output_text(build_task)
        asset_manifest = _task_output_text(asset_task)
        installer_spec = _task_output_text(installer_task)

        # 5: Platform Tester (선택)
        sandbox_result: Optional[PlatformTestResult] = None
        platform_test_report = ""
        if enable_platform_test:
            _, sandbox_serialized = _maybe_run_sandbox(code_files, sandbox_timeout_sec)
            tester = create_platform_tester_agent(verbose=verbose)
            build_ctx = (
                f"target_platform={target_platform}, "
                f"n_code_files={len(code_files)}, "
                f"entry_hint={entry_hint}"
            )
            tester_task = _build_platform_tester_task(
                tester,
                sandbox_serialized,
                build_ctx,
                shared_kickoff_decisions=shared_kickoff_decisions,
            )
            _tester_crew = Crew(
                agents=[tester],
                tasks=[tester_task],
                process=Process.sequential,
                verbose=verbose,
            )
            # 이슈 6 방어선 3 (PR #53) — Platform Tester 가 어제 10차 E2E 3차에서 실패한 지점
            kickoff_with_converter_rescue(_tester_crew, [tester_task])
            # 이슈 6 방어선 1 (PR #29) — Platform Tester 단독 task 재시도
            retry_short_tasks_in_chain([tester_task])
            platform_test_report = _task_output_text(tester_task)
        else:
            platform_test_report = (
                "## 산출물 검증 보고서\n\n"
                "Platform Tester 가 enable_platform_test=False 로 skip 되었습니다.\n"
                "수동 검증 권고: `python src/tests/test_platform_tester_agent.py`.\n\n"
                "Final Answer: SKIPPED (enable_platform_test=False)"
            )

        # 산출 파일 저장
        saved: list[Path] = []
        if workflow_dir is not None:
            workflow_dir.mkdir(parents=True, exist_ok=True)
            for name, content in (
                ("20_dependency_report.md", dependency_report),
                ("21_build_spec.md", build_spec),
                ("22_asset_manifest.md", asset_manifest),
                ("23_installer_spec.md", installer_spec),
                ("24_platform_test_report.md", platform_test_report),
            ):
                path = workflow_dir / name
                path.write_text(content, encoding="utf-8")
                saved.append(path)

        # PR #36 — PyInstaller 실제 호출 (enable_executor=True 일 때만)
        # PR #133 — Dependency Analyzer 보고서 파싱 → pip install → hidden_imports 자동 주입
        # PR #133 fixup #6 — LLM 보고서 + entry AST 스캔 UNION + --collect-all + 실패 시 build 중단
        executor_result: Optional[ExecuteResult] = None
        entry_selection_reason = ""
        if enable_executor and code_files and workflow_dir is not None and _is_web_project(
            code_files, build_spec
        ):
            # ★ v13 Phase 6.E P7 (PR #238) — web 프로젝트 → npm build → dist/ 경로.
            # PyInstaller/python-entry 경로 자체를 스킵 (python 이 .ts 실행 → SyntaxError
            # → .exe SKIP 하던 P5 verdict 의 P7 병목 차단). desktop(.py) 은 아래 elif 보존.
            executor_result = _run_web_build(
                code_files, workflow_dir, build_spec, timeout_sec=executor_timeout_sec
            )
            _web_md = workflow_dir / "25_executor_result.md"
            _web_md.write_text(_format_web_build_md(executor_result), encoding="utf-8")
            saved.append(_web_md)
        elif enable_executor and code_files and workflow_dir is not None:
            # 기존 desktop(PyInstaller) 경로 — 회귀 0
            # PR #133 fixup #9/#15 — _select_entry_point 사용 + 선택 이유 캡처
            entry_path, entry_selection_reason = _select_entry_point(code_files, entry_hint)
            # PR #133 fixup #15 — entry_path 가 None 이면 build 중단 (test 파일만 있는 경우 등)
            if entry_path is None:
                executor_result = ExecuteResult(
                    success=False,
                    exit_code=-7,
                    elapsed_sec=0.0,
                    error_message=(
                        f"적합한 entry .py 파일 없음 — LLM 산출 코드 점검 필요.\n"
                        f"reason: {entry_selection_reason}\n\n"
                        f"가능한 원인:\n"
                        f"  - LLM 이 entry 파일 없이 test 파일만 생성\n"
                        f"  - 모든 파일에 ``if __name__ == '__main__':`` 블록 부재\n"
                        f"  - 자연어 요청이 모호하여 LLM 이 의도 못 파악\n"
                        f"권장 조치: 요청을 구체화 (예: \"GUI 계산기 — tkinter 사용, "
                        f"app.py 에 main entry\") 후 재실행."
                    ),
                )
                # 25_executor_result.md 저장 (사용자가 확인할 수 있도록)
                executor_md = workflow_dir / "25_executor_result.md"
                executor_md.write_text(
                    f"## PR #133 — entry 미탐지 (fixup #15)\n\n"
                    f"- Selected entry: None\n"
                    f"- Reason: {entry_selection_reason}\n\n"
                    f"---\n\n"
                    f"# PyInstaller 실행 결과\n\n"
                    f"**상태**: 🔴 SKIPPED (no valid entry)\n"
                    f"**Exit Code**: `-7`\n"
                    f"**Elapsed**: 0.00초\n\n"
                    f"**에러 메시지**: {executor_result.error_message}\n",
                    encoding="utf-8",
                )
                saved.append(executor_md)
            elif entry_path is not None:
                # fixup #16 (2026-05-26) — windowed 결정 강화.
                # 기존: ui_spec 의 substring "need_gui: yes" 만 (LLM 산출 의존 false
                #       negative 빈번 — Calculator.exe 가 console 빌드되어 cmd 창 표시 사고).
                # 신규: AST 기반 GUI 감지 (PR #210 의 _detect_gui_in_saved_files) +
                #       ui_spec substring 의 OR — 둘 중 하나라도 GUI 면 --windowed.
                #       AST 가 *실제 import 만* 검출 → false negative 차단.
                ast_gui = False
                try:
                    from src.workflows.iterative_loop import (
                        _detect_gui_in_saved_files,
                    )
                    ast_gui = _detect_gui_in_saved_files(code_files)
                except Exception:  # noqa: BLE001
                    pass
                ui_spec_gui = (
                    "need_gui: yes" in ui_spec or "need_gui=yes" in ui_spec
                )
                windowed = ast_gui or ui_spec_gui
                # 앱 이름은 entry 파일명 또는 user_request 단서 → 안전한 단순 휴리스틱
                app_name = entry_path.stem.title() or "App"

                # PR #133 fixup #8 — AST primary + Mutex + Whitelist 구조화 결과
                build_deps = _resolve_build_deps(
                    dependency_report, entry_path, code_files
                )
                pip_log = "deps=0 (no install needed)"
                pip_ok = True
                pre_log = "not run (pip 단계 차단)"
                if build_deps.direct_deps_to_install:
                    pip_ok, pip_log = _install_dependencies_for_build(
                        build_deps.direct_deps_to_install
                    )

                if not pip_ok:
                    # pip install 실패 → PyInstaller 호출 중단 (fixup #6).
                    executor_result = ExecuteResult(
                        success=False,
                        exit_code=-4,
                        elapsed_sec=0.0,
                        error_message=(
                            f"필수 의존성 pip install 실패 — PyInstaller 호출 중단. "
                            f"누락된 패키지를 .exe 가 런타임에 못 찾으므로 빌드 무의미. "
                            f"실패 로그: {pip_log}"
                        ),
                    )
                else:
                    # PR #133 fixup #11 — pre-PyInstaller validation
                    # 코드 자체 결함 (AttributeError 등) 사전 검출 → 빈 껍데기 .exe 양산 차단
                    pre_ok, pre_log = _pre_pyinstaller_validation(entry_path)
                    # PR #133 fixup #14 — 정적 attribute 검증 (subprocess 가 못 잡는 deferred error)
                    attr_ok, attr_broken = (True, [])
                    if pre_ok:
                        attr_ok, attr_broken = _validate_module_attributes(entry_path, code_files)
                    if not pre_ok:
                        executor_result = ExecuteResult(
                            success=False,
                            exit_code=-5,
                            elapsed_sec=0.0,
                            error_message=(
                                f"Pre-PyInstaller validation 실패 — 코드 자체 결함이 "
                                f"있어 PyInstaller 호출해도 .exe 가 런타임 실패할 것. "
                                f"build 중단.\n\n{pre_log}"
                            ),
                        )
                    elif not attr_ok:
                        # PR #133 fixup #14 — Flet 처럼 internal error handler 가 catch 하는
                        # 케이스. subprocess 는 exit 0 로 종료하지만 LLM 코드는 broken.
                        executor_result = ExecuteResult(
                            success=False,
                            exit_code=-6,
                            elapsed_sec=0.0,
                            error_message=(
                                f"정적 attribute 검증 실패 — LLM 코드가 설치된 모듈의 "
                                f"존재하지 않는 attribute 를 사용. .exe 빌드해도 사용자 PC "
                                f"에서 AttributeError popup 발생할 것이므로 build 중단.\n"
                                f"누락 attribute 체인 ({len(attr_broken)}개):\n  "
                                + "\n  ".join(attr_broken[:10])
                            ),
                        )
                    else:
                        executor_result = execute_pyinstaller(
                            entry_path=entry_path,
                            output_dir=workflow_dir / "build_output",
                            app_name=app_name,
                            windowed=windowed,
                            onefile=True,
                            hidden_imports=build_deps.hidden_imports or None,
                            # fixup #8 — 화이트리스트의 패키지만 --collect-all
                            collect_all=build_deps.collect_all_packages or None,
                            # fixup #8 — mutex group 비채택 패키지 차단
                            exclude_modules=build_deps.excluded_modules or None,
                            timeout_sec=executor_timeout_sec,
                        )
                        # 2026-05-26 fixup #16 — windowed bootloader 검증.
                        # PyInstaller stdout 의 "Bootloader ...runw.exe" / "run.exe"
                        # 패턴 검색. windowed=True 인데 console bootloader 가 잡힌
                        # 경우 — 5번째 시도 사고 (Calculator.exe 에 cmd 창) 처방.
                        validation_log = _validate_windowed_bootloader(
                            executor_result, expected_windowed=windowed
                        )
                        if validation_log:
                            executor_result.stderr = validation_log + (
                                executor_result.stderr or ""
                            )

                        # 2026-05-26 — PM 명시 (4회 BLOCKED 사고 처방): GUI 앱
                        # (windowed=True) 빌드 성공 시 *.exe smoke test* 자동 실행.
                        # theme.py 같은 entry 오선택 사례를 빌드 직후 자동 검출.
                        # 결과는 executor_result.stderr 에 prepend 하여 사용자 가시.
                        if (
                            windowed
                            and executor_result.success
                            and executor_result.exe_path is not None
                        ):
                            try:
                                from src.agents.build_release.build_executor import (
                                    run_exe_smoke_test,
                                )
                                smoke = run_exe_smoke_test(executor_result.exe_path)
                                smoke_log = (
                                    f"[EXE_SMOKE_TEST] {'PASS' if smoke.passed else 'FAIL'} — "
                                    f"{smoke.reason}\n"
                                )
                                # stderr 에 prepend — 25_executor_result.md 에 표시됨
                                executor_result.stderr = smoke_log + (
                                    executor_result.stderr or ""
                                )
                            except Exception as exc:  # noqa: BLE001
                                executor_result.stderr = (
                                    f"[EXE_SMOKE_TEST] 실행 helper 호출 실패: {exc!r}\n"
                                ) + (executor_result.stderr or "")
                # 25_executor_result.md 저장 — 사용자 가시 산출물
                executor_md = workflow_dir / "25_executor_result.md"
                executor_md_body = _format_executor_result_md(executor_result)
                pr133_header = (
                    "## PR #133 — 의존성 자동 설치 결과 (fixup #11: pre-validation + LLM hidden_imports 필터 + multi-package extras)\n\n"
                    f"- Selected entry: `{entry_path.name}` (reason: {entry_selection_reason})\n"
                    f"- direct_dependencies (AST + extras): {len(build_deps.direct_deps_to_install)}개 "
                    f"({', '.join(build_deps.direct_deps_to_install) if build_deps.direct_deps_to_install else '없음'})\n"
                    f"- hidden_imports (LLM, filtered): {len(build_deps.hidden_imports)}개 "
                    f"({', '.join(build_deps.hidden_imports) if build_deps.hidden_imports else '없음'})\n"
                    f"- pip install: {pip_log}\n"
                    f"- pre-PyInstaller validation: {pre_log}\n"
                    f"- PyInstaller --collect-all: {len(build_deps.collect_all_packages)}개 "
                    f"({', '.join(build_deps.collect_all_packages) if build_deps.collect_all_packages else '없음'})\n"
                    f"- PyInstaller --exclude-module (mutex): {len(build_deps.excluded_modules)}개 "
                    f"({', '.join(build_deps.excluded_modules) if build_deps.excluded_modules else '없음'})\n\n"
                    "---\n\n"
                )
                executor_md.write_text(
                    pr133_header + executor_md_body,
                    encoding="utf-8",
                )
                saved.append(executor_md)

        return BuildWorkflowResult(
            dependency_report=dependency_report,
            build_spec=build_spec,
            asset_manifest=asset_manifest,
            installer_spec=installer_spec,
            platform_test_report=platform_test_report,
            sandbox_result=sandbox_result,
            saved_files=saved,
            target_platform=target_platform,
            executor_result=executor_result,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
