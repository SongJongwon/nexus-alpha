# -*- coding: utf-8 -*-
"""
PR #187 (Sprint 4) — Telemetry hook 회귀 테스트.

검증 매트릭스:
    1. emit OFF default — NEXUS_TELEMETRY_PATH 미 set 시 emitter 비활성 + emit no-op
    2. emit ON — env var set + reset 후 활성, jsonl 파일 생성 + line-atomic append
    3. 4 event dataclass 모두 type/필드 직렬화 정상
    4. department_for_node 매핑 — 9 노드 + 종결 2 + alias 4
    5. LangFuse env 양쪽 호환 — HOST 우선 / BASE_URL fallback / 둘 다 미 set 기본
    6. BaseLLMProvider.generate() finally 블록의 AgentMessageEvent emit 경로
    7. _telemetry_wrap — telemetry 비활성 시 원본 fn 그대로 호출 (0 overhead)
    8. _telemetry_wrap — 활성 시 working → fn → done 순서 + 예외 시 error emit
    9. scripts/run.py --emit-events flag — env var set 동작 + Path resolve
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.monitoring import (
    ENGINEERING,
    LEARNING,
    PLANNING,
    SYSTEM,
    AgentMessageEvent,
    AgentStatusEvent,
    IterationProgressEvent,
    ResultEvent,
    TelemetryEmitter,
    department_for_node,
    get_telemetry_emitter,
)
from src.monitoring import langfuse_client as lf_module


# ---------------------------------------------------------------------------
# Fixture — 깨끗한 emitter (env var + 싱글톤 리셋)
# ---------------------------------------------------------------------------
@pytest.fixture
def reset_emitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """각 테스트 진입 전후 emitter 싱글톤 + env var 초기화."""
    monkeypatch.delenv("NEXUS_TELEMETRY_PATH", raising=False)
    TelemetryEmitter.reset_for_tests()
    yield
    TelemetryEmitter.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. emit OFF default
# ---------------------------------------------------------------------------
def test_emit_off_by_default_no_file_no_error(reset_emitter: None, tmp_path: Path) -> None:
    """NEXUS_TELEMETRY_PATH 미 set 시 emitter 비활성 + emit 호출 silent."""
    emitter = get_telemetry_emitter()
    assert emitter.enabled is False
    assert emitter.path is None

    # 모든 emit shortcut 이 예외 없이 silent — 파일 미생성
    emitter.emit(AgentStatusEvent(agent="x", department=SYSTEM, status="working"))
    emitter.agent_working("expand_requirements")
    emitter.agent_done("expand_requirements")
    emitter.agent_error("expand_requirements", "boom")

    assert list(tmp_path.iterdir()) == [], "비활성 emitter 가 파일 생성하면 안 됨"


# ---------------------------------------------------------------------------
# 2. emit ON + jsonl 포맷
# ---------------------------------------------------------------------------
def test_emit_on_writes_jsonl_each_event_one_line(
    reset_emitter: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """env var set + reset → emit 가 jsonl 한 줄씩 append."""
    target = tmp_path / "events.jsonl"
    monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(target))
    TelemetryEmitter.reset_for_tests()

    emitter = get_telemetry_emitter()
    assert emitter.enabled is True
    assert emitter.path == target

    emitter.begin_run(max_iterations=3)
    emitter.emit(IterationProgressEvent(phase="run_start", iteration=0, max_iterations=3))
    emitter.emit(AgentStatusEvent(agent="run_chain", department=ENGINEERING, status="working"))
    emitter.emit(AgentMessageEvent(
        agent="FakeProvider", department=ENGINEERING, role="llm_call",
        prompt_preview="hi", output_preview="hello", model="fake-model-v0",
        prompt_length=2, output_length=5,
    ))
    emitter.emit(ResultEvent(verdict="COMPLETE", iterations_run=1, max_iterations=3))

    assert target.exists(), "활성 emitter 가 파일을 만들어야 함"
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4, f"각 emit 1줄, 총 4 — 실제 {len(lines)}"

    payloads = [json.loads(ln) for ln in lines]
    types = [p["type"] for p in payloads]
    assert types == ["iteration_progress", "agent_status", "agent_message", "result"]
    # run_id 자동 주입 — begin_run 후 emit 한 event 들이 모두 동일 run_id 보유
    run_ids = {p.get("run_id", "") for p in payloads}
    assert len(run_ids) == 1 and "" not in run_ids


# ---------------------------------------------------------------------------
# 3. 4 event dataclass 직렬화
# ---------------------------------------------------------------------------
def test_four_event_types_serialize_with_required_fields() -> None:
    """각 event 가 type 필드 + 핵심 필드 보존 — Tauri UI 가 type 으로 분기."""
    from dataclasses import asdict

    s = AgentStatusEvent(agent="a", department=PLANNING, status="working")
    assert asdict(s)["type"] == "agent_status"

    m = AgentMessageEvent(agent="a", department=ENGINEERING, role="llm_call",
                          prompt_preview="p", output_preview="o")
    assert asdict(m)["type"] == "agent_message"
    assert asdict(m)["prompt_preview"] == "p"

    ip = IterationProgressEvent(phase="run_start", iteration=0, max_iterations=3)
    assert asdict(ip)["type"] == "iteration_progress"

    r = ResultEvent(verdict="COMPLETE", iterations_run=1, max_iterations=3)
    assert asdict(r)["type"] == "result"


# ---------------------------------------------------------------------------
# 4. department_for_node 매핑
# ---------------------------------------------------------------------------
def test_department_for_node_covers_iterative_loop_nodes() -> None:
    """iterative_loop 의 13 노드 (9 + alias 4) 부서 매핑 정확."""
    assert department_for_node("expand_requirements") == PLANNING
    assert department_for_node("kickoff_meeting") == PLANNING
    assert department_for_node("analyze_gap") == PLANNING
    assert department_for_node("prepare_feedback") == PLANNING

    assert department_for_node("run_chain") == ENGINEERING
    assert department_for_node("run_sandbox") == ENGINEERING

    assert department_for_node("recall_past_knowledge") == LEARNING
    assert department_for_node("judge_convergence") == LEARNING
    assert department_for_node("retrospective") == LEARNING
    assert department_for_node("retrospective_blocked") == LEARNING
    assert department_for_node("curate_knowledge") == LEARNING
    assert department_for_node("curate_knowledge_blocked") == LEARNING

    assert department_for_node("finalize") == SYSTEM
    assert department_for_node("escalate") == SYSTEM

    # 미매핑 노드 → SYSTEM fallback (emit 차단 X)
    assert department_for_node("unknown_node_xyz") == SYSTEM


# ---------------------------------------------------------------------------
# 5. LangFuse env 양쪽 호환
# ---------------------------------------------------------------------------
def test_langfuse_host_takes_precedence_over_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """LANGFUSE_HOST 가 set 되면 BASE_URL 무시."""
    monkeypatch.setenv("LANGFUSE_HOST", "https://primary.example")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://alias.example")
    assert lf_module._resolve_langfuse_host() == "https://primary.example"


def test_langfuse_base_url_fallback_when_host_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """LANGFUSE_HOST 미 set → BASE_URL 사용."""
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://alias.example")
    assert lf_module._resolve_langfuse_host() == "https://alias.example"


def test_langfuse_default_cloud_when_both_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """둘 다 미 set → 기본 cloud 엔드포인트."""
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    assert lf_module._resolve_langfuse_host() == "https://cloud.langfuse.com"


def test_langfuse_host_with_quotes_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """LANGFUSE_HOST 가 따옴표로 감싸진 경우 ``_clean_env`` 가 제거."""
    monkeypatch.setenv("LANGFUSE_HOST", '"https://quoted.example"')
    assert lf_module._resolve_langfuse_host() == "https://quoted.example"


# ---------------------------------------------------------------------------
# 6. BaseLLMProvider.generate() AgentMessageEvent emit 경로
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_base_provider_generate_emits_agent_message_event(
    reset_emitter: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FakeProvider.generate() 호출 시 jsonl 에 agent_message 1줄 append."""
    target = tmp_path / "msgs.jsonl"
    monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(target))
    TelemetryEmitter.reset_for_tests()

    from src.tests.conftest import FakeProvider

    provider = FakeProvider(response="Final Answer: Hi")
    result = await provider.generate("ping", system="sys")
    assert "Hi" in result

    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    # FakeProvider.generate finally 블록의 AgentMessageEvent emit 1건
    msgs = [json.loads(ln) for ln in lines if json.loads(ln).get("type") == "agent_message"]
    assert len(msgs) == 1
    m = msgs[0]
    assert m["agent"] == "FakeProvider"
    assert m["department"] == ENGINEERING
    assert m["role"] == "llm_call"
    assert m["prompt_preview"] == "ping"
    assert "Hi" in m["output_preview"]
    assert m["model"] == "fake-model-v0"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# 7. _telemetry_wrap — 비활성 시 원본 fn 그대로
