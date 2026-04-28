# -*- coding: utf-8 -*-
"""실행 기반 GUI Test executor (Phase 7 강화 — PR #44).

GUI Test Agent 가 사용하는 결정론적 도구. **subprocess + pyautogui + Claude
Vision 호출** 만 담당 — LLM 보고서 작성은 별도 ``gui_test_agent.py`` 의 책임.

기능 흐름::

    1) target (.exe / .py / 패키지 entry) 을 ``subprocess.Popen`` 으로 실행
    2) ``wait_sec`` 만큼 대기 (GUI 렌더링 시간)
    3) ``pyautogui.screenshot()`` 로 PNG 캡처 (1~N 장)
    4) 자식 프로세스 terminate
    5) 각 스크린샷을 Claude Vision API 에 전송 → 구조화 분석 (JSON)
    6) ``GUITestResult`` 합산 반환

Code QA / Functional Test 와의 차별점:
    - **Code QA Agent (#42)**: pytest + ruff (실행 + 정적). UI 모름.
    - **Functional Test Agent (#43)**: stdin 기반 CLI 검증. GUI 는 timeout.
    - **GUI Test Agent (본 모듈)**: 실제 화면 렌더링 → Vision 으로 *시각적*
      결함 검출 (위젯 누락 / 한글 깨짐 / 에러 다이얼로그 / 레이아웃 잘림).

Optional 의존성 — 미설치 시 graceful skip:
    - **pyautogui**: GUI 자동화. 미설치 시 ``skipped=True`` 반환.
    - **anthropic SDK**: Vision API. 미설치 시 ``vision_analyses=[]``.
    - **ANTHROPIC_API_KEY**: 환경변수. 미설정 시 Vision skip.

CI 안전성:
    - pyautogui 는 활성 디스플레이가 필요 — Linux headless CI 에서는 실패.
    - 본 모듈은 *production / 로컬 Windows* 에서만 의미 있음.
    - 단위 테스트는 모든 외부 호출을 monkeypatch (실제 호출 없음).
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional


_DEFAULT_WAIT_SEC = 2.0
_DEFAULT_TIMEOUT_SEC = 30
_DEFAULT_NUM_SCREENSHOTS = 1
# Vision 분석에는 가장 저렴한 vision-capable Claude 모델을 default 로.
DEFAULT_VISION_MODEL = "claude-haiku-4-5-20251001"

DEFAULT_VISION_PROMPT = """\
당신은 GUI 자동화 검증 전문가입니다. 첨부된 스크린샷을 분석해 다음을 평가하세요:

1. **창 가시성**: 애플리케이션 창이 화면에 정상 렌더링됐는가? (까만 화면 / 빈 화면 / 충돌 다이얼로그가 아닌가)
2. **위젯 완성도**: 버튼·입력창·메뉴·라벨 등 GUI 위젯이 보이는가? 잘리거나 겹쳐 있지 않은가?
3. **텍스트 인코딩**: 한글이 □ / ? / 깨진 글자로 표시되지 않는가?
4. **에러 시그널**: "Error" / "예외" / "Traceback" / "Exception" / 빨간 박스 / 시스템 에러 다이얼로그가 보이는가?
5. **기타 비정상 시그널**: 정상 GUI 라면 절대 보이지 않을 요소.

답변은 반드시 다음 JSON 만 반환 (백틱 없이, 마크다운 없이, 추가 설명 없이):
{
  "summary": "한 문장 요약 (40자 이내)",
  "is_window_visible": true 또는 false,
  "ui_issues": ["이슈1", "이슈2"],
  "critical_issue_count": 정수
}

critical_issue_count 기준:
  - 창이 안 보이거나 충돌 다이얼로그 = 1 이상
  - 한글 깨짐 또는 에러 텍스트 표시 = 1 이상
  - 단순 레이아웃 미세 결함 = 0 (ui_issues 에만 명시)
