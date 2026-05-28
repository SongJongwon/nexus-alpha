# -*- coding: utf-8 -*-
"""Research 본부 — 외부 지식 탐색 + 가짜 패키지 가드 (v13 Phase 6.1, PR #229).

PM 의사결정 #1 (옵션 B 만): PyPI Registry JSON API 직접 조회. 비용 0원,
LLM 호출 없음, 결정론적 검증. Anthropic web_search tool (옵션 A) 은 향후
별도 sprint.

사용 예:
    from src.agents.research import scout_and_validate
    result = scout_and_validate("3D 시각화 Python")
    for pkg in result.validated:
        print(f"{pkg.name}: exists={pkg.exists} version={pkg.latest_version}")
"""

from .tech_scout import (
    DEFAULT_CACHE_DIR,
    DEFAULT_CACHE_TTL_DAYS,
    MAX_SEARCHES_PER_QUERY,
    PYPI_JSON_API_BASE,
    PyPIResult,
    ScoutResult,
    extract_candidates_from_query,
    scout_and_validate,
    validate_pypi_package,
)

__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_CACHE_TTL_DAYS",
    "MAX_SEARCHES_PER_QUERY",
    "PYPI_JSON_API_BASE",
    "PyPIResult",
    "ScoutResult",
    "extract_candidates_from_query",
    "scout_and_validate",
    "validate_pypi_package",
]
