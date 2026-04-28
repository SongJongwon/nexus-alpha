# -*- coding: utf-8 -*-
"""src/agents/qa/gui_test_executor.py 회귀 방지 테스트.

PR #44 — GUI 테스트 (pyautogui + Claude Vision) executor.

실제 pyautogui / Anthropic API 호출은 환경 의존이고 비용이 발생하므로 모든
외부 호출 monkeypatch. graceful skip 경로 + 파싱 헬퍼 + 합산 로직 검증.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from src.agents.qa.gui_test_executor import (
    DEFAULT_VISION_MODEL,
    GUITestResult,
    VisionAnalysis,
    _encode_image_base64,
    _extract_json_from_response,
    _is_anthropic_available,
    _is_pyautogui_available,
    _resolve_anthropic_api_key,
    analyze_screenshot,
    format_gui_test_result_for_task,
    run_gui_test,
)


# ---------------------------------------------------------------------------
# 의존성 가용성 검사
# ---------------------------------------------------------------------------


def test_is_anthropic_available_returns_bool() -> None:
    assert _is_anthropic_available() in (True, False)


def test_is_pyautogui_available_returns_bool() -> None:
    """pyautogui 미설치 환경에서 False, 설치 환경에서 True — 둘 다 정상."""
    assert _is_pyautogui_available() in (True, False)


def test_resolve_anthropic_api_key_explicit_wins(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert _resolve_anthropic_api_key("explicit-key") == "explicit-key"


def test_resolve_anthropic_api_key_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert _resolve_anthropic_api_key(None) == "from-env"


def test_resolve_anthropic_api_key_returns_none_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _resolve_anthropic_api_key(None) is None


# ---------------------------------------------------------------------------
# JSON 추출 헬퍼
# ---------------------------------------------------------------------------


def test_extract_json_from_response_clean_json() -> None:
    text = '{"summary": "정상", "is_window_visible": true, "ui_issues": [], "critical_issue_count": 0}'
    parsed = _extract_json_from_response(text)
    assert parsed is not None
    assert parsed["summary"] == "정상"
    assert parsed["is_window_visible"] is True


def test_extract_json_from_response_with_markdown_fence() -> None:
    """LLM 이 백틱으로 감싸도 추출 가능."""
    text = "```json\n{\"summary\": \"OK\", \"critical_issue_count\": 0}\n```"
    parsed = _extract_json_from_response(text)
    assert parsed is not None
    assert parsed["summary"] == "OK"


def test_extract_json_from_response_with_prefix_text() -> None:
    """첫 사족 후 JSON 도 추출."""
    text = '여기 분석 결과:\n{"summary": "OK", "critical_issue_count": 0}'
    parsed = _extract_json_from_response(text)
    assert parsed is not None


def test_extract_json_from_response_invalid_returns_none() -> None:
    assert _extract_json_from_response("not json") is None
    assert _extract_json_from_response("") is None
    assert _extract_json_from_response("{ invalid: json }") is None


# ---------------------------------------------------------------------------
# 이미지 base64 인코딩
# ---------------------------------------------------------------------------


def test_encode_image_base64_round_trip(tmp_path: Path) -> None:
    img_path = tmp_path / "shot.png"
    raw_bytes = b"\x89PNG\r\n\x1a\n" + b"fake_png_body"
    img_path.write_bytes(raw_bytes)

    b64, media_type = _encode_image_base64(img_path)
    assert media_type == "image/png"
    decoded = base64.standard_b64decode(b64.encode("ascii"))
    assert decoded == raw_bytes


def test_encode_image_base64_jpg_media_type(tmp_path: Path) -> None:
    img_path = tmp_path / "shot.jpg"
    img_path.write_bytes(b"\xff\xd8\xff" + b"fake")
    _, media_type = _encode_image_base64(img_path)
    assert media_type == "image/jpeg"


# ---------------------------------------------------------------------------
# analyze_screenshot — graceful skip 경로 + mocked 성공 경로
# ---------------------------------------------------------------------------


def test_analyze_screenshot_missing_file(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nope.png"
    result = analyze_screenshot(nonexistent)
    assert result.success is False
    assert "부재" in (result.error_message or "")


def test_analyze_screenshot_skips_when_anthropic_missing(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: False
    )
    result = analyze_screenshot(img)
    assert result.success is False
    assert "anthropic" in (result.error_message or "").lower()


def test_analyze_screenshot_skips_when_api_key_missing(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: True
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = analyze_screenshot(img, api_key=None)
    assert result.success is False
    assert "ANTHROPIC_API_KEY" in (result.error_message or "")


def test_analyze_screenshot_parses_vision_response(monkeypatch, tmp_path: Path) -> None:
    """anthropic 모듈 + client.messages.create 를 mock — 정상 파싱 검증."""
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: True
    )

    # Mock anthropic.Anthropic 클래스
    class MockTextBlock:
        type = "text"
        text = (
            '{"summary": "계산기 GUI 정상 렌더링", "is_window_visible": true, '
            '"ui_issues": [], "critical_issue_count": 0}'
        )

    class MockMessage:
        content = [MockTextBlock()]

    class MockClient:
        def __init__(self, api_key: str) -> None:  # noqa: ARG002
            self.messages = self

        def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            return MockMessage()

    fake_anthropic_module = type(
        "FakeAnthropicModule",
        (),
        {"Anthropic": MockClient},
    )()
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: True
    )
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic_module)

    result = analyze_screenshot(img, api_key="fake-key")
    assert result.success is True
    assert result.is_window_visible is True
    assert result.critical_issue_count == 0
    assert "정상" in result.summary


def test_analyze_screenshot_handles_invalid_json_response(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: True
    )

    class MockTextBlock:
        type = "text"
        text = "I'm sorry, I can't analyze this image."

    class MockMessage:
        content = [MockTextBlock()]

    class MockClient:
        def __init__(self, api_key: str) -> None:  # noqa: ARG002
            self.messages = self

        def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            return MockMessage()

    fake_module = type("M", (), {"Anthropic": MockClient})()
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = analyze_screenshot(img, api_key="fake-key")
    assert result.success is False
    assert "JSON" in (result.error_message or "")


def test_analyze_screenshot_handles_api_exception(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_anthropic_available", lambda: True
    )

    class MockClient:
        def __init__(self, api_key: str) -> None:  # noqa: ARG002
            self.messages = self

        def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
            raise RuntimeError("API rate limit")

    fake_module = type("M", (), {"Anthropic": MockClient})()
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = analyze_screenshot(img, api_key="fake-key")
    assert result.success is False
    assert "API" in (result.error_message or "")


# ---------------------------------------------------------------------------
# run_gui_test — graceful skip 경로
# ---------------------------------------------------------------------------


def test_run_gui_test_target_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nope.exe"
    result = run_gui_test(nonexistent, output_dir=tmp_path)
    assert result.success is False
    assert "부재" in (result.error_message or "")


def test_run_gui_test_skips_when_pyautogui_missing(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: False
    )
    result = run_gui_test(target, output_dir=tmp_path)
    assert result.success is False
    assert result.skipped is True
    assert "pyautogui" in (result.error_message or "").lower()


def test_run_gui_test_full_path_with_mocked_capture_and_vision(
    monkeypatch, tmp_path: Path
) -> None:
    """pyautogui / launch / Vision 모두 mock — 정상 흐름 합산 검증."""
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")
    output_dir = tmp_path / "out"

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: True
    )

    fake_shot = output_dir / "screenshot_01.png"
    fake_shot.parent.mkdir(parents=True, exist_ok=True)
    fake_shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def fake_launch(*args, **kwargs):  # noqa: ARG001
        return [fake_shot], 0, "terminated_after_capture"

    def fake_analyze(path, **kwargs):  # noqa: ARG001
        return VisionAnalysis(
            screenshot_path=path,
            model=DEFAULT_VISION_MODEL,
            success=True,
            summary="정상",
            is_window_visible=True,
            ui_issues=[],
            critical_issue_count=0,
        )

    monkeypatch.setattr("src.agents.qa.gui_test_executor.launch_and_capture", fake_launch)
    monkeypatch.setattr("src.agents.qa.gui_test_executor.analyze_screenshot", fake_analyze)

    result = run_gui_test(target, output_dir=output_dir)
    assert result.success is True
    assert result.skipped is False
    assert len(result.screenshot_paths) == 1
    assert len(result.vision_analyses) == 1
    assert result.total_critical_issues == 0


def test_run_gui_test_failure_when_critical_issues_detected(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    fake_shot = output_dir / "screenshot_01.png"
    fake_shot.write_bytes(b"\x89PNG")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: True
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.launch_and_capture",
        lambda *a, **kw: ([fake_shot], 0, "terminated_after_capture"),
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.analyze_screenshot",
        lambda path, **kw: VisionAnalysis(
            screenshot_path=path,
            model=DEFAULT_VISION_MODEL,
            success=True,
            summary="에러 다이얼로그 표시",
            is_window_visible=True,
            ui_issues=["빨간 에러 박스 보임", "한글 깨짐"],
            critical_issue_count=2,
        ),
    )

    result = run_gui_test(target, output_dir=output_dir)
    assert result.success is False
    assert result.total_critical_issues == 2


def test_run_gui_test_skip_vision_omits_api_calls(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    fake_shot = output_dir / "screenshot_01.png"
    fake_shot.write_bytes(b"\x89PNG")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: True
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.launch_and_capture",
        lambda *a, **kw: ([fake_shot], 0, "terminated_after_capture"),
    )

    def explode(*a, **kw):  # noqa: ARG001
        raise AssertionError("Vision 호출되면 안 됨 (skip_vision=True)")

    monkeypatch.setattr("src.agents.qa.gui_test_executor.analyze_screenshot", explode)

    result = run_gui_test(target, output_dir=output_dir, skip_vision=True)
    assert result.success is True  # critical=0 + vision_all_succeeded(empty list = True)
    assert result.vision_analyses == []


def test_run_gui_test_failure_when_no_screenshots(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: True
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.launch_and_capture",
        lambda *a, **kw: ([], 0, "natural_exit"),
    )

    result = run_gui_test(target, output_dir=tmp_path)
    assert result.success is False
    assert "스크린샷 캡처 실패" in (result.error_message or "")


def test_run_gui_test_failure_on_timeout_kill(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('hi')", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    fake_shot = output_dir / "screenshot_01.png"
    fake_shot.write_bytes(b"\x89PNG")

    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor._is_pyautogui_available", lambda: True
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.launch_and_capture",
        lambda *a, **kw: ([fake_shot], None, "timeout_kill"),
    )
    monkeypatch.setattr(
        "src.agents.qa.gui_test_executor.analyze_screenshot",
        lambda path, **kw: VisionAnalysis(
            screenshot_path=path,
            model=DEFAULT_VISION_MODEL,
            success=True,
            summary="OK",
            critical_issue_count=0,
        ),
    )

    result = run_gui_test(target, output_dir=output_dir)
    # timeout_kill → success=False (응답 없음 신호)
    assert result.success is False


# ---------------------------------------------------------------------------
# format_gui_test_result_for_task
# ---------------------------------------------------------------------------


def test_format_gui_test_skipped_path(tmp_path: Path) -> None:
    result = GUITestResult(
        success=False,
        skipped=True,
        elapsed_sec=0.0,
        target_path=tmp_path / "target.py",
        error_message="pyautogui 미설치",
    )
    text = format_gui_test_result_for_task(result)
    assert "skipped=True" in text
    assert "pyautogui" in text
    # skipped 시 스크린샷별 분석 안 나옴
    assert "## screenshot 1" not in text


def test_format_gui_test_full_result(tmp_path: Path) -> None:
    shot = tmp_path / "screenshot_01.png"
    shot.write_bytes(b"\x89PNG")
    analysis = VisionAnalysis(
        screenshot_path=shot,
        model=DEFAULT_VISION_MODEL,
        success=True,
        summary="계산기 정상 렌더링",
        is_window_visible=True,
        ui_issues=["밑줄 표시 누락"],
        critical_issue_count=0,
    )
    result = GUITestResult(
        success=True,
        elapsed_sec=3.5,
        target_path=tmp_path / "Calculator.exe",
        screenshot_paths=[shot],
        process_exit_code=0,
        process_terminated_by="terminated_after_capture",
        vision_analyses=[analysis],
    )
    text = format_gui_test_result_for_task(result)
    assert "overall_success=True" in text
    assert "## screenshot 1" in text
    assert "정상 렌더링" in text
    assert "밑줄 표시 누락" in text


def test_format_gui_test_truncates_too_many_issues(tmp_path: Path) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    issues = [f"이슈{i}" for i in range(20)]
    analysis = VisionAnalysis(
        screenshot_path=shot,
        model=DEFAULT_VISION_MODEL,
        success=True,
        summary="다수 결함",
        ui_issues=issues,
        critical_issue_count=3,
    )
    result = GUITestResult(
        success=False,
        elapsed_sec=1.0,
        screenshot_paths=[shot],
        vision_analyses=[analysis],
    )
    text = format_gui_test_result_for_task(result, max_issues_per_screenshot=5)
    assert "이슈0" in text
    assert "이슈4" in text
    # 5개 까지만 보이고 나머지 15개는 생략
    assert "이슈10" not in text
    assert "15 개 더 생략" in text


def test_format_gui_test_includes_failure_diagnostic(tmp_path: Path) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    analysis = VisionAnalysis(
        screenshot_path=shot,
        model=DEFAULT_VISION_MODEL,
        success=False,
        error_message="API 호출 실패: Timeout",
    )
    result = GUITestResult(
        success=False,
        elapsed_sec=10.0,
        screenshot_paths=[shot],
        vision_analyses=[analysis],
    )
    text = format_gui_test_result_for_task(result)
    assert "VISION FAILED" in text
    assert "API 호출 실패" in text


# ---------------------------------------------------------------------------
# summary_line — 표기 검증
# ---------------------------------------------------------------------------


def test_vision_analysis_summary_line_ok(tmp_path: Path) -> None:
    a = VisionAnalysis(
        screenshot_path=tmp_path / "s.png",
        model=DEFAULT_VISION_MODEL,
        success=True,
        critical_issue_count=0,
        ui_issues=[],
        is_window_visible=True,
    )
    line = a.summary_line()
    assert "VISION OK" in line


def test_vision_analysis_summary_line_critical(tmp_path: Path) -> None:
    a = VisionAnalysis(
        screenshot_path=tmp_path / "s.png",
        model=DEFAULT_VISION_MODEL,
        success=True,
        critical_issue_count=2,
        ui_issues=["x", "y"],
        is_window_visible=False,
    )
    line = a.summary_line()
    assert "CRITICAL×2" in line


def test_gui_test_result_summary_line_skipped() -> None:
    r = GUITestResult(success=False, skipped=True, elapsed_sec=0.0)
    line = r.summary_line()
    assert "SKIPPED" in line


def test_gui_test_result_summary_line_pass() -> None:
    r = GUITestResult(success=True, elapsed_sec=3.0)
    line = r.summary_line()
    assert "GUI_TEST PASS" in line
