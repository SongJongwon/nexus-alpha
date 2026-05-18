# -*- coding: utf-8 -*-
"""PR #170 — fail-silent Track B 잔재 fix (CodeQASkipped + _adapt_automate 4 케이스 분기).

배경 (2026-05-18 fail-silent 코드 전반 검색):
    PR #160a+b (Vision QA false-FAIL + retry build 진단) + PR #162 (결과 패널 build
    SKIPPED 진단) 처방의 *잔재* 검색 결과 Track B 자동화 경로에서 2 후보 발견:

    후보 #1 — automate_workflow._run_track_b_qa_loop (시그니처 A):
        ``except ImportError: return pytest_suite_text, None`` +
        ``except Exception: return pytest_suite_text, None`` 모두 단일 ``None`` 반환
        → caller 가 *환경 부재 (ImportError)* 와 *실 실패 (Exception)* 를 구분 못 함.
        주석에 "silent failure" 명시 (의도) 하나 진단 정보 미보존.

    후보 #2 — iterative_loop._adapt_automate_to_chain_result (시그니처 B):
        ``code_qa.summary_line()`` 호출 실패 시 ``qa_review = ""`` + 모든 falsy 케이스
        (code_qa=None / summary_line attr 없음 / 예외 / 빈 문자열) 동일 fallback
        ``"(no QA review — Track B 자동화 산출)"`` → 4 케이스 디버깅 불가.

PR #170 처방:

    A. ``CodeQASkipped`` dataclass + ``_run_code_qa_with_skip_reason`` 헬퍼:
        - ``success=False`` + ``skip_reason: str`` + ``summary_line() -> str`` 만
          (CodeQAResult duck-type 호환).
        - ImportError → reason="qa_feedback_loop 미가용 (ImportError: ...)"
        - 그 외 Exception → reason="<type>: <msg>"
        - run_code_qa 정상 응답 → CodeQAResult 그대로 pass-through

    B. ``_adapt_automate_to_chain_result`` 4 케이스 분기:
        - code_qa=None → "(no QA review — Track B 자동화 산출)"
        - code_qa.summary_line attr 없음 → type 정보 surface
        - summary_line() 예외 → exception type+msg surface
        - 빈 문자열 반환 → "(no QA review — summary_line 빈 문자열)"

본 테스트:
    1. ``CodeQASkipped`` dataclass 구조 + summary_line 형식
    2. ``_run_code_qa_with_skip_reason`` ImportError / Exception / 정상 3 분기
    3. ``_run_track_b_qa_loop`` 가 helper 를 사용해서 단일 None 회귀 차단
    4. ``_adapt_automate_to_chain_result`` 4 케이스 메시지 차별화
"""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.workflows.automate_workflow import (
    CodeQASkipped,
    _run_code_qa_with_skip_reason,
)


# ---------------------------------------------------------------------------
# 1. CodeQASkipped dataclass — duck-type 호환
# ---------------------------------------------------------------------------


def test_codeqaskipped_is_frozen_dataclass() -> None:
    assert is_dataclass(CodeQASkipped)
    skipped = CodeQASkipped(skip_reason="x")
    with pytest.raises(Exception):
        skipped.skip_reason = "y"  # type: ignore[misc]


def test_codeqaskipped_success_is_false_by_default() -> None:
    skipped = CodeQASkipped(skip_reason="anything")
    assert skipped.success is False


def test_codeqaskipped_summary_line_includes_reason() -> None:
    skipped = CodeQASkipped(skip_reason="ImportError: qa_feedback_loop 미가용")
    line = skipped.summary_line()
    assert line.startswith("[CODE_QA SKIPPED]")
    assert "ImportError" in line
    assert "qa_feedback_loop 미가용" in line


def test_codeqaskipped_is_duck_type_compatible_with_codeqaresult() -> None:
    """CodeQAResult 와 동일 attr (``success`` + ``summary_line()``) 만 caller 가 사용."""
    skipped = CodeQASkipped(skip_reason="x")
    assert hasattr(skipped, "success")
    assert hasattr(skipped, "summary_line")
    assert callable(skipped.summary_line)


# ---------------------------------------------------------------------------
# 2. _run_code_qa_with_skip_reason — 3 분기 + import 경로 회귀 차단
# ---------------------------------------------------------------------------


def test_run_code_qa_import_path_is_actually_valid() -> None:
    """``run_code_qa`` import 경로 정정 회귀 차단 (PR #170 핵심).

    PR #81 이래로 production 에서 ``from src.workflows.qa_feedback_loop import
    run_code_qa`` 가 영원히 ImportError → ``_run_track_b_qa_loop`` 가
    ``code_qa_result=None`` 영구 반환 → Track B enable_qa_loop=True 여도 실 code_qa
    단 한 번도 실행 안 됨. fail-silent 가 본 결함을 *마스킹*. 본 PR 이 사용하는
    ``src.agents.qa.code_qa_executor`` 경로가 실제로 import 가능 + callable.
    """
    from src.agents.qa.code_qa_executor import run_code_qa  # noqa: PLC0415

    assert callable(run_code_qa)


def test_run_code_qa_legacy_path_is_unreachable() -> None:
    """*잘못된* 기존 import 경로가 여전히 ImportError → 본 PR fix 가 필요했던 evidence."""
    with pytest.raises(ImportError):
        from src.workflows.qa_feedback_loop import (  # noqa: F401, PLC0415
            run_code_qa,
        )


