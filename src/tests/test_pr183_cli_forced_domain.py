# -*- coding: utf-8 -*-
"""PR #183 — CLI ``--forced-domain`` flag 추가 (PR #172 의 C 옵션).

배경 (PR #172):
    Track B 도메인 자동 분류 fail-HARD fix 시 3 처방안 식별:
        A. 한국어 동의어 키워드 확장 ✅ (PR #172 머지)
        B. UNKNOWN → WEB_SCRAPING graceful fallback + stderr 진단 ✅ (PR #172 머지)
        C. CLI ``--forced-domain`` flag — Track B 사용자 explicit override 안전망

    C 는 *별도 PR* 로 분리 (CLI scope 변경 — 본 PR scope 단순화). 본 PR #183 이 그 처방.

PR #183 처방 (4 변경):
    1. ``scripts/run.py`` argparse — ``--forced-domain`` flag 추가 (5 도메인 choices)
    2. ``scripts/run.py`` main() — args.forced_domain → AutomationDomain enum 변환
    3. ``scripts/run.py`` main() — Track A 일 때 warning + 무시
    4. ``scripts/run.py`` Track B 두 호출부 (직접 + iterative_loop) 에 forced_domain 전달
    5. ``iterative_loop.py`` — run_iterative_loop(forced_domain=...) 파라미터 추가 +
       _LoopState.forced_domain + Track B 분기에서 run_automate_workflow 에 전달

본 테스트:
    1. argparse — --forced-domain choices + default None
    2. argparse — 5 도메인 모두 valid (web_scraping / desktop_automation / api_integration / data_parser / devops)
    3. argparse — 잘못된 도메인 (e.g. "invalid") → SystemExit
    4. argparse — --forced-domain 미지정 → args.forced_domain is None
    5. file-text — run.py 가 AutomationDomain import + forced_domain_enum 변환 + 두 caller 에 전달
    6. file-text — Track A warning 메시지 정확
    7. iterative_loop.run_iterative_loop — forced_domain 파라미터 시그니처 + default None
    8. iterative_loop._LoopState — forced_domain 필드 추가
    9. iterative_loop — Track B 분기에서 forced_domain 을 run_automate_workflow 에 전달 (file-text)
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1-4. argparse — --forced-domain flag
# ---------------------------------------------------------------------------


def _parse(argv: list[str]):
    """run.py 의 _parse_args 호출 (test 헬퍼)."""
    from scripts.run import _parse_args  # noqa: PLC0415

    return _parse_args(argv)


def test_forced_domain_default_is_none() -> None:
    """--forced-domain 미지정 → args.forced_domain is None."""
    args = _parse(["--request", "x", "--non-interactive"])
    assert args.forced_domain is None


@pytest.mark.parametrize(
    "domain",
    [
        "web_scraping",
        "desktop_automation",
        "api_integration",
        "data_parser",
        "devops",
    ],
)
def test_forced_domain_accepts_5_valid_domains(domain: str) -> None:
    """5 도메인 모두 argparse choices 통과."""
    args = _parse([
        "--request", "x", "--non-interactive", "--track", "B",
        "--forced-domain", domain,
    ])
    assert args.forced_domain == domain


def test_forced_domain_rejects_invalid_value() -> None:
    """잘못된 도메인 → argparse SystemExit (choices 검증)."""
    with pytest.raises(SystemExit):
        _parse([
            "--request", "x", "--non-interactive",
            "--forced-domain", "invalid_domain_xyz",
        ])


# ---------------------------------------------------------------------------
# 5. file-text — run.py 가 AutomationDomain import + 두 caller 에 전달
# ---------------------------------------------------------------------------


def _read_runpy() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "scripts" / "run.py").read_text(encoding="utf-8")


def test_runpy_imports_automation_domain() -> None:
    """run.py 가 AutomationDomain enum 을 import 한다 (forced_domain 변환용)."""
    text = _read_runpy()
    assert "from src.workflows.automate_workflow import AutomationDomain" in text


def test_runpy_converts_forced_domain_string_to_enum() -> None:
    """run.py main() 에서 args.forced_domain (str) → AutomationDomain enum 변환."""
    text = _read_runpy()
    # forced_domain_enum 변수 + AutomationDomain(args.forced_domain) 패턴
    assert "forced_domain_enum" in text
    assert "AutomationDomain(args.forced_domain)" in text


def test_runpy_passes_forced_domain_to_both_track_b_callers() -> None:
    """⭐ PR #183 핵심 — Track B 두 호출부 (직접 + iterative_loop) 모두 forced_domain 전달."""
    text = _read_runpy()
    # forced_domain= 키워드 인자가 최소 2번 등장 (Track B 직접 + iterative_loop)
    assert text.count("forced_domain=forced_domain_enum") >= 2