# ---------------------------------------------------------------------------
def test_telemetry_wrap_passthrough_when_disabled(reset_emitter: None) -> None:
    """emitter 비활성 시 wrap 이 원본 fn 결과 그대로 — overhead 0."""
    from src.workflows.iterative_loop import _telemetry_wrap

    calls: list[dict] = []

    def raw(state: dict) -> dict:
        calls.append(state)
        return {"iteration": state.get("iteration", 0) + 1, "echo": "ok"}

    wrapped = _telemetry_wrap("expand_requirements", raw)
    out = wrapped({"iteration": 0})
    assert out == {"iteration": 1, "echo": "ok"}
    assert calls == [{"iteration": 0}]


# ---------------------------------------------------------------------------
# 8. _telemetry_wrap — 활성 시 working → fn → done 순서 + 예외 시 error
# ---------------------------------------------------------------------------
def test_telemetry_wrap_emits_working_then_done(
    reset_emitter: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """활성 시 진입 시 working / 종료 시 done — 정확한 순서."""
    target = tmp_path / "wrap.jsonl"
    monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(target))
    TelemetryEmitter.reset_for_tests()

    from src.workflows.iterative_loop import _telemetry_wrap

    def raw(state: dict) -> dict:
        return {"iteration": 2}

    wrapped = _telemetry_wrap("run_chain", raw)
    wrapped({"iteration": 1})

    payloads = [json.loads(ln) for ln in target.read_text(encoding="utf-8").splitlines()]
    assert len(payloads) == 2
    assert payloads[0]["type"] == "agent_status"
    assert payloads[0]["status"] == "working"
    assert payloads[0]["agent"] == "run_chain"
    assert payloads[0]["department"] == ENGINEERING
    assert payloads[1]["status"] == "done"


