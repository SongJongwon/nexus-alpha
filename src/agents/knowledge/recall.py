# -*- coding: utf-8 -*-
"""
지식 회상(Knowledge Recall) — RAG Searcher 호출 helper.

PR #140 Phase 3 (본인 비전 통찰 6, D-1):
    워크플로 진입 시 1회 호출되어 ``knowledge_index/`` 의 과거 entry 들에서
    현재 사용자 요청과 유사한 top-N 을 반환한다. Meeting Facilitator (PR #146)
    와 유사한 *하이브리드 (결정론 + 1 LLM call)* 패턴:

        1. 결정론 prefilter — ``KnowledgeEntry.score_against_request`` 키워드 매칭
        2. 단 1 LLM call (선택) — top-K 후보를 RAG Searcher 가 reranking

    pytest 환경에선 LLM 호출 자동 skip — 결정론 점수만으로 정렬.

호출 측 사용:
    from src.agents.knowledge import recall_past_entries

    entries = recall_past_entries(
        user_request="환율 변환기 만들어줘",
        knowledge_index_dir=Path("outputs/knowledge_index"),
        top_n=3,
    )
    for e in entries:
        print(e.summary, e.tags)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

import yaml

from .schemas import KnowledgeEntry


# ---------------------------------------------------------------------------
# 결정론 파싱 — 디스크 entry 읽기
# ---------------------------------------------------------------------------
def _load_entries_from_dir(index_dir: Path) -> list[KnowledgeEntry]:
    """``index_dir`` 의 ``*.yaml`` 모두 읽어 ``KnowledgeEntry`` 리스트로 반환.

    파일 1개 파싱 실패는 skip (전체 차단 X). 디렉터리 부재 시 빈 리스트.
    """
    if not index_dir.exists() or not index_dir.is_dir():
        return []

    entries: list[KnowledgeEntry] = []
    for path in sorted(index_dir.glob("*.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
            entries.append(KnowledgeEntry.from_yaml(text))
        except (OSError, ValueError, yaml.YAMLError):
            # 깨진 yaml 파일 1개 때문에 recall 전체 차단 X — 그 파일만 skip
            continue
    return entries


def _deterministic_top_n(
    user_request: str,
    entries: Sequence[KnowledgeEntry],
    top_n: int,
) -> list[tuple[KnowledgeEntry, float]]:
    """결정론 키워드 매칭으로 top-N 후보 산출.

    Returns:
        ``(entry, score)`` 페어 리스트, score 내림차순 정렬, ``top_n`` 까지.
        score 0.0 entry 는 제외 (의미 없는 추천 방지).
    """
    scored = [
        (e, e.score_against_request(user_request)) for e in entries
    ]
    scored = [s for s in scored if s[1] > 0.0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[: max(0, top_n)]


# ---------------------------------------------------------------------------
# 1 LLM call (선택) — RAG Searcher reranking
# ---------------------------------------------------------------------------
_RERANK_PROMPT_TEMPLATE = """\
당신은 한국 IT 회사의 지식 검색 전문가입니다. 아래 사용자 요청과 후보 entry 목록을 보고,
가장 관련 높은 순서로 *workflow_id 의 리스트* 만 JSON 으로 출력하세요. 다른 설명 금지.

스키마:
{{
  "reranked_workflow_ids": ["workflow_xxx", "workflow_yyy", ...]
}}

