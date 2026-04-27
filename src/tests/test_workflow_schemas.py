# -*- coding: utf-8 -*-
"""src/workflows/_schemas.py 회귀 방지 테스트.

이슈 6 방어선 2 (PR #31): structured output (CrewAI ``output_pydantic``).
- 스키마 인스턴스 생성·검증
- ``to_markdown()`` 렌더링 형식
- ``task_output_text`` 가 pydantic 우선·raw fallback 처리
"""

from __future__ import annotations

import pytest
from crewai import Task

from src.workflows._common import task_output_text
from src.workflows._schemas import (
    AssetManifestOutput,
    BuildSpecOutput,
    ChangelogEntryOutput,
    CodeReviewOutput,
    DependencyReportOutput,
    DistributionSpecOutput,
    GUICodeOutput,
    GUIDesignOutput,
    InstallerSpecOutput,
    PlatformTestReportOutput,
    ReleaseDecisionOutput,
    ThemeTokensOutput,
    UIUXSpecOutput,
    UpdateModuleSpecOutput,
    _strip_leading_section_header,
)


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


# ---------------------------------------------------------------------------
# _strip_leading_section_header — cosmetic sanitize 유틸 (PR #33)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_text, expected",
    [
        # 첫 줄에 ### N. 헤더 → 제거
        ("### 1. 도구 선택\n- 본문 내용", "- 본문 내용"),
        ("#### 2. 빌드 명령\n명령어 본문", "명령어 본문"),
        # 첫 줄 헤더 제거 후 빈 줄 정리
        ("### 1. 와이어프레임\n\n\nASCII art", "ASCII art"),
        # 헤더 없으면 원본 그대로
        ("- 일반 본문 시작", "- 일반 본문 시작"),
        ("일반 텍스트", "일반 텍스트"),
        # 빈 문자열 처리
        ("", ""),
        # ## 레벨도 제거 (level 2~4 매치)
        ("## 1. 의존성 매니페스트\nyaml content", "yaml content"),
        # 중간 헤더는 그대로 (첫 줄만 제거)
        ("- 첫 줄\n### 2. 다음 섹션\n- 본문", "- 첫 줄\n### 2. 다음 섹션\n- 본문"),
    ],
)
def test_strip_leading_section_header(input_text: str, expected: str) -> None:
    """LLM 이 본문에 자체 ### N. 헤더 포함한 경우 첫 줄 제거 검증."""
    assert _strip_leading_section_header(input_text) == expected


# ---------------------------------------------------------------------------
# 12 신규 스키마 — 인스턴스 생성 + to_markdown 섹션 검증
# (BuildSpec / ReleaseDecision 은 위에서 이미 검증됨)
# ---------------------------------------------------------------------------


def test_code_review_output_renders_5_sections() -> None:
    review = CodeReviewOutput(
        verdict="NEEDS_REVISION",
        overall_assessment="전반적 OK 그러나 보정 필요",
        item_check_table="| # | 항목 | 상태 |",
        issues_found="- **[MAJOR]** `app.py:42` — 인용",
        recommended_fixes="1. fix x",
        out_of_scope="없음",
    )
    md = review.to_markdown()
    assert review.verdict in md
    assert "### 1. 종합 판정" in md
    assert "### 2. 항목별 점검 결과" in md
    assert "### 3. 발견된 이슈" in md
    assert "### 4. 권장 보정" in md
    assert "### 5. 미검토 영역" in md


def test_uiux_spec_output_renders_2_sections() -> None:
    ui = UIUXSpecOutput(
        summary="form_factor=single_window, complexity=simple, need_gui=yes",
        ui_spec_yaml="```yaml\nneed_gui: yes\n```",
        analyst_notes="GUI 판정 근거...",
    )
    md = ui.to_markdown()
    assert ui.summary in md
    assert "## UI/UX 분석" in md
    assert "## 분석가 노트" in md


def test_gui_design_output_renders_4_sections() -> None:
    design = GUIDesignOutput(
        summary="GUI design — 1개 윈도우, 24개 위젯",
        wireframe="┌──────┐\n│ x  │\n└──────┘",
        widget_tree="```yaml\nroot:\n  widget: window\n```",
        interaction_flow="1. 사용자 → 시스템",
        designer_notes="layout=grid 권장",
    )
    md = design.to_markdown()
    assert design.summary in md
    for section in ("### 1. 와이어프레임", "### 2. 위젯 트리", "### 3. 인터랙션 흐름", "### 4. 디자이너 노트"):
        assert section in md


def test_theme_tokens_output_renders_3_sections() -> None:
    theme = ThemeTokensOutput(
        summary="theme_strategy=native, modes=1개, palette=#0B5FFF/...",
        design_tokens_json="```json\n{}\n```",
        application_guide="button → primary",
        theme_notes="노트",
    )
    md = theme.to_markdown()
    assert theme.summary in md
    for section in ("## 디자인 토큰", "## 적용 가이드", "## 디자이너 노트"):
        assert section in md


def test_gui_code_output_renders_3_sections() -> None:
    code = GUICodeOutput(
        summary="framework=tkinter, files=1개, entry=python calculator.py",
        framework_choice="tkinter 선택 근거",
        code_blocks="```python\n# file: calculator.py\n```",
        integration_guide="실행 명령",
    )
    md = code.to_markdown()
    assert code.summary in md
    for section in ("## GUI 구현", "### 1. 프레임워크 선택", "### 2. 코드", "### 3. 통합 가이드"):
        assert section in md


