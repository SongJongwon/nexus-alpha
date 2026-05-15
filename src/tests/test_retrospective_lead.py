# -*- coding: utf-8 -*-
"""PR #149 — Retrospective Lead 단위 테스트.

배경 (본인 비전 통찰 6, D-5 처방 + Phase 3 cycle 완성):
    PR #148 의 Knowledge Curator 는 코드 본문에서 평면적 정보로 summary/tags 채움.
    Retrospective Lead 가 매 빌드 종료 시 4단 회고 산출 → Curator prompt 입력으로
    추가 → entry 가 *결함/성공 패턴* 으로 풍부해짐.

본 테스트 목적:
    - RetrospectiveReport yaml/markdown 라운드트립
    - _detect_delta_from_kickoff: kickoff 결정 ↔ 산출물 불일치 자동 검출 (환율 사례)
    - _parse_retrospective_json: LLM 응답 파싱 (다양한 형식 + 깨진 입력)
    - run_retrospective: 결정론 골격 + 1 LLM call + pytest 자동 skip + 실패 격리
"""

from __future__ import annotations

from src.agents.coordination import (
    RetrospectiveReport,
    SharedAssumption,
    SharedKickoffDecisions,
    run_retrospective,
)
from src.agents.coordination.retrospective_lead import (
    _detect_delta_from_kickoff,
    _parse_retrospective_json,
)


# ---------------------------------------------------------------------------
# 1. RetrospectiveReport yaml/markdown 직렬화
# ---------------------------------------------------------------------------


def test_retrospective_yaml_roundtrip() -> None:
    """to_yaml → from_yaml 모든 필드 보존."""
    original = RetrospectiveReport(
        workflow_id="workflow_20260515_120000",
        verdict="COMPLETE",
        what_went_well=["frankfurter API 통합 안정", "Vision QA 통과"],
        what_went_wrong=["timeout 5s 부족"],
        lessons_learned=["timeout 10s 로 늘려야"],
        delta_from_kickoff=["currency_data_source: 킥오프 vs 산출 일치"],
    )
    restored = RetrospectiveReport.from_yaml(original.to_yaml())
    assert restored.workflow_id == original.workflow_id
    assert restored.verdict == "COMPLETE"
    assert restored.what_went_well == original.what_went_well
    assert restored.lessons_learned == original.lessons_learned


def test_retrospective_markdown_includes_all_4_sections() -> None:
    """markdown 에 4 섹션 헤더 모두 포함."""
    r = RetrospectiveReport(workflow_id="w_x", verdict="COMPLETE")
    text = r.to_markdown()
    assert "What went well" in text
    assert "What went wrong" in text
    assert "Lessons learned" in text
    assert "Delta from kickoff" in text


def test_retrospective_markdown_shows_empty_marker() -> None:
    """카테고리 비어 있으면 ``(없음)`` marker 출력 — 빈 상태 명시."""
    r = RetrospectiveReport(workflow_id="w_x", verdict="COMPLETE")
    text = r.to_markdown()
    assert "(없음)" in text


def test_retrospective_yaml_preserves_korean() -> None:
    """한글 escape 없이 보존."""
    r = RetrospectiveReport(
        workflow_id="w_x", verdict="COMPLETE",
        what_went_well=["환율 변환 정상 동작"],
    )
    text = r.to_yaml()
    assert "환율" in text
    assert "\\u" not in text


# ---------------------------------------------------------------------------
# 2. _detect_delta_from_kickoff — 킥오프 vs 산출 불일치 자동 검출
# ---------------------------------------------------------------------------


def _make_kickoff(decision_text: str = "frankfurter API 실시간 호출") -> SharedKickoffDecisions:
    return SharedKickoffDecisions(
        user_request="환율 변환기",
        spec_summary="USD/KRW 환율 변환",
        shared_assumptions=[
            SharedAssumption(
                id="currency_data_source",
                decision=decision_text,
                rationale="stale 데이터 차단",
                owner="CTO",
            )
        ],
    )


class _FakeChain:
    def __init__(self, engineer_output: str = "", gui_code_output: str = ""):
        self.engineer_output = engineer_output
        self.gui_code_output = gui_code_output


def test_delta_returns_empty_when_no_kickoff() -> None:
    """kickoff 부재 시 빈 리스트."""
    assert _detect_delta_from_kickoff(None, _FakeChain("anything"), "") == []


def test_delta_detects_missing_keyword_in_output() -> None:
    """킥오프 결정의 키워드가 산출물에 없으면 delta 검출 (환율 사례 evidence)."""
    kickoff = _make_kickoff("frankfurter API 실시간 호출")
    # Engineer 가 frankfurter 안 부르고 정적 dict 사용한 케이스 — 환율 사례 재현
    chain = _FakeChain(engineer_output="EXCHANGE_RATES = {'USD': 1365.5}")

    deltas = _detect_delta_from_kickoff(kickoff, chain, qa_review="")
    assert len(deltas) >= 1
    assert "currency_data_source" in deltas[0]


def test_delta_finds_no_issue_when_keyword_present() -> None:
    """킥오프 키워드가 산출물에 있으면 delta 없음."""
    kickoff = _make_kickoff("frankfurter API 실시간 호출")
    chain = _FakeChain(
        engineer_output="import requests\nrate = requests.get('https://frankfurter.app/...')"
    )
    deltas = _detect_delta_from_kickoff(kickoff, chain, qa_review="")
    assert deltas == []


