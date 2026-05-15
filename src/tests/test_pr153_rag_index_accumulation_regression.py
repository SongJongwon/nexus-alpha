# -*- coding: utf-8 -*-
"""PR #153 — RAG knowledge_index 다중 entry 누적 회귀 차단.

배경 (PR #152 사후 검증에서 발견):
    ``outputs/knowledge_index/<workflow_id>.yaml`` 누적 구조는 PR #148 부터 도입됐으나
    기존 회귀 테스트 (test_knowledge_curate.py / test_pr140_phase3_knowledge_wiring.py)
    는 *모두 1 entry 시나리오* 만 cover. 다중 빌드 누적 → recall 정렬 → graceful
    degradation 등의 핵심 RAG 동작은 라이브 검증만 거치고 회귀 차단 부재.

    PR #152 라이브 검증에서 3 build 시뮬레이션으로 누적 작동을 확인 (workflow_A/B/C
    각각 별도 yaml + recall top-N 정확 매칭). 본 PR 은 그 동작을 회귀 테스트로 굳힘.

본 테스트 목적:
    - 다중 빌드 누적: curate_workflow N회 호출 → index_dir 에 N 파일 생성, 충돌 없음
    - 동일 workflow_id 재 curate → idempotent overwrite (재 빌드 case)
    - recall: 누적된 모든 entry 글로브 read, top-N 정렬 (점수 내림차순)
    - score 0 entry 자동 제외 (의미 없는 추천 차단)
    - top_N > 누적 수 — 가용 entry 만 반환
    - 빈 디렉터리 / 부재 디렉터리 → 빈 리스트
    - 깨진 yaml 1개 → 그것만 skip, 나머지 정상 (graceful)
    - NEEDS_REVISION / partial-output 페널티 — 정상 entry 가 우선
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.knowledge import (
    KnowledgeEntry,
    curate_workflow,
    recall_past_entries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_entry(index_dir: Path, entry: KnowledgeEntry) -> Path:
    """``KnowledgeEntry`` 를 index_dir 에 직접 yaml 로 기록 (curate_workflow 우회)."""
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / f"{entry.workflow_id}.yaml"
    path.write_text(entry.to_yaml(), encoding="utf-8")
    return path


def _make_entry(
    workflow_id: str,
    *,
    summary: str = "",
    tags: list[str] | None = None,
    qa_verdict: str = "APPROVED",
    request_oneline: str = "",
) -> KnowledgeEntry:
    return KnowledgeEntry(
        workflow_id=workflow_id,
        curated_at="2026-05-15",
        user_request_oneline=request_oneline,
        summary=summary,
        tags=tags or [],
        qa_verdict=qa_verdict,
    )


# ---------------------------------------------------------------------------
# 1. 다중 빌드 누적 — 파일별 분리, 충돌 없음
# ---------------------------------------------------------------------------


def test_multiple_curate_workflow_calls_produce_separate_index_files(
    tmp_path: Path,
) -> None:
    """N 회 curate_workflow → index_dir 에 N 개 yaml 누적, overwrite 없음."""
    index_dir = tmp_path / "knowledge_index"

    workflow_ids: list[str] = []
    for i, request in enumerate(
        ["계산기", "환율 변환기", "메모장"], start=1
    ):
        wd = tmp_path / f"workflow_2026051{i}"
        wd.mkdir()
        (wd / "00_user_request.txt").write_text(request, encoding="utf-8")
        (wd / "04_qa_review.md").write_text(
            "Final Answer: APPROVED", encoding="utf-8"
        )
        entry, _, idx_path = curate_workflow(
            wd, request, knowledge_index_dir=index_dir
        )
        assert idx_path is not None and idx_path.exists()
        workflow_ids.append(entry.workflow_id)

    files = sorted(p.name for p in index_dir.glob("*.yaml"))
    assert len(files) == 3, (
        f"3 회 curate 후 index_dir 에 3 파일 누적 예상, 실제 {len(files)}: {files}"
    )
    # 각 파일이 자기 workflow_id 와 매칭
    for wid in workflow_ids:
        assert (index_dir / f"{wid}.yaml").exists()


def test_re_curating_same_workflow_id_overwrites_idempotently(
    tmp_path: Path,
) -> None:
    """동일 workflow_id 두 번 curate → 마지막 entry 로 덮어쓰기 (재 빌드 case).

    워크플로 디렉터리가 재실행되면 같은 wid 로 entry 재산출. 파일 누적 X.
    """
    index_dir = tmp_path / "knowledge_index"
    wd = tmp_path / "workflow_same_id"
    wd.mkdir()
    (wd / "00_user_request.txt").write_text("v1 request", encoding="utf-8")
    (wd / "04_qa_review.md").write_text(
        "Final Answer: NEEDS_REVISION", encoding="utf-8"
    )
    _, _, p1 = curate_workflow(wd, "v1 request", knowledge_index_dir=index_dir)

    # 같은 wd 에서 verdict 만 바꿔 재 curate
    (wd / "04_qa_review.md").write_text(
        "Final Answer: APPROVED", encoding="utf-8"
    )
    _, _, p2 = curate_workflow(wd, "v1 request", knowledge_index_dir=index_dir)

    assert p1 == p2, "동일 wid 의 두 curate 가 다른 path 산출"
    files = list(index_dir.glob("*.yaml"))
    assert len(files) == 1, "동일 wid 가 누적되어 파일 2개 — overwrite 회귀"

    restored = KnowledgeEntry.from_yaml(files[0].read_text(encoding="utf-8"))
    assert restored.qa_verdict == "APPROVED", "마지막 curate 의 verdict 반영 안 됨"


# ---------------------------------------------------------------------------
# 2. recall — 누적 전체 글로브 + top-N 정렬
# ---------------------------------------------------------------------------


def test_recall_reads_all_accumulated_entries(tmp_path: Path) -> None:
    """N 개 entry 누적 후 recall — 모두 후보 풀에 들어감 (glob *.yaml)."""
    index_dir = tmp_path / "knowledge_index"
    for i in range(5):
        _write_entry(
            index_dir,
            _make_entry(
                f"workflow_acc_{i}",
                tags=["currency", "python"],
                request_oneline="환율 변환기 만들어줘",
                summary=f"빌드 {i} 산출",
            ),
        )

    recalled = recall_past_entries(
        user_request="환율 변환기 python", knowledge_index_dir=index_dir, top_n=10
    )
    assert len(recalled) == 5, (
        f"top_n=10 으로 5 entry 모두 회수 예상, 실제 {len(recalled)}"
    )


def test_recall_returns_top_n_in_score_descending_order(tmp_path: Path) -> None:
    """recall 결과가 score 내림차순 정렬 — 점수 높은 entry 가 앞."""
    index_dir = tmp_path / "knowledge_index"
    # 환율 관련 정확 매칭 entry (점수 높음)
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_high",
            tags=["currency", "frankfurter"],
            request_oneline="환율 변환기 frankfurter API",
            summary="frankfurter 실시간 환율",
        ),
    )
    # 부분 매칭 entry (점수 낮음)
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_low",
            tags=["python"],
            request_oneline="범용 python 스크립트",
            summary="기타 빌드",
        ),
    )

    recalled = recall_past_entries(
        user_request="환율 변환기 frankfurter python",
        knowledge_index_dir=index_dir,
        top_n=2,
    )
    assert len(recalled) == 2
    assert recalled[0].workflow_id == "workflow_high", (
        f"top-1 이 high-score 가 아님 — 정렬 회귀. 실제: {[e.workflow_id for e in recalled]}"
    )


def test_recall_excludes_score_zero_entries(tmp_path: Path) -> None:
    """score=0 entry 는 추천 풀에서 자동 제외 — 의미 없는 추천 차단."""
    index_dir = tmp_path / "knowledge_index"
    # 검색 요청과 *완전 무관* — 점수 0 산출
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_unrelated",
            tags=["totally", "unrelated"],
            request_oneline="아무 상관 없는 요청",
            summary="무관한 빌드",
        ),
    )

    recalled = recall_past_entries(
        user_request="환율 변환기",  # 위 entry 와 토큰 겹침 없음
        knowledge_index_dir=index_dir,
        top_n=5,
    )
    assert recalled == [], (
        f"score=0 entry 가 추천에 포함 — 회귀: {[e.workflow_id for e in recalled]}"
    )


def test_recall_top_n_larger_than_available_returns_all_matching(
    tmp_path: Path,
) -> None:
    """top_N > 가용 매칭 수 → 가용 모두 반환 (out-of-range 안전)."""
    index_dir = tmp_path / "knowledge_index"
    for i in range(2):
        _write_entry(
            index_dir,
            _make_entry(
                f"workflow_few_{i}",
                tags=["currency"],
                request_oneline="환율 변환기",
            ),
        )

    recalled = recall_past_entries(
        user_request="환율", knowledge_index_dir=index_dir, top_n=10
    )
    assert len(recalled) == 2


# ---------------------------------------------------------------------------
# 3. Edge cases — 빈 디렉터리 / 부재 디렉터리 / 깨진 yaml
# ---------------------------------------------------------------------------


def test_recall_returns_empty_when_index_dir_missing(tmp_path: Path) -> None:
    """index_dir 부재 → 빈 리스트 (첫 빌드 시나리오)."""
    recalled = recall_past_entries(
        user_request="x", knowledge_index_dir=tmp_path / "nope", top_n=3
    )
    assert recalled == []


def test_recall_returns_empty_when_index_dir_empty(tmp_path: Path) -> None:
    """index_dir 존재하나 yaml 0개 → 빈 리스트."""
    (tmp_path / "knowledge_index").mkdir()
    recalled = recall_past_entries(
        user_request="x", knowledge_index_dir=tmp_path / "knowledge_index", top_n=3
    )
    assert recalled == []


def test_recall_skips_broken_yaml_and_loads_valid_ones(tmp_path: Path) -> None:
    """yaml 1개 깨졌어도 나머지 정상 처리 — graceful degradation."""
    index_dir = tmp_path / "knowledge_index"
    index_dir.mkdir()

    # 정상 entry 2개
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_ok_1",
            tags=["currency"],
            request_oneline="환율",
        ),
    )
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_ok_2",
            tags=["currency"],
            request_oneline="환율",
        ),
    )
    # 깨진 yaml — 파싱 실패해야 함
    (index_dir / "workflow_broken.yaml").write_text(
        "::: invalid yaml ::: not parseable\n  - {", encoding="utf-8"
    )

    recalled = recall_past_entries(
        user_request="환율 변환기", knowledge_index_dir=index_dir, top_n=5
    )
    wids = {e.workflow_id for e in recalled}
    assert "workflow_ok_1" in wids
    assert "workflow_ok_2" in wids
    assert "workflow_broken" not in wids, (
        "깨진 yaml 이 결과에 포함 — graceful skip 회귀"
    )


# ---------------------------------------------------------------------------
# 4. Penalty 동작 — NEEDS_REVISION / partial-output 항상 하향정렬
# ---------------------------------------------------------------------------


def test_recall_prefers_approved_over_needs_revision_on_equal_topic(
    tmp_path: Path,
) -> None:
    """동일 주제 2 entry — APPROVED 가 NEEDS_REVISION 보다 앞 (-2 페널티 효과)."""
    index_dir = tmp_path / "knowledge_index"
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_approved",
            tags=["currency"],
            request_oneline="환율 변환기",
            qa_verdict="APPROVED",
        ),
    )
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_needs_rev",
            tags=["currency"],
            request_oneline="환율 변환기",
            qa_verdict="NEEDS_REVISION",
        ),
    )

    recalled = recall_past_entries(
        user_request="환율 변환기", knowledge_index_dir=index_dir, top_n=2
    )
    assert len(recalled) == 2
    assert recalled[0].workflow_id == "workflow_approved", (
        "APPROVED 가 NEEDS_REVISION 앞에 정렬 안 됨 — 페널티 회귀"
    )


def test_recall_penalizes_partial_output_tag(tmp_path: Path) -> None:
    """partial-output 태그 entry — -2 페널티 적용되어 정상 entry 가 앞."""
    index_dir = tmp_path / "knowledge_index"
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_complete",
            tags=["currency"],
            request_oneline="환율 변환기",
        ),
    )
    _write_entry(
        index_dir,
        _make_entry(
            "workflow_partial",
            tags=["currency", "partial-output"],
            request_oneline="환율 변환기",
        ),
    )

    recalled = recall_past_entries(
        user_request="환율 변환기", knowledge_index_dir=index_dir, top_n=2
    )
    assert recalled[0].workflow_id == "workflow_complete", (
        "partial-output 페널티 미적용 — 정상 entry 가 앞으로 정렬 안 됨"
    )
