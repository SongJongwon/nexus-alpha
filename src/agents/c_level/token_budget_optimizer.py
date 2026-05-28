# -*- coding: utf-8 -*-
"""Token Budget Optimizer — 본부 0 C-Level (v13 Phase 4, PR #222).

이전 *CFO* 역할의 격상 형태. 이사회 안건의 *예상 LLM 비용* 을 견적하고
*누적 비용 + 한도* 와 대조하여 ``approved`` / ``throttled`` 의결권을 행사.

핵심 흐름 (Phase 4 의결권 활성화):
    Strategist 안건 → Boardroom → ★ 본 에이전트 → BudgetBrakeResult
                                                    ↓
                                          budget.status:
                                            - "approved"  → 다음 노드
                                            - "throttled" → final_decision=blocked

비용 견적 규칙 (결정론 우선 — LLM 무관):
    proposal.estimated_cost 필드 활용 ("low" / "medium" / "high"):
        - low    → 0.50 USD
        - medium → 2.00 USD
        - high   → 10.00 USD

    예상 비용 + 이번 run 누적 비용 ≤ 한도 → approved
    예상 비용 + 이번 run 누적 비용  > 한도 → throttled

누적 비용 출처:
    1. 환경변수 ``NEXUS_BOARDROOM_CUMULATIVE_COST_USD`` (test injection 또는
       외부 빌링 시스템 합산 결과 주입용)
    2. 미설정 시 ``events.jsonl`` token_usage 이벤트 합산 (best-effort)
    3. 둘 다 부재 시 0.0 (run 시작 시점)

한도 출처:
    1. 환경변수 ``NEXUS_BOARDROOM_BUDGET_LIMIT_USD`` (default 15.0 — PR #163 banner 와 일치)

가격 단가 (Opus 4.7 기준, Anthropic 공시):
    input  $3.00 / 1M tokens
    output $15.00 / 1M tokens
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# CrewAI Agent 프로파일
# ---------------------------------------------------------------------------
TOKEN_BUDGET_OPTIMIZER_NAME = "TokenBudgetOptimizer"
TOKEN_BUDGET_OPTIMIZER_ROLE = "Token Budget Optimizer (C-Level, v13)"
TOKEN_BUDGET_OPTIMIZER_GOAL = (
    "이사회 안건의 예상 LLM 비용을 견적하고 누적 비용 + 예산 한도와 대조하여 "
    "approved/throttled 의결권을 행사한다."
)
TOKEN_BUDGET_OPTIMIZER_BACKSTORY = (
    "당신은 본부 0 C-Level 의 *기술 재무 관리자* 입니다. "
    "v12 의 CFO 역할이 v13 에서 *Token Budget Optimizer* 로 격상.\n\n"
    "Nexus Alpha 의 *자원 거버넌스*:\n"
    "  - 1 run 당 LLM 비용 한도 (default $15) 초과 금지\n"
    "  - 안건 적용 시 추가 비용 견적 + 누적 비용 합산 검토\n"
    "  - 한도 초과 시 throttled — Strategist 가 *비용 절감 안건* 으로 재발제 유도\n\n"
    "Anthropic 단가 (Opus 4.7):\n"
    "  input  $3.00 / 1M tokens\n"
    "  output $15.00 / 1M tokens\n\n"
    "의결 원칙:\n"
    "  1. 안건 estimated_cost 가 'low'/'medium'/'high' 매핑된 USD 추정값 사용\n"
    "  2. 추정값 + 누적 ≤ 한도 → approved (잔여 예산 reason 명시)\n"
    "  3. 추정값 + 누적 > 한도 → throttled (초과액 reason 명시)"
)


def create_token_budget_optimizer_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = False,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Token Budget Optimizer CrewAI Agent 인스턴스 생성."""
    if llm is None:
        llm = NexusAlphaLLM()
    return Agent(
        name=TOKEN_BUDGET_OPTIMIZER_NAME,
        role=TOKEN_BUDGET_OPTIMIZER_ROLE,
        goal=TOKEN_BUDGET_OPTIMIZER_GOAL,
        backstory=TOKEN_BUDGET_OPTIMIZER_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )


