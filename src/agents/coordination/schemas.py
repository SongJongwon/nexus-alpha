# -*- coding: utf-8 -*-
"""
Coordination 본부 — Shared Kickoff Decisions 스키마.

PR #138 Phase 1 full (본인 비전 통찰 6):
    환율 변환기 사례 (1 USD = 1365.5 stale, 실제 ~1490, 9% 오차) — 4 에이전트가
    *서로 다른 가정* (실시간 API vs 정적 dict) 으로 일했지만 누구도 인지 못함.
    Meeting Facilitator 가 워크플로 시작 시 킥오프 회의를 진행해 *공유 가정* 과
    *부서별 책임* 을 ``SharedKickoffDecisions`` 객체로 산출 → 후속 task 들의
    description 에 자동 주입함으로써 cross-agent inconsistency 재발 차단.

이 모듈은 *순수 데이터 구조* 만 정의. 산출 로직은 ``meeting_facilitator.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence

import yaml


# ---------------------------------------------------------------------------
# 개별 합의 항목
# ---------------------------------------------------------------------------
@dataclass
class SharedAssumption:
    """킥오프 회의에서 합의된 1개의 공유 가정.

    Attributes:
        id: 안정 식별자 (예: ``data_source``, ``ui_framework``). 후속 회고/학습
            시점에 ADR 처럼 추적 가능하도록 한국어가 아닌 영문 snake_case 권장.
        decision: 결정 내용 1줄 (예: "frankfurter API 실시간 호출").
        rationale: 왜 그 결정인지 (예: "stale 환율 위험 회피 — 환율 변환기 사례").
        owner: 결정을 *제안* 한 부서/역할 (예: "CTO"). 후속 충돌 시 escalate 대상.
    """

    id: str
    decision: str
    rationale: str
    owner: str


# ---------------------------------------------------------------------------
# 전체 회의 산출물
# ---------------------------------------------------------------------------
@dataclass
class SharedKickoffDecisions:
    """워크플로 진입 시 1회 산출되는 부서간 공유 결정 묶음.

    iteration 재진입 시 재생성하지 않고 LangGraph state 에 보존 (회의는 1회만).

    Attributes:
        user_request: 사용자의 원본 자연어 요청.
        spec_summary: Requirement Expander 산출 YAML 의 1~2 줄 요약 (사람용 헤더).
        shared_assumptions: 부서간 합의된 가정 목록 (환율 사례의 "frankfurter API" 같은).
        agent_responsibilities: 부서/역할 → 책임 항목 리스트. 빈 dict 가능 (LLM 미주입 시).
        open_questions: 회의에서 합의 못한 미해결 질문. Iteration Controller 의
            BLOCKED 판정 근거로 활용 가능.
    """

    user_request: str
    spec_summary: str
    shared_assumptions: list[SharedAssumption] = field(default_factory=list)
    agent_responsibilities: dict[str, list[str]] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    # PR #152 — RAG recall markdown 직접 흡수 (본인 비전 통찰 6 Phase 3 cycle wiring).
    #
    # 배경: PR #148 의 ``_node_recall_past_knowledge`` 가 state 에 entries 를
    # 저장하지만 task description 에 *주입되지 않아* 학습 효과 사실상 0 이었음.
    # PR #152 처방: ``_node_kickoff_meeting`` 이 ``format_recalled_entries_for_context``
    # 산출 markdown 을 본 필드에 담아 ``to_kickoff_context_directive`` 가 자동 append
    # → 기존 shared_kickoff_decisions 의 모든 task 주입 회로 (PR #138) 를 무료 재사용.
    recalled_knowledge_markdown: str = ""

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------
    def to_yaml(self) -> str:
        """파일 산출용 YAML 문자열 반환 (``shared_kickoff_decisions.yaml``).

        한국어 문자열을 escape 하지 않도록 ``allow_unicode=True``.
        """
        return yaml.safe_dump(
            asdict(self),
            allow_unicode=True,
            sort_keys=False,
        )

    @classmethod
    def from_yaml(cls, text: str) -> "SharedKickoffDecisions":
        """yaml 텍스트에서 복원. 라운드트립 + 외부 시스템 주입용."""
        data = yaml.safe_load(text) or {}
        assumptions = [
            SharedAssumption(**a) for a in data.get("shared_assumptions", [])
        ]
        return cls(
            user_request=data.get("user_request", ""),
            spec_summary=data.get("spec_summary", ""),
            shared_assumptions=assumptions,
            agent_responsibilities=dict(data.get("agent_responsibilities", {})),
            open_questions=list(data.get("open_questions", [])),
            recalled_knowledge_markdown=str(
                data.get("recalled_knowledge_markdown", "") or ""
            ),
        )

    # ------------------------------------------------------------------
    # task description 주입용 markdown 변환
    # ------------------------------------------------------------------
    def to_kickoff_context_directive(
        self, prior_agent_roles: Sequence[str] = (), *, product_scoped: bool = False
    ) -> str:
        """task description 끝에 append 할 *공유 결정 + consistency 강조* 섹션.

        ``format_consistency_directive`` (PR #138 minimal) 가 *지시* 만 추가했다면,
        이 메서드는 *실제 결정 사항* 을 markdown 으로 풀어 description 에 주입한다.
        LLM 이 prior task output 을 "참고" 가 아니라 *합의된 사실* 로 인식하도록 강제.

        Args:
            prior_agent_roles: 본 task 이전에 산출물이 있었던 에이전트 역할 리스트.
                빈 시퀀스면 consistency 절을 생략하고 결정만 표시한다.

        Returns:
            markdown 섹션 문자열. 빈 결정 + 빈 prior_agent_roles 면 ``""``.

        v13 Phase 6.E P14 — ``product_scoped=True`` (제품 코드 생성기 전용):
            시스템 내부 정보가 *생성 제품* 컨텍스트로 새는 것을 차단하기 위해 부서별 책임
            (agent_responsibilities = 시스템 에이전트 명단) · cross-agent consistency
            (prior_agent_roles = 에이전트 역할명) · RAG recall(recalled_knowledge_markdown
            = 과거 시스템 정보) 섹션을 *제거*. 제품 관련 결정(shared_assumptions/open_questions)
            만 유지. default False → 기존 모든 호출자 동작 불변 (회귀 0).
        """
        if product_scoped:
            prior_agent_roles = ()  # 에이전트 역할명 누수 차단
        has_decisions = bool(self.shared_assumptions) or bool(
            self.agent_responsibilities
        )
        has_recalled = bool(self.recalled_knowledge_markdown.strip())
        if not has_decisions and not prior_agent_roles and not has_recalled:
            return ""

        lines: list[str] = [
            "",
            "",
            "## 📌 킥오프 회의 합의 사항 (PR #138 Phase 1 full)",
            "",
            "Meeting Facilitator 가 워크플로 진입 시 진행한 *모든 부서 합의* 입니다. ",
            "본 task 산출물은 *반드시* 이 합의와 일치해야 합니다.",
            "",
        ]

        if self.shared_assumptions:
            lines.append("### 공유 가정 (부서간 합의 완료)")
            for a in self.shared_assumptions:
                lines.append(
                    f"- **{a.id}** ({a.owner}): {a.decision}  \n"
                    f"  *근거*: {a.rationale}"
                )
            lines.append("")

        if self.agent_responsibilities and not product_scoped:  # P14 — 제품 컨텍스트엔 누수 금지
            lines.append("### 부서별 책임 (킥오프 분담)")
            for role, items in self.agent_responsibilities.items():
                if not items:
                    continue
                lines.append(f"- **{role}**:")
                for item in items:
                    lines.append(f"  - {item}")
            lines.append("")

        if self.open_questions:
            lines.append("### 미해결 질문 (BLOCKED 판정 후보)")
            for q in self.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        if prior_agent_roles:
            roles_list = "\n".join(
                f"  - **{role}**" for role in prior_agent_roles
            )
            lines.extend(
                [
                    "### ⚠️ Cross-agent consistency",
                    "",
                    "위 컨텍스트의 다음 부서들이 *이미 결정한 사항* 이 있습니다:",
                    roles_list,
                    "",
                    "**반드시 그 결정 + 위 킥오프 합의와 일치하는 산출물을 작성하세요.** ",
                    "충돌 시:",
                    "1. 본문에 충돌 사실을 *명시적으로* 표기",
                    "2. 이유와 처리 방식 기록",
                    "3. *암묵적 무시* 금지 — 환율 변환기 사례 재발 차단",
                    "",
                ]
            )

        # PR #152 — RAG recall markdown append (본인 비전 통찰 6 Phase 3 cycle wiring).
        # _node_kickoff_meeting 이 채워 둔 ``recalled_knowledge_markdown`` 가 있으면
        # 본 directive 끝에 그대로 이어 붙임 → 모든 agent 가 과거 빌드 패턴 인지.
        if has_recalled and not product_scoped:  # P14 — 과거 시스템 정보 누수 금지
            lines.append(self.recalled_knowledge_markdown.rstrip())
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retrospective — 빌드 종료 후 회고 (PR #149, 2026-05-15)
# ---------------------------------------------------------------------------
@dataclass
class RetrospectiveReport:
    """본부 10 Retrospective Lead 가 매 빌드 종료 시 산출하는 4단 회고.

    PR #149 (본인 비전 통찰 6, D-5 처방 — 회고/학습 메커니즘 부재):
        Phase 3 wiring (PR #148) 의 Knowledge Curator 가 코드 본문에서 평면적
        정보로 summary/tags 채우는 한계를 해결. Retrospective Lead 가 *킥오프 합의 ↔
        실제 산출* 차이까지 회고한 markdown 을 Curator 의 prompt 입력으로 추가 →
        entry 의 summary/tags 가 학습 가능한 *결함/성공 패턴* 으로 풍부해짐.

    Attributes:
        workflow_id: 본 빌드의 디렉터리 이름.
        verdict: 결정표 verdict ("COMPLETE" / "BLOCKED").
        what_went_well: 성공 패턴 1~3개 (다음 빌드 재활용 대상).
        what_went_wrong: 결함 패턴 1~3개 (다음 빌드 회피 대상).
        lessons_learned: actionable insight 1~3개 (다음 빌드 task description 에
            힌트로 주입 가능한 *행동 가능한* 학습).
        delta_from_kickoff: 킥오프 합의 ↔ 실제 산출 차이 (있을 때만, 환율 사례 evidence).
    """

    workflow_id: str
    verdict: str
    what_went_well: list[str] = field(default_factory=list)
    what_went_wrong: list[str] = field(default_factory=list)
    lessons_learned: list[str] = field(default_factory=list)
    delta_from_kickoff: list[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "RetrospectiveReport":
        data = yaml.safe_load(text) or {}
        return cls(
            workflow_id=str(data.get("workflow_id", "")),
            verdict=str(data.get("verdict", "UNKNOWN")),
            what_went_well=list(data.get("what_went_well", []) or []),
            what_went_wrong=list(data.get("what_went_wrong", []) or []),
            lessons_learned=list(data.get("lessons_learned", []) or []),
            delta_from_kickoff=list(data.get("delta_from_kickoff", []) or []),
        )

    def to_markdown(self) -> str:
        """사람용 markdown — ``workflow_dir/retrospective.md`` 산출 + Curator prompt 입력."""
        lines = [
            f"# Retrospective — {self.workflow_id}",
            "",
            f"**verdict**: {self.verdict}",
            "",
        ]
        for title, items in (
            ("✅ What went well", self.what_went_well),
            ("❌ What went wrong", self.what_went_wrong),
            ("💡 Lessons learned", self.lessons_learned),
            ("⚠️  Delta from kickoff", self.delta_from_kickoff),
        ):
            lines.append(f"## {title}")
            if items:
                for it in items:
                    lines.append(f"- {it}")
            else:
                lines.append("- (없음)")
            lines.append("")
        return "\n".join(lines)


__all__ = [
    "RetrospectiveReport",
    "SharedAssumption",
    "SharedKickoffDecisions",
]
