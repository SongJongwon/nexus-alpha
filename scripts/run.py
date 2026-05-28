"""Nexus Alpha 자연어 입력 진입점 (Alpha 단계 — PR #102).

사용자가 한 줄 자연어 요청을 입력 → Track 자동 라우팅 → 풀체인 실행 →
.exe + (선택) Draft Release URL 표시.

본 스크립트는 *Alpha* 단계 진입점입니다 (Streamlit Beta / Electron/Tauri
Release 의 *전 단계* — `docs/context/next_session_context.md` §10 참고).

사용 예 (인터랙티브):
    .venv/Scripts/python.exe scripts/run.py
    → 자연어 입력창 prompt → Track 자동 선택 → 풀체인 실행

사용 예 (CLI 인자):
    # Track A (Calculator-style GUI/CLI 앱)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "계산기 만들어줘" --track A --build

    # Track B (5 도메인 자동화)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "네이버 쇼핑 가격 크롤링" --track B --build

    # 자동 라우팅 (기본) — heuristic 으로 Track 결정
    .venv/Scripts/python.exe scripts/run.py --request "계산기 만들어줘"

    # Draft Release 발행 (gh CLI + repo 필수)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "엑셀 분석 PDF 보고서" --track A --build --force-cli \\
        --release --repo "SongJongwon/nexus-alpha" --tag "v0.1.0-demo"

종료 코드:
    0 — 풀체인 정상 종료 (산출 .exe 또는 .py 생성)
    1 — 실행 중 오류 (Provider 초기화 / 의존성 등)
    2 — 사용자 입력 부재 (인터랙티브 prompt 빈 입력)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Track 자동 라우팅 휴리스틱
# ---------------------------------------------------------------------------
# Track B 키워드 — Track B 도메인 (자동화 / 데이터 / 스크래핑 / API / DevOps)
_TRACK_B_KEYWORDS = (
    "크롤링",
    "스크래핑",
    "scrap",
    "crawl",
    "playwright",
    "selenium",
    "rpa",
    "자동화 스크립트",
    "api",
    "webhook",
    "graphql",
    "엑셀",
    "excel",
    "pdf 파싱",
    "pdf parse",
    "csv 처리",
    "데이터 변환",
    "도커",
    "dockerfile",
    "github actions",
    "ci/cd",
)

# Track A 키워드 — Calculator 류 GUI/CLI 앱 (default fallback)
_TRACK_A_KEYWORDS = (
    "계산기",
    "calculator",
    "메모장",
    "notepad",
    "타이머",
    "timer",
    "변환기",
    "converter",
    "보고서",
    "report",
    "gui",
    "데스크탑 앱",
)


def _detect_track(request: str) -> str:
    """자연어 요청에서 Track A/B 자동 판단.

    매칭 규칙:
        - Track B 키워드 매칭 수 > Track A → 'B'
        - 그 외 → 'A' (default — Calculator-style GUI/CLI)

    Returns:
        ``'A'`` 또는 ``'B'``.
    """
    if not request:
        return "A"
    text = request.lower()
    b_score = sum(1 for k in _TRACK_B_KEYWORDS if k.lower() in text)
    a_score = sum(1 for k in _TRACK_A_KEYWORDS if k.lower() in text)
    return "B" if b_score > a_score else "A"


# ---------------------------------------------------------------------------
# 출력 helpers
# ---------------------------------------------------------------------------
def _print_banner() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Nexus Alpha — Alpha (자연어 입력 → .exe 풀체인)             ║")
    print("║  Track A: Calculator-style GUI/CLI                           ║")
    print("║  Track B: 5 도메인 자동화 (스크래핑/RPA/API/파싱/DevOps)     ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def _print_section(title: str) -> None:
    print()
    print(f"━━ {title} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ---------------------------------------------------------------------------
# PR #150 Phase 4 — 실시간 진행 상황 대시보드 (본인 비전 통찰 5)
# ---------------------------------------------------------------------------
# 배경:
#   친구 PC 베타 22~33min 빌드 중 PowerShell 화면이 *dead screen* → 친구가
#   "멈춘 줄 알았다" → Quick Edit Mode 부작용으로 selection 시 실 정지 → Ctrl+C
#   로 작업 잃음. 이는 *사용자 결함* 아닌 시스템의 진행 상황 가시화 부재 결과.
#
# 처방 (의존성 0 — 친구 PC 환경 안정):
#   - PhaseTracker — print 기반 단순 진행률 표시. 단계 N 중 i, 누적 시간,
#     단계 시작/종료 시각, 단계별 elapsed
#   - install.ps1 에 Quick Edit Mode 안내 (별도 처리 — install.ps1)


class PhaseTracker:
    """Track A/B 의 단계별 진행 상황 print — 의존성 0, Quick Edit 사고 재발 차단.

    사용 패턴::

        tracker = PhaseTracker(total=3)
        tracker.start("analyze_and_implement")
        ...
        tracker.end(summary="4-agent chain 완료")
        tracker.start("vision_qa")
        ...

    스레드 안전 X — main 단일 흐름에서만 사용.
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.current_index = 0
        self.session_start = datetime.now()
        self._phase_start: Optional[datetime] = None
        self._phase_name: str = ""
        self._completed_phases: list[tuple[str, float]] = []  # (name, elapsed)

    def set_total(self, total: int) -> None:
        """추정한 분모를 실 측정에 맞춰 mid-flow 갱신.

        PR #150 Phase 4: build 후 .exe 산출 여부를 보고 Vision QA 단계를 늘리거나
        줄여 표시 일관성 확보.
        """
        if total < self.current_index:
            total = self.current_index
        self.total = total

    def start(self, name: str) -> None:
        """단계 시작 표시."""
        self.current_index += 1
        self._phase_name = name
        self._phase_start = datetime.now()
        cumulative = (self._phase_start - self.session_start).total_seconds()
        print()
        print(
            f"▶ [{self.current_index}/{self.total}] {name} "
            f"(누적 {cumulative:.1f}s)"
        )

    def end(self, summary: str = "") -> None:
        """단계 종료 표시 + 산출 요약."""
        if self._phase_start is None:
            return
        elapsed = (datetime.now() - self._phase_start).total_seconds()
        self._completed_phases.append((self._phase_name, elapsed))
        tail = f" — {summary}" if summary else ""
        print(f"✓ [{self.current_index}/{self.total}] {self._phase_name} "
              f"완료 ({elapsed:.1f}s){tail}")
        self._phase_start = None

    def total_elapsed(self) -> float:
        return (datetime.now() - self.session_start).total_seconds()


