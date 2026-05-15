# -*- coding: utf-8 -*-
"""
지식 색인(Knowledge Curate) — Knowledge Curator 호출 helper.

PR #140 Phase 3 (본인 비전 통찰 6, D-1):
    워크플로 종료 시 (finalize 또는 escalate) 1회 호출되어 본 빌드의 산출물을
    ``KnowledgeEntry`` yaml 로 산출 + 분산/중앙 두 곳에 저장. 다음 빌드 진입 시
    ``recall_past_entries`` 가 이 entry 들에서 검색.

저장 구조 (옵션 C — 분산 + 중앙):
    - 분산: ``<workflow_dir>/knowledge_entry.yaml`` (워크플로 자체 산출물)
    - 중앙: ``<outputs_dir>/knowledge_index/<workflow_id>.yaml`` (검색용 인덱스)

LLM 호출 (선택):
    Meeting Facilitator (PR #146) / recall (PR #140) 와 동일한 하이브리드 패턴.
    pytest 환경에선 결정론 entry 만 산출 (summary/tags 빈 상태). 실 환경에선
    ``KnowledgeCurator`` 에이전트를 1 LLM call 로 호출해 summary/tags 채움.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .schemas import VALID_QA_VERDICTS, KnowledgeEntry


# ---------------------------------------------------------------------------
# PR #154 — knowledge_index LRU 회전 정책 (본인 비전 통찰 6 Phase 3 cycle 후속)
# ---------------------------------------------------------------------------
# 배경: PR #148 부터 ``outputs/knowledge_index/<wid>.yaml`` 무제한 누적. 100+ 빌드
# 누적 시 ``recall_past_entries`` 의 glob + parse 비용 + disk 사용량 증가 위험.
#
# 처방 (의존성 0, 결정론):
#   - LRU by ``curated_at`` (ISO date string, lex sort 친화) — 가장 최근 N 개만 유지
#   - 기본 N=50, ``NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES`` env var override
#   - curate_workflow 종료 시 트리거 — 새 entry 작성 직후 정리
#   - tie break (동일 curated_at) → workflow_id alphabet — 결정론 보장
#   - 실패 격리: 정리 도중 OSError 등은 워크플로 차단 사유 아님

DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES = 50


def _resolve_max_entries(explicit: Optional[int]) -> int:
    """env var 또는 명시 인자로 최대 entry 수 결정. <= 0 이면 회전 비활성."""
    if explicit is not None:
        return explicit
    raw = os.environ.get("NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES")
    if raw is None or raw.strip() == "":
        return DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES


def _entry_sort_key(yaml_path: Path) -> tuple[str, str]:
    """LRU 정렬 키 — ``(curated_at, workflow_id)``.

    실패 시 ``("", path.stem)`` 으로 fallback — 가장 오래된 것으로 분류되어
    우선 삭제 후보가 됨 (의도적: 깨진 entry 정리 효과).
    """
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        curated_at = str(data.get("curated_at", "") or "")
        workflow_id = str(data.get("workflow_id", "") or yaml_path.stem)
        return (curated_at, workflow_id)
    except (OSError, yaml.YAMLError, ValueError):
        return ("", yaml_path.stem)


def prune_knowledge_index_lru(
    knowledge_index_dir: Path,
    *,
    max_entries: Optional[int] = None,
) -> list[Path]:
    """``knowledge_index_dir`` 의 yaml 파일을 LRU 정책으로 정리.

    ``curated_at`` 내림차순 + ``workflow_id`` 내림차순 (tie break) 으로 정렬해 상위
    ``max_entries`` 개만 유지, 나머지 hard delete. 디렉터리 부재 / 빈 디렉터리 /
    파일 수 <= max_entries → no-op.

    Args:
        knowledge_index_dir: ``outputs/knowledge_index/`` 경로.
        max_entries: 유지할 최대 entry 수. None 이면 env var 또는 기본 (50) 사용.
            ``<= 0`` 이면 회전 비활성 (no-op).

    Returns:
        삭제된 yaml 파일 경로 리스트 (회귀 테스트용). 정책 비활성 / 정리 불요 / 실패 시
        빈 리스트.
    """
    if not knowledge_index_dir.exists() or not knowledge_index_dir.is_dir():
        return []

    limit = _resolve_max_entries(max_entries)
    if limit <= 0:
        return []

    yaml_files = list(knowledge_index_dir.glob("*.yaml"))
    if len(yaml_files) <= limit:
        return []

    # 내림차순 정렬 (최신이 앞) — (curated_at, workflow_id) tie break
    yaml_files.sort(key=_entry_sort_key, reverse=True)
    to_keep = yaml_files[:limit]
    to_delete = yaml_files[limit:]

    deleted: list[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
        except OSError:
            # 1 파일 실패해도 나머지 정리 계속 — graceful
            continue
    return deleted


# ---------------------------------------------------------------------------
# 결정론 산출 — workflow_dir 메타데이터에서 entry 골격
# ---------------------------------------------------------------------------
_FINAL_ANSWER_RE = re.compile(r"Final Answer:\s*(APPROVED|NEEDS_REVISION)", re.IGNORECASE)


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _extract_qa_verdict(workflow_dir: Path) -> str:
    """``04_qa_review.md`` 의 ``Final Answer:`` 줄에서 verdict 결정론 추출."""
    review = _read_text_safe(workflow_dir / "04_qa_review.md")
    if not review:
        return "UNKNOWN"
    match = _FINAL_ANSWER_RE.search(review)
    if not match:
        return "UNKNOWN"
    verdict = match.group(1).upper()
    return verdict if verdict in VALID_QA_VERDICTS else "UNKNOWN"


def _shorten(text: str, limit: int) -> str:
    """``limit`` 문자 안으로 압축 — 줄바꿈 제거 + 길이 cap."""
    flat = " ".join(text.split())
    return flat[:limit]


def _list_artifacts(workflow_dir: Path) -> list[str]:
    """디렉터리 내 핵심 파일 상대 경로 목록 (00~04 + code/ 대표)."""
    artifacts: list[str] = []
    for name in ("00_user_request.txt", "01_cto_strategy.md", "02_analyst_brief.md",
                 "03_engineer_output.md", "04_qa_review.md"):
        if (workflow_dir / name).exists():
            artifacts.append(name)
    code_dir = workflow_dir / "code"
    if code_dir.is_dir():
        for p in sorted(code_dir.glob("*.py"))[:3]:
            artifacts.append(f"code/{p.name}")
    return artifacts


def _build_deterministic_entry(
    workflow_dir: Path,
    user_request: str,
    qa_verdict_hint: Optional[str] = None,
) -> KnowledgeEntry:
    """LLM 없이 산출 가능한 entry 골격 — summary/tags 는 빈 채로."""
    workflow_id = workflow_dir.name
    curated_at = datetime.now().strftime("%Y-%m-%d")

    if qa_verdict_hint and qa_verdict_hint.upper() in VALID_QA_VERDICTS:
        verdict = qa_verdict_hint.upper()
    else:
        verdict = _extract_qa_verdict(workflow_dir)

    user_request_oneline = _shorten(user_request, 80)

    return KnowledgeEntry(
        workflow_id=workflow_id,
        curated_at=curated_at,
        user_request_oneline=user_request_oneline,
        summary="",
        tags=[],
        artifacts=_list_artifacts(workflow_dir),
        qa_verdict=verdict,
    )


# ---------------------------------------------------------------------------
# 1 LLM call (선택) — summary + tags 채움
# ---------------------------------------------------------------------------
_CURATE_PROMPT_TEMPLATE = """\
당신은 한국 IT 회사의 지식 큐레이터입니다. 아래 사용자 요청 + 산출물 미리보기 +
회고 (있으면) 를 보고, **JSON 으로** summary (최대 120자, 1줄) + tags (5개 이내)
만 출력하세요. 다른 설명 금지.

