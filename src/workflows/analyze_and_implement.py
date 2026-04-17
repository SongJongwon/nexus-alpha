# -*- coding: utf-8 -*-
"""
CTO → Data Analyst → Python Engineer 순차 협업 워크플로우.

사용자의 자연어 요구사항 하나를 입력받아, 3명의 에이전트가 순차적으로
협업하며 **전략 문서 → 분석 지시서 → 실행 가능한 Python 구현**까지
자동 산출하는 CrewAI 기반 워크플로우를 제공한다.

LangFuse 통합:
    단일 trace(`analyze_and_implement`) 아래에 3개 generation이 기록되도록,
    kickoff 전에 `log_trace`를 호출하고 종료 후 `end_trace + flush`를 수행한다.
    `BaseLLMProvider.generate()`가 `_current_trace`를 부모로 하여
    generation을 붙이므로 별도 계측 코드가 필요 없다.
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
from src.agents.engineering import create_python_engineer_agent
from src.monitoring import get_langfuse_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"


@dataclass
class WorkflowResult:
    """3명 협업 워크플로우의 최종 산출물.

    Attributes:
        user_request: 사용자가 제출한 원본 자연어 요구사항.
        cto_strategy: CTO가 산출한 기술 전략 문서(마크다운).
        analyst_brief: Data Analyst가 산출한 분석 지시서(마크다운).
        engineer_output: Python Engineer가 산출한 전체 응답(마크다운).
        saved_dir: 산출물이 저장된 디렉터리 경로.
        saved_code_files: engineer_output에서 추출되어 저장된 `.py` 경로들.
    """

    user_request: str
    cto_strategy: str
    analyst_brief: str
    engineer_output: str
    saved_dir: Path
    saved_code_files: list[Path] = field(default_factory=list)


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


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_analyze_and_implement(
    user_request: str,
    outputs_dir: Optional[Path] = None,
    verbose: bool = True,
) -> WorkflowResult:
    """사용자 요청을 받아 CTO → Analyst → Engineer 순으로 협업 Crew를 실행한다.

    Args:
        user_request: 사용자의 자연어 요구사항 (예: "Excel을 PDF로 …").
        outputs_dir: 산출물 저장 디렉터리. 기본은 프로젝트 루트의 `outputs/`.
        verbose: CrewAI의 중간 로그를 콘솔에 출력할지 여부.

    Returns:
        `WorkflowResult` — 각 에이전트 산출물과 저장 경로를 담은 구조체.

    Raises:
        RuntimeError: Provider 초기화 등 체인 중간 장애가 발생했을 때
            호출 측에서 명확히 포착할 수 있도록 원본 예외를 그대로 전파한다.
    """
    target_outputs_dir = outputs_dir if outputs_dir is not None else DEFAULT_OUTPUTS_DIR
    target_outputs_dir.mkdir(parents=True, exist_ok=True)

    monitor = get_langfuse_client()
    monitor.log_trace(
        name="analyze_and_implement",
        user_id="local-dev",
        metadata={
            "phase": "phase_1",
            "workflow": "analyze_and_implement",
            "user_request_preview": user_request[:160],
        },
    )

    try:
        # 1) 에이전트 생성 (각자 NexusAlphaLLM 인스턴스를 개별 보유)
        cto = create_cto_agent(verbose=verbose)
        analyst = create_data_analyst_agent(verbose=verbose)
        engineer = create_python_engineer_agent(verbose=verbose)

        # 2) Task 체인 구성 — context 인자로 이전 Task 산출물 주입
        cto_task = Task(
            description=(
                f"[사용자 요청]\n{user_request}\n\n"
                "위 요청을 분석하여 **기술 스택 / 구현 접근 / 리스크 / 권장 "
                "작업 순서** 네 섹션으로 된 전략 문서를 한국어로 작성하세요. "
                "엔지니어가 즉시 착수할 수 있을 만큼 구체적이어야 하며, "
                "요구사항이 모호한 부분이 있다면 먼저 명확화 질문을 제시해 주세요."
            ),
            expected_output=(
                "기술 스택 / 구현 접근 / 리스크 / 권장 순서 네 섹션의 한국어 전략 문서"
            ),
            agent=cto,
        )

        analyst_task = Task(
            description=(
                "CTO의 전략 문서(이전 컨텍스트)를 반영하여 입력 데이터에 "
                "대한 분석 지시서를 작성하세요. 다섯 섹션 구조:\n"
                "  1) 데이터 품질 체크포인트\n"
                "  2) 핵심 지표 5개 (이름·계산식·단위·의사결정 질문·표시 위치)\n"
                "  3) 추천 차트 3종 (유형·축 구성·메시지·디자인 주의사항)\n"
                "  4) 이상치 탐지 기준 (통계 기준 + 비즈니스 임계값)\n"
                "  5) 분석가 코멘트 (경영진 요약 강조 포인트 2~3개)\n\n"
                "엔지니어가 바로 코드로 옮길 수 있도록 지표·차트·이상치 기준을 "
                "모두 구체적으로 명시해 주세요."
            ),
            expected_output=(
                "데이터 품질 / 지표 5개 / 차트 3종 / 이상치 / 분석가 코멘트 "
                "다섯 섹션의 한국어 분석 지시서"
            ),
            agent=analyst,
            context=[cto_task],
        )

        engineer_task = Task(
            description=(
                "CTO의 전략 문서와 Data Analyst의 분석 지시서(이전 컨텍스트)를 "
                "모두 만족하는 **바로 실행 가능한 Python 구현 산출물**을 "
                "작성하세요.\n\n"
                "요구 사항:\n"
                "  - 모듈별 파일 분리 (loader / transform / metrics / chart / "
                "    render / cli 등 역할 단위)\n"
                "  - 모든 공개 함수에 타입 힌트와 docstring\n"
                "  - 최소 3건의 pytest 단위 테스트 (지표 계산 함수 중심)\n"
                "  - CLI 엔트리 포함 (`python -m <pkg> --input ... --output ...`)\n"
                "  - 경계 지점(I/O, CLI)에만 예외 처리, 내부 함수는 계약 신뢰\n\n"
                "산출 규약:\n"
                "  - 각 파일은 ```python 코드 블록으로 감싸고 첫 줄에 "
                "    `# file: <상대경로>` 헤더 주석 포함\n"
                "  - 마지막 섹션에 설치·실행 방법과 예시 커맨드 요약"
            ),
            expected_output=(
                "모듈별 실행 가능한 Python 코드 세트와 pytest 테스트, "
                "설치·실행 가이드를 포함한 완전한 구현 산출물"
            ),
            agent=engineer,
            context=[cto_task, analyst_task],
        )

        # 3) Crew 실행 (순차 프로세스)
        crew = Crew(
            agents=[cto, analyst, engineer],
            tasks=[cto_task, analyst_task, engineer_task],
            process=Process.sequential,
            verbose=verbose,
        )
        crew_result = crew.kickoff()

        # 4) 각 Task의 개별 산출물 수집
        cto_strategy = _task_output_text(cto_task)
        analyst_brief = _task_output_text(analyst_task)
        engineer_output = _task_output_text(engineer_task) or (
            getattr(crew_result, "raw", None) or str(crew_result)
        )

        # 5) 산출물 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workflow_dir = target_outputs_dir / f"workflow_{timestamp}"
        workflow_dir.mkdir(parents=True, exist_ok=True)

        (workflow_dir / "00_user_request.txt").write_text(
            user_request, encoding="utf-8"
        )
        (workflow_dir / "01_cto_strategy.md").write_text(
            cto_strategy, encoding="utf-8"
        )
        (workflow_dir / "02_analyst_brief.md").write_text(
            analyst_brief, encoding="utf-8"
        )
        (workflow_dir / "03_engineer_output.md").write_text(
            engineer_output, encoding="utf-8"
        )
        code_paths = _extract_code_blocks(
            engineer_output, workflow_dir / "code"
        )

        return WorkflowResult(
            user_request=user_request,
            cto_strategy=cto_strategy,
            analyst_brief=analyst_brief,
            engineer_output=engineer_output,
            saved_dir=workflow_dir,
            saved_code_files=code_paths,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
