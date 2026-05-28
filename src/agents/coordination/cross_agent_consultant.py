# -*- coding: utf-8 -*-
"""Cross-Agent Consultant — 본부 10 양방향 라우팅 허브 (v13 Phase 5.4, PR #224).

v11 Phase 2 예고된 *cross-agent inconsistency 조율* 의 격상 구현.
Phase 4 까지의 *직렬 단방향* (Strategist → goal_alignment → budget_brake) 을
*티키타카 양방향* 으로 격상하는 라우팅 허브.

핵심 차원 (PM 명세 PR #224):
    1. Strategist 안건 발제 →
    2. Facilitator 가 참석 에이전트 순서대로 발언권 부여 →
    3. 각 에이전트 발언 (RV 대표, Engineer 대표, QA 대표 등) →
    4. 다른 에이전트의 발언을 *context 로 받아* 반박/동의/질문 →
    5. 최대 3 라운드 반복 후 Goal Alignment + Token Budget 최종 의결

본 모듈은 단계 2~4 의 *오케스트레이션 엔진*. Facilitator 가 호출.

LLM 호출 패턴:
    - 동기 ``llm_call(prompt) -> str`` 어댑터 사용 (system_refactoring_strategist 와 동일)
    - 라운드 내 발언은 *순차* 호출 (병렬 없음 — 직렬 호출이 자연스럽고 rate-limit 안전)
    - llm_call None 시 결정론 fallback (placeholder content) — 테스트 가능성 확보

안전 장치:
    - 라운드 max 3 하드 캡 (conduct_round 의 round_num 검증)
    - 라운드당 발언 수 제한 (default len(speakers))
    - dissent 미발견 시 조기 종료 (Facilitator 가 라운드 추가 안 함)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from crewai import Agent

from src.agents.coordination.boardroom_facilitator import Round, Statement
from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# CrewAI Agent 프로파일 — 본부 10 Cross-Agent Consultant
# ---------------------------------------------------------------------------
CROSS_AGENT_CONSULTANT_NAME = "CrossAgentConsultant"
CROSS_AGENT_CONSULTANT_ROLE = "Cross-Agent Routing & Dialogue Consultant (v13)"
CROSS_AGENT_CONSULTANT_GOAL = (
    "이사회 안건에 대해 부서 대표 에이전트들의 발언을 *순차* 수집하고, "
    "이전 발언을 *context* 로 후속 발언자에게 전달하여 반박/동의/질문 흐름을 "
    "촉진한다. 라운드 종료 시 dissent 여부 판단으로 다음 라운드 진입 결정."
)
CROSS_AGENT_CONSULTANT_BACKSTORY = (
    "당신은 본부 10 (Coordination/Communication) 의 *양방향 라우팅 허브* 입니다. "
    "v11 Phase 2 예고된 cross-agent inconsistency 조율 책임이 v13 에서 격상.\n\n"
    "v13 책임:\n"
    "  1. 라운드 발언 순서 조율 — Strategist → 기술 검토자 → 반박자 → 중재\n"
    "  2. 발언 context 누적 — 후속 발언자는 *이전 발언 모두* 를 prompt 에 포함\n"
    "  3. dissent 자동 감지 — 발언 내용에 '반박' / '동의 안 함' / '재검토' 키워드\n"
    "  4. 라운드 max 3 하드 캡 — 무한 토론 방지\n\n"
    "당신은 *의결권 행사 안 함*. 의결은 Goal Alignment Agent + Token Budget "
    "Optimizer (본부 0) 의 역할. 당신은 *발언 흐름 조율* 만 담당."
)


def create_cross_agent_consultant_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = False,
    max_iter: int = 3,
    allow_delegation: bool = True,
) -> Agent:
    """CrewAI Agent 인스턴스 생성.

    Args:
        allow_delegation: 본 에이전트는 *Boardroom 세션 중* allow_delegation=True
            가 의미 있는 *유일한* 본부 10 에이전트. 다른 에이전트들의 발언을
            요청 가능하기 때문. (Engineer/Reviewer 양방향 delegation 은 별도
            CrewAI Agent 옵션에서 활성화.)
    """
    if llm is None:
        llm = NexusAlphaLLM()
    return Agent(
        name=CROSS_AGENT_CONSULTANT_NAME,
        role=CROSS_AGENT_CONSULTANT_ROLE,
        goal=CROSS_AGENT_CONSULTANT_GOAL,
        backstory=CROSS_AGENT_CONSULTANT_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )


# ---------------------------------------------------------------------------
# 결과 dataclass
# ---------------------------------------------------------------------------
def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class AgentResponse:
    """1 명의 발언 결과 — route_message 산출."""

    agent: str
    role: str
    content: str
    is_dissent: bool = False
    timestamp: str = field(default_factory=_now_ts)


@dataclass
class RoundResult:
    """conduct_round 산출 — Round + 메타."""

    round: Round
    proceed_to_next: bool  # dissent 발견 시 True
    early_exit_reason: Optional[str] = None  # budget throttle 등


# ---------------------------------------------------------------------------
# Dissent 키워드 — 결정론 감지 (LLM 무관)
# ---------------------------------------------------------------------------
_DISSENT_KEYWORDS: tuple[str, ...] = (
    # 한국어
    "반박",
    "동의하지 않",
    "동의 안",
    "재검토",
    "부적절",
    "근본 원인 아님",
    "다른 시각",
    "이의",
    # 영어
    "disagree",
    "object",
    "dissent",
    "reconsider",
    "reject",
    "not the root cause",
)


def _detect_dissent(content: str) -> bool:
    """결정론 dissent 감지. content 에 키워드 (대소문자 무시) 포함 시 True."""
    haystack = content.lower()
    for kw in _DISSENT_KEYWORDS:
        if kw.lower() in haystack:
            return True
    return False


# ---------------------------------------------------------------------------
# 발언자 역할 — 라운드 sequence
# ---------------------------------------------------------------------------
@dataclass
class Speaker:
    """라운드 발언자 — agent 이름 + 역할."""

    agent: str
    role: str  # proposer / reviewer / dissenter / mediator


def default_round_speakers(round_num: int, dissenters: list[str]) -> list[Speaker]:
    """라운드별 default 발언 순서.

    Round 1 (제안 + 1차 검토):
        proposer: SystemRefactoringStrategist
        reviewer: CTO, AutoFixCoordinator (RV 대표), PythonEngineer
    Round 2 (반박):
        dissenter: round 1 의 dissent 발견자들 재발언 + reviewer 추가 의견
    Round 3 (중재):
        mediator: BoardroomFacilitator 타협안
    """
    if round_num == 1:
        return [
            Speaker("SystemRefactoringStrategist", "proposer"),
            Speaker("CTO", "reviewer"),
            Speaker("AutoFixCoordinator", "reviewer"),
            Speaker("PythonEngineer", "reviewer"),
        ]
    if round_num == 2:
        speakers: list[Speaker] = []
        for d in dissenters:
            speakers.append(Speaker(d, "dissenter"))
        # Round 2 에 새로운 검토자 1명 추가 (의견 확장)
        speakers.append(Speaker("BuildEngineer", "reviewer"))
        return speakers
    if round_num == 3:
        return [Speaker("BoardroomFacilitator", "mediator")]
    return []


# ---------------------------------------------------------------------------
# Core: route_message / conduct_round / collect_dissent
# ---------------------------------------------------------------------------
def route_message(
    sender: str,
    message: str,
    recipients: Sequence[Speaker],
    proposal_context: str,
    prior_statements: Sequence[Statement],
    llm_call: Optional[Callable[[str], str]] = None,
) -> list[AgentResponse]:
    """sender 메시지를 recipients 에게 순차 라우팅 — 각자 응답 수집.

    Args:
        sender: 메시지 발신자 (예: "SystemRefactoringStrategist").
        message: 발신 내용 (예: 안건 본문 또는 라운드 진입 안내).
        recipients: 응답 받을 발언자 리스트.
        proposal_context: 안건 본문 (모든 prompt 의 base context).
        prior_statements: 이번 라운드 이전 *모든* 라운드의 발언 (context 누적).
        llm_call: ``llm(prompt) -> str``. None 이면 결정론 placeholder.

    Returns:
        AgentResponse list — 각 recipient 1건.
    """
    responses: list[AgentResponse] = []
    for spk in recipients:
        prompt = _build_speaker_prompt(
            speaker=spk,
            sender=sender,
            message=message,
            proposal_context=proposal_context,
            prior_statements=prior_statements,
        )
        content: str
        if llm_call is None:
            # 결정론 fallback — placeholder content (테스트 가능성 + LLM 없는 환경)
            content = _deterministic_placeholder(spk, sender)
        else:
            try:
                response = llm_call(prompt)
                content = _extract_speaker_content(response, spk)
            except Exception as exc:  # noqa: BLE001
                content = (
                    f"[{spk.agent} 발언 LLM 실패: {exc.__class__.__name__}] "
                    f"결정론 fallback: {_deterministic_placeholder(spk, sender)}"
                )
        is_dissent = (spk.role == "dissenter") or _detect_dissent(content)
        responses.append(
            AgentResponse(
                agent=spk.agent,
                role=spk.role,
                content=content,
                is_dissent=is_dissent,
            )
        )
    return responses


def _build_speaker_prompt(
    speaker: Speaker,
    sender: str,
    message: str,
    proposal_context: str,
    prior_statements: Sequence[Statement],
) -> str:
    role_guidance = {
        "proposer": "당신은 안건 발제자입니다. 안건 본문을 1~2문장으로 핵심만 요약하세요.",
        "reviewer": "당신은 안건 *1차 검토자* 입니다. 안건 본문을 *기술적 관점* 에서 검토하고, 동의 또는 우려 사항을 1~2문장으로 표명하세요.",
        "dissenter": "당신은 *반박자* 입니다. 이전 발언 context 를 읽고, 그 중 *동의하지 않는 부분* 을 *구체적 근거* 와 함께 반박하세요. 1~2문장.",
        "mediator": "당신은 *중재자* (Facilitator) 입니다. 이전 라운드들의 모든 발언을 종합하여 *타협안* 을 한 문장으로 제시하세요.",
    }.get(speaker.role, "당신은 발언자입니다. 1~2문장으로 의견을 제시하세요.")

    prior_text = "\n".join(
        f"  [{s.role}] {s.agent}: {s.content}" for s in prior_statements
    ) or "  (없음 — 첫 발언)"

    return (
        f"당신은 Nexus Alpha 의 *{speaker.agent}* 입니다. {role_guidance}\n\n"
        f"--- 안건 ---\n{proposal_context}\n\n"
        f"--- 이전 발언 (오래된 순) ---\n{prior_text}\n\n"
        f"--- 현재 발화자 메시지 ({sender}) ---\n{message}\n\n"
        f"응답 schema (JSON 한 줄):\n"
        f'{{"content": "<당신의 발언 1~2문장 한국어>"}}'
    )


def _extract_speaker_content(response: str, speaker: Speaker) -> str:
    """LLM 응답 → content 추출. JSON parse 실패 시 raw text 그대로 반환."""
    text = response.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "content" in parsed:
            return str(parsed["content"]).strip()
    except Exception:  # noqa: BLE001
        pass
    return text or f"({speaker.agent} 응답 빈 값)"


def _deterministic_placeholder(speaker: Speaker, sender: str) -> str:
    """LLM 없는 환경에서의 결정론 placeholder."""
    if speaker.role == "proposer":
        return f"[{speaker.agent}] 안건 발제 — 자율 진화 차원의 개선이 필요합니다."
    if speaker.role == "reviewer":
        return f"[{speaker.agent}] {sender} 안건 1차 검토 — 기술적 타당성 확인."
    if speaker.role == "dissenter":
        return (
            f"[{speaker.agent}] 반박 — 이전 발언 중 일부에 동의하지 않습니다. "
            f"더 구체적 근거가 필요합니다."
        )
    if speaker.role == "mediator":
        return (
            f"[{speaker.agent}] 중재 — 모든 발언을 종합하여 타협안을 제시합니다. "
            f"안건의 핵심을 보존하되 반박 사항을 부분 수용."
        )
    return f"[{speaker.agent}] 의견 제시."


def collect_dissent(responses: Sequence[AgentResponse]) -> list[str]:
    """발언 list → dissent 한 agent 이름 list (다음 라운드 진입 시 재발언자)."""
    return [r.agent for r in responses if r.is_dissent]


# ---------------------------------------------------------------------------
# 양방향 delegation 페어 — Boardroom 세션 컨텍스트 전용 (PM 명세 #3, PR #224)
# ---------------------------------------------------------------------------
def create_delegation_enabled_pair(
    llm: Optional[NexusAlphaLLM] = None,
) -> dict[str, Agent]:
    """Code Reviewer ↔ Python Engineer 양방향 위임 활성화 페어.

    PM 명세 #3 (PR #224):
        - allow_delegation=True 범위 제한: Boardroom 세션 중에만 활성화
        - default False 유지 (회귀 0)
        - --enable-boardroom 플래그 켜야 동작

    *Boardroom 세션 컨텍스트에서만* 본 함수 호출. 다른 컨텍스트 (kickoff /
    run_chain / build_workflow) 에서는 기존 create_xxx_agent(allow_delegation=False)
    패턴 유지.

    Returns:
        {"code_reviewer": Agent, "python_engineer": Agent} — 양방향 위임 활성.
    """
    from src.agents.engineering.python_engineer import create_python_engineer_agent
    from src.agents.qa.code_reviewer import create_code_reviewer_agent

    return {
        "code_reviewer": create_code_reviewer_agent(
            llm=llm, allow_delegation=True
        ),
        "python_engineer": create_python_engineer_agent(
            llm=llm, allow_delegation=True
        ),
    }


def conduct_round(
    round_num: int,
    proposal_context: str,
    prior_statements: Sequence[Statement],
    dissenters_from_prev: Optional[list[str]] = None,
    llm_call: Optional[Callable[[str], str]] = None,
    speakers: Optional[Sequence[Speaker]] = None,
) -> RoundResult:
    """1 라운드 진행 — 발언 수집 + dissent 감지.

    Args:
        round_num: 1, 2, 3 (4 이상은 ValueError).
        proposal_context: 안건 본문.
        prior_statements: 이전 라운드들의 *누적* 발언.
        dissenters_from_prev: round 2+ 에서 재발언자 결정용.
        llm_call: 동기 LLM 호출 (None = placeholder).
        speakers: 명시적 발언 순서 override (None = default_round_speakers).

    Returns:
        RoundResult — round + proceed_to_next.

    Raises:
        ValueError: round_num > 3.
    """
    if round_num < 1 or round_num > 3:
        raise ValueError(
            f"round_num 은 1~3 만 허용 (max 3 하드 캡). 받은 값: {round_num}"
        )

    speakers_list = list(
        speakers
        if speakers is not None
        else default_round_speakers(round_num, dissenters_from_prev or [])
    )
    if not speakers_list:
        return RoundResult(
            round=Round(round_num=round_num, ended_at=_now_ts()),
            proceed_to_next=False,
            early_exit_reason="speakers 빈 list — 발언자 미선정",
        )

    sender = "BoardroomFacilitator"
    message = f"라운드 {round_num} 시작. 각자 의견을 제시해 주세요."
    responses = route_message(
        sender=sender,
        message=message,
        recipients=speakers_list,
        proposal_context=proposal_context,
        prior_statements=prior_statements,
        llm_call=llm_call,
    )

    round_obj = Round(
        round_num=round_num,
        statements=[
            Statement(
                agent=r.agent,
                role=r.role,
                content=r.content,
                timestamp=r.timestamp,
            )
            for r in responses
        ],
        dissent_detected=any(r.is_dissent for r in responses),
        ended_at=_now_ts(),
    )

    # Round 3 (mediator) 는 항상 마지막 — 추가 라운드 진입 X.
    proceed = round_obj.dissent_detected and round_num < 3
    return RoundResult(round=round_obj, proceed_to_next=proceed)
