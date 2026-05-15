# -*- coding: utf-8 -*-
"""
지식 관리(Knowledge) — Entry 스키마.

PR #140 Phase 3 (본인 비전 통찰 6, D-1 처방):
    Knowledge Curator 가 산출하는 ``KnowledgeEntry`` 와 RAG Searcher 가 검색하는
    구조. Curator/Searcher 둘 다 LLM agent 로 *이미* 존재하나 production path 에서
    호출 X (호출자 = 테스트 + 스크립트만) — 본 모듈의 helper 가 그 wiring 을 채운다.

이 모듈은 *순수 데이터 구조 + 결정론 파싱/직렬화* 만. LLM 호출은
``recall.py`` 와 ``curate.py`` 가 전담.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import yaml


VALID_QA_VERDICTS = ("APPROVED", "NEEDS_REVISION", "UNKNOWN")


@dataclass
class KnowledgeEntry:
    """Knowledge Curator 가 한 워크플로 종료 시 산출하는 1 entry.

    Attributes:
        workflow_id: 워크플로 디렉터리 이름 (예: ``workflow_20260515_120000``).
        curated_at: 색인 시점 ISO date (YYYY-MM-DD).
        user_request_oneline: 사용자 원 요청 1줄 압축 (최대 80자).
        summary: 핵심 산출물 1줄 요약 (최대 120자, 도구·언어·산출 형태).
        tags: 도메인/기술 스택/산출 형태/상태 태그 (5개 이내).
        artifacts: 디렉터리 내 핵심 파일 상대 경로 목록.
        qa_verdict: ``APPROVED`` / ``NEEDS_REVISION`` / ``UNKNOWN``.
    """

    workflow_id: str
    curated_at: str
    user_request_oneline: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    qa_verdict: str = "UNKNOWN"

    def to_yaml(self) -> str:
        return yaml.safe_dump(asdict(self), allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "KnowledgeEntry":
        data = yaml.safe_load(text) or {}
        return cls(
            workflow_id=str(data.get("workflow_id", "")),
            curated_at=str(data.get("curated_at", "")),
            user_request_oneline=str(data.get("user_request_oneline", "")),
            summary=str(data.get("summary", "")),
            tags=list(data.get("tags", []) or []),
            artifacts=list(data.get("artifacts", []) or []),
            qa_verdict=str(data.get("qa_verdict", "UNKNOWN")).upper()
            if data.get("qa_verdict")
            else "UNKNOWN",
        )

    def score_against_request(self, user_request: str) -> float:
        """결정론 키워드 매칭 점수 (0~10).

        RAG Searcher 의 LLM 점수 대신 *오프라인* fallback 으로 사용.
        ``user_request`` 의 토큰과 entry 의 ``tags + user_request_oneline + summary``
        매칭 수에 따라 0~10 점.

        Args:
            user_request: 새 사용자 요청 (자연어).

        Returns:
            0.0 ~ 10.0 점수. ``qa_verdict == "NEEDS_REVISION"`` 이거나
            ``"partial-output"`` 태그 있으면 -2 페널티 (백스토리의 *항상 하향정렬*
            원칙 반영).
        """
        if not user_request:
            return 0.0
        tokens = {t for t in re.split(r"\W+", user_request.lower()) if len(t) >= 2}
        if not tokens:
            return 0.0

        haystack_parts = (
            [t.lower() for t in self.tags]
            + [self.user_request_oneline.lower(), self.summary.lower()]
        )
        haystack = " ".join(haystack_parts)

        hits = sum(1 for t in tokens if t in haystack)
        # max 5점 — 키워드 매칭, max 5점 — 태그 hit
        keyword_score = min(5.0, hits * 1.5)
        tag_hits = sum(1 for t in self.tags if t.lower() in tokens)
        tag_score = min(5.0, tag_hits * 2.0)
        raw = keyword_score + tag_score

        # 백스토리 페널티 — qa-needs-revision / partial-output 항상 하향정렬
        if self.qa_verdict == "NEEDS_REVISION":
            raw -= 2.0
        if any(t.lower() == "partial-output" for t in self.tags):
            raw -= 2.0

        return max(0.0, min(10.0, raw))


__all__ = ["KnowledgeEntry", "VALID_QA_VERDICTS"]
