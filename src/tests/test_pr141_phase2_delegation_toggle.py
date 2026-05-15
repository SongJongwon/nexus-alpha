# -*- coding: utf-8 -*-
"""PR #141 Phase 2 — CrewAI allow_delegation 부분 ON 토글 회귀 차단.

배경 (본인 비전 통찰 6 D-2 — 양방향 피드백 부재):
    현재 24/24 에이전트 모두 ``allow_delegation=False`` — Engineer 가 CTO 에게
    "이 가정 안 됨" 피드백 X. 환율 변환기 사례에서 정확히 이게 일어났음.

PR #141 Phase 2 처방:
    Python Engineer + Code Reviewer 만 양방향 위임 ON (전체 ON 은 비용 폭증).
    workflow 호출 시 명시적으로 ``enable_engineer_reviewer_delegation=True`` 로
    활성화. 기본값은 False — backward compat.

본 테스트 목적:
    - run_iterative_loop / run_analyze_and_implement / 3 chain function 에
      ``enable_engineer_reviewer_delegation`` 매개변수 존재
    - True 일 때 ``create_python_engineer_agent`` 와 ``create_code_reviewer_agent`` 가
      ``allow_delegation=True`` 로 호출됨 (file-text 기반)
    - LangGraph _LoopState 에 필드 추가됨 (state 보존)
    - 기본값 False — backward compat 안전

회귀 차단: 본 테스트가 깨지면 Phase 2 의 paradigm shift 핵심 (양방향 위임 인프라)
이 사라짐. 환율 사례 같은 cross-agent inconsistency 가 양방향 피드백으로 자동
검출되는 시나리오 불가능.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from src.workflows import analyze_and_implement, iterative_loop


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYZE_PY = PROJECT_ROOT / "src" / "workflows" / "analyze_and_implement.py"
LOOP_PY = PROJECT_ROOT / "src" / "workflows" / "iterative_loop.py"


# ---------------------------------------------------------------------------
# 1. run_analyze_and_implement 시그니처
# ---------------------------------------------------------------------------


def test_run_analyze_and_implement_has_delegation_parameter() -> None:
    """공개 진입점 시그니처에 ``enable_engineer_reviewer_delegation`` 매개변수."""
    sig = inspect.signature(analyze_and_implement.run_analyze_and_implement)
    assert "enable_engineer_reviewer_delegation" in sig.parameters, (
        "run_analyze_and_implement 가 delegation 매개변수 누락 — Phase 2 회귀"
    )
    # 기본값 False — backward compat
    param = sig.parameters["enable_engineer_reviewer_delegation"]
    assert param.default is False, (
        "enable_engineer_reviewer_delegation 기본값이 False 아님 — backward compat 위반"
    )


def test_run_iterative_loop_has_delegation_parameter() -> None:
    """``run_iterative_loop`` 도 동일 매개변수 노출 (LangGraph 진입점)."""
    sig = inspect.signature(iterative_loop.run_iterative_loop)
    assert "enable_engineer_reviewer_delegation" in sig.parameters
    assert sig.parameters["enable_engineer_reviewer_delegation"].default is False


# ---------------------------------------------------------------------------
# 2. _LoopState 필드 보존
# ---------------------------------------------------------------------------


def test_loop_state_includes_delegation_field() -> None:
    """``_LoopState`` TypedDict 에 ``enable_engineer_reviewer_delegation`` 필드."""
    annotations = iterative_loop._LoopState.__annotations__
    assert "enable_engineer_reviewer_delegation" in annotations, (
        "_LoopState 에 delegation 필드 누락 — state pass-through 끊김"
    )


# ---------------------------------------------------------------------------
# 3. 3 chain function 시그니처
# ---------------------------------------------------------------------------


def test_classic_chain_has_delegation_parameter() -> None:
    """``_run_classic_chain`` 매개변수 — Track A 기본 경로."""
    sig = inspect.signature(analyze_and_implement._run_classic_chain)
    assert "enable_engineer_reviewer_delegation" in sig.parameters


def test_cli_chain_has_delegation_parameter() -> None:
    """``_run_cli_branch_chain_with_ui_context`` 매개변수."""
    sig = inspect.signature(
        analyze_and_implement._run_cli_branch_chain_with_ui_context
    )
    assert "enable_engineer_reviewer_delegation" in sig.parameters


def test_gui_chain_has_delegation_parameter() -> None:
    """``_run_gui_branch_chain`` 매개변수 — GUI 경로 (coder + reviewer pair)."""
    sig = inspect.signature(analyze_and_implement._run_gui_branch_chain)
    assert "enable_engineer_reviewer_delegation" in sig.parameters


# ---------------------------------------------------------------------------
# 4. agent 생성 시 적용 — file-text 기반 회귀 차단
# ---------------------------------------------------------------------------


def test_classic_chain_passes_delegation_to_engineer_and_reviewer() -> None:
    """classic chain 의 engineer + reviewer 생성 시 allow_delegation 전달."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_classic_chain[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    # engineer + reviewer 둘 다 allow_delegation 매개변수 전달
    assert (
        body.count("allow_delegation=enable_engineer_reviewer_delegation") >= 2
    ), (
        "_run_classic_chain 의 engineer + reviewer 둘 다 allow_delegation 전달 안 함"
    )


def test_gui_chain_passes_delegation_to_coder_and_reviewer() -> None:
    """GUI chain 에선 coder (GUI Code Generator) + reviewer 가 페어."""
    text = ANALYZE_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_run_gui_branch_chain[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert (
        body.count("allow_delegation=enable_engineer_reviewer_delegation") >= 2
    ), (
        "_run_gui_branch_chain 의 coder + reviewer 둘 다 allow_delegation 전달 안 함"
    )


# ---------------------------------------------------------------------------
# 5. iterative_loop 가 chain 으로 thread
# ---------------------------------------------------------------------------


def test_iterative_loop_threads_delegation_into_chain() -> None:
    """``_node_run_chain`` 이 state 의 delegation 값을 chain 호출에 전달."""
    text = LOOP_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_node_run_chain[\s\S]*?(?=\ndef\s|\Z)",
        text,
    )
    assert match is not None
    body = match.group(0)
    assert "enable_engineer_reviewer_delegation" in body, (
        "_node_run_chain 이 state 의 delegation 값을 chain 으로 thread 안 함"
    )


# ---------------------------------------------------------------------------
# 6. Smoke — delegation=True 로 호출해도 import 단계 깨지지 않음
# ---------------------------------------------------------------------------


def test_create_engineer_accepts_allow_delegation() -> None:
    """``create_python_engineer_agent(allow_delegation=True)`` import + 호출."""
    from src.agents.engineering import create_python_engineer_agent

    # 실제 Agent 인스턴스화는 LLM 의존이라 sig 만 확인
    sig = inspect.signature(create_python_engineer_agent)
    assert "allow_delegation" in sig.parameters


def test_create_code_reviewer_accepts_allow_delegation() -> None:
    """``create_code_reviewer_agent(allow_delegation=True)`` 시그니처."""
    from src.agents.qa import create_code_reviewer_agent

    sig = inspect.signature(create_code_reviewer_agent)
    assert "allow_delegation" in sig.parameters