def _format_build_skipped_line(executor_result: Any) -> Optional[str]:
    """PR #162 (2026-05-18) — exe_path 부재 시 결과 패널에 출력할 SKIPPED 메시지.

    이유 (2026-05-18 E2E 발견): ``_print_result_summary`` 가 ``exe_path=None`` 일 때
    아무 라인도 출력 안 했음 → PM 입장 "왜 Vision/QA 가 없지?" 디버깅 불가
    (build 가 SKIPPED 됐는지, vision-qa 가 비활성인지 구분 X). 본 헬퍼가 진단 진입점.

    분기:
        - ``executor_result is None``       → ``"(build 미실행 — enable_executor=False)"``
        - ``executor_result.success is False`` (SKIPPED 또는 FAIL)
                                            → ``"SKIPPED — exit=<N> reason=<error 1줄>"``
        - 그 외 (success=True 인데 exe_path=None 등 비정상)
                                            → ``"(.exe 산출 메타 부재 — executor_result 점검)"``
    """
    if executor_result is None:
        return "(build 미실행 — enable_executor=False)"
    success = getattr(executor_result, "success", True)
    if not success:
        exit_code = getattr(executor_result, "exit_code", "?")
        error_msg = getattr(executor_result, "error_message", None) or "unknown"
        first_line = error_msg.splitlines()[0] if error_msg else "unknown"
        return f"SKIPPED — exit={exit_code} reason={first_line}"
    # success=True 인데 exe_path 가 부재한 이상한 케이스
    return "(.exe 산출 메타 부재 — executor_result 점검)"


def _print_result_summary(
    track: str,
    elapsed_sec: float,
    outputs_dir: Optional[Path],
    exe_path: Optional[Path],
    release_url: Optional[str],
    vision_qa_summary: Optional[str] = None,
    qa_verdict_summary: Optional[str] = None,
    iterative_summary: Optional[str] = None,
    executor_result: Any = None,
) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print(f"║  결과 — Track {track} ({elapsed_sec/60:.2f}min)" + " " * (45 - len(f"Track {track} ({elapsed_sec/60:.2f}min)")) + "║")
    print("╚══════════════════════════════════════════════════════════════╝")
    if outputs_dir:
        print(f"  📁 outputs : {outputs_dir}")
    if exe_path and exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  📦 .exe    : {exe_path} ({size_mb:.2f} MB)")
    elif exe_path:
        print(f"  📦 .exe (예상): {exe_path} — 생성 안 됨")
    else:
        # PR #162 — exe_path=None 일 때 SKIPPED reason 진단 표시
        skipped_line = _format_build_skipped_line(executor_result)
        if skipped_line:
            print(f"  📦 .exe    : {skipped_line}")
    if iterative_summary:
        print(f"  🔄 Iterate: {iterative_summary}")
    if vision_qa_summary:
        print(f"  👁️  Vision : {vision_qa_summary}")
    if qa_verdict_summary:
        print(f"  🔁 QA loop: {qa_verdict_summary}")
    if release_url:
        print(f"  🔗 Release: {release_url}")
    print()


# ---------------------------------------------------------------------------
# Vision QA — PR #141 Phase 2 (본인 비전 통찰 6, D-3)
# ---------------------------------------------------------------------------
def _run_vision_qa_full(
    exe_path: Path,
    outputs_dir: Path,
    *,
    skip_vision: bool = False,
):
    """빌드된 .exe 에 대해 gui_test_executor 호출 → GUITestResult 객체 반환.

    PR #150 Phase 4 (2026-05-15): PR #147 의 ``_run_vision_qa`` 가 str summary 만
    반환했던 것을 확장 — 결과 객체 자체를 반환해 후속 ``qa_feedback_loop`` 평가에
    활용. 실패 / pyautogui 미설치 등 호출 자체 불가 시 None.
    """
    try:
        from src.agents.qa.gui_test_executor import run_gui_test
    except ImportError:
        return None

    vision_dir = outputs_dir / "vision_qa"
    vision_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_gui_test(
            target_path=exe_path,
            output_dir=vision_dir,
            skip_vision=skip_vision,
        )
    except Exception:  # noqa: BLE001 — wiring 실패는 정보로만
        return None

    try:
        (vision_dir / "summary.txt").write_text(
            result.summary_line(), encoding="utf-8"
        )
    except OSError:
        pass
    return result


def _run_vision_qa(
    exe_path: Path,
    outputs_dir: Path,
    *,
    skip_vision: bool = False,
) -> Optional[str]:
    """PR #141 Phase 2 backward-compat wrapper — str summary 만 반환.

    PR #150 Phase 4: 신규 호출 측은 ``_run_vision_qa_full`` 사용 권장.
    본 함수는 기존 호출 측 + 회귀 테스트 호환성 유지를 위해 보존.
    """
    result = _run_vision_qa_full(exe_path, outputs_dir, skip_vision=skip_vision)
    if result is None:
        return None
    return result.summary_line()


def _evaluate_vision_qa_via_feedback_loop(
    vision_result,
    *,
    retry_count: int = 0,
    max_retries: int = 0,
):
    """Vision QA 결과를 ``qa_feedback_loop.evaluate_qa_results`` 로 평가.

    PR #150 Phase 4: verdict 가시화만.
    PR #151 (Phase 4 후속, 2026-05-15): ``retry_count`` / ``max_retries`` kwargs
        추가 → Track A 가 ``--vision-qa-max-retries`` 값을 주입해 retry 가능 여부
        (``should_retry``) 판정. 반환은 (verdict_str, decision) 튜플 — 호출 측이
        decision 객체 자체를 검사할 수 있게 (회귀 차단: PR #150 의 기존 호출 측은
        반환의 첫 요소만 사용).

    Args:
        vision_result: ``GUITestResult`` (duck-typed).
        retry_count: 현재까지의 retry 횟수 (0=첫 평가).
        max_retries: 허용 retry 총 횟수.

    Returns:
        ``(summary_line, QAFeedbackDecision_or_None)``. ``QAFeedbackDecision`` 이
        None 이면 qa_feedback_loop import 실패.
    """
    try:
        from src.workflows.qa_feedback_loop import evaluate_qa_results
    except ImportError:
        return "[QA_FEEDBACK_LOOP unavailable]", None

    decision = evaluate_qa_results(
        results={"vision_qa": vision_result},
        retry_count=retry_count,
        max_retries=max_retries,
    )
    return decision.summary_line(), decision


