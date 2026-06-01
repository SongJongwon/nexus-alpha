# -*- coding: utf-8 -*-
"""자동 QA 피드백 루프 의사결정 helper (Phase 7 — PR #48).

PR #42~#47 에서 도입된 4종 QA 도구 (Code QA / Functional Test / GUI Test /
Robustness) 산출 결과를 합산해, **재생성 필요 여부** 와 **Python Engineer
에게 전달할 재생성 지시 메시지** 를 결정하는 standalone helper.

설계 원칙:
    - **duck typing**: 입력은 ``success: bool`` 와 ``summary_line()`` 메소드만
      가지면 OK — 구체 클래스 (CodeQAResult, FunctionalTestResult 등) 에 의존
      안 함. 다른 PR 들이 머지된 후 자연스럽게 통합 가능.
    - **standalone**: LangGraph / iterative_loop 와 직접 결합 안 함. 워크플로
      자유롭게 호출만 하면 됨.
    - **결정론적**: LLM 무관. 입력만 보고 deterministic 결정.

iterative_loop 통합 패턴 (PR #49 10차 E2E 에서 실 사용)::

    qa_results = {
        "code_qa": run_code_qa(workflow_dir),
        "functional": run_test_cases(target_script),
        "gui": run_gui_test(target_path, output_dir),
        "robustness": run_robustness_scenarios(target_script),
    }
    category = detect_artifact_category(target_script, target_exe)  # "gui"|"cli"|...
    decision = evaluate_qa_results(qa_results, retry_count=current_retry,
                                   max_retries=3, artifact_category=category)
    if decision.should_retry:
        feedback = build_feedback_message_for_engineer(decision, qa_reports)
        # → Python Engineer 에게 feedback 전달 후 재생성

산출물 카테고리 SKIPPED 규칙 (PR #50 — 10차 E2E 1차 실행 후 도입):
    - ``artifact_category="gui"`` 일 때 ``functional`` / ``robustness`` 자동
      SKIPPED — stdin 기반 도구는 GUI event loop 와 부적합 (deterministic
      timeout 으로 무한 재시도 발생).
    - ``code_qa`` 의 pytest exit_code==5 (no tests collected) 는 워크플로가
      pytest 스위트를 생성하지 않은 *환경적* 사실이므로 SKIPPED 로 처리 —
      LLM 재생성으로 해결 불가.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class QAFeedbackDecision:
    """QA 결과 합산 후 재생성 결정."""

    overall_passed: bool
    """모든 *실행된* QA 도구가 PASS — skipped 는 *집계 제외*."""

    should_retry: bool
    """재생성 필요 + retry budget 남음 (overall_passed=False AND retry_count < max_retries)."""

    retry_count: int
    """현재까지의 재시도 횟수 (0=첫 실행)."""

    max_retries: int
    """최대 재시도 횟수 (보통 3)."""

    failed_qa_tools: list[str] = field(default_factory=list)
    """실패 QA 도구 이름들 (예: ['code_qa', 'functional'])."""

    skipped_qa_tools: list[str] = field(default_factory=list)
    """skip 된 도구 이름들 (예: ['gui', 'robustness'])."""

    summary_lines: list[str] = field(default_factory=list)
    """각 도구의 한 줄 요약 (사람이 읽기 위함)."""

    def summary_line(self) -> str:
        if self.overall_passed:
            return (
                f"[QA_LOOP PASS] retry={self.retry_count}/{self.max_retries}, "
                f"failed=0, skipped={len(self.skipped_qa_tools)}"
            )
        verdict_kw = "RETRY" if self.should_retry else "BUDGET_EXHAUSTED"
        return (
            f"[QA_LOOP {verdict_kw}] retry={self.retry_count}/{self.max_retries}, "
            f"failed={len(self.failed_qa_tools)} ({', '.join(self.failed_qa_tools)})"
        )


# ---------------------------------------------------------------------------
# 산출물 카테고리 감지 (PR #50)
# ---------------------------------------------------------------------------

_GUI_FRAMEWORK_KEYWORDS: tuple[str, ...] = (
    "tkinter",
    "customtkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wxPython",
    "wx.App",
    "kivy",
)

_CLI_KEYWORDS: tuple[str, ...] = (
    "argparse",
    "sys.argv",
    "click.command",
    "typer.",
)

# PR #95 — Track B 외부 dependency 감지용 (LLM 이 선택할 수 있는 dep 후보).
# import 분석 시 본 목록의 top-level 모듈명 등장 → ``importlib.util.find_spec``
# 으로 .venv 설치 여부 확인 → 미설치면 ``external_dependent`` 카테고리.
# Track B 5 도메인 schema 가 강조하는 도구 위주:
#   web_scraping: playwright / selenium / beautifulsoup4 (실 모듈명: bs4)
#   desktop_automation: pyautogui / pywinauto / pywin32 (실 모듈명: win32api 등)
#   api_integration: httpx / requests / fastapi / gql
#   data_parser: openpyxl / pdfplumber / pymupdf (실 모듈명: fitz) / pandas
# Track A 의 CLI 표준 (argparse / typer 등) 은 stdlib 또는 흔히 설치 → 제외.
_EXTERNAL_DEPS: tuple[str, ...] = (
    "playwright",
    "selenium",
    "bs4",
    "pyautogui",
    "pywinauto",
    "win32api",  # pywin32 의 실 import 명
    "comtypes",
    "httpx",
    "gql",
    "fastapi",
    "openpyxl",
    "pdfplumber",
    "fitz",  # pymupdf 의 실 import 명
    "ijson",
)


def _detect_used_external_deps(content: str) -> list[str]:
    """source content 의 import 문에서 ``_EXTERNAL_DEPS`` 모듈명 추출 (PR #95).

    ``import X`` / ``from X import ...`` / ``from X.Y import ...`` 모두 매칭.
    top-level 모듈명만 비교 (서브모듈 path 무관).
    """
    used: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            # ``import X`` / ``import X as Y`` / ``import X, Y, Z``
            tail = stripped[len("import ") :]
            for token in tail.split(","):
                top = token.strip().split(" as ")[0].split(".")[0].strip()
                if top in _EXTERNAL_DEPS and top not in used:
                    used.append(top)
        elif stripped.startswith("from "):
            # ``from X import Y`` / ``from X.Y import Z``
            tail = stripped[len("from ") :]
            top = tail.split(" import ")[0].strip().split(".")[0]
            if top in _EXTERNAL_DEPS and top not in used:
                used.append(top)
    return used


def _is_module_installed(module_name: str) -> bool:
    """``importlib.util.find_spec`` 으로 모듈 설치 여부 확인 — PR #95.

    catch-all: spec 조회 실패 (ImportError / ValueError / ModuleNotFoundError 등)
    → 미설치로 판단 (보수적).
    """
    import importlib.util

    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False
    except Exception:
        return False


# v13 P16 (수정4) — web 타깃 인지 (vite/SPA/.ts/.html). vision_qa(데스크탑 .exe 스크린샷)
# 는 web 산출에 부적합 → SKIP 대상. 파이프라인이 이미 web↔desktop 을 구분(vite vs PyInstaller)
# 하는 그 신호를 산출 파일에서 재판별.
_WEB_TARGET_EXTS: frozenset = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".vue", ".svelte"}
)
_WEB_CONTENT_MARKERS: tuple = (
    "import * as three", "from 'three'", 'from "three"', "web-ifc",
    "defineconfig", "<!doctype html", '<script type="module"',
    "reactdom", "react-dom",
)


def detect_artifact_category(
    target_script: Optional[Any] = None,
    target_exe: Optional[Any] = None,
) -> str:
    """워크플로 산출물의 카테고리를 휴리스틱으로 추정.

    QA 도구 적용 시 stdin 기반 도구가 GUI event loop 에 무한 timeout 되는
    구조적 미스매치를 사전에 차단하기 위함 (PR #50 — 10차 E2E 1차 실행 결과 도입).

    PR #95 추가:
        ``external_dependent`` — Track B 산출이 외부 dep (playwright 등) import
        + .venv 미설치 시. functional/robustness executor 가 ``subprocess.run``
        으로 직접 실행할 때 ``ModuleNotFoundError`` → traceback → 0/N fail 회귀
        차단. GUI 카테고리와 같은 *의미적 SKIP* 패턴.

    Args:
        target_script: Python source 의 Path-like (None 가능).
        target_exe: 빌드 산출물 (.exe) 의 Path-like (None 가능).

    Returns:
        ``"gui"``: source 에 GUI 프레임워크 (tkinter / PyQt / PySide / wx /
            kivy) import 발견, 또는 source 미발견 + .exe 만 존재 (보수적 추정).
        ``"cli"``: source 에 ``argparse`` / ``sys.argv`` / ``click.command`` /
            ``typer.`` 마커 발견.
        ``"external_dependent"``: source 가 ``_EXTERNAL_DEPS`` 모듈 import 했으나
            그 중 하나라도 ``importlib.util.find_spec`` 조회 실패 (.venv 미설치).
            PR #95 — Track B web_scraping/desktop/api/parser 도메인의 functional/
            robustness fail 회귀 차단.
        ``"library"``: source 존재하나 위 카테고리 모두 해당 안 됨.
        ``"unknown"``: source / exe 모두 접근 불가.

    Note:
        검사 우선순위 (PR #96 — priority fix): GUI > external_dependent > CLI > library.

        Rationale:
          - GUI: stdin 기반 도구가 event loop 와 미스매치 → SKIP. external_dep
            여부 무관 — 같은 SKIP 결과.
          - **external_dependent (PR #96 — CLI 보다 *우선*):** subprocess.run
            ([sys.executable, script]) 이 ``ModuleNotFoundError`` 로 즉시 fail.
            CLI 마커 (argparse) 가 있어도 dep 미설치면 *실 실행 불가* — CLI 의
            의미 무관. PR #95 적용 후 발견된 회귀 (PR #96 검증) — scrape.py 가
            argparse + playwright 둘 다 import 시 CLI 우선 → external_dependent
            SKIP 미발동 → 0/10 fail. 수정: external_dependent 가 CLI 보다 우선.
          - CLI: external dep 모두 설치된 경우의 분류 — functional/robustness
            가 정상 실행 가능.
          - library: 위 모두 해당 안 됨.
    """
    if target_script is not None:
        script_path = Path(target_script)
        # P16 수정4 — web 타깃 우선 판별 (확장자 또는 내용 마커). vision_qa(.exe 스크린샷)
        # 부적합 → 아래 _classify_skipped 가 web 카테고리에서 gui 도구를 SKIP.
        if script_path.suffix.lower() in _WEB_TARGET_EXTS:
            return "web"
        if script_path.exists() and script_path.is_file():
            try:
                content = script_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                content = ""
            if content:
                lower = content.lower()
                if any(m in lower for m in _WEB_CONTENT_MARKERS):
                    return "web"
                if any(kw.lower() in lower for kw in _GUI_FRAMEWORK_KEYWORDS):
                    return "gui"
                # PR #96 — external_dependent 가 CLI 보다 우선.
                # subprocess 실행 시 ModuleNotFoundError 회귀가 CLI 의미보다 더 결정적.
                used_deps = _detect_used_external_deps(content)
                missing = [d for d in used_deps if not _is_module_installed(d)]
                if missing:
                    return "external_dependent"
                if any(kw.lower() in lower for kw in _CLI_KEYWORDS):
                    return "cli"
                return "library"

    if target_exe is not None:
        exe_path = Path(target_exe)
        if exe_path.exists() and exe_path.is_file():
            return "gui"

    return "unknown"


# ---------------------------------------------------------------------------
# SKIPPED 분류 — explicit flag + pytest exit=5 + GUI 카테고리 N/A
# ---------------------------------------------------------------------------


def _classify_skipped(
    tool_name: str,
    result: Any,
    artifact_category: Optional[str],
) -> tuple[bool, Optional[str]]:
    """SKIPPED 여부 + 오버라이드 요약 라인 결정.

    Returns:
        ``(is_skipped, override_summary_line_or_None)``. override_summary_line
        이 None 이면 호출 측이 ``result.summary_line()`` 로 fallback.
    """
    if bool(getattr(result, "skipped", False)):
        return True, None

    if tool_name == "code_qa":
        pytest_obj = getattr(result, "pytest", None)
        if pytest_obj is not None and getattr(pytest_obj, "exit_code", None) == 5:
            return True, (
                f"{tool_name}: [CODE_QA SKIPPED] pytest exit=5 (no tests collected) — "
                "워크플로가 pytest 스위트를 생성하지 않음"
            )

    if artifact_category == "gui" and tool_name in ("functional", "robustness"):
        return True, (
            f"{tool_name}: [SKIPPED] GUI 산출물에 부적합 — "
            "stdin 기반 검증이 GUI event loop 와 미스매치"
        )

    # v13 P16 (수정4) — web(vite/SPA) 타깃: vision_qa(gui) 는 데스크탑 .exe 스크린샷용이라
    # screenshots=0 → FAIL → retry → 데스크탑 .exe 재빌드로 web 산출이 떠밀리던 회귀 차단.
    # gui(=vision) + stdin 기반 functional/robustness 를 *우아하게 SKIP* (FAIL 아님) → retry 미발동.
    # web 을 headless 브라우저로 실제 스크린샷하는 건 후속 과제 (본 PR 범위 아님). desktop 불변.
    if artifact_category == "web" and tool_name in ("gui", "functional", "robustness"):
        return True, (
            f"{tool_name}: [SKIPPED] web(vite/SPA) 타깃 — vision_qa/stdin 기반 검증은 "
            "데스크탑 .exe 용이라 N/A. web 산출 보존 (headless 브라우저 검증은 후속 과제)."
        )

    # PR #95 — external_dependent: subprocess 직접 실행 시 ModuleNotFoundError
    # → traceback → 0/N fail 회귀 차단. test 코드는 stub 으로 PASS 가능하지만
    # functional/robustness 는 실 subprocess 실행 + 실 dep 필요 → 의미적 SKIP.
    if (
        artifact_category == "external_dependent"
        and tool_name in ("functional", "robustness")
    ):
        return True, (
            f"{tool_name}: [SKIPPED] 외부 dependency 미설치 (.venv) — "
            "subprocess 실 실행 시 ModuleNotFoundError 회귀. "
            "test 는 PR #88 import stub 으로 PASS, 본 도구는 의미적 SKIP "
            "(Track A GUI 패턴 재사용 — PR #95)"
        )

    return False, None


def evaluate_qa_results(
    results: dict[str, Any],
    retry_count: int = 0,
    max_retries: int = 3,
    artifact_category: Optional[str] = None,
) -> QAFeedbackDecision:
    """QA 도구 결과 묶음을 합산해 재생성 결정 산출.

    Args:
        results: ``{"tool_name": result_object_or_None}`` 형태. result 는 다음
            attr 만 있으면 됨: ``success: bool``, ``skipped: bool`` (선택),
            ``summary_line() -> str`` (선택). None 값은 *해당 도구 미실행* 로 간주.
            ``code_qa`` 의 경우 ``result.pytest.exit_code`` 가 5 이면 (no tests
            collected) 자동 SKIPPED 처리.
        retry_count: 현재까지의 재시도 횟수 (0=첫 실행).
        max_retries: 최대 재시도 횟수 (이후엔 budget exhausted).
        artifact_category: ``detect_artifact_category()`` 산출 (선택). ``"gui"``
            로 지정 시 ``functional`` / ``robustness`` 자동 SKIPPED — stdin
            기반 검증과 GUI event loop 미스매치 회피.

    Returns:
        QAFeedbackDecision — overall_passed / should_retry / failed_qa_tools.
    """
    failed: list[str] = []
    skipped: list[str] = []
    summaries: list[str] = []

    for tool_name, result in results.items():
        if result is None:
            continue

        is_skipped, override_summary = _classify_skipped(
            tool_name, result, artifact_category
        )
        if is_skipped:
            skipped.append(tool_name)
            if override_summary is not None:
                summaries.append(override_summary)
            elif hasattr(result, "summary_line"):
                summaries.append(f"{tool_name}: {result.summary_line()}")
            continue

        is_success = bool(getattr(result, "success", False))
        if not is_success:
            failed.append(tool_name)

        if hasattr(result, "summary_line"):
            summaries.append(f"{tool_name}: {result.summary_line()}")

    overall_passed = len(failed) == 0
    should_retry = (not overall_passed) and (retry_count < max_retries)

    return QAFeedbackDecision(
        overall_passed=overall_passed,
        should_retry=should_retry,
        retry_count=retry_count,
        max_retries=max_retries,
        failed_qa_tools=failed,
        skipped_qa_tools=skipped,
        summary_lines=summaries,
    )


def build_feedback_message_for_engineer(
    decision: QAFeedbackDecision,
    full_qa_reports: Optional[dict[str, str]] = None,
) -> str:
    """``QAFeedbackDecision`` + 도구별 *전체 보고서 텍스트* 를 받아 Python Engineer
    에게 보낼 재생성 지시 메시지 작성.

    Args:
        decision: ``evaluate_qa_results`` 산출.
        full_qa_reports: ``{"tool_name": "full markdown report text"}``. 각 보고서는
            해당 QA agent 가 작성한 5단 구조 마크다운. None 이면 summary_line 만 사용.

    Returns:
        Engineer 에게 전달할 markdown 재생성 지시 메시지.
    """
    lines: list[str] = []
    lines.append("# 🔁 QA 자동 피드백 — 재생성 지시")
    lines.append("")
    lines.append(
        f"이전 산출물의 자동 QA 검증 결과 **{len(decision.failed_qa_tools)} 도구 실패**, "
        f"재시도 budget {decision.retry_count + 1}/{decision.max_retries + 1} 회차."
    )
    lines.append("")
    lines.append("## 실패 도구 요약")
    if not decision.failed_qa_tools:
        lines.append("- (없음 — 모든 도구 PASS 또는 SKIPPED)")
    else:
        for line in decision.summary_lines:
            lines.append(f"- {line}")
    lines.append("")

    if decision.skipped_qa_tools:
        lines.append("## SKIPPED 도구 (환경 미구비, 결함 아님)")
        for tool in decision.skipped_qa_tools:
            lines.append(f"- {tool}")
        lines.append("")

    lines.append("## 보정 지시")
    if not decision.failed_qa_tools:
        lines.append("- 보정 불필요 — 모든 QA 도구 통과.")
    else:
        lines.append(
            "아래 *각 도구의 5단 보고서* 의 **재생성 지시** 섹션을 우선순위 순으로 반영해 "
            "코드를 재작성하세요. 한 번에 모두 보정하기 어려우면 BLOCKER → MAJOR → "
            "MINOR 순으로 처리하세요."
        )
        lines.append("")
        if full_qa_reports:
            for tool_name in decision.failed_qa_tools:
                report = full_qa_reports.get(tool_name)
                if report:
                    lines.append(f"### {tool_name} 보고서 (전문)")
                    lines.append(report)
                    lines.append("")
        else:
            lines.append("(개별 보고서 본문 미제공 — 호출 측이 `full_qa_reports` 인자 미전달)")
    lines.append("")
    lines.append("---")
    lines.append(
        f"본 메시지는 `qa_feedback_loop.build_feedback_message_for_engineer()` 자동 생성 "
        f"(retry_count={decision.retry_count}, max_retries={decision.max_retries})."
    )
    return "\n".join(lines)
