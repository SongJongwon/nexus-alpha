# -*- coding: utf-8 -*-
"""UI Automation Specialist 단위 test (v13 Phase 1)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.agents.runtime_verification.ui_automation_specialist import (
    UIAutomationResult,
    UIScenarioStep,
    run_ui_automation_scenario,
)


def _make_fake_exe() -> Path:
    tf = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
    tf.write(b"fake")
    tf.close()
    return Path(tf.name)


class TestUISchema:
    def test_step_schema(self):
        step = UIScenarioStep(action="click", target="100,200")
        assert step.action == "click"
        assert step.target == "100,200"

    def test_result_schema(self):
        result = UIAutomationResult(
            passed=True, completed_steps=3, failed_step_index=None, failed_step_reason=None
        )
        assert result.passed is True
        assert result.completed_steps == 3


class TestSkippedWhenPyAutoGUIMissing:
    """⭐ pyautogui 미설치 시 의미적 SKIP (skipped=True)."""

    @patch("src.agents.runtime_verification.ui_automation_specialist._is_pyautogui_available")
    def test_skip_when_pyautogui_unavailable(self, mock_available):
        mock_available.return_value = False
        exe = _make_fake_exe()
        try:
            result = run_ui_automation_scenario(exe, scenario=[])
            assert result.skipped is True
            assert result.passed is True  # 의미적 SKIP — 비-실패
            assert "pyautogui" in (result.failed_step_reason or "")
        finally:
            exe.unlink(missing_ok=True)


class TestExeNotFound:
    @patch("src.agents.runtime_verification.ui_automation_specialist._is_pyautogui_available")
    def test_exe_not_found_returns_fail(self, mock_available):
        mock_available.return_value = True
        result = run_ui_automation_scenario(
            Path("C:/__nonexistent__/fake.exe"),
            scenario=[UIScenarioStep(action="wait", value="0.1")],
        )
        assert result.passed is False
        assert "미발견" in (result.failed_step_reason or "")


class TestScenarioExecution:
    """⭐ 시나리오 step sequential — DoD 의 핵심: 계산기 1+1=2 검증 시뮬레이션."""

    @patch("src.agents.runtime_verification.ui_automation_specialist._is_pyautogui_available")
    @patch("src.agents.runtime_verification.ui_automation_specialist.subprocess.Popen")
    def test_calculator_scenario_passes(self, mock_popen, mock_available):
        """DoD 시뮬레이션: 계산기 spawn → click "1" → click "+" → click "1" → click "=" → screenshot."""
        mock_available.return_value = True

        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        # pyautogui mock 으로 inject
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            exe = _make_fake_exe()
            scenario = [
                UIScenarioStep(action="wait", value="0.01"),
                UIScenarioStep(action="click", target="100,200"),
                UIScenarioStep(action="click", target="150,200"),
                UIScenarioStep(action="click", target="100,250"),
                UIScenarioStep(action="click", target="200,300"),
            ]
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    result = run_ui_automation_scenario(
                        exe,
                        scenario=scenario,
                        screenshot_dir=Path(tmp),
                        spawn_grace_sec=0.01,
                    )
                    assert result.passed is True
                    assert result.completed_steps == 5
                    assert result.failed_step_index is None
                    # click 호출 4회 확인
                    assert mock_pyautogui.click.call_count == 4
            finally:
                exe.unlink(missing_ok=True)

    @patch("src.agents.runtime_verification.ui_automation_specialist._is_pyautogui_available")
    @patch("src.agents.runtime_verification.ui_automation_specialist.subprocess.Popen")
    def test_unknown_action_fails(self, mock_popen, mock_available):
        """알 수 없는 action 은 즉시 fail."""
        mock_available.return_value = True
        mock_popen.return_value = MagicMock()

        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            exe = _make_fake_exe()
            scenario = [UIScenarioStep(action="invalid_action")]
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    result = run_ui_automation_scenario(
                        exe,
                        scenario=scenario,
                        screenshot_dir=Path(tmp),
                        spawn_grace_sec=0.01,
                    )
                    assert result.passed is False
                    assert result.failed_step_index == 0
                    assert "invalid_action" in (result.failed_step_reason or "")
            finally:
                exe.unlink(missing_ok=True)
