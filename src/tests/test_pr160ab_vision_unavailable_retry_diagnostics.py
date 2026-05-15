# -*- coding: utf-8 -*-
"""PR #160a+b — Vision QA false-FAIL + retry build .exe 미생성 진단 회귀 차단.

배경 (2026-05-15 E2E 발견):
    `--auto-iterate --max-iterations 1` 본인 PC 실행 결과 (계산기 Calculator.exe
    10.67MB 정상 생성) 분석 시 *2 결함* 노출:

    결함 #1 — Vision QA false FAIL:
        ``[GUI_TEST FAIL] screenshots=1 critical=0 ui_issues=0`` — critical/ui_issues
        모두 0 인데 success=False. 원인: ``analyze_screenshot`` 가 5 케이스
        (screenshot 부재 / SDK 미설치 / API key 누락 / 호출 예외 / JSON 파싱 실패)
        모두 ``success=False`` 로 반환. ``run_gui_test`` 의 종합 판정이 그 결과를
        모두 *실 시각 결함* 으로 동일시 → 불필요한 RETRY 트리거.

    결함 #2 — retry build .exe 미생성 fail-silent:
        ``⚠️ retry build .exe 미생성`` 1줄만 출력 — 어느 원인 (executor_result=None /
        exe_path=None / 실 파일 부재) 인지 사용자가 알 수 없음. 디버깅 불가.

PR #160a 처방:
    - ``GUITestResult.vision_unavailable`` property 신설 — vision_analyses 모두 실패
      케이스 식별
    - ``run_gui_test`` 종합 판정에 추가 분기 — vision_unavailable + critical=0 +
      screenshot OK → ``skipped=True`` + error_message (FAIL 아님)
    - ``summary_line()`` 에 ``[GUI_TEST VISION_UNAVAILABLE] reason=...`` 분기 추가

PR #160b 처방:
    - ``_retry_engineer_with_vision_feedback`` 의 `.exe 미생성` 안내를 3 케이스
      세분화 + 실 원인 surface (executor=None / exe_path=None / 파일 부재)

본 테스트:
    1. GUITestResult.vision_unavailable property — 4 시나리오
    2. summary_line() VISION_UNAVAILABLE 분기 — reason 포함
    3. run_gui_test 가 vision-unavailable 케이스 → skipped=True
    4. qa_feedback_loop 가 skipped=True 면 RETRY 미트리거 (회귀 차단)
    5. _retry_engineer_with_vision_feedback 의 진단 3 분기
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr160ab", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr160ab"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. GUITestResult.vision_unavailable property + summary_line VISION_UNAVAILABLE 분기
# ---------------------------------------------------------------------------


def _make_vision_analysis(success: bool, error: str = "", critical: int = 0):
    from src.agents.qa.gui_test_executor import VisionAnalysis

    return VisionAnalysis(
        screenshot_path=Path("/tmp/shot.png"),
        model="claude-haiku-4-5",
        success=success,
        critical_issue_count=critical,
        error_message=error or None,
    )


def _make_gui_result(*, vision_analyses, **kw):
    from src.agents.qa.gui_test_executor import GUITestResult

    base = dict(
        success=False, elapsed_sec=3.10,
        target_path=Path("/tmp/App.exe"),
        screenshot_paths=[Path("/tmp/shot.png")],
        vision_analyses=vision_analyses,
    )
    base.update(kw)
    return GUITestResult(**base)


def test_vision_unavailable_true_when_all_analyses_failed() -> None:
    """모든 vision_analyses 실패 → ``vision_unavailable=True``."""
    result = _make_gui_result(
        vision_analyses=[
            _make_vision_analysis(success=False, error="ANTHROPIC_API_KEY 미설정"),
        ],
    )
    assert result.vision_unavailable is True


def test_vision_unavailable_false_when_at_least_one_succeeded() -> None:
    """1 개라도 성공 → ``vision_unavailable=False`` (실 시각 결함 검출 의미 있음)."""
    result = _make_gui_result(
        vision_analyses=[
            _make_vision_analysis(success=True),
            _make_vision_analysis(success=False, error="...timeout..."),
        ],
    )
    assert result.vision_unavailable is False


def test_vision_unavailable_false_when_no_analyses() -> None:
    """vision_analyses 비어 있음 (skip_vision=True 등) → ``vision_unavailable=False``."""
    result = _make_gui_result(vision_analyses=[])
    assert result.vision_unavailable is False


def test_summary_line_vision_unavailable_branch_surfaces_reason() -> None:
    """``summary_line()`` 에 ``[GUI_TEST VISION_UNAVAILABLE] reason=...`` 등장."""
    result = _make_gui_result(
        vision_analyses=[
            _make_vision_analysis(success=False, error="ANTHROPIC_API_KEY 미설정"),
        ],
        skipped=False,  # FAIL 분기에서 vision_unavailable 추가 식별
    )
    line = result.summary_line()
    assert "VISION_UNAVAILABLE" in line
    assert "ANTHROPIC_API_KEY 미설정" in line


def test_summary_line_real_fail_still_shows_fail() -> None:
    """실 시각 결함 (critical>0) 은 여전히 FAIL — VISION_UNAVAILABLE 로 swallow X."""
    # critical>0 + 분석 1개 success=True 시
    result = _make_gui_result(
        vision_analyses=[
            _make_vision_analysis(success=True, critical=2),
        ],
        skipped=False,
    )
    line = result.summary_line()
    assert "FAIL" in line
    assert "critical=2" in line
    assert "VISION_UNAVAILABLE" not in line


def test_summary_line_skipped_branch_unchanged() -> None:
    """``skipped=True`` 분기는 PR #160a 변경 영향 받지 않음 (기존 SKIPPED 메시지 그대로)."""
    result = _make_gui_result(
        vision_analyses=[],
        skipped=True,
        error_message="pyautogui 미설치",
    )
    line = result.summary_line()
    assert "SKIPPED" in line
    assert "pyautogui 미설치" in line


