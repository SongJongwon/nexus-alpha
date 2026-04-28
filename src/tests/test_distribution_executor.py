# -*- coding: utf-8 -*-
"""src/agents/build_release/distribution_executor.py 회귀 방지 테스트.

PR #39 — GitHub Release 자동 업로드 executor.

실제 ``gh release create`` 호출은 GitHub repo 에 영향 + 인증 의존이라 단위
테스트에선 subprocess + gh CLI 검색을 monkeypatch. 통합 검증은 smoke test 와
9차 E2E 에서.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.agents.build_release.distribution_executor import (
    PublishResult,
    _build_download_urls,
    _extract_release_url,
    _normalize_repo,
    _tail_text,
    build_sha256_manifest,
    execute_gh_release,
)


# ---------------------------------------------------------------------------
# 순수 헬퍼 — _normalize_repo / _extract_release_url / _build_download_urls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_repo, expected",
    [
        ("owner/name", "owner/name"),
        ("https://github.com/owner/name", "owner/name"),
        ("https://github.com/owner/name.git", "owner/name"),
        ("git@github.com:owner/name.git", "owner/name"),
        ("https://github.com/owner/name/tree/main", "owner/name"),
        ("", None),
        ("invalid", None),
        ("just-text-no-slash", None),
    ],
)
def test_normalize_repo_handles_various_formats(input_repo: str, expected) -> None:
    assert _normalize_repo(input_repo) == expected


def test_extract_release_url_finds_in_last_line() -> None:
    stdout = (
        "Creating release\n"
        "Uploading file...\n"
        "https://github.com/owner/repo/releases/tag/v0.2.0\n"
    )
    assert _extract_release_url(stdout) == "https://github.com/owner/repo/releases/tag/v0.2.0"


def test_extract_release_url_returns_none_when_no_url() -> None:
    assert _extract_release_url("no urls here") is None
    assert _extract_release_url("") is None


def test_extract_release_url_handles_url_in_middle() -> None:
    stdout = "https://github.com/owner/repo/releases/tag/v0.1.0\nupload progress...\n"
    # 마지막 줄에 URL 없으면 역순으로 검색 — 가장 최근 줄에서 찾음
    result = _extract_release_url(stdout)
    assert result == "https://github.com/owner/repo/releases/tag/v0.1.0"


def test_build_download_urls_converts_tag_to_download_path() -> None:
    release_url = "https://github.com/owner/repo/releases/tag/v0.2.0"
    files = [Path("Calculator.exe"), Path("Calculator.exe.sha256.txt")]
    urls = _build_download_urls(release_url, files)
    assert urls == [
        "https://github.com/owner/repo/releases/download/v0.2.0/Calculator.exe",
        "https://github.com/owner/repo/releases/download/v0.2.0/Calculator.exe.sha256.txt",
    ]


def test_build_download_urls_returns_empty_for_invalid_url() -> None:
    """release_url 이 표준 패턴 아니면 빈 리스트 (best effort)."""
    urls = _build_download_urls("https://example.com/random", [Path("x.exe")])
    assert urls == []


def test_tail_text_truncates_long() -> None:
    long_text = "x" * 100_000
    result = _tail_text(long_text, limit=1000)
    assert result.startswith("...(truncated 99000 bytes)...")
    assert len(result) < 1500


# ---------------------------------------------------------------------------
# build_sha256_manifest
# ---------------------------------------------------------------------------


def test_build_sha256_manifest_creates_correct_format(tmp_path: Path) -> None:
    exe_path = tmp_path / "Calculator.exe"
    exe_path.write_bytes(b"fake exe content")
    sha = "1d719f025c62b9e6e5042d6338b1a28f3bf14da952d2966248128057c4d2965a"

    manifest = build_sha256_manifest(exe_path, sha)

    assert manifest.exists()
    assert manifest.name == "Calculator.exe.sha256.txt"
    content = manifest.read_text(encoding="utf-8")
    assert content == f"{sha}  Calculator.exe\n"


# ---------------------------------------------------------------------------
# execute_gh_release — graceful failure 경로 (실 호출 X)
# ---------------------------------------------------------------------------


def test_execute_gh_release_returns_failure_when_gh_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh CLI 미설치 → exit_code=-2."""
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: None,
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
    )
    assert result.success is False
    assert result.exit_code == -2
    assert "gh CLI 미설치" in (result.error_message or "")


def test_execute_gh_release_returns_failure_when_auth_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh 미인증 → exit_code=-3."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )

    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (False, "not logged in"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
    )
    assert result.success is False
    assert result.exit_code == -3
    assert "gh 미인증" in (result.error_message or "")


def test_execute_gh_release_returns_failure_for_invalid_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """repo 형식 무효 → exit_code=-4."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    result = execute_gh_release(
        repo="invalid-no-slash",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
    )
    assert result.success is False
    assert result.exit_code == -4
    assert "repo 형식 무효" in (result.error_message or "")


def test_execute_gh_release_returns_failure_when_files_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """업로드 파일 부재 → exit_code=-5."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[tmp_path / "nonexistent.exe"],
    )
    assert result.success is False
    assert result.exit_code == -5
    assert "파일 부재" in (result.error_message or "")


