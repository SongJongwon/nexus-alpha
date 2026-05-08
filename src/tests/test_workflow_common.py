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
    kickoff_with_converter_rescue,
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


# ---------------------------------------------------------------------------
# kickoff_with_converter_rescue — PR #53 (이슈 6 방어선 3)
# ---------------------------------------------------------------------------


from pydantic import BaseModel  # noqa: E402

from src.workflows._common import _ConverterError  # noqa: E402


class _DummySchema(BaseModel):
    summary: str


class _FakeCrew:
    """Crew 흉내 — kickoff() 호출 횟수 추적 + 시퀀스 기반 결과 / 예외 분기."""

    def __init__(self, results):
        # results: callable() 또는 예외 인스턴스 / 정상 리턴 값 시퀀스
        self.results = list(results)
        self.kickoff_calls = 0

    def kickoff(self):
        self.kickoff_calls += 1
        if not self.results:
            return "exhausted"
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _converter_error(msg: str = "Agent must be provided"):
    """ConverterError 인스턴스 (CrewAI 미가용 시 RuntimeError 로 fallback)."""
    if _ConverterError is None:
        return RuntimeError(msg)
    return _ConverterError(msg)


def test_rescue_happy_path_no_exception_no_retry() -> None:
    """예외 없을 때 kickoff 1회, output_pydantic 미변경."""
    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=["OK"])

    result = kickoff_with_converter_rescue(crew, [task])

    assert result == "OK"
    assert crew.kickoff_calls == 1
    assert task.output_pydantic is _DummySchema  # 손대지 않음


def test_rescue_strips_pydantic_and_retries_on_converter_error() -> None:
    """ConverterError 시 output_pydantic=None 으로 벗기고 1회 재시도."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=[_converter_error(), "RECOVERED"])

    result = kickoff_with_converter_rescue(crew, [task])

    assert result == "RECOVERED"
    assert crew.kickoff_calls == 2
    assert task.output_pydantic is None  # 벗겨짐


def test_rescue_strips_multiple_tasks_with_pydantic() -> None:
    """체인 내 여러 task 의 output_pydantic 모두 벗김."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    task_a = _make_task()
    task_b = _make_task()
    task_c = _make_task()
    object.__setattr__(task_a, "output_pydantic", _DummySchema)
    object.__setattr__(task_b, "output_pydantic", _DummySchema)
    # task_c 는 output_pydantic 없음
    object.__setattr__(task_c, "output_pydantic", None)

    crew = _FakeCrew(results=[_converter_error(), "RECOVERED"])

    kickoff_with_converter_rescue(crew, [task_a, task_b, task_c])

    assert task_a.output_pydantic is None
    assert task_b.output_pydantic is None
    assert task_c.output_pydantic is None  # 변화 없음


def test_rescue_reraises_when_no_tasks_have_pydantic() -> None:
    """벗길 output_pydantic 이 없으면 원본 예외 재상승 — 다른 원인의 ConverterError 일 수 있음."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    task = _make_task()
    object.__setattr__(task, "output_pydantic", None)
    crew = _FakeCrew(results=[_converter_error("unrelated"), "would-not-reach"])

    import pytest

    with pytest.raises(_ConverterError):
        kickoff_with_converter_rescue(crew, [task])
    assert crew.kickoff_calls == 1


def test_rescue_max_rescue_zero_disables_recovery() -> None:
    """max_rescue=0 이면 rescue 비활성 — 즉시 raise."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=[_converter_error()])

    import pytest

    with pytest.raises(_ConverterError):
        kickoff_with_converter_rescue(crew, [task], max_rescue=0)
    assert crew.kickoff_calls == 1
    # max_rescue=0 이면 벗기기조차 안 함
    assert task.output_pydantic is _DummySchema


def test_rescue_propagates_non_converter_errors() -> None:
    """ConverterError 가 아닌 예외 (RuntimeError 등) 는 rescue 안 함, 그대로 propagate."""
    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=[ValueError("unrelated bug")])

    import pytest

    with pytest.raises(ValueError, match="unrelated bug"):
        kickoff_with_converter_rescue(crew, [task])
    assert crew.kickoff_calls == 1
    assert task.output_pydantic is _DummySchema  # 변경 없음


