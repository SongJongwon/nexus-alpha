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
from src.workflows._common import (
    SUSPICIOUS_OUTPUT_THRESHOLD as _SUSPICIOUS_OUTPUT_THRESHOLD,
    retry_short_tasks_in_chain,
    task_output_text as _task_output_text,
)
from src.workflows._schemas import (
    CodeReviewOutput,
    GUICodeOutput,
    GUIDesignOutput,
    ThemeTokensOutput,
    UIUXSpecOutput,
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
    # PR #36/#37 — PyInstaller executor 결과 (enable_executor=True 시만)
    executor_result: object = None  # ExecuteResult | None — circular import 회피용 object
    # PR #39 — GitHub Release publish 결과 (enable_publish=True 시만)
    publish_result: object = None  # PublishResult | None — 동일 사유


# ---------------------------------------------------------------------------
# 내부 헬퍼 — _task_output_text / SUSPICIOUS_OUTPUT_THRESHOLD 는 _common 으로 이동
# (PR #29, 이슈 6 fix). build_workflow / release_workflow 와 동일 구현 공유.
# ---------------------------------------------------------------------------


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


def _build_qa_task(reviewer, code_task: Task) -> Task:
    """Code Reviewer Task — code_task (Engineer 또는 GUI Code Generator) 컨텍스트로."""
    import sys

    kwargs: dict = dict(
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


def _build_gui_code_gen_task(
    coder, uiux_task: Task, designer_task: Task, theme_task: Task
) -> Task:
    """GUI Code Generator Task — 셋 모두 컨텍스트로."""
    import sys

    kwargs: dict = dict(
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
            # 이슈 6 fix — LLM 이 본문 생략 시 자동 재시도
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
                enable_executor=enable_executor,
                executor_timeout_sec=executor_timeout_sec,
                verbose=verbose,
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
    # 이슈 6 fix — LLM 본문 누락 자동 재시도
    retry_short_tasks_in_chain([cto_task, analyst_task, engineer_task, qa_review_task])

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
    # 이슈 6 fix — LLM 본문 누락 자동 재시도
    retry_short_tasks_in_chain([cto_task, analyst_task, engineer_task, qa_review_task])

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
    # 이슈 6 fix — LLM 본문 누락 자동 재시도 (GUI 체인 6 task)
    retry_short_tasks_in_chain([
        cto_task, analyst_task, designer_task, theme_task, code_gen_task, qa_review_task,
    ])

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
