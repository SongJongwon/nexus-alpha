# -*- coding: utf-8 -*-
"""
Nexus Alpha Meeting Facilitator — 킥오프 회의 진행 에이전트 (본부 10 첫 멤버).

PR #138 Phase 1 full (2026-05-15, 본인 비전 통찰 6):
    워크플로 시작 시 1회 호출되어 *모든 부서가 공유하는 결정 사항* 을
    ``SharedKickoffDecisions`` 로 산출한다. 산출물은 후속 task description 들에
    자동 주입되어 cross-agent inconsistency (환율 변환기 사례 — 1 USD = 1365.5
    stale vs 실제 ~1490, 9% 오차) 재발을 차단한다.

설계 결정 (사용자 합의 2026-05-15):
    - **하이브리드 (결정론 + 1 LLM call)** — 순수 LLM agent 가 아닌 helper 함수.
      Requirement Expander 산출 YAML 을 결정론으로 파싱해 가정/미해결 질문을
      추출하고, 단 1회 LLM 호출로 *부서별 책임 분담* 만 합성.
    - **삽입 지점** — ``iterative_loop`` 의 ``expand_requirements`` 다음. iteration
      재진입 시 state 에 이미 결정 객체가 있으면 skip (회의는 1회만).
    - **테스트 격리** — ``pytest`` 모듈 import 시 LLM 호출 자동 skip (deterministic
      half 만 사용). ``llm_call=`` 파라미터로 외부 주입도 가능.

호출 측 사용 예:
    from src.agents.coordination import run_kickoff_meeting

    decisions = run_kickoff_meeting(
        user_request="환율 변환기 만들어줘",
        spec_markdown=requirement_expander_output,
        participant_roles=["CTO", "Analyst", "UI/UX Analyst", "GUI Code Generator"],
    )
    yaml_text = decisions.to_yaml()
    workflow_dir.joinpath("shared_kickoff_decisions.yaml").write_text(
        yaml_text, encoding="utf-8"
    )
"""

from __future__ import annotations

import json
import re
import sys
from typing import Callable, Optional, Sequence

import yaml

from .schemas import SharedAssumption, SharedKickoffDecisions


# ---------------------------------------------------------------------------
# 에이전트 프로파일 (메타데이터 — 다른 에이전트와 일관성 유지용)
# ---------------------------------------------------------------------------
MEETING_FACILITATOR_NAME = "MeetingFacilitator"

MEETING_FACILITATOR_ROLE = "Senior Coordination Facilitator (Kickoff & Alignment)"

MEETING_FACILITATOR_GOAL = (
    "워크플로 시작 시점에 모든 부서가 공유해야 하는 *가정* 과 *책임 분담* 을 "
    "합의시켜 cross-agent inconsistency 를 사전 차단한다. 산출물은 "
    "shared_kickoff_decisions.yaml 로 후속 task 들에 자동 주입된다."
)

MEETING_FACILITATOR_BACKSTORY = (
    "당신은 본부 10 (Coordination/Communication) 의 첫 멤버로 신설된 협의 "
    "에이전트입니다. 진짜 회사의 킥오프 회의 진행자처럼 활동합니다.\n\n"
    "철학:\n"
    "  1. 모든 부서가 *같은 가정* 으로 출발하지 않으면 9% 환율 오차 같은 "
    "     무성의한 비일관성이 산출물에 새어든다.\n"
    "  2. 가정은 *명시적* 으로 적어야 한다 — 침묵으로 통과시키는 것이 가장 위험.\n"
    "  3. 책임 분담은 *결정* 이며 추후 회고/학습의 기준점이 된다.\n"
    "  4. 모르는 것은 ``open_questions`` 로 분리해 적는다 — BLOCKED 판정 후보."
)