"""


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class VisionAnalysis:
    """단일 스크린샷의 Vision 분석 결과."""

    __test__: ClassVar[bool] = False  # pytest 수집 차단

    screenshot_path: Path
    model: str
    success: bool
    """Vision API 호출 성공 + JSON 파싱 성공 여부."""

    summary: str = ""
    is_window_visible: Optional[bool] = None
    ui_issues: list[str] = field(default_factory=list)
    critical_issue_count: int = 0
    raw_response: str = ""
    error_message: Optional[str] = None

    def summary_line(self) -> str:
        if not self.success:
            return f"[VISION FAILED] {self.screenshot_path.name}: {self.error_message}"
        marker = "OK" if self.critical_issue_count == 0 else f"CRITICAL×{self.critical_issue_count}"
        return (
            f"[VISION {marker}] {self.screenshot_path.name} "
            f"window_visible={self.is_window_visible} issues={len(self.ui_issues)}"
        )


@dataclass
class GUITestResult:
    """``run_gui_test`` 의 합산 결과."""

    __test__: ClassVar[bool] = False

    success: bool
    """*전체 성공* — pyautogui/Vision 모두 OK + critical_issue_count 합 0."""

    skipped: bool = False
    """pyautogui 미설치 등으로 GUI 검증 자체가 막힌 경우."""

    elapsed_sec: float = 0.0
    target_path: Optional[Path] = None
    screenshot_paths: list[Path] = field(default_factory=list)
    process_exit_code: Optional[int] = None
    process_terminated_by: str = "unknown"
    """``natural_exit`` / ``terminated_after_capture`` / ``timeout_kill`` / ``skipped``."""

    vision_analyses: list[VisionAnalysis] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def total_critical_issues(self) -> int:
        return sum(a.critical_issue_count for a in self.vision_analyses)

    @property
    def total_ui_issues(self) -> int:
        return sum(len(a.ui_issues) for a in self.vision_analyses)

    def summary_line(self) -> str:
        if self.skipped:
            return f"[GUI_TEST SKIPPED] {self.error_message or 'pyautogui 미설치 등'}"
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"[GUI_TEST {verdict}] screenshots={len(self.screenshot_paths)} "
            f"critical={self.total_critical_issues} ui_issues={self.total_ui_issues} "
            f"({self.elapsed_sec:.2f}s)"
        )


# ---------------------------------------------------------------------------
# Optional 의존성 가용성 검사
# ---------------------------------------------------------------------------


def _is_pyautogui_available() -> bool:
    """pyautogui 가 import 가능한지. 실제 화면 접근 가능성은 별도."""
    try:
        import pyautogui  # noqa: F401

        return True
    except (ImportError, KeyError):
        # KeyError: 일부 OS 에서 환경변수 부재 시 import 단계 실패 가능
        return False
    except Exception:
        # pyautogui 가 import 시 X11/macOS 권한 등으로 실패할 수 있음 → skip
        return False


def _is_anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_anthropic_api_key(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    return os.environ.get("ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------
# 스크린샷 캡처 (pyautogui)
# ---------------------------------------------------------------------------


def _take_screenshot(output_path: Path) -> Optional[Path]:
    """pyautogui 로 스크린샷 1장 → PNG 저장. 실패 시 None.

    Optional dependency wrapper — 호출 측이 ``_is_pyautogui_available()`` 사전
    검증한 상태에서만 호출.
    """
    try:
        import pyautogui

        img = pyautogui.screenshot()
        img.save(str(output_path))
        return output_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 타깃 실행 + 캡처
# ---------------------------------------------------------------------------


def launch_and_capture(
    target_path: Path,
    output_dir: Path,
    wait_sec: float = _DEFAULT_WAIT_SEC,
    num_screenshots: int = _DEFAULT_NUM_SCREENSHOTS,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    inter_screenshot_delay: float = 0.5,
) -> tuple[list[Path], Optional[int], str]:
    """target 을 launch 하고 N 장 스크린샷 후 종료.

    Args:
        target_path: 실행할 ``.exe`` 또는 ``.py`` 또는 패키지 entry.
        output_dir: 스크린샷 저장 디렉터리 (생성됨).
        wait_sec: 첫 스크린샷 전 대기 (GUI 렌더링 시간). 기본 2.0.
        num_screenshots: 캡처 장수. 기본 1.
        timeout_sec: 자식 프로세스 강제 종료 임계. 기본 30.
        inter_screenshot_delay: 스크린샷 간 간격. 기본 0.5.

    Returns:
        (screenshot_paths, process_exit_code, terminated_by) — exit_code 가
        None 이면 timeout/manual termination 의미. terminated_by 는
        ``natural_exit`` / ``terminated_after_capture`` / ``timeout_kill``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # subprocess.Popen — .exe 와 .py 분기
    if target_path.suffix.lower() == ".py":
        cmd = [sys.executable, str(target_path)]
    else:
        cmd = [str(target_path)]

    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    started = time.time()
    screenshot_paths: list[Path] = []

    try:
        # 1) 첫 스크린샷 전 대기 (GUI 렌더링)
        time.sleep(wait_sec)

        # 2) N 장 캡처
        for i in range(num_screenshots):
            if i > 0:
                time.sleep(inter_screenshot_delay)
            shot_path = output_dir / f"screenshot_{i + 1:02d}.png"
            saved = _take_screenshot(shot_path)
            if saved:
                screenshot_paths.append(saved)

        # 3) 자식 프로세스 종료
        if proc.poll() is None:
            # 아직 살아 있음 — terminate
            proc.terminate()
            try:
                proc.wait(timeout=5)
                terminated_by = "terminated_after_capture"
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                terminated_by = "timeout_kill"
        else:
            terminated_by = "natural_exit"

        exit_code = proc.returncode

    except Exception:
        # 어떤 단계 실패라도 자식 프로세스 정리
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        raise
    finally:
        # 전체 timeout 검사 — 너무 오래 걸렸으면 정리
        if time.time() - started > timeout_sec and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

    return screenshot_paths, exit_code, terminated_by


