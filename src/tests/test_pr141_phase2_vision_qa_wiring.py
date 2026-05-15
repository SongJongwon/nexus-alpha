# -*- coding: utf-8 -*-
"""PR #141 Phase 2 — Vision QA wiring 회귀 차단.

배경 (본인 비전 통찰 6 D-3 — 시각 검증 부재):
    ``src/agents/qa/gui_test_executor.run_gui_test`` 는 PR #133 단계에서 완성됐으나
    *production path 에서 호출 X* — 호출자는 docstring 예시 (qa_feedback_loop.py:21)
    + 별도 E2E 스크립트 (scripts/run_e2e_10th_verification.py:91) 만. 결과:

        친구 PC 의 Message_App.exe 는 *어떤 에이전트도 시각적으로 본 적 없는* .exe.

PR #141 Phase 2 처방:
    ``scripts/run.py`` 의 Track A 가 ``--build`` 로 .exe 산출 직후 자동 호출.
    ``--no-vision-qa`` 로 명시 skip 가능 (pyautogui/Vision API 미설치 환경).

본 테스트 목적 (file-text 기반 — 실제 호출은 PR #133 의 자체 테스트가 커버):
    - scripts/run.py 에 _run_vision_qa helper 존재 + run_gui_test import 호출
    - Track A 진입점이 _run_vision_qa 호출 (exe_path 가 있을 때)
    - argparse 에 --no-vision-qa 플래그 추가
    - _print_result_summary 가 vision_qa_summary 매개변수 수용
"""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


# ---------------------------------------------------------------------------
# 1. Vision QA helper 존재 + run_gui_test 사용
# ---------------------------------------------------------------------------


def test_run_py_defines_run_vision_qa_helper() -> None:
    """``_run_vision_qa`` helper 정의 — Vision wiring 진입점."""
    text = RUN_PY.read_text(encoding="utf-8")
    assert "def _run_vision_qa" in text, (
        "scripts/run.py 에 _run_vision_qa helper 누락 — Vision QA wiring 회귀"
    )


def test_run_vision_qa_imports_run_gui_test() -> None:
    """helper 내부에서 ``run_gui_test`` import — gui_test_executor 와의 연결."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_vision_qa[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None, "_run_vision_qa 함수 본문 추출 실패"
    body = match.group(0)
    assert "run_gui_test" in body, (
        "_run_vision_qa 가 run_gui_test 호출 안 함 — wiring 미완성"
    )


def test_run_vision_qa_swallows_exceptions() -> None:
    """Vision 자체 실패가 워크플로 차단 사유 아님 — try/except 패턴 확인."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_vision_qa[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "except" in body, (
        "_run_vision_qa 가 예외 격리 안 함 — Vision 실패 시 워크플로 차단 위험"
    )


# ---------------------------------------------------------------------------
# 2. Track A 진입점에서 자동 호출
# ---------------------------------------------------------------------------


def test_track_a_invokes_vision_qa_when_exe_present() -> None:
    """``_run_track_a`` 가 exe_path 가 있을 때 _run_vision_qa 호출."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "_run_vision_qa" in body, (
        "Track A 진입점이 _run_vision_qa 호출 안 함 — PR #141 Phase 2 wiring 회귀"
    )


def test_track_a_respects_no_vision_qa_flag() -> None:
    """``--no-vision-qa`` 플래그 확인 코드 존재."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "no_vision_qa" in body, (
        "Track A 가 args.no_vision_qa 확인 안 함 — 강제 skip 불가"
    )


# ---------------------------------------------------------------------------
# 3. argparse 에 --no-vision-qa 등록
# ---------------------------------------------------------------------------


def test_argparse_has_no_vision_qa_flag() -> None:
    """``argparse`` 에 --no-vision-qa 등록."""
    text = RUN_PY.read_text(encoding="utf-8")
    assert "--no-vision-qa" in text, (
        "argparse 에 --no-vision-qa 미등록 — 사용자가 skip 할 방법 없음"
    )


# ---------------------------------------------------------------------------
# 4. _print_result_summary 가 vision_qa_summary 표시
# ---------------------------------------------------------------------------


def test_print_summary_accepts_vision_summary() -> None:
    """``_print_result_summary`` 시그니처에 ``vision_qa_summary`` 매개변수."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_print_result_summary\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "vision_qa_summary" in match.group(0), (
        "_print_result_summary 가 vision_qa_summary 매개변수 누락 — 결과 화면 표시 X"
    )


# ---------------------------------------------------------------------------
# 5. main() 진입점 import 검증 — sanity check
# ---------------------------------------------------------------------------


def test_run_py_module_imports_cleanly() -> None:
    """``scripts/run.py`` 모듈이 syntax 오류 없이 import 됨.

    회귀 차단 — wiring 추가 후 syntax 에러 발생 시 즉시 차단.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("scripts_run_under_test", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 실제 실행은 안 함 (argparse + interactive 가 들어 있음). 단지 import.
    spec.loader.exec_module(module)
    assert hasattr(module, "_run_vision_qa")
    assert hasattr(module, "_run_track_a")
