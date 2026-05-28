# -*- coding: utf-8 -*-
"""Tech Scout 단위 test (v13 Phase 6.1, PR #229).

검증 범위 (mock 위주, real PyPI 는 @pytest.mark.integration 분리):
    1. PyPIResult / ScoutResult dataclass schema
    2. extract_candidates_from_query — 도메인 매처 + MAX_SEARCHES truncate
    3. validate_pypi_package — 200/404/5xx/network 결함 4 분기
    4. 캐시 동작 — TTL 내 hit / TTL 초과 refetch / 5xx 시 stale fallback
    5. scout_and_validate — 종합 산출 + carve count
    6. (integration) real PyPI 호출 — 'requests' 같은 known good 패키지
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.research import (
    DEFAULT_CACHE_TTL_DAYS,
    MAX_SEARCHES_PER_QUERY,
    PyPIResult,
    ScoutResult,
    extract_candidates_from_query,
    scout_and_validate,
    validate_pypi_package,
)
from src.agents.research.tech_scout import (
    _cache_path,
    _is_cache_stale,
    _read_cache,
    _write_cache,
)


# =============================================================================
# 1. dataclass schema
# =============================================================================
class TestPyPIResultSchema:
    def test_minimal_construction(self) -> None:
        r = PyPIResult(name="requests", exists=True)
        assert r.name == "requests"
        assert r.exists is True
        assert r.latest_version is None
        assert r.from_cache is False

    def test_full_construction(self) -> None:
        r = PyPIResult(
            name="requests",
            exists=True,
            latest_version="2.31.0",
            last_release="2024-01-15T10:00:00",
            checked_at="2026-05-28T12:00:00Z",
            from_cache=True,
        )
        assert r.latest_version == "2.31.0"
        assert r.from_cache is True


class TestScoutResultSchema:
    def test_default_factories(self) -> None:
        s = ScoutResult(query="x", domain=None, candidates=[])
        assert s.validated == []  # default factory
        assert s.valid_count == 0
        assert s.elapsed_ms == 0.0


# =============================================================================
# 2. extract_candidates_from_query
# =============================================================================
class TestExtractCandidates:
    def test_3d_query_returns_pypi_candidates(self) -> None:
        domain, candidates = extract_candidates_from_query("3D 시각화 Python")
        assert domain == "3d_visualization"
        assert len(candidates) > 0
        assert "pythreejs" in candidates or "vispy" in candidates

    def test_bim_query_matches(self) -> None:
        domain, candidates = extract_candidates_from_query("BIM 건축 모델 뷰어")
        assert domain == "3d_visualization"
        assert len(candidates) > 0

    def test_korean_3d_keyword(self) -> None:
        domain, candidates = extract_candidates_from_query("3차원 공간 시각화")
        assert domain == "3d_visualization"

    def test_non_matching_query_returns_none(self) -> None:
        domain, candidates = extract_candidates_from_query("REST API server")
        assert domain is None
        assert candidates == []

    def test_empty_query(self) -> None:
        domain, candidates = extract_candidates_from_query("")
        assert domain is None
        assert candidates == []

    def test_max_searches_truncation(self) -> None:
        """⭐ MAX_SEARCHES=5 가드 — 후보가 더 많아도 5개로 truncate."""
        _, candidates = extract_candidates_from_query(
            "3D 시각화", max_candidates=3
        )
        assert len(candidates) <= 3

    def test_default_max_is_5(self) -> None:
        _, candidates = extract_candidates_from_query("3D 시각화")
        assert len(candidates) <= MAX_SEARCHES_PER_QUERY


# =============================================================================
# 3. validate_pypi_package — 4 분기 mock
# =============================================================================
def _make_session_mock(status_code: int, body: dict | None = None) -> MagicMock:
    """status_code + body 로 requests.Session.get mock 생성."""
    session = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body or {}
    session.get.return_value = response
    return session


class TestValidatePyPIPackage:
    def test_200_exists_true(self, tmp_path: Path) -> None:
        body = {
            "info": {"version": "2.31.0"},
            "urls": [{"upload_time": "2024-01-15T10:00:00"}],
        }
        session = _make_session_mock(200, body)
        result = validate_pypi_package(
            "requests", cache_dir=tmp_path, session=session
        )
        assert result.exists is True
        assert result.latest_version == "2.31.0"
        assert result.last_release == "2024-01-15T10:00:00"
        assert result.error is None
        assert result.from_cache is False

    def test_404_exists_false_fake_package(self, tmp_path: Path) -> None:
        """⭐ 가짜 패키지 — 404 → exists=False (PR #230 절충안 1차 IMPROVE)."""
        session = _make_session_mock(404)
        result = validate_pypi_package(
            "bim_repository", cache_dir=tmp_path, session=session
        )
        assert result.exists is False
        assert result.error == "not_found"

    def test_5xx_exists_none_no_cache(self, tmp_path: Path) -> None:
        """5xx + 캐시 없음 → exists=None + server_error."""
        session = _make_session_mock(503)
        result = validate_pypi_package(
            "unknown_pkg", cache_dir=tmp_path, session=session
        )
        assert result.exists is None
        assert result.error is not None
        assert "server_error" in result.error

    def test_network_exception_exists_none(self, tmp_path: Path) -> None:
        """network 결함 — exists=None + network_error."""
        session = MagicMock()
        session.get.side_effect = ConnectionError("DNS failure")
        result = validate_pypi_package(
            "any_pkg", cache_dir=tmp_path, session=session
        )
        assert result.exists is None
        assert result.error is not None
        assert "network_error" in result.error

    def test_empty_name_returns_error(self, tmp_path: Path) -> None:
        result = validate_pypi_package("", cache_dir=tmp_path)
        assert result.exists is None
        assert result.error == "empty_name"


# =============================================================================
# 4. 캐싱 (7d TTL + 5xx fallback)
# =============================================================================
class TestCaching:
    def test_cache_hit_within_ttl_skips_network(self, tmp_path: Path) -> None:
        """⭐ TTL 내 캐시 hit → network 호출 skip."""
        # 첫 호출 — 캐시 write
        session1 = _make_session_mock(
            200, {"info": {"version": "1.0"}, "urls": []}
        )
        result1 = validate_pypi_package(
            "test-pkg", cache_dir=tmp_path, session=session1
        )
        assert result1.from_cache is False
        assert session1.get.call_count == 1

        # 두 번째 호출 — 캐시 hit, network skip
        session2 = _make_session_mock(500)  # 5xx 라도 무관 — 호출 안 함
        result2 = validate_pypi_package(
            "test-pkg", cache_dir=tmp_path, session=session2
        )
        assert result2.from_cache is True
        assert result2.exists is True
        assert result2.latest_version == "1.0"
        assert session2.get.call_count == 0  # ⭐ network skip 확정

    def test_cache_stale_triggers_refetch(self, tmp_path: Path) -> None:
        """⭐ TTL (7d) 초과 → 재 fetch."""
        # 미리 stale 캐시 작성
        old_iso = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        stale = PyPIResult(
            name="stale-pkg", exists=True, latest_version="0.1", checked_at=old_iso
        )
        _write_cache(stale, tmp_path)

        # 새 호출 — refetch (200 새 응답)
        session = _make_session_mock(
            200, {"info": {"version": "2.0"}, "urls": []}
        )
        result = validate_pypi_package(
            "stale-pkg", cache_dir=tmp_path, session=session
        )
        assert session.get.call_count == 1  # refetch 됨
        assert result.latest_version == "2.0"  # 새 version
        assert result.from_cache is False

    def test_5xx_falls_back_to_stale_cache(self, tmp_path: Path) -> None:
        """⭐ 5xx + stale cache 있음 → stale 값 사용 (resilience)."""
        old_iso = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        stale = PyPIResult(
            name="stale-pkg", exists=True, latest_version="0.1", checked_at=old_iso
        )
        _write_cache(stale, tmp_path)

        # 5xx 응답
        session = _make_session_mock(503)
        result = validate_pypi_package(
            "stale-pkg", cache_dir=tmp_path, session=session
        )
        assert result.from_cache is True
        assert result.exists is True  # stale 값
        assert result.latest_version == "0.1"

    def test_cache_file_path_safe(self, tmp_path: Path) -> None:
        """패키지 이름에 위험 문자 있어도 안전한 파일명."""
        path = _cache_path("My-Package_v2", tmp_path)
        assert path.parent == tmp_path
        # alphanumeric + hyphen 만 허용
        assert path.name.endswith(".json")
        # path traversal 방지
        assert ".." not in path.name

    def test_is_cache_stale_thresholds(self) -> None:
        """7d 경계 검증."""
        now = datetime.now(timezone.utc)
        fresh = PyPIResult(
            name="x", exists=True,
            checked_at=(now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        stale = PyPIResult(
            name="x", exists=True,
            checked_at=(now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        no_check = PyPIResult(name="x", exists=True)  # checked_at=""
        assert _is_cache_stale(fresh, ttl_days=7) is False
        assert _is_cache_stale(stale, ttl_days=7) is True
        assert _is_cache_stale(no_check, ttl_days=7) is True  # 빈 timestamp = stale

    def test_corrupt_cache_falls_back_to_network(self, tmp_path: Path) -> None:
        """캐시 파일 손상 시 silent skip → network fetch."""
        cache_file = tmp_path / "corrupt-pkg.json"
        cache_file.write_text("not valid json {{{", encoding="utf-8")
        session = _make_session_mock(
            200, {"info": {"version": "1.0"}, "urls": []}
        )
        result = validate_pypi_package(
            "corrupt-pkg", cache_dir=tmp_path, session=session
        )
        # network 호출됨
        assert session.get.call_count == 1
        assert result.exists is True


# =============================================================================
# 5. scout_and_validate — 진입점 종합
# =============================================================================
class TestScoutAndValidate:
    def test_3d_query_full_cycle(self, tmp_path: Path) -> None:
        """⭐ 3D query → 후보 추출 → 모두 200 → valid_count=5."""
        body = {"info": {"version": "1.0"}, "urls": []}
        session = _make_session_mock(200, body)
        result = scout_and_validate(
            "3D 시각화 Python", cache_dir=tmp_path, session=session
        )
        assert result.query == "3D 시각화 Python"
        assert result.domain == "3d_visualization"
        assert len(result.candidates) == MAX_SEARCHES_PER_QUERY
        assert len(result.validated) == MAX_SEARCHES_PER_QUERY
        assert result.valid_count == MAX_SEARCHES_PER_QUERY
        assert result.fake_count == 0
        assert result.skipped_count == 0
        assert result.elapsed_ms >= 0

    def test_query_with_no_domain_match_returns_empty(
        self, tmp_path: Path
    ) -> None:
        result = scout_and_validate(
            "REST API server", cache_dir=tmp_path
        )
        assert result.domain is None
        assert result.candidates == []
        assert result.validated == []
        assert result.valid_count == 0

    def test_mixed_404_and_200(self, tmp_path: Path) -> None:
        """⭐ 일부 가짜 + 일부 실존 → fake_count + valid_count 정확."""
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            response = MagicMock()
            # 첫 2 호출은 200, 나머지는 404
            if call_count["n"] <= 2:
                response.status_code = 200
                response.json.return_value = {
                    "info": {"version": "1.0"},
                    "urls": [],
                }
            else:
                response.status_code = 404
            return response

        session = MagicMock()
        session.get.side_effect = side_effect
        result = scout_and_validate(
            "3D 시각화", cache_dir=tmp_path, session=session
        )
        assert result.valid_count == 2
        assert result.fake_count == 3  # 5 candidates - 2 valid

    def test_max_searches_5_guard(self, tmp_path: Path) -> None:
        """⭐ PM 의사결정 #7 — query 당 5건만 검증."""
        body = {"info": {"version": "1.0"}, "urls": []}
        session = _make_session_mock(200, body)
        result = scout_and_validate(
            "3D 시각화", cache_dir=tmp_path, session=session
        )
        assert len(result.validated) <= MAX_SEARCHES_PER_QUERY
        assert session.get.call_count <= MAX_SEARCHES_PER_QUERY


# =============================================================================
# 6. 상수 검증 (PM 의사결정 #6 / #7)
# =============================================================================
class TestPMDecisions:
    def test_default_cache_ttl_is_7_days(self) -> None:
        """PM 의사결정 #6 — 7일 TTL."""
        assert DEFAULT_CACHE_TTL_DAYS == 7

    def test_max_searches_is_5(self) -> None:
        """PM 의사결정 #7 — MAX_SEARCHES=5."""
        assert MAX_SEARCHES_PER_QUERY == 5


# =============================================================================
# 7. ⭐ Integration — real PyPI (CI 기본 실행에서 제외, @integration)
# =============================================================================
@pytest.mark.integration
class TestRealPyPI:
    """실제 PyPI 호출 — CI 에서 skip. 로컬 검증용 (`pytest -m integration`)."""

    def test_real_pypi_requests_package_exists(self, tmp_path: Path) -> None:
        """'requests' 는 PyPI 에 확정 존재 — exists=True 또는 None (5xx 변동 허용)."""
        result = validate_pypi_package(
            "requests", cache_dir=tmp_path, cache_ttl_days=7
        )
        # PyPI 5xx 변동성 cover — flaky 차단
        assert result.exists in (True, None)

    def test_real_pypi_fake_package_404(self, tmp_path: Path) -> None:
        """⭐ 실제 BIM 사례 — 'bim_repository' 같은 환각 패키지 404 확정."""
        result = validate_pypi_package(
            "nexus_alpha_fake_package_xyz_12345", cache_dir=tmp_path
        )
        # 5xx 변동 가능성 — None 또는 False 둘 다 허용 (5xx 시 None)
        assert result.exists in (False, None)

    def test_real_scout_3d_query(self, tmp_path: Path) -> None:
        """PM 검증 예시 — scout_and_validate('3D 시각화 Python')."""
        result = scout_and_validate(
            "3D 시각화 Python", cache_dir=tmp_path
        )
        assert result.domain == "3d_visualization"
        assert len(result.candidates) == MAX_SEARCHES_PER_QUERY
        # PyPI 5xx + 일부 deprecated 변동성 cover — 최소 1개 실존 확인
        assert result.valid_count >= 1
