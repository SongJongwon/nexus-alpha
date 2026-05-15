# -*- coding: utf-8 -*-
"""
Coordination 본부 (본부 10) — 부서간 협의 / 합의 / 회고 전담 에이전트 패키지.

PR #138 Phase 1 full (2026-05-15, 본인 비전 통찰 6):
    "AI 가상 기업" 비전을 실제화하는 첫 본부 — 환율 변환기 사례 (1 USD = 1365.5
    stale, 9% 오차) 같은 cross-agent inconsistency 를 사전 차단하기 위해 워크플로
    시작 시점에 *킥오프 회의* 를 진행한다.

현재 멤버:
    - Meeting Facilitator (PR #138 full) — 킥오프 회의 진행

향후 멤버 (별도 PR sequence):
    - Retrospective Lead — 매 빌드 후 회고 자동 작성 (Phase 3)
    - Knowledge Curator (이미 src/agents/knowledge/) wiring — 다음 빌드 학습 반영

사용 예:
    from src.agents.coordination import (
        run_kickoff_meeting,
        SharedKickoffDecisions,
    )

    decisions = run_kickoff_meeting(
        user_request="환율 변환기 만들어줘",
        spec_markdown=requirement_expander_output,
    )
    workflow_dir.joinpath("shared_kickoff_decisions.yaml").write_text(
        decisions.to_yaml(), encoding="utf-8"
    )
"""

from .meeting_facilitator import (
    DEFAULT_PARTICIPANTS,
    MEETING_FACILITATOR_BACKSTORY,
    MEETING_FACILITATOR_GOAL,
    MEETING_FACILITATOR_NAME,
    MEETING_FACILITATOR_ROLE,
    run_kickoff_meeting,
)
from .schemas import (
    SharedAssumption,
    SharedKickoffDecisions,
)

__all__ = [
    "DEFAULT_PARTICIPANTS",
    "MEETING_FACILITATOR_BACKSTORY",
    "MEETING_FACILITATOR_GOAL",
    "MEETING_FACILITATOR_NAME",
    "MEETING_FACILITATOR_ROLE",
    "SharedAssumption",
    "SharedKickoffDecisions",
    "run_kickoff_meeting",
]
