# -*- coding: utf-8 -*-
"""자동 QA 피드백 루프 의사결정 helper (Phase 7 — PR #48).

PR #42~#47 에서 도입된 4종 QA 도구 (Code QA / Functional Test / GUI Test /
Robustness) 산출 결과를 합산해, **재생성 필요 여부** 와 **Python Engineer
에게 전달할 재생성 지시 메시지** 를 결정하는 standalone helper.

설계 원칙:
    - **duck typing**: 입력은 ``success: bool`` 와 ``summary_line()`` 메소드만
      가지면 OK — 구체 클래스 (CodeQAResult, FunctionalTestResult 등) 에 의존
      안 함. 다른 PR 들이 머지된 후 자연스럽게 통합 가능.
    - **standalone**: LangGraph / iterative_loop 와 직접 결합 안 함. 워크플로
      자유롭게 호출만 하면 됨.
    - **결정론적**: LLM 무관. 입력만 보고 deterministic 결정.

iterative_loop 통합 패턴 (PR #49 10차 E2E 에서 실 사용)::

    qa_results = {
        "code_qa": run_code_qa(workflow_dir),
        "functional": run_test_cases(target_script),
        "gui": run_gui_test(target_path, output_dir),
        "robustness": run_robustness_scenarios(target_script),
    }
    decision = evaluate_qa_results(qa_results, retry_count=current_retry,
                                   max_retries=3)
    if decision.should_retry:
        feedback = build_feedback_message_for_engineer(decision, qa_reports)
        # → Python Engineer 에게 feedback 전달 후 재생성
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QAFeedbackDecision:
    """QA 결과 합산 후 재생성 결정."""

    overall_passed: bool
    """모든 *실행된* QA 도구가 PASS — skipped 는 *집계 제외*."""

    should_retry: bool
    """재생성 필요 + retry budget 남음 (overall_passed=False AND retry_count < max_retries)."""

    retry_count: int
    """현재까지의 재시도 횟수 (0=첫 실행)."""

    max_retries: int
    """최대 재시도 횟수 (보통 3)."""

    failed_qa_tools: list[str] = field(default_factory=list)
    """실패 QA 도구 이름들 (예: ['code_qa', 'functional'])."""

    skipped_qa_tools: list[str] = field(default_factory=list)
    """skip 된 도구 이름들 (예: ['gui', 'robustness'])."""

    summary_lines: list[str] = field(default_factory=list)
    """각 도구의 한 줄 요약 (사람이 읽기 위함)."""

    def summary_line(self) -> str:
        if self.overall_passed:
            return (
                f"[QA_LOOP PASS] retry={self.retry_count}/{self.max_retries}, "
                f"failed=0, skipped={len(self.skipped_qa_tools)}"
            )
        verdict_kw = "RETRY" if self.should_retry else "BUDGET_EXHAUSTED"
        return (
            f"[QA_LOOP {verdict_kw}] retry={self.retry_count}/{self.max_retries}, "
            f"failed={len(self.failed_qa_tools)} ({', '.join(self.failed_qa_tools)})"
        )


def evaluate_qa_results(
    results: dict[str, Any],
    retry_count: int = 0,
    max_retries: int = 3,
) -> QAFeedbackDecision:
    """QA 도구 결과 묶음을 합산해 재생성 결정 산출.

    Args:
        results: ``{"tool_name": result_object_or_None}`` 형태. result 는 다음
            attr 만 있으면 됨: ``success: bool``, ``skipped: bool`` (선택),
            ``summary_line() -> str`` (선택). None 값은 *해당 도구 미실행* 로 간주.
        retry_count: 현재까지의 재시도 횟수 (0=첫 실행).
        max_retries: 최대 재시도 횟수 (이후엔 budget exhausted).

    Returns:
        QAFeedbackDecision — overall_passed / should_retry / failed_qa_tools.
    """
    failed: list[str] = []
    skipped: list[str] = []
    summaries: list[str] = []

    for tool_name, result in results.items():
        if result is None:
            continue

        is_skipped = bool(getattr(result, "skipped", False))
        if is_skipped:
            skipped.append(tool_name)
            if hasattr(result, "summary_line"):
                summaries.append(f"{tool_name}: {result.summary_line()}")
            continue

        is_success = bool(getattr(result, "success", False))
        if not is_success:
            failed.append(tool_name)

        if hasattr(result, "summary_line"):
            summaries.append(f"{tool_name}: {result.summary_line()}")

    overall_passed = len(failed) == 0
    should_retry = (not overall_passed) and (retry_count < max_retries)

    return QAFeedbackDecision(
        overall_passed=overall_passed,
        should_retry=should_retry,
        retry_count=retry_count,
        max_retries=max_retries,
        failed_qa_tools=failed,
        skipped_qa_tools=skipped,
        summary_lines=summaries,
    )


def build_feedback_message_for_engineer(
    decision: QAFeedbackDecision,
    full_qa_reports: Optional[dict[str, str]] = None,
) -> str:
    """``QAFeedbackDecision`` + 도구별 *전체 보고서 텍스트* 를 받아 Python Engineer
    에게 보낼 재생성 지시 메시지 작성.

    Args:
        decision: ``evaluate_qa_results`` 산출.
        full_qa_reports: ``{"tool_name": "full markdown report text"}``. 각 보고서는
            해당 QA agent 가 작성한 5단 구조 마크다운. None 이면 summary_line 만 사용.

    Returns:
        Engineer 에게 전달할 markdown 재생성 지시 메시지.
    """
    lines: list[str] = []
    lines.append("# 🔁 QA 자동 피드백 — 재생성 지시")
    lines.append("")
    lines.append(
        f"이전 산출물의 자동 QA 검증 결과 **{len(decision.failed_qa_tools)} 도구 실패**, "
        f"재시도 budget {decision.retry_count + 1}/{decision.max_retries + 1} 회차."
    )
    lines.append("")
    lines.append("## 실패 도구 요약")
    if not decision.failed_qa_tools:
        lines.append("- (없음 — 모든 도구 PASS 또는 SKIPPED)")
    else:
        for line in decision.summary_lines:
            lines.append(f"- {line}")
    lines.append("")

    if decision.skipped_qa_tools:
        lines.append("## SKIPPED 도구 (환경 미구비, 결함 아님)")
        for tool in decision.skipped_qa_tools:
            lines.append(f"- {tool}")
        lines.append("")

    lines.append("## 보정 지시")
    if not decision.failed_qa_tools:
        lines.append("- 보정 불필요 — 모든 QA 도구 통과.")
    else:
        lines.append(
            "아래 *각 도구의 5단 보고서* 의 **재생성 지시** 섹션을 우선순위 순으로 반영해 "
            "코드를 재작성하세요. 한 번에 모두 보정하기 어려우면 BLOCKER → MAJOR → "
            "MINOR 순으로 처리하세요."
        )
        lines.append("")
        if full_qa_reports:
            for tool_name in decision.failed_qa_tools:
                report = full_qa_reports.get(tool_name)
                if report:
                    lines.append(f"### {tool_name} 보고서 (전문)")
                    lines.append(report)
                    lines.append("")
        else:
            lines.append("(개별 보고서 본문 미제공 — 호출 측이 `full_qa_reports` 인자 미전달)")
    lines.append("")
    lines.append("---")
    lines.append(
        f"본 메시지는 `qa_feedback_loop.build_feedback_message_for_engineer()` 자동 생성 "
        f"(retry_count={decision.retry_count}, max_retries={decision.max_retries})."
    )
    return "\n".join(lines)