def test_runpy_warns_when_track_a_with_forced_domain() -> None:
    """Track A 일 때 --forced-domain 명시 시 warning 출력."""
    text = _read_runpy()
    assert "Track A 에서 영향 없음" in text


# ---------------------------------------------------------------------------
# 6-7. iterative_loop.run_iterative_loop + _LoopState
# ---------------------------------------------------------------------------


def test_run_iterative_loop_has_forced_domain_param() -> None:
    """run_iterative_loop 시그니처에 forced_domain 키워드 추가 + default None."""
    from src.workflows.iterative_loop import run_iterative_loop  # noqa: PLC0415

    sig = inspect.signature(run_iterative_loop)
    assert "forced_domain" in sig.parameters
    assert sig.parameters["forced_domain"].default is None


def test_loop_state_has_forced_domain_field() -> None:
    """_LoopState TypedDict 에 forced_domain 필드 추가."""
    from src.workflows.iterative_loop import _LoopState  # noqa: PLC0415

    annotations = getattr(_LoopState, "__annotations__", {})
    assert "forced_domain" in annotations, (
        f"_LoopState 에 forced_domain 필드 누락 — annotations: {sorted(annotations.keys())}"
    )


# ---------------------------------------------------------------------------
# 8. iterative_loop Track B 분기에서 forced_domain 전달
# ---------------------------------------------------------------------------


def test_iterative_loop_track_b_passes_forced_domain_to_automate_workflow() -> None:
    """⭐ Track B iterative_loop 어댑터가 run_automate_workflow 에 forced_domain 전달."""
    repo_root = Path(__file__).resolve().parents[2]
    text = (
        repo_root / "src" / "workflows" / "iterative_loop.py"
    ).read_text(encoding="utf-8")
    # Track B 분기 (`if track == "B":`) 이후 `run_automate_workflow(` 호출의 인자에
    # forced_domain= 키워드가 등장하는지 검증. nested call 의 ) 문제 회피용 [\s\S]*? lazy.
    pattern = re.compile(
        r"if\s+track\s*==\s*[\"']B[\"'][\s\S]*?run_automate_workflow\([\s\S]*?forced_domain\s*=\s*state\.get",
        re.MULTILINE,
    )
    assert pattern.search(text), (
        "Track B 분기의 run_automate_workflow 호출에 forced_domain=state.get(...) 키워드 없음"
    )


# ---------------------------------------------------------------------------
# 9. 통합 — argparse + main() 변환 경로 (PYTEST_CURRENT_TEST 환경에서 단위 검증)
# ---------------------------------------------------------------------------


def test_forced_domain_str_round_trip_via_automation_domain() -> None:
    """argparse choices 5 도메인 모두 AutomationDomain enum 으로 변환 가능 (회귀 차단)."""
    from src.workflows.automate_workflow import AutomationDomain  # noqa: PLC0415

    for choice in (
        "web_scraping", "desktop_automation", "api_integration",
        "data_parser", "devops",
    ):
        enum_value = AutomationDomain(choice)
        assert enum_value.value == choice
