# -*- coding: utf-8 -*-
"""본부 0 거버넌스 에이전트 단위 test (v13 Phase 4, PR #222).

검증 범위:
    1. Goal Alignment Agent (assess_alignment)
       - 결정론 forbidden 키워드 → rejected
       - LLM 정상 응답 → JSON parse → approved/rejected 산출
       - LLM 결함 → 보수적 approved
       - 기본 (LLM 미주입 + forbidden 미매칭) → approved
    2. Token Budget Optimizer (assess_budget)
       - estimated_cost tier (low/medium/high) → USD 매핑
       - projected > limit → throttled
       - projected ≤ limit → approved
       - 누적 비용 env override + events.jsonl 합산
       - LLM 호출 (정상 + 결함) 분기
    3. CrewAI Agent factory — create_goal_alignment_agent / create_token_budget_optimizer_agent
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level import (
    DEFAULT_BUDGET_LIMIT_USD,
    GOAL_ALIGNMENT_AGENT_NAME,
    TOKEN_BUDGET_OPTIMIZER_NAME,
    BudgetSnapshot,
    assess_alignment,
    assess_budget,
)
from src.agents.c_level.goal_alignment_agent import (
    _FORBIDDEN_KEYWORDS,
    DEFAULT_REFERENCES,
)
from src.agents.c_level.token_budget_optimizer import (
    _COST_USD_BY_TIER,
)


def _proposal(
    title: str = "안건 X",
    estimated_cost: str = "medium",
    proposed_changes: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        estimated_cost=estimated_cost,
        proposed_changes=proposed_changes or [],
    )


# =============================================================================
# 1. Goal Alignment Agent
# =============================================================================
class TestGoalAlignmentForbiddenKeywords:
    """⭐ 결정론 forbidden 키워드 — 즉시 rejected."""

    def test_forbidden_keyword_in_title_yields_rejected(self) -> None:
        for kw in ["force push", "rm -rf", "QA 우회", "drop database"]:
            result = assess_alignment(_proposal(title=f"긴급 — {kw}"))
            assert result.status == "rejected", (
                f"forbidden '{kw}' 미감지 — 결과: {result.status}"
            )
            assert kw.lower() in result.note.lower()

    def test_forbidden_keyword_in_proposed_changes_yields_rejected(self) -> None:
        result = assess_alignment(
            _proposal(
                title="정상 안건",
                proposed_changes=["skip review 추가"],
            )
        )
        assert result.status == "rejected"

    def test_korean_forbidden_keywords_detected(self) -> None:
        result = assess_alignment(_proposal(title="리뷰 우회 강제 머지"))
        assert result.status == "rejected"

    def test_case_insensitive_forbidden_match(self) -> None:
        result = assess_alignment(_proposal(title="FORCE PUSH to main"))
        assert result.status == "rejected"


class TestGoalAlignmentDefaultApprove:
    """⭐ forbidden 미매칭 + LLM 미주입 → approved (강한 부정 신호 부재)."""

    def test_clean_proposal_yields_approved_default(self) -> None:
        result = assess_alignment(_proposal(title="GUI sandbox 강화"))
        assert result.status == "approved"
        assert list(result.references) == list(DEFAULT_REFERENCES)
        assert result.checked_at  # ISO8601 채워짐


class TestGoalAlignmentLLMBranch:
    """⭐ LLM 주입 시 JSON parse → approved/rejected 산출."""

    def test_llm_approved_response(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"status": "approved", "reason": "mission 부합"})

        result = assess_alignment(_proposal(title="안건 X"), llm_call=fake_llm)
        assert result.status == "approved"
        assert result.note == "mission 부합"

    def test_llm_rejected_response(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"status": "rejected", "reason": "보안 우려"})

        result = assess_alignment(_proposal(title="안건 X"), llm_call=fake_llm)
        assert result.status == "rejected"
        assert "보안" in result.note

    def test_llm_invalid_json_falls_back_to_approved(self) -> None:
        def broken_llm(prompt: str) -> str:
            return "not json {{"

        result = assess_alignment(_proposal(title="안건 X"), llm_call=broken_llm)
        assert result.status == "approved"
        assert "LLM 호출 실패" in result.note

    def test_llm_unknown_status_normalizes_to_approved(self) -> None:
        def odd_llm(prompt: str) -> str:
            return json.dumps({"status": "maybe", "reason": "모호"})

        result = assess_alignment(_proposal(title="안건 X"), llm_call=odd_llm)
        assert result.status == "approved"

    def test_forbidden_takes_precedence_over_llm(self) -> None:
        """forbidden 키워드는 LLM 호출 전 즉시 rejected."""

        def llm_says_approved(prompt: str) -> str:
            return json.dumps({"status": "approved", "reason": "OK"})

        result = assess_alignment(
            _proposal(title="rm -rf 강제 정리"), llm_call=llm_says_approved
        )
        assert result.status == "rejected"


# =============================================================================
# 2. Token Budget Optimizer
# =============================================================================
class TestBudgetCostTiers:
    """⭐ estimated_cost tier (low/medium/high) → USD 매핑."""

    def test_tier_mapping(self) -> None:
        assert _COST_USD_BY_TIER["low"] == 0.50
        assert _COST_USD_BY_TIER["medium"] == 2.00
        assert _COST_USD_BY_TIER["high"] == 10.00

    def test_unknown_tier_falls_back_to_medium(self) -> None:
        """estimated_cost='unknown' → medium 대체."""
        result = assess_budget(_proposal(estimated_cost="unknown"))
        assert result.estimated_cost_usd == 2.00


class TestBudgetBrakeDeterministic:
    """⭐ 결정론 brake — projected > limit → throttled."""

    def test_within_default_limit_yields_approved(self) -> None:
        result = assess_budget(_proposal(estimated_cost="high"))
        assert result.status == "approved"
        assert result.estimated_cost_usd == 10.0
        assert result.budget_limit_usd == DEFAULT_BUDGET_LIMIT_USD  # 15.0

    def test_high_cost_over_low_limit_yields_throttled(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "5.0")
        result = assess_budget(_proposal(estimated_cost="high"))
        assert result.status == "throttled"
        assert result.budget_limit_usd == 5.0
        assert "초과" in result.note

    def test_cumulative_env_override_pushes_to_throttled(
        self, monkeypatch
    ) -> None:
        """⭐ 누적 비용 env 주입 — low cost (0.5) 인데 누적이 14.7 → throttled."""
        monkeypatch.setenv("NEXUS_BOARDROOM_CUMULATIVE_COST_USD", "14.7")
        result = assess_budget(_proposal(estimated_cost="low"))
        assert result.status == "throttled"
        assert result.cumulative_cost_usd == 14.7

    def test_budget_limit_env_invalid_falls_back_to_default(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "not-a-number")
        result = assess_budget(_proposal(estimated_cost="low"))
        assert result.budget_limit_usd == DEFAULT_BUDGET_LIMIT_USD


class TestBudgetCumulativeFromEvents:
    """⭐ events.jsonl token_usage 이벤트 합산."""

    def test_cumulative_from_events_jsonl(self, tmp_path: Path) -> None:
        events = tmp_path / "events.jsonl"
        # input 1M tokens × $3 + output 100k × $15 = $3 + $1.5 = $4.5
        events.write_text(
            json.dumps(
                {
                    "type": "token_usage",
                    "input_tokens": 1_000_000,
                    "output_tokens": 100_000,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = assess_budget(
            _proposal(estimated_cost="low"), events_path=events
        )
        assert abs(result.cumulative_cost_usd - 4.5) < 0.001

    def test_events_jsonl_missing_yields_zero(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.jsonl"
        result = assess_budget(
            _proposal(estimated_cost="low"), events_path=missing
        )
        assert result.cumulative_cost_usd == 0.0


class TestBudgetLLMBranch:
    """⭐ LLM 주입 — projected ≤ limit 인 경우만 LLM 호출."""

    def test_llm_approved_response_within_limit(self) -> None:
        def fake_llm(prompt: str) -> str:
            return json.dumps({"status": "approved", "reason": "잔여 충분"})

        result = assess_budget(_proposal(estimated_cost="low"), llm_call=fake_llm)
        assert result.status == "approved"
        assert "잔여" in result.note

    def test_llm_can_throttle_even_within_limit(self) -> None:
        def cautious_llm(prompt: str) -> str:
            return json.dumps({"status": "throttled", "reason": "보수적 brake"})

        result = assess_budget(
            _proposal(estimated_cost="low"), llm_call=cautious_llm
        )
        assert result.status == "throttled"

    def test_llm_failure_falls_back_to_deterministic_approved(self) -> None:
        def broken_llm(prompt: str) -> str:
            raise RuntimeError("LLM 결함")

        result = assess_budget(
            _proposal(estimated_cost="low"), llm_call=broken_llm
        )
        # projected ≤ limit + LLM 결함 → 보수적 approved
        assert result.status == "approved"
        assert "LLM 호출 실패" in result.note

    def test_deterministic_throttle_skips_llm(self, monkeypatch) -> None:
        """⭐ projected > limit 면 LLM 호출 전 즉시 throttled."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "0.1")

        llm_called = {"yes": False}

        def llm(prompt: str) -> str:
            llm_called["yes"] = True
            return json.dumps({"status": "approved", "reason": "OK"})

        result = assess_budget(
            _proposal(estimated_cost="high"), llm_call=llm
        )
        assert result.status == "throttled"
        assert llm_called["yes"] is False, (
            "결정론 brake hit 인데 LLM 호출됨 — 비용 낭비"
        )