# ---------------------------------------------------------------------------
# 2. run_gui_test — Vision unavailable 케이스 skipped=True 처리
# ---------------------------------------------------------------------------


def test_run_gui_test_marks_skipped_on_all_vision_failures(
    monkeypatch, tmp_path: Path
) -> None:
    """모든 vision_analyses 실패 + screenshot OK → skipped=True (FAIL X).

    이 fix 가 qa_feedback_loop 가 ``skipped=True`` 면 RETRY 미트리거하는 기존 동작과
    결합해 false-RETRY 회귀 차단.
    """
    import src.agents.qa.gui_test_executor as gte

    # pyautogui 정상 동작 stub
    monkeypatch.setattr(gte, "_is_pyautogui_available", lambda: True)
    shot = tmp_path / "screenshot_01.png"
    shot.write_bytes(b"fake-png")
    monkeypatch.setattr(
        gte, "launch_and_capture",
        lambda *a, **kw: ([shot], 0, "terminated_after_capture"),
    )
    # analyze_screenshot 가 success=False 반환 (API key 누락 시뮬)
    monkeypatch.setattr(
        gte, "analyze_screenshot",
        lambda *a, **kw: _make_vision_analysis(
            success=False, error="ANTHROPIC_API_KEY 미설정"
        ),
    )

    target = tmp_path / "App.exe"
    target.write_bytes(b"MZ")
    result = gte.run_gui_test(target_path=target, output_dir=tmp_path)
    assert result.skipped is True, (
        "Vision API 미평가 케이스가 FAIL 로 처리됨 — PR #160a 회귀"
    )
    assert "Vision API 미평가" in (result.error_message or "")
    assert "ANTHROPIC_API_KEY 미설정" in (result.error_message or "")


