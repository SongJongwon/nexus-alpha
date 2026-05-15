# -*- coding: utf-8 -*-
"""PR #154 — knowledge_index LRU 회전 정책 회귀 차단.

배경 (PR #153 사후 검증에서 도출):
    ``outputs/knowledge_index/<wid>.yaml`` 무제한 누적 — 100+ 빌드 누적 시 recall
    glob+parse 비용 증가 + disk 사용량 폭증 위험. PR #153 회귀 테스트가 *동작은*
    굳혔지만 *정리 메커니즘 부재*.

PR #154 처방:
    - ``prune_knowledge_index_lru(index_dir, max_entries=N)`` — curated_at 내림차순
      정렬 후 상위 N 유지, 나머지 hard delete
    - 기본 N=50, ``NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES`` env var override
    - ``curate_workflow`` 가 새 entry 작성 직후 호출 — 매 빌드마다 정리
    - 실패 격리: prune 도중 OSError 등은 워크플로 차단 X
    - tie break: 동일 curated_at → workflow_id 알파벳 내림차순 (결정론)

본 테스트 목적:
    1. 기본 N=50 정상 작동 (49개 → no-op, 51개 → 1 삭제, 100개 → 50 삭제)
    2. max_entries 명시 override 우선
    3. env var override (max_entries=None 일 때만)
    4. <= 0 max_entries → 회전 비활성 (no-op)
    5. 디렉터리 부재 / 빈 디렉터리 → no-op (graceful)
    6. tie break: 동일 curated_at → workflow_id 알파벳 내림차순 → 알파벳 뒷순위 유지
    7. 깨진 yaml → ``(0, stem)`` fallback → 가장 오래된 것으로 분류 → 우선 삭제
    8. curate_workflow 통합 — 51번째 빌드 시 가장 오래된 entry 자동 삭제
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agents.knowledge import (
    DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES,
    KnowledgeEntry,
    curate_workflow,
    prune_knowledge_index_lru,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_yaml_entry(
    index_dir: Path,
    *,
    workflow_id: str,
    curated_at: str,
    qa_verdict: str = "APPROVED",
) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    entry = KnowledgeEntry(
        workflow_id=workflow_id,
        curated_at=curated_at,
        user_request_oneline="x",
        qa_verdict=qa_verdict,
    )
    path = index_dir / f"{workflow_id}.yaml"
    path.write_text(entry.to_yaml(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. 기본 동작 — N=50 default + no-op / pruning
# ---------------------------------------------------------------------------


def test_default_max_entries_is_50() -> None:
    """기본 N=50 — 변경 시 회귀."""
    assert DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES == 50


def test_prune_noop_when_under_limit(tmp_path: Path) -> None:
    """파일 수 <= max_entries → 아무 것도 삭제 안 함."""
    idx = tmp_path / "knowledge_index"
    for i in range(10):
        _make_yaml_entry(
            idx,
            workflow_id=f"w_{i:02d}",
            curated_at=f"2026-05-{(i % 28) + 1:02d}",
        )
    deleted = prune_knowledge_index_lru(idx, max_entries=50)
    assert deleted == []
    assert len(list(idx.glob("*.yaml"))) == 10


def test_prune_keeps_top_n_by_curated_at(tmp_path: Path) -> None:
    """5 file + max_entries=3 → 최신 3개만 유지, 오래된 2개 삭제."""
    idx = tmp_path / "knowledge_index"
    _make_yaml_entry(idx, workflow_id="w_old1", curated_at="2026-05-01")
    _make_yaml_entry(idx, workflow_id="w_old2", curated_at="2026-05-02")
    _make_yaml_entry(idx, workflow_id="w_mid", curated_at="2026-05-10")
    _make_yaml_entry(idx, workflow_id="w_new1", curated_at="2026-05-14")
    _make_yaml_entry(idx, workflow_id="w_new2", curated_at="2026-05-15")

    deleted = prune_knowledge_index_lru(idx, max_entries=3)
    remaining = sorted(p.stem for p in idx.glob("*.yaml"))
    deleted_stems = sorted(p.stem for p in deleted)

    assert remaining == ["w_mid", "w_new1", "w_new2"]
    assert deleted_stems == ["w_old1", "w_old2"]


def test_prune_at_exact_limit_is_noop(tmp_path: Path) -> None:
    """파일 수 == max_entries → 정확히 경계 — no-op (off-by-one 차단)."""
    idx = tmp_path / "knowledge_index"
    for i in range(5):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i}", curated_at=f"2026-05-{i + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx, max_entries=5)
    assert deleted == []


# ---------------------------------------------------------------------------
# 2. Override — explicit > env var > default
# ---------------------------------------------------------------------------


def test_explicit_max_entries_takes_priority_over_env_var(
    tmp_path: Path, monkeypatch
) -> None:
    """explicit max_entries=2 가 env var=10 보다 우선."""
    monkeypatch.setenv("NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES", "10")
    idx = tmp_path / "knowledge_index"
    for i in range(5):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i}", curated_at=f"2026-05-{i + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx, max_entries=2)
    assert len(deleted) == 3
    assert len(list(idx.glob("*.yaml"))) == 2


def test_env_var_override_when_max_entries_none(
    tmp_path: Path, monkeypatch
) -> None:
    """max_entries=None → env var 사용."""
    monkeypatch.setenv("NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES", "3")
    idx = tmp_path / "knowledge_index"
    for i in range(5):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i}", curated_at=f"2026-05-{i + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx)
    assert len(deleted) == 2
    assert len(list(idx.glob("*.yaml"))) == 3


def test_invalid_env_var_falls_back_to_default(
    tmp_path: Path, monkeypatch
) -> None:
    """env var 가 정수 파싱 실패 → 기본 50 fallback."""
    monkeypatch.setenv("NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES", "not-a-number")
    idx = tmp_path / "knowledge_index"
    # 10 파일 < 50 → no-op
    for i in range(10):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i:02d}", curated_at=f"2026-05-{i + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx)
    assert deleted == []


# ---------------------------------------------------------------------------
# 3. 회전 비활성 — max_entries <= 0
# ---------------------------------------------------------------------------


def test_max_entries_zero_disables_rotation(tmp_path: Path) -> None:
    """max_entries=0 → 비활성, 모든 파일 보존."""
    idx = tmp_path / "knowledge_index"
    for i in range(100):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i:03d}", curated_at=f"2026-05-{(i % 28) + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx, max_entries=0)
    assert deleted == []
    assert len(list(idx.glob("*.yaml"))) == 100


def test_negative_max_entries_disables_rotation(tmp_path: Path) -> None:
    """max_entries < 0 → 비활성 (안전망)."""
    idx = tmp_path / "knowledge_index"
    for i in range(3):
        _make_yaml_entry(
            idx, workflow_id=f"w_{i}", curated_at=f"2026-05-{i + 1:02d}"
        )
    deleted = prune_knowledge_index_lru(idx, max_entries=-1)
    assert deleted == []


# ---------------------------------------------------------------------------
# 4. Edge — 부재 디렉터리 / 빈 디렉터리
# ---------------------------------------------------------------------------


def test_prune_when_index_dir_missing_is_noop(tmp_path: Path) -> None:
    """디렉터리 부재 → no-op (graceful, 첫 빌드 케이스)."""
    deleted = prune_knowledge_index_lru(tmp_path / "nope", max_entries=10)
    assert deleted == []


def test_prune_when_index_dir_empty_is_noop(tmp_path: Path) -> None:
    """디렉터리 빈 → no-op."""
    idx = tmp_path / "knowledge_index"
    idx.mkdir()
    deleted = prune_knowledge_index_lru(idx, max_entries=10)
    assert deleted == []


# ---------------------------------------------------------------------------
# 5. Tie break — 동일 curated_at → workflow_id 알파벳 내림차순
# ---------------------------------------------------------------------------


def test_tie_break_keeps_higher_workflow_id_alphabetically(
    tmp_path: Path,
) -> None:
    """동일 curated_at 5 개 + max_entries=2 → alphabet 내림차순 상위 2개 유지."""
    idx = tmp_path / "knowledge_index"
    for wid in ["w_aaa", "w_bbb", "w_ccc", "w_ddd", "w_eee"]:
        _make_yaml_entry(idx, workflow_id=wid, curated_at="2026-05-15")

    prune_knowledge_index_lru(idx, max_entries=2)
    remaining = sorted(p.stem for p in idx.glob("*.yaml"))
    assert remaining == ["w_ddd", "w_eee"], (
        "tie break: workflow_id 알파벳 내림차순 보존 회귀 — "
        f"실제 remaining: {remaining}"
    )


# ---------------------------------------------------------------------------
# 6. 깨진 yaml — fallback 으로 최우선 삭제
# ---------------------------------------------------------------------------


def test_broken_yaml_files_are_pruned_first(tmp_path: Path) -> None:
    """깨진 yaml 은 ``("", stem)`` 으로 정렬되어 가장 오래된 것으로 분류 → 우선 삭제."""
    idx = tmp_path / "knowledge_index"
    # 정상 entry 2개
    _make_yaml_entry(idx, workflow_id="w_valid_new", curated_at="2026-05-15")
    _make_yaml_entry(idx, workflow_id="w_valid_old", curated_at="2026-05-01")
    # 깨진 yaml 1개
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "w_broken.yaml").write_text("::: bogus :::\n  - {", encoding="utf-8")

    prune_knowledge_index_lru(idx, max_entries=2)
    remaining = sorted(p.stem for p in idx.glob("*.yaml"))
    # 깨진 것 + valid_old 중 하나 삭제, valid_new 유지
    assert "w_valid_new" in remaining
    assert "w_broken" not in remaining, (
        "깨진 yaml 이 유지 — fallback 정렬 회귀"
    )


# ---------------------------------------------------------------------------
# 7. curate_workflow 통합 — 새 entry 작성 직후 자동 prune
# ---------------------------------------------------------------------------


def _create_workflow_dir(parent: Path, name: str, request: str = "x") -> Path:
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "00_user_request.txt").write_text(request, encoding="utf-8")
    (d / "04_qa_review.md").write_text(
        "Final Answer: APPROVED", encoding="utf-8"
    )
    return d


def test_curate_workflow_auto_prunes_when_limit_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    """``curate_workflow`` 호출 시 max 초과면 자동 prune (env var=2 로 강제)."""
    monkeypatch.setenv("NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES", "2")
    idx_dir = tmp_path / "knowledge_index"

    # 첫 빌드 — 1 entry
    wd1 = _create_workflow_dir(tmp_path, "workflow_20260513")
    curate_workflow(wd1, "x", knowledge_index_dir=idx_dir)
    # 둘째 빌드 — 2 entry (한도 도달)
    wd2 = _create_workflow_dir(tmp_path, "workflow_20260514")
    curate_workflow(wd2, "x", knowledge_index_dir=idx_dir)
    assert len(list(idx_dir.glob("*.yaml"))) == 2

    # 셋째 빌드 — 한도 초과 → 가장 오래된 (20260513) 자동 삭제
    wd3 = _create_workflow_dir(tmp_path, "workflow_20260515")
    curate_workflow(wd3, "x", knowledge_index_dir=idx_dir)

    remaining = sorted(p.stem for p in idx_dir.glob("*.yaml"))
    assert len(remaining) == 2
    assert "workflow_20260515" in remaining, (
        "최신 빌드 entry 가 유지되지 않음 — auto prune 회귀"
    )
    assert "workflow_20260513" not in remaining, (
        "가장 오래된 빌드 entry 가 삭제되지 않음 — auto prune 회귀"
    )


def test_curate_workflow_swallows_prune_exception(
    tmp_path: Path, monkeypatch
) -> None:
    """prune 도중 예외 → curate_workflow 자체는 정상 종료 (실패 격리)."""
    from src.agents.knowledge import curate as curate_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("prune boom")

    monkeypatch.setattr(curate_mod, "prune_knowledge_index_lru", _boom)

    idx_dir = tmp_path / "knowledge_index"
    wd = _create_workflow_dir(tmp_path, "workflow_x")
    entry, dist, idx_path = curate_workflow(
        wd, "x", knowledge_index_dir=idx_dir
    )
    # prune 실패 무관 — entry/path 정상 산출
    assert entry is not None
    assert idx_path is not None
    assert idx_path.exists()
