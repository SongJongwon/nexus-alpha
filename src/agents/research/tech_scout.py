# -*- coding: utf-8 -*-
"""Tech Scout — PyPI 실존 검증 + 도메인별 후보 추출 (v13 Phase 6.1, PR #229).

PM 의사결정 7건 충족:
  #1 옵션 B 만 (PyPI JSON API), LLM 호출 0
  #5 가짜 패키지 1차 IMPROVE / 2차 BLOCKED (본 모듈은 *판정 데이터 제공* 만 —
     실 verdict 분기는 PR #230 Phase 6.3 workflow 통합에서)
  #6 7일 (7d TTL) 로컬 디스크 캐싱
  #7 MAX_SEARCHES = 5 per query

설계:
    1. ``validate_pypi_package(name)`` — PyPI JSON API 단일 패키지 검증
        - 200 → exists=True + version + last_release
        - 404 → exists=False (가짜 확정)
        - 5xx → exists=None + error (확정 안 함, stale cache 사용)
        - 캐시 hit + TTL 내 → 네트워크 호출 skip

    2. ``extract_candidates_from_query(query)`` — 결정론 도메인 매처
        - 사용자 query (예: "3D 시각화 Python") → 후보 패키지 list
        - LLM 호출 없음 — 키워드 → 사전 정의 후보
        - MAX_SEARCHES=5 truncate

    3. ``scout_and_validate(query)`` — 진입점
        - extract_candidates → 각 validate_pypi_package → ScoutResult 종합

본 모듈은 *workflow 통합 X* (Phase 6.3 PR #230 에서 wire). 직접 호출만:
    >>> from src.agents.research import scout_and_validate
    >>> result = scout_and_validate("3D 시각화 Python")
    >>> result.valid_count, result.fake_count, result.skipped_count
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests


# ---------------------------------------------------------------------------
# 상수 (PM 의사결정 #6 / #7)
# ---------------------------------------------------------------------------
PYPI_JSON_API_BASE = "https://pypi.org/pypi"
"""PyPI JSON API base URL (무인증). https://pypi.org/pypi/<pkg>/json"""

DEFAULT_CACHE_TTL_DAYS = 7
"""PM 의사결정 #6 — 캐시 7일 TTL."""

MAX_SEARCHES_PER_QUERY = 5
"""PM 의사결정 #7 — query 당 PyPI 검증 호출 상한 (비용 가드)."""

DEFAULT_CACHE_DIR = Path("outputs") / "_pypi_cache"
"""캐시 디렉터리. 각 패키지 → ``<DEFAULT_CACHE_DIR>/<name>.json``."""

_PYPI_TIMEOUT_SEC = 10.0
"""PyPI API HTTP timeout (network 응답 한도)."""

_USER_AGENT = "Nexus-Alpha-Tech-Scout/v13.6.1 (+nexus-alpha)"
"""PyPI API 호출 시 User-Agent (Anti-bot 우회 목적, 무인증 호환)."""


# ---------------------------------------------------------------------------
# 결과 dataclass
# ---------------------------------------------------------------------------
@dataclass
class PyPIResult:
    """단일 패키지 PyPI JSON API 검증 결과.

    Attributes:
        name: 검증한 패키지 이름.
        exists: True (실존) / False (가짜 — 404) / None (확정 불가 — 5xx/network 결함).
        latest_version: 200 응답 시 최신 버전 문자열.
        last_release: 200 응답 시 마지막 release ISO 8601 timestamp.
        error: None / "not_found" / "server_error" / "network_error" 등.
        checked_at: 검증 시각 ISO 8601 UTC.
        from_cache: True 면 캐시 hit (네트워크 호출 skip).
    """

    name: str
    exists: Optional[bool]
    latest_version: Optional[str] = None
    last_release: Optional[str] = None
    error: Optional[str] = None
    checked_at: str = ""
    from_cache: bool = False


