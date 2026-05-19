# -*- coding: utf-8 -*-
"""
Nexus Alpha Retrospective Lead — 본부 10 Coordination/Communication 두 번째 멤버.

PR #149 (2026-05-15, 본인 비전 통찰 6 — D-5 처방 + Phase 3 cycle 완성):
    Phase 3 wiring (PR #148) 의 Knowledge Curator 가 *코드 본문* 으로만 summary/tags
    채우는 한계를 해결. Retrospective Lead 가 매 빌드 종료 시 4단 회고를 산출 →
    Curator 의 prompt 입력으로 추가 → entry 가 *결함/성공 패턴* 으로 풍부해짐 →
    다음 빌드 RAG recall 이 actionable insight 도 인식.

설계 (Meeting Facilitator / recall / curate 와 동일 하이브리드 패턴):
    - 결정론 골격: workflow_id + verdict + kickoff vs 산출 비교 (구조적 항목)
    - 1 LLM call (선택): what_went_well / what_went_wrong / lessons_learned 채움
    - pytest 환경 자동 skip — 결정론 골격만 + (가능하면) delta_from_kickoff 자동 추출

호출 측 사용:
    from src.agents.coordination import run_retrospective

    report = run_retrospective(
        user_request=...,
        workflow_id=workflow_dir.name,
        verdict="COMPLETE",
        shared_kickoff_decisions=kickoff,
        chain_result=chain_result,
        execution_result=sandbox,
        gap_report_raw=gap_md,
    )
    workflow_dir.joinpath("retrospective.md").write_text(
        report.to_markdown(), encoding="utf-8"
    )
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable, Optional

from .schemas import RetrospectiveReport, SharedKickoffDecisions


# ---------------------------------------------------------------------------
# 에이전트 프로파일 (메타데이터)
# ---------------------------------------------------------------------------
RETROSPECTIVE_LEAD_NAME = "RetrospectiveLead"

RETROSPECTIVE_LEAD_ROLE = "Senior Retrospective Facilitator (Build Postmortem)"

RETROSPECTIVE_LEAD_GOAL = (
    "매 빌드 종료 시 본 워크플로의 산출물 + 킥오프 합의 + 실행 결과를 비교해 "
    "4단 회고 (잘된 점 / 잘못된 점 / 다음 빌드 반영 가능한 학습 / 킥오프 차이) "
    "를 산출한다. 산출물은 Knowledge Curator 의 입력으로 활용되어 entry 의 "
    "summary/tags 가 *행동 가능한 학습* 으로 풍부해진다."
)

RETROSPECTIVE_LEAD_BACKSTORY = (
    "당신은 본부 10 (Coordination/Communication) 의 두 번째 멤버로 신설된 회고 "
    "진행자입니다. Meeting Facilitator 가 *킥오프* 를 담당했다면 당신은 *종결* 의 "
    "회고를 담당합니다.\n\n"
    "철학:\n"
    "  1. 회고는 비난이 아닌 **학습** — 잘된 점도 잘못된 점도 *왜* 그런지 적는다.\n"
    "  2. **킥오프 ↔ 산출 차이** 가 가장 가치 있는 학습 — 환율 변환기 사례 같은 "
    "     cross-agent inconsistency 가 정확히 여기서 드러난다.\n"
    "  3. **actionable insight 만** lessons_learned 에 — '코드 품질 개선' 같은 "
    "     추상적 문구는 다음 빌드에서 무의미. '환율 API timeout 5s 가 부족할 수 "
    "     있음' 같이 구체적으로.\n"
    "  4. **3개 이내** 각 카테고리 — 길게 쓰면 다음 빌드 RAG recall 이 무력화."
)


# ---------------------------------------------------------------------------
# 결정론 골격 — LLM 없이 산출 가능한 부분
# ---------------------------------------------------------------------------
def _detect_delta_from_kickoff(
    shared_kickoff_decisions: Optional[SharedKickoffDecisions],
    chain_result: Any,
    qa_review: str,
) -> list[str]:
    """킥오프 합의의 *공유 가정* 이 실제 산출물에 등장하는지 결정론 검사.

    환율 변환기 사례의 핵심 — 킥오프에서 "frankfurter API 실시간" 으로 합의했는데
    Engineer 산출물에 "frankfurter" 또는 "requests" 같은 키워드가 *없으면* delta.

    매우 거친 휴리스틱이지만 *명백한* 결함 자동 검출에 충분.
    """
    if shared_kickoff_decisions is None or not shared_kickoff_decisions.shared_assumptions:
        return []

    engineer_output = ""
    if chain_result is not None:
        engineer_output = (
            getattr(chain_result, "engineer_output", "")
            or getattr(chain_result, "gui_code_output", "")
            or ""
        )
    haystack = (engineer_output + "\n" + (qa_review or "")).lower()
    if not haystack.strip():
        return []

    deltas: list[str] = []
    for assumption in shared_kickoff_decisions.shared_assumptions:
        # 결정 본문의 영문 키워드 중 3자 이상 토큰 1개라도 잡히는지
        decision_tokens = [
            t.lower() for t in re.split(r"[\s\(\)\.,/]+", assumption.decision)
            if len(t) >= 3 and t.isascii()
        ]
        if not decision_tokens:
            continue
        if not any(t in haystack for t in decision_tokens):
            deltas.append(
                f"{assumption.id} ({assumption.owner}): 킥오프 결정 "
                f"'{assumption.decision[:60]}' 가 산출물에서 발견되지 않음"
            )
    return deltas[:3]  # 3개 이내 — actionable 유지


# ---------------------------------------------------------------------------
# 1 LLM call (선택) — what_went_well / wrong / lessons 채움
# ---------------------------------------------------------------------------
_RETROSPECTIVE_PROMPT_TEMPLATE = """\
당신은 한국 IT 회사의 회고 진행자입니다. 본 빌드의 컨텍스트를 보고 4단 회고를
**JSON 으로** 출력하세요. 다른 설명 금지. 각 카테고리 3개 이내.