# ---------------------------------------------------------------------------
# Vision 분석 (Anthropic API)
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_from_response(text: str) -> Optional[dict[str, Any]]:
    """Vision 응답에서 첫 JSON 블록 추출.

    LLM 이 ``{...}`` 만 반환하길 prompt 했지만, 마크다운 백틱이나 사족이 붙을
    가능성에 대비해 첫 매칭 ``{...}`` 패턴을 시도한다.
    """
    if not text:
        return None
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _encode_image_base64(image_path: Path) -> tuple[str, str]:
    """이미지 → (base64 문자열, media_type)."""
    suffix = image_path.suffix.lower().lstrip(".")
    media_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(suffix, "image/png")
    data = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
    return data, media_type


def analyze_screenshot(
    screenshot_path: Path,
    *,
    model: str = DEFAULT_VISION_MODEL,
    prompt: str = DEFAULT_VISION_PROMPT,
    api_key: Optional[str] = None,
    max_tokens: int = 512,
) -> VisionAnalysis:
    """Anthropic Vision API 로 스크린샷 1장 분석.

    Optional 의존성 / 키 부재 시 ``success=False`` 로 graceful return.
    """
    if not screenshot_path.exists():
        return VisionAnalysis(
            screenshot_path=screenshot_path,
            model=model,
            success=False,
            error_message=f"screenshot 파일 부재: {screenshot_path}",
        )

    if not _is_anthropic_available():
        return VisionAnalysis(
            screenshot_path=screenshot_path,
            model=model,
            success=False,
            error_message="anthropic SDK 미설치",
        )

    resolved_key = _resolve_anthropic_api_key(api_key)
    if not resolved_key:
        return VisionAnalysis(
            screenshot_path=screenshot_path,
            model=model,
            success=False,
            error_message="ANTHROPIC_API_KEY 미설정",
        )

    try:
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=resolved_key)
        b64_data, media_type = _encode_image_base64(screenshot_path)

        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        # response content blocks → 첫 text 블록만
        text_parts = [block.text for block in msg.content if getattr(block, "type", "") == "text"]
        raw_text = "\n".join(text_parts)
    except Exception as e:
        return VisionAnalysis(
            screenshot_path=screenshot_path,
            model=model,
            success=False,
            error_message=f"Vision API 호출 실패: {type(e).__name__}: {e}",
        )

    parsed = _extract_json_from_response(raw_text)
    if parsed is None:
        return VisionAnalysis(
            screenshot_path=screenshot_path,
            model=model,
            success=False,
            raw_response=raw_text,
            error_message="응답에서 JSON 추출 실패 — Vision 모델이 형식 외 텍스트 반환.",
        )

    return VisionAnalysis(
        screenshot_path=screenshot_path,
        model=model,
        success=True,
        summary=str(parsed.get("summary", ""))[:200],
        is_window_visible=parsed.get("is_window_visible"),
        ui_issues=[str(x) for x in (parsed.get("ui_issues") or [])][:20],
        critical_issue_count=int(parsed.get("critical_issue_count", 0) or 0),
        raw_response=raw_text,
    )


# ---------------------------------------------------------------------------
# 묶음 실행 — launch + capture + vision
# ---------------------------------------------------------------------------