@dataclass
class ScoutResult:
    """``scout_and_validate`` 종합 산출.

    Attributes:
        query: 입력 query 그대로.
        domain: 매칭된 도메인 ID (없으면 None).
        candidates: 추출된 후보 패키지 list (MAX_SEARCHES 까지 truncate).
        validated: 각 후보의 PyPIResult.
        valid_count: exists=True 개수.
        fake_count: exists=False 개수.
        skipped_count: exists=None 개수 (5xx/network 결함).
        elapsed_ms: 전체 소요 시간.
    """

    query: str
    domain: Optional[str]
    candidates: list[str]
    validated: list[PyPIResult] = field(default_factory=list)
    valid_count: int = 0
    fake_count: int = 0
    skipped_count: int = 0
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# 도메인 → PyPI 후보 매핑 (결정론, LLM 무관)
# ---------------------------------------------------------------------------
# v13 Phase 6.1 시점 — 3D 우선 (PM 의사결정 #4). 향후 도메인 확장 시 본 dict
# 와 keyword 매처 양쪽 갱신.
_DOMAIN_PYPI_CANDIDATES: dict[str, list[str]] = {
    "3d_visualization": [
        "pythreejs",        # Three.js Python wrapper
        "plotly",           # 3D scatter/surface
        "vispy",            # OpenGL high-performance
        "vtk",              # 과학 시각화 표준
        "open3d",           # 3D processing
    ],
}

# query keyword 매처 — _DOMAIN_PYPI_CANDIDATES 와 1:1 정합.
_QUERY_KEYWORDS: dict[str, list[str]] = {
    "3d_visualization": [
        "3d", "WebGL", "Three.js", "BIM", "CAD",
        "Bloch sphere", "Mesh", "Camera", "Orbit",
        "3차원", "삼차원", "공간 시각화", "건축 모델",
    ],
}


def extract_candidates_from_query(
    query: str, max_candidates: int = MAX_SEARCHES_PER_QUERY
) -> tuple[Optional[str], list[str]]:
    """query → (도메인 ID, 후보 패키지 list) — 결정론 매처.

    매칭 0 → (None, []). MAX_SEARCHES 초과 시 앞쪽 truncate.

    Args:
        query: 사용자 자연어 query (예: "3D 시각화 Python").
        max_candidates: 후보 상한 (default MAX_SEARCHES_PER_QUERY=5).

    Returns:
        (domain, candidates) tuple.
    """
    if not query:
        return (None, [])
    lower = query.lower()
    for domain, keywords in _QUERY_KEYWORDS.items():
        if any(kw.lower() in lower for kw in keywords):
            candidates = list(_DOMAIN_PYPI_CANDIDATES.get(domain, []))
            return (domain, candidates[:max_candidates])
    return (None, [])


# ---------------------------------------------------------------------------
# 캐시 헬퍼
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> float:
    return time.time()


def _cache_path(name: str, cache_dir: Path) -> Path:
    """패키지 이름 → 캐시 파일 경로. 안전한 파일명 (소문자 + 알파벳/숫자/하이픈)."""
    safe = "".join(c if c.isalnum() or c == "-" else "_" for c in name.lower())
    return cache_dir / f"{safe}.json"


