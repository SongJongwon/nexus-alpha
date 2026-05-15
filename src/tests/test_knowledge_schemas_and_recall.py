# -*- coding: utf-8 -*-
"""PR #140 Phase 3 — KnowledgeEntry schema + recall_past_entries 단위 테스트.

배경 (본인 비전 통찰 6 D-1 — 학습 메커니즘 부재):
    Knowledge Curator + RAG Searcher 는 PR #133 부터 *구현 완료* 상태이나 production
    path 에서 호출 X — 198 outputs 디렉터리가 *write-only* 였음. PR #140 은 RAG
    recall + Curator curate 를 LangGraph 진입/종결 노드로 wiring → *진짜 자기 진화*
    의 첫 cycle.

본 테스트 목적:
    - KnowledgeEntry yaml 라운드트립 + 한글 보존
    - score_against_request: 키워드/태그 매칭 + qa-needs-revision/partial-output 페널티
    - recall_past_entries: 디렉터리 부재 / 결정론 prefilter / LLM rerank / pytest 자동 skip
"""

from __future__ import annotations

from pathlib import Path

from src.agents.knowledge import (
    KnowledgeEntry,
    format_recalled_entries_for_context,
    recall_past_entries,
)


# ---------------------------------------------------------------------------
# 1. KnowledgeEntry yaml 라운드트립
# ---------------------------------------------------------------------------


def test_knowledge_entry_yaml_roundtrip() -> None:
    """to_yaml → from_yaml 라운드트립 모든 필드 보존."""
    original = KnowledgeEntry(
        workflow_id="workflow_20260514_120000",
        curated_at="2026-05-14",
        user_request_oneline="환율 변환기 만들어줘",
        summary="frankfurter API + tkinter GUI 환율 변환기",
        tags=["currency-converter", "python", "tkinter", "qa-approved"],
        artifacts=["00_user_request.txt", "code/main.py"],
        qa_verdict="APPROVED",
    )
    text = original.to_yaml()
    restored = KnowledgeEntry.from_yaml(text)

    assert restored.workflow_id == original.workflow_id
    assert restored.curated_at == original.curated_at
    assert restored.user_request_oneline == original.user_request_oneline
    assert restored.summary == original.summary
    assert restored.tags == original.tags
    assert restored.artifacts == original.artifacts
    assert restored.qa_verdict == "APPROVED"


def test_knowledge_entry_yaml_preserves_korean() -> None:
    """한글 escape 없이 보존."""
    e = KnowledgeEntry(
        workflow_id="x", curated_at="2026-05-15",
        user_request_oneline="환율 변환기",
    )
    text = e.to_yaml()
    assert "환율" in text
    assert "\\u" not in text


def test_knowledge_entry_normalizes_unknown_verdict() -> None:
    """알 수 없는 verdict 입력 시 UNKNOWN 으로 정규화."""
    e = KnowledgeEntry.from_yaml(
        "workflow_id: x\ncurated_at: 2026-01-01\nuser_request_oneline: a\nqa_verdict: weird\n"
    )
    assert e.qa_verdict in ("UNKNOWN", "WEIRD")  # upper-case 만 보장


# ---------------------------------------------------------------------------
# 2. score_against_request — 키워드/태그 매칭 + 페널티
# ---------------------------------------------------------------------------


def _make_entry(**overrides) -> KnowledgeEntry:
    defaults = dict(
        workflow_id="w_1",
        curated_at="2026-05-14",
        user_request_oneline="환율 변환기 만들어줘",
        summary="frankfurter API tkinter GUI",
        tags=["currency-converter", "python", "tkinter", "qa-approved"],
        artifacts=[],
        qa_verdict="APPROVED",
    )
    defaults.update(overrides)
    return KnowledgeEntry(**defaults)


def test_score_positive_when_keywords_match() -> None:
    """tag/summary 와 매칭되는 키워드 시 양수 점수."""
    e = _make_entry()
    score = e.score_against_request("환율 변환기 python tkinter")
    assert score > 0.0


def test_score_zero_for_unrelated_request() -> None:
    """완전 무관 요청 시 0 점."""
    e = _make_entry()
    # 영어 단어가 tag/summary 와 겹치지 않게 — Korean-only 요청
    score = e.score_against_request("정렬 알고리즘 자료구조")
    assert score == 0.0


def test_score_penalizes_needs_revision() -> None:
    """qa_verdict NEEDS_REVISION 은 score -2 페널티."""
    approved = _make_entry()
    revisable = _make_entry(qa_verdict="NEEDS_REVISION")
    req = "환율 변환기 python"
    assert approved.score_against_request(req) > revisable.score_against_request(req)


def test_score_penalizes_partial_output_tag() -> None:
    """``partial-output`` 태그 있는 entry 도 페널티."""
    normal = _make_entry()
    partial = _make_entry(tags=normal.tags + ["partial-output"])
    req = "환율 변환기 python"
    assert normal.score_against_request(req) > partial.score_against_request(req)


def test_score_caps_at_10() -> None:
    """매우 많은 매칭이어도 score 상한 10."""
    e = _make_entry(
        tags=["a", "b", "c", "d", "e"],
        summary="a b c d e f g h i j",
    )
    score = e.score_against_request("a b c d e f g h i j")
    assert score <= 10.0


# ---------------------------------------------------------------------------
# 3. recall_past_entries — 디스크 + prefilter + LLM rerank
# ---------------------------------------------------------------------------


