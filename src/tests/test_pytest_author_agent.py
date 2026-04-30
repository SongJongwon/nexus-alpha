# -*- coding: utf-8 -*-
"""Pytest Author 에이전트 + 워크플로우 통합 회귀 방지 테스트 (PR #58).

검증 축:
  1. 에이전트 생성 smoke (`create_pytest_author_agent` import + instantiate)
  2. backstory 의 *절대 규칙* 키워드 포함 (monkeypatch / mainloop / sys.path /
     결정론적 / 5개 시나리오) — 회귀 방지의 의도 문서화
  3. `_build_pytest_author_task` 의 description / context / agent 검증
  4. `_save_classic_artifacts` 가 ``pytest_suite`` 인자를 받아 ```python```
     블록을 ``code/`` 디렉터리에 ``test_*.py`` 로 추출
  5. 워크플로우 분기 통합 — 3개 분기 (`_run_classic_chain` /
     `_run_cli_branch_chain_with_ui_context` / `_run_gui_branch_chain`) 가
     모두 ``create_pytest_author_agent`` 와 ``_build_pytest_author_task`` 를
     호출하는지 source-level grep
  6. ``WorkflowResult`` 에 ``pytest_suite`` 필드 존재 (backward compat
     기본값 빈 문자열)

LLM 호출 없는 테스트만 — 풀체인 PASS 검증은 10차 E2E 7차에서.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from src.agents.qa import (
    PYTEST_AUTHOR_BACKSTORY,
    PYTEST_AUTHOR_GOAL,
    PYTEST_AUTHOR_NAME,
    PYTEST_AUTHOR_ROLE,
    create_pytest_author_agent,
)


# ---------------------------------------------------------------------------
# 1. 에이전트 생성 smoke
# ---------------------------------------------------------------------------


def test_pytest_author_agent_factory_exposes_metadata() -> None:
    """모듈 메타데이터 (NAME / ROLE / GOAL / BACKSTORY) 가 모두 비어있지 않음."""
    assert PYTEST_AUTHOR_NAME == "PytestAuthor"
    assert PYTEST_AUTHOR_ROLE.startswith("Senior Pytest Author")
    assert PYTEST_AUTHOR_GOAL  # non-empty
    assert PYTEST_AUTHOR_BACKSTORY  # non-empty


def test_pytest_author_factory_is_callable_with_default_args() -> None:
    """``create_pytest_author_agent()`` 가 인자 없이 호출 가능 — NexusAlphaLLM
    자동 주입 패턴 (다른 QA 에이전트와 동일)."""
    sig = inspect.signature(create_pytest_author_agent)
    # llm / verbose / max_iter / allow_delegation 모두 default 가짐
    for name in ("llm", "verbose", "max_iter", "allow_delegation"):
        assert name in sig.parameters
        assert sig.parameters[name].default is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 2. backstory 절대 규칙 키워드 포함 — 회귀 방지
# ---------------------------------------------------------------------------


def test_backstory_mentions_monkeypatch_for_gui_safety() -> None:
    """GUI 윈도우 미표시 — monkeypatch 패턴 명시 (절대 규칙 #2)."""
    assert "monkeypatch" in PYTEST_AUTHOR_BACKSTORY
    assert "mainloop" in PYTEST_AUTHOR_BACKSTORY
    # 한국어/영어 GUI 라이브러리 키워드 포함
    assert "tkinter" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_mentions_sys_path_insert_for_import_safety() -> None:
    """test 파일이 같은 디렉터리 entry 를 import 할 수 있도록 sys.path 보정 명시
    (절대 규칙 #3)."""
    assert "sys.path.insert" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_mentions_deterministic_assertion() -> None:
    """결정론적 assertion 강조 — vacuous truthy-only 검증 회피 (절대 규칙 #4)."""
    assert "결정론적" in PYTEST_AUTHOR_BACKSTORY
    assert "vacuous" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_requires_minimum_5_scenarios() -> None:
    """최소 5개 시나리오 — happy + edge + error 커버리지 보장 (절대 규칙 #5)."""
    assert "5개 시나리오" in PYTEST_AUTHOR_BACKSTORY or "최소 5개" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_requires_final_answer_pattern() -> None:
    """``Final Answer:`` 우선 + 본문 후속 — 이슈 4/6 회귀 방지."""
    assert "Final Answer:" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_forbids_app_mainloop_call() -> None:
    """``app.mainloop()`` 직접 호출 절대 금지 명시 — pytest hang 방지."""
    assert "app.mainloop" in PYTEST_AUTHOR_BACKSTORY


# ---------------------------------------------------------------------------
# 3. _build_pytest_author_task 시그니처 + description
# ---------------------------------------------------------------------------


def test_build_pytest_author_task_returns_task_with_code_context() -> None:
    """``_build_pytest_author_task(pytest_author, code_task)`` 가 code_task 를
    context 로 갖는 Task 반환. CrewAI Task 가 agent 인자에 Pydantic 검증을 걸므로
    실 ``create_pytest_author_agent()`` 로 만든 인스턴스를 사용 — LLM 호출은
    Task.execute 시점에만 일어나므로 본 테스트에서 발생하지 않음."""
    from crewai import Task

    from src.workflows.analyze_and_implement import _build_pytest_author_task

    code_task = Task(description="dummy code", expected_output="anything")
    pytest_author = create_pytest_author_agent(verbose=False)

    task = _build_pytest_author_task(pytest_author, code_task)

    assert isinstance(task, Task)
    assert code_task in (task.context or [])
    assert task.agent is pytest_author
    # description 에 절대 규칙 핵심 키워드 포함
    assert "monkeypatch" in task.description
    assert "sys.path.insert" in task.description
    assert "결정론적" in task.description
    assert "최소 5개" in task.description


# ---------------------------------------------------------------------------
# 4. _save_classic_artifacts — pytest_suite 인자 처리
# ---------------------------------------------------------------------------


def test_save_classic_artifacts_extracts_pytest_blocks_into_code_dir(tmp_path: Path) -> None:
    """``pytest_suite`` 본문의 ```python``` 블록이 ``code/`` 디렉터리에
    ``test_*.py`` 로 저장되고, 반환 목록에 합산됨."""
    from src.workflows.analyze_and_implement import _save_classic_artifacts

    engineer_md = (
        "```python\n"
        "# file: calculator.py\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n"
    )
    pytest_md = (
        "## 테스트 스위트\n\n"
        "```python\n"
        "# file: test_calculator.py\n"
        "from calculator import add\n"
        "def test_add(): assert add(2, 3) == 5\n"
        "```\n"
    )

    code_paths = _save_classic_artifacts(
        tmp_path,
        user_request="테스트 요청",
        cto_strategy="cto",
        analyst_brief="analyst",
        engineer_output=engineer_md,
        qa_review="qa",
        pytest_suite=pytest_md,
    )

    saved_names = sorted(p.name for p in code_paths)
    assert "calculator.py" in saved_names
    assert "test_calculator.py" in saved_names
    # 05_pytest_suite.md 도 함께 저장됨
    assert (tmp_path / "05_pytest_suite.md").exists()
    assert (tmp_path / "05_pytest_suite.md").read_text(encoding="utf-8") == pytest_md
    # 빈 pytest_suite=""(default) 시 05 파일 미생성 — backward compat
    no_suite_dir = tmp_path / "no_suite"
    no_suite_dir.mkdir()
    code_paths2 = _save_classic_artifacts(
        no_suite_dir,
        user_request="x",
        cto_strategy="x",
        analyst_brief="x",
        engineer_output=engineer_md,
        qa_review="x",
    )
    assert not (no_suite_dir / "05_pytest_suite.md").exists()
    # 그래도 calculator.py 는 추출됨
    assert any(p.name == "calculator.py" for p in code_paths2)


def test_save_classic_artifacts_default_pytest_suite_empty_is_backward_compat(
    tmp_path: Path,
) -> None:
    """``pytest_suite`` 인자 default 가 빈 문자열 — 기존 호출 시그니처 100% 호환."""
    import inspect as _inspect

    from src.workflows.analyze_and_implement import _save_classic_artifacts

    sig = _inspect.signature(_save_classic_artifacts)
    assert sig.parameters["pytest_suite"].default == ""


# ---------------------------------------------------------------------------
# 5. 워크플로우 3개 분기 통합 — source-level grep
# ---------------------------------------------------------------------------

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / "workflows" / "analyze_and_implement.py"
)


