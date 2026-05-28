# -*- coding: utf-8 -*-
"""Boardroom Tikitaka E2E (v13 Phase 5.4, PR #224).

PR #218 패턴 준수 — 실 TelemetryEmitter + 실 facilitator + 3라운드 핑퐁 +
decision.yaml v2 rounds[] 검증.

핵심 시나리오:
    1. enable_tikitaka=True 일 때 3 라운드 sequence 진행 + dissent 감지로
       라운드 추가 진입
    2. decision.yaml schema_version = "v2" + rounds[] + consensus 직렬화
    3. Telemetry 의 cross_agent_consultant 이벤트 dept="planning" emit
    4. enable_tikitaka=False (default) 시 회귀 0 — rounds=[] / consensus=None
    5. budget throttled 시 라운드 조기 종료
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _proposal(title: str = "GUI sandbox 강화", estimated_cost: str = "low"):
    return SimpleNamespace(
        title=title,
        estimated_cost=estimated_cost,
        root_cause_analysis="silent fail 5회 누적 감지",
        proposed_changes=["sandbox SKIP marker 추가", "max_iterations 1→3"],
    )


# =============================================================================
# 1. ⭐ enable_tikitaka=True — 3 라운드 sequence + decision.yaml v2
# =============================================================================
class TestTikitakaThreeRoundsE2E:
    """⭐ Dissent 가 라운드 1+2 에 발생 → 3 라운드 완주."""

    def test_three_rounds_produce_consensus_and_yaml_v2(
        self, tmp_path: Path
    ) -> None:
        from src.agents.coordination import convene_full_boardroom_cycle

        round_counter = {"n": 0}

        def fake_llm(prompt: str) -> str:
            round_counter["n"] += 1
            # round 1 발언 — dissent 트리거
            if round_counter["n"] <= 4:
                if "발제자" in prompt:
                    return json.dumps({"content": "안건 발제 — sandbox 강화 필요"})
                if "검토자" in prompt:
                    if "AutoFixCoordinator" in prompt:
                        return json.dumps(
                            {"content": "근본 원인 아님 — 요구사항 불명확이 원인"}
                        )
                    return json.dumps({"content": "기술적 타당성 검토 완료"})
            # round 2 발언 — 여전히 dissent
            if "반박자" in prompt:
                return json.dumps(
                    {"content": "재검토 — 근본 원인 정의 부족"}
                )
            # round 3 mediator
            if "중재자" in prompt:
                return json.dumps(
                    {"content": "sandbox 강화 + 요구사항 명세 보강 (타협안)"}
                )
            # alignment / budget assess_alignment 의 LLM prompt
            if "approved" in prompt and "rejected" in prompt:
                return json.dumps({"status": "approved", "reason": "mission 부합"})
            if "approved" in prompt and "throttled" in prompt:
                return json.dumps({"status": "approved", "reason": "한도 내"})
            return json.dumps({"content": "응답"})

        session, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=_proposal(),
            proposal_path="/x.md",
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            llm_call=fake_llm,
            enable_tikitaka=True,
        )

        # 라운드 1 이상 진행 (dissent 감지로 round 2+3 추가 가능)
        assert len(session.rounds) >= 1
        assert session.rounds[0].round_num == 1

        # decision.yaml v2 schema
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "v2"
        assert "rounds" in data
        assert isinstance(data["rounds"], list)
        assert len(data["rounds"]) == len(session.rounds)
        assert "consensus" in data

        # 라운드별 statements 직렬화
        round_1_data = data["rounds"][0]
        assert round_1_data["round_num"] == 1
        assert isinstance(round_1_data["statements"], list)
        assert all(
            "agent" in s and "role" in s and "content" in s
            for s in round_1_data["statements"]
        )

    def test_dissent_keyword_advances_to_round_2(self, tmp_path: Path) -> None:
        def fake_llm(prompt: str) -> str:
            if "발제자" in prompt:
                return json.dumps({"content": "발제"})
            if "검토자" in prompt and "round" not in prompt.lower():
                # 첫 reviewer 가 반박
                return json.dumps({"content": "이 안건에 반박합니다"})
            if "반박자" in prompt:
                return json.dumps({"content": "재반박"})
            if "중재자" in prompt:
                return json.dumps({"content": "타협안"})
            return json.dumps({"content": "ok"})

        from src.agents.coordination import convene_full_boardroom_cycle

        session, _md, _yaml = convene_full_boardroom_cycle(
            proposal=_proposal(),
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            llm_call=fake_llm,
            enable_tikitaka=True,
        )
        assert len(session.rounds) >= 2, (
            "Round 1 dissent 감지 → Round 2 진입 필수"
        )

    def test_full_consensus_short_circuits_at_round_1(
        self, tmp_path: Path
    ) -> None:
        """Round 1 dissent 0 → Round 2 진입 X (짧은 회의)."""

        def fake_llm(prompt: str) -> str:
            # 모든 발언자 동의
            return json.dumps({"content": "전적으로 동의합니다"})

        from src.agents.coordination import convene_full_boardroom_cycle

        session, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=_proposal(),
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            llm_call=fake_llm,
            enable_tikitaka=True,
        )
        assert len(session.rounds) == 1
        assert session.rounds[0].dissent_detected is False

        # consensus 보존 (mediator 미거침 시도 마지막 발언 인용)
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["consensus"] is not None


# =============================================================================
# 2. ⭐ enable_tikitaka=False — 회귀 0 (Phase 4 동작 보존)
# =============================================================================
class TestRegressionDefaultOff:
    """⭐ default OFF 시 rounds=[] / consensus=None — Phase 4 동작 그대로."""

    def test_default_off_no_rounds_no_consensus(self, tmp_path: Path) -> None:
        from src.agents.coordination import convene_full_boardroom_cycle

        session, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=_proposal(),
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            # enable_tikitaka 미지정 → default False
        )
        assert session.rounds == []
        assert session.consensus is None

        # YAML v2 schema 지만 rounds 빈 list
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "v2"
        assert data["rounds"] == []
        assert data["consensus"] is None
        # Phase 4 의 alignment / budget / final_decision 그대로 동작
        assert data["alignment"]["status"] in {"approved", "rejected"}
        assert data["final_decision"]["outcome"] in {"approved", "blocked"}


# =============================================================================
# 3. ⭐ Telemetry — cross_agent_consultant 이벤트 (PR #218 패턴)
# =============================================================================
class TestTikitakaTelemetryEmission:
    def test_tikitaka_emits_cross_agent_consultant_events(
        self, tmp_path: Path
    ) -> None:
        events_path = tmp_path / "events.jsonl"
        prev_env = os.environ.get("NEXUS_TELEMETRY_PATH")
        os.environ["NEXUS_TELEMETRY_PATH"] = str(events_path)
        try:
            from src.monitoring import TelemetryEmitter

            TelemetryEmitter.reset_for_tests()

            from src.agents.coordination import convene_full_boardroom_cycle

            def fake_llm(prompt: str) -> str:
                return json.dumps({"content": "동의"})

            convene_full_boardroom_cycle(
                proposal=_proposal(),
                output_dir=tmp_path / "_boardroom_sessions",
                decision_output_dir=tmp_path / "board_decisions",
                llm_call=fake_llm,
                enable_tikitaka=True,
            )

            assert events_path.exists()
            lines = events_path.read_text(encoding="utf-8").strip().splitlines()
            parsed = [json.loads(l) for l in lines]

            # ⭐ cross_agent_consultant working + done emit
            cac_events = [
                e for e in parsed if e.get("agent") == "cross_agent_consultant"
            ]
            assert len(cac_events) >= 2, (
                f"cross_agent_consultant 이벤트 부족 — 실제 {len(cac_events)}"
            )
            # dept="planning" (본부 10 Coordination)
            for e in cac_events:
                assert e.get("department") == "planning"
        finally:
            if prev_env is None:
                os.environ.pop("NEXUS_TELEMETRY_PATH", None)
            else:
                os.environ["NEXUS_TELEMETRY_PATH"] = prev_env
            from src.monitoring import TelemetryEmitter as _TE

            _TE.reset_for_tests()


# =============================================================================
# 4. ⭐ Budget throttle 시 라운드 조기 종료 (안전 장치)
# =============================================================================
class TestTikitakaBudgetSafety:
    def test_throttled_budget_terminates_rounds_early(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """한도 0.1 + high → 첫 라운드 진입 전 throttled → consensus 미도출."""
        monkeypatch.setenv("NEXUS_BOARDROOM_BUDGET_LIMIT_USD", "0.1")

        from src.agents.coordination import convene_full_boardroom_cycle

        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "ok"})

        session, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=_proposal(title="대규모", estimated_cost="high"),
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            llm_call=fake_llm,
            enable_tikitaka=True,
        )
        # 라운드 0건 (시작 전 throttled)
        assert len(session.rounds) == 0
        # consensus 에 throttled 메시지 보존
        assert session.consensus is not None
        assert "throttled" in session.consensus.lower()
        # final_decision = blocked (budget throttled)
        assert session.final_decision.outcome == "blocked"


# =============================================================================
# 5. ⭐ Schema v2 — 모든 5 최상위 키 존재
# =============================================================================
class TestDecisionYamlSchemaV2:
    def test_all_top_level_keys_in_v2(self, tmp_path: Path) -> None:
        from src.agents.coordination import convene_full_boardroom_cycle

        def fake_llm(prompt: str) -> str:
            return json.dumps({"content": "동의"})

        _, _md, yaml_path = convene_full_boardroom_cycle(
            proposal=_proposal(),
            output_dir=tmp_path / "_boardroom_sessions",
            decision_output_dir=tmp_path / "board_decisions",
            llm_call=fake_llm,
            enable_tikitaka=True,
        )
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        # v1 의 4 키 + v2 의 2 키 (rounds + consensus)
        assert set(data.keys()) >= {
            "schema_version",
            "session",
            "alignment",
            "budget",
            "final_decision",
            "rounds",
            "consensus",
        }
        assert data["schema_version"] == "v2"
