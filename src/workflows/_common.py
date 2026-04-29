# -*- coding: utf-8 -*-
"""Shared helpers for analyze_and_implement / build_workflow / release_workflow.

이슈 4 / 5 / 6 회귀 방지 통합 지점:
  - task_output_text: CrewAI Task 출력 안전 추출 + 짧은 출력 경고
  - retry_task_if_short: 짧은 출력 감지 시 동일 task 재실행 (이슈 6 fix)
  - retry_short_tasks_in_chain: production 헬퍼 (pytest 환경 skip)
  - kickoff_with_converter_rescue: ConverterError 시 output_pydantic 벗기고
    재시도 (이슈 6 방어선 3 — PR #53)
"""

from __future__ import annotations

import warnings
from typing import Callable, Sequence

from crewai import Crew, Process, Task

try:
    # CrewAI >= 0.x — converter 가 raise 하는 도메인 예외
    from crewai.utilities.converter import ConverterError as _ConverterError
except ImportError:  # pragma: no cover — 매우 오래된 CrewAI 또는 import 실패 시
    _ConverterError = None  # type: ignore[assignment]

try:
    from pydantic import ValidationError as _PydanticValidationError
except ImportError:  # pragma: no cover
    _PydanticValidationError = None  # type: ignore[assignment]


def _rescuable_exc_classes() -> tuple[type[BaseException], ...]:
    """rescue 대상 예외 클래스 모음 (CrewAI ConverterError + Pydantic ValidationError)."""
    classes: list[type[BaseException]] = []
    if _ConverterError is not None:
        classes.append(_ConverterError)
    if _PydanticValidationError is not None:
        classes.append(_PydanticValidationError)
    return tuple(classes)


# 짧은 출력 임계 (이슈 4 / 6) — Final Answer summary 한 줄만 캡처되는 케이스 감지.
SUSPICIOUS_OUTPUT_THRESHOLD = 120


def task_output_text(task: Task) -> str:
    """CrewAI Task 의 출력을 안전하게 문자열로 꺼낸다 (버전별 속성 차이 대응).

    이슈 4 (2026-04-21) / 이슈 6 (2026-04-27) 회귀 방지:
        agent backstory 가 `"마지막 줄 Final Answer: <summary>"` 패턴을 쓰거나,
        prompt restructuring 후에도 LLM 이 비결정적으로 본문을 생략하는 경우
        raw 가 매우 짧아짐. production 환경에서 경고로 surface — 회귀를 즉시 알 수 있음.

        본 함수는 *경고만* — 실제 본문 회수는 ``retry_task_if_short`` 가 담당.
        pytest 환경에서는 FakeProvider 응답이 본질적으로 짧아 false positive 방지를
        위해 경고 skip.

    이슈 6 방어선 2 (PR #31): 일부 Task 가 ``output_pydantic`` 으로 schema 를 강제
    → ``task.output.pydantic`` 에 파싱된 모델 인스턴스 저장. 모델이 ``to_markdown()``
    메서드를 제공하면 그 결과를 우선 반환 (raw 의 JSON 대신 markdown 으로 디스크 저장).
    """
    out = task.output
    if out is None:
        return ""

    # 방어선 2 — output_pydantic 이 적용됐고 모델이 to_markdown 을 제공하면 우선
    pyd = getattr(out, "pydantic", None)
    if pyd is not None and hasattr(pyd, "to_markdown"):
        try:
            rendered = pyd.to_markdown()
            if isinstance(rendered, str) and rendered.strip():
                return rendered
        except Exception:
            # 렌더 실패 시 raw 로 fallback (graceful degradation)
            pass

    raw = getattr(out, "raw", None) or str(out)

    import sys

    if (
        "pytest" not in sys.modules
        and raw
        and 0 < len(raw.strip()) < SUSPICIOUS_OUTPUT_THRESHOLD
    ):
        import warnings

        agent_name = getattr(getattr(out, "agent", None), "role", "unknown")
        warnings.warn(
            f"Task output is suspiciously short ({len(raw)} chars) for agent "
            f"'{agent_name}'. backstory 의 `Final Answer: <summary>` 패턴 또는 LLM "
            f"비결정적 본문 누락 가능 (이슈 4 / 6). retry_task_if_short 가 자동 "
            f"재시도를 시도합니다.",
            stacklevel=2,
        )

    return raw or ""


def retry_task_if_short(
    task: Task,
    kickoff_fn: Callable[[Task], None],
    max_retries: int = 1,
    threshold: int = SUSPICIOUS_OUTPUT_THRESHOLD,
) -> bool:
    """task 출력이 짧으면 동일 task 를 재실행 — 이슈 6 fix (LLM 비결정성 방어선 1).

    PR #25 의 prompt restructuring 으로 *대부분* 의 에이전트는 본문을 출력하지만,
    LLM 의 통계적 행동으로 가끔 Final Answer 한 줄만 캡처되는 경우가 잔존
    (PR #28 4차 E2E 에서 16개 중 4개 관찰). 본 함수는 그 잔존을 *런타임* 에서
    탐지·복구.

    Args:
        task: 검사할 task. ``task.output`` 이 짧으면 재실행 후 갱신.
        kickoff_fn: ``retry_task`` 를 받아 실행하고 ``retry_task.output`` 을 채우는
            함수. production 에선 ``Crew(...).kickoff()``, 테스트에선 fake.
        max_retries: 재시도 횟수 (기본 1). 더 시도해도 짧으면 원본 유지.
        threshold: 짧음 판정 임계 (기본 120자).

    Returns:
        True: 재시도가 더 긴 출력을 만들어 ``task.output`` 을 교체.
        False: 재시도 불필요 (이미 충분히 길거나 비어있음) 또는 모든 재시도 실패.
    """
    raw = task_output_text(task)
    if not raw or len(raw.strip()) >= threshold:
        return False  # OK or empty — no retry needed

    for _ in range(max_retries):
        retry_task = Task(
            description=task.description,
            expected_output=task.expected_output,
            agent=task.agent,
            context=task.context,
        )
        try:
            kickoff_fn(retry_task)
        except Exception:
            # 재시도 자체가 실패하면 원본 유지하고 다음 시도
            continue
        retry_raw = task_output_text(retry_task)
        if retry_raw and len(retry_raw.strip()) >= threshold:
            task.output = retry_task.output
            return True
    return False


