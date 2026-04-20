# -*- coding: utf-8 -*-
"""
Nexus Alpha 요청 라우터 (Phase 2-P5).

사용자의 자연어 요청을 받아 **어떤 워크플로우로 보낼지** 결정하는 라우팅
계층. 4가지 의도(intent)로 분류한다:

    IMPLEMENTATION (구현형) — "계산기 만들어줘", "파일 변환 스크립트"
        → `analyze_and_implement` 4-agent 워크플로우

    ANALYSIS (분석형) — "이 데이터 분석해줘", "지표 뽑아줘"
        → `analyze_and_implement` (Data Analyst가 핵심 단계 담당)

    SEARCH (검색형) — "이전에 비슷한 거 했나?", "기존 산출물 검색"
        → `knowledge_search` (RAG Searcher 기반, 별도 워크플로우는 차후 구축)

    UNKNOWN — 신호 부재 또는 충돌
        → CLI가 명확화 질문을 사용자에게 제시

설계 원칙:
    - **순수 휴리스틱(LLM 무관)**: 라우팅 자체에 LLM 호출은 사용자 경험 지연을
      만들고 결정론적 테스트가 어려워진다. 키워드 카운트 기반 단순 분류로
      충분하다.
    - **3가지 신호 축**: 구현 동사(`만들어줘`/`구현`/`작성`) · 분석 명사
      (`분석`/`지표`/`트렌드`) · 검색 단서(`이전에`/`기존`/`찾아줘`).
    - **UNKNOWN 친화적**: 모호하면 강제로 분류하지 않고 사용자에게 되돌린다.
      잘못된 라우팅은 사용자 시간을 더 낭비한다.
    - **확장 경로**: 모호 케이스에 LLM Router fallback을 끼우는 것은 v3
      도입 시 자연스럽게 추가 가능. 본 모듈의 공개 API(`route_request`)는
      그대로 유지.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Intent enum + 결정 데이터클래스
# ---------------------------------------------------------------------------
class Intent(str, Enum):
    """사용자 요청의 분류된 의도."""

    IMPLEMENTATION = "IMPLEMENTATION"
    ANALYSIS = "ANALYSIS"
    SEARCH = "SEARCH"
    UNKNOWN = "UNKNOWN"


@dataclass
class RoutingDecision:
    """`route_request` 의 구조화 산출물.

    Attributes:
        intent: 분류된 의도 (Intent enum).
        confidence: 0.0~1.0 신뢰도. 단일 약한 신호는 ~0.4, 다수 강한 신호는 ~0.9.
        recommended_workflow: 디스패치 대상 워크플로우 이름.
            - IMPLEMENTATION/ANALYSIS → "analyze_and_implement"
            - SEARCH → "knowledge_search" (실제 워크플로우 미구축, placeholder)
            - UNKNOWN → None
        reasoning: 사람이 읽을 수 있는 분류 근거 한 문장.
        matched_keywords: 카테고리별 매칭된 키워드 목록.
            UI에서 "이런 단어가 보여서 X로 분류했어요" 형태로 보여주기 위함.
    """

    intent: Intent
    confidence: float
    recommended_workflow: Optional[str]
    reasoning: str
    matched_keywords: dict[Intent, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 휴리스틱 키워드 사전 (한국어 우선 + 영문 보조)
# ---------------------------------------------------------------------------
# 각 카테고리의 강한 신호 키워드. 부분 문자열 일치(case-insensitive).
# "강한"의 기준: 다른 카테고리와 거의 겹치지 않고, 그 카테고리만의 특징적 표현.
_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.IMPLEMENTATION: (
        # 구현 동사
        "만들어줘", "만들어", "구현해", "구현", "작성해", "작성",
        "짜줘", "짜서", "생성해", "개발",
        # 산출물 명사
        "코드", "스크립트", "프로그램", "앱", "어플", "애플리케이션",
        "함수", "클래스", "모듈", "패키지", "라이브러리",
        "cli", "gui", "rest api", "api 서버", ".py", ".exe",
        # 영문 동사
        "build", "implement", "create", "write", "code",
    ),
    Intent.ANALYSIS: (
        # 분석 동사
        "분석해", "분석", "분석해줘", "살펴봐", "뽑아줘", "정리해",
        # 분석 명사
        "지표", "kpi", "통계", "트렌드", "패턴", "추세",
        "차트", "시각화", "그래프", "대시보드", "리포트", "보고서",
        "eda", "탐색적 분석", "데이터 품질", "이상치",
        # 영문 동사·명사
        "analyze", "analysis", "stats", "metric", "metrics", "trend", "dashboard",
    ),
    Intent.SEARCH: (
        # 시점 단서
        "이전에", "기존에", "전에 했던", "이미 만든", "지난번",
        "예전", "과거", "예전에",
        # 검색 동사
        "찾아줘", "찾아봐", "검색해", "조회해",
        # 비교 단서
        "비슷한", "유사한", "참고할 만한",
        # 영문
        "search", "lookup", "find existing", "previous", "history",
    ),
}


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def route_request(request: str) -> RoutingDecision:
    """사용자 요청을 분류해 `RoutingDecision` 을 반환한다.

    분류 절차:
        1. 빈 입력 → UNKNOWN (confidence=0.0).
        2. 카테고리별 키워드 매칭 카운트.
        3. 최고 카운트 카테고리를 후보로 선정.
        4. 1·2위가 동률이거나 둘 다 0이면 UNKNOWN.
        5. confidence 는 (해당 카테고리 매치 수 / 전체 매치 수) 와
           (매치 수가 1개면 0.4, 2개면 0.7, 3개+면 0.9) 의 minimum.

    Args:
        request: 사용자 자연어 요청.

    Returns:
        분류 결과를 담은 `RoutingDecision`. 라우팅이 결정되면 confidence>0,
        UNKNOWN 이면 confidence=0.0 또는 낮은 값.

    Note:
        본 함수는 LLM을 호출하지 않는다. 따라서 네트워크 없이 ms 단위로 동작.
        UI는 결과를 받아 즉시 사용자에게 의도 확인을 보여줄 수 있다.
    """
    text = (request or "").strip().lower()
    if not text:
        return RoutingDecision(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            recommended_workflow=None,
            reasoning="입력이 비어 있어 의도를 판단할 수 없습니다.",
            matched_keywords={},
        )

    # 카테고리별 매치 수집
    matched: dict[Intent, list[str]] = {intent: [] for intent in _KEYWORDS}
    for intent, keywords in _KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched[intent].append(kw)

    # 카운트 정렬 (내림차순)
    counts = sorted(
        ((intent, len(kws)) for intent, kws in matched.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    top_intent, top_count = counts[0]
    second_count = counts[1][1]

    # 신호 부재
    if top_count == 0:
        return RoutingDecision(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            recommended_workflow=None,
            reasoning=(
                "구현·분석·검색 어느 신호도 발견되지 않았습니다. "
                "더 구체적으로 말씀해 주세요 (예: '<무엇>을 만들어줘' / "
                "'<무엇>을 분석해줘' / '이전에 한 <무엇>을 찾아줘')."
            ),
            matched_keywords={k: v for k, v in matched.items() if v},
        )

    # 신호 충돌 (1·2위 동률 + 양쪽 다 1개 이상)
    if top_count == second_count and top_count > 0:
        tied = [intent.value for intent, c in counts if c == top_count]
        return RoutingDecision(
            intent=Intent.UNKNOWN,
            confidence=0.3,
            recommended_workflow=None,
            reasoning=(
                f"두 의도({', '.join(tied)})가 동일한 강도로 감지되었습니다. "
                "어느 쪽을 원하시는지 명확히 알려 주세요."
            ),
            matched_keywords={k: v for k, v in matched.items() if v},
        )

    # 단일 우세 카테고리 결정
    confidence = _score_confidence(top_count)
    workflow = _intent_to_workflow(top_intent)
    reasoning = (
        f"'{top_intent.value}' 신호 키워드 {top_count}건 매칭: "
        f"{', '.join(matched[top_intent][:3])}"
        f"{' 외' if top_count > 3 else ''}"
    )
    return RoutingDecision(
        intent=top_intent,
        confidence=confidence,
        recommended_workflow=workflow,
        reasoning=reasoning,
        matched_keywords={k: v for k, v in matched.items() if v},
    )


def _score_confidence(match_count: int) -> float:
    """매치 수에 따른 confidence 산정 (단순 단계 함수)."""
    if match_count >= 3:
        return 0.9
    if match_count == 2:
        return 0.7
    return 0.4


def _intent_to_workflow(intent: Intent) -> Optional[str]:
    """의도 → 디스패치 대상 워크플로우 이름 매핑."""
    mapping: dict[Intent, str] = {
        Intent.IMPLEMENTATION: "analyze_and_implement",
        Intent.ANALYSIS: "analyze_and_implement",  # 1차에는 동일 체인 재사용
        Intent.SEARCH: "knowledge_search",  # placeholder — 실제 워크플로우 미구축
    }
    return mapping.get(intent)
