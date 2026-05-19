# -*- coding: utf-8 -*-
"""PR #181 — retrospective_lead pytest 환경 검출 robust 변경 (80% silent 빈 응답률 root-cause fix).

배경 (2026-05-19 Phase 3 raw 분석):
    PR #179 의 raw 저장 (workflow_dir/retrospective_llm_raw.json) 으로 3 E2E sample 분석 결과
    *예상한* 5 root-cause 후보 (token 한도 / silent timeout / streaming / TimeoutError / JSON 형식)
    모두 **NO**. 결정적 root-cause:

        Sample 1 (13:14): llm_call_invoked=True, branch_hit='normal'   → 정상 응답
        Sample 2 (13:31): llm_call_invoked=False, branch_hit='no_llm_call'  ← LLM 호출 SKIP
        Sample 3 (13:46): llm_call_invoked=False, branch_hit='no_llm_call'  ← LLM 호출 SKIP

    즉 retrospective_lead 가 *LLM 호출 자체 안 함*. 분기:

        in_pytest = "pytest" in sys.modules   # 🚨 production E2E 에서 false positive
        if llm_call is None and not in_pytest:
            llm_call = _default_llm_call

    production E2E 어딘가에서 pytest module 이 import 됨 (pytest_author / code_qa /
    sandbox 등) → in_pytest=True → llm_call None 유지 → LLM 호출 자체 skip →
    retrospective.md 빈 (4 섹션 (없음)) = 80% silent 빈 응답률의 진짜 원인.

PR #181 처방:
    ``"pytest" in sys.modules`` → ``bool(os.environ.get("PYTEST_CURRENT_TEST"))``

    근거:
    - PYTEST_CURRENT_TEST env var: pytest 가 *각 test 실행 시점* 에 자동 set.
      import 만 된 상태에서는 미 set.
    - pytest unit test 실행 중: PYTEST_CURRENT_TEST set → in_pytest=True (skip LLM, 정확)
    - production E2E (pytest 가 sys.modules 에는 있지만 actively test 아님):
      미 set → in_pytest=False → llm_call=_default_llm_call 설정 → 정상 호출

본 테스트:
    1. PYTEST_CURRENT_TEST set 시 llm_call=None 유지 → branch_hit='no_llm_call'
    2. PYTEST_CURRENT_TEST 미 set 시 _default_llm_call 자동 set → 호출됨
    3. ⭐ PR #181 핵심: sys.modules 에 pytest 있어도 PYTEST_CURRENT_TEST 미 set 시 LLM 호출
    4. 명시적 llm_call 전달 시 환경 검사 무관 (회귀 차단)
    5. raw 진단 — llm_call_invoked 가 env 검출과 1대1 매핑
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from src.agents.coordination.retrospective_lead import (
    RETROSPECTIVE_RAW_FILENAME,
    run_retrospective,
)


def _load_raw(workflow_dir: Path) -> dict[str, Any]:
    return json.loads((workflow_dir / RETROSPECTIVE_RAW_FILENAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. PYTEST_CURRENT_TEST set (현재 test 환경) → in_pytest=True → llm_call None 유지
# ---------------------------------------------------------------------------


def test_pytest_current_test_set_keeps_llm_call_none(tmp_path: Path) -> None:
    """PYTEST_CURRENT_TEST set 상태 (pytest 실행 중) → branch_hit='no_llm_call'.

    본 test 자체가 pytest 실행 중이므로 PYTEST_CURRENT_TEST 자동 set 됨.
    """
    # 본 test 시점에 PYTEST_CURRENT_TEST 가 자동 set 되어 있어야 (pytest 가 set)
    import os  # noqa: PLC0415
    assert "PYTEST_CURRENT_TEST" in os.environ

    run_retrospective(
        user_request="test",
        workflow_id="wf",
        verdict="COMPLETE",
        workflow_dir=tmp_path,
        # llm_call 명시 안 함 → None → in_pytest=True → 유지
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "no_llm_call"
    assert raw["llm_call_invoked"] is False


# ---------------------------------------------------------------------------
# 2. PYTEST_CURRENT_TEST 미 set → _default_llm_call 자동 set + 호출
# ---------------------------------------------------------------------------


def test_pytest_current_test_unset_uses_default_llm_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PYTEST_CURRENT_TEST 미 set → _default_llm_call 자동 set + 호출 진입."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    call_log: list[str] = []

    def fake_default(prompt: str) -> str:
        call_log.append(prompt[:50])
        return (
            '{"what_went_well": ["good"], '
            '"what_went_wrong": ["bad"], '
            '"lessons_learned": ["lesson"]}'
        )

    import src.agents.coordination.retrospective_lead as mod  # noqa: PLC0415
    monkeypatch.setattr(mod, "_default_llm_call", fake_default)

    run_retrospective(
        user_request="네이버 쇼핑 크롤러",
        workflow_id="wf_prod_sim",
        verdict="BLOCKED",
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)

    # PR #181 — production E2E 시뮬레이션: PYTEST_CURRENT_TEST 미 set → LLM 호출 진입
    assert raw["branch_hit"] == "normal"
    assert raw["llm_call_invoked"] is True
    assert raw["parsed_well_count"] == 1
    assert call_log, "_default_llm_call 가 호출되지 않음 — env 검출 결함"


# ---------------------------------------------------------------------------
# 3. ⭐ PR #181 핵심 — sys.modules 에 pytest 있어도 env 미 set 시 LLM 호출 진입
# ---------------------------------------------------------------------------


def test_pytest_in_sys_modules_no_env_still_invokes_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """⭐ PR #181 핵심 회귀 차단 — 80% silent 빈 응답률의 실 root-cause.

    이전 (``"pytest" in sys.modules``) 는 본 시나리오에서 in_pytest=True false positive
    → llm_call SKIP. PR #181 (``PYTEST_CURRENT_TEST``) 는 정상 호출 진입.

    Production E2E 가 pytest_author / code_qa 의존성으로 pytest module 을 import 한
    *직후* retrospective_lead 가 호출되는 시나리오 정확 재현.
    """
    # sys.modules 에 pytest 가 있음 확인 (본 test 환경 자체가 그러함)
    assert "pytest" in sys.modules

    # 그러나 PYTEST_CURRENT_TEST 는 미 set 으로 production 시뮬레이션
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    invoked: list[bool] = []

    def fake_llm(prompt: str) -> str:
        invoked.append(True)
        return '{"what_went_well": ["ok"], "what_went_wrong": [], "lessons_learned": []}'

    import src.agents.coordination.retrospective_lead as mod  # noqa: PLC0415
    monkeypatch.setattr(mod, "_default_llm_call", fake_llm)

    run_retrospective(
        user_request="test",
        workflow_id="wf_critical",
        verdict="BLOCKED",
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)

    # PR #181 fix evidence — sys.modules pytest 있어도 env 미 set 시 호출 진입
    assert raw["llm_call_invoked"] is True
    assert raw["branch_hit"] != "no_llm_call"
    assert invoked, "PR #181 fix 회귀 — env 미 set 인데 LLM 호출 안 됨"


# ---------------------------------------------------------------------------
# 4. 명시적 llm_call 전달 시 환경 검사 무관 (회귀 차단)
# ---------------------------------------------------------------------------


def test_explicit_llm_call_overrides_env_detection(tmp_path: Path) -> None:
    """llm_call 명시 전달 시 PYTEST_CURRENT_TEST 와 무관하게 호출 (회귀 차단)."""

    def explicit_llm(prompt: str) -> str:
        return '{"what_went_well": ["explicit"], "what_went_wrong": [], "lessons_learned": []}'

    # 본 test 환경에서 PYTEST_CURRENT_TEST 자동 set 되어 있지만, llm_call 명시 전달
    run_retrospective(
        user_request="test",
        workflow_id="wf_explicit",
        verdict="COMPLETE",
        llm_call=explicit_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    # 명시 llm_call 전달 → 환경 검사 우회 → 호출 진입
    assert raw["llm_call_invoked"] is True
    assert raw["parsed_well_count"] == 1


# ---------------------------------------------------------------------------
# 5. raw 진단 — llm_call_invoked 가 env 검출과 1대1 매핑
# ---------------------------------------------------------------------------


def test_raw_diag_llm_call_invoked_matches_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PR #179 raw evidence — llm_call_invoked 가 env 검출 결과와 1대1 매핑.

    Phase 3 의 3 E2E sample 결과 회귀 차단:
        - Sample 1 (정상): llm_call_invoked=True
        - Sample 2,3 (silent): llm_call_invoked=False (이전 root-cause, PR #181 fix 대상)
    """
    # Case A — env set (pytest 실행 중) → False
    raw_a = tmp_path / "case_a"
    run_retrospective(
        user_request="t",
        workflow_id="a",
        verdict="C",
        workflow_dir=raw_a,
    )
    assert _load_raw(raw_a)["llm_call_invoked"] is False

    # Case B — env 미 set (production 시뮬레이션) → True
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def fake(prompt: str) -> str:
        return '{"what_went_well": [], "what_went_wrong": [], "lessons_learned": []}'

    import src.agents.coordination.retrospective_lead as mod  # noqa: PLC0415
    monkeypatch.setattr(mod, "_default_llm_call", fake)

    raw_b = tmp_path / "case_b"
    run_retrospective(
        user_request="t",
        workflow_id="b",
        verdict="C",
        workflow_dir=raw_b,
    )
    assert _load_raw(raw_b)["llm_call_invoked"] is True