스키마:
{{
  "summary": "...",
  "tags": ["domain-x", "python", "cli-script", "qa-approved", ...]
}}

태그 선택 가이드:
  - 도메인 (예: excel-to-pdf, file-converter, calculator)
  - 기술 스택 (예: python, pandas, tkinter)
  - 산출 형태 (예: cli-script, gui-app, package)
  - 상태 (qa-approved / qa-needs-revision / partial-output 중 1)
  - **회고 기반 태그** (PR #149) — Retrospective Lead 가 결함 패턴 명시한 경우
    그 패턴을 short-hand tag 로 (예: stale-data-dict / mock-vs-real / timeout-too-short)

--- 사용자 요청 ---
{user_request}
--- 산출물 미리보기 (최대 800자) ---
{preview}
--- QA verdict (결정론 추출) ---
{verdict}
--- 회고 (Retrospective Lead 산출, 있으면) ---
{retrospective}
--- 끝 ---
"""


def _build_preview(workflow_dir: Path, max_chars: int = 800) -> str:
    """산출물 핵심 본문 미리보기 — Engineer output 우선, 없으면 CTO 전략."""
    for name in ("03_engineer_output.md", "13_gui_code_output.md", "01_cto_strategy.md"):
        text = _read_text_safe(workflow_dir / name)
        if text:
            return _shorten(text, max_chars)
    return "(산출물 미리보기 없음)"


def _parse_curate_response(text: str) -> tuple[str, list[str]]:
    """LLM 응답에서 summary + tags 추출. 실패 시 (``""``, ``[]``)."""
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
        summary = str(data.get("summary", "")).strip()
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list):
            continue
        tags = [str(t).strip() for t in raw_tags if str(t).strip()][:5]
        if summary or tags:
            return summary[:120], tags
    return "", []


def _default_llm_call(prompt: str) -> str:
    """기본 LLM 호출 — Meeting Facilitator / recall 과 동일 패턴."""
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
def curate_workflow(
    workflow_dir: Path,
    user_request: str,
    *,
    knowledge_index_dir: Optional[Path] = None,
    qa_verdict_hint: Optional[str] = None,
    retrospective_md: str = "",
    llm_call: Optional[Callable[[str], str]] = None,
) -> tuple[KnowledgeEntry, Path, Optional[Path]]:
    """워크플로 종료 시 1회 호출 — KnowledgeEntry 산출 + yaml 저장.

    Args:
        workflow_dir: 본 워크플로의 산출 디렉터리 (``outputs/workflow_<ts>/``).
            존재해야 하며 ``workflow_id`` = ``workflow_dir.name``.
        user_request: 사용자 원 자연어 요청.
        knowledge_index_dir: 중앙 인덱스 디렉터리. None 이면 분산 저장만.
            지정 시 ``<index_dir>/<workflow_id>.yaml`` 복사본 추가 저장.
        qa_verdict_hint: 호출 측에서 알고 있는 verdict (있으면 우선 사용,
            없으면 ``04_qa_review.md`` 결정론 파싱).
        retrospective_md: PR #149 — Retrospective Lead 산출 markdown (있으면).
            Curator prompt 에 추가 입력으로 들어가 entry summary/tags 가 *결함/성공
            패턴* 으로 풍부해진다. 빈 문자열이면 PR #148 동작 그대로.
        llm_call: 외부 주입 가능한 LLM 호출 (테스트용). None + 비-pytest 환경에선
            ``_default_llm_call`` 사용. pytest 환경에선 자동 skip.

    Returns:
        ``(entry, distributed_yaml_path, index_yaml_path_or_none)`` 트리플.
        디스크 저장 실패 시에도 entry 객체는 반환 (path 는 None 가능).
    """
    entry = _build_deterministic_entry(workflow_dir, user_request, qa_verdict_hint)

    in_pytest = "pytest" in sys.modules
    if llm_call is None and not in_pytest:
        llm_call = _default_llm_call

    if llm_call is not None:
        prompt = _CURATE_PROMPT_TEMPLATE.format(
            user_request=user_request.strip(),
            preview=_build_preview(workflow_dir),
            verdict=entry.qa_verdict,
            retrospective=retrospective_md.strip() if retrospective_md else "(회고 없음)",
        )
        try:
            response = llm_call(prompt)
            summary, tags = _parse_curate_response(response or "")
        except Exception:
            summary, tags = "", []
        if summary:
            entry.summary = summary
        if tags:
            entry.tags = tags

    # 분산 저장 (워크플로 자체 산출물)
    distributed_path = workflow_dir / "knowledge_entry.yaml"
    try:
        workflow_dir.mkdir(parents=True, exist_ok=True)
        distributed_path.write_text(entry.to_yaml(), encoding="utf-8")
    except OSError:
        pass

    # 중앙 인덱스 저장 (검색용)
    index_path: Optional[Path] = None
    if knowledge_index_dir is not None:
        try:
            knowledge_index_dir.mkdir(parents=True, exist_ok=True)
            index_path = knowledge_index_dir / f"{entry.workflow_id}.yaml"
            index_path.write_text(entry.to_yaml(), encoding="utf-8")
        except OSError:
            index_path = None

        # PR #154 — LRU 회전 (새 entry 작성 직후 트리거, 실패 격리)
        try:
            prune_knowledge_index_lru(knowledge_index_dir)
        except Exception:  # noqa: BLE001 — 정리 실패는 워크플로 차단 X
            pass

    return entry, distributed_path, index_path


__all__ = [
    "DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES",
    "curate_workflow",
    "prune_knowledge_index_lru",
]
