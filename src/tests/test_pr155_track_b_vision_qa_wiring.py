# -*- coding: utf-8 -*-
"""PR #155 — Track B 자동 감지 기반 Vision QA wiring 회귀 차단.

배경 (PR #150 후 Track A 만 cover 한 갭):
    PR #150/151 의 Vision QA + qa_feedback_loop wiring 은 Track A 전용. Track B
    (5 도메인 자동화) 산출이 *GUI* 인 케이스 (예: tkinter wrapper + pywinauto 데스크탑
    자동화) 는 빈 화면 / 한글 깨짐 등의 결함이 사용자에게 도달.

PR #155 처방 (Option B — 자동 감지 분기):
    - ``_run_track_b`` 가 build 산출 직후 ``detect_artifact_category`` 휴리스틱 호출
    - 카테고리 == "gui" 일 때만 Track A 와 동일한 ``_run_vision_qa_full`` + qa_feedback_loop
      평가 파이프라인 적용
    - CLI / library / external_dependent → 자동 skip (Vision API 호출 0)
    - ``--no-vision-qa`` 강제 skip 그대로 적용
    - Retry 는 Track B *비활성* (max_retries=0) — 자체 enable_qa_loop 와 2중 retry 회피

본 테스트 목적:
    1. ``_detect_track_b_gui_artifact`` 휴리스틱 단위
    2. ``_run_track_b`` file-text 회귀 (호출 wiring 존재)
    3. 결과 패널에 vision_summary + qa_verdict 표시
    4. ``--no-vision-qa`` 존중 (강제 skip)
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr155", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr155"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. _detect_track_b_gui_artifact 휴리스틱 — 단위 동작
# ---------------------------------------------------------------------------


def test_detect_gui_when_source_imports_tkinter(run_mod, tmp_path: Path) -> None:
    """saved_code_files 의 첫 .py 가 tkinter import → GUI 분기 True."""
    entry = tmp_path / "app.py"
    entry.write_text(
        "import tkinter as tk\n"
        "def main():\n    root = tk.Tk()\n    root.mainloop()\n",
        encoding="utf-8",
    )
    assert run_mod._detect_track_b_gui_artifact([entry], None) is True


def test_detect_non_gui_when_source_is_cli(run_mod, tmp_path: Path) -> None:
    """argparse 기반 CLI → False (Vision QA skip)."""
    entry = tmp_path / "scrape.py"
    entry.write_text(
        "import argparse\n"
        "def main():\n    parser = argparse.ArgumentParser()\n    parser.parse_args()\n",
        encoding="utf-8",
    )
    assert run_mod._detect_track_b_gui_artifact([entry], None) is False


def test_detect_non_gui_for_pure_library(run_mod, tmp_path: Path) -> None:
    """argparse / GUI 키워드 없는 평이한 library → False."""
    entry = tmp_path / "helpers.py"
    entry.write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    assert run_mod._detect_track_b_gui_artifact([entry], None) is False


def test_detect_skips_test_files_when_selecting_entry(
    run_mod, tmp_path: Path
) -> None:
    """첫 파일이 test_*.py 면 휴리스틱에 부적합 — 다음 후보로 진행."""
    test_file = tmp_path / "test_app.py"
    test_file.write_text("import tkinter\n", encoding="utf-8")
    real_entry = tmp_path / "app.py"
    real_entry.write_text(
        "import argparse\nparser = argparse.ArgumentParser()\n",
        encoding="utf-8",
    )
    # test 파일이 GUI 처럼 보이지만 *실 entry* 가 CLI 면 False
    result = run_mod._detect_track_b_gui_artifact([test_file, real_entry], None)
    assert result is False, (
        "test_*.py 가 entry 로 선택돼 GUI 오판 — test prefix 필터링 회귀"
    )


def test_detect_gui_via_exe_only_when_no_source(
    run_mod, tmp_path: Path
) -> None:
    """source 미존재 + exe 있음 → conservative "gui" 분류."""
    exe = tmp_path / "App.exe"
    exe.write_bytes(b"MZ")
    assert run_mod._detect_track_b_gui_artifact([], exe) is True


def test_detect_false_when_both_inputs_missing(run_mod) -> None:
    """source 0개 + exe None → False (unknown)."""
    assert run_mod._detect_track_b_gui_artifact([], None) is False


def test_detect_swallows_detect_artifact_exception(
    run_mod, tmp_path: Path, monkeypatch
) -> None:
    """detect_artifact_category 가 예외 → False 반환 (Vision QA skip).

    헬퍼 실패가 워크플로 차단 사유 아님 — graceful.
    """
    from src.workflows import qa_feedback_loop

    def _boom(*args, **kwargs):
        raise RuntimeError("heuristic boom")

    monkeypatch.setattr(qa_feedback_loop, "detect_artifact_category", _boom)
    entry = tmp_path / "app.py"
    entry.write_text("import tkinter\n", encoding="utf-8")
    assert run_mod._detect_track_b_gui_artifact([entry], None) is False


# ---------------------------------------------------------------------------
# 2. _run_track_b file-text 회귀 — wiring 호출 존재
# ---------------------------------------------------------------------------


def test_track_b_calls_detect_helper() -> None:
    """``_run_track_b`` 본문에 ``_detect_track_b_gui_artifact`` 호출."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "_detect_track_b_gui_artifact" in body, (
        "Track B 가 _detect_track_b_gui_artifact 호출 안 함 — PR #155 회귀"
    )