def _read_cache(name: str, cache_dir: Path) -> Optional[PyPIResult]:
    """캐시 read. 파싱 실패 또는 file 부재 시 None."""
    path = _cache_path(name, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PyPIResult(**data)
    except Exception:  # noqa: BLE001 — 캐시 파싱 결함은 silent (네트워크 fallback)
        return None


def _write_cache(result: PyPIResult, cache_dir: Path) -> None:
    """캐시 write. 실패 silent (디스크 결함이 검증 차단 X)."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(result.name, cache_dir)
        path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def _is_cache_stale(result: PyPIResult, ttl_days: int) -> bool:
    """checked_at 가 ttl_days 이전이면 stale."""
    if not result.checked_at:
        return True
    try:
        checked = datetime.strptime(result.checked_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age = datetime.now(timezone.utc) - checked
        return age.days >= ttl_days
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------------
# 핵심: PyPI JSON API 검증
# ---------------------------------------------------------------------------
def validate_pypi_package(
    name: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    timeout_sec: float = _PYPI_TIMEOUT_SEC,
    session: Optional[requests.Session] = None,
) -> PyPIResult:
    """PyPI JSON API 로 패키지 실존 검증. 캐시 7d TTL + 5xx resilience.

    동작 순서:
        1. 캐시 read — TTL 내 + exists 확정값 (True/False) 이면 즉시 반환 (network skip)
        2. PyPI ``GET /pypi/<name>/json`` 호출 (timeout 10s)
        3. 200 → exists=True + 메타 캐싱
        4. 404 → exists=False 캐싱 (가짜 확정)
        5. 5xx → stale cache 사용 (없으면 exists=None + error="server_error")
        6. network exception → stale cache 사용 (없으면 exists=None + error="network_error")

    Args:
        name: PyPI 패키지 이름 (대소문자 무시 — pypi.org 가 정규화).
        cache_dir: 캐시 디렉터리. Default ``outputs/_pypi_cache``.
        cache_ttl_days: 캐시 stale 기준일 (default 7).
        timeout_sec: HTTP timeout.
        session: 옵션 ``requests.Session`` 주입 (테스트 mock 용).

    Returns:
        PyPIResult — exists / 메타 / from_cache 표시.
    """
    if not name or not name.strip():
        return PyPIResult(
            name=name,
            exists=None,
            error="empty_name",
            checked_at=_now_iso(),
        )

    # 1. 캐시 read
    cached = _read_cache(name, cache_dir)
    if cached is not None and not _is_cache_stale(cached, cache_ttl_days):
        if cached.exists in (True, False):
            # 확정값은 TTL 내라면 그대로 사용 (network skip)
            cached.from_cache = True
            return cached
        # exists=None (이전 5xx) 은 stale 아니어도 재시도

    # 2. PyPI 호출
    url = f"{PYPI_JSON_API_BASE}/{name}/json"
    http = session or requests
    try:
        response = http.get(
            url,
            timeout=timeout_sec,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001 — 모든 network 결함 catch
        # 6. network exception → stale cache fallback
        if cached is not None:
            cached.from_cache = True
            return cached
        return PyPIResult(
            name=name,
            exists=None,
            error=f"network_error: {exc.__class__.__name__}",
            checked_at=_now_iso(),
        )

    if response.status_code == 200:
        # 3. 실존 확정
        try:
            data = response.json()
            info = data.get("info", {}) if isinstance(data, dict) else {}
            urls = data.get("urls", []) if isinstance(data, dict) else []
            latest_version = str(info.get("version", "")) or None
            last_release = None
            if isinstance(urls, list) and urls:
                first = urls[0]
                if isinstance(first, dict):
                    last_release = first.get("upload_time")
            result = PyPIResult(
                name=name,
                exists=True,
                latest_version=latest_version,
                last_release=last_release,
                checked_at=_now_iso(),
            )
        except Exception as exc:  # noqa: BLE001 — JSON parse 결함
            result = PyPIResult(
                name=name,
                exists=True,  # 200 은 존재 확정 — JSON 결함은 메타만 빈 채
                error=f"json_parse_error: {exc.__class__.__name__}",
                checked_at=_now_iso(),
            )
        _write_cache(result, cache_dir)
        return result

    if response.status_code == 404:
        # 4. 가짜 확정
        result = PyPIResult(
            name=name,
            exists=False,
            error="not_found",
            checked_at=_now_iso(),
        )
        _write_cache(result, cache_dir)
        return result

    # 5. 5xx (또는 기타) → stale cache fallback
    if cached is not None:
        cached.from_cache = True
        return cached
    return PyPIResult(
        name=name,
        exists=None,
        error=f"server_error: HTTP {response.status_code}",
        checked_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# 진입점 — scout_and_validate
# ---------------------------------------------------------------------------
def scout_and_validate(
    query: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    max_searches: int = MAX_SEARCHES_PER_QUERY,
    session: Optional[requests.Session] = None,
) -> ScoutResult:
    """query → 후보 추출 → 각 후보 PyPI 검증 → 종합 ScoutResult.

    Phase 6.1 모드 (옵션 B 만 — PM 의사결정 #1):
        - LLM 호출 0 (extract_candidates 가 결정론 매처)
        - 비용 0 (PyPI JSON API 무인증)
        - MAX_SEARCHES=5 가드 (per query)

    Args:
        query: 사용자 자연어 query.
        cache_dir / cache_ttl_days: 캐시 정책 (PM 의사결정 #6).
        max_searches: per query 검증 상한 (PM 의사결정 #7).
        session: requests.Session 주입 (테스트용).

    Returns:
        ScoutResult — 후보 + 검증 결과 + 카운트.

    Example:
        >>> result = scout_and_validate("3D 시각화 Python")
        >>> print(f"valid={result.valid_count} fake={result.fake_count}")
        >>> for pkg in result.validated:
        ...     print(pkg.name, pkg.exists, pkg.latest_version)
    """
    start = _now_ts()
    domain, candidates = extract_candidates_from_query(query, max_candidates=max_searches)

    validated: list[PyPIResult] = []
    for name in candidates:
        result = validate_pypi_package(
            name,
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            session=session,
        )
        validated.append(result)

    valid_count = sum(1 for r in validated if r.exists is True)
    fake_count = sum(1 for r in validated if r.exists is False)
    skipped_count = sum(1 for r in validated if r.exists is None)
    elapsed_ms = (_now_ts() - start) * 1000.0

    return ScoutResult(
        query=query,
        domain=domain,
        candidates=candidates,
        validated=validated,
        valid_count=valid_count,
        fake_count=fake_count,
        skipped_count=skipped_count,
        elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# v13 Phase 6.3 (PR #230) — requirements.txt 파일 일괄 검증
# ---------------------------------------------------------------------------
# pip requirements 형식 — 각 줄에서 패키지 이름 추출.
# 형식 예: "requests>=2.31.0", "numpy ; python_version>='3.10'",
#         "git+https://...", "-e ./local", "# comment"
import re as _re

_PKG_NAME_RE = _re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
"""pip requirements 줄에서 패키지 이름 추출. extras/version 제외."""


def _parse_requirements_lines(content: str) -> list[str]:
    """requirements.txt 본문 → 패키지 이름 list (정규화 — 소문자 + 중복 제거).

    무시 대상:
        - 주석 (``#`` 시작)
        - 빈 줄
        - VCS URL (``git+``, ``hg+`` 등)
        - 로컬 파일 (``-e .``, ``./local``)
        - 옵션 라인 (``-r other.txt``)
    """
    names: list[str] = []
    seen: set[str] = set()
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            # -e, -r, --index-url 등 옵션 라인
            continue
        if line.startswith(("git+", "hg+", "svn+", "bzr+", "./", "/")):
            continue
        match = _PKG_NAME_RE.match(line)
        if not match:
            continue
        name = match.group(1).lower()
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def validate_requirements_txt(
    req_path: Path,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    max_packages: int = MAX_SEARCHES_PER_QUERY * 4,
    session: Optional[requests.Session] = None,
) -> list[PyPIResult]:
    """Engineer 산출 requirements.txt 파일 → 각 패키지 PyPI 검증.

    Phase 6.3 (PR #230) 의 핵심 — Engineer 가 환각 패키지 (``bim_repository``)
    포함한 requirements.txt 산출 시 *각 패키지 PyPI 실존 검증*. 결과 list 의
    ``exists=False`` 항목이 *가짜 패키지*.

    Args:
        req_path: requirements.txt 파일 경로.
        cache_dir / cache_ttl_days: 캐시 정책 (Phase 6.1 과 동일).
        max_packages: requirements.txt 의 *총* 패키지 상한 (기본 MAX_SEARCHES*4=20).
            과다 의존성 안건은 truncate.
        session: 옵션 ``requests.Session`` (테스트 mock 용).

    Returns:
        PyPIResult list. 빈 list 면 파일 부재 / 파싱 실패 / 패키지 0건.
    """
    if not req_path.exists() or not req_path.is_file():
        return []
    try:
        content = req_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    names = _parse_requirements_lines(content)
    if not names:
        return []
    names = names[:max_packages]
    results: list[PyPIResult] = []
    for name in names:
        result = validate_pypi_package(
            name,
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            session=session,
        )
        results.append(result)
    return results


def extract_fake_packages(results: list[PyPIResult]) -> list[str]:
    """검증 결과 → 가짜 패키지 이름 list (exists=False 만).

    Phase 6.3 의 *판정 입력*:
        - 빈 list → 가짜 없음 (모두 실존 또는 5xx 확정 불가)
        - 1+ 항목 → judge_convergence 가 IMPROVE/BLOCKED 분기

    Note:
        ``exists=None`` (5xx / network 결함) 은 *확정 불가* 라 가짜 list 에서 제외.
        보수적 — 5xx 변동성으로 인한 false BLOCKED 회피.
    """
    return [r.name for r in results if r.exists is False]
