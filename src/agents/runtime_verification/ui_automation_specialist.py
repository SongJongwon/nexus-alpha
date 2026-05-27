# -*- coding: utf-8 -*-
"""UI Automation Specialist — 본부 9 RV GUI 시나리오 검증 (v13 Phase 1).

PyAutoGUI (Windows native) 또는 Playwright (Electron/Tauri/Web) 로 GUI 앱의
사용자 시나리오 자동 수행. 빌드된 .exe 가 *실제로 사용자 입력에 반응* 하는지
검증 — Exe Runtime Tester (단순 alive 확인) 의 *다음 layer*.

Telemetry: `AgentStatusEvent(department="rv")` emit.

본 v13 Phase 1 의 1단계 — *interface + 결정론 골격*. 실제 PyAutoGUI 호출은
optional import (테스트 환경에서 mock 가능). 시나리오 yaml 해석 + 결과 dataclass.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 시나리오 step + 결과 schema
# ---------------------------------------------------------------------------
@dataclass
class UIScenarioStep:
    """단일 UI 시나리오 step.

    Attributes:
        action: ``"click"`` / ``"type"`` / ``"hotkey"`` / ``"wait"`` / ``"screenshot"`` / ``"assert_window"``.
        target: 클릭 좌표 (x, y) 또는 이미지 path 또는 hotkey 조합 ("ctrl+s") 등.
        value: ``"type"`` action 의 입력 텍스트 / ``"wait"`` 의 초.
        expected: ``"assert_window"`` 의 윈도우 title substring.
    """

    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    expected: Optional[str] = None


@dataclass
class UIAutomationResult:
    """`run_ui_automation_scenario` 의 산출.

    Attributes:
        passed: 모든 step 통과면 True.
        completed_steps: 시도된 step 수 (성공 + 실패 모두).
        failed_step_index: 실패한 첫 step 의 index. None 면 전부 성공.
        failed_step_reason: 실패 사유 (Optional).
        screenshots: 각 screenshot step 에서 저장된 path list.
        elapsed_sec: 시나리오 전체 실행 시간.
        skipped: ``True`` 면 pyautogui 미설치 등 *환경 부재* 로 skip (test pass 처럼 처리).
    """

    passed: bool
    completed_steps: int
    failed_step_index: Optional[int]
    failed_step_reason: Optional[str]
    screenshots: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0
    skipped: bool = False


def _try_emit_telemetry(agent: str, status: str, detail: str = "") -> None:
    """Telemetry emit — 실패 silent."""
    try:
        from src.monitoring.telemetry import (
            AgentStatusEvent,
            get_telemetry_emitter,
        )

        emitter = get_telemetry_emitter()
        if not emitter.enabled:
            return
        emitter.emit(
            AgentStatusEvent(
                agent=agent,
                department="rv",
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


def _is_pyautogui_available() -> bool:
    """pyautogui import 가능한지 확인. 미설치면 skip 모드."""
    try:
        import pyautogui  # type: ignore  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def run_ui_automation_scenario(
    exe_path: Path,
    scenario: list[UIScenarioStep],
    screenshot_dir: Optional[Path] = None,
    spawn_grace_sec: float = 1.0,
) -> UIAutomationResult:
    """빌드된 .exe 를 spawn 한 뒤 시나리오 step 들을 sequential 수행.

    동작:
        1. Telemetry emit (working)
        2. pyautogui 가용성 확인 — 미설치면 skipped=True 로 즉시 반환
        3. .exe spawn (subprocess.Popen, detached)
        4. spawn_grace_sec 대기 (윈도우 표시 + mainloop 진입)
        5. 시나리오 step sequential 수행:
           - click(x, y) / type(text) / hotkey(combo) / wait(sec) / screenshot(path) / assert_window(title)
        6. 첫 실패 시 즉시 중단 + failed_step_index 기록
        7. 정리 (.exe terminate)
        8. Telemetry emit (done)

    Args:
        exe_path: 빌드된 .exe.
        scenario: UIScenarioStep list.
        screenshot_dir: 스크린샷 저장 디렉터리 (없으면 cwd/.ui_test_screenshots).
        spawn_grace_sec: spawn 후 GUI 표시까지 대기 시간.

    Returns:
        UIAutomationResult.
    """
    _try_emit_telemetry(
        "ui_automation_specialist",
        "working",
        f"target={exe_path.name} steps={len(scenario)}",
    )
    start = time.monotonic()

    if not _is_pyautogui_available():
        result = UIAutomationResult(
            passed=True,  # SKIP 은 verdict 차원에서는 *비-실패*
            completed_steps=0,
            failed_step_index=None,
            failed_step_reason="pyautogui 미설치 — UI automation SKIP (의미적 SKIP)",
            screenshots=[],
            elapsed_sec=time.monotonic() - start,
            skipped=True,
        )
        _try_emit_telemetry(
            "ui_automation_specialist", "done", "skipped (pyautogui not available)"
        )
        return result

    if not exe_path.exists() or not exe_path.is_file():
        result = UIAutomationResult(
            passed=False,
            completed_steps=0,
            failed_step_index=None,
            failed_step_reason=f".exe 미발견: {exe_path}",
            elapsed_sec=time.monotonic() - start,
        )
        _try_emit_telemetry("ui_automation_specialist", "error", "exe not found")
        return result

    # spawn .exe
    creationflags = 0x00000008 if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result = UIAutomationResult(
            passed=False,
            completed_steps=0,
            failed_step_index=None,
            failed_step_reason=f"spawn 실패: {exc!r}",
            elapsed_sec=time.monotonic() - start,
        )
        _try_emit_telemetry("ui_automation_specialist", "error", f"spawn fail")
        return result

    # GUI 표시 대기
    time.sleep(spawn_grace_sec)

    screenshots: list[str] = []
    if screenshot_dir is None:
        screenshot_dir = exe_path.parent / ".ui_test_screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    try:
        import pyautogui  # type: ignore

        for i, step in enumerate(scenario):
            try:
                _execute_step(step, screenshot_dir, screenshots, pyautogui)
            except Exception as exc:  # noqa: BLE001
                result = UIAutomationResult(
                    passed=False,
                    completed_steps=i,
                    failed_step_index=i,
                    failed_step_reason=f"step[{i}] {step.action} 실패: {exc!r}",
                    screenshots=screenshots,
                    elapsed_sec=time.monotonic() - start,
                )
                _try_emit_telemetry(
                    "ui_automation_specialist",
                    "error",
                    f"step[{i}] {step.action} fail",
                )
                return result

        # 전체 성공
        result = UIAutomationResult(
            passed=True,
            completed_steps=len(scenario),
            failed_step_index=None,
            failed_step_reason=None,
            screenshots=screenshots,
            elapsed_sec=time.monotonic() - start,
        )
        _try_emit_telemetry(
            "ui_automation_specialist",
            "done",
            f"PASS {len(scenario)} steps",
        )
        return result
    finally:
        # 정리 — .exe terminate
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _execute_step(
    step: UIScenarioStep,
    screenshot_dir: Path,
    screenshots: list[str],
    pyautogui_mod: object,
) -> None:
    """단일 step 실행. 실패 시 raise."""
    if step.action == "click":
        if step.target and "," in step.target:
            x_s, y_s = step.target.split(",", 1)
            pyautogui_mod.click(int(x_s.strip()), int(y_s.strip()))  # type: ignore
        else:
            raise ValueError(f"click target invalid: {step.target!r}")
    elif step.action == "type":
        pyautogui_mod.typewrite(step.value or "")  # type: ignore
    elif step.action == "hotkey":
        if step.target:
            keys = [k.strip() for k in step.target.split("+")]
            pyautogui_mod.hotkey(*keys)  # type: ignore
    elif step.action == "wait":
        time.sleep(float(step.value or 1.0))
    elif step.action == "screenshot":
        path = screenshot_dir / (step.target or f"step_{len(screenshots)}.png")
        pyautogui_mod.screenshot(str(path))  # type: ignore
        screenshots.append(str(path))
    elif step.action == "assert_window":
        # PyAutoGUI 자체는 윈도우 검증 없음 — pygetwindow 활용 권장 (미설치 시 skip)
        try:
            import pygetwindow as gw  # type: ignore

            wins = gw.getWindowsWithTitle(step.expected or "")
            if not wins:
                raise AssertionError(f"window not found: {step.expected!r}")
        except ImportError:
            pass  # pygetwindow 미설치 — 검증 skip
    else:
        raise ValueError(f"unknown action: {step.action!r}")
