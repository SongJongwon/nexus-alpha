# -*- coding: utf-8 -*-
"""src/workflows/_schemas.py 회귀 방지 테스트.

이슈 6 방어선 2 (PR #31): structured output (CrewAI ``output_pydantic``).
- 스키마 인스턴스 생성·검증
- ``to_markdown()`` 렌더링 형식
- ``task_output_text`` 가 pydantic 우선·raw fallback 처리
"""

from __future__ import annotations

from crewai import Task

from src.workflows._common import task_output_text
from src.workflows._schemas import BuildSpecOutput, ReleaseDecisionOutput


# ---------------------------------------------------------------------------
# BuildSpecOutput
# ---------------------------------------------------------------------------


def test_build_spec_output_instantiates_with_all_fields() -> None:
    spec = BuildSpecOutput(
        summary="tool=pyinstaller, mode=onefile, hidden_imports=2개, est_size=~12MB",
        tool_section="PyInstaller 6.x 채택. Nuitka 는 컴파일 시간이 길고 cx_Freeze 는 windows-only ...",
        command_section="`pyinstaller --onefile --windowed --icon=app.ico calculator.py`",
        spec_section="hidden imports: tkinter, decimal. data files: 없음. icon: app.ico (256x256).",
        pitfalls="antivirus false positive 가능 — 코드 서명 적용 권장.",
        checklist=["깨끗한 VM 부팅", "첫 윈도우 < 5s", "산출 < 15MB"],
        engineer_notes="Dep Analyzer 가 lazy import 1건 보고 — Build 명령에 hidden import 추가.",
    )
    assert spec.summary.startswith("tool=")
    assert len(spec.checklist) == 3


def test_build_spec_output_to_markdown_includes_all_sections() -> None:
    spec = BuildSpecOutput(
        summary="tool=pyinstaller, mode=onefile, hidden_imports=2개, est_size=~12MB",
        tool_section="도구 본문",
        command_section="명령 본문",
        spec_section="spec 본문",
        pitfalls="함정 본문",
        checklist=["체크 1", "체크 2"],
        engineer_notes="노트 본문",
    )
    md = spec.to_markdown()
    assert spec.summary in md
    assert "### 1. 도구 선택" in md
    assert "### 2. 빌드 명령" in md
    assert "### 3. PyInstaller spec / Nuitka 옵션" in md
    assert "### 4. 함정" in md
    assert "### 5. 빌드 후 검증 체크리스트" in md
    assert "### 6. 빌드 엔지니어 노트" in md
    assert "- [ ] 체크 1" in md
    assert "- [ ] 체크 2" in md


def test_build_spec_output_to_markdown_handles_empty_checklist() -> None:
    spec = BuildSpecOutput(
        summary="tool=x, mode=y, hidden_imports=0개, est_size=~5MB",
        tool_section="x", command_section="x", spec_section="x", pitfalls="x",
        checklist=[], engineer_notes="x",
    )
    md = spec.to_markdown()
    assert "(없음)" in md


# ---------------------------------------------------------------------------
# ReleaseDecisionOutput
# ---------------------------------------------------------------------------


def test_release_decision_output_instantiates_with_all_fields() -> None:
    decision = ReleaseDecisionOutput(
        summary="version=0.2.0, bump=minor, tag=v0.2.0",
        decision_rationale="신기능 1건 (GUI 분기) 추가 → semver minor",
        release_manifest="# v0.2.0\n다운로드: <URL>",
        user_friendly_summary="이번 업데이트로 자연어로 계산기 GUI 를 만들 수 있어요.",
        manager_notes="Distribution Agent 에게 GitHub Release 채널 사용 신호 전달.",
    )
    assert decision.summary.startswith("version=")


def test_release_decision_output_to_markdown_includes_all_sections() -> None:
    decision = ReleaseDecisionOutput(
        summary="version=0.2.0, bump=minor, tag=v0.2.0",
        decision_rationale="근거 본문",
        release_manifest="매니페스트 본문",
        user_friendly_summary="요약 본문",
        manager_notes="노트 본문",
    )
    md = decision.to_markdown()
    assert decision.summary in md
    assert "### 1. 버전 결정 근거" in md
    assert "### 2. RELEASE.md 매니페스트" in md
    assert "### 3. 사용자 친화 한국어 요약" in md
    assert "### 4. 매니저 노트" in md


# ---------------------------------------------------------------------------
# task_output_text — pydantic 우선·raw fallback 검증
# ---------------------------------------------------------------------------


def _make_task() -> Task:
    return Task(description="x", expected_output="y")


class _StubOutput:
    def __init__(self, raw: str = "", pydantic_obj=None):
        self.raw = raw
        self.pydantic = pydantic_obj

        class _Agent:
            role = "test"

        self.agent = _Agent()


def test_task_output_text_prefers_pydantic_to_markdown_over_raw() -> None:
    """output_pydantic 적용된 Task 의 출력은 pydantic.to_markdown() 결과를 우선."""
    spec = BuildSpecOutput(
        summary="tool=pyinstaller, mode=onefile, hidden_imports=0개, est_size=~5MB",
        tool_section="rendered tool section content",
        command_section="cmd", spec_section="spec", pitfalls="none",
        checklist=["item"], engineer_notes="notes",
    )
    task = _make_task()
    object.__setattr__(task, "output", _StubOutput(
        raw='{"summary":"...","tool_section":"..."}',  # JSON 형태의 raw
        pydantic_obj=spec,
    ))
    result = task_output_text(task)
    assert "rendered tool section content" in result
    assert "### 1. 도구 선택" in result
    # raw 가 JSON 으로 시작했는데 결과는 markdown 이어야 함
    assert not result.startswith("{")


def test_task_output_text_falls_back_to_raw_when_no_pydantic() -> None:
    """output_pydantic 미적용 Task 는 기존처럼 raw 반환 (backward compat)."""
    task = _make_task()
    object.__setattr__(task, "output", _StubOutput(raw="plain markdown body"))
    assert task_output_text(task) == "plain markdown body"


def test_task_output_text_falls_back_when_pydantic_render_fails() -> None:
    """to_markdown 이 예외 던지면 graceful 하게 raw 반환."""

    class _BrokenModel:
        def to_markdown(self) -> str:
            raise RuntimeError("simulated render failure")

    task = _make_task()
    object.__setattr__(task, "output", _StubOutput(
        raw="raw fallback content",
        pydantic_obj=_BrokenModel(),
    ))
    assert task_output_text(task) == "raw fallback content"


def test_task_output_text_falls_back_when_pydantic_lacks_to_markdown() -> None:
    """to_markdown 메서드가 없는 모델은 raw 사용 (다른 BaseModel 호환)."""

    class _PlainModel:
        pass  # to_markdown 없음

    task = _make_task()
    object.__setattr__(task, "output", _StubOutput(
        raw="raw fallback",
        pydantic_obj=_PlainModel(),
    ))
    assert task_output_text(task) == "raw fallback"
