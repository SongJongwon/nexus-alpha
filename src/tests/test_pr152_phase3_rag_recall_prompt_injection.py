# -*- coding: utf-8 -*-
"""PR #152 Phase 3 후속 — RAG recall entries 가 다음 빌드 task prompt 에 *실 주입* 되는지 검증.

배경 (본인 비전 통찰 6 Phase 3 cycle wiring 갭):
    PR #148 (#140) 의 ``_node_recall_past_knowledge`` 는 ``state["recalled_entries"]``
    에 top-3 entry 를 저장만 함 — task description 에 *주입하지 않음*. 결과:

        format_recalled_entries_for_context 호출 위치: 0건 (production), 2건 (테스트만)

    → 다음 빌드 진입 시 *학습 자료를 모음* 했지만 *실제 agent prompt 에는 안 들어감* —
    Phase 3 cycle 의 학습 효과 사실상 0.

PR #152 처방:
    1. ``SharedKickoffDecisions`` 에 ``recalled_knowledge_markdown: str`` 필드 신설
    2. ``_node_kickoff_meeting`` 이 state recalled_entries 를 markdown 변환 후
       decisions 객체에 주입
    3. ``to_kickoff_context_directive`` 가 본 markdown 을 directive 끝에 append
    4. 기존 shared_kickoff_decisions 의 모든 task description 주입 회로 (PR #138)
       가 자동으로 recall 정보를 모든 agent 에게 전달 — wiring 자동 완성

본 테스트:
    - schema: 신규 필드 + yaml round-trip
    - directive: 빈 markdown ↔ 비어있는 directive, 비어 있지 않은 markdown ↔ append
    - kickoff node: state recalled_entries → decisions.recalled_knowledge_markdown
    - 회귀: ``format_recalled_entries_for_context`` 가 production 코드에서 호출됨
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# 1. SharedKickoffDecisions schema — 신규 필드 + 라운드트립
# ---------------------------------------------------------------------------


def test_shared_kickoff_decisions_has_recalled_knowledge_markdown_field() -> None:
    """``SharedKickoffDecisions`` 에 ``recalled_knowledge_markdown`` 필드 존재."""
    from src.agents.coordination.schemas import SharedKickoffDecisions

    decisions = SharedKickoffDecisions(user_request="x", spec_summary="y")
    assert hasattr(decisions, "recalled_knowledge_markdown")
    assert decisions.recalled_knowledge_markdown == ""  # 기본값


def test_shared_kickoff_decisions_yaml_round_trip_preserves_recalled_markdown() -> None:
    """``to_yaml`` → ``from_yaml`` 라운드트립이 recalled markdown 보존."""
    from src.agents.coordination.schemas import SharedKickoffDecisions

    sample_md = "## 🧠 과거 빌드 학습\n- **workflow_2026_05_01** (verdict=COMPLETE)\n"
    original = SharedKickoffDecisions(
        user_request="환율 변환기",
        spec_summary="frankfurter API 사용",
        recalled_knowledge_markdown=sample_md,
    )
    yaml_text = original.to_yaml()
    assert "recalled_knowledge_markdown" in yaml_text
    restored = SharedKickoffDecisions.from_yaml(yaml_text)
    assert restored.recalled_knowledge_markdown == sample_md


def test_shared_kickoff_decisions_from_yaml_handles_missing_field() -> None:
    """기존 yaml (recalled_knowledge_markdown 필드 부재) → 빈 문자열로 복원 (backward compat)."""
    from src.agents.coordination.schemas import SharedKickoffDecisions

    legacy_yaml = (
        "user_request: 계산기\n"
        "spec_summary: tkinter\n"
        "shared_assumptions: []\n"
        "agent_responsibilities: {}\n"
        "open_questions: []\n"
    )
    restored = SharedKickoffDecisions.from_yaml(legacy_yaml)
    assert restored.recalled_knowledge_markdown == ""


# ---------------------------------------------------------------------------
# 2. to_kickoff_context_directive — recalled markdown append
# ---------------------------------------------------------------------------


def test_directive_returns_empty_when_all_fields_empty() -> None:
    """모든 필드 빈 + prior_agent_roles 비어 있음 → directive 빈 문자열 (PR #138 기존 동작 회귀)."""
    from src.agents.coordination.schemas import SharedKickoffDecisions

    empty = SharedKickoffDecisions(user_request="x", spec_summary="y")
    assert empty.to_kickoff_context_directive() == ""


def test_directive_includes_recalled_markdown_when_present() -> None:
    """``recalled_knowledge_markdown`` 만 있어도 directive 가 비지 않고 markdown 포함."""
    from src.agents.coordination.schemas import SharedKickoffDecisions

    decisions = SharedKickoffDecisions(
        user_request="x",
        spec_summary="y",
        recalled_knowledge_markdown=(
            "## 🧠 과거 빌드 학습\n- **workflow_AAA** (verdict=COMPLETE)\n"
        ),
    )
    directive = decisions.to_kickoff_context_directive()
    assert "과거 빌드 학습" in directive
    assert "workflow_AAA" in directive


def test_directive_appends_recalled_markdown_after_kickoff_section() -> None:
    """kickoff 합의 + recalled markdown 둘 다 있을 때 — recalled 가 *뒤* 에 append."""
    from src.agents.coordination.schemas import (
        SharedAssumption,
        SharedKickoffDecisions,
    )

    decisions = SharedKickoffDecisions(
        user_request="환율 변환기",
        spec_summary="frankfurter API",
        shared_assumptions=[
            SharedAssumption(
                id="A1",
                decision="frankfurter API 사용",
                rationale="실시간 환율 필수",
                owner="CTO",
            ),
        ],
        recalled_knowledge_markdown=(
            "## 🧠 과거 빌드 학습\n- **workflow_BBB** (verdict=BLOCKED)\n"
        ),
    )
    directive = decisions.to_kickoff_context_directive()
    kickoff_pos = directive.find("킥오프 회의 합의 사항")
    recall_pos = directive.find("과거 빌드 학습")
    assert kickoff_pos != -1 and recall_pos != -1
    assert recall_pos > kickoff_pos, (
        "recalled markdown 이 kickoff 합의 *앞* 에 위치 — append 순서 회귀"
    )


# ---------------------------------------------------------------------------
# 3. _node_kickoff_meeting — state recalled_entries → decisions markdown
# ---------------------------------------------------------------------------


def _make_fake_entry(workflow_id: str, verdict: str = "COMPLETE"):
    """``KnowledgeEntry`` duck-type — recall 산출 stub."""
    from src.agents.knowledge.schemas import KnowledgeEntry

    return KnowledgeEntry(
        workflow_id=workflow_id,
        user_request_oneline="이전 요청",
        qa_verdict=verdict,
        summary="이전 빌드 요약",
        tags=["recall-test"],
        curated_at="2026-05-15",
    )


def test_kickoff_node_populates_recalled_markdown_from_state(
    monkeypatch, tmp_path: Path
) -> None:
    """state.recalled_entries 가 있으면 decisions.recalled_knowledge_markdown 채움."""
    from src.workflows import iterative_loop as IL

    # run_kickoff_meeting stub — Meeting Facilitator LLM 호출 회피
    from src.agents.coordination.schemas import SharedKickoffDecisions

    def _stub_meeting(*, user_request, spec_markdown):
        return SharedKickoffDecisions(
            user_request=user_request,
            spec_summary="stub summary",
        )

    monkeypatch.setattr(IL, "run_kickoff_meeting", _stub_meeting)

    entries = [_make_fake_entry("workflow_X"), _make_fake_entry("workflow_Y")]
    state: dict[str, Any] = {
        "user_request": "환율 변환기",
        "spec_markdown": "",
        "outputs_dir": tmp_path,
        "recalled_entries": entries,
    }

    out = IL._node_kickoff_meeting(state)
    decisions = out["shared_kickoff_decisions"]
    assert decisions.recalled_knowledge_markdown != ""
    assert "workflow_X" in decisions.recalled_knowledge_markdown
    assert "workflow_Y" in decisions.recalled_knowledge_markdown


def test_kickoff_node_leaves_markdown_empty_when_no_recall(
    monkeypatch, tmp_path: Path
) -> None:
    """state.recalled_entries 비어 있으면 markdown 빈 문자열 (첫 빌드 호환)."""
    from src.workflows import iterative_loop as IL

    from src.agents.coordination.schemas import SharedKickoffDecisions

    def _stub_meeting(*, user_request, spec_markdown):
        return SharedKickoffDecisions(
            user_request=user_request,
            spec_summary="stub",
        )

    monkeypatch.setattr(IL, "run_kickoff_meeting", _stub_meeting)

    state: dict[str, Any] = {
        "user_request": "x",
        "spec_markdown": "",
        "outputs_dir": tmp_path,
        # recalled_entries 키 부재 — 첫 빌드 시나리오
    }
    out = IL._node_kickoff_meeting(state)
    decisions = out["shared_kickoff_decisions"]
    assert decisions.recalled_knowledge_markdown == ""


def test_kickoff_node_writes_recalled_md_into_yaml_file(
    monkeypatch, tmp_path: Path
) -> None:
    """디스크 ``shared_kickoff_decisions.yaml`` 에 recalled markdown 도 포함 (회고/감사)."""
    from src.workflows import iterative_loop as IL

    from src.agents.coordination.schemas import SharedKickoffDecisions

    def _stub_meeting(*, user_request, spec_markdown):
        return SharedKickoffDecisions(user_request=user_request, spec_summary="x")

    monkeypatch.setattr(IL, "run_kickoff_meeting", _stub_meeting)

    state: dict[str, Any] = {
        "user_request": "x",
        "spec_markdown": "",
        "outputs_dir": tmp_path,
        "recalled_entries": [_make_fake_entry("workflow_Z")],
    }
    IL._node_kickoff_meeting(state)

    yaml_text = (tmp_path / "shared_kickoff_decisions.yaml").read_text(encoding="utf-8")
    assert "recalled_knowledge_markdown" in yaml_text
    assert "workflow_Z" in yaml_text


# ---------------------------------------------------------------------------
# 4. 회귀 — format_recalled_entries_for_context 가 production 코드에서 호출됨
# ---------------------------------------------------------------------------


def test_format_recalled_entries_called_from_iterative_loop() -> None:
    """``format_recalled_entries_for_context`` 가 ``iterative_loop.py`` 에서 import + 호출.

    PR #152 회귀 차단 — 본 wiring 이 제거되면 다시 PR #148 의 "저장만 함" 갭으로 회귀.
    """
    src = (
        Path(__file__).resolve().parent.parent.parent
        / "src" / "workflows" / "iterative_loop.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "format_recalled_entries_for_context" in text, (
        "iterative_loop.py 가 format_recalled_entries_for_context 호출 안 함 — "
        "PR #148 의 'recall 저장만' 갭 회귀"
    )


def test_directive_injection_flows_end_to_end() -> None:
    """종단 검증 — entries 가 directive 텍스트에 들어가는지 (전체 pipeline 1줄).

    이 한 줄이 통과하면:
      recall_past_entries → format_recalled_entries_for_context → kickoff_meeting →
      decisions.recalled_knowledge_markdown → to_kickoff_context_directive → task description
    체인 전체가 회로상으로 연결되어 있음을 보장.
    """
    from src.agents.coordination.schemas import SharedKickoffDecisions
    from src.agents.knowledge import format_recalled_entries_for_context

    entries = [_make_fake_entry("workflow_E2E")]
    md = format_recalled_entries_for_context(entries)
    decisions = SharedKickoffDecisions(
        user_request="x",
        spec_summary="y",
        recalled_knowledge_markdown=md,
    )
    directive = decisions.to_kickoff_context_directive()
    assert "workflow_E2E" in directive, (
        "End-to-end: recall entries → kickoff decisions → directive 주입 회로 끊김"
    )