def test_rescue_only_calls_kickoff_twice_max() -> None:
    """rescue 후 2번째 kickoff 도 ConverterError → max_rescue=1 이면 raise (총 2회)."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=[_converter_error(), _converter_error("second")])

    import pytest

    with pytest.raises(_ConverterError):
        kickoff_with_converter_rescue(crew, [task], max_rescue=1)
    assert crew.kickoff_calls == 2  # 1차 실패 + rescue 1회 = 2


# ---------------------------------------------------------------------------
# PR #53 v2 — ValidationError 도 rescue (10차 E2E 4차 Installer Creator 사례)
# ---------------------------------------------------------------------------


def _validation_error():
    """Pydantic ValidationError 인스턴스 — Installer Creator 사례 재현용."""
    from pydantic import BaseModel

    class _Throw(BaseModel):
        x: int

    try:
        _Throw.model_validate_json('{{not-valid-json}}')
    except Exception as e:
        return e
    raise AssertionError("expected ValidationError but none raised")


def test_rescue_strips_pydantic_and_retries_on_validation_error() -> None:
    """CrewAI handle_partial_json 의 _JSON_PATTERN 이 비-JSON {..} 매칭해 raw
    ValidationError escape 케이스 (10차 E2E 4차 Installer Creator 패턴) 도 rescue."""
    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)
    crew = _FakeCrew(results=[_validation_error(), "RECOVERED"])

    result = kickoff_with_converter_rescue(crew, [task])

    assert result == "RECOVERED"
    assert crew.kickoff_calls == 2
    assert task.output_pydantic is None  # 벗겨짐


def test_rescue_validation_error_no_pydantic_reraises() -> None:
    """output_pydantic 없는 task 에 ValidationError 만 raise → rescue 안 함."""
    task = _make_task()
    object.__setattr__(task, "output_pydantic", None)
    crew = _FakeCrew(results=[_validation_error()])

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        kickoff_with_converter_rescue(crew, [task])
    assert crew.kickoff_calls == 1


def test_rescuable_exc_classes_includes_both_when_available() -> None:
    """rescuable 예외 set 에 ConverterError + ValidationError 모두 포함 (정상 환경)."""
    from src.workflows._common import _rescuable_exc_classes

    classes = _rescuable_exc_classes()
    if _ConverterError is not None:
        assert _ConverterError in classes
    from pydantic import ValidationError

    assert ValidationError in classes


# ---------------------------------------------------------------------------
# PR #54 — Capture-before-rescue (A안)
#
# 핵심: Task._export_output(result) 가 raise 하면 그 task 의 output_pydantic 만
# in-place 로 None 처리한 뒤 *같은 raw* 로 재호출 → schema 만 잃고 본문 보존,
# crew 재 kickoff 불필요. 5차 E2E 의 부수효과 (rescue 후 짧은 출력) 해결.
# ---------------------------------------------------------------------------


class _ExportingFakeCrew:
    """kickoff() 가 등록된 task 들의 ``_export_output(raw)`` 를 호출 — A안의
    클래스 레벨 patch 가 실제로 발동되는 시나리오 시뮬레이션.

    실 라이브러리에선 Crew 내부에서 task 별로 _export_output 이 호출됨. 본 fake
    는 그 호출 흐름만 흉내 — 첫 kickoff 에서 task 별 raw 를 _export_output 에
    전달, 두 번째 kickoff (만약 일어나면) 도 동일.
    """

    def __init__(self, tasks_and_raws):
        self.pairs = list(tasks_and_raws)
        self.kickoff_calls = 0

    def kickoff(self):
        self.kickoff_calls += 1
        for task, raw in self.pairs:
            task._export_output(raw)
        return f"kickoff#{self.kickoff_calls}"


def test_capture_strips_per_task_in_place_no_re_kickoff() -> None:
    """A안 핵심 — _export_output 안에서 ValidationError raise → 그 task 의
    output_pydantic 만 None 으로 in-place strip → 같은 raw 로 재호출 →
    crew.kickoff() 는 1회만 (재 kickoff 없음, 본문 보존)."""
    from crewai.task import Task as _CrewTask

    task1 = _make_task()
    task2 = _make_task()
    object.__setattr__(task1, "output_pydantic", _DummySchema)
    object.__setattr__(task2, "output_pydantic", _DummySchema)

    call_log: list[tuple[int, object, str]] = []

    def fake_export(self, result):
        call_log.append((id(self), self.output_pydantic, result))
        if self.output_pydantic is not None:
            # 첫 호출 — schema 강제 시 ValidationError raise (5차 사례 재현)
            raise _validation_error()
        # 두 번째 호출 (strip 후) — 정상 반환 (raw 가 task.output 에 들어감)
        return (None, None)

    original = _CrewTask._export_output
    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew(
            [(task1, "RAW BODY 1 (long markdown)"), (task2, "RAW BODY 2 (long markdown)")]
        )

        result = kickoff_with_converter_rescue(crew, [task1, task2])

        assert result == "kickoff#1"  # ⭐ 재 kickoff 안 함 — A안 핵심
        assert crew.kickoff_calls == 1
        # 두 task 모두 strip 됨
        assert task1.output_pydantic is None
        assert task2.output_pydantic is None
        # 각 task 는 2회 호출됨 (실패 + strip 후 재호출)
        assert len(call_log) == 4
        # 두 번째 호출들은 모두 output_pydantic=None 으로 들어감
        assert call_log[1][1] is None  # task1 second
        assert call_log[3][1] is None  # task2 second
        # raw 본문이 두 호출 모두에 동일하게 전달됨 (보존)
        assert call_log[0][2] == call_log[1][2] == "RAW BODY 1 (long markdown)"
        assert call_log[2][2] == call_log[3][2] == "RAW BODY 2 (long markdown)"
    finally:
        _CrewTask._export_output = original


def test_capture_strips_on_converter_error_too() -> None:
    """ConverterError 도 동일하게 capture-and-strip."""
    if _ConverterError is None:
        import pytest

        pytest.skip("CrewAI ConverterError 미가용 환경")

    from crewai.task import Task as _CrewTask

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)

    def fake_export(self, result):
        if self.output_pydantic is not None:
            raise _converter_error("Agent must be provided")
        return (None, None)

    original = _CrewTask._export_output
    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew([(task, "RAW")])
        result = kickoff_with_converter_rescue(crew, [task])
        assert result == "kickoff#1"
        assert crew.kickoff_calls == 1
        assert task.output_pydantic is None
    finally:
        _CrewTask._export_output = original


def test_capture_skips_when_task_has_no_pydantic() -> None:
    """output_pydantic 없는 task 에서 raise 시 capture 가 처리 못 하므로 원 예외 raise."""
    from crewai.task import Task as _CrewTask

    task = _make_task()
    object.__setattr__(task, "output_pydantic", None)

    def fake_export(self, result):
        # output_pydantic 없는데도 어떤 이유로든 ValidationError raise — 매우 드물지만
        raise _validation_error()

    original = _CrewTask._export_output
    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew([(task, "RAW")])
        # output_pydantic 이 None 이므로 capture 가 strip 할 게 없음 → ValidationError
        # 가 _export_output 밖으로 escape → kickoff() 가 raise → fallback 시도 →
        # fallback 도 strip 대상 없어 결국 raise
        from pydantic import ValidationError

        import pytest

        with pytest.raises(ValidationError):
            kickoff_with_converter_rescue(crew, [task])
        assert crew.kickoff_calls == 1  # 재 kickoff 시도조차 못 함 (strip 대상 없음)
    finally:
        _CrewTask._export_output = original


def test_capture_preserves_kickoff_return_when_no_exception() -> None:
    """예외 없을 때 kickoff_with_converter_rescue 가 kickoff() 결과를 그대로 반환."""
    from crewai.task import Task as _CrewTask

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)

    def fake_export(self, result):
        # 정상 — 변환 성공 시뮬레이션
        return (None, None)

    original = _CrewTask._export_output
    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew([(task, "RAW")])
        result = kickoff_with_converter_rescue(crew, [task])
        assert result == "kickoff#1"
        assert crew.kickoff_calls == 1
        # output_pydantic 손대지 않음 (capture 발동 안 됨)
        assert task.output_pydantic is _DummySchema
    finally:
        _CrewTask._export_output = original


def test_capture_restores_original_export_after_completion() -> None:
    """rescue 종료 후 Task._export_output 가 원본으로 복원되는지 (다른 워크플로 영향 차단)."""
    from crewai.task import Task as _CrewTask

    pre_export = _CrewTask._export_output

    task = _make_task()
    object.__setattr__(task, "output_pydantic", _DummySchema)

    def fake_export(self, result):
        return (None, None)

    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew([(task, "RAW")])
        kickoff_with_converter_rescue(crew, [task])
        # 우리가 set 한 fake_export 가 그대로 남아 있어야 함 (rescue 가 finally 에서 복원)
        assert _CrewTask._export_output is fake_export
    finally:
        _CrewTask._export_output = pre_export


def test_capture_restores_export_even_when_exception_propagates() -> None:
    """예외가 외부로 propagate 해도 finally 에서 _export_output 복원."""
    from crewai.task import Task as _CrewTask

    sentinel_export = _CrewTask._export_output

    task = _make_task()
    object.__setattr__(task, "output_pydantic", None)  # capture 가 처리 못 함

    def fake_export(self, result):
        raise _validation_error()

    _CrewTask._export_output = fake_export
    try:
        crew = _ExportingFakeCrew([(task, "RAW")])
        from pydantic import ValidationError

        import pytest

        with pytest.raises(ValidationError):
            kickoff_with_converter_rescue(crew, [task])
        # 예외 후에도 우리가 set 한 fake_export 가 남아 있어야 (rescue 의 finally 가 복원)
        assert _CrewTask._export_output is fake_export
    finally:
        _CrewTask._export_output = sentinel_export


# ---------------------------------------------------------------------------
# PR #93 — retry_task_if_short 재시도 directive 주입 (PR #92 회귀 차단)
#
# 배경 (PR #92 publish 검증에서 발견):
#   Pytest Author 가 27 chars Final Answer 만 출력 → ConverterError 발생 →
#   output_pydantic stripped → retry_task_if_short 자동 재시도. 그러나 동일
#   description 으로 재시도 → LLM 이 *같은* 27 chars 응답 반복 → infinite short.
#
# 처방: retry 시 description 에 stronger directive 주입.
#   - 짧은 출력 명시 거부
#   - 최소 분량 임계 명시 (threshold * 10)
#   - 5단/3단 본문 강제
#   - schema 필드 + fence 마커 + # file: 헤더 강조
# ---------------------------------------------------------------------------


def test_retry_injects_short_output_directive_into_retry_description() -> None:
    """retry 시 retry_task.description 에 PR #93 directive 자동 주입."""
    task = _make_task()
    _set_output(task, "tiny")  # 4 chars — well below 120 threshold

    captured: list[str] = []

    def fake_kickoff(retry_task: Task) -> None:
        captured.append(retry_task.description)
        # 짧은 응답 유지 — directive 주입 검증이 목적
        _set_output(retry_task, "still tiny")

    retry_task_if_short(task, fake_kickoff, max_retries=1)
    assert len(captured) == 1
    retry_desc = captured[0]
    # 원본 description 보존
    assert task.description in retry_desc
    # PR #93 directive 추가
    assert "재시도 directive (PR #93)" in retry_desc
    assert "짧은 출력 회귀 차단" in retry_desc
    # 분량 임계 명시 (threshold 기반)
    assert "임계" in retry_desc
    assert "본문 모두" in retry_desc or "분량" in retry_desc


