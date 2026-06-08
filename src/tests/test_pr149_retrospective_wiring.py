# -*- coding: utf-8 -*-
"""PR #149 — iterative_loop 의 _node_retrospective 통합 + curate cycle 회귀 차단.

배경: Retrospective Lead 가 종결 노드로 wiring 되어야 그 산출 markdown 이
Knowledge Curator 의 입력으로 흘러간다. cycle 끊기면 entry 가 다시 평면적 정보로
돌아감 — Phase 3 cycle 무력화.

본 테스트 목적:
    - _LoopState 에 retrospective_report / retrospective_md_path 필드
    - LoopOutcome 에 동일 필드
    - _node_retrospective: report 산출 + markdown 저장 + state 갱신
    - Graph 가 retrospective 노드 + 엣지 (judge → retrospective → curate) 포함
    - curate_workflow 가 retrospective_md 인자를 수용 + prompt 에 포함
"""

from __future__ import annotations

from pathlib import Path

from src.agents.coordination import RetrospectiveReport
from src.agents.knowledge import curate_workflow
from src.workflows import iterative_loop as IL


# ---------------------------------------------------------------------------
# 1. _LoopState / LoopOutcome 필드
# ---------------------------------------------------------------------------


def test_loop_state_has_retrospective_fields() -> None:
    """_LoopState 가 retrospective_report + retrospective_md_path 필드 포함."""
    ann = IL._LoopState.__annotations__
    assert "retrospective_report" in ann
    assert "retrospective_md_path" in ann


def test_loop_outcome_has_retrospective_fields() -> None:
    """LoopOutcome dataclass 가 retrospective_report + retrospective_md_path 필드."""
    fields_set = {f.name for f in IL.LoopOutcome.__dataclass_fields__.values()}
    assert "retrospective_report" in fields_set
    assert "retrospective_md_path" in fields_set


# ---------------------------------------------------------------------------
# 2. _node_retrospective — 종결 노드
# ---------------------------------------------------------------------------


class _FakeChain:
    def __init__(self, saved_dir):
        self.saved_dir = saved_dir
        self.engineer_output = "x"
        self.gui_code_output = ""
        self.qa_review = "Final Answer: APPROVED"


class _FakeVerdict:
    name = "COMPLETE"


class _FakeDecision:
    verdict = _FakeVerdict()


def test_node_retrospective_writes_markdown_when_chain_succeeds(tmp_path: Path) -> None:
    """workflow_dir 에 retrospective.md 작성 + state 갱신."""
    workflow_dir = tmp_path / "workflow_20260515_120000"
    workflow_dir.mkdir(parents=True)

    state = {
        "user_request": "환율 변환기",
        "outputs_dir": tmp_path.as_posix(),
        "chain_result": _FakeChain(workflow_dir),
        "decision": _FakeDecision(),
        "execution_result": None,
        "shared_kickoff_decisions": None,
    }
    result = IL._node_retrospective(state)  # type: ignore[arg-type]

    assert isinstance(result["retrospective_report"], RetrospectiveReport)
    assert result["retrospective_md_path"]
    assert (workflow_dir / "retrospective.md").exists()
    md = (workflow_dir / "retrospective.md").read_text(encoding="utf-8")
    assert "Retrospective" in md
    assert "COMPLETE" in md


def test_node_retrospective_survives_no_chain_result(tmp_path: Path) -> None:
    """chain_result 부재 시 — report 는 골격만 반환, path 빈 문자열."""
    state = {
        "user_request": "x",
        "outputs_dir": tmp_path.as_posix(),
        "decision": _FakeDecision(),
    }
    result = IL._node_retrospective(state)  # type: ignore[arg-type]
    assert isinstance(result["retrospective_report"], RetrospectiveReport)
    assert result["retrospective_md_path"] == ""


# ---------------------------------------------------------------------------
# 3. Graph 노드 + 엣지
# ---------------------------------------------------------------------------


def test_graph_contains_retrospective_nodes() -> None:
    """compiled graph 에 retrospective + retrospective_blocked 노드 포함."""
    graph = IL.build_iterative_loop_graph()
    nodes = set(graph.get_graph().nodes.keys())
    assert "retrospective" in nodes
    assert "retrospective_blocked" in nodes


def test_graph_routes_retrospective_before_curate() -> None:
    """retrospective → curate_knowledge → (documentation_lead) → finalize 순서 (정상 종결 경로).

    v13 P27: curate_knowledge 와 finalize 사이에 documentation_lead 가 가산됨(비차단 문서 생성).
    """
    graph = IL.build_iterative_loop_graph()
    edge_pairs = set()
    for edge in graph.get_graph().edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    assert ("retrospective", "curate_knowledge") in edge_pairs
    # v13 P27 — curate_knowledge → finalize 사이에 documentation_lead 가산(curate→…→finalize 불변).
    assert ("curate_knowledge", "documentation_lead") in edge_pairs
    assert ("documentation_lead", "finalize") in edge_pairs


def test_graph_routes_retrospective_blocked_before_curate_blocked() -> None:
    """BLOCKED 경로도 retrospective_blocked → curate_knowledge_blocked → escalate."""
    graph = IL.build_iterative_loop_graph()
    edge_pairs = set()
    for edge in graph.get_graph().edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    assert ("retrospective_blocked", "curate_knowledge_blocked") in edge_pairs
    assert ("curate_knowledge_blocked", "escalate") in edge_pairs


# ---------------------------------------------------------------------------
# 4. curate_workflow + retrospective_md — cycle 완성
# ---------------------------------------------------------------------------


def test_curate_workflow_accepts_retrospective_md(tmp_path: Path) -> None:
    """``curate_workflow`` 가 ``retrospective_md`` 키워드 인자 수용."""
    workflow_dir = tmp_path / "workflow_x"
    workflow_dir.mkdir()
    (workflow_dir / "04_qa_review.md").write_text(
        "Final Answer: APPROVED", encoding="utf-8"
    )

    # 단지 인자 수용 + 호출 깨지지 않으면 성공 — LLM mock 없으면 pytest 환경
    entry, _, _ = curate_workflow(
        workflow_dir, "환율 변환기",
        retrospective_md="# Retrospective\n## lessons\n- timeout 늘려야",
    )
    # 결정론 entry — summary/tags 비어 있어도 OK (LLM skip)
    assert entry.workflow_id == "workflow_x"


def test_curate_workflow_includes_retrospective_in_prompt(tmp_path: Path) -> None:
    """retrospective_md 가 LLM prompt 에 포함됨 — Curator 가 회고 기반으로 응답."""
    workflow_dir = tmp_path / "workflow_x"
    workflow_dir.mkdir()
    captured_prompt: list[str] = []

    def fake_llm(prompt: str) -> str:
        captured_prompt.append(prompt)
        return '{"summary": "x", "tags": ["a"]}'

    curate_workflow(
        workflow_dir, "환율 변환기",
        retrospective_md="## Lessons learned\n- frankfurter timeout 10s 권장",
        llm_call=fake_llm,
    )
    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert "frankfurter timeout 10s" in prompt or "Lessons learned" in prompt