# ---------------------------------------------------------------------------
# 비용 견적 — proposal.estimated_cost (low/medium/high) → USD 매핑
# ---------------------------------------------------------------------------
_COST_USD_BY_TIER: dict[str, float] = {
    "low": 0.50,
    "medium": 2.00,
    "high": 10.00,
}

DEFAULT_BUDGET_LIMIT_USD = 15.00

# Anthropic Opus 4.7 단가 (1M tokens 기준 USD)
_OPUS_INPUT_USD_PER_1M = 3.00
_OPUS_OUTPUT_USD_PER_1M = 15.00


def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _estimated_cost_for_proposal(proposal: Any) -> float:
    """proposal.estimated_cost ∈ {low, medium, high} → USD."""
    tier = str(getattr(proposal, "estimated_cost", "medium")).lower()
    return _COST_USD_BY_TIER.get(tier, _COST_USD_BY_TIER["medium"])


def _budget_limit_usd() -> float:
    """환경변수 ``NEXUS_BOARDROOM_BUDGET_LIMIT_USD`` → float (default 15.0)."""
    raw = os.environ.get("NEXUS_BOARDROOM_BUDGET_LIMIT_USD")
    if not raw:
        return DEFAULT_BUDGET_LIMIT_USD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_BUDGET_LIMIT_USD


def _cumulative_cost_from_events_jsonl(events_path: Path) -> float:
    """events.jsonl token_usage 이벤트 합산. 실패 silent → 0.0."""
    if not events_path.exists():
        return 0.0
    total = 0.0
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if ev.get("type") != "token_usage":
                continue
            input_t = float(ev.get("input_tokens", 0))
            output_t = float(ev.get("output_tokens", 0))
            total += (input_t / 1_000_000.0) * _OPUS_INPUT_USD_PER_1M
            total += (output_t / 1_000_000.0) * _OPUS_OUTPUT_USD_PER_1M
    except Exception:  # noqa: BLE001
        return 0.0
    return total


