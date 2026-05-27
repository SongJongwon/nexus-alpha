# -*- coding: utf-8 -*-
"""System Refactoring Strategist — 본부 1 자율 개선안 발제 엔진 (v13 Phase 2).

자기 진화 루프의 *두뇌* 노드. 본부 9 RV (Runtime Verification) 가 감지한
런타임 결함 + Telemetry 이벤트 시퀀스를 분석 → *이사회 안건* (Refactoring
Proposal) 으로 변환.

호출 시점 (Phase 2):
    1. Auto-Fix Coordinator 가 ``ESCALATION_THRESHOLD`` (5회 연속 실패) 도달
       시 ``action="escalate"`` 결정
    2. 본 모듈의 ``trigger_strategist_on_escalation()`` 호출 → 최근 N 회 events
       분석 + LLM 호출 (옵션) → ``RefactoringProposal`` 작성
    3. ``outputs/_refactoring_proposals/<timestamp>_<title>.md`` 파일로 저장

Phase 4 (의결권 활성화 후): Boardroom 에 안건 제출 → C-Level + 부서 대표 토론
→ approved/rejected. Phase 2 시점에서는 *markdown 보존만* (자동 적용 X).

Telemetry: ``AgentStatusEvent(department="planning")`` emit (본부 1).
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# 산출 schema
# ---------------------------------------------------------------------------
@dataclass
class RefactoringProposal:
    """``analyze_runtime_patterns`` 의 산출 — 이사회 안건 1건.

    Attributes:
        title: 안건 제목 (예: "GUI sandbox 강화 — 5회 연속 silent fail 패턴").
        root_cause_analysis: 근본 원인 분석 (결정론 또는 LLM 산출).
        proposed_changes: 구체 수정사항 리스트 (각 항목은 한 줄 처방).
        estimated_cost: 토큰 예산 견적 ("low" / "medium" / "high").
        confidence: 0.0~1.0. 결정론 매칭 0.85+, LLM 0.6~0.8, 미매칭 0.3.
        analysis_method: ``"rule"`` (결정론) / ``"llm"`` / ``"hybrid"``.
        signal_summary: 분석 입력의 통계 요약 (event 수 / verdict 분포 등).
    """

    title: str
    root_cause_analysis: str
    proposed_changes: list[str]
    estimated_cost: str = "medium"
    confidence: float = 0.5
    analysis_method: str = "rule"
    signal_summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Telemetry — 본부 1 (planning) 식별자
# ---------------------------------------------------------------------------
def _try_emit_telemetry(agent: str, status: str, detail: str = "") -> None:
    """Telemetry emit — 실패 silent. dept="planning" (본부 1)."""
    try:
        from src.monitoring.telemetry import (
            AgentStatusEvent,
            get_telemetry_emitter,
        )

        emitter = get_telemetry_emitter()
        if not emitter.enabled:
            return
        emitter.emit(
            AgentStatusEvent(
                agent=agent,
                department="planning",
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Event 분석 — events.jsonl 또는 in-memory list 입력
# ---------------------------------------------------------------------------
def _count_silent_fails(events: list[dict[str, Any]]) -> int:
    """events 중 ``verdict=SILENT_FAIL`` 또는 detail 에 'silent fail' 포함 카운트."""
    n = 0
    for e in events:
        detail = str(e.get("detail", ""))
        if "SILENT_FAIL" in detail or "silent fail" in detail.lower():
            n += 1
    return n


def _count_verdicts(events: list[dict[str, Any]]) -> Counter:
    """exe_runtime_tester ``done`` 이벤트의 verdict 분포."""
    counter: Counter = Counter()
    for e in events:
        if e.get("agent") != "exe_runtime_tester":
            continue
        if e.get("status") != "done":
            continue
        detail = str(e.get("detail", ""))
        m = re.search(r"verdict=(\w+)", detail)
        if m:
            counter[m.group(1)] += 1
    return counter


def _count_blocked_verdicts(events: list[dict[str, Any]]) -> int:
    """result 이벤트의 verdict=BLOCKED 카운트 (run 단위)."""
    n = 0
    for e in events:
        if e.get("type") != "result":
            continue
        if str(e.get("verdict", "")).upper() == "BLOCKED":
            n += 1
    return n


# ---------------------------------------------------------------------------
# 결정론 패턴 매처 — LLM 없이 즉시 안건 발제 가능한 알려진 패턴
# ---------------------------------------------------------------------------
SILENT_FAIL_THRESHOLD: int = 5
"""5회 연속 silent fail → "GUI sandbox 강화" 안건 자율 발제 (DoD)."""


def _proposal_silent_fail_pattern(silent_count: int, total_runs: int) -> RefactoringProposal:
    """결정론 안건: silent fail 5회 이상 → GUI sandbox 강화."""
    return RefactoringProposal(
        title=f"GUI sandbox 강화 — {silent_count}회 연속 silent fail 패턴",
        root_cause_analysis=(
            f"최근 events 시퀀스에서 silent fail {silent_count}회 감지. "
            "GUI 앱이 mainloop 진입 전 즉시 exit 0 으로 종료되는 패턴 — "
            "entry 오선택 (theme.py / test_*.py) 또는 hidden_imports 누락 의심."
        ),
        proposed_changes=[
            "build_workflow._select_entry_point PRIORITY 1 검증 강화 — non-test + __main__ 블록 필수",
            "PyInstaller --collect-all 옵션을 GUI 프레임워크에 자동 적용 (tkinter/PyQt/customtkinter)",
            "sandbox.py 의 GUI marker AST scan 을 1차 의심 패키지 import 까지 확장",
        ],
        estimated_cost="medium",
        confidence=0.9,
        analysis_method="rule",
        signal_summary={
            "silent_fail_count": silent_count,
            "total_runs": total_runs,
            "pattern": "consecutive_silent_fail",
        },
    )


def _proposal_blocked_ratio(blocked: int, total: int) -> RefactoringProposal:
    """결정론 안건: BLOCKED 비율 50% 이상 → max_iterations 또는 budget 상향."""
    ratio = blocked / total if total else 0.0
    return RefactoringProposal(
        title=f"max_iterations 또는 token budget 상향 — BLOCKED 비율 {ratio:.0%}",
        root_cause_analysis=(
            f"최근 {total}회 run 중 {blocked}회 BLOCKED ({ratio:.0%}). "
            "iteration 한도 또는 토큰 예산 부족으로 수렴 전에 강제 종료되는 패턴."
        ),
        proposed_changes=[
            "max_iterations 기본값 3 → 5 (보수적 상향)",
            "C-Level Token Budget Optimizer 의 per-iteration 한도 +20% 재조정",
            "Convergence Judge 의 STAGNATION 감지 sensitivity 완화 (gap delta threshold 상향)",
        ],
        estimated_cost="low",
        confidence=0.85,
        analysis_method="rule",
        signal_summary={
            "blocked_count": blocked,
            "total_runs": total,
            "blocked_ratio": ratio,
            "pattern": "high_blocked_ratio",
        },
    )


# ---------------------------------------------------------------------------
# 공개 분석 진입점
# ---------------------------------------------------------------------------
def analyze_runtime_patterns(
    events: list[dict[str, Any]],
    recent_verdicts: Optional[list[str]] = None,
    llm_call: Optional[Callable[[str], str]] = None,
) -> RefactoringProposal:
    """events.jsonl + 최근 verdicts 시퀀스를 분석 → ``RefactoringProposal`` 산출.

    동작:
        1. 입력 통계 집계 (silent fail / verdict 분포 / BLOCKED 비율)
        2. 결정론 매처 시도 (silent fail ≥ 5 → GUI 강화 안건 / BLOCKED ≥ 50%
           → budget 상향 안건)
        3. 결정론 미매칭 + ``llm_call`` 제공 시 LLM 분석
        4. 모두 실패 시 unknown fallback

    Args:
        events: events.jsonl 파싱 결과 (list of dict). Telemetry singleton 의
            출력 포맷 (agent_status / iteration_progress / result).
        recent_verdicts: 최근 N 회 run 의 verdict 시퀀스 (옵션).
            ``["COMPLETE", "BLOCKED", "BLOCKED", ...]`` 형태.
        llm_call: 옵션 ``llm(prompt) -> str``. None 이면 결정론만 사용.

    Returns:
        RefactoringProposal — 안건 1건 (markdown 변환 대상).
    """
    _try_emit_telemetry(
        "system_refactoring_strategist",
        "working",
        f"events={len(events)} recent={len(recent_verdicts or [])}",
    )

    silent_count = _count_silent_fails(events)
    verdict_dist = _count_verdicts(events)
    blocked_count = _count_blocked_verdicts(events)

    # 최근 verdicts 도 BLOCKED 카운트에 합산 (in-memory 시나리오)
    if recent_verdicts:
        blocked_count += sum(1 for v in recent_verdicts if v.upper() == "BLOCKED")
        total_runs = len(recent_verdicts)
    else:
        # events 의 result 이벤트 수를 total_runs 로 사용
        total_runs = sum(1 for e in events if e.get("type") == "result")

    # 1. silent fail 패턴 (DoD)
    if silent_count >= SILENT_FAIL_THRESHOLD:
        proposal = _proposal_silent_fail_pattern(silent_count, total_runs)
        _try_emit_telemetry(
            "system_refactoring_strategist",
            "done",
            f"rule match — silent_fail {silent_count}회",
        )
        return proposal

    # 2. BLOCKED 비율 50%+ 패턴
    if total_runs >= 2 and blocked_count / total_runs >= 0.5:
        proposal = _proposal_blocked_ratio(blocked_count, total_runs)
        _try_emit_telemetry(
            "system_refactoring_strategist",
            "done",
            f"rule match — blocked_ratio {blocked_count}/{total_runs}",
        )
        return proposal

    # 3. LLM fallback (옵션)
    if llm_call is not None and (events or recent_verdicts):
        prompt = _build_llm_prompt(events, recent_verdicts, verdict_dist, silent_count, blocked_count)
        try:
            response = llm_call(prompt)
            parsed = json.loads(response.strip())
            proposal = RefactoringProposal(
                title=str(parsed.get("title", "(LLM 미해석)")),
                root_cause_analysis=str(parsed.get("root_cause_analysis", "(LLM 미해석)")),
                proposed_changes=list(parsed.get("proposed_changes", [])),
                estimated_cost=str(parsed.get("estimated_cost", "medium")),
                confidence=float(parsed.get("confidence", 0.65)),
                analysis_method="llm",
                signal_summary={
                    "silent_fail_count": silent_count,
                    "verdict_distribution": dict(verdict_dist),
                    "blocked_count": blocked_count,
                    "total_runs": total_runs,
                },
            )
            _try_emit_telemetry(
                "system_refactoring_strategist", "done", "llm analysis"
            )
            return proposal
        except Exception:  # noqa: BLE001
            pass  # → unknown fallback

    # 4. Unknown fallback — 안건이 발제될 만한 강한 신호 부재
    proposal = RefactoringProposal(
        title="신호 부족 — 안건 발제 보류",
        root_cause_analysis=(
            f"silent_fail={silent_count}, blocked={blocked_count}/{total_runs}, "
            f"verdict_dist={dict(verdict_dist)}. 결정론 threshold 미달 + LLM 미제공."
        ),
        proposed_changes=["(추가 데이터 수집 후 재분석 — Phase 2 단계 정상 동작)"],
        estimated_cost="low",
        confidence=0.3,
        analysis_method="rule",
        signal_summary={
            "silent_fail_count": silent_count,
            "verdict_distribution": dict(verdict_dist),
            "blocked_count": blocked_count,
            "total_runs": total_runs,
        },
    )
    _try_emit_telemetry(
        "system_refactoring_strategist", "done", "no strong signal"
    )
    return proposal


def _build_llm_prompt(
    events: list[dict[str, Any]],
    recent_verdicts: Optional[list[str]],
    verdict_dist: Counter,
    silent_count: int,
    blocked_count: int,
) -> str:
    """LLM 입력 prompt — JSON 응답 강제."""
    return (
        "당신은 자기 진화형 소프트웨어의 *시스템 리팩토링 전략가* 입니다. "
        "다음 통계를 분석하여 *이사회 안건* 1건을 JSON 으로 반환해주세요.\n\n"
        f"통계:\n"
        f"  silent_fail_count = {silent_count}\n"
        f"  verdict_distribution = {dict(verdict_dist)}\n"
        f"  blocked_count = {blocked_count}\n"
        f"  recent_verdicts = {recent_verdicts or []}\n\n"
        '응답 JSON: {"title": "...", "root_cause_analysis": "...", '
        '"proposed_changes": ["...", "..."], "estimated_cost": "low|medium|high", '
        '"confidence": 0.0~1.0}'
    )


# ---------------------------------------------------------------------------
# Markdown 출력 — 이사회 안건 보존 (Phase 4 의결권 활성화 전까지)
# ---------------------------------------------------------------------------
def write_proposal_markdown(
    proposal: RefactoringProposal, output_dir: Path
) -> Path:
    """``RefactoringProposal`` 을 ``<timestamp>_<title>.md`` 로 저장.

    Args:
        proposal: 안건.
        output_dir: 저장 디렉터리 (예: ``outputs/_refactoring_proposals/``).
            부재 시 자동 생성.

    Returns:
        저장된 markdown 파일 경로.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    # title 을 file-system safe slug 로 변환
    slug = re.sub(r"[^\w\-_.가-힣]+", "_", proposal.title)[:80]
    md_path = output_dir / f"{timestamp}_{slug}.md"

    lines = [
        f"# {proposal.title}",
        "",
        f"- **analysis_method**: `{proposal.analysis_method}`",
        f"- **confidence**: {proposal.confidence:.2f}",
        f"- **estimated_cost**: `{proposal.estimated_cost}`",
        "",
        "## Root Cause Analysis",
        "",
        proposal.root_cause_analysis,
        "",
        "## Proposed Changes",
        "",
    ]
    for i, change in enumerate(proposal.proposed_changes, start=1):
        lines.append(f"{i}. {change}")
    lines.extend([
        "",
        "## Signal Summary",
        "",
        "```json",
        json.dumps(proposal.signal_summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "---",
        "",
        "*Phase 2 한계 — 본 안건은 markdown 보존만. Phase 4 의결권 활성화 후",
        "Boardroom 의결을 거쳐 자동 적용 예정.*",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# Auto-Fix Coordinator → Strategist 라우팅 진입점
# ---------------------------------------------------------------------------
def trigger_strategist_on_escalation(
    decision: Any,
    events_jsonl_path: Optional[Path] = None,
    recent_verdicts: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
    llm_call: Optional[Callable[[str], str]] = None,
) -> Optional[Path]:
    """Auto-Fix Coordinator ``decision.action == "escalate"`` 시 호출.

    동작:
        1. ``decision.action != "escalate"`` 면 즉시 None 반환 (no-op)
        2. events.jsonl 파일 로드 (있으면) + recent_verdicts 합산
        3. ``analyze_runtime_patterns`` → ``RefactoringProposal``
        4. ``write_proposal_markdown`` → outputs/_refactoring_proposals/ 저장
        5. 저장 경로 반환

    Args:
        decision: ``AutoFixDecision`` (duck-typed — ``.action`` 속성만 확인).
        events_jsonl_path: events.jsonl 경로. None 이면 빈 list 로 처리.
        recent_verdicts: 최근 run 의 verdict 시퀀스 (옵션).
        output_dir: proposal markdown 저장 디렉터리. None 이면
            ``outputs/_refactoring_proposals/`` 기본.
        llm_call: LLM 호출 callable (옵션).

    Returns:
        저장된 markdown 경로 (escalate 아닌 경우 None).
    """
    if getattr(decision, "action", "") != "escalate":
        return None

    events: list[dict[str, Any]] = []
    if events_jsonl_path is not None and events_jsonl_path.exists():
        try:
            for line in events_jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:  # noqa: BLE001
            pass  # 파일 읽기 실패해도 빈 list 로 진행

    proposal = analyze_runtime_patterns(
        events=events, recent_verdicts=recent_verdicts, llm_call=llm_call
    )

    if output_dir is None:
        # 기본 경로 — 호출 측이 outputs_dir 컨텍스트를 모를 때
        output_dir = Path("outputs") / "_refactoring_proposals"

    return write_proposal_markdown(proposal, output_dir)


# ---------------------------------------------------------------------------
# Agent 프로파일 (CrewAI / LLM 호출 시 사용)
# ---------------------------------------------------------------------------
SYSTEM_REFACTORING_STRATEGIST_NAME = "SystemRefactoringStrategist"
SYSTEM_REFACTORING_STRATEGIST_ROLE = "Senior System Refactoring Strategist"
SYSTEM_REFACTORING_STRATEGIST_GOAL = (
    "런타임 로그 + Telemetry 이벤트를 분석하여 자기 진화형 소프트웨어의 "
    "*시스템 자율 개선안* (max_iterations / GUI sandbox / Token 한도 등) 을 "
    "이사회 안건으로 발제한다."
)
SYSTEM_REFACTORING_STRATEGIST_BACKSTORY = (
    "당신은 자기 진화형 소프트웨어의 *전략 분석가* 입니다. "
    "본부 9 RV (Runtime Verification) 가 감지한 런타임 결함과 Telemetry "
    "이벤트 패턴을 종합하여, 시스템 차원의 개선이 필요한 지점을 식별하고 "
    "*구체적인 수정 제안* 을 이사회 안건으로 작성합니다.\n\n"
    "작업 원칙:\n"
    "  1. 결정론 패턴 (silent fail 5회 / BLOCKED 50%+) 은 LLM 없이 즉시 안건화\n"
    "  2. 결정론 미매치 시 LLM 으로 패턴 해석 + JSON 산출\n"
    "  3. 모든 안건은 root_cause + proposed_changes + estimated_cost 필수\n"
    "  4. confidence < 0.5 면 \"신호 부족\" 으로 보류 (false positive 차단)\n"
    "  5. Phase 4 이사회 의결권 활성화 전까지 markdown 저장만 (자동 적용 X)"
)