def test_track_b_invokes_vision_qa_full_on_gui_branch() -> None:
    """GUI 분기에서 ``_run_vision_qa_full`` + qa_feedback_loop 평가 호출."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "_run_vision_qa_full" in body
    assert "_evaluate_vision_qa_via_feedback_loop" in body


def test_track_b_respects_no_vision_qa_flag() -> None:
    """``args.no_vision_qa`` 가 GUI 판정 *전에* 차단 — file-text 검증."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "args.no_vision_qa" in body, (
        "Track B 가 --no-vision-qa 미존중 — 강제 skip 회귀"
    )


def test_track_b_disables_retry_for_vision_qa() -> None:
    """Track B 의 Vision QA verdict 평가는 ``max_retries=0`` 명시 — 2중 retry 회피."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    # _evaluate_vision_qa_via_feedback_loop 호출 시점 이후의 max_retries=0 확인
    # — Track A 와 달리 args.vision_qa_max_retries 미주입 (자체 enable_qa_loop 이중 retry 회피)
    assert "max_retries=0" in body, (
        "Track B Vision QA 가 max_retries=0 명시 안 함 — 2중 retry 위험"
    )
    assert "args.vision_qa_max_retries" not in body, (
        "Track B 가 args.vision_qa_max_retries 사용 — Track A 와 동일 retry 정책 회귀"
    )


# ---------------------------------------------------------------------------
# 3. _run_track_b 실행 — Vision QA branch / non-GUI skip
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> SimpleNamespace:
    base = {
        "request": "tkinter 자동화 도구",
        "verbose": False,
        "build": True,
        "no_vision_qa": False,
        "vision_qa_max_retries": 0,  # Track B 는 retry 비활성
        "release": False,
        "repo": "",
        "tag": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _setup_fake_automate(
    run_mod, monkeypatch, tmp_path: Path, *, source_code: str, has_exe: bool
):
    """run_automate_workflow stub — code 파일 + (옵션) .exe 산출."""
    code_path = tmp_path / "app.py"
    code_path.write_text(source_code, encoding="utf-8")
    exe_path = None
    if has_exe:
        exe_path = tmp_path / "App.exe"
        exe_path.write_bytes(b"MZ")

    fake_result = SimpleNamespace(
        saved_dir=tmp_path,
        saved_code_files=[code_path],
        executor_result=SimpleNamespace(exe_path=exe_path) if exe_path else None,
        publish_result=None,
    )

    from src.workflows import automate_workflow as aw
    monkeypatch.setattr(aw, "run_automate_workflow", lambda *a, **kw: fake_result)
    return fake_result, exe_path


def test_track_b_runs_vision_qa_on_gui_artifact(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """tkinter import + .exe → Vision QA 실 호출 → 결과 패널에 👁️ Vision 출력."""
    _setup_fake_automate(
        run_mod, monkeypatch, tmp_path,
        source_code="import tkinter\ndef main(): pass\n",
        has_exe=True,
    )

    vision_calls: list = []

    def _fake_vision(exe, outputs_dir, *, skip_vision=False):
        vision_calls.append(exe)
        return SimpleNamespace(
            success=True,
            skipped=False,
            summary_line=lambda: "[GUI_TEST PASS] critical=0",
        )

    monkeypatch.setattr(run_mod, "_run_vision_qa_full", _fake_vision)

    args = _make_args()
    rc = run_mod._run_track_b(args)
    assert rc == 0
    assert len(vision_calls) == 1, (
        f"Vision QA 호출 횟수 1 예상, 실제 {len(vision_calls)}"
    )
    captured = capsys.readouterr().out
    assert "Vision" in captured
    assert "GUI_TEST PASS" in captured
    assert "QA loop" in captured  # qa_feedback_loop verdict 라인


def test_track_b_skips_vision_qa_on_cli_artifact(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """argparse 기반 CLI → Vision QA 미호출 → 결과 패널에 Vision 라인 부재."""
    _setup_fake_automate(
        run_mod, monkeypatch, tmp_path,
        source_code="import argparse\nparser = argparse.ArgumentParser()\nparser.parse_args()\n",
        has_exe=True,
    )

    vision_calls: list = []
    monkeypatch.setattr(
        run_mod, "_run_vision_qa_full",
        lambda *a, **kw: (vision_calls.append(1), None)[1],
    )

    args = _make_args()
    rc = run_mod._run_track_b(args)
    assert rc == 0
    assert vision_calls == [], (
        "CLI 산출에서 Vision QA 호출됨 — auto-skip 회귀"
    )


def test_track_b_skips_vision_qa_when_no_vision_qa_flag(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """``--no-vision-qa`` 강제 skip — GUI 산출이라도 호출 안 함."""
    _setup_fake_automate(
        run_mod, monkeypatch, tmp_path,
        source_code="import tkinter\n",
        has_exe=True,
    )

    vision_calls: list = []
    monkeypatch.setattr(
        run_mod, "_run_vision_qa_full",
        lambda *a, **kw: (vision_calls.append(1), None)[1],
    )

    args = _make_args(no_vision_qa=True)
    rc = run_mod._run_track_b(args)
    assert rc == 0
    assert vision_calls == [], (
        "--no-vision-qa 미존중 — 강제 skip 회귀"
    )


def test_track_b_skips_vision_qa_when_no_exe(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """.exe 미생성 → Vision QA 미호출 (build 결과 부재)."""
    _setup_fake_automate(
        run_mod, monkeypatch, tmp_path,
        source_code="import tkinter\n",
        has_exe=False,
    )

    vision_calls: list = []
    monkeypatch.setattr(
        run_mod, "_run_vision_qa_full",
        lambda *a, **kw: (vision_calls.append(1), None)[1],
    )

    args = _make_args()
    rc = run_mod._run_track_b(args)
    assert rc == 0
    assert vision_calls == [], (
        ".exe 미생성에도 Vision QA 호출 — exe presence 가드 회귀"
    )