def test_run_gui_test_real_pass_still_succeeds(monkeypatch, tmp_path: Path) -> None:
    """Vision success=True + critical=0 → success=True 유지 (회귀 차단)."""
    import src.agents.qa.gui_test_executor as gte

    monkeypatch.setattr(gte, "_is_pyautogui_available", lambda: True)
    shot = tmp_path / "screenshot_01.png"
    shot.write_bytes(b"fake")
    monkeypatch.setattr(
        gte, "launch_and_capture",
        lambda *a, **kw: ([shot], 0, "terminated_after_capture"),
    )
    monkeypatch.setattr(
        gte, "analyze_screenshot",
        lambda *a, **kw: _make_vision_analysis(success=True, critical=0),
    )

    target = tmp_path / "App.exe"
    target.write_bytes(b"MZ")
    result = gte.run_gui_test(target_path=target, output_dir=tmp_path)
    assert result.success is True
    assert result.skipped is False


def test_run_gui_test_real_fail_still_fails(monkeypatch, tmp_path: Path) -> None:
    """Vision success=True + critical>0 → success=False, skipped=False (실 결함 검출 유지)."""
    import src.agents.qa.gui_test_executor as gte

    monkeypatch.setattr(gte, "_is_pyautogui_available", lambda: True)
    shot = tmp_path / "screenshot_01.png"
    shot.write_bytes(b"fake")
    monkeypatch.setattr(
        gte, "launch_and_capture",
        lambda *a, **kw: ([shot], 0, "terminated_after_capture"),
    )
    monkeypatch.setattr(
        gte, "analyze_screenshot",
        lambda *a, **kw: _make_vision_analysis(success=True, critical=2),
    )

    target = tmp_path / "App.exe"
    target.write_bytes(b"MZ")
    result = gte.run_gui_test(target_path=target, output_dir=tmp_path)
    assert result.success is False
    assert result.skipped is False, "실 시각 결함이 SKIPPED 로 swallow — PR #160a 회귀"


# ---------------------------------------------------------------------------
# 3. qa_feedback_loop 가 skipped=True 인 vision_qa 를 SKIPPED 로 처리
# ---------------------------------------------------------------------------


def test_qa_feedback_loop_treats_vision_unavailable_skipped_as_no_retry() -> None:
    """``skipped=True`` 인 vision_qa → ``should_retry=False`` (false RETRY 차단)."""
    from src.workflows.qa_feedback_loop import evaluate_qa_results

    # PR #160a 의 vision_unavailable + skipped=True 시뮬
    skipped_vision = SimpleNamespace(
        success=False, skipped=True,
        summary_line=lambda: "[GUI_TEST VISION_UNAVAILABLE] reason=key missing",
    )
    decision = evaluate_qa_results(
        results={"vision_qa": skipped_vision},
        retry_count=0,
        max_retries=1,
    )
    assert decision.should_retry is False, (
        "Vision unavailable 가 RETRY 트리거 — PR #160a 갭"
    )
    assert "vision_qa" in decision.skipped_qa_tools


# ---------------------------------------------------------------------------
# 4. _retry_engineer_with_vision_feedback — 진단 3 분기
# ---------------------------------------------------------------------------


class _StubVisionResult:
    success = False
    skipped = False

    def summary_line(self) -> str:
        return "[GUI_TEST FAIL] critical=1"


def _make_prev_result(tmp_path: Path) -> SimpleNamespace:
    code_dir = tmp_path / "prev_code"
    code_dir.mkdir(parents=True, exist_ok=True)
    file1 = code_dir / "calculator.py"
    file1.write_text("print('x')\n", encoding="utf-8")
    return SimpleNamespace(
        saved_code_files=[file1],
        saved_dir=tmp_path,
        gui_code_output="",
        ui_spec="",
        design_tokens="",
        engineer_output="x",
    )