def retry_short_tasks_in_chain(
    tasks: Sequence[Task],
    max_retries: int = 1,
) -> list[Task]:
    """Production 헬퍼 — 체인의 모든 task 를 검사·재시도.

    pytest 환경에선 skip (FakeProvider 의 본질적 짧은 출력 대응).

    Args:
        tasks: 검사 대상 task 시퀀스 (체인 순서대로).
        max_retries: 각 task 당 재시도 횟수 (기본 1).

    Returns:
        실제 재시도되어 출력이 교체된 task 리스트 (로깅·진단용).
    """
    import sys

    if "pytest" in sys.modules:
        return []

    def _crew_kickoff(retry_task: Task) -> None:
        Crew(
            agents=[retry_task.agent],
            tasks=[retry_task],
            process=Process.sequential,
            verbose=False,
        ).kickoff()

    retried: list[Task] = []
    for task in tasks:
        if retry_task_if_short(task, _crew_kickoff, max_retries=max_retries):
            retried.append(task)
    return retried


# ---------------------------------------------------------------------------
# 이슈 6 방어선 3 (PR #53) — ConverterError rescue
# ---------------------------------------------------------------------------


def kickoff_with_converter_rescue(
    crew: Crew,
    tasks: Sequence[Task],
    max_rescue: int = 1,
) -> object:
    """``crew.kickoff()`` 를 호출. **CrewAI converter 에서 raise 되는** 예외
    (``ConverterError`` 또는 ``pydantic.ValidationError``) 시 모든 task 의
    ``output_pydantic`` 을 벗기고 1회 재시도.

    배경 (PR #53 진단 — 두 가지 결함 모두 처리):
        1. ``ConverterError`` (10차 E2E 1·3차 — Build Engineer / Platform Tester):
           CrewAI ``Converter.to_pydantic()`` 의 ``handle_partial_json(agent=None)``
           하드코딩 (converter.py:85) → ``convert_with_instructions(agent=None)``
           → ``"Agent must be provided"`` ``TypeError`` → ConverterError surface.
        2. ``ValidationError`` (10차 E2E 4차 — Installer Creator):
           CrewAI ``handle_partial_json`` 의 ``_JSON_PATTERN = r"({.*})"`` (DOTALL,
           greedy) 가 markdown 의 ``{{guid}}`` / ``{autodesktop}`` 등 비-JSON
           ``{...}`` 블록을 잘못 매칭 → ``model_validate_json`` ValidationError 가
           ``except ValidationError: raise`` (converter.py:266) 로 wrap 없이 escape.
        두 결함 모두 LLM 의 markdown 출력을 JSON 으로 강제 변환하려는 CrewAI
        converter 의 부작용. 결정적 — LLM 같은 답을 또 내도 같은 결과.

    처방:
        rescuable 예외 (``ConverterError`` ∪ ``ValidationError``) raise 시 모든
        task 의 ``output_pydantic`` 을 ``None`` 으로 벗긴 뒤 같은 ``crew`` 를 1회
        재실행. 산출물의 schema 보장은 잃지만 raw 텍스트는 보존되고 workflow
        진행 가능 (``task_output_text`` 가 raw 출력 짧음/누락 별도 감지).

    Args:
        crew: ``kickoff()`` 할 Crew 인스턴스.
        tasks: 해당 crew 의 task 시퀀스 — rescue 시 ``output_pydantic`` 벗길 대상.
        max_rescue: rescue 시도 최대 횟수 (기본 1, 0 이면 rescue 비활성).

    Returns:
        ``crew.kickoff()`` 의 반환값 (CrewOutput — CrewAI 버전 의존).

    Raises:
        ConverterError | ValidationError: rescue 도 실패하거나 ``max_rescue<=0``
            인데 raise 발생 시 원본 예외 재상승.
    """
    rescuable = _rescuable_exc_classes()
    if not rescuable:
        # CrewAI / Pydantic 미가용 — 기본 kickoff 만 (rescue 불가)
        return crew.kickoff()

    try:
        return crew.kickoff()
    except rescuable as e:
        if max_rescue <= 0:
            raise

        rescued: list[str] = []
        for task in tasks:
            if getattr(task, "output_pydantic", None) is not None:
                try:
                    # CrewAI Task 는 Pydantic v2 BaseModel — 기본 mutable.
                    task.output_pydantic = None
                    role = getattr(getattr(task, "agent", None), "role", "unknown")
                    rescued.append(role)
                except Exception:
                    # Pydantic frozen 등 mutate 실패 — graceful skip
                    pass

        if not rescued:
            raise

        import sys

        if "pytest" not in sys.modules:
            warnings.warn(
                f"[converter rescue] {type(e).__name__}: tasks={rescued}; "
                f"output_pydantic stripped, retrying once. Original: {e}",
                stacklevel=2,
            )

        # 1회 재시도 (max_rescue=1 이면 마지막 기회)
        if max_rescue > 1:
            return kickoff_with_converter_rescue(crew, tasks, max_rescue=max_rescue - 1)
        return crew.kickoff()