def _cumulative_cost_usd(events_path: Optional[Path] = None) -> float:
    """누적 비용 — env 우선 → events.jsonl → 0.0."""
    raw = os.environ.get("NEXUS_BOARDROOM_CUMULATIVE_COST_USD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    if events_path is not None:
        return _cumulative_cost_from_events_jsonl(events_path)
    # NEXUS_TELEMETRY_PATH fallback
    tele_path = os.environ.get("NEXUS_TELEMETRY_PATH")
    if tele_path:
        return _cumulative_cost_from_events_jsonl(Path(tele_path))
    return 0.0


# ---------------------------------------------------------------------------
# 의결 결과 산출 (boardroom_facilitator 의 BudgetBrakeResult 재활용)
# ---------------------------------------------------------------------------
@dataclass
class BudgetSnapshot:
    """비용 견적 + 한도 + 누적 — assess_budget 산출 보조 구조."""

    estimated_cost_usd: float
    budget_limit_usd: float
    cumulative_cost_usd: float

    @property
    def projected_total_usd(self) -> float:
        return self.estimated_cost_usd + self.cumulative_cost_usd

    @property
    def remaining_usd(self) -> float:
        return self.budget_limit_usd - self.cumulative_cost_usd

    @property
    def overage_usd(self) -> float:
        return self.projected_total_usd - self.budget_limit_usd


def _build_llm_prompt(snap: BudgetSnapshot, proposal: Any) -> str:
    title = str(getattr(proposal, "title", ""))
    return (
        "다음은 Nexus Alpha 이사회 안건의 비용 견적입니다. "
        "안건 적용이 예산 한도 내에서 안전한지 판단하고 결과를 *JSON 한 줄* 로 응답하세요.\n\n"
        f"안건 제목: {title}\n"
        f"안건 예상 비용 (USD): {snap.estimated_cost_usd:.2f}\n"
        f"이번 run 누적 비용 (USD): {snap.cumulative_cost_usd:.2f}\n"
        f"예산 한도 (USD): {snap.budget_limit_usd:.2f}\n"
        f"적용 후 예상 총 (USD): {snap.projected_total_usd:.2f}\n\n"
        "응답 schema (필드 정확):\n"
        '{"status": "approved" | "throttled", "reason": "<한국어 1~2문장>"}\n'
        "approved: projected_total ≤ budget_limit\n"
        "throttled: projected_total > budget_limit (overage 명시)"
    )


def assess_budget(
    proposal: Any,
    llm_call: Optional[Callable[[str], str]] = None,
    events_path: Optional[Path] = None,
) -> "BudgetBrakeResult":  # noqa: F821 — 순환 import 회피
    """안건 → BudgetBrakeResult.

    Args:
        proposal: ``RefactoringProposal`` duck-typed (``.title`` + ``.estimated_cost``).
        llm_call: 옵션. None 이면 결정론 brake 만 사용.
        events_path: 누적 비용 산출용 events.jsonl 경로 (옵션).

    Returns:
        BudgetBrakeResult (status / estimated_cost_usd / budget_limit_usd /
        cumulative_cost_usd / note / checked_at).

    검증 순서:
        1. snapshot 계산 (estimated + limit + cumulative)
        2. 결정론 brake: projected > limit → throttled (즉시 종료)
        3. llm_call 제공 시 LLM 검토 (보수적 — projected ≤ limit 인 경우만 호출)
        4. 결정론 fallback → approved
    """
    from src.agents.coordination.boardroom_facilitator import BudgetBrakeResult

    snap = BudgetSnapshot(
        estimated_cost_usd=_estimated_cost_for_proposal(proposal),
        budget_limit_usd=_budget_limit_usd(),
        cumulative_cost_usd=_cumulative_cost_usd(events_path),
    )

    # 1. 결정론 brake — projected > limit 면 즉시 throttled
    if snap.projected_total_usd > snap.budget_limit_usd:
        return BudgetBrakeResult(
            status="throttled",
            estimated_cost_usd=snap.estimated_cost_usd,
            budget_limit_usd=snap.budget_limit_usd,
            cumulative_cost_usd=snap.cumulative_cost_usd,
            note=(
                f"예산 한도 초과 — 예상 {snap.estimated_cost_usd:.2f} + 누적 "
                f"{snap.cumulative_cost_usd:.2f} = {snap.projected_total_usd:.2f} USD "
                f"> 한도 {snap.budget_limit_usd:.2f} USD (overage "
                f"{snap.overage_usd:.2f} USD)"
            ),
            checked_at=_now_ts(),
        )

    # 2. LLM 검토 (옵션) — projected ≤ limit 인 경우만 nuanced 판단
    if llm_call is not None:
        prompt = _build_llm_prompt(snap, proposal)
        try:
            response = llm_call(prompt)
            parsed = json.loads(response.strip())
            status = str(parsed.get("status", "approved")).lower()
            reason = str(parsed.get("reason", ""))
            if status not in {"approved", "throttled"}:
                status = "approved"
            return BudgetBrakeResult(
                status=status,
                estimated_cost_usd=snap.estimated_cost_usd,
                budget_limit_usd=snap.budget_limit_usd,
                cumulative_cost_usd=snap.cumulative_cost_usd,
                note=reason or f"LLM 판단 — status={status}",
                checked_at=_now_ts(),
            )
        except Exception as exc:  # noqa: BLE001
            # LLM 결함 — 결정론 통과 (projected ≤ limit) 이므로 approved
            return BudgetBrakeResult(
                status="approved",
                estimated_cost_usd=snap.estimated_cost_usd,
                budget_limit_usd=snap.budget_limit_usd,
                cumulative_cost_usd=snap.cumulative_cost_usd,
                note=(
                    f"LLM 호출 실패 ({exc.__class__.__name__}) — 결정론 brake "
                    f"통과 (잔여 예산 {snap.remaining_usd:.2f} USD) 로 approved."
                ),
                checked_at=_now_ts(),
            )

    # 3. 결정론 fallback — projected ≤ limit → approved
    return BudgetBrakeResult(
        status="approved",
        estimated_cost_usd=snap.estimated_cost_usd,
        budget_limit_usd=snap.budget_limit_usd,
        cumulative_cost_usd=snap.cumulative_cost_usd,
        note=(
            f"잔여 예산 {snap.remaining_usd:.2f} USD ≥ 예상 "
            f"{snap.estimated_cost_usd:.2f} USD — 한도 내 진행 가능"
        ),
        checked_at=_now_ts(),
    )
