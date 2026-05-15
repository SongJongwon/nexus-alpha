# -*- coding: utf-8 -*-
"""PR #138 Phase 1 minimal slice — Cross-agent consistency directive 회귀 차단.

배경 (2026-05-14 종합 점검 통찰 6 — 본인 비전):
    환율 변환기 사례 — CTO/Analyst/UI Designer 가 "frankfurter API 실시간 환율"
    결정했으나 GUI Code Generator 가 정적 dict 내장 → 1 USD = 1365.5 stale (실제
    ~1490, 9% 오차). 4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함.

    CrewAI Task.context=[...] 는 prior output 자동 주입하지만 강조 부재 →
    LLM 이 prior output 을 무시 가능.

PR #138 Phase 1 minimal slice 처방:
    1. ``format_consistency_directive`` helper — task description 에 append 할
       "다른 부서 결정 사항 일치 유지" 강조 섹션 생성
    2. GUI Code Generator task 에 시범 적용 (UI/UX Analyst + GUI Designer + Theme)

다음 PR (Phase 1 full) 예정:
    - Meeting Facilitator 에이전트 신설 (본부 10 첫 멤버)
    - Pytest Author / Code Reviewer / Build chain 으로 확대

회귀 차단: 본 테스트가 깨지면 통찰 6 의 Phase 1 첫 단계가 무력화 — 환율 사례
재발 가능.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.workflows._common import format_consistency_directive

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYZE_PY = PROJECT_ROOT / "src" / "workflows" / "analyze_and_implement.py"


# ---------------------------------------------------------------------------
# 1. format_consistency_directive helper 단위 테스트
# ---------------------------------------------------------------------------


def test_directive_returns_empty_for_empty_input() -> None:
    """빈 리스트 입력 시 빈 string 반환 (no-op)."""
    assert format_consistency_directive([]) == ""


def test_directive_includes_all_agent_roles() -> None:
    """입력된 모든 agent role 이 결과에 포함."""
    result = format_consistency_directive(["CTO", "Analyst", "UI Designer"])
    assert "CTO" in result
    assert "Analyst" in result
    assert "UI Designer" in result


def test_directive_uses_markdown_emphasis() -> None:
    """각 role 이 markdown bold 로 강조 — LLM attention 환기."""
    result = format_consistency_directive(["CTO"])
    assert "**CTO**" in result, "agent role markdown bold 누락 — LLM 강조 약화"


def test_directive_includes_consistency_section_header() -> None:
    """``## ⚠️ Cross-agent consistency directive`` 섹션 헤더."""
    result = format_consistency_directive(["CTO"])
    assert "## ⚠️" in result, "경고 마크 + 섹션 헤더 누락"
    assert "consistency" in result.lower(), "consistency 키워드 누락"


def test_directive_includes_conflict_resolution_protocol() -> None:
    """충돌 시 처리 절차 명시 — 암묵적 무시 차단."""
    result = format_consistency_directive(["CTO", "Analyst"])
    assert "충돌 시" in result, "충돌 처리 절차 누락"
    assert "암묵적 무시" in result, "암묵적 무시 금지 명시 누락 — 환율 사례 재발 위험"


def test_directive_references_currency_case_for_anti_regression() -> None:
    """환율 변환기 사례 명시 — 미래 본인이 회귀 시 즉시 인식."""
    result = format_consistency_directive(["CTO"])
    assert "환율" in result, (
        "환율 변환기 사례 evidence 명시 누락 — 1주일 후 본인이 directive 의 "
        "*존재 이유* 를 즉시 못 알 위험"
    )


def test_directive_references_phase_1_and_org_v11() -> None:
    """Phase 1 + 본부 10 (Coordination/Communication) 명시."""
    result = format_consistency_directive(["CTO"])
    assert "PR #138" in result, "PR # reference 누락"
    assert "Phase 1" in result, "Phase 1 명시 누락"
    assert "본부 10" in result or "Coordination" in result, (
        "본부 10 (Coordination/Communication) 신설 비전 reference 누락"
    )


def test_directive_preserves_role_order() -> None:
    """입력 순서가 결과에 유지 — 워크플로 순서 강조."""
    result = format_consistency_directive(["CTO", "Analyst", "UI Designer"])
    cto_pos = result.find("**CTO**")
    analyst_pos = result.find("**Analyst**")
    designer_pos = result.find("**UI Designer**")
    assert 0 < cto_pos < analyst_pos < designer_pos, (
        "agent role 순서 회귀 — 워크플로 sequential 순서가 directive 에 반영 안 됨"
    )


# ---------------------------------------------------------------------------
# 2. GUI Code Generator task 적용 회귀 차단
# ---------------------------------------------------------------------------


def test_gui_code_gen_task_uses_consistency_directive() -> None:
    """``_build_gui_code_gen_task`` 가 consistency / kickoff context directive 사용.

    회귀 차단 — directive import 또는 호출이 빠지면 환율 사례 재발 가능.

    PR #138 Phase 1 full (2026-05-15):
        analyze_and_implement.py 의 GUI Code Generator 가 ``format_consistency_directive``
        를 superset 인 ``format_kickoff_context_directive`` 로 교체. 둘 중 하나 라도
        파일에 등장하면 directive 가 적용된 것으로 인정.
    """
    text = ANALYZE_PY.read_text(encoding="utf-8")
    assert (
        "format_kickoff_context_directive" in text
        or "format_consistency_directive" in text
    ), (
        "GUI Code Generator task 가 consistency / kickoff context directive 둘 다 "
        "미사용 — PR #138 Phase 1 회귀"
    )


def test_gui_code_gen_directive_includes_three_prior_agents() -> None:
    """UI/UX Analyst + GUI Designer + Theme Designer 3 agent 명시.

    이 셋이 GUI Code Generator 의 prior decision 출처 (Task.context 와 일치).
    """
    text = ANALYZE_PY.read_text(encoding="utf-8")
    # _build_gui_code_gen_task 함수 본문 추출
    func_match = re.search(
        r"def\s+_build_gui_code_gen_task[^}]*?return\s+Task\(\*\*kwargs\)",
        text,
        re.DOTALL,
    )
    assert func_match is not None, "_build_gui_code_gen_task 함수 추출 실패"
    body = func_match.group(0)
    assert "UI/UX Analyst" in body, "UI/UX Analyst directive 누락"
    assert "GUI Designer" in body, "GUI Designer directive 누락"
    assert "Theme Designer" in body, "Theme Designer directive 누락"


def test_gui_code_gen_appends_directive_to_description() -> None:
    """directive 가 base_description 에 append 되는 구조."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    assert "base_description + consistency_directive" in text, (
        "directive 가 description 에 append 되지 않음 — Task 생성 시점에 누락 위험"
    )
