# -*- coding: utf-8 -*-
"""
빌드 & 배포(Build & Release) 에이전트 패키지 (Phase 4.5/5 신설 본부, v4).

`docs/architecture/nexus_alpha_org_v4.md` §3-8 — 9명 정원:
    Phase 4.5 (빌드 & 패키징, 5명):
        - Build Engineer       — PyInstaller/Nuitka/cx_Freeze 선택 + 빌드 사양
        - Dependency Analyzer  — hidden imports / data files / license / OS-specific
        - Asset Manager        — 아이콘·폰트·리소스 수집
        - Installer Creator    — Inno Setup / WiX / pkgbuild / AppImage
        - Platform Tester      — 깨끗한 환경에서 빌드 산출물 자동 실행 검증

    Phase 5 (배포 자동화, 4명):
        - Release Manager
        - Changelog Generator
        - Update Checker
        - Distribution Agent

본 PR (`phase4.5/build-engineer`): Build Engineer + Dependency Analyzer 2명만.
나머지 7명은 후속 PR로 점진 추가.

사용 예:
    from src.agents.build_release import (
        create_build_engineer_agent,
        create_dependency_analyzer_agent,
    )

    analyzer = create_dependency_analyzer_agent()  # 먼저 의존성 감사
    builder = create_build_engineer_agent()         # 그 결과로 빌드 사양 결정
"""

from .build_engineer import (
    BUILD_ENGINEER_BACKSTORY,
    BUILD_ENGINEER_GOAL,
    BUILD_ENGINEER_NAME,
    BUILD_ENGINEER_ROLE,
    create_build_engineer_agent,
)
from .dependency_analyzer import (
    DEPENDENCY_ANALYZER_BACKSTORY,
    DEPENDENCY_ANALYZER_GOAL,
    DEPENDENCY_ANALYZER_NAME,
    DEPENDENCY_ANALYZER_ROLE,
    create_dependency_analyzer_agent,
)

__all__ = [
    "BUILD_ENGINEER_BACKSTORY",
    "BUILD_ENGINEER_GOAL",
    "BUILD_ENGINEER_NAME",
    "BUILD_ENGINEER_ROLE",
    "DEPENDENCY_ANALYZER_BACKSTORY",
    "DEPENDENCY_ANALYZER_GOAL",
    "DEPENDENCY_ANALYZER_NAME",
    "DEPENDENCY_ANALYZER_ROLE",
    "create_build_engineer_agent",
    "create_dependency_analyzer_agent",
]
