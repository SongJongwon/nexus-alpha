# -*- coding: utf-8 -*-
"""PR #138 Phase 1 full — iterative_loop 킥오프 노드 통합 테스트.

배경 (본인 비전 통찰 6):
    Meeting Facilitator 신설만으로는 산출이 워크플로에 흘러들어가지 않음. LangGraph
    state 에 ``shared_kickoff_decisions`` 필드를 추가하고, ``expand_requirements``
    다음 노드로 ``kickoff_meeting`` 을 삽입해 1회만 실행되도록 배선.

본 테스트 목적:
    - ``_LoopState`` TypedDict 에 ``shared_kickoff_decisions`` 필드 존재
    - ``_node_kickoff_meeting`` 호출 결과로 ``SharedKickoffDecisions`` 인스턴스 반환
    - state 의 yaml 파일이 outputs_dir 루트에 작성됨
    - graph 가 expand_requirements → kickoff_meeting → run_chain 순서
    - iteration 재진입 (prepare_feedback → run_chain) 시 kickoff 재실행 없음

회귀 차단: 본 테스트가 깨지면 SharedKickoffDecisions 가 산출돼도 후속 chain 에
주입되지 않음 → Phase 1 full 의 핵심 기능 (kickoff → task description 자동 주입) 무력화.
"""

from __future__ import annotations

from pathlib import Path

from src.agents.coordination import SharedKickoffDecisions
from src.workflows import iterative_loop as IL


# ---------------------------------------------------------------------------
# 1. _LoopState 필드 회귀 차단
# ---------------------------------------------------------------------------


def test_loop_state_includes_shared_kickoff_decisions() -> None:
    """``_LoopState`` 가 shared_kickoff_decisions 필드 정의.

    회귀 차단 — 필드 누락 시 LangGraph 가 keyword 를 merge 못함.
    """
    annotations = IL._LoopState.__annotations__
    assert "shared_kickoff_decisions" in annotations, (
        "_LoopState 에 shared_kickoff_decisions 필드 누락 — PR #138 Phase 1 full "
        "킥오프 산출 보존 경로 단절"
    )


# ---------------------------------------------------------------------------
# 2. _node_kickoff_meeting 노드 동작
# ---------------------------------------------------------------------------


def test_node_kickoff_meeting_returns_decisions(tmp_path: Path) -> None:
    """노드 호출 → ``SharedKickoffDecisions`` 인스턴스를 state 키에 반환."""
    spec = """
```yaml
title: 환율 변환기
assumptions:
  - frankfurter API 실시간 호출
open_questions:
  - 오프라인 모드?
```
"""
    state = {
        "user_request": "환율 변환기 만들어줘",
        "spec_markdown": spec,
        "outputs_dir": tmp_path.as_posix(),
    }
    result = IL._node_kickoff_meeting(state)  # type: ignore[arg-type]

    assert "shared_kickoff_decisions" in result
    decisions = result["shared_kickoff_decisions"]
    assert isinstance(decisions, SharedKickoffDecisions)
    assert decisions.user_request == "환율 변환기 만들어줘"
    assert len(decisions.shared_assumptions) == 1
    assert "frankfurter" in decisions.shared_assumptions[0].decision


def test_node_kickoff_meeting_writes_yaml_to_outputs_dir(tmp_path: Path) -> None:
    """kickoff yaml 이 outputs_dir 루트에 1회 작성됨."""
    state = {
        "user_request": "테스트",
        "spec_markdown": "```yaml\nassumptions:\n  - 가정\n```",
        "outputs_dir": tmp_path.as_posix(),
    }
    IL._node_kickoff_meeting(state)  # type: ignore[arg-type]

    yaml_file = tmp_path / "shared_kickoff_decisions.yaml"
    assert yaml_file.exists(), "shared_kickoff_decisions.yaml 미생성"
    content = yaml_file.read_text(encoding="utf-8")
    assert "user_request" in content
    assert "테스트" in content
    # 한글 escape 없이 보존
    assert "\\u" not in content


def test_node_kickoff_meeting_survives_no_spec(tmp_path: Path) -> None:
    """spec_markdown 누락에도 예외 안 던지고 빈 decisions 반환."""
    state = {
        "user_request": "x",
        "outputs_dir": tmp_path.as_posix(),
    }
    result = IL._node_kickoff_meeting(state)  # type: ignore[arg-type]
    assert isinstance(result["shared_kickoff_decisions"], SharedKickoffDecisions)


# ---------------------------------------------------------------------------
# 3. Graph 조립 — 노드 + 엣지 회귀 차단
# ---------------------------------------------------------------------------


def test_graph_contains_kickoff_meeting_node() -> None:
    """compiled graph 의 nodes 에 kickoff_meeting 포함."""
    graph = IL.build_iterative_loop_graph()
    # LangGraph compiled graph 는 .nodes 또는 .get_graph() 로 노드 확인 가능
    nodes = set(graph.get_graph().nodes.keys())
    assert "kickoff_meeting" in nodes, (
        "graph 에 kickoff_meeting 노드 누락 — PR #138 Phase 1 full 배선 실패"
    )


def test_graph_routes_expand_to_kickoff_then_chain() -> None:
    """expand_requirements → kickoff_meeting → run_chain 순서."""
    graph = IL.build_iterative_loop_graph()
    edges = graph.get_graph().edges

    # edges 는 (source, target) 쌍 — 객체 형식 다양해 dict 가 아닐 수 있음
    edge_pairs = set()
    for edge in edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    assert ("expand_requirements", "kickoff_meeting") in edge_pairs, (
        "expand_requirements → kickoff_meeting edge 누락"
    )
    assert ("kickoff_meeting", "run_chain") in edge_pairs, (
        "kickoff_meeting → run_chain edge 누락"
    )


def test_graph_preserves_iteration_reentry_skips_kickoff() -> None:
    """prepare_feedback → run_chain (kickoff 우회) 그대로 — iteration 재진입 시
    kickoff 가 재실행되지 않아야 함 (회의는 1회만)."""
    graph = IL.build_iterative_loop_graph()
    edges = graph.get_graph().edges
    edge_pairs = set()
    for edge in edges:
        src = getattr(edge, "source", None)
        tgt = getattr(edge, "target", None)
        if src is not None and tgt is not None:
            edge_pairs.add((src, tgt))

    assert ("prepare_feedback", "run_chain") in edge_pairs, (
        "iteration 재진입 edge prepare_feedback → run_chain 누락 — "
        "kickoff 재실행 회피 무력화"
    )
    # kickoff_meeting 으로의 역방향 edge 가 *없어야* 함
    assert ("prepare_feedback", "kickoff_meeting") not in edge_pairs, (
        "prepare_feedback 이 kickoff_meeting 으로 회귀 — 회의가 매 iteration 재실행 "
        "→ 비용 폭증 + 결정 reset 위험"
    )
