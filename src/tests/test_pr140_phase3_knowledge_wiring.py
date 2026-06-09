# -*- coding: utf-8 -*-
"""PR #140 Phase 3 — iterative_loop 노드 통합 회귀 차단.

배경 (본인 비전 통찰 6 D-1):
    Knowledge Curator + RAG Searcher 가 PR #133 부터 *구현 완료* 인데 production
    path 호출 X — 본 PR 이 LangGraph 진입/종결 노드로 wiring. *진짜 자기 진화*
    의 첫 cycle (회고 → 색인 → 다음 빌드 학습).

본 테스트 목적 (file-text + 단위 + 통합 혼합):
    - _LoopState 에 knowledge_index_dir / recalled_entries / curated_entry 필드
    - LoopOutcome 에 recalled_entries / curated_entry / curated_entry_path 필드
    - _node_recall_past_knowledge: 인덱스 부재 시 빈 리스트, 존재 시 추천
    - _node_curate_knowledge: workflow_dir 산출물 → KnowledgeEntry yaml 저장
    - Graph 가 recall_past_knowledge / curate_knowledge 노드 + 엣지 포함
"""

from __future__ import annotations

from pathlib import Path

from src.agents.knowledge import KnowledgeEntry
from src.workflows import iterative_loop as IL


# ---------------------------------------------------------------------------
# 1. _LoopState 필드 회귀 차단
# ---------------------------------------------------------------------------


def test_loop_state_has_knowledge_fields() -> None:
    """_LoopState 가 4 신규 필드 포함."""
    ann = IL._LoopState.__annotations__
    for key in (
        "knowledge_index_dir",
        "recalled_entries",
        "curated_entry",
        "curated_entry_path",
        "curated_index_path",
    ):
        assert key in ann, f"_LoopState 에 {key} 필드 누락"


def test_loop_outcome_has_knowledge_fields() -> None:
    """LoopOutcome dataclass 가 4 신규 필드 포함."""
    fields_set = {f.name for f in IL.LoopOutcome.__dataclass_fields__.values()}
    for key in (
        "recalled_entries",
        "curated_entry",
        "curated_entry_path",
        "curated_index_path",
    ):
        assert key in fields_set, f"LoopOutcome 에 {key} 필드 누락"


# ---------------------------------------------------------------------------
# 2. _node_recall_past_knowledge — 진입 노드
# ---------------------------------------------------------------------------


def test_node_recall_returns_empty_list_when_index_missing(tmp_path: Path) -> None:
    """인덱스 디렉터리 부재 시 빈 리스트 반환."""
    state = {
        "user_request": "환율 변환기",
        "outputs_dir": tmp_path.as_posix(),
    }
    result = IL._node_recall_past_knowledge(state)  # type: ignore[arg-type]

    assert "recalled_entries" in result
    assert result["recalled_entries"] == []
    # knowledge_index_dir 도 state 에 추가 (curate 노드가 재사용)
    assert "knowledge_index_dir" in result


def test_node_recall_finds_existing_entries(tmp_path: Path) -> None:
    """outputs_dir/knowledge_index/ 에 entry 있으면 검색."""
    idx_dir = tmp_path / "knowledge_index"
    idx_dir.mkdir(parents=True)
    entry = KnowledgeEntry(
        workflow_id="w_past",
        curated_at="2026-05-14",
        user_request_oneline="환율 변환기",
        summary="frankfurter API 변환기",
        tags=["currency", "python", "qa-approved"],
        qa_verdict="APPROVED",
    )
    (idx_dir / f"{entry.workflow_id}.yaml").write_text(
        entry.to_yaml(), encoding="utf-8"
    )

    state = {
        "user_request": "환율 변환기 만들어줘 python",
        "outputs_dir": tmp_path.as_posix(),
    }
    result = IL._node_recall_past_knowledge(state)  # type: ignore[arg-type]

    recalled = result["recalled_entries"]
    assert len(recalled) == 1
    assert recalled[0].workflow_id == "w_past"


def test_node_recall_survives_internal_exception(monkeypatch, tmp_path: Path) -> None:
    """recall_past_entries 가 예외 던져도 노드는 빈 리스트 반환."""

    def boom(*args, **kwargs):
        raise RuntimeError("internal")

    monkeypatch.setattr(IL, "recall_past_entries", boom)

    state = {
        "user_request": "x",
        "outputs_dir": tmp_path.as_posix(),
    }
    result = IL._node_recall_past_knowledge(state)  # type: ignore[arg-type]
    assert result["recalled_entries"] == []


