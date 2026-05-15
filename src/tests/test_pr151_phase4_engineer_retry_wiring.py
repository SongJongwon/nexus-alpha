# -*- coding: utf-8 -*-
"""PR #151 Phase 4 후속 — Vision QA should_retry 일 때 Engineer + Build 재호출 회귀 차단.

배경 (본인 비전 통찰 6 D-3 완성):
    PR #150 은 Vision QA verdict 를 결과 패널에 표시하기만 함 (max_retries=0 고정).
    "결함을 *보고* 도 *고치지 않는*" 절반 wiring — 사용자가 결함 알아도 직접 재실행
    필요.

PR #151 처방:
    - Vision QA 가 ``should_retry`` → ``_retry_engineer_with_vision_feedback`` 호출
    - Engineer 또는 GUI Code Generator 단일 task Crew kickoff (풀체인 X, ~5min)
    - ``_extract_code_blocks`` 로 새 코드 추출 → ``run_build_workflow`` 로 새 .exe
    - 새 .exe 에 재 Vision QA 1회 → verdict 재평가
    - ``--vision-qa-max-retries N`` CLI 플래그 (기본 1)

본 테스트 목적:
    - retry helper 의 5단계 (feedback → 이전 코드 조립 → Engineer Crew → 코드 추출
      → Build) 각각의 실패 격리 회귀 차단
    - CLI 플래그 등록 + 기본값 1 회귀 차단
    - ``_evaluate_vision_qa_via_feedback_loop`` 반환이 tuple (verdict, decision)
      회귀 차단
    - retry budget exhaustion → BUDGET_EXHAUSTED verdict 회귀 차단
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr151", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr151"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. CLI 플래그 등록 + 기본값
# ---------------------------------------------------------------------------


def test_argparse_has_vision_qa_max_retries_flag() -> None:
    """``--vision-qa-max-retries`` 등록 확인 (file-text)."""
    text = RUN_PY.read_text(encoding="utf-8")
    assert "--vision-qa-max-retries" in text, (
        "argparse 에 --vision-qa-max-retries 미등록 — PR #151 회귀"
    )


def test_vision_qa_max_retries_defaults_to_1(run_mod) -> None:
    """기본값 1 — Vision QA 실패 시 자동 retry 1회."""
    args = run_mod._parse_args(["--request", "테스트", "--non-interactive"])
    assert args.vision_qa_max_retries == 1


def test_vision_qa_max_retries_accepts_explicit_value(run_mod) -> None:
    """명시 ``--vision-qa-max-retries 2`` 수용."""
    args = run_mod._parse_args(
        ["--request", "x", "--non-interactive", "--vision-qa-max-retries", "2"]
    )
    assert args.vision_qa_max_retries == 2


def test_vision_qa_max_retries_zero_disables_retry(run_mod) -> None:
    """``--vision-qa-max-retries 0`` 으로 PR #150 verdict 가시화 모드 복귀."""
    args = run_mod._parse_args(
        ["--request", "x", "--non-interactive", "--vision-qa-max-retries", "0"]
    )
    assert args.vision_qa_max_retries == 0


# ---------------------------------------------------------------------------
# 2. _evaluate_vision_qa_via_feedback_loop — tuple 반환 + retry_count/max_retries
# ---------------------------------------------------------------------------


def test_evaluate_returns_tuple_of_verdict_and_decision(run_mod) -> None:
    """반환이 ``(str, QAFeedbackDecision)`` 튜플."""
    result = SimpleNamespace(
        success=True, skipped=False, summary_line=lambda: "[PASS]"
    )
    out = run_mod._evaluate_vision_qa_via_feedback_loop(result)
    assert isinstance(out, tuple)
    assert len(out) == 2
    verdict, decision = out
    assert isinstance(verdict, str)
    assert decision is not None
    assert hasattr(decision, "should_retry")
    assert hasattr(decision, "overall_passed")


def test_evaluate_should_retry_when_fail_with_budget(run_mod) -> None:
    """fail + max_retries=1 → should_retry=True (재호출 가능)."""
    result = SimpleNamespace(
        success=False, skipped=False, summary_line=lambda: "[FAIL]"
    )
    _, decision = run_mod._evaluate_vision_qa_via_feedback_loop(
        result, retry_count=0, max_retries=1
    )
    assert decision.should_retry is True


def test_evaluate_budget_exhausted_when_retry_count_eq_max(run_mod) -> None:
    """fail + retry_count == max_retries → should_retry=False (budget exhausted)."""
    result = SimpleNamespace(
        success=False, skipped=False, summary_line=lambda: "[FAIL]"
    )
    verdict, decision = run_mod._evaluate_vision_qa_via_feedback_loop(
        result, retry_count=1, max_retries=1
    )
    assert decision.should_retry is False
    assert "BUDGET_EXHAUSTED" in verdict


