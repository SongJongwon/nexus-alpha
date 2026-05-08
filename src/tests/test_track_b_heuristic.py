# -*- coding: utf-8 -*-
"""Track B 휴리스틱 분류 개선 회귀 방지 테스트 (PR #80).

배경 (PR #79 5 도메인 sample 검증에서 발견):
    "FastAPI Docker 배포 파이프라인" → API_INTEGRATION 으로 오분류.
    원인: ``fastapi`` 안의 ``api`` 부분문자열이 도매로 1점 추가 →
    API: fastapi(1)+api(1)=2 vs DEVOPS: docker(1)=1 → API 승.

PR #80 처방:
    1. 3 tier 가중치 (STRONG=3 / MEDIUM=2 / WEAK=1)
    2. 짧은 모호 영어 키워드 (``api``, ``pdf``, ``csv``, ``json``, ``docker``)
       은 단어 경계 (``\\bword\\b``) 매칭
    3. 가중치 동률 시 LLM fallback (pytest gating)

본 테스트는 LLM 호출 없는 정적·결정론적 검증만 — 풀체인 PASS 검증은 PR #80
머지 후 devops 재검증에서.
"""

from __future__ import annotations

import pytest

from src.workflows.automate_workflow import (
    AutomationDomain,
    _DOMAIN_KEYWORDS,
    _keyword_matches,
    _llm_classify_domain,
    detect_automation_domain,
)


# ---------------------------------------------------------------------------
# 1. _keyword_matches 헬퍼 — word_boundary 동작 검증
# ---------------------------------------------------------------------------


def test_keyword_matches_substring_default() -> None:
    """word_boundary=False 는 단순 부분문자열 매칭."""
    assert _keyword_matches("fastapi docker", "fastapi", False) is True
    assert _keyword_matches("크롤링 스크립트", "크롤링", False) is True
    assert _keyword_matches("foo bar", "baz", False) is False


def test_keyword_matches_word_boundary_blocks_substring_match() -> None:
    """word_boundary=True 는 ``api`` 가 ``fastapi`` 안에서 매칭 안 됨."""
    # PR #80 핵심 회귀 차단
    assert _keyword_matches("fastapi docker", "api", True) is False
    # 같은 단어 경계 검사 — ``api`` 가 단독으로 등장해야 매칭
    assert _keyword_matches("github api 호출", "api", True) is True
    assert _keyword_matches("api 연동", "api", True) is True


def test_keyword_matches_word_boundary_handles_punctuation() -> None:
    """ ``-`` `,` 같은 비-단어 문자도 단어 경계로 인식."""
    # docker-compose 안의 docker 는 매칭 (하이픈은 단어 경계)
    assert _keyword_matches("docker-compose 로", "docker", True) is True
    # csv. 안의 csv 매칭
    assert _keyword_matches("data.csv 파일", "csv", True) is True
    # 그러나 csvfile 안의 csv 는 매칭 안 됨
    assert _keyword_matches("csvfile reader", "csv", True) is False


# ---------------------------------------------------------------------------
# 2. PR #79 회귀 사례 — devops 오분류 fix
# ---------------------------------------------------------------------------


def test_fastapi_docker_deployment_classifies_as_devops() -> None:
    """PR #79 발견 — "FastAPI Docker 배포 파이프라인" 이 DEVOPS 로 분류 (PR #80 fix).

    가중치 합산:
        - API_INTEGRATION: fastapi(strong=3) + api(weak=1, 단어경계 — fastapi
          안에서 매칭 안 됨) = 3
        - DEVOPS: docker(weak=2, 단어경계) + 배포 파이프라인(strong=3) = 5
        → DEVOPS 승 (5 > 3)
    """
    result = detect_automation_domain(
        "FastAPI Docker 배포 파이프라인", allow_llm_fallback=False
    )
    assert result is AutomationDomain.DEVOPS, (
        f"PR #79 회귀 사례 fix 실패 — {result.value} (예상 devops)"
    )


