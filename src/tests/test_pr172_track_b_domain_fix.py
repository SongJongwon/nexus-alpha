# -*- coding: utf-8 -*-
"""PR #172 — Track B 도메인 분류 fail-HARD 결함 fix (PM E2E 라이브 검증 발견).

배경 (2026-05-18 Track B E2E 검증):
    PM 본인 PC 에서 PR #170 효과 확인 목적 Track B + ``enable_qa_loop=True`` E2E 시도:

        .venv\\Scripts\\python.exe scripts\\run.py --request "네이버 쇼핑 크롤러" \\
            --track B --build --auto-iterate --max-iterations 1

    결과: ``ValueError at automate_workflow.py:1455`` — *전체 run 중단*. 메시지:
    "Track B 자동화 도메인을 결정할 수 없습니다. ... 더 구체적인 요청 또는
    forced_domain= 파라미터를 명시해 주세요."

    Root-cause 분석:
        - ``_DOMAIN_KEYWORDS[WEB_SCRAPING]`` 에 "크롤러" 키워드 누락 (있는 건 "크롤링",
          "스크래퍼"). "네이버 쇼핑 크롤러" → score=0 → ``UNKNOWN`` → ``ValueError``.
        - "쇼핑" / "네이버" 도 사전 없음.
        - 명백한 web_scraping 의도의 요청도 *키워드 갭만으로 전체 run 중단* — fail-HARD.

    어제 fail-silent 검색 sprint (PR #170) 에서 ``_llm_classify_domain`` 을 "LOW —
    의도된 graceful fallback, skip" 으로 분류한 것은 **잘못된 판단** — 실제는 fail-HARD.
    PM E2E 라이브 검증으로 self-correction 도달.

PR #172 처방 (A + B 결합, C 별도 PR):

    A. 한국어 동의어 누락 보완 (root-cause 직접 fix):
        - WEB_SCRAPING STRONG: "크롤러" / "스크레이퍼" / "스크레이핑" 추가
        - WEB_SCRAPING MEDIUM: "수집기" 추가
        - 향후 한국어 동의어는 동일 패턴으로 누적

    B. ``_resolve_track_b_domain`` 헬퍼 + graceful fallback:
        - ``UNKNOWN`` → ``WEB_SCRAPING`` default + ``sys.stderr`` 진단 메시지
        - PR #160a (Vision QA SKIPPED) + PR #170 (CodeQASkipped) 와 같은 *진단 surface*
          패턴 — fail-silent 아닌 *graceful with diagnostics*
        - ``forced_domain`` 명시는 휴리스틱 우회 (기존 동작 유지)
        - ``run_automate_workflow`` 진입부의 ``ValueError`` raise 분기 제거

본 테스트:
    1. PM E2E 회귀 case ("네이버 쇼핑 크롤러" → WEB_SCRAPING)
    2. 한국어 동의어 키워드 확장 5+ 케이스
    3. ``_resolve_track_b_domain`` 4 분기 (forced_domain / 휴리스틱 정상 / UNKNOWN fallback / stderr 진단)
    4. 기존 휴리스틱 회귀 차단 (다른 도메인 정확 분류 유지)
"""

from __future__ import annotations

from typing import Optional

import pytest

from src.workflows.automate_workflow import (
    AutomationDomain,
    _DOMAIN_KEYWORDS,
    _resolve_track_b_domain,
    detect_automation_domain,
)


# ---------------------------------------------------------------------------
# 1. PM E2E 라이브 검증 회귀 case + 한국어 동의어 확장
# ---------------------------------------------------------------------------


def test_pm_e2e_naver_shopping_crawler_classifies_web_scraping() -> None:
    """PM E2E 라이브 검증 회귀 case — '네이버 쇼핑 크롤러' → WEB_SCRAPING.

    PR #172 이전에는 score=0 → UNKNOWN → ValueError (전체 run 중단).
    """
    domain = detect_automation_domain("네이버 쇼핑 크롤러", allow_llm_fallback=False)
    assert domain is AutomationDomain.WEB_SCRAPING


@pytest.mark.parametrize(
    "request_text",
    [
        "크롤러 만들어줘",
        "스크레이퍼 작성",
        "스크레이핑 자동화",
        "데이터 수집기",
        "네이버 뉴스 크롤러로 헤드라인 수집",
        "쇼핑몰 상품 크롤러",
    ],
)
def test_korean_synonym_keywords_classify_web_scraping(request_text: str) -> None:
    """PR #172 — 한국어 동의어 키워드 확장 cover."""
    domain = detect_automation_domain(request_text, allow_llm_fallback=False)
    assert domain is AutomationDomain.WEB_SCRAPING