# ---------------------------------------------------------------------------
# Engineer + Build 재호출 — PR #151 (Phase 4 후속, 본인 비전 통찰 6 D-3 완성)
# ---------------------------------------------------------------------------
def _retry_engineer_with_vision_feedback(
    *,
    prev_result,
    vision_result,
    user_request: str,
    outputs_dir: Path,
    retry_index: int,
    max_retries: int,
    verbose: bool = False,
) -> Optional[Path]:
    """Vision QA 결함을 Engineer 에게 피드백해 *Engineer + Build 만* 재실행.

    PR #151 처방 (PR #150 verdict 가시화의 다음 단계):
        Vision QA verdict 가 ``should_retry`` 일 때 풀체인 재실행 (~25min) 대신
        Engineer + Build 만 (~5min) 재호출 → 비용 폭증 차단.

        ``qa_feedback_loop.build_feedback_message_for_engineer`` 가 작성한 markdown
        피드백을 Engineer revision task description 에 주입 → 단일 task Crew kickoff
        → ``_extract_code_blocks`` 로 새 코드 추출 → ``run_build_workflow`` 로 새 .exe
        산출.

    실패 격리:
        Crew kickoff / build 어느 단계든 실패 시 ``None`` 반환 — 워크플로 차단 X.

    Args:
        prev_result: 직전 ``run_analyze_and_implement`` 결과 (``saved_code_files``
            + ``gui_code_output`` 등 포함).
        vision_result: 직전 Vision QA 결과 — feedback 메시지 작성 입력.
        user_request: 원본 사용자 자연어 요청.
        outputs_dir: 산출 dir — ``retry_{N:02d}/`` 하위에 저장.
        retry_index: 1-based retry 번호.
        max_retries: 전체 허용 retry 수 (feedback 메시지의 budget 표시용).
        verbose: CrewAI 중간 로그 출력 여부.

    Returns:
        새 ``.exe`` 경로 또는 None (재호출 실패).
    """
    try:
        from src.workflows.qa_feedback_loop import (
            build_feedback_message_for_engineer,
            evaluate_qa_results,
        )
    except ImportError as exc:
        print(f"  ⚠️  qa_feedback_loop import 실패: {exc!r}", file=sys.stderr)
        return None

    # 1. Vision QA feedback 메시지 작성 (Engineer 에게 줄 markdown 지시)
    decision = evaluate_qa_results(
        results={"vision_qa": vision_result},
        retry_count=retry_index - 1,
        max_retries=max_retries,
    )
    vision_report_text = (
        vision_result.summary_line() if hasattr(vision_result, "summary_line") else str(vision_result)
    )
    feedback_md = build_feedback_message_for_engineer(
        decision, full_qa_reports={"vision_qa": vision_report_text}
    )

    retry_dir = outputs_dir / f"retry_{retry_index:02d}"
    retry_dir.mkdir(parents=True, exist_ok=True)
    (retry_dir / "feedback_for_engineer.md").write_text(feedback_md, encoding="utf-8")

    # 2. 이전 코드를 markdown 으로 조립 — Engineer 가 그대로 revision 가능하도록
    prior_code_parts: list[str] = []
    for code_path in getattr(prev_result, "saved_code_files", []) or []:
        try:
            content = Path(code_path).read_text(encoding="utf-8")
        except OSError:
            continue
        prior_code_parts.append(
            f"```python\n# file: {Path(code_path).name}\n{content}\n```"
        )
    prior_code_md = (
        "\n\n".join(prior_code_parts) if prior_code_parts else "# (이전 산출 코드 없음)"
    )

    # 3. Engineer agent + 단일 revision task — GUI 분기 / CLI 분기 자동 판별
    try:
        from crewai import Crew, Process, Task

        from src.agents.design.gui_code_generator import create_gui_code_generator_agent
        from src.agents.engineering import create_python_engineer_agent
    except ImportError as exc:
        print(f"  ⚠️  retry 의존성 import 실패: {exc!r}", file=sys.stderr)
        return None

    is_gui = bool(getattr(prev_result, "gui_code_output", "") or "")
    engineer = (
        create_gui_code_generator_agent(verbose=verbose)
        if is_gui
        else create_python_engineer_agent(verbose=verbose)
    )

    revision_task = Task(
        description=(
            f"사용자 원 요청: {user_request}\n\n"
            "## 이전 코드 산출물\n\n"
            f"{prior_code_md}\n\n"
            "## Vision QA 자동 검증 피드백\n\n"
            f"{feedback_md}\n\n"
            "## 보정 지시\n\n"
            "위 Vision QA 피드백의 *결함* 만 보정한 새 코드를 산출하세요. 무관한 "
            "리팩토링은 금지. 산출 규약: 각 파일은 ```python 코드 블록 + 첫 줄 "
            "`# file: <상대경로>` 헤더 주석 + 단독 실행 가능 (`python <entry>.py`) "
            "구조."
        ),
        expected_output=(
            "이전 코드의 Vision QA 결함을 보정한 완전한 Python 코드 세트 "
            "(```python 블록 + # file: 헤더 + python <entry>.py 실행 가능)."
        ),
        agent=engineer,
    )

    try:
        crew = Crew(
            agents=[engineer],
            tasks=[revision_task],
            process=Process.sequential,
            verbose=verbose,
        )
        crew.kickoff()
    except Exception as exc:  # noqa: BLE001 — retry 실패는 워크플로 차단 X
        print(f"  ⚠️  Engineer 재호출 실패: {exc!r}", file=sys.stderr)
        return None

    # 4. 산출 markdown → 코드 파일 추출
    try:
        from src.workflows._common import task_output_text
        from src.workflows.analyze_and_implement import _extract_code_blocks
    except ImportError as exc:
        print(f"  ⚠️  _extract_code_blocks import 실패: {exc!r}", file=sys.stderr)
        return None

    revised_output = task_output_text(revision_task)
    if not revised_output:
        print("  ⚠️  Engineer 재호출 산출 비어 있음", file=sys.stderr)
        return None
    (retry_dir / "engineer_revised_output.md").write_text(
        revised_output, encoding="utf-8"
    )
    new_code_paths = _extract_code_blocks(revised_output, retry_dir / "code")
    if not new_code_paths:
        print("  ⚠️  재산출에서 코드 블록 추출 실패", file=sys.stderr)
        return None

    # 5. Build 재실행 — Platform Tester skip (retry 비용 절감)
    try:
        from src.workflows.build_workflow import run_build_workflow

        build_result = run_build_workflow(
            code_files=new_code_paths,
            user_request=user_request,
            target_platform="windows",
            ui_spec=getattr(prev_result, "ui_spec", "") or "",
            design_tokens=getattr(prev_result, "design_tokens", "") or "",
            workflow_dir=retry_dir,
            enable_platform_test=False,
            enable_executor=True,
            verbose=verbose,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  retry build 실패: {exc!r}", file=sys.stderr)
        return None

    # PR #160b — retry build .exe 미생성 시 실 원인 surface (이전 PR #151 단순 'retry skip' fail-silent).
    # 가능한 원인:
    #   1. executor_result=None — build_workflow 가 enable_executor=True 임에도 executor 호출 자체 skip
    #      (보통 entry .py 미탐지 or workflow_dir 부재). 진단: build_result 의 다른 필드 조사
    #   2. executor_result.success=False — PyInstaller 실행했으나 실패 (exit_code≠0).
    #      ExecuteResult 에 ``error_message`` / ``stderr_tail`` 등 있으면 surface
    #   3. executor_result.exe_path=None — 빌드 시도했으나 결과물 추출 실패
    executor = getattr(build_result, "executor_result", None)
    if executor is None:
        platform_test = getattr(build_result, "platform_test_report", "") or ""
        platform_summary = platform_test[:200].replace("\n", " ") if platform_test else ""
        print(
            f"  ⚠️  retry build .exe 미생성 — executor_result=None "
            f"(build_workflow 가 PyInstaller 호출 안 함, entry .py 미탐지 가능). "
            f"platform_test={platform_summary!r}",
            file=sys.stderr,
        )
        return None
    exe_path_attr = getattr(executor, "exe_path", None)
    if exe_path_attr is None:
        success_attr = getattr(executor, "success", False)
        err_msg = getattr(executor, "error_message", "") or ""
        stderr_tail = getattr(executor, "stderr_tail", "") or ""
        print(
            f"  ⚠️  retry build .exe 미생성 — executor.exe_path=None "
            f"(success={success_attr}, error={err_msg!r}, "
            f"stderr_tail={stderr_tail[:160]!r})",
            file=sys.stderr,
        )
        return None
    exe_path_obj = Path(exe_path_attr)
    if not exe_path_obj.exists():
        print(
            f"  ⚠️  retry build .exe 경로 존재 X — {exe_path_obj} "
            "(PyInstaller success=True 보고했으나 디스크에 파일 없음)",
            file=sys.stderr,
        )
        return None
    return exe_path_obj


# ---------------------------------------------------------------------------
# Track A / B 실행
# ---------------------------------------------------------------------------
def _run_track_a(args: argparse.Namespace) -> int:
    """Track A — Calculator-style GUI/CLI 앱 풀체인.

    PR #150 Phase 4: PhaseTracker 로 단계 진행 표시 + Vision QA 결과를
    ``qa_feedback_loop.evaluate_qa_results`` 로 평가해 verdict 출력.
    PR #157 (2026-05-15): ``--auto-iterate`` 시 ``run_iterative_loop`` 호출 분기.
        Convergence Judge 가 COMPLETE/BLOCKED 판정할 때까지 최대 ``--max-iterations``
        회 recall→kickoff→chain→sandbox→gap→judge→retrospective→curate cycle 자동
        반복. LoopOutcome.final_chain_result 의 ``executor_result`` / ``publish_result``
        를 그대로 result 변수로 매핑해 downstream (Vision QA + retry + 결과 패널) 가
        동일 흐름 재사용.
    """
    outputs_dir = PROJECT_ROOT / "outputs" / f"alpha_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    start = datetime.now()

    # 활성 phase 수 추정 (대시보드 분모) — build + vision-qa + retry 토글 반영.
    # 실제 .exe 산출 여부 / retry 발생 여부에 따라 ``tracker.set_total`` 로
    # 후보정 (.exe 미생성 → 축소, retry 발생 → 확장 불필요 — 각 retry 가 본인 phase
    # 를 push 하므로 current_index 가 자연 증가, set_total 가 clamp).
    total_phases = 1  # analyze_and_implement 또는 iterative_loop (필수)
    if args.build and not args.no_vision_qa:
        total_phases += 2  # vision_qa + qa_feedback_loop
        if args.vision_qa_max_retries > 0:
            # 각 retry 는 1 phase (engineer+build → 재 Vision QA + verdict 까지 합산)
            total_phases += args.vision_qa_max_retries
    tracker = PhaseTracker(total=total_phases)

    iterative_summary: Optional[str] = None
    if args.auto_iterate:
        # PR #157 — 자기 진화 루프 진입 (opt-in)
        from src.workflows.iterative_loop import run_iterative_loop

        tracker.start(
            f"iterative_loop (max_iter={args.max_iterations}, "
            "recall→kickoff→chain→sandbox→gap→judge→retro→curate)"
        )
        outcome = run_iterative_loop(
            args.request,
            outputs_dir=outputs_dir,
            max_iterations=args.max_iterations,
            verbose=args.verbose,
            enable_gui_branch=not args.force_cli,
            enable_build_branch=args.build,
            enable_rv=args.enable_rv,
            enable_strategist=args.enable_strategist,
            enable_boardroom=args.enable_boardroom,
            enable_tikitaka=args.enable_tikitaka,
            enable_release_branch=args.release,
            enable_executor=args.build,
            enable_publish=args.release,
            publish_as_draft=True,
            repo_url=args.repo,
        )
        result = outcome.final_chain_result
        # PR #174 — BLOCKED UX 개선 (blocked_cause + partial output 안내)
        from src.workflows.iterative_loop import format_iterative_summary  # noqa: PLC0415
        iterative_summary = format_iterative_summary(outcome, args.max_iterations)
        if result is None:
            # 안전망: 어떤 이유로든 chain_result 부재 → downstream 가 .saved_dir 등 접근 시
            # AttributeError 위험. dummy result-like namespace 로 폴백.
            result = SimpleNamespace(
                saved_dir=outputs_dir,
                executor_result=None,
                publish_result=None,
                gui_code_output="",
                ui_spec="",
                design_tokens="",
                saved_code_files=[],
                engineer_output="",
            )
        tracker.end(summary=iterative_summary)
    else:
        from src.workflows.analyze_and_implement import run_analyze_and_implement

        tracker.start("analyze_and_implement (4~7 agent chain + build/release)")
        # PR #217 follow-up — enable_rv 는 iterative_loop 전용 (analyze_and_implement
        # 단발 호출 시 RV 노드 우회가 자연 동작). 잘못 전달 시 TypeError 발생.
        if args.enable_rv:
            print(
                "  ! --enable-rv 는 --auto-iterate 모드에서만 동작 — "
                "1회성 chain 실행에서는 무시됨",
                file=sys.stderr,
            )
        result = run_analyze_and_implement(
            args.request,
            outputs_dir=outputs_dir,
            verbose=args.verbose,
            enable_gui_branch=not args.force_cli,
            enable_build_branch=args.build,
            enable_release_branch=args.release,
            enable_executor=args.build,
            enable_publish=args.release,
            publish_as_draft=True,
            repo_url=args.repo,
        )
        tracker.end(summary=f"saved_dir={result.saved_dir}")

    elapsed = (datetime.now() - start).total_seconds()
    exe_path = getattr(result, "executor_result", None)
    exe_path = Path(exe_path.exe_path) if exe_path and getattr(exe_path, "exe_path", None) else None
    release_url = None
    publish = getattr(result, "publish_result", None)
    if publish:
        release_url = getattr(publish, "release_url", None)

    # PR #141 Phase 2 — Vision QA wiring (build 산출 .exe 가 있고 --no-vision-qa 미지정)
    vision_summary: Optional[str] = None
    qa_verdict_summary: Optional[str] = None
    if not (exe_path and exe_path.exists() and not args.no_vision_qa):
        # .exe 미생성 또는 vision-qa skip → 잔여 2단계 미실행 → total 후보정.
        tracker.set_total(tracker.current_index)
    if exe_path and exe_path.exists() and not args.no_vision_qa:
        tracker.start("vision_qa (gui_test_executor 시각 검증)")
        vision_result = _run_vision_qa_full(exe_path, outputs_dir)
        if vision_result is not None:
            vision_summary = vision_result.summary_line()
            tracker.end(summary=vision_summary)
        else:
            vision_summary = "(Vision QA skip — gui_test_executor 호출 불가)"
            tracker.end(summary=vision_summary)

        # PR #150 Phase 4 — Vision QA 결과를 qa_feedback_loop.evaluate_qa_results 로 평가
        if vision_result is not None:
            tracker.start("qa_feedback_loop (Vision QA verdict 합산)")
            qa_verdict_summary, qa_decision = _evaluate_vision_qa_via_feedback_loop(
                vision_result,
                retry_count=0,
                max_retries=args.vision_qa_max_retries,
            )
            tracker.end(summary=qa_verdict_summary)

            # PR #151 — should_retry 일 때 Engineer + Build 재호출 (max_retries 한도 안)
            if (
                qa_decision is not None
                and args.vision_qa_max_retries > 0
                and qa_decision.should_retry
            ):
                for retry_idx in range(1, args.vision_qa_max_retries + 1):
                    tracker.start(
                        f"retry {retry_idx}/{args.vision_qa_max_retries} "
                        "(Engineer + Build 재호출)"
                    )
                    new_exe = _retry_engineer_with_vision_feedback(
                        prev_result=result,
                        vision_result=vision_result,
                        user_request=args.request,
                        outputs_dir=outputs_dir,
                        retry_index=retry_idx,
                        max_retries=args.vision_qa_max_retries,
                        verbose=args.verbose,
                    )
                    if new_exe is None:
                        tracker.end(summary="retry skip — 재호출 실패")
                        break
                    exe_path = new_exe

                    # 재 Vision QA 1회 + verdict 재평가
                    retry_vision_dir = outputs_dir / f"retry_{retry_idx:02d}"
                    new_vision = _run_vision_qa_full(new_exe, retry_vision_dir)
                    if new_vision is None:
                        vision_summary = (
                            f"retry {retry_idx} new_exe={new_exe.name} "
                            "(Vision QA 호출 불가)"
                        )
                        tracker.end(summary=vision_summary)
                        break

                    vision_result = new_vision
                    vision_summary = new_vision.summary_line()
                    qa_verdict_summary, qa_decision = (
                        _evaluate_vision_qa_via_feedback_loop(
                            new_vision,
                            retry_count=retry_idx,
                            max_retries=args.vision_qa_max_retries,
                        )
                    )
                    tracker.end(
                        summary=f"new_exe={new_exe.name}, {qa_verdict_summary}"
                    )
                    if qa_decision is None or qa_decision.overall_passed:
                        break
                    if not qa_decision.should_retry:
                        break  # budget exhausted

    _print_result_summary(
        "A", elapsed, outputs_dir, exe_path, release_url,
        vision_summary, qa_verdict_summary, iterative_summary,
        executor_result=getattr(result, "executor_result", None),
    )
    return 0


def _detect_track_b_gui_artifact(
    saved_code_files, exe_path: Optional[Path]
) -> bool:
    """Track B 산출이 GUI 인지 ``detect_artifact_category`` 휴리스틱으로 판정.

    PR #155 (Track B Vision QA wiring): Track B 산출 대부분이 CLI 스크립트라
    Vision QA 불필요. GUI 분기만 자동 트리거하기 위해 본 helper 가 entry source
    파일 + exe 둘 다를 ``qa_feedback_loop.detect_artifact_category`` 에 전달 →
    ``"gui"`` 결과일 때만 True 반환.

    Args:
        saved_code_files: ``AutomateWorkflowResult.saved_code_files`` (list[Path]).
            첫 .py 를 entry 휴리스틱 입력으로 사용.
        exe_path: 빌드된 .exe 경로 (없으면 None).

    Returns:
        True if 카테고리 == "gui", else False.
    """
    try:
        from src.workflows.qa_feedback_loop import detect_artifact_category
    except ImportError:
        return False
    entry_script: Optional[Path] = None
    if saved_code_files:
        non_test = [
            p for p in saved_code_files
            if not Path(p).name.startswith("test_")
        ]
        candidates = non_test or list(saved_code_files)
        if candidates:
            entry_script = Path(candidates[0])
    try:
        category = detect_artifact_category(
            target_script=entry_script,
            target_exe=exe_path,
        )
    except Exception:  # noqa: BLE001 — 휴리스틱 실패는 Vision QA skip
        return False
    return category == "gui"


def _run_track_b(args: argparse.Namespace) -> int:
    """Track B — 5 도메인 자동화 풀체인.

    PR #150 Phase 4: PhaseTracker 로 단계 진행 표시.
    PR #155 (2026-05-15): Vision QA 자동 감지 분기 신설.
    PR #158 (2026-05-15): ``--auto-iterate`` 시 ``run_iterative_loop(track="B")``
        호출 분기. iterative_loop 의 ``_node_run_chain`` 이 state.track="B" 면
        ``run_automate_workflow`` 호출 후 ``_adapt_automate_to_chain_result`` 로
        WorkflowResult-like duck type 변환 → Gap Analyst / Convergence Judge /
        Retrospective / Curator 모두 동일하게 작동.
    """
    outputs_dir = PROJECT_ROOT / "outputs" / f"alpha_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    start = datetime.now()

    # PR #183 — --forced-domain (Track B 도메인 자동 분류 우회) str → enum 변환
    forced_domain_enum = None
    if getattr(args, "forced_domain", None):
        from src.workflows.automate_workflow import AutomationDomain  # noqa: PLC0415
        forced_domain_enum = AutomationDomain(args.forced_domain)

    total_phases = 1  # automate_workflow 또는 iterative_loop (필수)
    if args.build and not args.no_vision_qa:
        total_phases += 2  # vision_qa + qa_feedback_loop (gui 분기일 때만 실 호출)
    tracker = PhaseTracker(total=total_phases)

    iterative_summary: Optional[str] = None
    if args.auto_iterate:
        # PR #158 — 자기 진화 루프 진입 (Track B opt-in)
        from src.workflows.iterative_loop import run_iterative_loop

        tracker.start(
            f"iterative_loop track=B (max_iter={args.max_iterations}, "
            "recall→kickoff→automate→sandbox→gap→judge→retro→curate)"
        )
        outcome = run_iterative_loop(
            args.request,
            outputs_dir=outputs_dir,
            max_iterations=args.max_iterations,
            verbose=args.verbose,
            track="B",
            enable_build_branch=args.build,  # Track B QA loop + build 트리거
            enable_executor=args.build,
            enable_release_branch=args.release,
            enable_publish=args.release,
            publish_as_draft=True,
            repo_url=args.repo,
            release_tag=args.tag,
            # PR #183 — CLI --forced-domain Track B 자동 분류 우회
            forced_domain=forced_domain_enum,
        )
        chain = outcome.final_chain_result
        # PR #174 — BLOCKED UX 개선 (Track B 동일 포맷 — blocked_cause + partial hint)
        from src.workflows.iterative_loop import format_iterative_summary  # noqa: PLC0415
        iterative_summary = format_iterative_summary(outcome, args.max_iterations)
        if chain is None:
            # 안전망: LoopOutcome.final_chain_result=None → dummy 폴백
            result = SimpleNamespace(
                saved_dir=outputs_dir,
                saved_code_files=[],
                executor_result=None,
                publish_result=None,
            )
        else:
            result = chain
        tracker.end(summary=iterative_summary)
    else:
        from src.workflows.automate_workflow import run_automate_workflow

        tracker.start("automate_workflow (5 도메인 자동화 chain + build/release)")
        result = run_automate_workflow(
            args.request,
            outputs_dir=outputs_dir,
            verbose=args.verbose,
            enable_qa_loop=args.build,
            enable_build=args.build,
            enable_release=args.release,
            repo_url=args.repo,
            release_tag=args.tag,
            publish_as_draft=True,
            # PR #183 — CLI --forced-domain Track B 자동 분류 우회
            forced_domain=forced_domain_enum,
        )
        tracker.end(summary=f"saved_dir={getattr(result, 'saved_dir', None)}")

    elapsed = (datetime.now() - start).total_seconds()
    executor = getattr(result, "executor_result", None)
    exe_path = Path(executor.exe_path) if executor and getattr(executor, "exe_path", None) else None
    release_url = None
    publish = getattr(result, "publish_result", None)
    if publish:
        release_url = getattr(publish, "release_url", None)

    # PR #155 — GUI 산출 분기에서만 Vision QA 자동 호출 (Track A 와 동일 helper 재사용).
    vision_summary: Optional[str] = None
    qa_verdict_summary: Optional[str] = None
    is_gui_artifact = (
        args.build
        and not args.no_vision_qa
        and exe_path is not None
        and exe_path.exists()
        and _detect_track_b_gui_artifact(
            getattr(result, "saved_code_files", []) or [], exe_path
        )
    )
    if is_gui_artifact:
        tracker.start("vision_qa (Track B GUI 산출 — 자동 감지)")
        vision_result = _run_vision_qa_full(exe_path, outputs_dir)
        if vision_result is not None:
            vision_summary = vision_result.summary_line()
            tracker.end(summary=vision_summary)
            tracker.start("qa_feedback_loop (Vision QA verdict 합산)")
            qa_verdict_summary, _ = _evaluate_vision_qa_via_feedback_loop(
                vision_result,
                retry_count=0,
                max_retries=0,  # Track B 는 retry 비활성 — 자체 qa_loop 가 있음
            )
            tracker.end(summary=qa_verdict_summary)
        else:
            vision_summary = "(Vision QA skip — gui_test_executor 호출 불가)"
            tracker.end(summary=vision_summary)
            tracker.set_total(tracker.current_index)
    else:
        # GUI 아님 / build 비활성 / --no-vision-qa → 잔여 단계 분모 축소
        tracker.set_total(tracker.current_index)

    _print_result_summary(
        "B",
        elapsed,
        getattr(result, "saved_dir", None) or outputs_dir,
        exe_path,
        release_url,
        vision_summary,
        qa_verdict_summary,
        iterative_summary,
        executor_result=getattr(result, "executor_result", None),
    )
    return 0


# ---------------------------------------------------------------------------
# 인터랙티브 입력
# ---------------------------------------------------------------------------
def _prompt_request() -> str:
    """자연어 요청 prompt — 빈 입력은 종료."""
    _print_section("자연어 요청 입력")
    print("  예시:")
    print("    - 계산기 만들어줘")
    print("    - 매장별 시간 매출 Excel 분석 PDF 보고서")
    print("    - 네이버 쇼핑 가격 크롤링 스크립트")
    print()
    try:
        request = input("👉 요청: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return request


def _prompt_track(default_track: str, input_fn=input) -> str:
    """Track 선택 prompt — PR #115: 'b' 키 충돌 회피 (Build 옵션과 혼동 가능).

    숫자 1/2 로 선택 — 'a'/'b' 입력은 default 로 fallback.

    Args:
        default_track: 자동 감지된 Track ('A' or 'B').
        input_fn: ``input()`` 주입 (테스트용, 기본 builtins.input).
    """
    print(f"  자동 감지 Track: **{default_track}**")
    print("    1) Track A — Calculator-style GUI/CLI 앱")
    print("    2) Track B — 5 도메인 자동화 (스크래핑/RPA/API/파싱/DevOps)")
    try:
        choice = input_fn(f"  선택 [Enter={default_track} / 1 / 2]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default_track
    if choice == "1":
        return "A"
    if choice == "2":
        return "B"
    return default_track


def _prompt_build(input_fn=input) -> bool:
    """Build 옵션 인터랙티브 prompt — PR #115 신설.

    Track 결정 후 별도 단계로 호출. ``--build`` 플래그 미지정 + 인터랙티브 모드일 때만.
    PyInstaller .exe 빌드는 +30~60초 추가 시간이 들어 사용자 명시적 확인 필요.

    Args:
        input_fn: ``input()`` 주입 (테스트용, 기본 builtins.input).
    """
    print()
    print("  Build (.exe 생성)?")
    print("    y) PyInstaller 로 .exe 빌드 (+30~60초, 산출물에 .exe 포함)")
    print("    N) 코드 + 사양만 산출 (.exe 없음, 빠름)")
    try:
        choice = input_fn("  빌드 [y/N, Enter=N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return choice in ("y", "yes")


# ---------------------------------------------------------------------------
# auto-iterate 비용 안내 banner — PR #163 (2026-05-18, 기본 ON 전환 처방)
# ---------------------------------------------------------------------------
# 1 iter 당 LLM call 비용 추정 (4-agent chain + sandbox + gap + judge + retro +
# curate). 베이스라인 — 본인 PC E2E 측정 (~30min / iter, Sonnet 4.6 기준 ~$5).
# 추정값은 *최악* 시나리오 안내용이므로 보수적으로 잡음.
_AUTO_ITERATE_MIN_PER_ITER: int = 25  # 평균 ~25min/iter (E2E 측정 30.41min/1iter 보수)
_AUTO_ITERATE_USD_PER_ITER: int = 5   # Sonnet 4.6 기준 ~$5/iter (Opus 시 ~3배)


def _confirm_auto_iterate_cost(args, input_fn=input) -> bool:
    """auto-iterate 진입 직전 비용 안내 + Enter 대기 (PR #163).

    기본 ON 전환에 따라 *명시 opt-in 이 아닌* 사용자도 자기 진화 cycle 에 진입.
    PM 입장 큰 비용 부담 (최악 max_iter * ~25min, ~$5/iter) 을 *진입 전* 보여주고
    명시 confirm 받기. non-interactive 모드는 안내만 출력 (자동 confirm).

    Returns:
        True 면 계속 진행, False 면 사용자 중단 (Ctrl-C / EOF / 'n' 답변).
    """
    n = max(1, getattr(args, "max_iterations", 3))
    worst_min = n * _AUTO_ITERATE_MIN_PER_ITER
    worst_usd = n * _AUTO_ITERATE_USD_PER_ITER
    print()
    print("  ⚡ auto-iterate 활성 (PR #163 — 기본 ON, --no-auto-iterate 로 OFF)")
    print(
        f"     max_iterations = {n} → 최악 ~{worst_min}min, ~${worst_usd} "
        "(Convergence Judge 가 COMPLETE/BLOCKED 판정하면 조기 종료)"
    )
    print("     iter 당 cycle: recall→kickoff→chain→sandbox→gap→judge→retro→curate")
    if getattr(args, "non_interactive", False):
        print("     (non-interactive 모드 — 자동 확인)")
        return True
    try:
        choice = input_fn("  계속 [Enter 로 진행 / Ctrl-C 또는 'n' 으로 중단]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return choice not in ("n", "no")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nexus Alpha 자연어 입력 → .exe 풀체인 (Alpha 단계)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--request", "-r", default="",
        help="자연어 요청. 미지정 시 인터랙티브 prompt.",
    )
    parser.add_argument(
        "--track", choices=["A", "B", "auto"], default="auto",
        help="Track 강제 (기본: auto — 휴리스틱 라우팅).",
    )
    parser.add_argument(
        "--build", action="store_true", default=False,
        help="PyInstaller .exe 빌드 활성 (default off — 사양만 산출).",
    )
    parser.add_argument(
        "--enable-rv", dest="enable_rv", action="store_true", default=False,
        help=(
            "v13 Phase 1 — 본부 9 Runtime Verification opt-in. 빌드된 .exe 를 "
            "Exe Runtime Tester 가 자율 검증 (silent fail / crash 감지). "
            "default OFF — Telemetry --emit-events 와 동일 패턴 (기존 사용자 영향 0)."
        ),
    )
    parser.add_argument(
        "--enable-strategist", dest="enable_strategist", action="store_true", default=False,
        help=(
            "v13 Phase 2 — 본부 1 System Refactoring Strategist opt-in. "
            "Auto-Fix Coordinator 가 escalate 결정 시 Strategist 가 events.jsonl "
            "+ verdict 시퀀스를 분석해 *이사회 안건* markdown 발제. "
            "default OFF — Phase 4 의결권 활성화 전까지 안건은 보존만."
        ),
    )
    parser.add_argument(
        "--enable-boardroom", dest="enable_boardroom", action="store_true", default=False,
        help=(
            "v13 Phase 3 — 본부 10 Boardroom 회의실 인프라 opt-in. "
            "Strategist 안건 발제 시 Boardroom Facilitator 가 BoardroomSession 생성 + "
            "goal_alignment_check/budget_brake Placeholder 실행 + 회의록 markdown 저장. "
            "default OFF — Phase 4 의결권 활성화 전까지 회의록 보존만 (자동 적용 X)."
        ),
    )
    parser.add_argument(
        "--enable-tikitaka", dest="enable_tikitaka", action="store_true", default=False,
        help=(
            "v13 Phase 5.4 — Boardroom 진입 후 *3 라운드 양방향 토론* opt-in. "
            "Cross-Agent Consultant 가 proposer → reviewer → dissenter → mediator "
            "sequence 진행. dissent 자동 감지로 Round 1→2→3 진입. decision.yaml "
            "schema v2 (rounds[] + consensus) 산출. "
            "default OFF — --enable-boardroom 와 함께 사용 (boardroom 비활성 시 무시)."
        ),
    )
    parser.add_argument(
        "--force-cli", action="store_true", default=False,
        help="Track A 에서 GUI 분기 비활성 → CLI 산출 강제 (active 4/4 도달).",
    )
    parser.add_argument(
        "--release", action="store_true", default=False,
        help="gh release create --draft 활성 (gh CLI + --repo 필수).",
    )
    parser.add_argument(
        "--repo", default="",
        help="GitHub repo (예: 'owner/name'). --release 시 필수.",
    )
    parser.add_argument(
        "--tag", default="",
        help="Track B release tag (예: 'v0.1.0-demo'). --release 시 필수.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="CrewAI 중간 로그 출력.",
    )
    parser.add_argument(
        "--non-interactive", action="store_true", default=False,
        help="인터랙티브 prompt 비활성 — --request 필수.",
    )
    parser.add_argument(
        "--no-vision-qa", action="store_true", default=False,
        help=(
            "PR #141 Phase 2 — Vision QA 강제 skip. 기본은 --build 시 자동 활성. "
            "pyautogui/Vision API 미설치 환경에서 강제 차단할 때 사용."
        ),
    )
    parser.add_argument(
        "--vision-qa-max-retries", type=int, default=1,
        help=(
            "PR #151 — Vision QA 실패 시 Engineer + Build 재호출 횟수 (기본 1). "
            "0 으로 설정하면 retry 비활성 (PR #150 의 verdict 가시화만). "
            "풀체인 (~25min) 이 아닌 Engineer + Build (~5min) 만 재실행."
        ),
    )
    parser.add_argument(
        "--auto-iterate", dest="auto_iterate", action="store_true", default=True,
        help=(
            "PR #163 (2026-05-18) — 기본 ON 으로 전환. Track A/B 진입을 "
            "run_iterative_loop (자기 진화 루프) 로 사용. Convergence Judge 가 "
            "COMPLETE/BLOCKED 판정할 때까지 최대 --max-iterations 회 "
            "(recall→kickoff→chain→sandbox→gap→judge→retrospective→curate cycle). "
            "비용 주의 — iter 당 ~25min × 최대 N. 명시 OFF 는 --no-auto-iterate."
        ),
    )
    parser.add_argument(
        "--no-auto-iterate", dest="auto_iterate", action="store_false",
        help=(
            "PR #163 — auto-iterate 명시 OFF (1회 실행, 자기 진화 cycle 없음). "
            "CI/스크립트 자동화 등 빠른 1회 실행이 필요한 경우 사용."
        ),
    )
    parser.add_argument(
        "--max-iterations", type=int, default=3,
        help=(
            "PR #163 (2026-05-18) — 기본 5 → 3 으로 하향 (보수적). auto-iterate "
            "시 최대 iteration 횟수. 1 로 설정하면 사실상 1회 실행. 사용자 대기 "
            "시간 소지감 + 비용 폭증 회피."
        ),
    )
    parser.add_argument(
        "--forced-domain", dest="forced_domain",
        choices=["web_scraping", "desktop_automation", "api_integration", "data_parser", "devops"],
        default=None,
        help=(
            "PR #183 — Track B 도메인 자동 분류 우회 (PR #172 의 C 옵션). 지정 시 "
            "휴리스틱/LLM fallback 무시 + 해당 도메인 강제. 예: "
            "`--track B --forced-domain web_scraping`. Track A 에서는 무시 (warning)."
        ),
    )
    parser.add_argument(
        "--emit-events", dest="emit_events", default=None,
        help=(
            "PR #187 Sprint 4 — Tauri 데스크탑 앱 prerequisite. JSON Lines 형식의 "
            "에이전트 이벤트 stream (AgentStatusEvent / AgentMessageEvent / "
            "IterationProgressEvent / ResultEvent) 을 지정 경로에 append. "
            "default OFF — 기존 사용자 영향 0. 환경변수 NEXUS_TELEMETRY_PATH 와 "
            "동등 (flag 가 env var 를 set). 예: --emit-events events.jsonl"
        ),
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    _print_banner()
    args = _parse_args(argv)

    # 0. PR #187 Sprint 4 — Telemetry hook 활성화 (가장 먼저, 이후 emit 가 누락되지 않도록).
    # --emit-events <path> 가 명시되면 NEXUS_TELEMETRY_PATH env var 를 set. 비어 있으면 no-op.
    # singleton 이 lazy 초기화이므로 env var 만 set 하면 이후 emit 자동 활성.
    if getattr(args, "emit_events", None):
        emit_path = Path(args.emit_events).expanduser().resolve()
        os.environ["NEXUS_TELEMETRY_PATH"] = str(emit_path)
        # 이미 초기화된 싱글톤이 있다면 (test 등) 리셋 — production main 진입 시점은 첫 진입이므로 safe.
        try:
            from src.monitoring import TelemetryEmitter
            TelemetryEmitter.reset_for_tests()
        except Exception:  # noqa: BLE001
            pass
        print(f"  Telemetry: {emit_path}")

    # 1. 자연어 요청
    if not args.request:
        if args.non_interactive:
            print("✗ --non-interactive 모드 — --request 필수.", file=sys.stderr)
            return 2
        args.request = _prompt_request()
        if not args.request:
            print("✗ 빈 요청 — 종료.", file=sys.stderr)
            return 2

    # 2. Track 결정
    if args.track == "auto":
        detected = _detect_track(args.request)
        if args.non_interactive:
            args.track = detected
        else:
            args.track = _prompt_track(detected)

    # 2.4. PR #183 — --forced-domain Track A warning (변환 자체는 _run_track_b 에서 수행)
    if args.forced_domain and args.track == "A":
        print(
            f"[WARN] --forced-domain={args.forced_domain} 은 Track A 에서 영향 없음 (무시).",
            file=sys.stderr,
        )

    # 2.5. Build 결정 (PR #115) — --build 미지정 + 인터랙티브 모드일 때 별도 prompt.
    # Track 선택 ('a'/'b' 키) 와 Build 옵션 ('b') 입력 혼동 방지.
    if not args.build and not args.non_interactive:
        args.build = _prompt_build()

    # 3. release 검증
    if args.release:
        if not args.repo:
            print("✗ --release 사용 시 --repo 필수 (예: 'owner/name').", file=sys.stderr)
            return 2

    # 4. 실행 summary
    _print_section("실행 시작")
    print(f"  Track    : {args.track}")
    print(f"  Request  : {args.request!r}")
    print(f"  Build    : {args.build}")
    print(f"  Release  : {args.release}")
    if args.repo:
        print(f"  Repo     : {args.repo}")
    print()

    # 4.5. PR #163 (2026-05-18) — auto-iterate 비용 안내 banner.
    # 기본 ON 으로 전환됨에 따라 *명시 opt-in 이 아닌 사용자* 도 자기 진화 cycle 진입 →
    # 최악 비용을 *진입 전* 보여주고 confirm 받기. non-interactive 모드는 안내만.
    if args.auto_iterate:
        if not _confirm_auto_iterate_cost(args):
            print("✗ 사용자 중단 (auto-iterate cost confirm).", file=sys.stderr)
            return 1

    try:
        if args.track == "A":
            return _run_track_a(args)
        else:
            return _run_track_b(args)
    except KeyboardInterrupt:
        print("\n✗ 사용자 중단.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ 실행 실패: {exc!r}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
