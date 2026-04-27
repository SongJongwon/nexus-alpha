# -*- coding: utf-8 -*-
"""src/workflows/_common.py 회귀 방지 테스트.

이슈 6 (PR #29, 2026-04-27): LLM 비결정적 본문 누락 시 자동 재시도하는
``retry_task_if_short`` 헬퍼의 동작 검증.

PR #28 4차 E2E 결과:
  - 16개 에이전트 중 12개는 본문 정상 출력, 4개는 Final Answer summary 한 줄만.
  - 동일 fix 패턴 (PR #25/#27) 이 다른 에이전트에선 작동 — LLM 의 통계적 행동이 원인.
  - 방어선 1: 짧은 raw 감지 → 동일 task 자동 재실행 (본 PR).
"""

from __future__ import annotations

from crewai import Task

from src.workflows._common import (
    SUSPICIOUS_OUTPUT_THRESHOLD,
    retry_short_tasks_in_chain,
    retry_task_if_short,
    task_output_text,
)


# ---------------------------------------------------------------------------
# 테스트 유틸 — 실제 Task 객체 + duck-typed output (Pydantic 검증 회피)
# ---------------------------------------------------------------------------


class _StubOutput:
    """task.output 에 붙일 duck-typed 객체. raw + agent 속성만 사용됨."""

    def __init__(self, raw: str, agent_role: str = "test-agent"):
        self.raw = raw

        class _Agent:
            role = agent_role

        self.agent = _Agent()


def _make_task() -> Task:
    """retry 로직만 테스트하므로 agent/context 는 None 으로 충분."""
    return Task(description="test task description", expected_output="anything")


def _set_output(task: Task, raw: str) -> None:
    """Pydantic validate_assignment 회피 — object.__setattr__ 로 우회."""
    object.__setattr__(task, "output", _StubOutput(raw))


# ---------------------------------------------------------------------------
# task_output_text — 기본 동작 (이슈 4/6 PR #25 의 짧은 raw 처리 검증과 동일)
# ---------------------------------------------------------------------------


def test_task_output_text_returns_long_raw_unchanged() -> None:
    task = _make_task()
    long_raw = "x" * (SUSPICIOUS_OUTPUT_THRESHOLD + 50)
    _set_output(task, long_raw)
    assert task_output_text(task) == long_raw


def test_task_output_text_returns_short_raw_unchanged() -> None:
    """짧아도 raw 자체는 그대로 반환 (경고는 production 에서만)."""
    task = _make_task()
    _set_output(task, "framework=tkinter, files=1개")
    assert task_output_text(task) == "framework=tkinter, files=1개"


def test_task_output_text_handles_none_output() -> None:
    task = _make_task()
    # task.output = None (default)
    assert task_output_text(task) == ""


# ---------------------------------------------------------------------------
# retry_task_if_short — 핵심 로직 (이슈 6 fix)
# ---------------------------------------------------------------------------


def test_retry_skips_when_output_already_long() -> None:
    """충분히 긴 출력은 재시도 안 함 — kickoff_fn 호출 0건."""
    task = _make_task()
    _set_output(task, "x" * (SUSPICIOUS_OUTPUT_THRESHOLD + 100))

    calls: list[Task] = []

    def fake_kickoff(retry_task: Task) -> None:
        calls.append(retry_task)

    result = retry_task_if_short(task, fake_kickoff)
    assert result is False
    assert calls == []


def test_retry_skips_when_output_empty() -> None:
    """빈 출력 (None) 도 재시도 안 함 — 회복 불가능 케이스 구분."""
    task = _make_task()
    # output = None default

    calls: list[Task] = []

    def fake_kickoff(retry_task: Task) -> None:
        calls.append(retry_task)

    result = retry_task_if_short(task, fake_kickoff)
    assert result is False
    assert calls == []


def test_retry_replaces_short_output_with_long_retry() -> None:
    """짧은 raw → 재시도가 긴 raw 반환 → task.output 교체."""
    task = _make_task()
    _set_output(task, "short summary only")  # 18자

    def fake_kickoff(retry_task: Task) -> None:
        _set_output(retry_task, "y" * (SUSPICIOUS_OUTPUT_THRESHOLD + 100))

    result = retry_task_if_short(task, fake_kickoff, max_retries=1)
    assert result is True
    assert len(task_output_text(task).strip()) >= SUSPICIOUS_OUTPUT_THRESHOLD


def test_retry_keeps_original_when_all_retries_short() -> None:
    """재시도가 다 짧으면 원본 유지 — false 반환."""
    task = _make_task()
    _set_output(task, "short A")

    def fake_kickoff(retry_task: Task) -> None:
        _set_output(retry_task, "still short")  # 11자

    result = retry_task_if_short(task, fake_kickoff, max_retries=2)
    assert result is False
    assert task_output_text(task) == "short A"


def test_retry_respects_max_retries_cap() -> None:
    """max_retries=2 면 정확히 2번까지만 시도 (LLM 비용 보호)."""
    task = _make_task()
    _set_output(task, "tiny")

    call_count = [0]

    def fake_kickoff(retry_task: Task) -> None:
        call_count[0] += 1
        _set_output(retry_task, "still tiny")

    retry_task_if_short(task, fake_kickoff, max_retries=2)
    assert call_count[0] == 2


def test_retry_handles_kickoff_exception_gracefully() -> None:
    """kickoff_fn 예외 시 원본 유지하고 다음 시도. 외부로 propagate 안 함."""
    task = _make_task()
    _set_output(task, "short")

    call_count = [0]

    def fake_kickoff(retry_task: Task) -> None:
        call_count[0] += 1
        raise RuntimeError("simulated kickoff crash")

    result = retry_task_if_short(task, fake_kickoff, max_retries=2)
    assert result is False
    assert task_output_text(task) == "short"
    # max_retries 만큼 시도하되 매번 catch
    assert call_count[0] == 2


def test_retry_succeeds_on_second_attempt() -> None:
    """첫 시도 짧음 → 두 번째 시도 길음 → 두 번째 출력으로 교체."""
    task = _make_task()
    _set_output(task, "short")

    attempts = [0]

    def fake_kickoff(retry_task: Task) -> None:
        attempts[0] += 1
        if attempts[0] == 1:
            _set_output(retry_task, "still short")
        else:
            _set_output(retry_task, "z" * (SUSPICIOUS_OUTPUT_THRESHOLD + 50))

    result = retry_task_if_short(task, fake_kickoff, max_retries=2)
    assert result is True
    assert attempts[0] == 2
    assert len(task_output_text(task).strip()) >= SUSPICIOUS_OUTPUT_THRESHOLD


# ---------------------------------------------------------------------------
# retry_short_tasks_in_chain — production 헬퍼 (pytest 환경 skip 검증)
# ---------------------------------------------------------------------------


def test_retry_short_tasks_in_chain_skips_under_pytest() -> None:
    """pytest 환경에선 FakeProvider 의 본질적 짧은 출력 false-positive 방지를 위해 skip."""
    task = _make_task()
    _set_output(task, "would normally trigger retry")

    retried = retry_short_tasks_in_chain([task])
    assert retried == []
    # 원본도 변경 없어야 함
    assert task_output_text(task) == "would normally trigger retry"


def test_threshold_constant_is_120() -> None:
    """이슈 4/5/6 전체에서 일관된 임계값 보장 — 변경 시 의도적 결정 필요."""
    assert SUSPICIOUS_OUTPUT_THRESHOLD == 120
