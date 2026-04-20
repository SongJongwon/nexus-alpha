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

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

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
from src.agents.qa import create_code_reviewer_agent
from src.monitoring import get_langfuse_client


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


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------
def _task_output_text(task: Task) -> str:
    """CrewAI Task의 출력을 안전하게 문자열로 꺼낸다(버전별 속성 차이 대응)."""
    out = task.output
    if out is None:
        return ""
    return getattr(out, "raw", None) or str(out)


def _extract_code_blocks(markdown: str, code_dir: Path) -> list[Path]:
    """```python 블록을 추출해 `code_dir` 아래에 파일로 저장한다.

    블록 첫 줄에 `# file: <상대경로>` 헤더 주석이 있으면 해당 이름을 사용하고,
    없으면 `block01.py`, `block02.py` 순으로 자동 번호를 매긴다.
    """
    code_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
    saved: list[Path] = []
    for idx, block in enumerate(pattern.findall(markdown), start=1):
        first_line = block.splitlines()[0] if block.strip() else ""
        name_match = re.match(r"#\s*file:\s*(\S+\.py)", first_line)
        if name_match:
            safe_name = (
                name_match.group(1).replace("/", "__").replace("\\", "__")
            )
            file_path = code_dir / safe_name
        else:
            file_path = code_dir / f"block{idx:02d}.py"
        file_path.write_text(block, encoding="utf-8")
        saved.append(file_path)
    return saved


def _parse_ui_ux_path(ui_ux_markdown: str) -> str:
    """UI/UX Analyst 산출 마크다운에서 `need_gui` 를 파싱해 경로 문자열 반환.

    파싱 우선순위:
        1. 마지막 `Final Answer:` 줄에서 `need_gui=yes/no` 검색
        2. `need_gui: yes` / `need_gui: no` (YAML 본문)
        3. 둘 다 못 찾으면 `cli` 로 안전 fallback
           (모호 시 GUI 오버헤드 회피 — 디자인 본부 3명 호출 비용 큼)

    Returns:
        "gui" | "cli"
    """
    text = (ui_ux_markdown or "").lower()

    # Final Answer 줄 우선 (가장 신뢰)
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("final answer"):
            if "need_gui=yes" in s or "need_gui: yes" in s:
                return "gui"
            if "need_gui=no" in s or "need_gui: no" in s:
                return "cli"

    # YAML 본문 fallback
    if "need_gui: yes" in text:
        return "gui"
    if "need_gui: no" in text:
        return "cli"

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
    """Python Engineer 구현 Task (기존 4-agent 흐름)."""
    return Task(
        description=(
            "CTO의 전략 문서와 Data Analyst의 분석 지시서(이전 컨텍스트)를 모두 "
            "만족하는 **바로 실행 가능한 Python 구현 산출물**을 작성하세요.\n\n"
            "요구 사항:\n"
            "  - 모듈별 파일 분리 (loader / transform / metrics / chart / "
            "    render / cli 등 역할 단위)\n"
            "  - 모든 공개 함수에 타입 힌트와 docstring\n"
            "  - 최소 3건의 pytest 단위 테스트 (지표 계산 함수 중심)\n"
            "  - CLI 엔트리 포함 (`python -m <pkg> --input ... --output ...`)\n"
            "  - 경계 지점(I/O, CLI)에만 예외 처리, 내부 함수는 계약 신뢰\n\n"
            "산출 규약:\n"
            "  - 각 파일은 ```python 코드 블록으로 감싸고 첫 줄에 `# file: "
            "    <상대경로>` 헤더 주석 포함\n"
            "  - 마지막 섹션에 설치·실행 방법과 예시 커맨드 요약"
        ),
        expected_output=(
            "모듈별 실행 가능한 Python 코드 세트와 pytest 테스트, 설치·실행 가이드를 "
            "포함한 완전한 구현 산출물"
        ),
        agent=engineer,
        context=[cto_task, analyst_task],
    )


def _build_qa_task(reviewer, code_task: Task) -> Task:
    """Code Reviewer Task — code_task (Engineer 또는 GUI Code Generator) 컨텍스트로."""
    return Task(
        description=(
            "이전 컨텍스트의 코드 산출물을 백스토리에 명시된 다섯 가지 정적 점검 "
            "항목 — 타입 힌트 / docstring / pytest 실행 가능성 / 경계 예외 처리 / "
            "모듈 분리 — 으로 점검하고, **5단 구조(종합 판정 / 항목별 결과표 / "
            "발견된 이슈 / 권장 보정 / 미검토 영역)** 의 한국어 마크다운 리뷰 "
            "보고서를 작성하세요.\n\n"
            "유의 사항:\n"
            "  - 코드를 실행하지 않습니다(정적 점검 전담).\n"
            "  - 발견 사항은 (파일:라인 — 인용 — 원칙 — 보정안) 형식으로 적습니다.\n"
            "  - 마지막 줄은 반드시 `Final Answer:` 로 시작하는 한 줄 종합 "
            "    판정(APPROVED / NEEDS_REVISION)이어야 합니다."
        ),
        expected_output=(
            "5단 구조의 한국어 리뷰 보고서. 마지막 줄에 `Final Answer:`로 시작하는 "
            "종합 판정(APPROVED 또는 NEEDS_REVISION) 포함."
        ),
        agent=reviewer,
        context=[code_task],
    )


