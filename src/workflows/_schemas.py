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

본 모듈은 시범 적용 대상 2 에이전트 (BuildEngineer, ReleaseManager) 의 스키마
정의 + 모델 → markdown 렌더러. 검증 후 16 에이전트 전체로 확장 검토.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
            f"### 1. 도구 선택\n\n{self.tool_section}\n\n"
            f"### 2. 빌드 명령\n\n{self.command_section}\n\n"
            f"### 3. PyInstaller spec / Nuitka 옵션\n\n{self.spec_section}\n\n"
            f"### 4. 함정\n\n{self.pitfalls}\n\n"
            f"### 5. 빌드 후 검증 체크리스트\n\n{checklist_md}\n\n"
            f"### 6. 빌드 엔지니어 노트\n\n{self.engineer_notes}\n"
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
            f"### 1. 버전 결정 근거\n\n{self.decision_rationale}\n\n"
            f"### 2. RELEASE.md 매니페스트\n\n{self.release_manifest}\n\n"
            f"### 3. 사용자 친화 한국어 요약\n\n{self.user_friendly_summary}\n\n"
            f"### 4. 매니저 노트\n\n{self.manager_notes}\n"
        )
