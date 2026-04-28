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
    - phase4.5/asset-installer (#16): Asset Manager + Installer Creator
    - phase4.5/platform-tester (#17): Platform Tester ← Phase 4.5 5/5 완성
    - phase5/release-changelog (#19): Release Manager + Changelog Generator
    - phase5/update-distribution (본 PR): Update Checker + Distribution Agent
        ← Phase 5 4/4 완성 + 본부 정원 9/9 완성 ✅

사용 예 (Phase 4.5 빌드 5단계 사슬 완성):
    from src.agents.build_release import (
        create_asset_manager_agent,
        create_build_engineer_agent,
        create_dependency_analyzer_agent,
        create_installer_creator_agent,
        create_platform_tester_agent,
        # Platform Tester 결정론 함수 + 결과 직렬화 헬퍼
        PlatformTestResult,
        format_platform_test_result_for_task,
        test_executable_in_sandbox,
    )

    deps = create_dependency_analyzer_agent()       # 1. 의존성 감사
    builder = create_build_engineer_agent()          # 2. 빌드 사양
    assets = create_asset_manager_agent()            # 3. 자원 매니페스트
    installer = create_installer_creator_agent()     # 4. 인스톨러 사양
    tester = create_platform_tester_agent()          # 5. 산출물 smoke 검증
"""

from .asset_manager import (
    ASSET_MANAGER_BACKSTORY,
    ASSET_MANAGER_GOAL,
    ASSET_MANAGER_NAME,
    ASSET_MANAGER_ROLE,
    create_asset_manager_agent,
)
from .build_executor import ExecuteResult, execute_pyinstaller
from .distribution_executor import (
    PublishResult,
    build_sha256_manifest,
    execute_gh_release,
)
from .build_engineer import (
    BUILD_ENGINEER_BACKSTORY,
    BUILD_ENGINEER_GOAL,
    BUILD_ENGINEER_NAME,
    BUILD_ENGINEER_ROLE,
    create_build_engineer_agent,
)
from .changelog_generator import (
    CHANGELOG_GENERATOR_BACKSTORY,
    CHANGELOG_GENERATOR_GOAL,
    CHANGELOG_GENERATOR_NAME,
    CHANGELOG_GENERATOR_ROLE,
    create_changelog_generator_agent,
)
from .dependency_analyzer import (
    DEPENDENCY_ANALYZER_BACKSTORY,
    DEPENDENCY_ANALYZER_GOAL,
    DEPENDENCY_ANALYZER_NAME,
    DEPENDENCY_ANALYZER_ROLE,
    create_dependency_analyzer_agent,
)
from .distribution_agent import (
    DISTRIBUTION_AGENT_BACKSTORY,
    DISTRIBUTION_AGENT_GOAL,
    DISTRIBUTION_AGENT_NAME,
    DISTRIBUTION_AGENT_ROLE,
    create_distribution_agent_agent,
)
from .installer_creator import (
    INSTALLER_CREATOR_BACKSTORY,
    INSTALLER_CREATOR_GOAL,
    INSTALLER_CREATOR_NAME,
    INSTALLER_CREATOR_ROLE,
    create_installer_creator_agent,
)
from .platform_tester import (
    PLATFORM_TESTER_BACKSTORY,
    PLATFORM_TESTER_GOAL,
    PLATFORM_TESTER_NAME,
    PLATFORM_TESTER_ROLE,
    PlatformTestResult,
    create_platform_tester_agent,
    format_platform_test_result_for_task,
    test_executable_in_sandbox,
)
from .release_manager import (
    RELEASE_MANAGER_BACKSTORY,
    RELEASE_MANAGER_GOAL,
    RELEASE_MANAGER_NAME,
    RELEASE_MANAGER_ROLE,
    create_release_manager_agent,
)
from .update_checker import (
    UPDATE_CHECKER_BACKSTORY,
    UPDATE_CHECKER_GOAL,
    UPDATE_CHECKER_NAME,
    UPDATE_CHECKER_ROLE,
    create_update_checker_agent,
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
    "CHANGELOG_GENERATOR_BACKSTORY",
    "CHANGELOG_GENERATOR_GOAL",
    "CHANGELOG_GENERATOR_NAME",
    "CHANGELOG_GENERATOR_ROLE",
    "DEPENDENCY_ANALYZER_BACKSTORY",
    "DEPENDENCY_ANALYZER_GOAL",
    "DEPENDENCY_ANALYZER_NAME",
    "DEPENDENCY_ANALYZER_ROLE",
    "DISTRIBUTION_AGENT_BACKSTORY",
    "DISTRIBUTION_AGENT_GOAL",
    "DISTRIBUTION_AGENT_NAME",
    "DISTRIBUTION_AGENT_ROLE",
    "INSTALLER_CREATOR_BACKSTORY",
    "INSTALLER_CREATOR_GOAL",
    "INSTALLER_CREATOR_NAME",
    "INSTALLER_CREATOR_ROLE",
    "PLATFORM_TESTER_BACKSTORY",
    "PLATFORM_TESTER_GOAL",
    "PLATFORM_TESTER_NAME",
    "PLATFORM_TESTER_ROLE",
    "ExecuteResult",
    "PlatformTestResult",
    "PublishResult",
    "RELEASE_MANAGER_BACKSTORY",
    "RELEASE_MANAGER_GOAL",
    "RELEASE_MANAGER_NAME",
    "RELEASE_MANAGER_ROLE",
    "UPDATE_CHECKER_BACKSTORY",
    "UPDATE_CHECKER_GOAL",
    "UPDATE_CHECKER_NAME",
    "UPDATE_CHECKER_ROLE",
    "create_asset_manager_agent",
    "create_build_engineer_agent",
    "create_changelog_generator_agent",
    "create_dependency_analyzer_agent",
    "create_distribution_agent_agent",
    "create_installer_creator_agent",
    "create_platform_tester_agent",
    "create_release_manager_agent",
    "create_update_checker_agent",
    "build_sha256_manifest",
    "execute_gh_release",
    "execute_pyinstaller",
    "format_platform_test_result_for_task",
    "test_executable_in_sandbox",
]