# ---------------------------------------------------------------------------
# 3. _retry_engineer_with_vision_feedback — 5단계 실패 격리
# ---------------------------------------------------------------------------


class _StubVisionResult:
    success = False
    skipped = False

    def summary_line(self) -> str:
        return "[GUI_TEST FAIL] critical=1 ui_issues=0"


def _make_prev_result(tmp_path: Path, *, with_code: bool = True) -> SimpleNamespace:
    """이전 워크플로 결과 stub — ``saved_code_files`` 가 실 파일 경로."""
    code_dir = tmp_path / "prev_code"
    code_dir.mkdir(parents=True, exist_ok=True)
    code_paths: list[Path] = []
    if with_code:
        file1 = code_dir / "calculator.py"
        file1.write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        code_paths.append(file1)
    return SimpleNamespace(
        saved_code_files=code_paths,
        saved_dir=tmp_path,
        gui_code_output="",  # CLI 분기로 판정
        ui_spec="",
        design_tokens="",
        engineer_output="def add(a, b): ...",
    )


def test_retry_writes_feedback_md(run_mod, tmp_path, monkeypatch) -> None:
    """retry 호출 시 ``retry_{N}/feedback_for_engineer.md`` 저장 (실패 경로 포함)."""
    prev = _make_prev_result(tmp_path)
    vision = _StubVisionResult()

    # Engineer Crew kickoff 까지 가지 않게 import 단계에서 차단 — early-fail
    monkeypatch.setattr(
        "src.workflows.qa_feedback_loop.build_feedback_message_for_engineer",
        lambda decision, full_qa_reports=None: "# feedback\n- critical=1\n",
    )
    # Crew import 실패 시뮬 — try/except 격리 확인
    with patch.dict("sys.modules", {"crewai": None}):
        ret = run_mod._retry_engineer_with_vision_feedback(
            prev_result=prev,
            vision_result=vision,
            user_request="계산기",
            outputs_dir=tmp_path,
            retry_index=1,
            max_retries=1,
        )

    # crewai import 실패로 None 반환
    assert ret is None
    # feedback md 는 import 실패 *이전* 단계라 저장돼 있어야 함
    feedback_path = tmp_path / "retry_01" / "feedback_for_engineer.md"
    assert feedback_path.exists()


def _patch_crewai_primitives(monkeypatch, *, kickoff_side_effect=None) -> MagicMock:
    """CrewAI Task / Crew 를 mock 으로 대체 — Agent 검증 회피.

    Returns:
        ``fake_crew`` (Crew 인스턴스 mock) — ``kickoff`` 호출 추적용.
    """
    import crewai

    fake_task_class = MagicMock(return_value=MagicMock(name="MockTask"))
    monkeypatch.setattr(crewai, "Task", fake_task_class)

    fake_crew = MagicMock()
    if kickoff_side_effect is not None:
        fake_crew.kickoff.side_effect = kickoff_side_effect
    else:
        fake_crew.kickoff.return_value = None
    fake_crew_class = MagicMock(return_value=fake_crew)
    monkeypatch.setattr(crewai, "Crew", fake_crew_class)
    return fake_crew


def test_retry_returns_none_on_crew_kickoff_failure(
    run_mod, tmp_path, monkeypatch
) -> None:
    """Crew.kickoff 가 예외 → retry helper None 반환 (워크플로 차단 X)."""
    prev = _make_prev_result(tmp_path)
    vision = _StubVisionResult()

    _patch_crewai_primitives(
        monkeypatch, kickoff_side_effect=RuntimeError("boom")
    )

    # Engineer 팩토리도 stub
    import src.agents.engineering as eng_pkg
    monkeypatch.setattr(
        eng_pkg, "create_python_engineer_agent",
        lambda **kw: SimpleNamespace(role="stub"),
    )

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=prev,
        vision_result=vision,
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret is None


def test_retry_returns_none_when_no_code_blocks_extracted(
    run_mod, tmp_path, monkeypatch
) -> None:
    """Engineer 산출 markdown 에 ```python 블록 없음 → None 반환."""
    prev = _make_prev_result(tmp_path)
    vision = _StubVisionResult()

    _patch_crewai_primitives(monkeypatch)  # kickoff 정상 종료
    import src.agents.engineering as eng_pkg
    monkeypatch.setattr(
        eng_pkg, "create_python_engineer_agent",
        lambda **kw: SimpleNamespace(role="stub"),
    )
    # task_output_text 가 코드 블록 없는 텍스트 반환
    import src.workflows._common as _common
    monkeypatch.setattr(_common, "task_output_text", lambda task: "보정 완료 (코드 없음)")

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=prev,
        vision_result=vision,
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret is None
    # engineer_revised_output.md 는 저장돼 있어야 함 (산출 자체는 있음, 코드만 추출 실패)
    assert (tmp_path / "retry_01" / "engineer_revised_output.md").exists()


