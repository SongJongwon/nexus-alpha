# -*- coding: utf-8 -*-
"""src/workflows/qa_feedback_loop.py 회귀 방지 테스트 (PR #48).

duck typing 입력으로 evaluate_qa_results / build_feedback_message_for_engineer
의 결정 로직 단위 검증. 다른 PR 들의 구체 클래스에 의존 안 함.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from src.workflows.qa_feedback_loop import (
    QAFeedbackDecision,
    build_feedback_message_for_engineer,
    detect_artifact_category,
    evaluate_qa_results,
)


# ---------------------------------------------------------------------------
# duck-type stub — 4종 QA 결과 흉내
# ---------------------------------------------------------------------------


@dataclass
class FakeQAResult:
    success: bool
    skipped: bool = False
    line: Optional[str] = None

    def summary_line(self) -> str:
        return self.line or ("PASS" if self.success else "FAIL")


@dataclass
class FakePytestResult:
    """CodeQAResult.pytest 흉내 — exit_code 만 확인."""
    exit_code: int


@dataclass
class FakeCodeQAResult:
    """CodeQAResult 흉내 — pytest 중첩 attr 노출 (PR #50 SKIPPED 규칙용)."""
    success: bool
    pytest: FakePytestResult
    skipped: bool = False
    line: Optional[str] = None

    def summary_line(self) -> str:
        return self.line or ("PASS" if self.success else "FAIL")


# ---------------------------------------------------------------------------
# evaluate_qa_results 결정 로직
# ---------------------------------------------------------------------------


def test_all_pass_overall_passed_no_retry() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="[CODE_QA PASS]"),
        "functional": FakeQAResult(success=True, line="[FUNCTIONAL PASS]"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True
    assert d.should_retry is False
    assert d.failed_qa_tools == []


def test_one_failure_should_retry_when_budget_left() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="PASS"),
        "functional": FakeQAResult(success=False, line="FAIL"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is False
    assert d.should_retry is True
    assert d.failed_qa_tools == ["functional"]


def test_failure_with_budget_exhausted_no_retry() -> None:
    results = {"code_qa": FakeQAResult(success=False, line="FAIL")}
    d = evaluate_qa_results(results, retry_count=3, max_retries=3)
    assert d.overall_passed is False
    assert d.should_retry is False  # budget exhausted


def test_skipped_tool_not_counted_as_failure() -> None:
    """skipped=True 는 실패 집계 제외 — 환경 미구비는 결함이 아님."""
    results = {
        "code_qa": FakeQAResult(success=True, line="PASS"),
        "gui": FakeQAResult(success=False, skipped=True, line="SKIPPED"),
        "robustness": FakeQAResult(success=True, line="PASS"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True  # gui skipped → 집계 제외
    assert d.failed_qa_tools == []
    assert d.skipped_qa_tools == ["gui"]


def test_none_result_treated_as_unrun() -> None:
    """None 값은 *해당 도구 미실행* 로 간주 — 실패 / skipped 어느 쪽도 아님."""
    results = {
        "code_qa": FakeQAResult(success=True),
        "functional": None,
        "gui": None,
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True
    assert d.failed_qa_tools == []
    assert d.skipped_qa_tools == []


def test_multiple_failures_collected() -> None:
    results = {
        "code_qa": FakeQAResult(success=False),
        "functional": FakeQAResult(success=False),
        "gui": FakeQAResult(success=True),
    }
    d = evaluate_qa_results(results, retry_count=1, max_retries=3)
    assert d.overall_passed is False
    assert set(d.failed_qa_tools) == {"code_qa", "functional"}


def test_retry_count_at_max_no_retry() -> None:
    results = {"code_qa": FakeQAResult(success=False)}
    d = evaluate_qa_results(results, retry_count=3, max_retries=3)
    assert d.should_retry is False


def test_summary_lines_collected() -> None:
    results = {
        "code_qa": FakeQAResult(success=True, line="[CODE_QA PASS] 5p/0f"),
        "functional": FakeQAResult(success=False, line="[FUNCTIONAL FAIL] 2/10"),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert any("CODE_QA PASS" in line for line in d.summary_lines)
    assert any("FUNCTIONAL FAIL" in line for line in d.summary_lines)


# ---------------------------------------------------------------------------
# QAFeedbackDecision.summary_line
# ---------------------------------------------------------------------------


def test_decision_summary_line_pass() -> None:
    d = QAFeedbackDecision(
        overall_passed=True,
        should_retry=False,
        retry_count=0,
        max_retries=3,
    )
    assert "QA_LOOP PASS" in d.summary_line()


def test_decision_summary_line_retry() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=1,
        max_retries=3,
        failed_qa_tools=["code_qa", "functional"],
    )
    line = d.summary_line()
    assert "RETRY" in line
    assert "code_qa" in line


def test_decision_summary_line_budget_exhausted() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=False,
        retry_count=3,
        max_retries=3,
        failed_qa_tools=["code_qa"],
    )
    line = d.summary_line()
    assert "BUDGET_EXHAUSTED" in line


# ---------------------------------------------------------------------------
# build_feedback_message_for_engineer
# ---------------------------------------------------------------------------


def test_build_message_pass_no_correction_needed() -> None:
    d = QAFeedbackDecision(
        overall_passed=True, should_retry=False, retry_count=0, max_retries=3
    )
    msg = build_feedback_message_for_engineer(d)
    assert "보정 불필요" in msg
    assert "모든 QA 도구 통과" in msg


def test_build_message_includes_failed_tools() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["code_qa", "functional"],
        summary_lines=[
            "code_qa: [CODE_QA FAIL] 2p/3f",
            "functional: [FUNCTIONAL FAIL] 5/10",
        ],
    )
    msg = build_feedback_message_for_engineer(d)
    assert "CODE_QA FAIL" in msg
    assert "FUNCTIONAL FAIL" in msg
    assert "재생성 지시" in msg


def test_build_message_includes_full_reports() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["code_qa"],
    )
    full_reports = {"code_qa": "## Code QA 보고서\n\n### 1. 종합 판정\n..."}
    msg = build_feedback_message_for_engineer(d, full_qa_reports=full_reports)
    assert "## Code QA 보고서" in msg
    assert "code_qa 보고서 (전문)" in msg


def test_build_message_includes_skipped_section() -> None:
    d = QAFeedbackDecision(
        overall_passed=False,
        should_retry=True,
        retry_count=0,
        max_retries=3,
        failed_qa_tools=["functional"],
        skipped_qa_tools=["gui"],
    )
    msg = build_feedback_message_for_engineer(d)
    assert "SKIPPED" in msg
    assert "gui" in msg


def test_build_message_includes_retry_metadata() -> None:
    d = QAFeedbackDecision(
        overall_passed=False, should_retry=True, retry_count=1, max_retries=3
    )
    msg = build_feedback_message_for_engineer(d)
    assert "retry_count=1" in msg
    assert "max_retries=3" in msg


# ---------------------------------------------------------------------------
# PR #50 — pytest exit=5 (no tests collected) → SKIPPED
# ---------------------------------------------------------------------------


def test_pytest_exit_5_treated_as_skipped() -> None:
    """워크플로가 pytest 스위트를 안 만들면 (exit=5) FAIL 이 아니라 SKIPPED."""
    code_qa = FakeCodeQAResult(
        success=False,
        pytest=FakePytestResult(exit_code=5),
        line="[CODE_QA FAIL] no tests",
    )
    results = {
        "code_qa": code_qa,
        "functional": FakeQAResult(success=True),
    }
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is True
    assert "code_qa" in d.skipped_qa_tools
    assert d.failed_qa_tools == []
    assert any("no tests collected" in line for line in d.summary_lines)


def test_pytest_exit_other_than_5_still_fails() -> None:
    """pytest exit_code≠5 (실 테스트 실패) 는 그대로 FAIL 집계."""
    code_qa = FakeCodeQAResult(
        success=False,
        pytest=FakePytestResult(exit_code=1),
    )
    results = {"code_qa": code_qa}
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is False
    assert "code_qa" in d.failed_qa_tools
    assert "code_qa" not in d.skipped_qa_tools


def test_pytest_exit_5_with_pass_status_still_marked_skipped() -> None:
    """pytest exit=5 는 success 여부와 무관하게 SKIPPED — 게이트 역할 없음."""
    code_qa = FakeCodeQAResult(
        success=True,  # 테스트 0개도 success=True 가 가능 (executor 정책)
        pytest=FakePytestResult(exit_code=5),
    )
    d = evaluate_qa_results({"code_qa": code_qa}, retry_count=0, max_retries=3)
    assert "code_qa" in d.skipped_qa_tools


# ---------------------------------------------------------------------------
# PR #50 — artifact_category="gui" → functional/robustness 자동 SKIPPED
# ---------------------------------------------------------------------------


def test_gui_category_skips_functional_and_robustness() -> None:
    """GUI 산출물에 stdin 기반 도구 부적합 → 강제 SKIPPED."""
    results = {
        "code_qa": FakeQAResult(success=True),
        "functional": FakeQAResult(success=False, line="[FUNCTIONAL FAIL] 0/10"),
        "robustness": FakeQAResult(success=False, line="[ROBUSTNESS FAIL] 0/9"),
        "gui": FakeQAResult(success=True, line="[GUI PASS]"),
    }
    d = evaluate_qa_results(
        results, retry_count=0, max_retries=3, artifact_category="gui"
    )
    assert d.overall_passed is True
    assert d.failed_qa_tools == []
    assert "functional" in d.skipped_qa_tools
    assert "robustness" in d.skipped_qa_tools


def test_cli_category_does_not_skip_functional() -> None:
    """CLI 산출물에서는 functional/robustness 정상 평가."""
    results = {"functional": FakeQAResult(success=False)}
    d = evaluate_qa_results(
        results, retry_count=0, max_retries=3, artifact_category="cli"
    )
    assert d.overall_passed is False
    assert "functional" in d.failed_qa_tools


def test_default_category_none_preserves_legacy_behavior() -> None:
    """artifact_category 미지정 시 backwards compat — 기존 6개 테스트 유효."""
    results = {"functional": FakeQAResult(success=False)}
    d = evaluate_qa_results(results, retry_count=0, max_retries=3)
    assert d.overall_passed is False
    assert "functional" in d.failed_qa_tools


def test_gui_category_does_not_skip_code_qa_or_gui() -> None:
    """GUI 카테고리는 functional/robustness 만 skip — code_qa / gui 는 유효 게이트."""
    results = {
        "code_qa": FakeQAResult(success=False),
        "gui": FakeQAResult(success=False),
    }
    d = evaluate_qa_results(
        results, retry_count=0, max_retries=3, artifact_category="gui"
    )
    assert d.overall_passed is False
    assert set(d.failed_qa_tools) == {"code_qa", "gui"}


# ---------------------------------------------------------------------------
# PR #50 — detect_artifact_category 휴리스틱
# ---------------------------------------------------------------------------


def test_detect_gui_from_tkinter_import(tmp_path) -> None:
    script = tmp_path / "calc.py"
    script.write_text(
        "import tkinter as tk\nroot = tk.Tk()\nroot.mainloop()\n",
        encoding="utf-8",
    )
    assert detect_artifact_category(target_script=script) == "gui"


def test_detect_gui_from_pyqt_import(tmp_path) -> None:
    script = tmp_path / "app.py"
    script.write_text(
        "from PyQt5.QtWidgets import QApplication\n", encoding="utf-8"
    )
    assert detect_artifact_category(target_script=script) == "gui"


def test_detect_gui_from_pyside6(tmp_path) -> None:
    script = tmp_path / "app.py"
    script.write_text(
        "from PySide6.QtWidgets import QMainWindow\n", encoding="utf-8"
    )
    assert detect_artifact_category(target_script=script) == "gui"


def test_detect_cli_from_argparse(tmp_path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(
        "import argparse\nparser = argparse.ArgumentParser()\n",
        encoding="utf-8",
    )
    assert detect_artifact_category(target_script=script) == "cli"


def test_detect_cli_from_sys_argv(tmp_path) -> None:
    script = tmp_path / "main.py"
    script.write_text(
        "import sys\nname = sys.argv[1]\nprint(name)\n", encoding="utf-8"
    )
    assert detect_artifact_category(target_script=script) == "cli"


def test_detect_library_when_no_markers(tmp_path) -> None:
    script = tmp_path / "lib.py"
    script.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert detect_artifact_category(target_script=script) == "library"


def test_detect_unknown_when_paths_missing(tmp_path) -> None:
    nonexistent = tmp_path / "missing.py"
    assert detect_artifact_category(target_script=nonexistent) == "unknown"


def test_detect_unknown_when_no_inputs() -> None:
    assert detect_artifact_category() == "unknown"


def test_detect_gui_fallback_when_only_exe_present(tmp_path) -> None:
    """source 미가용 + .exe 만 존재 시 보수적으로 GUI 추정."""
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ\x00\x00")
    assert detect_artifact_category(target_exe=exe) == "gui"


def test_detect_gui_takes_precedence_over_cli_when_both_imports(tmp_path) -> None:
    """동일 파일에 GUI + CLI 마커 둘 다 있으면 GUI 우선 (사용자 대면 = GUI)."""
    script = tmp_path / "hybrid.py"
    script.write_text(
        "import argparse\nimport tkinter as tk\n", encoding="utf-8"
    )
    assert detect_artifact_category(target_script=script) == "gui"


# ---------------------------------------------------------------------------
# PR #95 — external_dependent 카테고리 (Track B 도메인 산출 functional/robustness
# SKIP 메커니즘)
# ---------------------------------------------------------------------------


def test_detect_external_dependent_when_playwright_missing(
    tmp_path, monkeypatch
) -> None:
    """Track B web_scraping 산출 (playwright import) + .venv 미설치 → external_dependent."""
    script = tmp_path / "scrape.py"
    script.write_text(
        "from playwright.async_api import async_playwright\n"
        "import asyncio\n",
        encoding="utf-8",
    )
    # importlib.util.find_spec 가 playwright 미설치 시뮬레이션
    import importlib.util

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "playwright":
            return None  # 미설치
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    assert detect_artifact_category(target_script=script) == "external_dependent"


def test_detect_library_when_dep_actually_installed(tmp_path, monkeypatch) -> None:
    """dep import + .venv 설치됨 → library (정상 가동 가능)."""
    script = tmp_path / "scrape.py"
    script.write_text(
        "import requests\nfrom bs4 import BeautifulSoup\n",
        encoding="utf-8",
    )
    # 모든 dep 가 설치된 것처럼 시뮬레이션
    import importlib.util

    real_find_spec = importlib.util.find_spec

    class _FakeSpec:
        pass

    def fake_find_spec(name, *args, **kwargs):
        if name in ("requests", "bs4"):
            return _FakeSpec()
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    # library 분류 (GUI/CLI 마커 없음 + external dep 모두 설치)
    assert detect_artifact_category(target_script=script) == "library"


def test_detect_external_dependent_with_multiple_deps_one_missing(
    tmp_path, monkeypatch
) -> None:
    """여러 dep 중 *하나라도* 미설치 시 external_dependent."""
    script = tmp_path / "app.py"
    script.write_text(
        "import requests\n"
        "from playwright.async_api import async_playwright\n",
        encoding="utf-8",
    )
    import importlib.util

    real_find_spec = importlib.util.find_spec

    class _FakeSpec:
        pass

    def fake_find_spec(name, *args, **kwargs):
        if name == "requests":
            return _FakeSpec()  # 설치됨
        if name == "playwright":
            return None  # 미설치
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    assert detect_artifact_category(target_script=script) == "external_dependent"


def test_detect_external_dependent_takes_precedence_over_cli_when_deps_missing(
    tmp_path, monkeypatch
) -> None:
    """PR #96 — argparse + playwright 미설치 → external_dependent (CLI 우선 X).

    배경: PR #95 우선순위는 CLI > external_dependent 였으나, PR #96 검증에서
    scrape.py 가 argparse + playwright 둘 다 import 시 CLI 분류 → functional
    /robustness 정상 실행 → ModuleNotFoundError 회귀 발견. subprocess 가 dep
    미설치로 fail 하면 CLI 의미 무관 — external_dependent 가 *우선*해야 의미적
    SKIP 가능.
    """
    script = tmp_path / "cli_with_missing_dep.py"
    script.write_text(
        "import argparse\n"
        "from playwright.async_api import async_playwright\n",
        encoding="utf-8",
    )
    import importlib.util

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **kw: None,  # 전부 미설치
    )
    # PR #96 — dep 미설치 시 external_dependent 우선 (CLI 마커 무시)
    assert detect_artifact_category(target_script=script) == "external_dependent"


def test_detect_cli_when_all_deps_installed(
    tmp_path, monkeypatch
) -> None:
    """PR #96 — argparse + dep 모두 설치됨 → cli (정상 실행 가능 + CLI 의미)."""
    script = tmp_path / "cli_with_installed_dep.py"
    script.write_text(
        "import argparse\nimport requests\n",
        encoding="utf-8",
    )
    import importlib.util

    class _FakeSpec:
        pass

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "requests":
            return _FakeSpec()  # 설치됨
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    # dep 모두 설치 → cli 분류 (functional/robustness 정상 가동 가능)
    assert detect_artifact_category(target_script=script) == "cli"


def test_detect_gui_takes_precedence_over_external_dependent(
    tmp_path, monkeypatch
) -> None:
    """PR #96 — GUI > external_dependent (PR #50 기존 동작 보존).

    GUI 카테고리는 stdin 기반 도구가 event loop 와 미스매치이므로 어쨌든 SKIP.
    external_dependent 도 같은 SKIP 결과 — GUI 우선해도 외부 동작 변화 없음.
    """
    script = tmp_path / "gui_with_missing_dep.py"
    script.write_text(
        "import tkinter as tk\n"
        "from playwright.async_api import async_playwright\n",
        encoding="utf-8",
    )
    import importlib.util

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **kw: None,
    )
    # GUI 우선 (PR #50 기존 동작)
    assert detect_artifact_category(target_script=script) == "gui"