def test_delta_caps_at_3_items() -> None:
    """delta 3개 이내 — actionable insight 유지 위해 길이 cap."""
    kickoff = SharedKickoffDecisions(
        user_request="x", spec_summary="",
        shared_assumptions=[
            SharedAssumption(
                id=f"id_{i}",
                decision=f"unique_keyword_{i} required",
                rationale="r",
                owner="x",
            )
            for i in range(10)
        ],
    )
    chain = _FakeChain(engineer_output="empty output")
    deltas = _detect_delta_from_kickoff(kickoff, chain, qa_review="")
    assert len(deltas) <= 3


# ---------------------------------------------------------------------------
# 3. _parse_retrospective_json — LLM 응답 파싱
# ---------------------------------------------------------------------------


def test_parse_plain_json() -> None:
    """순수 JSON 응답 처리."""
    text = (
        '{"what_went_well": ["a"], "what_went_wrong": ["b"], '
        '"lessons_learned": ["c"]}'
    )
    parsed = _parse_retrospective_json(text)
    assert parsed["what_went_well"] == ["a"]
    assert parsed["what_went_wrong"] == ["b"]
    assert parsed["lessons_learned"] == ["c"]


def test_parse_json_with_fence() -> None:
    """```json 펜스 안 JSON 처리."""
    text = (
        "설명...\n```json\n"
        '{"what_went_well": ["good"], "what_went_wrong": [], "lessons_learned": ["learn"]}'
        "\n```"
    )
    parsed = _parse_retrospective_json(text)
    assert parsed.get("what_went_well") == ["good"]


def test_parse_returns_empty_on_malformed() -> None:
    """깨진 JSON 입력 시 빈 dict."""
    assert _parse_retrospective_json("그냥 자연어 응답") == {}
    assert _parse_retrospective_json("") == {}


def test_parse_caps_each_category_at_3() -> None:
    """각 카테고리 3개 이내 cap."""
    text = (
        '{"what_went_well": ["a", "b", "c", "d", "e"], '
        '"what_went_wrong": [], "lessons_learned": []}'
    )
    parsed = _parse_retrospective_json(text)
    assert len(parsed["what_went_well"]) <= 3


# ---------------------------------------------------------------------------
# 4. run_retrospective — 진입점
# ---------------------------------------------------------------------------


def test_run_retrospective_returns_report_with_deterministic_skeleton() -> None:
    """pytest 환경에서 LLM skip → workflow_id + verdict + (가능하면) delta 만."""
    kickoff = _make_kickoff("frankfurter API")
    chain = _FakeChain(engineer_output="static_dict = {}")

    report = run_retrospective(
        user_request="환율 변환기",
        workflow_id="w_test",
        verdict="COMPLETE",
        shared_kickoff_decisions=kickoff,
        chain_result=chain,
    )
    assert isinstance(report, RetrospectiveReport)
    assert report.workflow_id == "w_test"
    assert report.verdict == "COMPLETE"
    # delta 자동 검출 — 킥오프의 frankfurter 키워드가 산출물에 없음
    assert len(report.delta_from_kickoff) >= 1


def test_run_retrospective_auto_promotes_delta_to_what_went_wrong() -> None:
    """delta 가 자동 검출됐는데 LLM 이 wrong 못 채우면, delta 가 wrong 으로 promote."""
    kickoff = _make_kickoff("frankfurter API")
    chain = _FakeChain(engineer_output="static dict")

    report = run_retrospective(
        user_request="x", workflow_id="w", verdict="BLOCKED",
        shared_kickoff_decisions=kickoff, chain_result=chain,
        llm_call=None,  # pytest 환경 = LLM skip
    )
    # delta 있는데 wrong 비어 있을 수 없음 — 자동 promote
    assert len(report.what_went_wrong) >= 1


def test_run_retrospective_uses_injected_llm() -> None:
    """외부 llm_call 주입 시 well/wrong/lessons 채움."""
    fake_response = (
        '{"what_went_well": ["frankfurter 정상"], '
        '"what_went_wrong": ["timeout 짧음"], '
        '"lessons_learned": ["timeout 10s 로 설정"]}'
    )

    def fake_llm(prompt: str) -> str:
        return fake_response

    report = run_retrospective(
        user_request="환율", workflow_id="w", verdict="COMPLETE",
        chain_result=_FakeChain("ok"), llm_call=fake_llm,
    )
    assert report.what_went_well == ["frankfurter 정상"]
    assert report.lessons_learned == ["timeout 10s 로 설정"]


def test_run_retrospective_survives_llm_exception() -> None:
    """LLM 예외 시 결정론 골격만 반환 — 워크플로 차단 X."""

    def boom(prompt: str) -> str:
        raise RuntimeError("LLM down")

    report = run_retrospective(
        user_request="x", workflow_id="w", verdict="COMPLETE",
        chain_result=_FakeChain("ok"), llm_call=boom,
    )
    assert report.workflow_id == "w"
    # well/wrong/lessons 빈 채로 정상 반환
    assert report.what_went_well == []
    assert report.what_went_wrong == []


def test_run_retrospective_handles_no_chain_result() -> None:
    """chain_result=None 도 예외 없이 reports 반환."""
    report = run_retrospective(
        user_request="x", workflow_id="w", verdict="BLOCKED",
        chain_result=None,
    )
    assert isinstance(report, RetrospectiveReport)