def _patch_crew_and_engineer(monkeypatch, kickoff_side_effect=None):
    import crewai
    fake_task_class = MagicMock(return_value=MagicMock(name="MockTask"))
    monkeypatch.setattr(crewai, "Task", fake_task_class)
    fake_crew = MagicMock()
    if kickoff_side_effect is not None:
        fake_crew.kickoff.side_effect = kickoff_side_effect
    else:
        fake_crew.kickoff.return_value = None
    monkeypatch.setattr(crewai, "Crew", MagicMock(return_value=fake_crew))
    import src.agents.engineering as eng_pkg
    monkeypatch.setattr(
        eng_pkg, "create_python_engineer_agent",
        lambda **kw: SimpleNamespace(role="stub"),
    )
    import src.workflows._common as _common
    monkeypatch.setattr(
        _common, "task_output_text",
        lambda task: (
            "수정 완료.\n\n"
            "```python\n# file: calculator.py\nprint('fixed')\n```\n"
        ),
    )


def test_retry_surfaces_executor_none_reason(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """``executor_result=None`` → 진단 메시지에 executor=None 명시 + platform_test surface."""
    _patch_crew_and_engineer(monkeypatch)

    fake_build = SimpleNamespace(
        executor_result=None,
        platform_test_report="Platform Tester: PASS but executor skipped (entry .py 미탐지)",
    )
    import src.workflows.build_workflow as bw
    monkeypatch.setattr(bw, "run_build_workflow", lambda **kw: fake_build)

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=_make_prev_result(tmp_path),
        vision_result=_StubVisionResult(),
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret is None
    captured = capsys.readouterr().err
    assert "executor_result=None" in captured
    assert "entry .py" in captured  # platform_test_report 의 일부


def test_retry_surfaces_exe_path_none_reason(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """``executor.exe_path=None`` (success=False) → error_message / stderr_tail 노출."""
    _patch_crew_and_engineer(monkeypatch)

    fake_executor = SimpleNamespace(
        exe_path=None,
        success=False,
        error_message="PyInstaller exited with code 1",
        stderr_tail="ERROR: Cannot find module foo",
    )
    fake_build = SimpleNamespace(executor_result=fake_executor)
    import src.workflows.build_workflow as bw
    monkeypatch.setattr(bw, "run_build_workflow", lambda **kw: fake_build)

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=_make_prev_result(tmp_path),
        vision_result=_StubVisionResult(),
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret is None
    err = capsys.readouterr().err
    assert "executor.exe_path=None" in err
    assert "PyInstaller exited with code 1" in err
    assert "Cannot find module foo" in err


def test_retry_surfaces_exe_path_not_exists(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """``executor.exe_path`` 지정됐지만 디스크 파일 부재 → 진단 메시지."""
    _patch_crew_and_engineer(monkeypatch)

    bogus_path = tmp_path / "does_not_exist.exe"
    fake_executor = SimpleNamespace(exe_path=bogus_path, success=True)
    fake_build = SimpleNamespace(executor_result=fake_executor)
    import src.workflows.build_workflow as bw
    monkeypatch.setattr(bw, "run_build_workflow", lambda **kw: fake_build)

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=_make_prev_result(tmp_path),
        vision_result=_StubVisionResult(),
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret is None
    err = capsys.readouterr().err
    assert "디스크에 파일 없음" in err or "경로 존재 X" in err


def test_retry_returns_exe_path_on_success(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """정상 성공 path — 회귀 차단 (기존 PR #151 happy path 보존)."""
    _patch_crew_and_engineer(monkeypatch)

    real_exe = tmp_path / "Calc.exe"
    real_exe.write_bytes(b"MZ")
    fake_executor = SimpleNamespace(exe_path=real_exe, success=True)
    fake_build = SimpleNamespace(executor_result=fake_executor)
    import src.workflows.build_workflow as bw
    monkeypatch.setattr(bw, "run_build_workflow", lambda **kw: fake_build)

    ret = run_mod._retry_engineer_with_vision_feedback(
        prev_result=_make_prev_result(tmp_path),
        vision_result=_StubVisionResult(),
        user_request="x",
        outputs_dir=tmp_path,
        retry_index=1,
        max_retries=1,
    )
    assert ret == real_exe