def test_external_dependent_category_skips_functional_and_robustness() -> None:
    """external_dependent 카테고리 → functional/robustness SKIPPED (PR #95)."""
    results = {
        "code_qa": FakeQAResult(success=True),
        "functional": FakeQAResult(success=False, line="[FUNCTIONAL FAIL] 0/10"),
        "robustness": FakeQAResult(success=False, line="[ROBUSTNESS FAIL] 0/9"),
        "gui": FakeQAResult(success=True, line="[GUI PASS]"),
    }
    d = evaluate_qa_results(
        results,
        retry_count=0,
        max_retries=3,
        artifact_category="external_dependent",
    )
    assert d.overall_passed is True
    assert d.failed_qa_tools == []
    assert "functional" in d.skipped_qa_tools
    assert "robustness" in d.skipped_qa_tools
    # SKIPPED summary 본문에 PR #95 명시 (추적성)
    summary = " ".join(d.summary_lines)
    assert "PR #95" in summary or "external" in summary.lower()


def test_external_dependent_does_not_skip_code_qa_or_gui() -> None:
    """external_dependent 는 functional/robustness 만 SKIP — code_qa / gui 는 유효 게이트."""
    results = {
        "code_qa": FakeQAResult(success=False),
        "gui": FakeQAResult(success=False),
    }
    d = evaluate_qa_results(
        results,
        retry_count=0,
        max_retries=3,
        artifact_category="external_dependent",
    )
    assert d.overall_passed is False
    assert set(d.failed_qa_tools) == {"code_qa", "gui"}


def test_external_deps_list_includes_track_b_domain_keys() -> None:
    """``_EXTERNAL_DEPS`` 가 Track B 5 도메인 schema 의 핵심 dep 포함 (regression guard)."""
    from src.workflows.qa_feedback_loop import _EXTERNAL_DEPS

    # Track B schema 의 ``# file:`` 헤더와 직접 mapping 되는 도구
    assert "playwright" in _EXTERNAL_DEPS  # web_scraping
    assert "pyautogui" in _EXTERNAL_DEPS  # desktop_automation
    assert "httpx" in _EXTERNAL_DEPS  # api_integration
    assert "openpyxl" in _EXTERNAL_DEPS  # data_parser
    # devops 는 .exe 빌드 부적합 → external_dependent 회피 의도