--- 사용자 요청 ---
{user_request}
--- 후보 entry (결정론 score 내림차순) ---
{candidates_block}
--- 끝 ---
"""


def _format_candidates_block(scored: Sequence[tuple[KnowledgeEntry, float]]) -> str:
    lines: list[str] = []
    for entry, score in scored:
        tags = ", ".join(entry.tags) if entry.tags else "-"
        lines.append(
            f"- workflow_id={entry.workflow_id} score={score:.1f} verdict={entry.qa_verdict}\n"
            f"  request: {entry.user_request_oneline}\n"
            f"  summary: {entry.summary}\n"
            f"  tags: {tags}"
        )
    return "\n".join(lines)


def _parse_rerank_response(text: str) -> list[str]:
    """LLM 응답에서 ``reranked_workflow_ids`` list 추출. 실패 시 빈 list."""
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    candidates: list[str] = []
    if fence is not None:
        candidates.append(fence.group(1))
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    candidates.append(text)

    for chunk in candidates:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        ids = data.get("reranked_workflow_ids")
        if isinstance(ids, list):
            return [str(i) for i in ids if str(i).strip()]
    return []


def _default_llm_call(prompt: str) -> str:
    """기본 LLM 호출 — ``src.llm.get_llm_provider`` 동기 wrap (Meeting Facilitator 와 동일)."""
    import asyncio
    import concurrent.futures

    from src.llm import get_llm_provider

    async def _go() -> str:
        provider = get_llm_provider()
        return await provider.generate(prompt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _go())
        return future.result()


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def recall_past_entries(
    user_request: str,
    knowledge_index_dir: Path,
    *,
    top_n: int = 3,
    prefilter_k: int = 8,
    llm_call: Optional[Callable[[str], str]] = None,
) -> list[KnowledgeEntry]:
    """과거 KnowledgeEntry 들에서 ``user_request`` 와 가장 관련된 top-N 반환.

    Args:
        user_request: 새 사용자 요청 (자연어).
        knowledge_index_dir: ``KnowledgeEntry`` yaml 들이 누적된 디렉터리.
            존재하지 않거나 비어 있으면 빈 리스트.
        top_n: 최종 반환 개수 (기본 3).
        prefilter_k: 결정론 prefilter 가 LLM 에게 넘기는 후보 수 (기본 8).
            너무 크면 prompt 비용 증가, 너무 작으면 LLM 의 rerank 가치 줄어듦.
        llm_call: 외부 주입 가능한 LLM 호출 (테스트용). None 이면 pytest 환경
            자동 skip / 외 환경에선 ``_default_llm_call`` 사용.

    Returns:
        ``KnowledgeEntry`` 리스트 (top-N). 비어 있을 수 있음.
    """
    entries = _load_entries_from_dir(knowledge_index_dir)
    if not entries:
        return []

    # 1) 결정론 prefilter
    candidates = _deterministic_top_n(user_request, entries, prefilter_k)
    if not candidates:
        return []

    # pytest 환경 + 외부 주입 없음 → 결정론 결과만 top_n 으로 자름
    in_pytest = "pytest" in sys.modules
    if llm_call is None and not in_pytest:
        llm_call = _default_llm_call

    if llm_call is None:
        return [c[0] for c in candidates[:top_n]]

    # 2) LLM rerank (선택) — 실패 시 결정론 결과 fallback
    try:
        response = llm_call(
            _RERANK_PROMPT_TEMPLATE.format(
                user_request=user_request.strip(),
                candidates_block=_format_candidates_block(candidates),
            )
        )
    except Exception:
        return [c[0] for c in candidates[:top_n]]

    reranked_ids = _parse_rerank_response(response or "")
    if not reranked_ids:
        return [c[0] for c in candidates[:top_n]]

    by_id = {c[0].workflow_id: c[0] for c in candidates}
    reordered: list[KnowledgeEntry] = []
    for wid in reranked_ids:
        entry = by_id.pop(wid, None)
        if entry is not None:
            reordered.append(entry)
    # LLM 이 누락한 후보가 있으면 결정론 순서로 뒤에 붙임
    reordered.extend(by_id.values())
    return reordered[:top_n]


def format_recalled_entries_for_context(
    entries: Sequence[KnowledgeEntry],
) -> str:
    """recall 결과를 task description 끝에 append 할 markdown 으로 변환.

    빈 리스트면 ``""`` 반환 (no-op). Meeting Facilitator 의
    ``to_kickoff_context_directive`` 와 유사한 패턴.
    """
    if not entries:
        return ""

    lines = [
        "",
        "",
        "## 🧠 과거 빌드 학습 (PR #140 Phase 3 — RAG recall)",
        "",
        "Knowledge Curator 가 색인한 과거 빌드 entry 중 본 요청과 관련 높은 것:",
        "",
    ]
    for e in entries:
        tags = ", ".join(e.tags) if e.tags else "-"
        lines.append(
            f"- **{e.workflow_id}** (verdict={e.qa_verdict})\n"
            f"  request: {e.user_request_oneline}\n"
            f"  summary: {e.summary}\n"
            f"  tags: {tags}"
        )
    lines.append("")
    lines.append(
        "→ 이 entry 들의 *성공 패턴* 은 재활용하고, ``qa-needs-revision`` / "
        "``partial-output`` 태그가 붙은 entry 의 *결함 패턴* 은 회피하세요."
    )
    return "\n".join(lines)


__all__ = [
    "format_recalled_entries_for_context",
    "recall_past_entries",
]
