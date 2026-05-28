# -*- coding: utf-8 -*-
"""Requirement Expander v13 Phase 6.2 단위 test (PR #226).

검증 범위:
    1. ChecklistItem dataclass schema
    2. _DOMAIN_PATTERNS 3D 키워드 매칭
    3. _detect_domain — 영문/한국어/case-insensitive/매칭 0건
    4. build_domain_checklist — 3D 도메인 4 항목 + 빈 도메인
    5. 3D 템플릿 항목 4개 모두 must_satisfy=True + detect_keywords 비공백
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import (
    ChecklistItem,
    build_domain_checklist,
)
from src.agents.analysis.requirement_expander import (
    _DOMAIN_PATTERNS,
    _TEMPLATE_3D_CHECKLIST,
    _detect_domain,
)


# =============================================================================
# 1. ChecklistItem dataclass
# =============================================================================
class TestChecklistItemSchema:
    def test_minimal_construction(self) -> None:
        item = ChecklistItem(
            id="3d-test",
            domain="3d_visualization",
            description="테스트 항목",
        )
        assert item.id == "3d-test"
        assert item.domain == "3d_visualization"
        assert item.must_satisfy is True  # default
        assert item.detect_keywords == []  # default factory

    def test_full_construction(self) -> None:
        item = ChecklistItem(
            id="3d-orbit",
            domain="3d_visualization",
            description="카메라 Orbit",
            must_satisfy=False,
            detect_keywords=["OrbitControls", "rotate"],
        )
        assert item.must_satisfy is False
        assert "OrbitControls" in item.detect_keywords


# =============================================================================
# 2. _DOMAIN_PATTERNS — 3D 키워드 존재
# =============================================================================
class TestDomainPatterns:
    def test_3d_pattern_present(self) -> None:
        assert "3d_visualization" in _DOMAIN_PATTERNS
        patterns = _DOMAIN_PATTERNS["3d_visualization"]
        assert "3d" in patterns
        assert "Three.js" in patterns
        assert "BIM" in patterns
        # 한국어 키워드
        assert "3차원" in patterns


# =============================================================================
# 3. _detect_domain — 매칭 케이스
# =============================================================================
class TestDetectDomain:
    def test_english_3d_keyword_matches(self) -> None:
        assert _detect_domain("Build a 3D viewer with Three.js") == ["3d_visualization"]

    def test_korean_3d_keyword_matches(self) -> None:
        assert _detect_domain("3차원 BIM 대시보드 만들어줘") == ["3d_visualization"]

    def test_bim_keyword_matches(self) -> None:
        """⭐ BIM 케이스 — Phase 6.2 본질 검증."""
        assert _detect_domain("BIM 건축 모델 뷰어") == ["3d_visualization"]

    def test_case_insensitive(self) -> None:
        assert _detect_domain("WEBGL RENDERER") == ["3d_visualization"]
        assert _detect_domain("three.JS app") == ["3d_visualization"]

    def test_no_match_returns_empty(self) -> None:
        assert _detect_domain("간단한 calculator GUI") == []
        assert _detect_domain("REST API server") == []

    def test_empty_request_returns_empty(self) -> None:
        assert _detect_domain("") == []
        assert _detect_domain(None or "") == []


# =============================================================================
# 4. build_domain_checklist — 3D 템플릿 + empty
# =============================================================================
class TestBuildDomainChecklist:
    def test_3d_request_returns_4_items(self) -> None:
        """⭐ 3D 요청 → 4 항목 템플릿 반환."""
        checklist = build_domain_checklist("3D BIM 대시보드")
        assert len(checklist) == 4
        ids = [c.id for c in checklist]
        assert "3d-camera-orbit" in ids
        assert "3d-webgl-vs-canvas" in ids
        assert "3d-interactive-controls" in ids
        assert "3d-real-3d-not-isometric" in ids

    def test_non_3d_request_returns_empty(self) -> None:
        """비-3D 요청 → 빈 list (Rule 0 자동 skip)."""
        assert build_domain_checklist("RESTful API server") == []
        assert build_domain_checklist("간단한 CLI 도구") == []

    def test_empty_request_returns_empty(self) -> None:
        assert build_domain_checklist("") == []

    def test_returned_items_are_all_must_satisfy(self) -> None:
        """⭐ 3D 템플릿 4 항목 모두 must_satisfy=True (BIM 핵심)."""
        checklist = build_domain_checklist("3D viewer")
        for item in checklist:
            assert item.must_satisfy is True, f"{item.id} must_satisfy False"

    def test_returned_items_have_detect_keywords(self) -> None:
        """모든 항목에 detect_keywords 가 비공백 (결정론 검증 가능)."""
        checklist = build_domain_checklist("3차원 모델")
        for item in checklist:
            assert len(item.detect_keywords) > 0, f"{item.id} no keywords"


# =============================================================================
# 5. _TEMPLATE_3D_CHECKLIST schema 검증
# =============================================================================
class TestTemplate3DSchema:
    def test_template_has_4_items(self) -> None:
        assert len(_TEMPLATE_3D_CHECKLIST) == 4

    def test_camera_orbit_item_detect_keywords(self) -> None:
        item = next(c for c in _TEMPLATE_3D_CHECKLIST if c.id == "3d-camera-orbit")
        assert "OrbitControls" in item.detect_keywords
        assert "rotate" in item.detect_keywords

    def test_real_3d_item_distinguishes_from_isometric(self) -> None:
        """⭐ 진짜 3D vs 가짜 2D — BIM 본질 검증 항목."""
        item = next(
            c for c in _TEMPLATE_3D_CHECKLIST if c.id == "3d-real-3d-not-isometric"
        )
        assert "rotateY" in item.detect_keywords
        assert "Vector3" in item.detect_keywords
        assert "PerspectiveCamera" in item.detect_keywords
        assert item.description.find("진짜 3D") >= 0