def test_workflow_imports_pytest_author_factory() -> None:
    """analyze_and_implement.py 가 ``create_pytest_author_agent`` 를 import."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "create_pytest_author_agent" in src
    assert "from src.agents.qa import" in src


def test_workflow_calls_build_pytest_author_task_in_three_branches() -> None:
    """3개 분기 (classic / cli / gui) 가 모두 ``_build_pytest_author_task`` 호출."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    # 호출 횟수 정확히 3 — 분기당 1회
    occurrences = src.count("_build_pytest_author_task(")
    assert occurrences >= 4, (
        f"_build_pytest_author_task 호출이 4회 미만 ({occurrences}). "
        "정의(1) + classic(1) + cli(1) + gui(1) = 최소 4회 기대."
    )


def test_workflow_gui_branch_saves_14_pytest_suite_md() -> None:
    """GUI 분기는 ``14_pytest_suite.md`` 로 저장 (10~13 다음 번호)."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "14_pytest_suite.md" in src


def test_workflow_classic_and_cli_save_05_pytest_suite_md() -> None:
    """classic / cli 분기는 ``05_pytest_suite.md`` 로 저장 (00~04 다음 번호) — 그러나
    저장은 ``_save_classic_artifacts`` 안에서 한 번만 정의됨."""
    src = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "05_pytest_suite.md" in src


# ---------------------------------------------------------------------------
# 6. WorkflowResult.pytest_suite — backward compat 기본값
# ---------------------------------------------------------------------------


def test_workflow_result_has_pytest_suite_field_with_default_empty_string() -> None:
    from src.workflows.analyze_and_implement import WorkflowResult

    fields = WorkflowResult.__dataclass_fields__
    assert "pytest_suite" in fields
    # backward compat — 기본값이 있어 기존 호출자 변경 불요
    assert fields["pytest_suite"].default == ""


def test_workflow_result_can_be_constructed_without_pytest_suite() -> None:
    """기존 호출자는 ``pytest_suite`` 인자 없이 생성 가능."""
    from src.workflows.analyze_and_implement import WorkflowResult

    result = WorkflowResult(
        user_request="x",
        cto_strategy="x",
        analyst_brief="x",
        engineer_output="x",
        qa_review="x",
        saved_dir=Path("/tmp/x"),
    )
    assert result.pytest_suite == ""


# ---------------------------------------------------------------------------
# PR #59 — output_pydantic schema (PytestSuiteOutput) + backstory 강화
#
# 배경: 10차 E2E 7차 (PR #58) 에서 Pytest Author 가 backstory 의 출력 규약을
# 무시하고 Final Answer 한 줄(30바이트)만 출력 → test_*.py 추출 실패.
# 처방: schema 강제 (방어선 2) + backstory/description 분량 임계 명시.
# ---------------------------------------------------------------------------


def test_pytest_suite_output_schema_has_four_required_fields() -> None:
    """PytestSuiteOutput 이 4개 필드 (summary / test_strategy / test_code_block /
    intent_and_limits) 모두 정의 — LLM 이 어느 하나라도 누락 시 task 미완료."""
    from src.workflows._schemas import PytestSuiteOutput

    fields = set(PytestSuiteOutput.model_fields.keys())
    expected = {"summary", "test_strategy", "test_code_block", "intent_and_limits"}
    assert fields == expected, f"필드 차이: 누락={expected-fields}, 잉여={fields-expected}"


def test_pytest_suite_output_to_markdown_renders_three_sections() -> None:
    """``to_markdown()`` 이 PR #58 산출 파일 형식과 호환 (## 테스트 스위트 + ### 1~3)."""
    from src.workflows._schemas import PytestSuiteOutput

    m = PytestSuiteOutput(
        summary="test_calculator.py 5 scenarios",
        test_strategy="entry calculator.py 의 _on_press 메서드를 monkeypatch CTk.__init__ 후 직접 호출하는 패턴으로 5개 시나리오 작성. happy path 1 + edge case (0 / 음수 / 큰수) 3 + ZeroDivision error 1.",
        test_code_block="```python\n# file: test_calculator.py\nimport sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\n\ndef test_add(): assert 1 + 1 == 2\ndef test_sub(): assert 5 - 3 == 2\ndef test_mul(): assert 4 * 3 == 12\ndef test_div(): assert 10 / 2 == 5\ndef test_div_zero():\n    import pytest\n    with pytest.raises(ZeroDivisionError):\n        1/0\n```",
        intent_and_limits="시나리오 #1~5 모두 결정론적 assertion. GUI event loop 자체와 키보드 이벤트는 미검증 (별도 gui_test 가 담당).",
    )
    md = m.to_markdown()
    assert "## 테스트 스위트" in md
    assert "### 1. 테스트 전략" in md
    assert "### 2. 실 테스트 코드" in md
    assert "### 3. 검증 의도 + 한계" in md
    # ```python``` 블록 보존
    assert "```python" in md
    assert "# file: test_calculator.py" in md