# =============================================================================
# 3. BudgetSnapshot 보조 구조
# =============================================================================
class TestBudgetSnapshot:
    def test_projected_total(self) -> None:
        snap = BudgetSnapshot(
            estimated_cost_usd=2.0,
            budget_limit_usd=15.0,
            cumulative_cost_usd=3.0,
        )
        assert snap.projected_total_usd == 5.0
        assert snap.remaining_usd == 12.0
        assert snap.overage_usd == -10.0  # under limit


# =============================================================================
# 4. Agent 메타데이터 상수 + factory 시그니처 (CrewAI Agent 인스턴스화는
#    pydantic 유효성 검사로 인해 실 LLM 의존 — smoke test 는 별도 파일에서)
# =============================================================================
class TestAgentMetadata:
    def test_goal_alignment_agent_constants(self) -> None:
        from src.agents.c_level import (
            GOAL_ALIGNMENT_AGENT_BACKSTORY,
            GOAL_ALIGNMENT_AGENT_GOAL,
            GOAL_ALIGNMENT_AGENT_ROLE,
        )

        assert GOAL_ALIGNMENT_AGENT_NAME == "GoalAlignmentAgent"
        assert "Goal Alignment" in GOAL_ALIGNMENT_AGENT_ROLE
        assert "v13" in GOAL_ALIGNMENT_AGENT_ROLE
        assert "approved" in GOAL_ALIGNMENT_AGENT_GOAL
        assert "보안 거버넌스" in GOAL_ALIGNMENT_AGENT_BACKSTORY

    def test_token_budget_optimizer_constants(self) -> None:
        from src.agents.c_level import (
            TOKEN_BUDGET_OPTIMIZER_BACKSTORY,
            TOKEN_BUDGET_OPTIMIZER_GOAL,
            TOKEN_BUDGET_OPTIMIZER_ROLE,
        )

        assert TOKEN_BUDGET_OPTIMIZER_NAME == "TokenBudgetOptimizer"
        assert "Token Budget Optimizer" in TOKEN_BUDGET_OPTIMIZER_ROLE
        assert "approved" in TOKEN_BUDGET_OPTIMIZER_GOAL
        assert "throttled" in TOKEN_BUDGET_OPTIMIZER_GOAL
        assert "한도" in TOKEN_BUDGET_OPTIMIZER_BACKSTORY

    def test_factory_signatures_present(self) -> None:
        """factory 함수 import + 시그니처 파라미터 정상."""
        import inspect

        from src.agents.c_level import (
            create_goal_alignment_agent,
            create_token_budget_optimizer_agent,
        )

        ga_sig = inspect.signature(create_goal_alignment_agent)
        assert "llm" in ga_sig.parameters
        assert "verbose" in ga_sig.parameters
        assert "max_iter" in ga_sig.parameters

        tbo_sig = inspect.signature(create_token_budget_optimizer_agent)
        assert "llm" in tbo_sig.parameters
        assert "verbose" in tbo_sig.parameters