def test_web_scraping_keywords_include_crawler_synonyms() -> None:
    """PR #172 — `_DOMAIN_KEYWORDS` 에 한국어 누락 동의어 등록 회귀 차단."""
    keywords = {kw for kw, _, _ in _DOMAIN_KEYWORDS[AutomationDomain.WEB_SCRAPING]}
    # PR #172 새 동의어 — 회귀 차단
    assert "크롤러" in keywords
    assert "스크레이퍼" in keywords
    assert "스크레이핑" in keywords
    assert "수집기" in keywords
    # 기존 키워드 — 회귀 차단
    assert "크롤링" in keywords
    assert "스크래퍼" in keywords
    assert "스크래핑" in keywords


# ---------------------------------------------------------------------------
# 2. _resolve_track_b_domain — 4 분기
# ---------------------------------------------------------------------------


def test_resolve_returns_forced_domain_bypassing_heuristic() -> None:
    """``forced_domain`` 명시 → 휴리스틱 우회 + 그 도메인 그대로 반환."""
    domain = _resolve_track_b_domain(
        "엑셀 파일 파싱",  # 휴리스틱이라면 DATA_PARSER
        forced_domain=AutomationDomain.API_INTEGRATION,
    )
    assert domain is AutomationDomain.API_INTEGRATION


def test_resolve_returns_heuristic_domain_when_known() -> None:
    """휴리스틱이 정상 도메인 감지 → 그대로 반환 (fallback 안 탐)."""
    domain = _resolve_track_b_domain("네이버 쇼핑 크롤러", forced_domain=None)
    assert domain is AutomationDomain.WEB_SCRAPING


def test_resolve_falls_back_to_web_scraping_on_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """휴리스틱 UNKNOWN → WEB_SCRAPING fallback + stderr 진단 메시지."""

    def fake_detect(text: str, *, allow_llm_fallback: bool = True) -> AutomationDomain:
        return AutomationDomain.UNKNOWN

    monkeypatch.setattr(
        "src.workflows.automate_workflow.detect_automation_domain", fake_detect
    )

    domain = _resolve_track_b_domain("아무말 대잔치", forced_domain=None)
    assert domain is AutomationDomain.WEB_SCRAPING

    err = capsys.readouterr().err
    # 진단 메시지 — 사용자 가시화 (fail-silent 아님)
    assert "domain 자동 감지 실패" in err
    assert "아무말 대잔치" in err
    assert "fallback" in err
    assert "web_scraping" in err
    assert "forced_domain" in err  # opt-out 안내


def test_resolve_respects_custom_fallback_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``fallback_domain`` 파라미터 override 가능 (default WEB_SCRAPING)."""

    def fake_detect(text: str, *, allow_llm_fallback: bool = True) -> AutomationDomain:
        return AutomationDomain.UNKNOWN

    monkeypatch.setattr(
        "src.workflows.automate_workflow.detect_automation_domain", fake_detect
    )

    domain = _resolve_track_b_domain(
        "아무 말",
        forced_domain=None,
        fallback_domain=AutomationDomain.DATA_PARSER,
    )
    assert domain is AutomationDomain.DATA_PARSER


def test_resolve_never_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_resolve_track_b_domain`` 은 *절대* UNKNOWN 을 반환하지 않는다 (fallback 보장)."""

    def fake_detect(text: str, *, allow_llm_fallback: bool = True) -> AutomationDomain:
        return AutomationDomain.UNKNOWN

    monkeypatch.setattr(
        "src.workflows.automate_workflow.detect_automation_domain", fake_detect
    )

    domain = _resolve_track_b_domain("", forced_domain=None)  # 빈 입력도 fallback
    assert domain is not AutomationDomain.UNKNOWN


# ---------------------------------------------------------------------------
# 3. 기존 휴리스틱 회귀 차단 (다른 도메인 정확 분류 유지)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text, expected",
    [
        ("PyInstaller 마우스 자동화 RPA", AutomationDomain.DESKTOP_AUTOMATION),
        ("외부 API 연동으로 webhook 받기", AutomationDomain.API_INTEGRATION),
        ("엑셀 파일 파싱 + PDF 추출", AutomationDomain.DATA_PARSER),
        ("Dockerfile + CI/CD 배포 자동화", AutomationDomain.DEVOPS),
    ],
)
def test_other_domains_still_classify_correctly(
    request_text: str, expected: AutomationDomain
) -> None:
    """PR #172 키워드 확장이 다른 도메인 분류에 회귀 안 일으킴 (격리)."""
    domain = detect_automation_domain(request_text, allow_llm_fallback=False)
    assert domain is expected