def test_fastapi_alone_still_classifies_as_api_integration() -> None:
    """반례 검증 — 순수 ``fastapi`` 만 등장하면 여전히 API_INTEGRATION."""
    result = detect_automation_domain(
        "FastAPI 로 webhook endpoint 작성", allow_llm_fallback=False
    )
    assert result is AutomationDomain.API_INTEGRATION


# ---------------------------------------------------------------------------
# 3. 가중치 차등 — STRONG vs WEAK
# ---------------------------------------------------------------------------


def test_strong_keyword_beats_multiple_weak_keywords() -> None:
    """STRONG 키워드 1개 (3점) > WEAK 키워드 2개 (2점)."""
    # WEB: playwright(strong=3) = 3
    # DATA: pdf(weak=1) + json(weak=1) = 2
    result = detect_automation_domain(
        "playwright 사용 + pdf 와 json 산출", allow_llm_fallback=False
    )
    assert result is AutomationDomain.WEB_SCRAPING


def test_medium_keyword_beats_weak_keyword() -> None:
    """MEDIUM 키워드 (2점) > WEAK 키워드 (1점)."""
    # DATA: 엑셀(medium=2) = 2
    # API: api(weak=1, 단어 경계 — 'api 명세'에서 매칭) = 1
    result = detect_automation_domain(
        "엑셀 데이터 분석 + api 명세", allow_llm_fallback=False
    )
    assert result is AutomationDomain.DATA_PARSER


# ---------------------------------------------------------------------------
# 4. 기존 5 도메인 분류 회귀 (test_automate_workflow.py 와 일치 — backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text, expected_domain",
    [
        ("네이버 쇼핑 가격 크롤링 스크립트", AutomationDomain.WEB_SCRAPING),
        ("Playwright 로 동적 페이지 스크래핑", AutomationDomain.WEB_SCRAPING),
        ("Selenium 으로 로그인 자동 후 데이터 수집해", AutomationDomain.WEB_SCRAPING),
        ("PyAutoGUI 로 엑셀 자동 입력", AutomationDomain.DESKTOP_AUTOMATION),
        ("PyWinAuto 로 outlook 자동화", AutomationDomain.DESKTOP_AUTOMATION),
        ("Excel 자동 입력 RPA 스크립트", AutomationDomain.DESKTOP_AUTOMATION),
        ("Slack webhook 으로 알림 보내기", AutomationDomain.API_INTEGRATION),
        ("Stripe API OAuth 인증 연동", AutomationDomain.API_INTEGRATION),
        ("GitHub API 이슈 자동 생성 스크립트", AutomationDomain.API_INTEGRATION),
        ("엑셀 파일 분석 PDF 보고서 변환", AutomationDomain.DATA_PARSER),
        ("openpyxl 로 .xlsx 파싱", AutomationDomain.DATA_PARSER),
        ("pdfplumber 로 PDF 테이블 추출", AutomationDomain.DATA_PARSER),
        ("한글 Excel 파일 파싱 스크립트", AutomationDomain.DATA_PARSER),
        ("Dockerfile multi-stage 빌드 작성", AutomationDomain.DEVOPS),
        ("GitHub Actions CI/CD 파이프라인", AutomationDomain.DEVOPS),
        ("docker-compose 로 멀티 서비스 구성", AutomationDomain.DEVOPS),
        (
            "Docker multi-stage Dockerfile GitHub Actions CI/CD 워크플로 작성",
            AutomationDomain.DEVOPS,
        ),
    ],
)
def test_existing_5_domain_classifications_still_pass(
    request_text, expected_domain
) -> None:
    """PR #75/#79 검증된 5 도메인 sample request 모두 기존 분류 유지."""
    result = detect_automation_domain(request_text, allow_llm_fallback=False)
    assert result is expected_domain, (
        f"{request_text!r} → {result.value} (예상 {expected_domain.value})"
    )


# ---------------------------------------------------------------------------
# 5. UNKNOWN — 매칭 0건 + 동률 (LLM fallback 비활성)
# ---------------------------------------------------------------------------