def run_gui_test(
    target_path: Path,
    output_dir: Path,
    *,
    wait_sec: float = _DEFAULT_WAIT_SEC,
    num_screenshots: int = _DEFAULT_NUM_SCREENSHOTS,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    skip_vision: bool = False,
    vision_model: str = DEFAULT_VISION_MODEL,
    vision_api_key: Optional[str] = None,
) -> GUITestResult:
    """target launch + screenshot + Vision 분석 묶음.

    Args:
        target_path: 실행할 GUI ``.exe`` 또는 ``.py``.
        output_dir: 스크린샷 저장 디렉터리.
        wait_sec: 첫 스크린샷 전 GUI 렌더링 대기 (기본 2.0).
        num_screenshots: 캡처 장수 (기본 1).
        timeout_sec: 전체 timeout (기본 30).
        skip_vision: True 면 Vision API 호출 생략 — 비용 절감 / 테스트 모드.
        vision_model: Vision 모델 (기본 ``claude-haiku-4-5-20251001``).
        vision_api_key: 명시 API 키. None 이면 ``ANTHROPIC_API_KEY`` env.

    Returns:
        GUITestResult — 캡처 + 분석 합산.
    """
    started = time.time()

    if not target_path.exists():
        return GUITestResult(
            success=False,
            elapsed_sec=time.time() - started,
            target_path=target_path,
            error_message=f"target 부재: {target_path}",
        )

    if not _is_pyautogui_available():
        return GUITestResult(
            success=False,
            skipped=True,
            elapsed_sec=time.time() - started,
            target_path=target_path,
            process_terminated_by="skipped",
            error_message="pyautogui 미설치 — `pip install pyautogui` 필요. GUI 검증 skip.",
        )

    # 1) launch + screenshot
    try:
        screenshot_paths, exit_code, terminated_by = launch_and_capture(
            target_path,
            output_dir,
            wait_sec=wait_sec,
            num_screenshots=num_screenshots,
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        return GUITestResult(
            success=False,
            elapsed_sec=time.time() - started,
            target_path=target_path,
            error_message=f"launch_and_capture 실패: {type(e).__name__}: {e}",
        )

    if not screenshot_paths:
        return GUITestResult(
            success=False,
            elapsed_sec=time.time() - started,
            target_path=target_path,
            process_exit_code=exit_code,
            process_terminated_by=terminated_by,
            error_message="스크린샷 캡처 실패 (pyautogui 가 0 장 반환).",
        )

    # 2) Vision 분석 (skip_vision=False 일 때만)
    vision_analyses: list[VisionAnalysis] = []
    if not skip_vision:
        for shot_path in screenshot_paths:
            vision_analyses.append(
                analyze_screenshot(
                    shot_path, model=vision_model, api_key=vision_api_key
                )
            )

    elapsed = time.time() - started

    # 3) 종합 판정
    total_critical = sum(a.critical_issue_count for a in vision_analyses)
    vision_all_succeeded = all(a.success for a in vision_analyses) if vision_analyses else True
    overall_success = (
        len(screenshot_paths) > 0
        and total_critical == 0
        and vision_all_succeeded
        and terminated_by != "timeout_kill"
    )

    return GUITestResult(
        success=overall_success,
        elapsed_sec=elapsed,
        target_path=target_path,
        screenshot_paths=screenshot_paths,
        process_exit_code=exit_code,
        process_terminated_by=terminated_by,
        vision_analyses=vision_analyses,
    )


# ---------------------------------------------------------------------------
# 헬퍼 — GUI Test Agent Task description 직렬화
# ---------------------------------------------------------------------------


def format_gui_test_result_for_task(
    result: GUITestResult,
    *,
    max_issues_per_screenshot: int = 10,
) -> str:
    """``GUITestResult`` 를 Agent Task description 본문에 직렬화."""
    parts: list[str] = []
    parts.append(
        f"# GUI Test Result — overall_success={result.success}, "
        f"skipped={result.skipped}, elapsed={result.elapsed_sec:.2f}s"
    )
    parts.append(f"target: {result.target_path}")
    if result.skipped:
        parts.append(f"skipped_reason: {result.error_message}")
        return "\n".join(parts)

    parts.append(f"screenshots: {len(result.screenshot_paths)} 장")
    parts.append(
        f"process: exit_code={result.process_exit_code}, "
        f"terminated_by={result.process_terminated_by}"
    )
    parts.append(
        f"summary: critical_issues={result.total_critical_issues}, "
        f"ui_issues={result.total_ui_issues}"
    )
    if result.error_message:
        parts.append(f"error_message: {result.error_message}")

    parts.append("")
    for i, a in enumerate(result.vision_analyses, 1):
        parts.append(f"## screenshot {i} — {a.screenshot_path.name}")
        parts.append(f"  {a.summary_line()}")
        if a.success:
            parts.append(f"  summary: {a.summary}")
            parts.append(f"  is_window_visible: {a.is_window_visible}")
            parts.append(f"  critical_issue_count: {a.critical_issue_count}")
            issues_to_show = a.ui_issues[:max_issues_per_screenshot]
            if issues_to_show:
                parts.append("  ui_issues:")
                for issue in issues_to_show:
                    parts.append(f"    - {issue}")
            if len(a.ui_issues) > max_issues_per_screenshot:
                parts.append(
                    f"    ... ({len(a.ui_issues) - max_issues_per_screenshot} 개 더 생략)"
                )
        else:
            parts.append(f"  error: {a.error_message}")
        parts.append("")

    return "\n".join(parts)
