# -*- coding: utf-8 -*-
"""Runtime Failure Analyzer — 본부 9 RV 분석 엔진 (v13 Phase 1).

`Exe Runtime Tester` 가 산출한 `RuntimeTestResult.stderr` / `error_trace` 를
입력으로 받아 *actionable feedback* (구체 처방) 산출.

LLM 호출 *옵션* — `BaseLLMProvider.generate()` 사용 (기존 패턴). 다만 *결정론
fallback* 도 제공 — 알려진 silent fail 패턴 (UnicodeEncodeError /
ModuleNotFoundError / ImportError) 은 LLM 없이도 *즉시 처방*.

Telemetry: `AgentStatusEvent(department="rv")` emit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from crewai import Agent  # type: ignore
    from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult


# ---------------------------------------------------------------------------
# 분석 결과 schema
# ---------------------------------------------------------------------------
@dataclass
class FailureAnalysis:
    """`analyze_runtime_failure` 의 산출 — *actionable feedback*.

    Attributes:
        root_cause: 추정 근본 원인 (예: "UnicodeEncodeError — cp949 환경에서 UTF-8 미지정").
        recommended_fix: 구체 처방 (예: "entry.py 의 sys.stdout.reconfigure(encoding='utf-8') 추가").
        severity: ``"low"`` / ``"medium"`` / ``"high"`` / ``"critical"``.
        confidence: 0.0~1.0 — 결정론 매칭은 0.9+, LLM 분석은 0.6~0.8.
        analysis_method: ``"rule"`` (결정론) / ``"llm"`` / ``"hybrid"``.
    """

    root_cause: str
    recommended_fix: str
    severity: str
    confidence: float
    analysis_method: str


# ---------------------------------------------------------------------------
# 결정론 패턴 매처 — LLM 호출 없이 즉시 진단 가능한 알려진 silent fail
# ---------------------------------------------------------------------------
_DETERMINISTIC_PATTERNS: list[tuple[re.Pattern[str], FailureAnalysis]] = [
    (
        re.compile(r"UnicodeEncodeError|UnicodeDecodeError|codec can't (encode|decode)"),
        FailureAnalysis(
            root_cause="UnicodeEncodeError — Windows cp949 환경에서 UTF-8 미지정으로 한글/특수문자 인코딩 실패",
            recommended_fix="entry.py 시작에 `sys.stdout.reconfigure(encoding='utf-8')` + `sys.stderr.reconfigure(encoding='utf-8')` 추가. 또는 PyInstaller `--collect-binaries codecs` 적용.",
            severity="high",
            confidence=0.95,
            analysis_method="rule",
        ),
    ),
    (
        re.compile(r"ModuleNotFoundError: No module named ['\"]([\w._]+)['\"]"),
        FailureAnalysis(
            root_cause="ModuleNotFoundError — PyInstaller hidden_imports 누락",
            recommended_fix="execute_pyinstaller 호출의 `hidden_imports` 에 누락된 module 추가. AST scan 또는 `--collect-all <package>` 옵션 검토.",
            severity="high",
            confidence=0.9,
            analysis_method="rule",
        ),
    ),
    (
        re.compile(r"ImportError|cannot import name"),
        FailureAnalysis(
            root_cause="ImportError — module 존재하지만 *특정 attribute* 가 미발견",
            recommended_fix="LLM 산출 코드의 `from X import Y` 가 *X 의 실제 attribute Y* 와 일치하는지 검증. PR #133 fixup #14 의 AST chain 검증 패턴 적용.",
            severity="high",
            confidence=0.85,
            analysis_method="rule",
        ),
    ),
    (
        re.compile(r"PermissionError|Access is denied"),
        FailureAnalysis(
            root_cause="PermissionError — file 또는 디렉터리 권한 부족 (Windows UAC 또는 file lock)",
            recommended_fix="entry 가 *user 쓰기 가능 디렉터리* (예: %APPDATA%) 사용하도록 변경. 또는 *file lock* 확인 (이전 process 가 미해제).",
            severity="medium",
            confidence=0.85,
            analysis_method="rule",
        ),
    ),
    (
        re.compile(r"silent fail / entry 오선택"),
        FailureAnalysis(
            root_cause="entry 오선택 — entry 가 import 만 하고 즉시 return (theme.py / test_*.py 같은 비-앱 file)",
            recommended_fix="`_select_entry_point()` (build_workflow.py:336) 의 PRIORITY 1 검증 강화 — non-test + `__main__` block 필수.",
            severity="critical",
            confidence=0.9,
            analysis_method="rule",
        ),
    ),
]


def _try_emit_telemetry(
    agent: str, status: str, detail: str = ""
) -> None:
    """Telemetry emit — 실패 silent."""
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
                department="rv",
                status=status,
                detail=detail,
            )
        )
    except Exception:  # noqa: BLE001
        pass


def analyze_runtime_failure(
    runtime_result: "RuntimeTestResult",
    llm_call: Optional[Callable[[str], str]] = None,
) -> FailureAnalysis:
    """`RuntimeTestResult` 의 stderr/error_trace 를 분석하여 *처방* 산출.

    동작:
        1. PASS verdict → 분석 불필요 (no_failure 반환)
        2. 결정론 패턴 매처로 즉시 진단 시도
        3. 매치 실패 + ``llm_call`` 제공 시 LLM 분석
        4. LLM 미제공 시 ``unknown`` fallback

    Args:
        runtime_result: Exe Runtime Tester 의 산출.
        llm_call: 선택. ``llm_call(prompt: str) -> str`` 의 callable.
            None 시 결정론 패턴만 사용. pytest 환경에서는 항상 None 권장.

    Returns:
        FailureAnalysis — actionable feedback.
    """
    _try_emit_telemetry(
        "runtime_failure_analyzer",
        "working",
        f"verdict={runtime_result.verdict}",
    )

    if runtime_result.verdict == "PASS":
        analysis = FailureAnalysis(
            root_cause="no failure — runtime PASS",
            recommended_fix="(no action required)",
            severity="low",
            confidence=1.0,
            analysis_method="rule",
        )
        _try_emit_telemetry("runtime_failure_analyzer", "done", "PASS — no analysis")
        return analysis

    # 결정론 패턴 매처
    haystack = "\n".join([
        runtime_result.error_trace or "",
        runtime_result.stderr or "",
    ])
    for pattern, prebuilt_analysis in _DETERMINISTIC_PATTERNS:
        if pattern.search(haystack):
            _try_emit_telemetry(
                "runtime_failure_analyzer",
                "done",
                f"rule match — {prebuilt_analysis.root_cause[:40]}",
            )
            return prebuilt_analysis

    # LLM fallback (옵션)
    if llm_call is not None:
        prompt = (
            f"빌드된 .exe 가 다음과 같이 실패했습니다. *근본 원인* + *구체 처방* 을 "
            f"JSON 형식으로 답해주세요.\n\n"
            f"verdict: {runtime_result.verdict}\n"
            f"exit_code: {runtime_result.exit_code}\n"
            f"stderr (앞 800자):\n{(runtime_result.stderr or '')[:800]}\n\n"
            f"응답 JSON: {{\"root_cause\": \"...\", \"recommended_fix\": \"...\", \"severity\": \"medium\"}}"
        )
        try:
            response = llm_call(prompt)
            # JSON parse 시도
            import json

            parsed = json.loads(response.strip())
            analysis = FailureAnalysis(
                root_cause=str(parsed.get("root_cause", "(unparseable)")),
                recommended_fix=str(parsed.get("recommended_fix", "(unparseable)")),
                severity=str(parsed.get("severity", "medium")),
                confidence=0.7,
                analysis_method="llm",
            )
            _try_emit_telemetry("runtime_failure_analyzer", "done", "llm analysis")
            return analysis
        except Exception:  # noqa: BLE001
            pass  # fall through to unknown fallback

    # Unknown fallback
    analysis = FailureAnalysis(
        root_cause=f"unknown failure pattern (verdict={runtime_result.verdict})",
        recommended_fix=(
            f"stderr 직접 검토 필요. (앞 200자) "
            f"{(runtime_result.stderr or runtime_result.error_trace or 'no info')[:200]}"
        ),
        severity="medium",
        confidence=0.3,
        analysis_method="rule",
    )
    _try_emit_telemetry("runtime_failure_analyzer", "done", "unknown — fallback")
    return analysis


# ---------------------------------------------------------------------------
# CrewAI Agent factory (LLM 호출 경로)
# ---------------------------------------------------------------------------
def create_runtime_failure_analyzer_agent(
    llm: Optional[object] = None,
    verbose: bool = False,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> "Agent":
    """CrewAI Agent — LLM 기반 failure 분석 (결정론 패턴 매처 보완용).

    `analyze_runtime_failure(runtime_result, llm_call=...)` 의 LLM 경로용.
    pytest 환경에서는 사용하지 않음 (결정론 매처가 우선).
    """
    from crewai import Agent  # type: ignore
    from src.llm.factory import NexusAlphaLLM  # type: ignore

    role = "Runtime Failure Analyzer (본부 9 RV)"
    goal = (
        "빌드된 .exe 의 런타임 silent fail / crash 의 *근본 원인* 을 stderr/trace 에서 "
        "추출하고, *구체 처방* (코드 변경 + PyInstaller 옵션 + 환경 변수) 을 산출한다."
    )
    backstory = (
        "당신은 Windows .exe 런타임 결함의 전문 분석가입니다. PyInstaller bootloader, "
        "Python C extension, UAC 권한, cp949 encoding 같은 *Windows 특화 silent fail* "
        "패턴을 정확히 매핑할 수 있습니다.\n\n"
        "응답 형식: JSON 객체 — root_cause, recommended_fix, severity."
    )
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        verbose=verbose,
        llm=llm or NexusAlphaLLM(),
        max_iter=max_iter,
        allow_delegation=allow_delegation,
    )