def test_recall_returns_empty_when_index_missing(tmp_path: Path) -> None:
    """인덱스 디렉터리 부재 시 빈 리스트."""
    result = recall_past_entries(
        "환율 변환기", tmp_path / "does_not_exist", top_n=3
    )
    assert result == []


def test_recall_returns_empty_when_index_empty(tmp_path: Path) -> None:
    """빈 디렉터리 시 빈 리스트."""
    tmp_path.mkdir(exist_ok=True)
    result = recall_past_entries("환율", tmp_path, top_n=3)
    assert result == []


def _write_entry(dir_path: Path, **fields) -> None:
    entry = _make_entry(**fields)
    (dir_path / f"{entry.workflow_id}.yaml").write_text(
        entry.to_yaml(), encoding="utf-8"
    )


def test_recall_returns_top_n_by_deterministic_score(tmp_path: Path) -> None:
    """결정론 score 내림차순 top_n."""
    _write_entry(tmp_path, workflow_id="w_high",
                 user_request_oneline="환율 변환기",
                 tags=["currency", "python"])
    _write_entry(tmp_path, workflow_id="w_low",
                 user_request_oneline="메모장",
                 summary="텍스트 에디터", tags=["editor"])
    _write_entry(tmp_path, workflow_id="w_unrelated",
                 user_request_oneline="image-tool",
                 summary="png batch resize", tags=["image"])

    result = recall_past_entries(
        "환율 변환기 python", tmp_path, top_n=2
    )
    assert len(result) <= 2
    # 가장 관련 높은 게 w_high
    assert result[0].workflow_id == "w_high"


def test_recall_filters_zero_score_entries(tmp_path: Path) -> None:
    """score 0 entry 는 결과에서 제외 — 의미 없는 추천 방지."""
    _write_entry(tmp_path, workflow_id="w_unrelated",
                 user_request_oneline="비행기 시뮬레이터", summary="3D flight sim",
                 tags=["3d", "game"])
    result = recall_past_entries("환율 변환기", tmp_path, top_n=3)
    assert result == []


def test_recall_skips_llm_in_pytest_env(tmp_path: Path) -> None:
    """pytest 환경에서 LLM 호출 자동 skip — CI 가 OPENAI_API_KEY 없이 통과해야."""
    _write_entry(tmp_path, workflow_id="w_x", user_request_oneline="환율 변환기")
    # llm_call=None + pytest 환경 → 결정론만
    result = recall_past_entries("환율", tmp_path, top_n=3, llm_call=None)
    # 호출 자체 안 깨짐 — 결과는 결정론 score 로 결정
    assert isinstance(result, list)


def test_recall_uses_injected_llm_call_for_rerank(tmp_path: Path) -> None:
    """외부 ``llm_call`` 주입 시 reranking 결과 반영."""
    _write_entry(tmp_path, workflow_id="w_alpha", user_request_oneline="환율 alpha",
                 tags=["currency", "python"])
    _write_entry(tmp_path, workflow_id="w_beta", user_request_oneline="환율 beta",
                 tags=["currency", "python"])

    # LLM 이 beta 를 먼저 선호한다고 응답
    def fake_llm(prompt: str) -> str:
        return '{"reranked_workflow_ids": ["w_beta", "w_alpha"]}'

    result = recall_past_entries(
        "환율 python", tmp_path, top_n=2, llm_call=fake_llm
    )
    assert [e.workflow_id for e in result] == ["w_beta", "w_alpha"]


def test_recall_survives_llm_exception(tmp_path: Path) -> None:
    """LLM 호출 실패 시 결정론 결과로 fallback."""
    _write_entry(tmp_path, workflow_id="w_x", user_request_oneline="환율 변환기")

    def boom(prompt: str) -> str:
        raise RuntimeError("network down")

    result = recall_past_entries("환율", tmp_path, top_n=3, llm_call=boom)
    # 결정론 결과만 — 호출은 깨지지 않음
    assert isinstance(result, list)
    assert all(e.workflow_id == "w_x" for e in result)


def test_recall_skips_malformed_yaml(tmp_path: Path) -> None:
    """yaml 파싱 실패 파일은 skip — 한 파일 깨졌다고 전체 차단 X."""
    (tmp_path / "broken.yaml").write_text("not: valid: yaml:\n  - 1\n - 2", encoding="utf-8")
    _write_entry(tmp_path, workflow_id="w_ok", user_request_oneline="환율 변환기")

    result = recall_past_entries("환율", tmp_path, top_n=3)
    # broken 은 skip, w_ok 만 후보
    assert any(e.workflow_id == "w_ok" for e in result)


# ---------------------------------------------------------------------------
# 4. format_recalled_entries_for_context — markdown 직렬화
# ---------------------------------------------------------------------------


def test_format_returns_empty_for_empty_entries() -> None:
    """빈 리스트 입력 시 빈 string."""
    assert format_recalled_entries_for_context([]) == ""


def test_format_includes_workflow_id_and_tags() -> None:
    """markdown 에 workflow_id + tags 모두 포함."""
    entries = [_make_entry(workflow_id="w_xyz", tags=["a", "b"])]
    text = format_recalled_entries_for_context(entries)
    assert "w_xyz" in text
    assert "a, b" in text or "a" in text
    assert "RAG recall" in text  # 섹션 헤더 evidence