def test_execute_gh_release_handles_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subprocess.TimeoutExpired → exit_code=-1."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh"], timeout=1, output=b"out", stderr=b"err")

    monkeypatch.setattr(subprocess, "run", _timeout)

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
        timeout_sec=1,
    )
    assert result.success is False
    assert result.exit_code == -1
    assert "timeout" in (result.error_message or "").lower()


def test_execute_gh_release_handles_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh exit_code != 0 → success=False."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    class _StubProc:
        returncode = 1
        stdout = ""
        stderr = "release v0.0.1 already exists"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _StubProc())

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.0.1",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
    )
    assert result.success is False
    assert result.exit_code == 1
    assert "non-zero" in (result.error_message or "").lower()
    assert "already exists" in result.stderr


def test_execute_gh_release_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit 0 + URL 추출 성공 → success=True + download_urls 채워짐."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "Calculator.exe"
    exe.write_bytes(b"fake exe")
    manifest = tmp_path / "Calculator.exe.sha256.txt"
    manifest.write_text("abc  Calculator.exe\n")

    class _StubProc:
        returncode = 0
        stdout = "https://github.com/owner/repo/releases/tag/v0.2.0\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _StubProc())

    result = execute_gh_release(
        repo="owner/repo",
        tag="v0.2.0",
        title="Release v0.2.0",
        notes_body="## Added\n- new feature",
        files_to_upload=[exe, manifest],
        draft=True,
    )
    assert result.success is True
    assert result.exit_code == 0
    assert result.tag == "v0.2.0"
    assert result.is_draft is True
    assert result.release_url == "https://github.com/owner/repo/releases/tag/v0.2.0"
    assert len(result.download_urls) == 2
    assert all("releases/download/v0.2.0" in url for url in result.download_urls)
    assert exe in result.files_uploaded
    assert manifest in result.files_uploaded


def test_execute_gh_release_command_includes_required_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명령에 --repo / --title / --notes / --target 등 포함, draft 지정 시 --draft."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    captured: list[str] = []

    def _capture(cmd, **kwargs):
        captured.extend(cmd)

        class _StubProc:
            returncode = 1
            stdout = ""
            stderr = ""

        return _StubProc()

    monkeypatch.setattr(subprocess, "run", _capture)

    execute_gh_release(
        repo="owner/repo",
        tag="v1.2.3",
        title="My Release",
        notes_body="Notes body",
        files_to_upload=[exe],
        draft=True,
        prerelease=True,
    )

    assert "release" in captured
    assert "create" in captured
    assert "v1.2.3" in captured
    assert "--repo" in captured
    assert "owner/repo" in captured
    assert "--title" in captured
    assert "My Release" in captured
    assert "--notes" in captured
    assert "Notes body" in captured
    assert "--draft" in captured
    assert "--prerelease" in captured
    assert "--target" in captured
    assert "main" in captured  # default target_branch


def test_execute_gh_release_published_when_draft_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """draft=False 면 명령에 --draft 없음 (published)."""
    fake_gh = tmp_path / "fake_gh"
    fake_gh.write_text("")
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._resolve_gh_executable",
        lambda: fake_gh,
    )
    monkeypatch.setattr(
        "src.agents.build_release.distribution_executor._check_gh_auth",
        lambda gh, timeout_sec=10: (True, "ok"),
    )

    exe = tmp_path / "x.exe"
    exe.write_bytes(b"x")

    captured: list[str] = []

    def _capture(cmd, **kwargs):
        captured.extend(cmd)

        class _StubProc:
            returncode = 1
            stdout = ""
            stderr = ""

        return _StubProc()

    monkeypatch.setattr(subprocess, "run", _capture)

    execute_gh_release(
        repo="owner/repo",
        tag="v1.0.0",
        title="Test",
        notes_body="notes",
        files_to_upload=[exe],
        draft=False,
    )

    assert "--draft" not in captured


# ---------------------------------------------------------------------------
# PublishResult dataclass
# ---------------------------------------------------------------------------


def test_publish_result_summary_for_success_draft() -> None:
    result = PublishResult(
        success=True,
        exit_code=0,
        elapsed_sec=5.7,
        tag="v0.2.0",
        is_draft=True,
        release_url="https://github.com/owner/repo/releases/tag/v0.2.0",
        files_uploaded=[Path("Calculator.exe"), Path("Calculator.exe.sha256.txt")],
    )
    summary = result.summary_line()
    assert "PUBLISH SUCCESS" in summary
    assert "[DRAFT]" in summary
    assert "v0.2.0" in summary
    assert "2 파일" in summary


def test_publish_result_summary_for_failure() -> None:
    result = PublishResult(
        success=False,
        exit_code=-3,
        elapsed_sec=0.5,
        tag="v0.0.1",
        is_draft=True,
        error_message="gh 미인증",
    )
    summary = result.summary_line()
    assert "PUBLISH FAILED" in summary
    assert "v0.0.1" in summary
    assert "exit=-3" in summary
    assert "gh 미인증" in summary


def test_publish_result_default_factories_isolated() -> None:
    """download_urls / files_uploaded / command 가 매번 새 list (mutable default 회귀)."""
    a = PublishResult(success=False, exit_code=-1, elapsed_sec=0.0)
    b = PublishResult(success=False, exit_code=-1, elapsed_sec=0.0)
    a.download_urls.append("test")
    a.files_uploaded.append(Path("test"))
    a.command.append("test")
    assert b.download_urls == []
    assert b.files_uploaded == []
    assert b.command == []
