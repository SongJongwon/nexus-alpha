# -*- coding: utf-8 -*-
"""
요청 라우터 테스트 (Phase 2-P5).

`route_request` 는 LLM과 무관한 순수 휴리스틱 분류기. 본 테스트는 4가지
의도(IMPLEMENTATION / ANALYSIS / SEARCH / UNKNOWN)와 엣지 케이스를
ms 단위로 검증한다 — FakeProvider 자체에 의존하지 않지만 conftest.py의
autouse fixture는 그대로 적용된다.

실행:
    .venv\\Scripts\\pytest.exe src\\tests\\test_router.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows import Intent, RoutingDecision, route_request


# ---------------------------------------------------------------------------
# 1. 의도별 분류 — 명확한 단일 카테고리 케이스
# ---------------------------------------------------------------------------
def test_route_implementation_strong_signal() -> None:
    """'계산기 만들어줘' 같은 강한 구현형 요청은 IMPLEMENTATION 분류."""
    decision = route_request("계산기 만들어줘. 사칙연산 가능한 Python 코드로.")

    assert decision.intent == Intent.IMPLEMENTATION
    assert decision.confidence >= 0.7  # 다수 매치
    assert decision.recommended_workflow == "analyze_and_implement"
    assert any(kw in {"만들어줘", "만들어", "코드"} for kw in decision.matched_keywords[Intent.IMPLEMENTATION])


def test_route_analysis_strong_signal() -> None:
    """'데이터 분석해서 트렌드 뽑아줘' 같은 분석형은 ANALYSIS."""
    decision = route_request("월별 매출 데이터를 분석해서 트렌드와 지표를 뽑아줘")

    assert decision.intent == Intent.ANALYSIS
    assert decision.confidence >= 0.7
    assert decision.recommended_workflow == "analyze_and_implement"
    assert "분석" in str(decision.matched_keywords[Intent.ANALYSIS])


def test_route_search_strong_signal() -> None:
    """'이전에 만든 X 찾아줘' 같은 검색형은 SEARCH."""
    decision = route_request("이전에 만든 PDF 변환기 찾아줘")

    assert decision.intent == Intent.SEARCH
    assert decision.confidence >= 0.4
    assert decision.recommended_workflow == "knowledge_search"
    assert "이전에" in decision.matched_keywords[Intent.SEARCH]


# ---------------------------------------------------------------------------
# 2. 엣지 케이스
# ---------------------------------------------------------------------------
def test_route_empty_request_is_unknown() -> None:
    """빈 입력은 UNKNOWN, confidence 0.0, workflow None."""
    decision = route_request("")
    assert decision.intent == Intent.UNKNOWN
    assert decision.confidence == 0.0
    assert decision.recommended_workflow is None
    assert "비어 있" in decision.reasoning


def test_route_whitespace_only_is_unknown() -> None:
    """공백만 있는 입력도 UNKNOWN."""
    decision = route_request("   \n   ")
    assert decision.intent == Intent.UNKNOWN
    assert decision.confidence == 0.0


def test_route_no_signal_is_unknown() -> None:
    """카테고리 키워드가 전혀 없는 일반 문장은 UNKNOWN, 도움말 reasoning."""
    decision = route_request("오늘 날씨가 어때")
    assert decision.intent == Intent.UNKNOWN
    assert decision.confidence == 0.0
    assert decision.recommended_workflow is None
    assert "발견되지" in decision.reasoning or "더 구체적" in decision.reasoning


def test_route_tied_signals_are_unknown() -> None:
    """두 카테고리가 동률로 감지되면 UNKNOWN + 충돌 reasoning.

    주의: 동률을 정확히 만들려면 substring 매칭이 누적되지 않는 키워드를 골라야 함.
    "코드"(IMPL) + "차트"(ANAL) 는 각각 1회씩만 매칭되어 정확한 1:1 동률.
    """
    decision = route_request("코드와 차트.")
    assert decision.intent == Intent.UNKNOWN
    assert decision.confidence == 0.3  # 충돌 시 낮은 신뢰도
    assert "동일한 강도" in decision.reasoning or "동률" in decision.reasoning


def test_route_case_insensitive_english() -> None:
    """영문 키워드는 대소문자 무관하게 매칭."""
    decision = route_request("Build a REST API server in Python")
    assert decision.intent == Intent.IMPLEMENTATION
    assert decision.confidence >= 0.4


# ---------------------------------------------------------------------------
# 3. 데이터클래스 구조
# ---------------------------------------------------------------------------
def test_routing_decision_has_required_fields() -> None:
    """RoutingDecision의 모든 필드가 채워지는지 확인."""
    decision = route_request("계산기 만들어줘")
    assert isinstance(decision, RoutingDecision)
    assert isinstance(decision.intent, Intent)
    assert isinstance(decision.confidence, float)
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.recommended_workflow is None or isinstance(decision.recommended_workflow, str)
    assert isinstance(decision.reasoning, str) and decision.reasoning
    assert isinstance(decision.matched_keywords, dict)


def test_intent_enum_values_are_stable() -> None:
    """Intent enum의 값이 documented contract와 일치하는지 (외부 통신 안정성)."""
    assert Intent.IMPLEMENTATION.value == "IMPLEMENTATION"
    assert Intent.ANALYSIS.value == "ANALYSIS"
    assert Intent.SEARCH.value == "SEARCH"
    assert Intent.UNKNOWN.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# 4. 라우팅 후 워크플로우 매핑
# ---------------------------------------------------------------------------
def test_workflow_mapping_implementation_and_analysis_share_chain() -> None:
    """IMPLEMENTATION과 ANALYSIS는 1차 구현에서 동일 워크플로우 (analyze_and_implement) 재사용."""
    impl = route_request("계산기 만들어줘")
    anal = route_request("월별 매출을 분석해줘")
    assert impl.recommended_workflow == "analyze_and_implement"
    assert anal.recommended_workflow == "analyze_and_implement"


def test_workflow_mapping_search_uses_placeholder() -> None:
    """SEARCH는 아직 미구축이므로 placeholder 워크플로우 이름 반환."""
    decision = route_request("이전에 만든 거 찾아줘")
    assert decision.recommended_workflow == "knowledge_search"


def test_workflow_mapping_unknown_returns_none() -> None:
    """UNKNOWN은 디스패치 대상 워크플로우 없음."""
    decision = route_request("뭐 하나")
    assert decision.recommended_workflow is None