스키마:
{{
  "what_went_well": ["성공 패턴 1줄 1", ...],
  "what_went_wrong": ["결함 패턴 1줄 1", ...],
  "lessons_learned": ["다음 빌드 actionable insight 1줄 1", ...]
}}

원칙:
  - lessons_learned 는 *구체적* — "환율 API timeout 5s 부족 가능" 같이.
    추상적 문구 ("코드 품질 향상") 금지.
  - 충돌/결함이 명확히 있으면 무리해서 well 채우지 말 것.

--- 사용자 요청 ---
{user_request}
--- 킥오프 합의 (있으면) ---
{kickoff_summary}
--- 산출물 미리보기 (최대 1000자) ---
{output_preview}
--- 실행 verdict ---
{execution_verdict}
--- QA verdict ---
{qa_verdict}
--- 자동 검출된 kickoff delta ---
{delta_block}
--- 끝 ---
"""


def _build_output_preview(chain_result: Any, max_chars: int = 1000) -> str:
    if chain_result is None:
        return "(산출물 없음)"
    parts: list[str] = []
    for attr in ("engineer_output", "gui_code_output", "qa_review"):
        text = getattr(chain_result, attr, "") or ""
        if text:
            parts.append(f"[{attr}]\n{text[:400]}")
    if not parts:
        return "(산출물 없음)"
    joined = "\n\n".join(parts)
    return joined[:max_chars]


def _build_kickoff_summary(decisions: Optional[SharedKickoffDecisions]) -> str:
    if decisions is None or not decisions.shared_assumptions:
        return "(킥오프 합의 없음)"
    lines = []
    for a in decisions.shared_assumptions:
        lines.append(f"- {a.id} ({a.owner}): {a.decision}")
    return "\n".join(lines[:8])  # 8개 이내


def _parse_retrospective_json(text: str) -> dict[str, list[str]]:
    """LLM 응답에서 4 카테고리 dict 추출. 실패 시 빈 dict."""
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
        result: dict[str, list[str]] = {}
        for key in ("what_went_well", "what_went_wrong", "lessons_learned"):
            raw = data.get(key, [])
            if isinstance(raw, list):
                result[key] = [str(x).strip() for x in raw if str(x).strip()][:3]
        if result:
            return result
    return {}


def _default_llm_call(prompt: str) -> str:
    """기본 LLM 호출 — Meeting Facilitator / recall / curate 와 동일 패턴."""
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
def run_retrospective(
    *,
    user_request: str,
    workflow_id: str,
    verdict: str,
    shared_kickoff_decisions: Optional[SharedKickoffDecisions] = None,
    chain_result: Any = None,
    execution_result: Any = None,
    qa_review: str = "",
    llm_call: Optional[Callable[[str], str]] = None,
) -> RetrospectiveReport:
    """매 빌드 종료 시 1회 호출 — RetrospectiveReport 산출.

    하이브리드 흐름 (Meeting Facilitator 와 동일):
        1. 결정론 골격 — workflow_id / verdict / delta_from_kickoff
        2. 1 LLM call (선택) — well / wrong / lessons 채움
        3. pytest 환경 자동 skip → 결정론 골격만 반환

    Args:
        user_request: 사용자 원 자연어 요청.
        workflow_id: 본 빌드 디렉터리 이름.
        verdict: ``"COMPLETE"`` / ``"BLOCKED"`` 등 결정표 verdict 문자열.
        shared_kickoff_decisions: PR #146 의 킥오프 산출 (있으면 delta 검출).
        chain_result: ``WorkflowResult`` 객체 (Engineer/QA 산출).
        execution_result: SandboxResult (실행 verdict).
        qa_review: QA 리뷰 markdown — chain_result 의 qa_review 와 합쳐 delta 검출.
        llm_call: 외부 주입 가능 (테스트용). None + 비-pytest 시 ``_default_llm_call``.

    Returns:
        RetrospectiveReport — to_yaml() / to_markdown() 둘 다 지원.
    """
    deltas = _detect_delta_from_kickoff(
        shared_kickoff_decisions, chain_result, qa_review
    )

    in_pytest = "pytest" in sys.modules
    if llm_call is None and not in_pytest:
        llm_call = _default_llm_call

    well: list[str] = []
    wrong: list[str] = []
    lessons: list[str] = []

    if llm_call is not None:
        execution_verdict = "unknown"
        if execution_result is not None:
            execution_verdict = str(getattr(execution_result, "verdict", "unknown"))

        prompt = _RETROSPECTIVE_PROMPT_TEMPLATE.format(
            user_request=user_request.strip(),
            kickoff_summary=_build_kickoff_summary(shared_kickoff_decisions),
            output_preview=_build_output_preview(chain_result),
            execution_verdict=execution_verdict,
            qa_verdict=(
                "APPROVED" if "APPROVED" in qa_review.upper() else
                "NEEDS_REVISION" if "NEEDS_REVISION" in qa_review.upper() else
                "UNKNOWN"
            ),
            delta_block="\n".join(f"- {d}" for d in deltas) if deltas else "(없음)",
        )
        # PR #174 — 3 시나리오 진단 surface (fail-silent 5번째 변형 정리)
        llm_error_reason: Optional[str] = None
        try:
            response = llm_call(prompt)
        except Exception as exc:  # noqa: BLE001 — 모든 예외 surface (PR #160a/#170/#172 패턴)
            response = ""
            llm_error_reason = f"{type(exc).__name__}: {exc}"
        parsed = _parse_retrospective_json(response or "")
        well = parsed.get("what_went_well", [])
        wrong = parsed.get("what_went_wrong", [])
        lessons = parsed.get("lessons_learned", [])

        # 진단 분기 1 — LLM 호출 자체 실패 (response 빈 문자열 + 예외)
        if llm_error_reason is not None:
            if not wrong:
                wrong = [f"Retrospective LLM 호출 실패 ({llm_error_reason})"]
            if not lessons:
                lessons = ["LLM API 안정성 점검 필요 (다음 빌드 회고 fallback 진입)"]
        # 진단 분기 2 (PR #176 hot-fix) — response *빈/공백* + 예외 *없음* (silent timeout/공백)
        # PR #174 의 첫 시도가 본 분기 누락 → 2026-05-19 Track B E2E 재검증에서 retrospective.md
        # 여전히 (없음). 우선순위: Exception > 빈/공백 > parse 실패 > 빈 list — strip 후 빈
        # 응답은 *parse 실패 분기와 의미가 다름* (LLM 이 실 응답을 보냈는지 자체가 의문).
        elif not (response or "").strip():
            if not wrong:
                wrong = [
                    "Retrospective LLM 응답 빈 문자열 (예외 없이 silent 빈 응답 수신 — "
                    "provider timeout / prompt 토큰 한도 / streaming 결함 추정)"
                ]
            if not lessons:
                lessons = [
                    "LLM provider 상태 점검 + prompt 길이/토큰 한도 확인 필요"
                ]
        # 진단 분기 3 — response 받았지만 JSON parsing 실패
        elif response and not parsed:
            raw_preview = response.strip()[:120]
            if len(response.strip()) > 120:
                raw_preview += "..."
            if not wrong:
                wrong = [f"Retrospective JSON parse 실패 — raw: {raw_preview!r}"]
            if not lessons:
                lessons = ["LLM 응답 JSON 형식 강제 prompt 개선 필요"]
        # 진단 분기 4 — 정상 응답 + parse OK 인데 4 list 모두 빈 list
        elif response and parsed and not (well or wrong or lessons):
            well = ["LLM 정상 응답 — 회고 항목 없음 판단 (재현 시 prompt 개선 검토)"]

    # delta 가 자동 검출됐는데 LLM 이 wrong 에 반영 안 했다면, wrong 에 자동 추가
    if deltas and not wrong:
        wrong = [
            f"킥오프 합의 ↔ 산출 불일치 (자동 검출): {d}" for d in deltas[:3]
        ]

    return RetrospectiveReport(
        workflow_id=workflow_id,
        verdict=verdict,
        what_went_well=well,
        what_went_wrong=wrong,
        lessons_learned=lessons,
        delta_from_kickoff=deltas,
    )


__all__ = [
    "RETROSPECTIVE_LEAD_BACKSTORY",
    "RETROSPECTIVE_LEAD_GOAL",
    "RETROSPECTIVE_LEAD_NAME",
    "RETROSPECTIVE_LEAD_ROLE",
    "run_retrospective",
]
