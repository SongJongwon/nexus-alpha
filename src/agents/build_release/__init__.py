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

진행 상황:
    - phase4.5/build-engineer (#15): Build Engineer + Dependency Analyzer
    - phase4.5/asset-installer (본 PR): Asset Manager + Installer Creator
    - 후속: Platform Tester (1명) — Phase 4.5 완성

사용 예:
    from src.agents.build_release import (
        create_asset_manager_agent,
        create_build_engineer_agent,
        create_dependency_analyzer_agent,
        create_installer_creator_agent,
    )

    # 빌드 4단계 (Phase 4.5 마지막 1단계 Platform Tester 까지 도달 시):
    deps = create_dependency_analyzer_agent()       # 1. 의존성 감사
    builder = create_build_engineer_agent()          # 2. 빌드 사양
    assets = create_asset_manager_agent()            # 3. 자원 매니페스트
    installer = create_installer_creator_agent()     # 4. 인스톨러 사양
    # tester = create_platform_tester_agent()        # 5. 산출물 검증 (다음 PR)
"""

from .asset_manager import (
    ASSET_MANAGER_BACKSTORY,
    ASSET_MANAGER_GOAL,
    ASSET_MANAGER_NAME,
    ASSET_MANAGER_ROLE,
    create_asset_manager_agent,
)
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
from .installer_creator import (
    INSTALLER_CREATOR_BACKSTORY,
    INSTALLER_CREATOR_GOAL,
    INSTALLER_CREATOR_NAME,
    INSTALLER_CREATOR_ROLE,
    create_installer_creator_agent,
)

__all__ = [
    "ASSET_MANAGER_BACKSTORY",
    "ASSET_MANAGER_GOAL",
    "ASSET_MANAGER_NAME",
    "ASSET_MANAGER_ROLE",
    "BUILD_ENGINEER_BACKSTORY",
    "BUILD_ENGINEER_GOAL",
    "BUILD_ENGINEER_NAME",
    "BUILD_ENGINEER_ROLE",
    "DEPENDENCY_ANALYZER_BACKSTORY",
    "DEPENDENCY_ANALYZER_GOAL",
    "DEPENDENCY_ANALYZER_NAME",
    "DEPENDENCY_ANALYZER_ROLE",
    "INSTALLER_CREATOR_BACKSTORY",
    "INSTALLER_CREATOR_GOAL",
    "INSTALLER_CREATOR_NAME",
    "INSTALLER_CREATOR_ROLE",
    "create_asset_manager_agent",
    "create_build_engineer_agent",
    "create_dependency_analyzer_agent",
    "create_installer_creator_agent",
]
