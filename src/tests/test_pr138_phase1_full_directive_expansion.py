# -*- coding: utf-8 -*-
"""PR #138 Phase 1 full — directive 확대 적용 회귀 차단.

PR #138 minimal slice (2026-05-14) 는 ``format_consistency_directive`` 를 1 개
task (GUI Code Generator) 에만 적용. 본 full slice (2026-05-15) 는 superset 인
``format_kickoff_context_directive`` 로 교체하고 적용 대상을 확장:

    1. Pytest Author task (analyze_and_implement.py)
    2. Code Reviewer task (analyze_and_implement.py)
    3. Track B / 빌드 사슬 5 task (build_workflow.py)

본 테스트는 *file-text grep* 으로 회귀 차단 — directive 호출이 누락되면
환율 변환기 사례 (cross-agent inconsistency) 가 해당 task 들에서 재발 가능.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.workflows._common import format_kickoff_context_directive


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYZE_PY = PROJECT_ROOT / "src" / "workflows" / "analyze_and_implement.py"
BUILD_PY = PROJECT_ROOT / "src" / "workflows" / "build_workflow.py"
COMMON_PY = PROJECT_ROOT / "src" / "workflows" / "_common.py"


# ---------------------------------------------------------------------------
# 1. format_kickoff_context_directive helper — _common.py
# ---------------------------------------------------------------------------


def test_kickoff_context_directive_defined_in_common() -> None:
    """``_common.py`` 에 helper 정의 — 호출 측 single entry point 유지."""
    text = COMMON_PY.read_text(encoding="utf-8")
    assert "def format_kickoff_context_directive" in text


def test_kickoff_context_directive_returns_empty_when_no_decisions_no_prior() -> None:
    """decisions=None + 빈 prior → ``""``."""
    assert format_kickoff_context_directive(None, prior_agent_roles=[]) == ""


def test_kickoff_context_directive_falls_back_to_minimal_when_no_decisions() -> None:
    """decisions=None 인데 prior 있음 → minimal slice (consistency directive) 동작."""
    text = format_kickoff_context_directive(
        None, prior_agent_roles=["CTO", "Analyst"]
    )
    assert "Cross-agent consistency" in text
    assert "**CTO**" in text


# ---------------------------------------------------------------------------
# 2. Pytest Author task 적용 (analyze_and_implement.py)
# ---------------------------------------------------------------------------


def test_pytest_author_task_uses_kickoff_directive() -> None:
    """``_build_pytest_author_task`` 가 directive 호출."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_pytest_author_task[\s\S]*?return\s+Task\(\*\*kwargs\)",
        text,
    )
    assert match is not None, "_build_pytest_author_task 추출 실패"
    body = match.group(0)
    assert "format_kickoff_context_directive" in body, (
        "Pytest Author task 가 kickoff directive 미사용 — PR #138 Phase 1 full 회귀"
    )
    assert "base_description" in body, "description 분리 안 됨"


def test_pytest_author_task_accepts_shared_kickoff_decisions() -> None:
    """시그니처에 ``shared_kickoff_decisions`` 매개변수 명시."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_pytest_author_task\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "shared_kickoff_decisions" in match.group(0), (
        "Pytest Author task 가 shared_kickoff_decisions 매개변수 누락 — "
        "kickoff 결정 주입 경로 단절"
    )


# ---------------------------------------------------------------------------
# 3. Code Reviewer task 적용 (analyze_and_implement.py)
# ---------------------------------------------------------------------------


def test_qa_task_uses_kickoff_directive() -> None:
    """``_build_qa_task`` (Code Reviewer) 가 directive 호출."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_qa_task[\s\S]*?return\s+Task\(\*\*kwargs\)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "format_kickoff_context_directive" in body, (
        "Code Reviewer task 가 kickoff directive 미사용 — 환율 사례 같은 "
        "API 가정 vs 정적 dict 구현 불일치가 리뷰에서 안 잡힘"
    )


def test_qa_task_description_explicitly_requires_kickoff_check() -> None:
    """리뷰어 description 에 *킥오프 합의 일치 점검* 명시."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_qa_task[\s\S]*?return\s+Task\(\*\*kwargs\)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "킥오프 합의" in body or "킥오프 회의 합의" in body, (
        "Code Reviewer description 이 킥오프 합의 점검 의무 미명시 — "
        "환율 사례 재발 차단 약화"
    )


# ---------------------------------------------------------------------------
# 4. GUI Code Generator (minimal slice 의 업그레이드 확인)
# ---------------------------------------------------------------------------


def test_gui_code_gen_task_uses_kickoff_directive_superset() -> None:
    """GUI Code Generator 가 minimal helper → full helper 로 교체됨."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_gui_code_gen_task[\s\S]*?return\s+Task\(\*\*kwargs\)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "format_kickoff_context_directive" in body, (
        "GUI Code Gen 이 minimal slice 의 format_consistency_directive 그대로 "
        "사용 — kickoff 결정 주입 무력화"
    )


def test_gui_code_gen_task_accepts_shared_kickoff_decisions() -> None:
    """GUI Code Generator 시그니처에 ``shared_kickoff_decisions`` 매개변수."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_gui_code_gen_task\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "shared_kickoff_decisions" in match.group(0)


# ---------------------------------------------------------------------------
# 5. Track B / 빌드 사슬 5 task (build_workflow.py)
# ---------------------------------------------------------------------------


def test_build_workflow_imports_kickoff_directive() -> None:
    """build_workflow.py 가 helper import."""
    text = BUILD_PY.read_text(encoding="utf-8")
    assert "format_kickoff_context_directive" in text, (
        "build_workflow.py 에 helper import 누락 — Track B 의 5 task 가 "
        "directive 적용 불가"
    )


def test_build_workflow_all_5_task_builders_use_directive() -> None:
    """5 task builder 모두 directive 호출.

    회귀 차단 — 어느 하나라도 빠지면 그 단계에서 cross-agent inconsistency
    검출 불가 (예: Build Engineer 가 Dep Analyzer 결정 무시).
    """
    text = BUILD_PY.read_text(encoding="utf-8")
    builders = [
        "_build_dependency_analyzer_task",
        "_build_build_engineer_task",
        "_build_asset_manager_task",
        "_build_installer_creator_task",
        "_build_platform_tester_task",
    ]
    for name in builders:
        match = re.search(
            rf"def\s+{re.escape(name)}[\s\S]*?return\s+Task\(\*\*kwargs\)",
            text,
        )
        assert match is not None, f"{name} 추출 실패"
        body = match.group(0)
        assert "format_kickoff_context_directive" in body, (
            f"{name} 가 directive 미사용 — PR #138 Phase 1 full Track B 회귀"
        )


def test_run_build_workflow_accepts_shared_kickoff_decisions() -> None:
    """``run_build_workflow`` 시그니처에 ``shared_kickoff_decisions`` 매개변수."""
    text = BUILD_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+run_build_workflow\([^)]*\)",
        text,
        re.DOTALL,
    )
    assert match is not None
    assert "shared_kickoff_decisions" in match.group(0), (
        "run_build_workflow 가 shared_kickoff_decisions 매개변수 누락 — "
        "Track B 로의 결정 주입 경로 단절"
    )