def test_build_pytest_author_task_skips_output_pydantic_under_pytest() -> None:
    """pytest 환경에선 output_pydantic 미적용 — FakeProvider 호환 (다른 task 빌더와 동일 패턴)."""
    from crewai import Task

    from src.workflows.analyze_and_implement import _build_pytest_author_task

    code_task = Task(description="dummy", expected_output="x")
    pytest_author = create_pytest_author_agent(verbose=False)

    task = _build_pytest_author_task(pytest_author, code_task)
    # pytest 환경 ⇒ output_pydantic 은 None 유지
    assert task.output_pydantic is None


def test_build_pytest_author_task_attaches_schema_outside_pytest(monkeypatch) -> None:
    """pytest 모듈을 임시 제거한 환경 시뮬레이션 — output_pydantic=PytestSuiteOutput 적용."""
    import sys as _sys

    from crewai import Task

    from src.workflows._schemas import PytestSuiteOutput
    from src.workflows.analyze_and_implement import _build_pytest_author_task

    # sys.modules 에서 pytest 만 임시 제거 (FakeProvider 호환 분기 우회)
    saved_pytest = _sys.modules.pop("pytest", None)
    try:
        code_task = Task(description="dummy", expected_output="x")
        pytest_author = create_pytest_author_agent(verbose=False)
        task = _build_pytest_author_task(pytest_author, code_task)
        assert task.output_pydantic is PytestSuiteOutput
    finally:
        if saved_pytest is not None:
            _sys.modules["pytest"] = saved_pytest


