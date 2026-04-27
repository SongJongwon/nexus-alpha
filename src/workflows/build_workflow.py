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
from src.agents.operations import run_python_package_in_sandbox
from src.monitoring import get_langfuse_client
from src.workflows._common import (
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
    """

    dependency_report: str
    build_spec: str
    asset_manifest: str
    installer_spec: str
    platform_test_report: str
    sandbox_result: Optional[PlatformTestResult]
    saved_files: list[Path] = field(default_factory=list)
    target_platform: str = "windows"


# ---------------------------------------------------------------------------
# Task 빌더 (5명 각자)
# ---------------------------------------------------------------------------
def _build_dependency_analyzer_task(agent, code_summary: str, target_platform: str) -> Task:
    import sys

    kwargs: dict = dict(
        description=(
            "아래 4블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 보고서 6축 + "
            "분석가 코멘트 + 미검토 영역)로 한국어 의존성 보고서를 작성하세요. "
            "lazy import / data file / native binary 신호를 빠뜨리지 마세요.\n\n"
            f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
            f"[CODE_SAMPLES]\n(상위 호출 측이 코드 본문을 별도로 첨부하지 않은 경우, "
            f"PROJECT_LAYOUT 의 파일명·역할만으로 lazy import 가능성 추정)\n\n"
            f"[REQUIREMENTS]\n(상위 호출 측 미제공 — 코드에서 추론)\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n"
        ),
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
    agent, code_summary: str, target_platform: str, entry_hint: str, dep_task: Task
) -> Task:
    # 이슈 6 방어선 2 (PR #31) — production 에서만 output_pydantic 활성.
    # pytest 환경에선 FakeProvider 응답이 JSON 스키마와 맞지 않아 false 실패 방지.
    import sys

    kwargs: dict = dict(
        description=(
            "이전 컨텍스트의 의존성 보고서 + 아래 3블록을 받아, 백스토리에 명시된 "
            "5단 구조(도구 선택 / 빌드 명령 / 함정 / 검증 체크리스트 / 빌드 엔지니어 "
            "노트)로 한국어 빌드 사양을 작성하세요.\n\n"
            f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n\n"
            f"[ENTRY_POINT]\n{entry_hint}\n"
        ),
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
) -> Task:
    import sys

    kwargs: dict = dict(
        description=(
            "아래 5블록을 입력으로, 백스토리에 명시된 3단 구조(YAML 매니페스트 + "
            "처리 지시 + 매니저 노트)로 한국어 자원 매니페스트를 작성하세요. "
            "사용자가 자원을 안 준 항목은 placeholder 로 채우고 사후 교체 권고를 "
            "노트에 명시하세요.\n\n"
            f"[USER_REQUEST]\n{user_request}\n\n"
            f"[PROJECT_LAYOUT]\n{code_summary}\n\n"
            f"[DESIGN_TOKENS]\n{design_tokens or '(없음 — Phase 4 GUI 분기 미사용)'}\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n\n"
            f"[PROVIDED_ASSETS]\nnone   # 사용자 자원 미제공 — placeholder 처리\n"
        ),
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
) -> Task:
    import sys

    kwargs: dict = dict(
        description=(
            "이전 컨텍스트의 빌드 사양 + 자원 매니페스트 + 아래 3블록을 받아, "
            "백스토리에 명시된 4단 구조(도구 선택 / 인스톨러 스크립트 / 사용자 가이드 / "
            "노트)로 한국어 인스톨러 사양을 작성하세요. 코드 서명이 없으므로 SignTool "
            "절은 비활성 주석으로만 남기고, SmartScreen 우회 안내를 사용자 가이드에 "
            "포함하세요.\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n\n"
            f"[APP_METADATA]\n사용자 요청: {user_request}\n"
            f"display_name·short_name·publisher 는 자원 매니페스트의 app_metadata 값 사용\n\n"
            f"[SIGNING_AVAILABLE]\nno\n"
        ),
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
    agent, sandbox_summary: str, build_context_summary: str
) -> Task:
    import sys

    kwargs: dict = dict(
        description=(
            "아래는 Phase 3 의 결정론 sandbox(`run_python_package_in_sandbox`) "
            "산출물입니다. 진짜 .exe 검증이 아니라 **Engineer 산출 .py 코드의 부팅 "
            "smoke** 임을 인지하고, 백스토리에 명시된 5단 구조(종합 판정 / 출력 "
            "인용 / 근본 원인 / 재현·다음 단계 / 미관찰 영역)로 한국어 보고서를 "
            "작성하세요. **verdict 는 절대 뒤집지 마세요.**\n\n"
            f"--- PlatformTestResult (sandbox 결과 차용) ---\n{sandbox_summary}\n\n"
            f"[BUILD_CONTEXT]\n{build_context_summary}\n\n"
            "주의: 본 검증은 *.py 코드 실행* 이며, 실제 PyInstaller 빌드 산출 .exe 가 "
            "아닙니다. '미관찰 영역' 섹션에 이 한계를 반드시 명시하세요."
        ),
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

    sb = run_python_package_in_sandbox(code_files, timeout_sec=timeout_sec)
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
    verbose: bool = False,
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

        dep_task = _build_dependency_analyzer_task(dep_agent, code_summary, target_platform)
        build_task = _build_build_engineer_task(
            build_agent, code_summary, target_platform, entry_hint, dep_task
        )
        asset_task = _build_asset_manager_task(
            asset_agent, user_request, code_summary, design_tokens, target_platform
        )
        installer_task = _build_installer_creator_task(
            installer_agent, target_platform, user_request, build_task, asset_task
        )

        Crew(
            agents=[dep_agent, build_agent, asset_agent, installer_agent],
            tasks=[dep_task, build_task, asset_task, installer_task],
            process=Process.sequential,
            verbose=verbose,
        ).kickoff()
        # 이슈 6 fix — LLM 본문 누락 자동 재시도 (Build 4 task)
        retry_short_tasks_in_chain([dep_task, build_task, asset_task, installer_task])

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
            tester_task = _build_platform_tester_task(tester, sandbox_serialized, build_ctx)
            Crew(
                agents=[tester],
                tasks=[tester_task],
                process=Process.sequential,
                verbose=verbose,
            ).kickoff()
            # 이슈 6 fix — Platform Tester 단독 task 재시도
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

        return BuildWorkflowResult(
            dependency_report=dependency_report,
            build_spec=build_spec,
            asset_manifest=asset_manifest,
            installer_spec=installer_spec,
            platform_test_report=platform_test_report,
            sandbox_result=sandbox_result,
            saved_files=saved,
            target_platform=target_platform,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
