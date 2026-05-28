# -*- coding: utf-8 -*-
"""Goal Alignment Agent — 본부 0 C-Level (v13 Phase 4, PR #222).

이전 *CEO* 역할의 격상 형태. 이사회 안건 (System Refactoring Strategist 발제) 을
*시스템 궁극적 목적* + *보안 거버넌스* 와 대조하여 ``approved`` / ``rejected``
의결권을 행사한다.

핵심 흐름 (Phase 4 의결권 활성화):
    Strategist 안건 → Boardroom Facilitator → ★ 본 에이전트 → AlignmentCheckResult
                                                   ↓
                                         alignment.status:
                                           - "approved" → 다음 노드 (budget)
                                           - "rejected" → final_decision=blocked

Phase 3 까지의 ``status="pending_phase4"`` 를 본 모듈이 교체.

검증 우선순위:
    1. 결정론 forbidden keywords (mission/security 위배 명백한 패턴) — 즉시 rejected
    2. LLM 호출 (옵션) — 모호한 경우 nuanced 판단 위임
    3. 기본 approved — 강한 부정 신호 부재
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# CrewAI Agent 프로파일
# ---------------------------------------------------------------------------
GOAL_ALIGNMENT_AGENT_NAME = "GoalAlignmentAgent"
GOAL_ALIGNMENT_AGENT_ROLE = "Goal Alignment Officer (C-Level, v13)"
GOAL_ALIGNMENT_AGENT_GOAL = (
    "이사회 안건을 시스템의 궁극적 목적 (자연어 → 동작 .exe 풀체인 자동화) 과 "
    "보안 거버넌스에 비추어 검토하고 approved/rejected 의결권을 행사한다."
)
GOAL_ALIGNMENT_AGENT_BACKSTORY = (
    "당신은 본부 0 C-Level 의 *목적 조율 관리자* 입니다. "
    "v12 의 CEO 역할이 v13 에서 *Goal Alignment Agent* 로 격상.\n\n"
    "Nexus Alpha 시스템의 *궁극적 목적*:\n"
    "  - 사용자의 자연어 요구 → 동작 가능한 .exe + Draft Release 풀체인 자동화\n"
    "  - 자기 진화: Telemetry 자율 인지 → 안건 발제 → 이사회 의결 → 자율 배포\n"
    "  - 사용자 신뢰: 회의록 + 의결 로그로 모든 결정 추적 가능\n\n"
    "*보안 거버넌스* (안건 검토 시 위배 여부 확인):\n"
    "  - 코드 리뷰 우회 금지 (Reviewer / QA 단계 SKIP 안건 거부)\n"
    "  - 외부 시스템 직접 변경 금지 (force push, prod DB 변경, 서비스 종료)\n"
    "  - Secrets/credentials 변경 금지\n"
    "  - .exe 실행 sandbox 우회 금지\n\n"
    "의결 원칙:\n"
    "  1. 안건이 위 목적과 *부합* 하면 approved\n"
    "  2. 보안 거버넌스 *위배* 가 명백하면 rejected (구체 이유 + 위배 항목 인용)\n"
    "  3. 모호한 경우 — 보수적으로 approved 하되 reason 에 우려 명시"
)


def create_goal_alignment_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = False,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Goal Alignment Agent CrewAI Agent 인스턴스 생성."""
    if llm is None:
        llm = NexusAlphaLLM()
    return Agent(
        name=GOAL_ALIGNMENT_AGENT_NAME,
        role=GOAL_ALIGNMENT_AGENT_ROLE,
        goal=GOAL_ALIGNMENT_AGENT_GOAL,
        backstory=GOAL_ALIGNMENT_AGENT_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )


# ---------------------------------------------------------------------------
# 결정론 forbidden 패턴 — 보안 거버넌스 위배 명백한 키워드 (한/영 혼합)
# ---------------------------------------------------------------------------
# 안건 title 또는 proposed_changes 에 본 키워드 (대소문자 무시) 포함 시 즉시 rejected.
_FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    # 보안 우회
    "disable security",
    "skip review",
    "bypass qa",
    "리뷰 우회",
    "리뷰 생략",
    "qa 우회",
    "qa 생략",
    # 외부 시스템 파괴적 변경
    "force push",
    "rm -rf",
    "drop database",
    "production deploy",
    "prod deploy",
    "프로덕션 배포",
    # Secrets / credentials
    "expose secret",
    "leak credential",
    "secret 노출",
)

DEFAULT_REFERENCES: tuple[str, ...] = (
    "Goal Alignment Agent backstory (mission)",
    "Goal Alignment Agent backstory (security governance)",
)


