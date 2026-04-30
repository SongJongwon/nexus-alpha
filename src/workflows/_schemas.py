# -*- coding: utf-8 -*-
"""Pydantic output schemas for structured agent output (이슈 6 방어선 2).

PR #29 (방어선 1 — auto-retry) 의 한계:
  PR #30 5차 E2E 결과 캡처율 75% 정체. 일부 에이전트 (BuildEngineer, ReleaseManager)
  는 *체계적* 으로 본문 생략 — 결정형 요약 형식의 자기-종결성 때문에 단순 재시도
  로 회복 불가.

방어선 2 — CrewAI 의 ``output_pydantic`` 파라미터 활용:
  Task 에 ``output_pydantic=<BaseModel>`` 을 지정하면 CrewAI 가 LLM 에게
  스키마를 강제. LLM 이 JSON 으로 응답 → ``task.output.pydantic`` 에 파싱된
  모델 인스턴스 저장. 누락 필드가 있으면 CrewAI 가 자동 재호출.

PR #31 (시범 — 2 에이전트): BuildSpec / ReleaseDecision. 6차 E2E 100% 본문 캡처.
PR #33 (확장 — 12 에이전트): 활성 체인의 나머지 에이전트로 확장.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════
# 공용 sanitize 유틸 — LLM 이 본문 첫 줄에 자체 ### N. 헤더를 포함한 경우 제거
# (PR #32 6차 E2E 에서 21_build_spec.md 의 ### 1. 도구 선택 중복 발견)
# ══════════════════════════════════════════════════════════════════════════

_LEADING_HEADER_RE = re.compile(r"^#{2,4}\s+\d+\.\s+[^\n]+\n+", re.MULTILINE)


def _strip_leading_section_header(text: str) -> str:
    """본문 첫 줄이 `### N. <name>` 형태면 제거.

    LLM 이 종종 필드 본문 안에 자체 섹션 헤더를 포함 → ``to_markdown()`` 의
    헤더와 중복. 첫 줄만 제거하고 나머지는 보존.
    """
    if not text:
        return text
    stripped = text.lstrip()
    match = _LEADING_HEADER_RE.match(stripped)
    if match:
        return stripped[match.end():].lstrip()
    return text


# ══════════════════════════════════════════════════════════════════════════
# Build Engineer — 빌드 사양 5단 구조
# ══════════════════════════════════════════════════════════════════════════


class BuildSpecOutput(BaseModel):
    """Build Engineer 출력 스키마 — output_pydantic 으로 구조 강제."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'tool=<X>, mode=<Y>, hidden_imports=<N>개, "
            "est_size=~<Z>MB' (예: 'tool=pyinstaller, mode=onefile, "
            "hidden_imports=2개, est_size=~12MB')"
        ),
    )
    tool_section: str = Field(
        description=(
            "### 1. 도구 선택 본문. PyInstaller / Nuitka / cx_Freeze 중 어느 것을 "
            "고르는지와 그 근거 (호환성·산출 크기·온보딩 비용 트레이드오프)"
        ),
    )
    command_section: str = Field(
        description=(
            "### 2. 빌드 명령 본문. 정확한 명령어 + 옵션 + entry point. "
            "재현 가능하도록 모든 인자를 명시"
        ),
    )
    spec_section: str = Field(
        description=(
            "### 3. PyInstaller spec / Nuitka 옵션 본문. hidden imports + data "
            "files + icon + version 메타데이터 등의 spec 파일 / 옵션 사양"
        ),
    )
    pitfalls: str = Field(
        description=(
            "### 4. 함정 본문. 이번 빌드에서 특별히 주의해야 할 점 "
            "(antivirus false positive, dynamic import, lazy load 등)"
        ),
    )
    checklist: list[str] = Field(
        description=(
            "### 5. 빌드 후 검증 체크리스트. 5~7 항목 "
            "(예: '깨끗한 VM 에서 더블클릭 실행', '첫 윈도우 표시 < 5s', "
            "'산출 크기 ±20% 이내' 등). 각 항목은 한 줄"
        ),
    )
    engineer_notes: str = Field(
        description=(
            "### 6. 빌드 엔지니어 노트. Dependency Analyzer 의 신호 반영 + "
            "후속 단계 (Asset Manager / Installer Creator / Platform Tester) "
            "에 전달할 주의 사항"
        ),
    )

    def to_markdown(self) -> str:
        checklist_md = "\n".join(f"- [ ] {item}" for item in self.checklist) or "- (없음)"
        return (
            f"{self.summary}\n\n"
            f"### 1. 도구 선택\n\n{_strip_leading_section_header(self.tool_section)}\n\n"
            f"### 2. 빌드 명령\n\n{_strip_leading_section_header(self.command_section)}\n\n"
            f"### 3. PyInstaller spec / Nuitka 옵션\n\n{_strip_leading_section_header(self.spec_section)}\n\n"
            f"### 4. 함정\n\n{_strip_leading_section_header(self.pitfalls)}\n\n"
            f"### 5. 빌드 후 검증 체크리스트\n\n{checklist_md}\n\n"
            f"### 6. 빌드 엔지니어 노트\n\n{_strip_leading_section_header(self.engineer_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Release Manager — 릴리스 결정 4단 구조
# ══════════════════════════════════════════════════════════════════════════


class ReleaseDecisionOutput(BaseModel):
    """Release Manager 출력 스키마."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'version=<X.Y.Z>, bump=<major|minor|patch|prerelease>, "
            "tag=v<X.Y.Z>' (예: 'version=0.2.0, bump=minor, tag=v0.2.0')"
        ),
    )
    decision_rationale: str = Field(
        description=(
            "### 1. 버전 결정 근거. semver 기준으로 어떤 변경이 어떤 bump 를 "
            "요구하는지 (breaking change → major, 새 기능 → minor, 버그 → patch)"
        ),
    )
    release_manifest: str = Field(
        description=(
            "### 2. RELEASE.md 매니페스트 (다운로드 URL placeholder 포함). "
            "릴리스 노트 본문 — 사용자가 실제로 읽을 markdown"
        ),
    )
    user_friendly_summary: str = Field(
        description=(
            "### 3. 사용자 친화 한국어 요약 3~4 문장. 비전공자가 읽고 *왜* "
            "업데이트할 가치가 있는지 이해할 수 있는 톤. 가시 변화 위주"
        ),
    )
    manager_notes: str = Field(
        description=(
            "### 4. 매니저 노트. 이번 결정의 가장 큰 위험 + Changelog Generator / "
            "Distribution Agent 에게 전달할 핵심 신호"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 버전 결정 근거\n\n{_strip_leading_section_header(self.decision_rationale)}\n\n"
            f"### 2. RELEASE.md 매니페스트\n\n{_strip_leading_section_header(self.release_manifest)}\n\n"
            f"### 3. 사용자 친화 한국어 요약\n\n{_strip_leading_section_header(self.user_friendly_summary)}\n\n"
            f"### 4. 매니저 노트\n\n{_strip_leading_section_header(self.manager_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# QA — Code Reviewer (5단 구조: 종합 판정 / 항목별 점검 / 발견된 이슈 / 권장 보정 / 미검토)
# ══════════════════════════════════════════════════════════════════════════


class CodeReviewOutput(BaseModel):
    """Code Reviewer 출력 스키마. PR #28/#30/#32 모두 'NEEDS_REVISION' 1단어로 종결되는
    systematic failure → output_pydantic 으로 5단 본문 강제."""

    verdict: str = Field(
        description="`APPROVED` 또는 `NEEDS_REVISION` 둘 중 하나만",
    )
    overall_assessment: str = Field(
        description=(
            "### 1. 종합 판정 본문. 결과(APPROVED/NEEDS_REVISION) 와 한 단락 (2~4문장) "
            "근거 요약. 섹션 헤더 (### 1. ...) 없이 본문만"
        ),
    )
    item_check_table: str = Field(
        description=(
            "### 2. 항목별 점검 결과 본문 (markdown 표). 5개 항목 (타입힌트 / 에러처리 / "
            "테스트 격리 / 경계 예외 / 모듈 분리) 각각 ✅/⚠️/❌ + 한 줄 코멘트. "
            "섹션 헤더 없이 본문만"
        ),
    )
    issues_found: str = Field(
        description=(
            "### 3. 발견된 이슈 본문. 각 이슈 형식: '- **[BLOCKER|MAJOR|MINOR]** "
            "`<file>:<line>` — 인용 + 문제 + 보정안'. 0건이면 '발견된 이슈 없음'. "
            "섹션 헤더 없이 본문만"
        ),
    )
    recommended_fixes: str = Field(
        description=(
            "### 4. 권장 보정 본문 (NEEDS_REVISION 일 때만). 우선순위 순 번호 매김 + "
            "가능 시 코드 스니펫. APPROVED 면 '해당 없음'. 섹션 헤더 없이 본문만"
        ),
    )
    out_of_scope: str = Field(
        description=(
            "### 5. 미검토 영역 본문. 분량·범위상 본 리뷰에서 다루지 못한 부분. "
            "없으면 '없음'. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.verdict}\n\n"
            f"## 코드 리뷰 보고서\n\n"
            f"### 1. 종합 판정\n\n{_strip_leading_section_header(self.overall_assessment)}\n\n"
            f"### 2. 항목별 점검 결과\n\n{_strip_leading_section_header(self.item_check_table)}\n\n"
            f"### 3. 발견된 이슈\n\n{_strip_leading_section_header(self.issues_found)}\n\n"
            f"### 4. 권장 보정\n\n{_strip_leading_section_header(self.recommended_fixes)}\n\n"
            f"### 5. 미검토 영역\n\n{_strip_leading_section_header(self.out_of_scope)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Planning — UI/UX Analyst (2단: ui_spec YAML + 분석가 노트)
# ══════════════════════════════════════════════════════════════════════════


class UIUXSpecOutput(BaseModel):
    """UI/UX Analyst — form_factor / complexity / need_gui 결정."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'form_factor=<X>, complexity=<Y>, need_gui=<yes|no>' "
            "(예: 'form_factor=single_window, complexity=simple, need_gui=yes')"
        ),
    )
    ui_spec_yaml: str = Field(
        description=(
            "## UI/UX 분석 본문. ```yaml ... ``` 코드 블록 안에 need_gui / "
            "form_factor / complexity / questions(5) / assumptions / "
            "recommended_framework_hint 모두 포함. 섹션 헤더 없이 본문만"
        ),
    )
    analyst_notes: str = Field(
        description=(
            "## 분석가 노트 본문. GUI vs CLI 판정 근거 + 가장 위험한 가정 + 디자인 "
            "본부에 줄 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## UI/UX 분석\n\n{_strip_leading_section_header(self.ui_spec_yaml)}\n\n"
            f"## 분석가 노트\n\n{_strip_leading_section_header(self.analyst_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Design — GUI Designer (4단: 와이어프레임 / 위젯 트리 / 인터랙션 / 노트)
# ══════════════════════════════════════════════════════════════════════════


class GUIDesignOutput(BaseModel):
    """GUI Designer — 와이어프레임 + 위젯 트리 + 인터랙션 흐름."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'GUI design — <N>개 윈도우, <M>개 위젯' "
            "(예: 'GUI design — 1개 윈도우, 24개 위젯')"
        ),
    )
    wireframe: str = Field(
        description=(
            "### 1. 와이어프레임 본문. ASCII art 또는 markdown 표로 1차 와이어 표현. "
            "섹션 헤더 없이 본문만"
        ),
    )
    widget_tree: str = Field(
        description=(
            "### 2. 위젯 트리 본문. ```yaml ... ``` 안에 root → children 계층. "
            "위젯 종류는 일반명 (button / label / entry / textarea / table 등) — "
            "특정 프레임워크 클래스명 사용 금지. 섹션 헤더 없이 본문만"
        ),
    )
    interaction_flow: str = Field(
        description=(
            "### 3. 인터랙션 흐름 본문. 사용자 액션 → 시스템 반응 시퀀스 + 오류 케이스. "
            "섹션 헤더 없이 본문만"
        ),
    )
    designer_notes: str = Field(
        description=(
            "### 4. 디자이너 노트 본문. 분석가 가정 의존성 + Theme 톤 힌트 + "
            "Code Generator layout 힌트. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 와이어프레임\n\n{_strip_leading_section_header(self.wireframe)}\n\n"
            f"### 2. 위젯 트리\n\n{_strip_leading_section_header(self.widget_tree)}\n\n"
            f"### 3. 인터랙션 흐름\n\n{_strip_leading_section_header(self.interaction_flow)}\n\n"
            f"### 4. 디자이너 노트\n\n{_strip_leading_section_header(self.designer_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Design — Theme Designer (3단: 디자인 토큰 JSON + 적용 가이드 + 노트)
# ══════════════════════════════════════════════════════════════════════════


class ThemeTokensOutput(BaseModel):
    """Theme Designer — 디자인 토큰 + 매핑. PR #30/#32 systematic 짧음."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'theme_strategy=<X>, modes=<N>개, palette=<5색 hex>' "
            "(예: 'theme_strategy=native, modes=1개, palette=#0B5FFF/#5A6573/...')"
        ),
    )
    design_tokens_json: str = Field(
        description=(
            "## 디자인 토큰 본문. ```json ... ``` 안에 theme_strategy / colors / "
            "typography / spacing / radii / motion 토큰 모두 포함. 섹션 헤더 없이 본문만"
        ),
    )
    application_guide: str = Field(
        description=(
            "## 적용 가이드 본문. 위젯 종류별 토큰 매핑 (button → primary color "
            "+ medium radius 등). WCAG AA 대비 검증 결과 포함. 섹션 헤더 없이 본문만"
        ),
    )
    theme_notes: str = Field(
        description=(
            "## 디자이너 노트 본문. 가장 중요한 토큰 결정 근거 + Code Generator 에 "
            "줄 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## 디자인 토큰\n\n{_strip_leading_section_header(self.design_tokens_json)}\n\n"
            f"## 적용 가이드\n\n{_strip_leading_section_header(self.application_guide)}\n\n"
            f"## 디자이너 노트\n\n{_strip_leading_section_header(self.theme_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Design — GUI Code Generator (3단: 프레임워크 / 코드 / 통합 가이드)
# ══════════════════════════════════════════════════════════════════════════


class GUICodeOutput(BaseModel):
    """GUI Code Generator — 실제 Python 코드 산출."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'framework=<X>, files=<N>개, entry=python <file>' "
            "(예: 'framework=tkinter, files=1개, entry=python calculator.py')"
        ),
    )
    framework_choice: str = Field(
        description=(
            "### 1. 프레임워크 선택 본문. tkinter / PyQt / Flet / customtkinter 중 "
            "선택 + 근거 + 추가 의존성. 섹션 헤더 없이 본문만"
        ),
    )
    code_blocks: str = Field(
        description=(
            "### 2. 코드 본문. ```python ... ``` 코드 블록 (각 블록 첫 줄에 "
            "`# file: <path>` 주석). 단독 실행 가능 (절대 import). 섹션 헤더 없이 본문만"
        ),
    )
    integration_guide: str = Field(
        description=(
            "### 3. 통합 가이드 본문. 실행 명령 + 의존성 설치 + 디자이너 노트 의 "
            "layout 힌트 반영 설명. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## GUI 구현\n\n"
            f"### 1. 프레임워크 선택\n\n{_strip_leading_section_header(self.framework_choice)}\n\n"
            f"### 2. 코드\n\n{_strip_leading_section_header(self.code_blocks)}\n\n"
            f"### 3. 통합 가이드\n\n{_strip_leading_section_header(self.integration_guide)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Build — Dependency Analyzer (3단: YAML 매니페스트 6축 + 코멘트 + 미검토)
# ══════════════════════════════════════════════════════════════════════════


class DependencyReportOutput(BaseModel):
    """Dependency Analyzer — 의존성 6축 보고서."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'deps=<N>개, hidden=<M>개, license_warnings=<L>개, "
            "os_blockers=<B>개'"
        ),
    )
    manifest_yaml: str = Field(
        description=(
            "## 의존성 매니페스트 본문. ```yaml ... ``` 안에 6축 (direct_deps / "
            "hidden_imports / data_files / native_binaries / license_warnings / "
            "os_specific). 섹션 헤더 없이 본문만"
        ),
    )
    analyst_notes: str = Field(
        description=(
            "## 분석가 코멘트 본문. 가장 시급한 hidden import + 결정 필요 항목 + "
            "Build Engineer 신호. 섹션 헤더 없이 본문만"
        ),
    )
    unverified_areas: str = Field(
        description=(
            "## 미검토 영역 본문. 본 분석에서 못 본 부분 (lazy import 가능성 등). "
            "없으면 '없음'. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## 의존성 매니페스트\n\n{_strip_leading_section_header(self.manifest_yaml)}\n\n"
            f"## 분석가 코멘트\n\n{_strip_leading_section_header(self.analyst_notes)}\n\n"
            f"## 미검토 영역\n\n{_strip_leading_section_header(self.unverified_areas)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Build — Asset Manager (3단: 매니페스트 + 처리 지시 + 매니저 노트)
# ══════════════════════════════════════════════════════════════════════════


class AssetManifestOutput(BaseModel):
    """Asset Manager — 비-코드 자원 매니페스트."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'assets — icons=<N>개, fonts=<M>개, images=<I>개, "
            "locales=<L>개, legal=<L2>개'"
        ),
    )
    manifest_body: str = Field(
        description=(
            "## 자원 매니페스트 본문. ```yaml ... ``` 안에 icons / fonts / images / "
            "locales / legal / app_metadata 모두. placeholder 항목은 명시. "
            "섹션 헤더 없이 본문만"
        ),
    )
    processing_instructions: str = Field(
        description=(
            "## 자원 처리 지시 본문. 아이콘 변환 명령 + 폰트 라이선스 동봉 + 로케일 "
            "누락 안내. 섹션 헤더 없이 본문만"
        ),
    )
    manager_notes: str = Field(
        description=(
            "## 매니저 노트 본문. placeholder 사용 사후 교체 권고 + 산출 크기 영향 "
            "큰 자원 + Installer Creator 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## 자원 매니페스트\n\n{_strip_leading_section_header(self.manifest_body)}\n\n"
            f"## 자원 처리 지시\n\n{_strip_leading_section_header(self.processing_instructions)}\n\n"
            f"## 매니저 노트\n\n{_strip_leading_section_header(self.manager_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Build — Installer Creator (4단: 도구 / 스크립트 / 사용자 가이드 / 노트)
# ══════════════════════════════════════════════════════════════════════════


class InstallerSpecOutput(BaseModel):
    """Installer Creator — Inno Setup / WiX / pkgbuild / AppImage 사양."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'tool=<X>, output=<setup.exe|...>, est_size=<N>MB, "
            "signed=<yes|no>'"
        ),
    )
    tool_choice: str = Field(
        description=(
            "### 1. 도구 선택 본문. target_platform 기준 인스톨러 도구 선택 + 근거. "
            "섹션 헤더 없이 본문만"
        ),
    )
    installer_script: str = Field(
        description=(
            "### 2. 인스톨러 스크립트 본문. ```ini``` 또는 ```xml``` 안에 정확한 "
            "스크립트. 섹션 헤더 없이 본문만"
        ),
    )
    user_guide: str = Field(
        description=(
            "### 3. 사용자 가이드 본문. SmartScreen/Gatekeeper 안내 + 설치 디렉터리 + "
            "단축키. 섹션 헤더 없이 본문만"
        ),
    )
    installer_notes: str = Field(
        description=(
            "### 4. 인스톨러 노트 본문. Asset 매니페스트 반영 + 빠진 자원 + 코드 서명 "
            "+ Platform Tester 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 도구 선택\n\n{_strip_leading_section_header(self.tool_choice)}\n\n"
            f"### 2. 인스톨러 스크립트\n\n{_strip_leading_section_header(self.installer_script)}\n\n"
            f"### 3. 사용자 가이드\n\n{_strip_leading_section_header(self.user_guide)}\n\n"
            f"### 4. 인스톨러 노트\n\n{_strip_leading_section_header(self.installer_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Build — Platform Tester (5단: 환경 / 결과 / 원인 / 재현 / 미관찰)
# ══════════════════════════════════════════════════════════════════════════


class PlatformTestReportOutput(BaseModel):
    """Platform Tester — sandbox 결과 narration."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: '<verdict> (exit=<int>, startup=<X.X>s, "
            "elapsed=<X.X>s)'"
        ),
    )
    verification_environment: str = Field(
        description=(
            "### 1. 검증 환경 본문. target_platform / Python 버전 / sandbox 한계 "
            "(진짜 .exe 아님 — .py 부팅 smoke). 섹션 헤더 없이 본문만"
        ),
    )
    results: str = Field(
        description=(
            "### 2. 결과 본문. PASS/FAIL/CRASH/TIMEOUT + stdout/stderr 인용. "
            "섹션 헤더 없이 본문만"
        ),
    )
    root_cause_diagnosis: str = Field(
        description=(
            "### 3. 근본 원인 진단 본문 (FAIL/CRASH/TIMEOUT 일 때만). 추정 원인 1~3 "
            "순위. PASS 면 '진단 불필요'. 섹션 헤더 없이 본문만"
        ),
    )
    reproduction_next_steps: str = Field(
        description=(
            "### 4. 재현·다음 단계 지침 본문. 환경 가정 + 보정 방향 우선순위. "
            "섹션 헤더 없이 본문만"
        ),
    )
    out_of_scope: str = Field(
        description=(
            "### 5. 미관찰 영역 본문. 확인 못 한 동작 (실제 GUI 표시 / 사용자 입력 / "
            "장시간 안정성) + Windows Sandbox/Docker 미적용 명시. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 검증 환경\n\n{_strip_leading_section_header(self.verification_environment)}\n\n"
            f"### 2. 결과\n\n{_strip_leading_section_header(self.results)}\n\n"
            f"### 3. 근본 원인 진단\n\n{_strip_leading_section_header(self.root_cause_diagnosis)}\n\n"
            f"### 4. 재현·다음 단계 지침\n\n{_strip_leading_section_header(self.reproduction_next_steps)}\n\n"
            f"### 5. 미관찰 영역\n\n{_strip_leading_section_header(self.out_of_scope)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Release — Changelog Generator (2단: CHANGELOG 항목 + 작성자 노트)
# ══════════════════════════════════════════════════════════════════════════


class ChangelogEntryOutput(BaseModel):
    """Changelog Generator — Keep a Changelog 형식 항목."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'version=<X.Y.Z>, entries=<N>개, breaking=<B>개, "
            "categories=<쉼표 구분>'"
        ),
    )
    changelog_body: str = Field(
        description=(
            "## CHANGELOG 엔트리 본문. ```markdown ... ``` 안에 Keep a Changelog "
            "형식 (Added / Changed / Deprecated / Removed / Fixed / Security). "
            "빈 카테고리는 헤더째 생략. 섹션 헤더 없이 본문만"
        ),
    )
    author_notes: str = Field(
        description=(
            "## 작성자 노트 본문. 카테고리 분류 근거 + 사용자 시점 옮긴 항목 + "
            "Distribution Agent 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## CHANGELOG 엔트리\n\n{_strip_leading_section_header(self.changelog_body)}\n\n"
            f"## 작성자 노트\n\n{_strip_leading_section_header(self.author_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Release — Update Checker (5단: 모듈 설계 / updater.py / GUI 통합 / 보안 / 노트)
# ══════════════════════════════════════════════════════════════════════════


class UpdateModuleSpecOutput(BaseModel):
    """Update Checker — 자동 업데이트 모듈 사양 + 참조 구현."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'updater module — endpoint=<URL 도메인>, "
            "sha256_check=yes, signing_check=<yes|no>, check_interval=24h'"
        ),
    )
    module_design: str = Field(
        description=(
            "### 1. 모듈 설계 본문. ALLOWED_ENDPOINTS / 캐시 정책 / 사용자 동의 흐름. "
            "섹션 헤더 없이 본문만"
        ),
    )
    updater_py_reference: str = Field(
        description=(
            "### 2. updater.py 참조 구현 본문. ```python ... ``` 안에 실제 사용 가능한 "
            "구현 (requests + sha256 검증). 섹션 헤더 없이 본문만"
        ),
    )
    gui_integration: str = Field(
        description=(
            "### 3. GUI 통합 본문. 알림 위젯 + 사용자 동의 다이얼로그 흐름. "
            "섹션 헤더 없이 본문만"
        ),
    )
    security_checklist: str = Field(
        description=(
            "### 4. 보안 체크리스트 본문. https only / verify=False 금지 / endpoint "
            "override 금지 / sha256 비교 / 자동 다운로드 금지 / Authenticode 검증. "
            "섹션 헤더 없이 본문만"
        ),
    )
    author_notes: str = Field(
        description=(
            "### 5. 작성자 노트 본문. endpoint 근거 + 코드 서명 미보유 한계 + "
            "Distribution Agent 신호. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 모듈 설계\n\n{_strip_leading_section_header(self.module_design)}\n\n"
            f"### 2. updater.py 참조 구현\n\n{_strip_leading_section_header(self.updater_py_reference)}\n\n"
            f"### 3. GUI 통합\n\n{_strip_leading_section_header(self.gui_integration)}\n\n"
            f"### 4. 보안 체크리스트\n\n{_strip_leading_section_header(self.security_checklist)}\n\n"
            f"### 5. 작성자 노트\n\n{_strip_leading_section_header(self.author_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Release — Distribution Agent (5단: 채널 / 명령 / release notes / endpoint / 노트)
# ══════════════════════════════════════════════════════════════════════════


class DistributionSpecOutput(BaseModel):
    """Distribution Agent — 배포 채널 + 업로드 명령 + release notes."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'channel=<X>, url_template=<도메인>, signed=<yes|no>, "
            "sha256_in_manifest=yes'"
        ),
    )
    channel_choice: str = Field(
        description=(
            "### 1. 채널 선택 본문. github_releases / S3 / direct 중 + 근거. "
            "섹션 헤더 없이 본문만"
        ),
    )
    upload_commands: str = Field(
        description=(
            "### 2. 업로드 명령 시퀀스 본문. ```bash``` 안에 정확한 gh release create "
            "또는 aws s3 cp 명령. 섹션 헤더 없이 본문만"
        ),
    )
    release_notes: str = Field(
        description=(
            "### 3. release notes 본문. 사용자 시점 다운로드 안내 + 이전 버전 링크 + "
            "(미서명 시) SmartScreen 안내. 섹션 헤더 없이 본문만"
        ),
    )
    update_endpoint_recommendation: str = Field(
        description=(
            "### 4. Update Checker endpoint 권고 본문. 화이트리스트에 등록할 단일 URL "
            "(예: https://api.github.com/.../releases/latest). 섹션 헤더 없이 본문만"
        ),
    )
    distribution_notes: str = Field(
        description=(
            "### 5. 배포 노트 본문. 채널 트레이드오프 + 사용자 가이드 강조 포인트 + "
            "다음 버전 자동화 항목. 섹션 헤더 없이 본문만"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"### 1. 채널 선택\n\n{_strip_leading_section_header(self.channel_choice)}\n\n"
            f"### 2. 업로드 명령 시퀀스\n\n{_strip_leading_section_header(self.upload_commands)}\n\n"
            f"### 3. release notes\n\n{_strip_leading_section_header(self.release_notes)}\n\n"
            f"### 4. Update Checker endpoint 권고\n\n{_strip_leading_section_header(self.update_endpoint_recommendation)}\n\n"
            f"### 5. 배포 노트\n\n{_strip_leading_section_header(self.distribution_notes)}\n"
        )


# ══════════════════════════════════════════════════════════════════════════
# Pytest Author — 테스트 스위트 3단 (전략 + 코드 블록 + 의도/한계) [PR #59]
# ══════════════════════════════════════════════════════════════════════════
#
# 배경: PR #58 (10차 E2E 7차) 에서 Pytest Author 가 backstory 의 "Final Answer
# 다음 본문" 출력 규약을 무시하고 한 줄 요약만 출력 (30바이트, ```python```
# 블록 0개) → test_*.py 추출 실패 → code_qa SKIPPED 정체.
#
# PR #59 처방 — 방어선 2 (output_pydantic schema 강제):
#   CrewAI 가 LLM 에게 schema 를 강제 → 모든 필드 채워야 task 완료. 누락 시
#   ConverterError / ValidationError 가 PR #55 capture-before-rescue 로 흡수.
#   동시에 backstory + description 강화 (PR #59 옵션 A) 로 LLM 행동 안정화.


class PytestSuiteOutput(BaseModel):
    """Pytest Author — 산출 코드의 테스트 스위트 3단 구조."""

    summary: str = Field(
        description=(
            "한 줄 요약. 형식: 'test_<entry>.py N scenarios' (예: "
            "'test_calculator.py 8 scenarios')"
        ),
    )
    test_strategy: str = Field(
        description=(
            "### 1. 테스트 전략 본문. entry 파일명 + 검증 패턴 (module-level "
            "함수 직접 호출 / GUI 클래스 monkeypatch / 부분 검증) + 시나리오 "
            "수. 섹션 헤더 없이 본문만 (수치·근거 포함, 최소 100자)"
        ),
    )
    test_code_block: str = Field(
        description=(
            "### 2. 실 테스트 코드 본문. **반드시 ```python ... ``` 코드 블록** "
            "을 1개 이상 포함하고, 첫 줄에 `# file: test_<entry>.py` 헤더 주석. "
            "절대 규칙 5개 모두 준수: pytest standalone / GUI 윈도우 미표시 "
            "(monkeypatch __init__/mainloop) / sys.path.insert / 결정론적 "
            "assertion (예상값 박아넣음) / 최소 5개 시나리오 (happy + edge + "
            "error). 섹션 헤더 없이 본문만 (코드 분량 최소 30줄)"
        ),
    )
    intent_and_limits: str = Field(
        description=(
            "### 3. 검증 의도 + 한계 본문. 시나리오별 검증 의도 1줄씩 + 검증 "
            "못한 부분 (분량 / GUI event loop / 외부 의존 등). 섹션 헤더 없이 "
            "본문만 (최소 80자)"
        ),
    )

    def to_markdown(self) -> str:
        return (
            f"{self.summary}\n\n"
            f"## 테스트 스위트\n\n"
            f"### 1. 테스트 전략\n\n{_strip_leading_section_header(self.test_strategy)}\n\n"
            f"### 2. 실 테스트 코드\n\n{_strip_leading_section_header(self.test_code_block)}\n\n"
            f"### 3. 검증 의도 + 한계\n\n{_strip_leading_section_header(self.intent_and_limits)}\n"
        )