# ---------------------------------------------------------------------------
# Phase 4 GUI 분기 Task 빌더
# ---------------------------------------------------------------------------
def _build_uiux_task(user_request: str, ui_ux) -> Task:
    """UI/UX Analyst Task — Phase 4 활성 시 첫 단계."""
    return Task(
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


def _build_gui_designer_task(designer, uiux_task: Task) -> Task:
    """GUI Designer Task — UI/UX 산출 ui_spec 을 컨텍스트로."""
    return Task(
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


def _build_theme_task(theme, uiux_task: Task, designer_task: Task) -> Task:
    """Theme Designer Task — ui_spec + GUI 설계를 컨텍스트로."""
    return Task(
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


def _build_gui_code_gen_task(
    coder, uiux_task: Task, designer_task: Task, theme_task: Task
) -> Task:
    """GUI Code Generator Task — 셋 모두 컨텍스트로."""
    return Task(
        description=(
            "이전 컨텍스트의 ui_spec + GUI 설계 + 디자인 토큰을 모두 만족하는 "
            "**바로 실행 가능한 Python GUI 코드** 를 백스토리에 명시된 4단 구조"
            "(프레임워크 선택 + 코드 + 실행 방법 + 작성자 노트)로 작성하세요. "
            "각 파일은 ```python 블록 + `# file:` 헤더 포함."
        ),
        expected_output=(
            "프레임워크 선택 근거 + Python GUI 코드(파일 여러 개) + 실행 방법 + "
            "작성자 노트. 마지막 줄 `Final Answer: framework=..., files=N개, entry=...`."
        ),
        agent=coder,
        context=[uiux_task, designer_task, theme_task],
    )


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
) -> list[Path]:
    """기존 4-agent 산출물 저장 (00~04 + code/). 반환은 추출된 .py 파일 목록."""
    (workflow_dir / "00_user_request.txt").write_text(user_request, encoding="utf-8")
    (workflow_dir / "01_cto_strategy.md").write_text(cto_strategy, encoding="utf-8")
    (workflow_dir / "02_analyst_brief.md").write_text(analyst_brief, encoding="utf-8")
    (workflow_dir / "03_engineer_output.md").write_text(engineer_output, encoding="utf-8")
    (workflow_dir / "04_qa_review.md").write_text(qa_review, encoding="utf-8")
    return _extract_code_blocks(engineer_output, workflow_dir / "code")


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

    Returns:
        `WorkflowResult` — 신규 Phase 4/4.5 필드는 각 토글 비활성 시 빈 문자열.

    Raises:
        RuntimeError: Provider 초기화 등 체인 중간 장애가 발생했을 때 호출 측에서
            명확히 포착할 수 있도록 원본 예외를 그대로 전파한다.

    Phase 4.5 한계 (build branch):
        실제 PyInstaller 호출·setup.exe 빌드는 외부 도구 의존이라 통합하지 않음.
        본 토글은 *사양 산출만* (LLM 5건). Platform Tester 는 Phase 3 sandbox 의
        `run_python_package_in_sandbox` 결과를 narration 입력으로 활용.
    """
    target_outputs_dir = outputs_dir if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
    target_outputs_dir.mkdir(parents=True, exist_ok=True)

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="analyze_and_implement",
        user_id="local-dev",
        metadata={
            "phase": "phase_4_5" if enable_build_branch else ("phase_4" if enable_gui_branch else "phase_1"),
            "workflow": "analyze_and_implement",
            "user_request_preview": user_request[:160],
            "enable_gui_branch": enable_gui_branch,
            "enable_build_branch": enable_build_branch,
            "target_platform": target_platform if enable_build_branch else None,
        },
    )

    try:
        # 산출 디렉터리 미리 만들어 모든 경로가 동일 워크디렉터리 사용
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workflow_dir = target_outputs_dir / f"workflow_{timestamp}"
        workflow_dir.mkdir(parents=True, exist_ok=True)

        # ─── 분기 0: Phase 4 비활성 — 기존 4-agent 그대로 ──────────────────────
        if not enable_gui_branch:
            result = _run_classic_chain(user_request, workflow_dir, verbose=verbose)
        else:
            # ─── 분기 1: Phase 4 활성 — UI/UX 먼저 실행 ────────────────────────
            ui_ux = create_uiux_analyst_agent(verbose=verbose)
            uiux_task = _build_uiux_task(user_request, ui_ux)
            Crew(
                agents=[ui_ux],
                tasks=[uiux_task],
                process=Process.sequential,
                verbose=verbose,
            ).kickoff()
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
                )
            # ─── 분기 2-B: CLI 경로 ─────────────────────────────────────────────
            else:
                result = _run_cli_branch_chain_with_ui_context(
                    user_request=user_request,
                    workflow_dir=workflow_dir,
                    ui_spec=ui_spec,
                    uiux_task=uiux_task,
                    verbose=verbose,
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
                verbose=verbose,
            )
            # Build 결과를 메인 WorkflowResult 에 merge
            result.dependency_report = build_result.dependency_report
            result.build_spec = build_result.build_spec
            result.asset_manifest = build_result.asset_manifest
            result.installer_spec = build_result.installer_spec
            result.platform_test_report = build_result.platform_test_report

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
) -> WorkflowResult:
    """`enable_gui_branch=False` (기본) 경로. 기존 동작 그대로 보존."""
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    engineer = create_python_engineer_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(verbose=verbose)

    cto_task = _build_cto_task(user_request, cto)
    analyst_task = _build_analyst_task(analyst, cto_task)
    engineer_task = _build_engineer_task(engineer, cto_task, analyst_task)
    qa_review_task = _build_qa_task(reviewer, engineer_task)

    crew_result = Crew(
        agents=[cto, analyst, engineer, reviewer],
        tasks=[cto_task, analyst_task, engineer_task, qa_review_task],
        process=Process.sequential,
        verbose=verbose,
    ).kickoff()

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    engineer_output = _task_output_text(engineer_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
    )

    code_paths = _save_classic_artifacts(
        workflow_dir, user_request, cto_strategy, analyst_brief, engineer_output, qa_review
    )

    return WorkflowResult(
        user_request=user_request,
        cto_strategy=cto_strategy,
        analyst_brief=analyst_brief,
        engineer_output=engineer_output,
        qa_review=qa_review,
        saved_dir=workflow_dir,
        saved_code_files=code_paths,
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
) -> WorkflowResult:
    """UI/UX 가 GUI 가 아니라고 판정한 경로. Engineer 그대로 + UI/UX context 만 추가."""
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    engineer = create_python_engineer_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(verbose=verbose)

    cto_task = _build_cto_task(user_request, cto, ui_spec_context=uiux_task)
    analyst_task = _build_analyst_task(analyst, cto_task)
    engineer_task = _build_engineer_task(engineer, cto_task, analyst_task)
    qa_review_task = _build_qa_task(reviewer, engineer_task)

    crew_result = Crew(
        agents=[cto, analyst, engineer, reviewer],
        tasks=[cto_task, analyst_task, engineer_task, qa_review_task],
        process=Process.sequential,
        verbose=verbose,
    ).kickoff()

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    engineer_output = _task_output_text(engineer_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
    )

    code_paths = _save_classic_artifacts(
        workflow_dir, user_request, cto_strategy, analyst_brief, engineer_output, qa_review
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
) -> WorkflowResult:
    """UI/UX 가 GUI 라고 판정한 경로. Engineer 자리를 디자인 본부 3명이 대체."""
    cto = create_cto_agent(verbose=verbose)
    analyst = create_data_analyst_agent(verbose=verbose)
    designer = create_gui_designer_agent(verbose=verbose)
    theme = create_theme_designer_agent(verbose=verbose)
    coder = create_gui_code_generator_agent(verbose=verbose)
    reviewer = create_code_reviewer_agent(verbose=verbose)

    cto_task = _build_cto_task(user_request, cto, ui_spec_context=uiux_task)
    analyst_task = _build_analyst_task(analyst, cto_task)
    designer_task = _build_gui_designer_task(designer, uiux_task)
    theme_task = _build_theme_task(theme, uiux_task, designer_task)
    code_gen_task = _build_gui_code_gen_task(coder, uiux_task, designer_task, theme_task)
    qa_review_task = _build_qa_task(reviewer, code_gen_task)

    crew_result = Crew(
        agents=[cto, analyst, designer, theme, coder, reviewer],
        tasks=[
            cto_task,
            analyst_task,
            designer_task,
            theme_task,
            code_gen_task,
            qa_review_task,
        ],
        process=Process.sequential,
        verbose=verbose,
    ).kickoff()

    cto_strategy = _task_output_text(cto_task)
    analyst_brief = _task_output_text(analyst_task)
    gui_design = _task_output_text(designer_task)
    design_tokens = _task_output_text(theme_task)
    gui_code_output = _task_output_text(code_gen_task)
    qa_review = _task_output_text(qa_review_task) or (
        getattr(crew_result, "raw", None) or str(crew_result)
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

    # 코드 추출은 GUI Code Generator 산출 기준
    code_paths = _extract_code_blocks(gui_code_output, workflow_dir / "code")

    return WorkflowResult(
        user_request=user_request,
        cto_strategy=cto_strategy,
        analyst_brief=analyst_brief,
        engineer_output="",
        qa_review=qa_review,
        saved_dir=workflow_dir,
        saved_code_files=code_paths,
        chosen_path="gui",
        ui_spec=ui_spec,
        gui_design=gui_design,
        design_tokens=design_tokens,
        gui_code_output=gui_code_output,
    )