def test_build_pytest_author_task_description_mentions_minimum_size_threshold() -> None:
    """description 에 본문 분량 임계 (최소 800자, 코드 30줄 등) 명시 — PR #58 7차 회귀 차단."""
    from crewai import Task

    from src.workflows.analyze_and_implement import _build_pytest_author_task

    code_task = Task(description="dummy", expected_output="x")
    pytest_author = create_pytest_author_agent(verbose=False)
    task = _build_pytest_author_task(pytest_author, code_task)

    # 분량 임계 키워드
    assert "800자" in task.description, "전체 출력 800자 임계 누락"
    assert "5개" in task.description, "def test_* 5개 임계 누락"
    assert "PytestSuiteOutput" in task.description or "output_pydantic" in task.description


def test_backstory_explicitly_warns_against_one_line_only_output() -> None:
    """PR #58 7차 회귀 (Final Answer 한 줄 30바이트) 를 backstory 가 명시적으로 경고."""
    assert "한 줄 요약만" in PYTEST_AUTHOR_BACKSTORY or "절대 반복 금지" in PYTEST_AUTHOR_BACKSTORY
    assert "최소 800자" in PYTEST_AUTHOR_BACKSTORY
    # PR #58 7차 사례 인용 (회귀 추적용)
    assert "PR #58" in PYTEST_AUTHOR_BACKSTORY or "30바이트" in PYTEST_AUTHOR_BACKSTORY


def test_backstory_documents_output_pydantic_schema() -> None:
    """backstory 가 output_pydantic 강제와 4 필드 명시 — LLM 이 schema 인지."""
    assert "output_pydantic" in PYTEST_AUTHOR_BACKSTORY
    assert "PytestSuiteOutput" in PYTEST_AUTHOR_BACKSTORY
    for field in ("summary", "test_strategy", "test_code_block", "intent_and_limits"):
        assert field in PYTEST_AUTHOR_BACKSTORY, f"backstory 에 schema 필드 누락: {field}"