def test_retry_directive_includes_actual_output_length() -> None:
    """directive 가 *실제 짧은 출력 길이* 를 명시 (LLM 인지 강화)."""
    task = _make_task()
    _set_output(task, "x" * 27)  # PR #92 회귀 사례 정확 재현 (27 chars)

    captured: list[str] = []

    def fake_kickoff(retry_task: Task) -> None:
        captured.append(retry_task.description)
        _set_output(retry_task, "x" * 27)

    retry_task_if_short(task, fake_kickoff, max_retries=1)
    assert len(captured) == 1
    # directive 본문에 실제 출력 길이 (27) 포함
    assert "27 chars" in captured[0] or "27 " in captured[0]


def test_retry_directive_does_not_pollute_original_task_description() -> None:
    """원본 task.description 은 mutate 안 됨 — retry_task 만 augment."""
    task = _make_task()
    original_desc = task.description
    _set_output(task, "short")

    def fake_kickoff(retry_task: Task) -> None:
        _set_output(retry_task, "still short")

    retry_task_if_short(task, fake_kickoff, max_retries=1)
    # 원본 description 변경 없음
    assert task.description == original_desc
    assert "PR #93" not in task.description


def test_retry_directive_emphasizes_schema_fields_and_fence_markers() -> None:
    """directive 가 schema 필드 + fence 마커 + # file: 헤더 강조 — 다른 layer
    에서도 활용 가능."""
    task = _make_task()
    _set_output(task, "y")

    captured: list[str] = []

    def fake_kickoff(retry_task: Task) -> None:
        captured.append(retry_task.description)
        _set_output(retry_task, "y" * 5)

    retry_task_if_short(task, fake_kickoff, max_retries=1)
    desc = captured[0]
    # schema 필드 강조 (Pytest Author / 도메인 schema 모두 적용)
    assert "schema" in desc.lower()
    # fence 마커 + 파일 헤더 (PR #64/#66 패턴 재사용 강조)
    assert "fence" in desc.lower() or "```python" in desc
    assert "# file:" in desc