# ---------------------------------------------------------------------------
# 결정론 파싱 — Requirement Expander 산출 YAML 에서 가정/질문/요구 추출
# ---------------------------------------------------------------------------
def _extract_yaml_block(spec_markdown: str) -> dict:
    """spec_markdown 에서 YAML 블록을 추출해 dict 로 반환.

    Requirement Expander 백스토리상 산출은 평탄 YAML — 마크다운 코드펜스로
    감싸졌을 수도, 본문에 그대로 있을 수도 있다. 둘 다 시도하고 실패하면
    빈 dict 반환 (LLM 합성으로만 fallback).
    """
    # 1) ```yaml ... ``` 또는 ``` ... ``` 펜스 안 우선
    fence = re.search(
        r"```(?:yaml|yml)?\s*\n(.*?)\n```",
        spec_markdown,
        re.DOTALL | re.IGNORECASE,
    )
    candidates: list[str] = []
    if fence is not None:
        candidates.append(fence.group(1))
    candidates.append(spec_markdown)  # 펜스 없이 본문 그대로

    for text in candidates:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_spec_deterministic(
    spec_markdown: str,
) -> tuple[list[SharedAssumption], list[str], str]:
    """spec_markdown 을 결정론으로 파싱.

    Returns:
        (assumptions, open_questions, spec_summary).

        - assumptions: Requirement Expander 가 명시한 ``assumptions:`` 항목.
            owner 는 일단 ``Requirement Expander`` 로 고정 (LLM 합성 단계에서
            적합한 부서로 reassign 될 수 있음).
        - open_questions: ``open_questions:`` 항목 평탄화.
        - spec_summary: 첫 비공백 줄 1개 (회의 헤더용 한 줄 요약).
    """
    data = _extract_yaml_block(spec_markdown)

    raw_assumptions = data.get("assumptions", []) or []
    raw_questions = data.get("open_questions", []) or []

    assumptions: list[SharedAssumption] = []
    for idx, item in enumerate(raw_assumptions, start=1):
        decision = item if isinstance(item, str) else str(item)
        slug = re.sub(r"[^a-z0-9]+", "_", decision.lower()).strip("_")[:40] or (
            f"assumption_{idx}"
        )
        assumptions.append(
            SharedAssumption(
                id=slug,
                decision=decision,
                rationale="Requirement Expander 가 spec 산출 시 명시한 가정",
                owner="Requirement Expander",
            )
        )

    questions: list[str] = []
    for q in raw_questions:
        questions.append(q if isinstance(q, str) else str(q))

    # 1줄 요약 — title 필드 우선, 없으면 본문 첫 비공백 줄
    spec_summary = ""
    title = data.get("title") or data.get("summary")
    if isinstance(title, str) and title.strip():
        spec_summary = title.strip()
    else:
        for line in spec_markdown.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("```"):
                spec_summary = stripped.lstrip("#").strip()
                break

    return assumptions, questions, spec_summary


# ---------------------------------------------------------------------------
# 1 LLM call — 부서별 책임 분담 합성
# ---------------------------------------------------------------------------
_RESPONSIBILITY_PROMPT_TEMPLATE = """\
당신은 한국 IT 회사의 킥오프 회의 진행자입니다. 아래 사용자 요청과 요구 스펙을 보고,
참여 부서 각각에게 어떤 책임을 분담해야 할지 한 줄씩 정리하세요.

**중요**:
  - 한 부서당 1~3개 항목 (너무 많지 마세요)
  - 환율 변환기 사례 같은 cross-agent inconsistency 가 일어나지 않도록 외부 의존
    (실시간 API / 정적 데이터 / 캐시 등) 결정이 있으면 *모든 관련 부서* 의 책임에
    동일하게 명시
  - 출력은 *반드시* 아래 JSON 스키마만 (앞뒤 설명 금지)

스키마:
{{
  "agent_responsibilities": {{
    "부서명": ["책임1", "책임2"],
    ...
  }}
}}

--- 사용자 요청 ---
{user_request}
--- 요구 스펙 ---
{spec_markdown}
--- 참여 부서 ---
{participants_joined}
--- 끝 ---
"""


def _default_llm_call(prompt: str) -> str:
    """기본 LLM 호출 — ``src.llm.get_llm_provider`` 의 async generate 를 동기 wrap.

    별도 thread 에서 새 이벤트 루프를 돌려 호출 측 컨텍스트(LangGraph 노드 등)가
    동기 / 비동기 어느 쪽이든 안전하게 사용 가능.
    """
    import asyncio
    import concurrent.futures

    from src.llm import get_llm_provider

    async def _go() -> str:
        provider = get_llm_provider()
        return await provider.generate(prompt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _go())
        return future.result()