def test_dependency_report_output_renders_3_sections() -> None:
    rep = DependencyReportOutput(
        summary="deps=12개, hidden=2개, license_warnings=0개, os_blockers=0개",
        manifest_yaml="```yaml\ndirect_deps: []\n```",
        analyst_notes="hidden import 1건",
        unverified_areas="lazy import 가능성",
    )
    md = rep.to_markdown()
    assert rep.summary in md
    for section in ("## 의존성 매니페스트", "## 분석가 코멘트", "## 미검토 영역"):
        assert section in md


def test_asset_manifest_output_renders_3_sections() -> None:
    asset = AssetManifestOutput(
        summary="assets — icons=4개, fonts=1개, images=0개, locales=1개, legal=2개",
        manifest_body="```yaml\nicons: []\n```",
        processing_instructions="아이콘 변환 명령",
        manager_notes="placeholder 사용",
    )
    md = asset.to_markdown()
    assert asset.summary in md
    for section in ("## 자원 매니페스트", "## 자원 처리 지시", "## 매니저 노트"):
        assert section in md


def test_installer_spec_output_renders_4_sections() -> None:
    inst = InstallerSpecOutput(
        summary="tool=inno_setup, output=setup.exe, est_size=15MB, signed=no",
        tool_choice="Inno Setup 선택",
        installer_script="[Setup]\nAppName=...",
        user_guide="SmartScreen 안내",
        installer_notes="자원 매핑",
    )
    md = inst.to_markdown()
    assert inst.summary in md
    for section in ("### 1. 도구 선택", "### 2. 인스톨러 스크립트", "### 3. 사용자 가이드", "### 4. 인스톨러 노트"):
        assert section in md


def test_platform_test_report_output_renders_5_sections() -> None:
    report = PlatformTestReportOutput(
        summary="PASS (exit=0, startup=1.2s, elapsed=3.4s)",
        verification_environment="windows / Python 3.13",
        results="PASS — stdout 정상",
        root_cause_diagnosis="진단 불필요",
        reproduction_next_steps="채택 권고",
        out_of_scope="GUI 윈도우 미관찰",
    )
    md = report.to_markdown()
    assert report.summary in md
    for section in (
        "### 1. 검증 환경", "### 2. 결과", "### 3. 근본 원인 진단",
        "### 4. 재현·다음 단계 지침", "### 5. 미관찰 영역",
    ):
        assert section in md


def test_changelog_entry_output_renders_2_sections() -> None:
    ch = ChangelogEntryOutput(
        summary="version=0.2.0, entries=8개, breaking=0개, categories=Added,Changed",
        changelog_body="### Added\n- new feature",
        author_notes="분류 근거",
    )
    md = ch.to_markdown()
    assert ch.summary in md
    for section in ("## CHANGELOG 엔트리", "## 작성자 노트"):
        assert section in md


def test_update_module_spec_output_renders_5_sections() -> None:
    upd = UpdateModuleSpecOutput(
        summary="updater module — endpoint=github.com, sha256_check=yes, signing_check=no, check_interval=24h",
        module_design="ALLOWED_ENDPOINTS",
        updater_py_reference="```python\nimport requests\n```",
        gui_integration="알림 위젯",
        security_checklist="https only",
        author_notes="endpoint 근거",
    )
    md = upd.to_markdown()
    assert upd.summary in md
    for section in (
        "### 1. 모듈 설계", "### 2. updater.py 참조 구현", "### 3. GUI 통합",
        "### 4. 보안 체크리스트", "### 5. 작성자 노트",
    ):
        assert section in md


def test_distribution_spec_output_renders_5_sections() -> None:
    dist = DistributionSpecOutput(
        summary="channel=github_releases, url_template=github.com, signed=no, sha256_in_manifest=yes",
        channel_choice="GitHub Releases 선택",
        upload_commands="```bash\ngh release create\n```",
        release_notes="다운로드 안내",
        update_endpoint_recommendation="https://api.github.com/.../latest",
        distribution_notes="자동화 항목",
    )
    md = dist.to_markdown()
    assert dist.summary in md
    for section in (
        "### 1. 채널 선택", "### 2. 업로드 명령 시퀀스", "### 3. release notes",
        "### 4. Update Checker endpoint 권고", "### 5. 배포 노트",
    ):
        assert section in md


# ---------------------------------------------------------------------------
# Cosmetic 통합 — sanitize 가 to_markdown 안에서 실제 작동하는지 검증
# ---------------------------------------------------------------------------


def test_to_markdown_strips_duplicate_section_header_in_field() -> None:
    """LLM 이 필드 안에 자체 섹션 헤더 포함한 경우 to_markdown 이 제거.

    PR #32 6차 E2E 에서 21_build_spec.md 의 '### 1. 도구 선택' 중복 발견.
    PR #33 sanitize 로 해결.
    """
    spec = BuildSpecOutput(
        summary="tool=pyinstaller, mode=onefile, hidden_imports=0개, est_size=~5MB",
        # LLM 이 자체 헤더 포함한 경우 — sanitize 로 제거되어야 함
        tool_section="### 1. 도구 선택\n\nPyInstaller 6.x 채택",
        command_section="cmd",
        spec_section="spec",
        pitfalls="none",
        checklist=["x"],
        engineer_notes="notes",
    )
    md = spec.to_markdown()
    # ### 1. 도구 선택 헤더는 정확히 한 번만
    assert md.count("### 1. 도구 선택") == 1
    # 본문은 보존
    assert "PyInstaller 6.x 채택" in md
