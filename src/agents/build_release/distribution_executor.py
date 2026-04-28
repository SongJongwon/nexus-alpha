# -*- coding: utf-8 -*-
"""GitHub Release 자동 업로드 executor (Phase 5 강화 — PR #39).

Distribution Agent 의 사양 (DistributionSpec) + build_executor 의 산출 (.exe + SHA256)
→ 실제 ``gh release create`` subprocess 호출 → GitHub Release 생성 → 다운로드 URL.
v6 doc DoD 의 M5 (다운로드 가능 setup.exe URL) 마일스톤 완성.

설계 원칙:
  - **subprocess 호출만 담당** — Distribution Agent 의 LLM 산출 markdown 을 직접
    파싱하지 않음. 입력은 *구조화된 인자* (repo / tag / title / notes_body /
    files_to_upload).
  - **default draft=True** — 안전 default. 실수로 public publish 방지.
    명시적으로 ``draft=False`` 줘야 published.
  - **graceful failure** — 실패 시 PublishResult.success=False, 예외 propagate 안 함.
  - **gh CLI 의존** — 미설치 또는 미인증 시 명확한 에러 메시지.

호출 측 (release_workflow.py) 통합 패턴::

    if enable_publish and executor_result and executor_result.success:
        manifest_path = build_sha256_manifest(
            executor_result.exe_path, executor_result.sha256
        )
        publish_result = execute_gh_release(
            repo=repo_url,
            tag=parsed_tag_from_release_decision,
            title=parsed_title,
            notes_body=changelog_entry_markdown,
            files_to_upload=[executor_result.exe_path, manifest_path],
            draft=publish_as_draft,
        )
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_DEFAULT_TIMEOUT_SEC = 120  # 2분 — 일반 .exe 업로드 충분
_OUTPUT_TAIL_BYTES = 50_000


# ---------------------------------------------------------------------------
# 결과 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class PublishResult:
    """``gh release create`` 실행 결과 — graceful failure 모델."""

    success: bool
    """성공 여부 — gh exit_code == 0 AND release URL 추출 성공."""

    exit_code: int
    """subprocess 종료 코드. -1=timeout, -2=gh 미설치, -3=인증 실패, -4=repo 무효."""

    elapsed_sec: float
    """소요 시간 (실측)."""

    tag: str = ""
    """release tag (예: 'v0.2.0')."""

    is_draft: bool = True
    """draft 여부. True 면 public 노출 안 됨."""

    release_url: Optional[str] = None
    """release 페이지 URL — 실패 시 None."""

    download_urls: list[str] = field(default_factory=list)
    """업로드된 파일별 다운로드 URL (best effort 추정)."""

    files_uploaded: list[Path] = field(default_factory=list)
    """실제 업로드된 파일 경로."""

    command: list[str] = field(default_factory=list)
    """실행한 명령 (debug/재현용)."""

    stdout: str = ""
    """gh stdout (마지막 50KB)."""

    stderr: str = ""
    """gh stderr (마지막 50KB)."""

    error_message: Optional[str] = None
    """failure 시 사람이 읽을 수 있는 진단 메시지."""

    def summary_line(self) -> str:
        if self.success:
            draft_marker = " [DRAFT]" if self.is_draft else ""
            return (
                f"[PUBLISH SUCCESS]{draft_marker} {self.tag} → {self.release_url} "
                f"({len(self.files_uploaded)} 파일 업로드, {self.elapsed_sec:.1f}s)"
            )
        return (
            f"[PUBLISH FAILED] tag={self.tag}, exit={self.exit_code}, "
            f"error={self.error_message or 'unknown'}, elapsed={self.elapsed_sec:.1f}s"
        )


# ---------------------------------------------------------------------------
# 유틸 — repo 정규화 / SHA256 manifest / output 파싱
# ---------------------------------------------------------------------------


def _normalize_repo(repo_or_url: str) -> Optional[str]:
    """다양한 입력에서 'owner/name' 형태 정규화.

    수용:
        'owner/name'                          → 'owner/name'
        'https://github.com/owner/name'       → 'owner/name'
        'https://github.com/owner/name.git'   → 'owner/name'
        'git@github.com:owner/name.git'       → 'owner/name'
    """
    if not repo_or_url:
        return None
    text = repo_or_url.strip()
    # github.com URL 패턴
    m = re.search(r"github\.com[/:]([^/\s]+/[^/\s.]+)", text)
    if m:
        return m.group(1)
    # 단순 owner/name
    if re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", text):
        return text
    return None


def build_sha256_manifest(exe_path: Path, sha256: str) -> Path:
    """sha256sum 형식 manifest 파일을 .exe 옆에 생성.

    형식: ``<sha256>  <filename>\\n`` (sha256sum / shasum -a 256 호환).

    Returns:
        생성된 manifest 파일 경로 (예: ``Calculator.exe.sha256.txt``).
    """
    manifest_path = exe_path.with_suffix(exe_path.suffix + ".sha256.txt")
    manifest_path.write_text(f"{sha256}  {exe_path.name}\n", encoding="utf-8")
    return manifest_path


def _tail_text(text: str, limit: int = _OUTPUT_TAIL_BYTES) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"...(truncated {len(text) - limit} bytes)...\n" + text[-limit:]


def _extract_release_url(stdout: str) -> Optional[str]:
    """gh release create 의 stdout 에서 release URL 추출.

    gh 는 보통 마지막 줄에 ``https://github.com/owner/repo/releases/tag/vX.Y.Z`` 출력.
    """
    if not stdout:
        return None
    # 모든 줄에서 URL 패턴 검색 (역순 우선)
    for line in reversed(stdout.strip().splitlines()):
        m = re.search(r"https://github\.com/[^\s]+/releases/(?:tag/)?[^\s]+", line.strip())
        if m:
            return m.group(0)
    return None


def _build_download_urls(release_url: str, files: list[Path]) -> list[str]:
    """release URL + 파일 목록 → 다운로드 URL 추정.

    GitHub Release 다운로드 URL 패턴:
        https://github.com/owner/repo/releases/download/<tag>/<filename>

    release_url 이 ``/releases/tag/v0.2.0`` 형태이면 ``/releases/download/v0.2.0/`` 로 변환.
    """
    if "/releases/tag/" in release_url:
        base = release_url.replace("/releases/tag/", "/releases/download/")
    else:
        # fallback — 그대로 사용 (download URL 못 만들면 빈 리스트)
        return []
    return [f"{base.rstrip('/')}/{f.name}" for f in files]


# ---------------------------------------------------------------------------
# gh CLI 검증
# ---------------------------------------------------------------------------


def _resolve_gh_executable() -> Optional[Path]:
    """gh CLI 실행 파일 위치 탐색."""
    found = shutil.which("gh")
    return Path(found) if found else None


def _check_gh_auth(gh_exe: Path, timeout_sec: int = 10) -> tuple[bool, str]:
    """gh auth status 확인. Returns (is_authenticated, message)."""
    try:
        proc = subprocess.run(
            [str(gh_exe), "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"gh auth status 확인 실패: {e}"
    if proc.returncode != 0:
        return False, _tail_text(proc.stderr or proc.stdout, limit=2000)
    return True, "ok"


# ---------------------------------------------------------------------------
# GitHub Release 실행자
# ---------------------------------------------------------------------------


def execute_gh_release(
    repo: str,
    tag: str,
    title: str,
    notes_body: str,
    files_to_upload: list[Path],
    draft: bool = True,
    prerelease: bool = False,
    target_branch: str = "main",
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    extra_args: Optional[list[str]] = None,
) -> PublishResult:
    """``gh release create`` 호출로 GitHub Release 생성 + 파일 업로드.

    Args:
        repo: ``'owner/name'`` 또는 GitHub URL — 자동 정규화.
        tag: Release tag (예: ``'v0.2.0'``).
        title: Release 제목.
        notes_body: Release notes markdown.
        files_to_upload: 업로드할 파일 경로 리스트 (예: ``[exe_path, manifest_path]``).
        draft: True (기본) 면 ``--draft`` (public 노출 안 됨).
        prerelease: True 면 ``--prerelease``.
        target_branch: Release 가 가리킬 branch (기본 ``main``).
        timeout_sec: subprocess 타임아웃 (초). 기본 120 (2분).
        extra_args: gh 추가 raw 인자.

    Returns:
        PublishResult — 성공/실패 + URL + download_urls + 진단.
    """
    started = time.time()

    # 1. gh CLI 검증
    gh_exe = _resolve_gh_executable()
    if gh_exe is None:
        return PublishResult(
            success=False,
            exit_code=-2,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            error_message="gh CLI 미설치 — `winget install GitHub.cli` 필요.",
        )

    # 2. 인증 검증
    is_auth, auth_msg = _check_gh_auth(gh_exe)
    if not is_auth:
        return PublishResult(
            success=False,
            exit_code=-3,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            stderr=auth_msg,
            error_message="gh 미인증 — `gh auth login` 필요.",
        )

    # 3. repo 정규화
    repo_normalized = _normalize_repo(repo)
    if repo_normalized is None:
        return PublishResult(
            success=False,
            exit_code=-4,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            error_message=f"repo 형식 무효: '{repo}'. 'owner/name' 또는 GitHub URL 필요.",
        )

    # 4. 파일 검증
    missing = [str(f) for f in files_to_upload if not f.exists()]
    if missing:
        return PublishResult(
            success=False,
            exit_code=-5,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            error_message=f"업로드 파일 부재: {missing}",
        )

    # 5. 명령 빌드
    cmd: list[str] = [
        str(gh_exe),
        "release", "create", tag,
        "--repo", repo_normalized,
        "--title", title,
        "--notes", notes_body,
        "--target", target_branch,
    ]
    if draft:
        cmd.append("--draft")
    if prerelease:
        cmd.append("--prerelease")
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(str(f) for f in files_to_upload)

    # 6. subprocess 실행
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        exit_code = proc.returncode
        stdout = _tail_text(proc.stdout)
        stderr = _tail_text(proc.stderr)
    except subprocess.TimeoutExpired as e:
        return PublishResult(
            success=False,
            exit_code=-1,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            command=cmd,
            stdout=_tail_text(e.stdout.decode("utf-8", errors="replace") if e.stdout else ""),
            stderr=_tail_text(e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
            error_message=f"gh release create timeout — {timeout_sec}s 초과.",
        )
    except FileNotFoundError as e:
        return PublishResult(
            success=False,
            exit_code=-2,
            elapsed_sec=time.time() - started,
            tag=tag,
            is_draft=draft,
            command=cmd,
            error_message=f"gh 실행 실패 (FileNotFoundError): {e}",
        )

    elapsed = time.time() - started

    # 7. 결과 파싱
    if exit_code != 0:
        return PublishResult(
            success=False,
            exit_code=exit_code,
            elapsed_sec=elapsed,
            tag=tag,
            is_draft=draft,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            error_message=f"gh release create exit_code={exit_code} (non-zero).",
        )

    release_url = _extract_release_url(proc.stdout)
    if release_url is None:
        return PublishResult(
            success=False,
            exit_code=exit_code,
            elapsed_sec=elapsed,
            tag=tag,
            is_draft=draft,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            error_message="gh exit 0 그러나 release URL 추출 실패 (stdout 형식 변경 가능성).",
        )

    download_urls = _build_download_urls(release_url, files_to_upload)

    return PublishResult(
        success=True,
        exit_code=exit_code,
        elapsed_sec=elapsed,
        tag=tag,
        is_draft=draft,
        release_url=release_url,
        download_urls=download_urls,
        files_uploaded=list(files_to_upload),
        command=cmd,
        stdout=stdout,
        stderr=stderr,
    )