def test_empty_or_blank_returns_unknown() -> None:
    assert detect_automation_domain("", allow_llm_fallback=False) is AutomationDomain.UNKNOWN
    assert detect_automation_domain("   ", allow_llm_fallback=False) is AutomationDomain.UNKNOWN
    assert (
        detect_automation_domain(None, allow_llm_fallback=False)  # type: ignore[arg-type]
        is AutomationDomain.UNKNOWN
    )


def test_no_keyword_match_returns_unknown() -> None:
    """매칭 0건 → UNKNOWN (Track A fallback 신호)."""
    assert (
        detect_automation_domain("사칙연산 계산기 만들어줘", allow_llm_fallback=False)
        is AutomationDomain.UNKNOWN
    )


def test_tied_score_returns_unknown_when_llm_fallback_disabled() -> None:
    """가중치 동률 + allow_llm_fallback=False → UNKNOWN.

    overlap 없는 키워드로 인위적 동률 — playwright(strong=3) + multi-stage(strong=3).
    """
    text = "playwright + multi-stage 환경"
    assert (
        detect_automation_domain(text, allow_llm_fallback=False)
        is AutomationDomain.UNKNOWN
    )


# ---------------------------------------------------------------------------
# 6. LLM fallback — pytest 환경 gating (None 반환)
# ---------------------------------------------------------------------------


def test_llm_classify_domain_returns_none_under_pytest() -> None:
    """pytest 환경에선 LLM 호출 우회 → None 반환 (FakeProvider 호환)."""
    result = _llm_classify_domain(
        "ambiguous request",
        [AutomationDomain.WEB_SCRAPING, AutomationDomain.DEVOPS],
    )
    assert result is None


def test_detect_with_default_allow_llm_fallback_returns_unknown_for_tie_under_pytest() -> None:
    """default allow_llm_fallback=True 라도 pytest 환경에선 LLM 우회 → UNKNOWN."""
    text = "playwright + multi-stage 환경"
    # default 인자 (True) 시도해도 pytest 환경 → LLM None → UNKNOWN
    assert detect_automation_domain(text) is AutomationDomain.UNKNOWN


# ---------------------------------------------------------------------------
# 7. _DOMAIN_KEYWORDS 데이터 무결성
# ---------------------------------------------------------------------------


def test_all_5_domains_have_keywords() -> None:
    """5 도메인 (UNKNOWN 제외) 모두 키워드 정의."""
    expected = {
        AutomationDomain.WEB_SCRAPING,
        AutomationDomain.DESKTOP_AUTOMATION,
        AutomationDomain.API_INTEGRATION,
        AutomationDomain.DATA_PARSER,
        AutomationDomain.DEVOPS,
    }
    assert set(_DOMAIN_KEYWORDS.keys()) == expected
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        assert len(keywords) > 0, f"{domain.value} 키워드 비어있음"


def test_keyword_tuple_format_is_consistent() -> None:
    """모든 키워드가 (str, int, bool) 3 tuple — weight ∈ {1,2,3}."""
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for entry in keywords:
            assert isinstance(entry, tuple)
            assert len(entry) == 3
            kw, weight, word_boundary = entry
            assert isinstance(kw, str) and len(kw) > 0
            assert isinstance(weight, int) and 1 <= weight <= 3
            assert isinstance(word_boundary, bool)


def test_short_english_ambiguous_keywords_use_word_boundary() -> None:
    """짧은 모호 영어 키워드 (``api``, ``pdf``, ``csv``, ``json``, ``docker``) 는
    word_boundary=True 로 정의돼야 회귀 차단."""
    must_have_word_boundary = {"api", "pdf", "csv", "json", "docker", "k8s", "url",
                               "http", "https"}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw, _, word_boundary in keywords:
            if kw in must_have_word_boundary:
                assert word_boundary is True, (
                    f"{domain.value}: '{kw}' 에 word_boundary=True 누락 — "
                    "PR #80 회귀 차단 위반"
                )