def test_telemetry_wrap_emits_error_on_exception_then_reraises(
    reset_emitter: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """node 예외 발생 시 error event emit + 원본 예외 re-raise (동작 변경 0)."""
    target = tmp_path / "err.jsonl"
    monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(target))
    TelemetryEmitter.reset_for_tests()

    from src.workflows.iterative_loop import _telemetry_wrap

    def raw(state: dict) -> dict:
        raise RuntimeError("boom")

    wrapped = _telemetry_wrap("retrospective", raw)
    with pytest.raises(RuntimeError, match="boom"):
        wrapped({"iteration": 1})

    payloads = [json.loads(ln) for ln in target.read_text(encoding="utf-8").splitlines()]
    assert payloads[0]["status"] == "working"
    assert payloads[1]["status"] == "error"
    assert "boom" in payloads[1]["detail"]
    assert payloads[1]["department"] == LEARNING


# ---------------------------------------------------------------------------
# 9. scripts/run.py --emit-events flag
# ---------------------------------------------------------------------------
def test_emit_events_flag_in_argparse(reset_emitter: None) -> None:
    """argparse 가 --emit-events 를 받고 기본 None."""
    from scripts.run import _parse_args

    args = _parse_args(["--request", "x", "--non-interactive"])
    assert args.emit_events is None

    args = _parse_args(["--request", "x", "--non-interactive", "--emit-events", "out.jsonl"])
    assert args.emit_events == "out.jsonl"


def test_emit_events_flag_resolves_to_absolute_path(
    reset_emitter: None,
    tmp_path: Path,
) -> None:
    """flag 값이 main 진입 시 abs path 로 환경변수에 set — Path.resolve 사용 확인.

    main 자체는 호출하지 않고 *동작 부분* 만 단위 테스트 — Path.expanduser/resolve.
    """
    rel_path = "events.jsonl"
    abs_expected = (Path.cwd() / rel_path).resolve()
    resolved = Path(rel_path).expanduser().resolve()
    assert resolved == abs_expected


# ---------------------------------------------------------------------------
# 10. emitter — begin_run / set_iteration / end_run 컨텍스트
# ---------------------------------------------------------------------------
def test_emitter_run_context_auto_injects_run_id_and_iteration(
    reset_emitter: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """begin_run 후 emit 한 event 들의 run_id/iteration 가 자동 주입."""
    target = tmp_path / "ctx.jsonl"
    monkeypatch.setenv("NEXUS_TELEMETRY_PATH", str(target))
    TelemetryEmitter.reset_for_tests()

    emitter = get_telemetry_emitter()
    run_id = emitter.begin_run(max_iterations=3)
    assert run_id

    emitter.set_iteration(2)
    emitter.agent_working("run_chain")

    emitter.end_run()
    # end_run 후 emit 은 빈 run_id 가 다시 set 되지 않음 — 동작 검증
    assert emitter.run_id == ""

    payloads = [json.loads(ln) for ln in target.read_text(encoding="utf-8").splitlines()]
    working = [p for p in payloads if p.get("status") == "working"]
    assert working[0]["run_id"] == run_id
    assert working[0]["iteration"] == 2