def test_run_code_qa_returns_codeqaresult_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_code_qa 정상 응답 → 그대로 pass-through (wrapping 없음)."""
    sentinel = SimpleNamespace(success=True, summary_line=lambda: "[CODE_QA PASS] x")

    def fake_run_code_qa(code_dir: Path) -> Any:
        assert code_dir == tmp_path / "code"
        return sentinel

    import src.agents.qa.code_qa_executor as qa_mod  # noqa: PLC0415
    monkeypatch.setattr(qa_mod, "run_code_qa", fake_run_code_qa)

    result = _run_code_qa_with_skip_reason(tmp_path)
    assert result is sentinel
    assert not isinstance(result, CodeQASkipped)


def test_run_code_qa_returns_skipped_on_import_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """qa_feedback_loop import 실패 → CodeQASkipped + reason 보존."""
    import builtins  # noqa: PLC0415

    real_import = builtins.__import__

    def patched_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "src.agents.qa.code_qa_executor":
            raise ImportError("simulated missing code_qa_executor")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", patched_import)

    result = _run_code_qa_with_skip_reason(tmp_path)
    assert isinstance(result, CodeQASkipped)
    assert "code_qa_executor 미가용" in result.skip_reason
    assert "ImportError" in result.skip_reason
    assert "simulated missing code_qa_executor" in result.skip_reason


def test_run_code_qa_returns_skipped_on_runtime_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_code_qa 가 예외 발생 → CodeQASkipped + 예외 type + msg 보존."""

    def fake_run_code_qa(code_dir: Path) -> Any:
        raise RuntimeError("pytest binary missing")

    import src.agents.qa.code_qa_executor as qa_mod  # noqa: PLC0415
    monkeypatch.setattr(qa_mod, "run_code_qa", fake_run_code_qa)

    result = _run_code_qa_with_skip_reason(tmp_path)
    assert isinstance(result, CodeQASkipped)
    assert "RuntimeError" in result.skip_reason
    assert "pytest binary missing" in result.skip_reason


def test_run_code_qa_skipped_summary_line_surfaces_via_duck_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CodeQASkipped 가 결과 패널 (summary_line caller) 에서 진단 가시화."""

    def fake_run_code_qa(code_dir: Path) -> Any:
        raise ValueError("ruff config invalid")

    import src.agents.qa.code_qa_executor as qa_mod  # noqa: PLC0415
    monkeypatch.setattr(qa_mod, "run_code_qa", fake_run_code_qa)

    result = _run_code_qa_with_skip_reason(tmp_path)
    line = result.summary_line()
    assert "[CODE_QA SKIPPED]" in line
    assert "ValueError" in line
    assert "ruff config invalid" in line


# ---------------------------------------------------------------------------
# 3. _adapt_automate_to_chain_result — 4 케이스 차별화
# ---------------------------------------------------------------------------


def _adapt(code_qa: Any) -> str:
    """``_adapt_automate_to_chain_result`` 의 qa_review 만 추출 (테스트 헬퍼)."""
    from src.workflows.iterative_loop import (  # noqa: PLC0415
        _adapt_automate_to_chain_result,
    )

    automate_result = SimpleNamespace(
        saved_dir=None,
        saved_code_files=[],
        agent_output="",
        code_qa_result=code_qa,
        executor_result=None,
        publish_result=None,
    )
    chain_result = _adapt_automate_to_chain_result(automate_result)
    return chain_result.qa_review


def test_adapt_qa_review_when_code_qa_is_none() -> None:
    """code_qa=None → 기존 호환 fallback (Track B 자동화 산출)."""
    qa_review = _adapt(None)
    assert qa_review == "(no QA review — Track B 자동화 산출)"


def test_adapt_qa_review_when_code_qa_has_no_summary_line() -> None:
    """code_qa 가 summary_line attr 없음 → type 정보 surface."""

    class NoSummary:
        success = False

    qa_review = _adapt(NoSummary())
    assert "no summary_line" in qa_review
    assert "NoSummary" in qa_review  # type 정보 surface


def test_adapt_qa_review_when_summary_line_raises() -> None:
    """summary_line() 예외 → exception type + msg surface."""

    class Broken:
        success = False

        def summary_line(self) -> str:
            raise RuntimeError("formatter crashed")

    qa_review = _adapt(Broken())
    assert "summary_line 호출 실패" in qa_review
    assert "RuntimeError" in qa_review
    assert "formatter crashed" in qa_review


def test_adapt_qa_review_when_summary_line_returns_empty() -> None:
    """summary_line() 빈 문자열 → 별도 fallback (다른 None 케이스와 구분)."""

    class EmptyOutput:
        success = False

        def summary_line(self) -> str:
            return ""

    qa_review = _adapt(EmptyOutput())
    assert qa_review == "(no QA review — summary_line 빈 문자열)"


def test_adapt_qa_review_when_summary_line_returns_valid_string() -> None:
    """summary_line() 정상 응답 → 그 문자열 그대로 qa_review."""

    class GoodResult:
        success = True

        def summary_line(self) -> str:
            return "[CODE_QA PASS] pytest=12/12 | ruff=0 | total=3.21s"

    qa_review = _adapt(GoodResult())
    assert qa_review == "[CODE_QA PASS] pytest=12/12 | ruff=0 | total=3.21s"


def test_adapt_qa_review_with_codeqaskipped_surfaces_skip_reason() -> None:
    """CodeQASkipped (fix #1 산출) 가 _adapt 까지 propagate → 결과 패널 진단 가시화."""
    skipped = CodeQASkipped(skip_reason="ImportError: simulated")
    qa_review = _adapt(skipped)
    assert "[CODE_QA SKIPPED]" in qa_review
    assert "ImportError" in qa_review
    assert "simulated" in qa_review