# ---------------------------------------------------------------------------
# 결과 산출 (boardroom_facilitator 의 AlignmentCheckResult 재활용)
# ---------------------------------------------------------------------------
def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class _ProposalView:
    """duck-typed proposal view — title + changes 텍스트 결합."""

    title: str
    changes_text: str


def _flatten_proposal(proposal: Any) -> _ProposalView:
    title = str(getattr(proposal, "title", ""))
    changes = getattr(proposal, "proposed_changes", []) or []
    if isinstance(changes, (list, tuple)):
        changes_text = " | ".join(str(c) for c in changes)
    else:
        changes_text = str(changes)
    return _ProposalView(title=title, changes_text=changes_text)


def _scan_forbidden(view: _ProposalView) -> Optional[str]:
    """결정론 forbidden 스캔. 히트 키워드 반환 또는 None."""
    haystack = f"{view.title} {view.changes_text}".lower()
    for kw in _FORBIDDEN_KEYWORDS:
        if kw.lower() in haystack:
            return kw
    return None


def _build_llm_prompt(view: _ProposalView) -> str:
    return (
        "다음은 Nexus Alpha 시스템 자율 개선 안건입니다. "
        "시스템 *목적* (자연어 → .exe 풀체인 자동화 + 자기 진화) 과 "
        "*보안 거버넌스* (코드 리뷰 / QA SKIP 금지, 외부 시스템 파괴적 변경 금지, "
        "secrets 노출 금지) 에 비추어 검토하고 결과를 *JSON 한 줄* 로 응답하세요.\n\n"
        f"안건 제목: {view.title}\n"
        f"제안 변경사항: {view.changes_text}\n\n"
        "응답 schema (필드 정확):\n"
        '{"status": "approved" | "rejected", "reason": "<한국어 1~2문장>"}\n'
        "approved: 목적 부합 + 보안 위배 없음\n"
        "rejected: 목적 위배 또는 보안 거버넌스 위배 명백"
    )


def assess_alignment(
    proposal: Any,
    llm_call: Optional[Callable[[str], str]] = None,
) -> "AlignmentCheckResult":  # noqa: F821 — 순환 import 회피, runtime 에서 import
    """안건 → AlignmentCheckResult.

    Args:
        proposal: ``RefactoringProposal`` duck-typed (``.title`` + ``.proposed_changes``).
        llm_call: 옵션 ``llm(prompt) -> str``. None 이면 결정론 + 기본 approved.

    Returns:
        AlignmentCheckResult (status / reason / references / checked_at).

    검증 순서:
        1. forbidden keyword 매칭 → rejected (즉시 종료)
        2. llm_call 제공 시 LLM 호출 → JSON parse → approved/rejected 산출
        3. 결정론 fallback → approved (강한 부정 신호 부재)
    """
    from src.agents.coordination.boardroom_facilitator import AlignmentCheckResult

    view = _flatten_proposal(proposal)
    references = list(DEFAULT_REFERENCES)

    # 1. forbidden keyword 결정론 검증
    hit = _scan_forbidden(view)
    if hit:
        return AlignmentCheckResult(
            status="rejected",
            note=(
                f"보안 거버넌스 위배 — 안건에 forbidden 키워드 '{hit}' 포함. "
                f"Goal Alignment Agent backstory 보안 거버넌스 항목 위배."
            ),
            references=references,
            checked_at=_now_ts(),
        )

    # 2. LLM 호출 (옵션)
    if llm_call is not None:
        prompt = _build_llm_prompt(view)
        try:
            response = llm_call(prompt)
            parsed = json.loads(response.strip())
            status = str(parsed.get("status", "approved")).lower()
            reason = str(parsed.get("reason", ""))
            if status not in {"approved", "rejected"}:
                status = "approved"  # 미지정 fallback
            return AlignmentCheckResult(
                status=status,
                note=reason or f"LLM 판단 — status={status}",
                references=references,
                checked_at=_now_ts(),
            )
        except Exception as exc:  # noqa: BLE001
            return AlignmentCheckResult(
                status="approved",
                note=(
                    f"LLM 호출 실패 ({exc.__class__.__name__}) — 결정론 forbidden "
                    f"스캔 통과로 보수적 approved. 안건 제목: {view.title[:60]}"
                ),
                references=references,
                checked_at=_now_ts(),
            )

    # 3. 결정론 fallback — 강한 부정 신호 부재 → approved
    return AlignmentCheckResult(
        status="approved",
        note=(
            "결정론 검증 통과 — forbidden 키워드 미매칭. "
            f"안건 제목: {view.title[:60]}"
        ),
        references=references,
        checked_at=_now_ts(),
    )
