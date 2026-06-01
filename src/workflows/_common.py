# -*- coding: utf-8 -*-
"""Shared helpers for analyze_and_implement / build_workflow / release_workflow.

이슈 4 / 5 / 6 회귀 방지 통합 지점:
  - task_output_text: CrewAI Task 출력 안전 추출 + 짧은 출력 경고
  - retry_task_if_short: 짧은 출력 감지 시 동일 task 재실행 (이슈 6 fix)
  - retry_short_tasks_in_chain: production 헬퍼 (pytest 환경 skip)
  - kickoff_with_converter_rescue: ConverterError/ValidationError 시 본문(raw)
    보존하고 task.output_pydantic 만 in-place 벗긴 뒤 같은 raw 로 _export_output
    재호출 — 재 kickoff 불필요, LLM 본문 100% 보존 (이슈 6 방어선 3 — PR #53/#54)
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

    # PR #93 — 재시도 시 progressively stronger directive 주입.
    # 배경: PR #92 검증에서 retry 시 LLM 이 *같은* 27 chars 응답 반복 → infinite
    # short loop. 동일 prompt 재실행은 LLM 에 같은 패턴 유도 — 자유 영역 차단을
    # 위해 description 에 *짧은 출력 명시 거부* directive 추가.
    short_retry_directive = (
        f"\n\n## 🚨 재시도 directive (PR #93) — 짧은 출력 회귀 차단\n"
        f"이전 출력이 {len(raw.strip())} chars 로 임계 {threshold} 미달. "
        f"Final Answer 한 줄만으로는 task 미완료입니다. **5단/3단 본문 모두 "
        f"작성 필수** + 최소 분량 {max(threshold * 10, 1200)} chars. schema 의 "
        f"모든 필드 (summary + body sections) 채우고, ```python``` 등 fence "
        f"마커 + ``# file:`` 헤더 누락 금지. 이전 응답의 Final Answer 라인은 "
        f"summary 필드에만 사용하고 본문은 별도로 *상세히* 작성하세요.\n"
    )

    for _ in range(max_retries):
        retry_task = Task(
            description=task.description + short_retry_directive,
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
# 이슈 6 방어선 3 — Capture-before-rescue (PR #53 → PR #54)
# ---------------------------------------------------------------------------


def kickoff_with_converter_rescue(
    crew: Crew,
    tasks: Sequence[Task],
    max_rescue: int = 1,
) -> object:
    """``crew.kickoff()`` 를 호출. CrewAI converter 가 raise 하는 rescuable
    예외 (``ConverterError`` 또는 ``pydantic.ValidationError``) 발생 시
    **그 task 의 ``output_pydantic`` 만 in-place 로 벗기고 같은 raw 로
    ``_export_output`` 을 재호출** — 본문(raw) 100% 보존, crew 재 kickoff 불필요.

    배경 (PR #53 진단 — 두 가지 결함):
        1. ``ConverterError`` (10차 E2E 1·3차 — Build Engineer / Platform Tester):
           CrewAI ``Converter.to_pydantic()`` 의 ``handle_partial_json(agent=None)``
           하드코딩 (converter.py:85) → ``convert_with_instructions(agent=None)``
           → ``"Agent must be provided"`` ``TypeError`` → ConverterError surface.
        2. ``ValidationError`` (10차 E2E 4차 — Installer Creator):
           CrewAI ``handle_partial_json`` 의 ``_JSON_PATTERN = r"({.*})"`` (DOTALL,
           greedy) 가 markdown 의 ``{{guid}}`` / ``{autodesktop}`` / Python set
           literal 등 비-JSON ``{...}`` 블록을 잘못 매칭 → ``model_validate_json``
           ValidationError 가 ``except ValidationError: raise`` (converter.py:266)
           로 wrap 없이 escape.
        두 결함 모두 LLM 의 markdown 출력을 JSON 으로 강제 변환하려는 CrewAI
        converter 의 부작용. 결정적 — LLM 같은 답을 또 내도 같은 결과.

    PR #54 — Capture-before-rescue (A안):
        v1/v2 (PR #53) 의 처방은 "전체 task 의 output_pydantic 벗기고 crew 재
        kickoff" 였으나, 10차 E2E 5차 (2026-04-29) 에서 부수효과 발견:
        rescue 후 재 kickoff 시 LLM 이 schema instruction 부재 상태에서 backstory
        의 ``Final Answer:`` 한 줄 패턴을 따라 본문이 짧아짐 → GUI Code Generator
        의 ``code/`` 빈 폴더 → .exe 미생성.

        본 PR 의 A안: ``Task._export_output(result)`` 를 *클래스 레벨* 로 wrap.
        rescuable 예외 raise 시 그 task 의 ``output_pydantic`` 을 ``None`` 으로
        in-place 벗긴 뒤 **같은 raw result 로 ``_export_output`` 재호출** —
        schema 변환만 skip 되고 raw 본문은 그대로 ``task.output.raw`` 에 들어감.
        crew 재 kickoff 불필요 → 첫 kickoff 의 긴 raw 가 보존됨 → 코드 추출 성공.

        만약 ``_export_output`` 외부에서 rescuable 예외가 raise 되는 경우
        (예: Crew 자체 로직, 호출 순서 차이 등) 는 v2 fallback 으로 전체 task
        ``output_pydantic`` 벗기고 1회 재 kickoff (호환성).

    Args:
        crew: ``kickoff()`` 할 Crew 인스턴스.
        tasks: 해당 crew 의 task 시퀀스 — fallback rescue 시 ``output_pydantic``
            벗길 대상.
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

    if max_rescue <= 0:
        # rescue 비활성 — patch 도 fallback 도 적용하지 않음
        return crew.kickoff()

    # ----- A안: Task._export_output 클래스 레벨 patch (capture-before-rescue) -----
    try:
        from crewai.task import Task as _CrewTask  # type: ignore[import-not-found]
    except Exception:
        _CrewTask = None  # type: ignore[assignment]

    captured: list[tuple[str, str]] = []  # (agent_role, exc_type)
    original_export = None

    if _CrewTask is not None and hasattr(_CrewTask, "_export_output"):
        original_export = _CrewTask._export_output

        def _patched_export(self, result):  # type: ignore[no-untyped-def]
            try:
                return original_export(self, result)
            except rescuable as exc:
                # 그 task 만 schema 벗기고 같은 raw 로 재호출 — 본문 보존
                if getattr(self, "output_pydantic", None) is None:
                    raise
                try:
                    self.output_pydantic = None
                except Exception:
                    raise exc  # mutate 실패 — 원 예외 surface
                role = getattr(getattr(self, "agent", None), "role", "unknown")
                captured.append((role, type(exc).__name__))
                # 두 번째 호출 — output_pydantic=None 이라 convert_to_model skip,
                # raw 가 task.output 에 그대로 들어감
                return original_export(self, result)

        _CrewTask._export_output = _patched_export  # type: ignore[assignment]

    try:
        try:
            result = crew.kickoff()
        except rescuable as e:
            # _export_output 외부 (Crew 내부 로직) 에서 raise 된 케이스 — v2 fallback
            rescued: list[str] = []
            for task in tasks:
                if getattr(task, "output_pydantic", None) is not None:
                    try:
                        task.output_pydantic = None
                        role = getattr(getattr(task, "agent", None), "role", "unknown")
                        rescued.append(role)
                    except Exception:
                        pass
            if not rescued:
                raise

            import sys

            if "pytest" not in sys.modules:
                warnings.warn(
                    f"[converter rescue v2 fallback] {type(e).__name__}: "
                    f"tasks={rescued}; output_pydantic stripped, retrying once. "
                    f"Original: {e}",
                    stacklevel=2,
                )

            # fallback 재 kickoff — patched 는 여전히 활성 상태
            result = crew.kickoff()
    finally:
        if original_export is not None and _CrewTask is not None:
            _CrewTask._export_output = original_export  # type: ignore[assignment]

    if captured:
        import sys

        if "pytest" not in sys.modules:
            roles = [r for r, _ in captured]
            warnings.warn(
                f"[converter rescue capture] tasks={roles}; output_pydantic "
                f"stripped per-task in-place, raw preserved (no re-kickoff).",
                stacklevel=2,
            )

    return result


# ---------------------------------------------------------------------------
# PR #138 Phase 1 minimal slice — Cross-agent consistency directive
# ---------------------------------------------------------------------------
# 배경 (2026-05-14 종합 점검 통찰 6 — 본인 비전):
#   환율 변환기 사례 — CTO/Analyst/UI Designer 가 "frankfurter API 실시간 환율"
#   결정했으나 GUI Code Generator 가 정적 dict 내장 → 1 USD = 1365.5 stale (실제
#   ~1490, 9% 오차). 4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함.
#
#   CrewAI 의 ``Task.context=[task1, task2, ...]`` 는 prior output 을 자동 주입
#   하지만 *결정 사항 강조* 가 없음 — LLM 이 prior output 을 "그냥 참고"하고
#   자기 가정으로 일관성 깨뜨릴 위험.
#
# PR #138 minimal slice (Phase 1):
#   1. ``format_consistency_directive`` helper — task description 에 append 할
#      "다른 부서 결정 사항 일치 유지" 강조 섹션 생성
#   2. 1 task (GUI Code Generator) 에 시범 적용 — 효과 라이브 검증 후 확대
#
# 다음 세션 (PR #138 full):
#   - Meeting Facilitator 에이전트 신설 (본부 10 첫 멤버) — 킥오프 회의 진행
#   - shared_kickoff_decisions.yaml 산출 → 모든 task description 자동 주입
#   - 모든 워크플로 (analyze_and_implement / build / release) 에 확대


def format_consistency_directive(prior_agent_roles: Sequence[str]) -> str:
    """Cross-agent consistency directive 를 task description 에 append 할 형태로 반환.

    PR #138 Phase 1 (Shared Context Pool minimal slice — 본인 비전 통찰 6).

    배경:
        환율 변환기 사례 (1 USD = 1365.5 stale) — CrewAI ``Task.context=[...]`` 가
        prior output 자동 주입하지만 *강조 부재* 로 LLM 이 무시. 본 directive 는
        명시적으로 "다른 부서 결정과 일치 유지 의무" 를 LLM 에게 인식시킴.

    사용법:
        ::

            description = base_description + format_consistency_directive(
                prior_agent_roles=["CTO", "Analyst", "UI Designer"],
            )

    Args:
        prior_agent_roles: 이전 task 의 에이전트 역할 리스트 (순서 유지).
            빈 리스트면 빈 string 반환 (no-op).

    Returns:
        task description 끝에 append 할 markdown 문자열. 빈 입력이면 ``""``.

    설계 결정:
        - **prior output 은 주입 안 함** — CrewAI Task.context 가 이미 raw 로 주입.
          본 directive 는 *지시* 만 추가 (LLM 의 attention 환기).
        - **agent_role 만 받음** — 실제 output 은 CrewAI 가 자동 처리.
        - **markdown 헤더 강조** — LLM 이 markdown 구조를 attention weight 로 우선시.
    """
    if not prior_agent_roles:
        return ""

    roles_list = "\n".join(f"  - **{role}**" for role in prior_agent_roles)
    return f"""

## ⚠️ Cross-agent consistency directive (PR #138 Phase 1)

위 컨텍스트의 다음 부서들이 *이미 결정한 사항* 이 있습니다:
{roles_list}

**반드시 그 결정과 일치하는 산출물을 작성하세요.** 충돌 시:
1. 본문에 충돌 사실을 *명시적으로* 표기 ("CTO 사양은 X 였으나 ...")
2. 이유와 처리 방식 (수용 / 대안 제시 / 재논의 요청) 기록
3. *암묵적 무시* 금지 — 환율 변환기 사례 (정적 dict vs 실시간 API 가정 충돌) 재발 차단

→ 이 directive 는 "AI 가상 기업" 의 *진짜 협업* 첫 단계 (본부 10 Coordination/Communication).
"""


# ---------------------------------------------------------------------------
# PR #138 Phase 1 full — Kickoff Context directive
# ---------------------------------------------------------------------------
# 본 helper 는 Meeting Facilitator (``src/agents/coordination/``) 가 산출한
# ``SharedKickoffDecisions`` 를 task description 끝에 append 할 markdown 으로
# 변환한다. ``format_consistency_directive`` 가 *지시만* 추가했다면, 이 helper 는
# *실제 합의 사항* (공유 가정 / 부서별 책임 / 미해결 질문) 을 풀어 LLM 이
# 합의를 "사실" 로 인식하도록 강제한다.
#
# decisions=None 또는 비어 있으면 ``format_consistency_directive`` 의 결과만 반환
# → 호출 측은 무조건 본 helper 하나만 쓰면 minimal slice / full 모두 커버.


def format_kickoff_context_directive(
    decisions,  # SharedKickoffDecisions | None — 순환 import 회피로 untyped
    prior_agent_roles: Sequence[str] = (),
    *,
    product_scoped: bool = False,
) -> str:
    """킥오프 회의 결정 + consistency directive 를 task description 에 append.

    PR #138 Phase 1 full (본인 비전 통찰 6) — Meeting Facilitator 의 산출물을
    모든 task 에 자동 주입하는 단일 진입점. ``analyze_and_implement.py``,
    ``build_workflow.py``, ``release_workflow.py`` 의 모든 task builder 가 본
    helper 만 호출해서 directive 일관성을 유지한다.

    Args:
        decisions: ``SharedKickoffDecisions`` 또는 None.
            - None / 비어 있음 → consistency directive 만 (minimal slice 동작).
            - 채워져 있음 → 공유 가정 + 책임 + 미해결 질문 + consistency directive.
        prior_agent_roles: 본 task 이전에 산출물이 있었던 에이전트 역할 리스트.

    Returns:
        markdown 문자열. 입력 모두 비어 있으면 ``""``.
    """
    if decisions is not None:
        # SharedKickoffDecisions 의 to_kickoff_context_directive 사용 — 완전판
        # v13 Phase 6.E P14 — product_scoped 면 시스템 내부 정보(부서 명단/RAG recall 등) 제거.
        try:
            return decisions.to_kickoff_context_directive(
                prior_agent_roles, product_scoped=product_scoped
            )
        except AttributeError:  # 잘못된 객체 주입 시 minimal 로 fallback
            pass
    if product_scoped:
        # 제품 컨텍스트엔 cross-agent 역할명 directive 도 주입 안 함 (누수 차단).
        return ""
    return format_consistency_directive(prior_agent_roles)