# ---------------------------------------------------------------------------
# 3. _node_curate_knowledge — 종결 노드
# ---------------------------------------------------------------------------


def _make_dummy_chain_result(workflow_dir: Path):
    """Minimal WorkflowResult-like object — saved_dir 만 있으면 됨."""
    class _Chain:
        def __init__(self, saved):
            self.saved_dir = saved

    return _Chain(workflow_dir)


def test_node_curate_writes_yaml_when_chain_succeeds(tmp_path: Path) -> None:
    """chain_result.saved_dir 있을 때 entry yaml 작성 + state 갱신."""
    workflow_dir = tmp_path / "workflow_20260515_120000"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "04_qa_review.md").write_text(
        "Final Answer: APPROVED", encoding="utf-8"
    )
    index_dir = tmp_path / "knowledge_index"

    state = {
        "user_request": "환율 변환기 만들어줘",
        "outputs_dir": tmp_path.as_posix(),
        "knowledge_index_dir": index_dir.as_posix(),
        "chain_result": _make_dummy_chain_result(workflow_dir),
    }
    result = IL._node_curate_knowledge(state)  # type: ignore[arg-type]

    assert isinstance(result["curated_entry"], KnowledgeEntry)
    assert result["curated_entry"].qa_verdict == "APPROVED"
    assert result["curated_entry_path"]
    assert (workflow_dir / "knowledge_entry.yaml").exists()
    assert (index_dir / f"{workflow_dir.name}.yaml").exists()


def test_node_curate_handles_missing_chain_result(tmp_path: Path) -> None:
    """chain_result 부재 시 None entry 반환 — 차단 없이 빠져나감."""
    state = {
        "user_request": "x",
        "outputs_dir": tmp_path.as_posix(),
        "knowledge_index_dir": (tmp_path / "knowledge_index").as_posix(),
    }
    result = IL._node_curate_knowledge(state)  # type: ignore[arg-type]
    assert result["curated_entry"] is None
    assert result["curated_entry_path"] == ""


# ---------------------------------------------------------------------------
# 4. Graph 구조 — 노드 + 엣지 회귀 차단
# ---------------------------------------------------------------------------


def test_graph_contains_recall_and_curate_nodes() -> None:
    """compiled graph 에 recall_past_knowledge / curate_knowledge 포함."""
    graph = IL.build_iterative_loop_graph()
    nodes = set(graph.get_graph().nodes.keys())
    assert "recall_past_knowledge" in nodes
    assert "curate_knowledge" in nodes


def test_graph_routes_expand_to_recall_then_kickoff() -> None:
    """expand_requirements → recall_past_knowledge → kickoff_meeting 순서."""
    graph = IL.build_iterative_loop_graph()
    edge_pairs = set()
    for edge in graph.get_graph().edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    assert ("expand_requirements", "recall_past_knowledge") in edge_pairs
    assert ("recall_past_knowledge", "kickoff_meeting") in edge_pairs


def test_graph_routes_curate_before_finalize() -> None:
    """curate_knowledge 가 종결(finalize) 전에 색인됨 — 종결 전 색인.

    v13 P27: curate_knowledge → finalize 직결이 documentation_lead 경유로 바뀜
    (curate_knowledge → documentation_lead → finalize). curate 가 finalize 전에 도는 불변은 유지.
    """
    graph = IL.build_iterative_loop_graph()
    edge_pairs = set()
    for edge in graph.get_graph().edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    # P27 — curate 직후 documentation_lead, 그 다음 finalize (curate→…→finalize 불변).
    assert ("curate_knowledge", "documentation_lead") in edge_pairs
    assert ("documentation_lead", "finalize") in edge_pairs


def test_graph_preserves_iteration_reentry_no_recall_recall() -> None:
    """prepare_feedback → run_chain (kickoff/recall 우회) — iteration 재진입."""
    graph = IL.build_iterative_loop_graph()
    edge_pairs = set()
    for edge in graph.get_graph().edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    # recall 으로의 역방향 edge 없어야 함 (회상은 1회만)
    assert ("prepare_feedback", "recall_past_knowledge") not in edge_pairs
