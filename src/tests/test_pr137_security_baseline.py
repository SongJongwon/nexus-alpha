# -*- coding: utf-8 -*-
"""PR #137 — Security baseline 자동화 + BFG 절차 회귀 차단.

배경 (2026-05-14 종합 점검):
    PUBLIC repo 인데 보안 자동화 0:
    - gitleaks 없음 → PR #103 의 LangFuse key 같은 leak 이 history 잔존 + 신규
      leak 즉시 차단 못함
    - dependabot 없음 → vulnerable dep 알림 0
    - CodeQL 없음 → hardcoded credentials / unsafe code patterns 정적 검출 0

PR #137 처방 (자동화만, BFG 실 실행은 별도):
    1. .github/workflows/gitleaks.yml — 전체 history 스캔 + push/PR/weekly
    2. .github/dependabot.yml — pip + github-actions weekly
    3. .github/workflows/codeql.yml — python security-extended
    4. docs/security/bfg_rotation_procedure.md — BFG 절차 문서화 (실 실행 별도)

회귀 차단: 본 테스트가 깨지면 보안 자동화 disabled — leak/취약점 검출 무력화.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GITHUB_DIR = PROJECT_ROOT / ".github"
WORKFLOWS_DIR = GITHUB_DIR / "workflows"
DOCS_SECURITY = PROJECT_ROOT / "docs" / "security"


# ---------------------------------------------------------------------------
# 1. gitleaks workflow
# ---------------------------------------------------------------------------


def test_gitleaks_workflow_exists() -> None:
    """``.github/workflows/gitleaks.yml`` 존재."""
    path = WORKFLOWS_DIR / "gitleaks.yml"
    assert path.exists(), f"gitleaks workflow 파일 누락: {path}"


def test_gitleaks_workflow_is_valid_yaml() -> None:
    """gitleaks.yml 파싱 가능 + 핵심 키 보유."""
    path = WORKFLOWS_DIR / "gitleaks.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "gitleaks"
    assert "jobs" in data
    assert "scan" in data["jobs"]


def test_gitleaks_triggers_on_push_pr_and_schedule() -> None:
    """3 트리거 모두 — push / PR (즉시) + schedule (주간 보강)."""
    path = WORKFLOWS_DIR / "gitleaks.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML 가 ``on:`` 을 Python ``True`` 로 파싱하는 회피 (YAML 1.1 spec).
    triggers = data.get(True) or data.get("on")
    assert triggers is not None, "트리거 정의 누락"
    assert "push" in triggers, "push 트리거 누락"
    assert "pull_request" in triggers, "pull_request 트리거 누락"
    assert "schedule" in triggers, (
        "schedule 누락 — 누락 보강 weekly cron 없으면 force-push bypass 위험"
    )


def test_gitleaks_uses_full_history_fetch() -> None:
    """``fetch-depth: 0`` (전체 history) — shallow clone 면 과거 leak 검출 불가."""
    path = WORKFLOWS_DIR / "gitleaks.yml"
    text = path.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text, (
        "fetch-depth: 0 누락 — shallow clone 으로는 PR #103 같은 history leak 검출 불가"
    )


def test_gitleaks_uses_official_action() -> None:
    """공식 ``gitleaks/gitleaks-action`` 사용 (잠재적 supply-chain 회피)."""
    path = WORKFLOWS_DIR / "gitleaks.yml"
    text = path.read_text(encoding="utf-8")
    assert "gitleaks/gitleaks-action@v" in text, (
        "공식 gitleaks-action 미사용 — supply-chain 위험 + 기능 누락 가능"
    )


# ---------------------------------------------------------------------------
# 2. dependabot.yml
# ---------------------------------------------------------------------------


def test_dependabot_config_exists() -> None:
    """``.github/dependabot.yml`` 존재."""
    path = GITHUB_DIR / "dependabot.yml"
    assert path.exists(), f"dependabot config 누락: {path}"


def test_dependabot_config_is_valid() -> None:
    """dependabot.yml 파싱 가능 + version 2 + updates 배열."""
    path = GITHUB_DIR / "dependabot.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["version"] == 2, "dependabot version 2 명시 필수"
    assert isinstance(data["updates"], list), "updates 배열 필수"


def test_dependabot_covers_pip_and_actions() -> None:
    """pip (requirements.txt) + github-actions 둘 다 커버."""
    path = GITHUB_DIR / "dependabot.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    ecosystems = {u["package-ecosystem"] for u in data["updates"]}
    assert "pip" in ecosystems, (
        "pip ecosystem 누락 — requirements.txt 의 vulnerable dep 알림 0"
    )
    assert "github-actions" in ecosystems, (
        "github-actions ecosystem 누락 — outdated action (잠재 취약점) 알림 0"
    )


def test_dependabot_has_pr_limit() -> None:
    """``open-pull-requests-limit`` 설정 — PR 폭주 방지."""
    path = GITHUB_DIR / "dependabot.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for update in data["updates"]:
        assert "open-pull-requests-limit" in update, (
            f"{update['package-ecosystem']} 의 PR 한도 누락 — PR 폭주 위험"
        )


# ---------------------------------------------------------------------------
# 3. CodeQL workflow
# ---------------------------------------------------------------------------


def test_codeql_workflow_exists() -> None:
    """``.github/workflows/codeql.yml`` 존재."""
    path = WORKFLOWS_DIR / "codeql.yml"
    assert path.exists(), f"CodeQL workflow 누락: {path}"


def test_codeql_workflow_is_valid_yaml() -> None:
    """codeql.yml 파싱 가능 + analyze job."""
    path = WORKFLOWS_DIR / "codeql.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "CodeQL"
    assert "analyze" in data["jobs"]


def test_codeql_targets_python() -> None:
    """python 언어 분석 명시 — Nexus Alpha 의 주 언어."""
    path = WORKFLOWS_DIR / "codeql.yml"
    text = path.read_text(encoding="utf-8")
    assert "python" in text, "python 언어 분석 누락"


def test_codeql_uses_security_extended_queries() -> None:
    """``security-extended`` 쿼리 세트 — default 보다 더 많은 잠재 취약점 검출."""
    path = WORKFLOWS_DIR / "codeql.yml"
    text = path.read_text(encoding="utf-8")
    assert "security-extended" in text, (
        "security-extended 쿼리 세트 누락 — default 만으로는 path traversal / "
        "unsafe yaml / weak crypto 등 검출 부족"
    )


def test_codeql_has_security_events_write_permission() -> None:
    """``security-events: write`` 권한 — Security tab 에 alert 게시 필수."""
    path = WORKFLOWS_DIR / "codeql.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    perms = data.get("permissions", {})
    assert perms.get("security-events") == "write", (
        "security-events: write 권한 누락 — alert 게시 불가"
    )


# ---------------------------------------------------------------------------
# 4. BFG 절차 문서
# ---------------------------------------------------------------------------


def test_bfg_procedure_doc_exists() -> None:
    """``docs/security/bfg_rotation_procedure.md`` 존재."""
    path = DOCS_SECURITY / "bfg_rotation_procedure.md"
    assert path.exists(), f"BFG 절차 문서 누락: {path}"


def test_bfg_procedure_documents_target_leak() -> None:
    """BFG 대상 leak 명시 — 실 실행 시 어떤 값을 정리할지 명확."""
    path = DOCS_SECURITY / "bfg_rotation_procedure.md"
    text = path.read_text(encoding="utf-8")
    assert "pk-lf-09fedad5" in text, "BFG 대상 LangFuse key 미명시"
    assert "354ccfb" in text or "잔존 commit" in text, (
        "잔존 commit hash 또는 명시 키워드 누락"
    )


def test_bfg_procedure_documents_force_push_warning() -> None:
    """force-push 위험 경고 명시 — 자동 실행 회피."""
    path = DOCS_SECURITY / "bfg_rotation_procedure.md"
    text = path.read_text(encoding="utf-8")
    assert "force-push" in text or "force --mirror" in text, "force-push 명시 누락"
    assert "사용자 명시 컨펌" in text or "DESTRUCTIVE" in text, (
        "force-push 위험 경고 누락 — 자동 실행 위험"
    )


def test_bfg_procedure_documents_friend_pc_impact() -> None:
    """친구 PC 영향 명시 — install.ps1 PR #107 destructive sync 가 자동 처리."""
    path = DOCS_SECURITY / "bfg_rotation_procedure.md"
    text = path.read_text(encoding="utf-8")
    assert "친구" in text or "베타" in text, "베타 사용자 영향 미명시"
    assert "PR #107" in text or "destructive sync" in text or "git fetch + reset --hard" in text, (
        "destructive sync 자동 처리 메커니즘 미명시 — 친구가 manual reclone 한다고 오해할 위험"
    )