def test_retry_returns_exe_path_on_full_success(
    run_mod, tmp_path, monkeypatch
) -> None:
    """전체 happy path — Crew kickoff + 코드 추출 + Build 성공 → 새 .exe 경로 반환."""
    prev = _make_prev_result(tmp_path)
    vision = _StubVisionResult()

    _patch_crewai_primitives(monkeypatch)
    import src.agents.engineering as eng_pkg
    monkeypatch.setattr(
        eng_pkg, "create_python_engineer_agent",
        lambda **kw: SimpleNamespace(role="stub"),
    )

    # task_output_text → ```python 블록 포함 markdown
    revised_md = (
        "수정 완료.\n\n"
        "```python\n# file: calculator.py\n"
        "def add(a, b):\n    return a + b  # fixed\n"
        "```\n"
    )
    import src.workflows._common as _common
    monkeypatch.setattr(_common, "task_output_text", lambda task: revised_md)

    # run_build_workflow → 가짜 .exe 산출
    fake_exe = tmp_path / "retry_01" / "fake_built.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_bytes(b"MZ")

    fake_build_result = SimpleNamespace(
        executor_result=SimpleNamespace(exe_path=fake_exe, success=True)
    )
    import src.workflows.build_workflow as bw
    monkeypatch.setattr(bw, "run_build_workflow", lambda **kw: fake_build_result)

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=prev,
        vision_result=vision,
        user_request="계산기",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret == fake_exe
    # 산출물 보존
    assert (tmp_path / "retry_01" / "feedback_for_engineer.md").exists()
    assert (tmp_path / "retry_01" / "engineer_revised_output.md").exists()
    extracted_files = list((tmp_path / "retry_01" / "code").glob("*.py"))
    assert len(extracted_files) >= 1


def test_retry_routes_gui_branch_when_gui_code_output_present(
    run_mod, tmp_path, monkeypatch
) -> None:
    """prev_result.gui_code_output 가 있으면 GUI Code Generator 분기."""
    prev = _make_prev_result(tmp_path)
    prev.gui_code_output = "tkinter 산출"
    vision = _StubVisionResult()

    called_factories: list[str] = []
    import src.agents.design.gui_code_generator as gcg_mod
    import src.agents.engineering as eng_pkg

    def _stub_gui(**kw):
        called_factories.append("gui")
        return SimpleNamespace(role="gui")

    def _stub_cli(**kw):
        called_factories.append("cli")
        return SimpleNamespace(role="cli")

    monkeypatch.setattr(gcg_mod, "create_gui_code_generator_agent", _stub_gui)
    monkeypatch.setattr(eng_pkg, "create_python_engineer_agent", _stub_cli)

    # Crew → kickoff 즉시 실패 (분기 확인이 목적, build 까지 안 가도 됨)
    _patch_crewai_primitives(monkeypatch, kickoff_side_effect=RuntimeError("stop"))

    run_mod._retry_engineer_with_vision_feedback(
        prev_result=prev,
        vision_result=vision,
        user_request="GUI 계산기",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert "gui" in called_factories
    assert "cli" not in called_factories


# ---------------------------------------------------------------------------
# 4. Track A wiring — file-text 회귀 검증
# ---------------------------------------------------------------------------


def test_track_a_invokes_retry_when_should_retry() -> None:
    """``_run_track_a`` 본문이 retry 호출 코드 포함."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "_retry_engineer_with_vision_feedback" in body, (
        "Track A 가 _retry_engineer_with_vision_feedback 호출 안 함 — PR #151 회귀"
    )
    assert "should_retry" in body, (
        "Track A 가 should_retry 분기 안 함 — PR #151 회귀"
    )
    assert "args.vision_qa_max_retries" in body, (
        "Track A 가 args.vision_qa_max_retries 참조 안 함"
    )


def test_track_a_loop_re_runs_vision_qa_after_retry() -> None:
    """retry 루프 안에서 ``_run_vision_qa_full`` 재호출 — 재 Vision QA 1회 ON."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    # retry loop 안에서 _run_vision_qa_full 호출
    retry_section_start = body.find("_retry_engineer_with_vision_feedback")
    assert retry_section_start > 0
    retry_section = body[retry_section_start:]
    assert "_run_vision_qa_full" in retry_section, (
        "retry 루프 안에서 _run_vision_qa_full 재호출 누락 — 재 Vision QA 1회 ON 회귀"
    )
