# -*- coding: utf-8 -*-
"""Runtime Failure Analyzer 단위 test (v13 Phase 1)."""

from __future__ import annotations

from pathlib import Path

from src.agents.runtime_verification.exe_runtime_tester import RuntimeTestResult
from src.agents.runtime_verification.runtime_failure_analyzer import (
    FailureAnalysis,
    analyze_runtime_failure,
)


def _make_runtime_result(stderr: str, verdict: str = "CRASH") -> RuntimeTestResult:
    """test 용 RuntimeTestResult."""
    return RuntimeTestResult(
        exit_code=1 if verdict == "CRASH" else 0,
        stderr=stderr,
        stdout="",
        startup_time_ms=50.0,
        memory_peak_mb=None,
        timed_out=False,
        verdict=verdict,
        error_trace=stderr,
        exe_path=Path("C:/fake/dist/App.exe"),
    )


class TestFailureAnalysisSchema:
    def test_dataclass_fields(self):
        analysis = FailureAnalysis(
            root_cause="test",
            recommended_fix="fix it",
            severity="high",
            confidence=0.9,
            analysis_method="rule",
        )
        assert analysis.severity == "high"
        assert analysis.confidence == 0.9


class TestDeterministicPatterns:
    """⭐ 결정론 패턴 매처 — LLM 호출 없이 즉시 진단."""

    def test_pass_verdict_no_analysis(self):
        """PASS verdict 는 분석 불필요."""
        rt = _make_runtime_result(stderr="", verdict="PASS")
        analysis = analyze_runtime_failure(rt)
        assert "no failure" in analysis.root_cause
        assert analysis.severity == "low"

    def test_unicode_encode_error(self):
        """⭐ UnicodeEncodeError pattern — DoD 의 핵심 케이스."""
        rt = _make_runtime_result(
            stderr="UnicodeEncodeError: 'cp949' codec can't encode character"
        )
        analysis = analyze_runtime_failure(rt)
        assert "UnicodeEncodeError" in analysis.root_cause
        assert "utf-8" in analysis.recommended_fix.lower()
        assert analysis.severity == "high"
        assert analysis.analysis_method == "rule"

    def test_module_not_found(self):
        rt = _make_runtime_result(
            stderr="ModuleNotFoundError: No module named 'playwright'"
        )
        analysis = analyze_runtime_failure(rt)
        assert "ModuleNotFoundError" in analysis.root_cause
        assert "hidden_imports" in analysis.recommended_fix
        assert analysis.analysis_method == "rule"

    def test_import_error(self):
        rt = _make_runtime_result(
            stderr="ImportError: cannot import name 'NonExistent' from 'module'"
        )
        analysis = analyze_runtime_failure(rt)
        assert "ImportError" in analysis.root_cause
        assert analysis.analysis_method == "rule"

    def test_permission_error(self):
        rt = _make_runtime_result(stderr="PermissionError: [WinError 5] Access is denied")
        analysis = analyze_runtime_failure(rt)
        assert "PermissionError" in analysis.root_cause
        assert analysis.severity == "medium"

    def test_entry_misselect_silent_fail(self):
        """⭐ theme.py 같은 entry 오선택 — error_trace 의 'silent fail / entry 오선택' substring 매치."""
        rt = _make_runtime_result(
            stderr="(exit 0 immediate — silent fail / entry 오선택 추정)",
            verdict="SILENT_FAIL",
        )
        analysis = analyze_runtime_failure(rt)
        assert "entry 오선택" in analysis.root_cause
        assert "_select_entry_point" in analysis.recommended_fix
        assert analysis.severity == "critical"


class TestLLMFallback:
    """LLM fallback — 결정론 매처 fail 시."""

    def test_unknown_pattern_no_llm_returns_fallback(self):
        """LLM 미제공 + 결정론 매치 실패 → unknown fallback."""
        rt = _make_runtime_result(stderr="some unfamiliar error format XYZ")
        analysis = analyze_runtime_failure(rt, llm_call=None)
        assert "unknown" in analysis.root_cause.lower()
        assert analysis.confidence < 0.5
        assert analysis.analysis_method == "rule"

    def test_unknown_pattern_with_llm_uses_llm(self):
        """LLM 제공 + 결정론 매치 실패 → LLM 호출."""

        def mock_llm(prompt: str) -> str:
            return '{"root_cause": "LLM 분석 결과 X", "recommended_fix": "do Y", "severity": "high"}'

        rt = _make_runtime_result(stderr="some unfamiliar error format XYZ")
        analysis = analyze_runtime_failure(rt, llm_call=mock_llm)
        assert "LLM 분석 결과 X" in analysis.root_cause
        assert "do Y" in analysis.recommended_fix
        assert analysis.analysis_method == "llm"
        assert analysis.confidence > 0.5

    def test_llm_json_parse_fail_returns_fallback(self):
        """LLM 응답 JSON parse 실패 → unknown fallback."""

        def bad_llm(prompt: str) -> str:
            return "not valid json"

        rt = _make_runtime_result(stderr="some unfamiliar error")
        analysis = analyze_runtime_failure(rt, llm_call=bad_llm)
        assert analysis.analysis_method == "rule"
        assert "unknown" in analysis.root_cause.lower()