def _parse_responsibility_json(text: str) -> dict[str, list[str]]:
    """LLM 응답에서 ``agent_responsibilities`` dict 추출.

    code fence / 앞뒤 잡설 모두 관대하게 처리. 실패 시 빈 dict.
    """
    # ```json ... ``` 펜스
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    candidates: list[str] = []
    if fence is not None:
        candidates.append(fence.group(1))
    # 첫 ``{`` 부터 마지막 ``}`` 까지
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    candidates.append(text)

    for chunk in candidates:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            inner = data.get("agent_responsibilities", data)
            if isinstance(inner, dict):
                result: dict[str, list[str]] = {}
                for role, items in inner.items():
                    if not isinstance(items, list):
                        continue
                    str_items = [str(i) for i in items if str(i).strip()]
                    if str_items:
                        result[str(role)] = str_items
                if result:
                    return result
    return {}


def _synthesize_responsibilities(
    user_request: str,
    spec_markdown: str,
    participant_roles: Sequence[str],
    llm_call: Callable[[str], str],
) -> dict[str, list[str]]:
    """1 LLM call 로 부서별 책임 분담 합성."""
    participants_joined = ", ".join(participant_roles)
    prompt = _RESPONSIBILITY_PROMPT_TEMPLATE.format(
        user_request=user_request.strip(),
        spec_markdown=spec_markdown.strip(),
        participants_joined=participants_joined,
    )
    try:
        response = llm_call(prompt)
    except Exception:  # LLM 실패는 워크플로 차단 사유 아님 — deterministic half 만 사용
        return {}
    return _parse_responsibility_json(response or "")


# ---------------------------------------------------------------------------
# 공개 API — 진입점
# ---------------------------------------------------------------------------
DEFAULT_PARTICIPANTS: tuple[str, ...] = (
    "CTO",
    "Data Analyst",
    "UI/UX Analyst",
    "GUI Designer",
    "Theme Designer",
    "Python Engineer",
    "GUI Code Generator",
    "Pytest Author",
    "Code Reviewer",
)


def run_kickoff_meeting(
    user_request: str,
    spec_markdown: str,
    participant_roles: Optional[Sequence[str]] = None,
    llm_call: Optional[Callable[[str], str]] = None,
) -> SharedKickoffDecisions:
    """킥오프 회의 1회 진행 → ``SharedKickoffDecisions`` 반환.

    하이브리드 흐름:
        1. ``_parse_spec_deterministic`` — Requirement Expander 산출 YAML 에서
           가정 / 미해결 질문 / 한 줄 요약 추출 (결정론).
        2. ``_synthesize_responsibilities`` — 단 1회 LLM 호출로 부서별 책임 합성.
           실패 / pytest 환경 / ``llm_call=None`` 시 자동 skip (책임 dict 빈 채).

    Args:
        user_request: 사용자의 원본 자연어 요청.
        spec_markdown: Requirement Expander 산출 (YAML 포함 마크다운).
        participant_roles: 회의 참여 부서/역할 리스트. None 이면 기본 9개 부서.
        llm_call: 외부 주입 가능한 LLM 호출 함수 (테스트용). None 이고 pytest
            환경이 아니면 ``_default_llm_call`` 사용. pytest 환경에선 자동 skip.

    Returns:
        ``SharedKickoffDecisions`` — yaml 직렬화 / task description 주입 가능.
    """
    participants = list(participant_roles or DEFAULT_PARTICIPANTS)

    assumptions, open_questions, spec_summary = _parse_spec_deterministic(
        spec_markdown
    )

    # pytest 환경 + 외부 주입 없음 → LLM 호출 skip (결정론 half 만)
    in_pytest = "pytest" in sys.modules
    if llm_call is None and not in_pytest:
        llm_call = _default_llm_call

    responsibilities: dict[str, list[str]] = {}
    if llm_call is not None:
        responsibilities = _synthesize_responsibilities(
            user_request=user_request,
            spec_markdown=spec_markdown,
            participant_roles=participants,
            llm_call=llm_call,
        )

    return SharedKickoffDecisions(
        user_request=user_request,
        spec_summary=spec_summary,
        shared_assumptions=assumptions,
        agent_responsibilities=responsibilities,
        open_questions=open_questions,
    )


__all__ = [
    "DEFAULT_PARTICIPANTS",
    "MEETING_FACILITATOR_BACKSTORY",
    "MEETING_FACILITATOR_GOAL",
    "MEETING_FACILITATOR_NAME",
    "MEETING_FACILITATOR_ROLE",
    "run_kickoff_meeting",
]
