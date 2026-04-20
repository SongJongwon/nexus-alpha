# -*- coding: utf-8 -*-
"""
Nexus Alpha 릴리스 워크플로우 (Phase 5 통합 — v4 종착지).

`run_release_workflow(...)` — 빌드 & 배포 본부 후반 4명 사슬을 한 번에 호출하는
공개 진입점. Phase 4.5 산출물(빌드 사양 + 인스톨러 사양 + Platform Tester 보고)
을 입력으로 받아 SemVer 결정·CHANGELOG·자동 업데이트 모듈·배포 사양을 순차
산출.

4단계 사슬 (org_v4 §3-8 — 빌드 & 배포 본부 Phase 5):
    1. Release Manager     → SemVer 결정 + RELEASE.md 초안
    2. Changelog Generator → Keep a Changelog 형식 항목
    3. Update Checker      → 자동 업데이트 모듈 사양 + 참조 구현
    4. Distribution Agent  → 배포 채널 + 업로드 명령 + 다운로드 URL 패턴

⚠️ MVP 한계 (모든 호출 측에 명시):
    - 본 워크플로우는 *사양만* 산출. 실제 Git 태그 생성·gh release create 호출·
      파일 업로드·SHA256 산출은 외부 자동화 스크립트 또는 CI 가 본 사양 보고
      수행해야 함. v5 또는 별도 후속 작업.
    - Update Checker 가 만든 `updater.py` 는 *참조 구현* — 실제 앱에 통합하려면
      Engineer 가 산출 코드에 본 모듈을 추가하는 별도 단계 필요.

호출 측 사용 예:
    from src.workflows import run_release_workflow

    release_result = run_release_workflow(
        previous_version="0.2.0",
        change_summary="...",
        target_platform="windows",
        repo_url="https://github.com/owner/repo",
        signing_available=False,
        privacy_level="public",
        workflow_dir=Path("outputs/workflow_..."),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from crewai import Crew, Process, Task

from src.agents.build_release import (
    create_changelog_generator_agent,
    create_distribution_agent_agent,
    create_release_manager_agent,
    create_update_checker_agent,
)
from src.monitoring import get_langfuse_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 결과 dataclass
# ---------------------------------------------------------------------------
@dataclass
class ReleaseWorkflowResult:
    """`run_release_workflow` 의 최종 산출물.

    Attributes:
        release_decision: Release Manager 산출 (4단 — 버전 결정 + RELEASE.md +
            사용자 친화 요약 + 매니저 노트).
        changelog_entry: Changelog Generator 산출 (Keep a Changelog 형식 + 작성자 노트).
        update_module_spec: Update Checker 산출 (5단 — 흐름 + updater.py 구현 +
            통합 위치 + 보안 체크리스트 + 노트).
        distribution_spec: Distribution Agent 산출 (5단 — 채널 선택 + 업로드 명령
            + 다운로드 URL+SHA256 + Update Checker endpoint 권고 + 배포 노트).
        saved_files: 산출 파일들 (30_~33_ prefix). workflow_dir 가 None 이면 빈 리스트.
        previous_version: 입력 echo (참고용).
        target_platform: 입력 echo.
    """

    release_decision: str
    changelog_entry: str
    update_module_spec: str
    distribution_spec: str
    saved_files: list[Path] = field(default_factory=list)
    previous_version: str = ""
    target_platform: str = "windows"


# ---------------------------------------------------------------------------
# Task 빌더 (4명 각자, 컨텍스트 chain)
# ---------------------------------------------------------------------------
def _build_release_manager_task(
    agent,
    previous_version: str,
    change_summary: str,
    breaking_flags: str,
    build_summary: str,
    target_platform: str,
) -> Task:
    return Task(
        description=(
            "아래 5블록을 입력으로, 백스토리에 명시된 4단 구조(버전 결정 / RELEASE.md "
            "초안 / 사용자 친화 요약 / 매니저 노트)로 한국어 릴리스 결정을 작성하세요.\n\n"
            f"[PREVIOUS_VERSION]\n{previous_version or 'none (첫 릴리스)'}\n\n"
            f"[CHANGE_SUMMARY]\n{change_summary or '(없음 — 호출 측이 변경 요약 미제공)'}\n\n"
            f"[BREAKING_FLAGS]\n{breaking_flags or 'none'}\n\n"
            f"[BUILD_RESULT]\n{build_summary or '(없음 — Phase 4.5 build_workflow 미실행)'}\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n"
        ),
        expected_output=(
            "4단 한국어 릴리스 결정. 마지막 줄 `Final Answer: version=X.Y.Z, "
            "bump=<major|minor|patch|prerelease>, tag=vX.Y.Z`."
        ),
        agent=agent,
    )


def _build_changelog_task(
    agent, change_sources: str, breaking_flags: str, previous_changelog: str, release_task: Task
) -> Task:
    return Task(
        description=(
            "이전 컨텍스트의 Release Manager 결정 + 아래 3블록을 입력으로, "
            "백스토리에 명시된 2단 구조(Keep a Changelog 형식 항목 + 작성자 노트)로 "
            "한국어 CHANGELOG 항목을 작성하세요. 빈 카테고리는 헤더째 생략, "
            "카테고리 키워드는 영문 표준 유지.\n\n"
            f"[CHANGE_SOURCES]\n{change_sources}\n\n"
            f"[BREAKING_FLAGS]\n{breaking_flags or 'none'}\n\n"
            f"[PREVIOUS_CHANGELOG]\n{previous_changelog or '(없음 — 첫 릴리스)'}\n"
        ),
        expected_output=(
            "Keep a Changelog 형식 항목 + 작성자 노트. 마지막 줄 `Final Answer: "
            "version=X.Y.Z, entries=N개, breaking=B개, categories=<쉼표 구분>`."
        ),
        agent=agent,
        context=[release_task],
    )


def _build_update_checker_task(
    agent,
    app_short_name: str,
    update_endpoint: str,
    target_platform: str,
    signing_available: bool,
    release_task: Task,
) -> Task:
    return Task(
        description=(
            "이전 컨텍스트의 Release Manager 결정 + 아래 4블록을 입력으로, 백스토리에 "
            "명시된 5단 구조(동작 흐름 / 참조 구현 updater.py / 통합 위치 / 보안 "
            "체크리스트 / 작성자 노트)로 한국어 자동 업데이트 모듈 사양을 작성하세요. "
            "**보안 5원칙 (HTTPS / TLS 검증 / 화이트리스트 / SHA256 검증 / 자동 적용 "
            "금지) 모두 준수해야 합니다.**\n\n"
            f"[APP_METADATA]\n"
            f"short_name: {app_short_name}\n"
            f"current_version: (Release Manager 결정 사용)\n\n"
            f"[UPDATE_ENDPOINT]\n{update_endpoint}\n\n"
            f"[TARGET_PLATFORM]\n{target_platform}\n\n"
            f"[SIGNING_AVAILABLE]\n{'yes' if signing_available else 'no'}\n"
        ),
        expected_output=(
            "5단 한국어 자동 업데이트 모듈 사양. 마지막 줄 `Final Answer: updater "
            "module — endpoint=<도메인>, sha256_check=yes, signing_check=<yes|no>, "
            "check_interval=24h`."
        ),
        agent=agent,
        context=[release_task],
    )


def _build_distribution_task(
    agent,
    artifact_summary: str,
    repo_url: str,
    signing_available: bool,
    privacy_level: str,
    release_task: Task,
    update_task: Task,
) -> Task:
    return Task(
        description=(
            "이전 컨텍스트의 Release Manager 결정 + Update Checker endpoint 요구 + "
            "아래 4블록을 입력으로, 백스토리에 명시된 5단 구조(채널 선택 / 업로드 "
            "명령 / 다운로드 URL+SHA256 / Update Checker endpoint 권고 / 배포 노트)로 "
            "한국어 배포 사양을 작성하세요. **GitHub Releases 1순위 권장**, 다운로드 "
            "URL + SHA256 manifest 동봉 필수.\n\n"
            f"[BUILD_ARTIFACT]\n{artifact_summary}\n\n"
            f"[REPO_URL]\n{repo_url or 'none'}\n\n"
            f"[SIGNING_AVAILABLE]\n{'yes' if signing_available else 'no'}\n\n"
            f"[PRIVACY_LEVEL]\n{privacy_level}\n"
        ),
        expected_output=(
            "5단 한국어 배포 사양. 마지막 줄 `Final Answer: channel=<X>, "
            "url_template=<도메인>, signed=<yes|no>, sha256_in_manifest=yes`."
        ),
        agent=agent,
        context=[release_task, update_task],
    )


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _task_output_text(task: Task) -> str:
    out = task.output
    if out is None:
        return ""
    return getattr(out, "raw", None) or str(out)


def _detect_default_endpoint(repo_url: str) -> str:
    """repo_url 에서 GitHub Releases endpoint 자동 추출 (있으면).

    repo_url 이 GitHub URL 이면 https://api.github.com/repos/<owner>/<repo>/releases/latest.
    그 외엔 'TBD — Distribution Agent 결정 후 채움' placeholder 반환.
    """
    if not repo_url:
        return "TBD — Distribution Agent 결정 후 채움"
    url = repo_url.rstrip("/")
    if "github.com/" in url:
        # https://github.com/<owner>/<repo>
        path = url.split("github.com/", 1)[-1]
        return f"https://api.github.com/repos/{path}/releases/latest"
    return f"{url}/releases/latest  # placeholder — 채널별 커스터마이징 필요"


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def run_release_workflow(
    *,
    previous_version: str = "",
    change_summary: str = "",
    change_sources: str = "",
    breaking_flags: str = "",
    previous_changelog: str = "",
    build_summary: str = "",
    artifact_summary: str = "",
    target_platform: str = "windows",
    repo_url: str = "",
    app_short_name: str = "NexusApp",
    signing_available: bool = False,
    privacy_level: str = "public",
    workflow_dir: Optional[Path] = None,
    verbose: bool = False,
) -> ReleaseWorkflowResult:
    """4-agent 릴리스 사슬을 한 번에 실행. Phase 4.5 산출물 직후 호출 가정.

    Args:
        previous_version: 이전 릴리스 버전 ("0.2.0" 등). 빈 문자열이면 첫 릴리스.
        change_summary: Release Manager 입력 — 사용자 가시 변화 요약.
        change_sources: Changelog Generator 입력 — iteration history / git commits /
            build summary 등 자유 형식. 빈 문자열이면 change_summary 대체 사용.
        breaking_flags: 호환성 깨짐 명시 신호 (있으면 Release Manager 가 major bump).
        previous_changelog: 직전 CHANGELOG.md (Changelog Generator 톤 일관성 참고).
        build_summary: Phase 4.5 BuildWorkflowResult 요약 (Release Manager 입력).
        artifact_summary: Distribution Agent 입력 — 파일명/크기/플랫폼.
        target_platform: windows | macos | linux.
        repo_url: GitHub repo URL — 자동 endpoint 추출에 사용.
        app_short_name: Update Checker 의 ~/.<short_name>/ 경로용.
        signing_available: 코드 서명 EV 인증서 보유 여부.
        privacy_level: public | corporate-internal | one-time-share.
        workflow_dir: 산출 파일 저장 디렉터리. None 이면 디스크 저장 skip.
        verbose: CrewAI 중간 로그.

    Returns:
        ReleaseWorkflowResult — 4 에이전트 산출 + 저장 경로.

    Note:
        본 워크플로우는 LLM 호출 4건 (Release/Changelog/Update/Distribution).
        실제 Git 태그·gh release·SHA256 산출은 외부 자동화에 위임.
    """
    monitor = get_langfuse_client()
    monitor.log_trace(
        name="release_workflow",
        user_id="local-dev",
        metadata={
            "phase": "phase_5_workflow",
            "workflow": "release_workflow",
            "previous_version": previous_version or "none",
            "target_platform": target_platform,
            "signing_available": signing_available,
            "privacy_level": privacy_level,
        },
    )

    try:
        # change_sources 가 비어 있으면 change_summary 를 fallback 으로
        effective_sources = change_sources or change_summary or "(없음)"
        update_endpoint = _detect_default_endpoint(repo_url)

        # 4-agent sequential
        release_agent = create_release_manager_agent(verbose=verbose)
        changelog_agent = create_changelog_generator_agent(verbose=verbose)
        update_agent = create_update_checker_agent(verbose=verbose)
        distribution_agent = create_distribution_agent_agent(verbose=verbose)

        release_task = _build_release_manager_task(
            release_agent,
            previous_version=previous_version,
            change_summary=change_summary,
            breaking_flags=breaking_flags,
            build_summary=build_summary,
            target_platform=target_platform,
        )
        changelog_task = _build_changelog_task(
            changelog_agent,
            change_sources=effective_sources,
            breaking_flags=breaking_flags,
            previous_changelog=previous_changelog,
            release_task=release_task,
        )
        update_task = _build_update_checker_task(
            update_agent,
            app_short_name=app_short_name,
            update_endpoint=update_endpoint,
            target_platform=target_platform,
            signing_available=signing_available,
            release_task=release_task,
        )
        distribution_task = _build_distribution_task(
            distribution_agent,
            artifact_summary=artifact_summary or f"(없음 — {target_platform} 빌드 산출물 미명시)",
            repo_url=repo_url,
            signing_available=signing_available,
            privacy_level=privacy_level,
            release_task=release_task,
            update_task=update_task,
        )

        Crew(
            agents=[release_agent, changelog_agent, update_agent, distribution_agent],
            tasks=[release_task, changelog_task, update_task, distribution_task],
            process=Process.sequential,
            verbose=verbose,
        ).kickoff()

        release_decision = _task_output_text(release_task)
        changelog_entry = _task_output_text(changelog_task)
        update_module_spec = _task_output_text(update_task)
        distribution_spec = _task_output_text(distribution_task)

        # 산출 파일 저장
        saved: list[Path] = []
        if workflow_dir is not None:
            workflow_dir.mkdir(parents=True, exist_ok=True)
            for name, content in (
                ("30_release_decision.md", release_decision),
                ("31_changelog_entry.md", changelog_entry),
                ("32_update_module_spec.md", update_module_spec),
                ("33_distribution_spec.md", distribution_spec),
            ):
                path = workflow_dir / name
                path.write_text(content, encoding="utf-8")
                saved.append(path)

        return ReleaseWorkflowResult(
            release_decision=release_decision,
            changelog_entry=changelog_entry,
            update_module_spec=update_module_spec,
            distribution_spec=distribution_spec,
            saved_files=saved,
            previous_version=previous_version,
            target_platform=target_platform,
        )

    finally:
        monitor.end_trace()
        monitor.flush()
