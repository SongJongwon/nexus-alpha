# -*- coding: utf-8 -*-
"""P16 하네스 신뢰성 하드닝 회귀 test (v13 Phase 6.E — HARNESS_AUDIT P1 처방).

P0~P15 를 보존하고 *추가 보강만* 한 4개 수정의 회귀 차단:

수정1a — ``retry_task_if_short`` 코드-추출 인지형 가드(``code_measure``):
    HARNESS_AUDIT 근본원인 = 단축 가드가 ``GUICodeOutput.to_markdown()`` *총길이*(산문 필드
    포함)를 재 "충분히 김" 으로 통과시킴 → code_blocks 가 비어 추출 코드 0 인데도 재시도 미발동.
    ``code_measure`` 가 주어지면 산문 길이 무시, *추출 가능한 실제 코드* 길이로 판정.

수정1b — degenerate→regenerate 액추에이터(``_maybe_regenerate_on_degenerate``):
    ``_is_degenerate_codegen`` 발동 지점에서 *우회 이전에* 코더를 '실제 코드 출력' 지시로
    N회 재호출 + 재추출. P14 감지 + P15 선택은 유지 — 재생성을 우회 전에 끼워넣음.
    pytest 환경은 no-op (FakeProvider 경로 보호 — drift 재생성과 동일 관례).

수정2 — ``compiled.invoke`` 예외 → 구조화 LoopOutcome:
    GraphRecursionError 등 그래프 실행 예외를 try/except 로 잡아 verdict=BLOCKED(INTERNAL_ERROR)
    + ``crash_reason`` 에 예외 타입/메시지 보존. 크래시를 COMPLETE 로 오보하지 않음(2026-05-29
    크래시 회귀 차단). 정상 BLOCKED 와 구분(전용 cause).

수정3 — 다중 iteration loop-back E2E (결정적 mock):
    iter1 degenerate/incomplete → must_fix>0 IMPROVE → 루프백 → iter2 정상 → COMPLETE.
    ≥2 iter 주행 + loop-back 발동 + P15 best-iteration 이 좋은 iter 채택 검증.

수정4 — vision_qa/qa_feedback_loop target-aware:
    web 타깃 → vision_qa(gui)·stdin 기반 도구 *우아하게 SKIP*(FAIL 아님) → qa_feedback_loop 가
    데스크탑 .exe 로 retry-rebuild 하지 않음. web 산출 보존. desktop 동작 불변.

절대 보존: Track A/B 라우팅, desktop(.exe/PyInstaller) 경로, python-only 제약,
convergence_judge 도메인 게이트(P14), request-anchoring(P14), best-iteration(P15) — 회귀 0.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from crewai import Task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level.convergence_judge import (  # noqa: E402
    BlockedCause,
    GapReport,
    Verdict,
)
from src.workflows import iterative_loop as IL  # noqa: E402
from src.workflows._common import (  # noqa: E402
    SUSPICIOUS_OUTPUT_THRESHOLD,
    retry_task_if_short,
    task_output_text,
)
from src.workflows.analyze_and_implement import (  # noqa: E402
    _build_degenerate_regen_directive,
    _is_degenerate_codegen,
    _maybe_regenerate_on_degenerate,
)
from src.workflows.iterative_loop import (  # noqa: E402
    LoopOutcome,
    _format_blocked_partial_hint,
    run_iterative_loop,
)
from src.workflows.qa_feedback_loop import (  # noqa: E402
    _WEB_CONTENT_MARKERS,
    _WEB_TARGET_EXTS,
    _classify_skipped,
    detect_artifact_category,
    evaluate_qa_results,
)


# ---------------------------------------------------------------------------
# 테스트 유틸 — 실제 Task + duck-typed output (test_workflow_common 패턴 재사용)
# ---------------------------------------------------------------------------
class _StubOutput:
    def __init__(self, raw: str) -> None:
        self.raw = raw

        class _Agent:
            role = "p16-agent"

        self.agent = _Agent()


def _make_task() -> Task:
    return Task(description="p16 test task", expected_output="anything")


def _set_output(task: Task, raw: str) -> None:
    object.__setattr__(task, "output", _StubOutput(raw))


# =============================================================================
# 수정1a — retry_task_if_short code_measure (코드-추출 인지형 단축 가드)
# =============================================================================
class TestS1aCodeMeasure:
    """긴 산문 + 빈 코드(추출 0) 케이스를 단축 가드가 잡도록 — HARNESS_AUDIT 근본원인."""

    def test_long_prose_zero_code_triggers_retry(self) -> None:
        """raw 가 임계 초과(산문 길음)지만 code_measure=0(추출 코드 없음) → 재시도 발동.

        기존(총길이 기준)이라면 통과했을 degenerate 산출을 code_measure 가 잡아냄.
        """
        task = _make_task()
        _set_output(task, "설명 산문 " * 40)  # >> 120 chars 이지만 추출 코드는 0

        attempts = [0]

        def fake_kickoff(retry_task: Task) -> None:
            attempts[0] += 1
            # 재시도는 *실제 코드*(추출 길이 큼) 반환
            _set_output(retry_task, "real fenced code body")

        # code_measure: 첫 raw 는 0, 재시도 raw 는 충분히 큼
        def code_measure(raw: str) -> int:
            return 0 if "설명 산문" in raw else 999

        result = retry_task_if_short(task, fake_kickoff, max_retries=1, code_measure=code_measure)
        assert result is True
        assert attempts[0] == 1

    def test_long_prose_zero_code_without_measure_does_not_retry(self) -> None:
        """code_measure 없으면(기존 동작) 같은 긴 산문이 통과 → 재시도 안 함 (회귀 0 증명)."""
        task = _make_task()
        _set_output(task, "설명 산문 " * 40)  # 총길이 >> 120

        calls: list[Task] = []

        def fake_kickoff(retry_task: Task) -> None:
            calls.append(retry_task)

        result = retry_task_if_short(task, fake_kickoff)  # code_measure 미지정
        assert result is False
        assert calls == []

    def test_real_code_with_measure_no_retry(self) -> None:
        """code_measure 가 충분한 코드 길이를 반환하면 재시도 안 함 (정상 산출)."""
        task = _make_task()
        _set_output(task, "x = 1\n" * 50)

        calls: list[Task] = []

        def fake_kickoff(retry_task: Task) -> None:
            calls.append(retry_task)

        result = retry_task_if_short(
            task, fake_kickoff, code_measure=lambda raw: SUSPICIOUS_OUTPUT_THRESHOLD + 500
        )
        assert result is False
        assert calls == []

    def test_measure_keyword_only(self) -> None:
        """code_measure 는 keyword-only — 시그니처 회귀 차단."""
        import inspect

        sig = inspect.signature(retry_task_if_short)
        assert "code_measure" in sig.parameters
        assert sig.parameters["code_measure"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["code_measure"].default is None

    def test_measure_retry_uses_extracted_length_not_total(self) -> None:
        """재시도 산출이 *산문만 길고 코드 0* 이면 여전히 단축 → 교체 안 함 (방어선 유지)."""
        task = _make_task()
        _set_output(task, "초기 산문 " * 30)

        def fake_kickoff(retry_task: Task) -> None:
            _set_output(retry_task, "재시도도 산문만 " * 30)  # 총길이 큼, 코드 0

        result = retry_task_if_short(
            task, fake_kickoff, max_retries=2, code_measure=lambda raw: 0
        )
        assert result is False  # 추출 코드 0 유지 → 교체 안 함


# =============================================================================
# 수정1b — _maybe_regenerate_on_degenerate + 재생성 directive
# =============================================================================
class TestS1bDegenerateRegenerate:
    def test_directive_demands_real_code(self) -> None:
        """재생성 directive 가 '산문 말고 실제 코드를 fenced block 으로' 를 명시."""
        d = _build_degenerate_regen_directive()
        assert "재생성 directive (P16)" in d
        assert "코드를 내세요" in d
        assert "fenced" in d
        # web entry/manifest 도 명시 (web degenerate 복구 유도)
        assert "package.json" in d and "index.html" in d
        # file 헤더 마커 강조
        assert "file:" in d

    def test_regenerate_is_noop_under_pytest(self, tmp_path: Path) -> None:
        """pytest 환경 no-op — degenerate 여도 실 Crew 미호출, 입력 그대로 반환 (FakeProvider 보호)."""
        tiny = tmp_path / "block01.py"
        tiny.write_text("x=1\n", encoding="utf-8")
        code_paths = [tiny]
        # 사전조건: 실제로 degenerate 로 판정되는 입력
        assert _is_degenerate_codegen(code_paths, "web") is True

        out, paths = _maybe_regenerate_on_degenerate(
            "원본 산출",
            code_paths,
            code_gen_task=_make_task(),
            coder=SimpleNamespace(),  # pytest no-op 이라 미사용
            context_tasks=[],
            workflow_dir=tmp_path,
            platform_intent="web",
            verbose=False,
        )
        assert out == "원본 산출"
        assert paths == code_paths  # 변경 없음 (no-op)

    def test_regenerate_noop_when_not_degenerate(self, tmp_path: Path) -> None:
        """정상(non-degenerate) 산출이면 무조건 no-op — 회귀 0."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        idx = code_dir / "index.html"
        idx.write_text("<!doctype html><html><body></body></html>\n" * 8, encoding="utf-8")
        pkg = code_dir / "package.json"
        pkg.write_text('{"name":"x","scripts":{"build":"vite build"}}\n', encoding="utf-8")
        main = code_dir / "main.ts"
        main.write_text("import * as THREE from 'three';\n" * 20, encoding="utf-8")
        code_paths = [idx, pkg, main]
        assert _is_degenerate_codegen(code_paths, "web") is False

        out, paths = _maybe_regenerate_on_degenerate(
            "정상 산출",
            code_paths,
            code_gen_task=_make_task(),
            coder=SimpleNamespace(),
            context_tasks=[],
            workflow_dir=tmp_path,
            platform_intent="web",
            verbose=False,
        )
        assert out == "정상 산출"
        assert paths == code_paths

    def test_is_degenerate_detects_short_and_missing_entry(self, tmp_path: Path) -> None:
        """_is_degenerate_codegen — 단축/web entry 부재 모두 degenerate (P14 재사용 무결성)."""
        # 빈 코드 → degenerate
        assert _is_degenerate_codegen([], "web") is True
        # 단축 .py → degenerate
        f = tmp_path / "block01.py"
        f.write_text("x=1\n", encoding="utf-8")
        assert _is_degenerate_codegen([f], "unspecified") is True
        # web 인데 큰 .ts 만 있고 index.html/package.json 부재 → degenerate
        big = tmp_path / "main.ts"
        big.write_text("import x from 'three';\n" * 40, encoding="utf-8")
        assert _is_degenerate_codegen([big], "web") is True


# =============================================================================
# 수정2 — compiled.invoke 예외 → BLOCKED(INTERNAL_ERROR) + crash_reason
# =============================================================================
class _BoomGraph:
    """compiled graph 흉내 — invoke() 가 항상 raise."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def invoke(self, *_a, **_kw):  # noqa: ANN002, ANN003
        raise self._exc


class TestS2CrashToStructuredOutcome:
    def test_graph_crash_becomes_blocked_internal_error(self, tmp_path: Path, monkeypatch) -> None:
        """invoke 예외 → COMPLETE 오보 없이 BLOCKED(INTERNAL_ERROR) 구조화 결과."""

        class _FakeRecursionError(RuntimeError):
            pass

        monkeypatch.setattr(
            IL, "build_iterative_loop_graph",
            lambda: _BoomGraph(_FakeRecursionError("recursion_limit 60 exceeded")),
        )
        outcome = run_iterative_loop("크래시 유발 요청", outputs_dir=tmp_path, max_iterations=3)

        assert isinstance(outcome, LoopOutcome)
        assert outcome.verdict == Verdict.BLOCKED
        assert outcome.verdict != Verdict.COMPLETE  # 절대 COMPLETE 오보 금지
        assert outcome.blocked_cause == BlockedCause.INTERNAL_ERROR
        assert outcome.iterations_run == 0
        assert outcome.final_chain_result is None

    def test_crash_reason_preserves_exception_type_and_message(self, tmp_path: Path, monkeypatch) -> None:
        """crash_reason 에 예외 타입명 + 메시지 보존 (디버깅 surface)."""
        monkeypatch.setattr(
            IL, "build_iterative_loop_graph",
            lambda: _BoomGraph(ValueError("boom-detail-xyz")),
        )
        outcome = run_iterative_loop("크래시", outputs_dir=tmp_path)
        assert outcome.crash_reason is not None
        assert "ValueError" in outcome.crash_reason
        assert "boom-detail-xyz" in outcome.crash_reason

    def test_internal_error_distinct_from_normal_blocked(self, tmp_path: Path, monkeypatch) -> None:
        """INTERNAL_ERROR 는 BUILD_FAILED/ITERATION_CAP 등 정상 BLOCKED 사유와 구분."""
        monkeypatch.setattr(
            IL, "build_iterative_loop_graph",
            lambda: _BoomGraph(RuntimeError("x")),
        )
        outcome = run_iterative_loop("크래시", outputs_dir=tmp_path)
        assert outcome.blocked_cause == BlockedCause.INTERNAL_ERROR
        assert outcome.blocked_cause not in (
            BlockedCause.BUILD_FAILED,
            BlockedCause.ITERATION_CAP,
            BlockedCause.STAGNATION,
            BlockedCause.BUDGET_EXHAUSTED,
            BlockedCause.FAKE_PACKAGE,
        )

    def test_internal_error_has_partial_hint(self) -> None:
        """결과 패널 hint 가 INTERNAL_ERROR 전용 안내(crash_reason 확인) 제공."""
        hint = _format_blocked_partial_hint(BlockedCause.INTERNAL_ERROR)
        assert hint  # 비어있지 않음
        assert "내부 오류" in hint
        assert "crash_reason" in hint

    def test_normal_completion_still_works(self, tmp_path: Path) -> None:
        """try/except 가 정상 경로를 방해하지 않음 — FakeProvider 1-iter COMPLETE 회귀 0."""
        outcome = run_iterative_loop("정상 단순 요청", outputs_dir=tmp_path, max_iterations=3)
        assert outcome.verdict == Verdict.COMPLETE
        assert outcome.blocked_cause == BlockedCause.NONE
        assert outcome.crash_reason is None


# =============================================================================
# 수정3 — 다중 iteration loop-back E2E (결정적 mock, ≥2 iter + P15 best-iteration)
# =============================================================================
class TestS3LoopBackE2E:
    """노드를 결정적 stub 으로 교체, judge/router/best-iteration 은 *실제* 로직 사용.

    iter1 degenerate(must_fix>0) → IMPROVE → 루프백 → iter2 정상(build_ok) → COMPLETE.
    """

    @staticmethod
    def _install_stubs(monkeypatch, tmp_path: Path) -> dict:
        chains: dict[int, SimpleNamespace] = {}

        def _degenerate_chain(it: int) -> SimpleNamespace:
            d = tmp_path / f"iter{it}_code"
            d.mkdir(parents=True, exist_ok=True)
            f = d / "block01.py"
            f.write_text("x=1\n", encoding="utf-8")  # 단축 → degenerate
            return SimpleNamespace(
                saved_code_files=[f], executor_result=None, saved_dir=d,
                engineer_output="degenerate stub", qa_review="",
            )

        def _valid_web_chain(it: int) -> SimpleNamespace:
            d = tmp_path / f"iter{it}_code"
            d.mkdir(parents=True, exist_ok=True)
            idx = d / "index.html"
            idx.write_text("<!doctype html><html></html>\n" * 8, encoding="utf-8")
            pkg = d / "package.json"
            pkg.write_text('{"name":"app","scripts":{"build":"vite build"}}\n', encoding="utf-8")
            main = d / "main.ts"
            main.write_text("import * as THREE from 'three';\n" * 30, encoding="utf-8")
            exe = d / "dist" / "index.html"
            return SimpleNamespace(
                saved_code_files=[idx, pkg, main],
                executor_result=SimpleNamespace(success=True, exit_code=0, exe_path=exe),
                saved_dir=d, engineer_output="real web code", qa_review="ok",
            )

        def fake_run_chain(state):
            next_iter = state["iteration"] + 1
            chain = _degenerate_chain(next_iter) if next_iter == 1 else _valid_web_chain(next_iter)
            chains[next_iter] = chain
            artifacts = list(state.get("iteration_artifacts", []))
            artifacts.append(chain.saved_dir.as_posix())
            return {
                "iteration": next_iter,
                "chain_result": chain,
                "iteration_artifacts": artifacts,
                "execution_result": None,
            }

        def fake_analyze_gap(state):
            it = state["iteration"]
            if it == 1:
                gap = GapReport(satisfied_count=1, unsatisfied_blockers=1, iteration=1)
            else:
                gap = GapReport(satisfied_count=3, unsatisfied_blockers=0, iteration=it)
            return {
                "gap_report": gap,
                "gap_report_raw": f"iter{it} gap",
                "satisfied_history": list(state.get("satisfied_history", [])) + [gap.satisfied_count],
            }

        def fake_expand(state):
            # 실제 _node_expand_requirements 와 동일한 초기화 키 set (iteration=0 등).
            return {
                "spec_markdown": "stub spec",
                "iteration": 0,
                "feedback": "",
                "satisfied_history": [],
                "feedback_history": [],
                "iteration_artifacts": [],
                "gap_report_raw": "",
                "platform_intent": "web",
                "domain_checklist": None,  # 도메인 게이트(Rule 0) 미발동 — must_fix 로 루프 구동
            }

        # 무거운/LLM 노드 → 결정적 stub. judge/router/prepare_feedback/finalize/escalate 는 실제.
        monkeypatch.setattr(IL, "_node_expand_requirements", fake_expand)
        monkeypatch.setattr(IL, "_node_recall_past_knowledge", lambda s: {})
        monkeypatch.setattr(IL, "_node_kickoff_meeting", lambda s: {})
        monkeypatch.setattr(IL, "_node_run_chain", fake_run_chain)
        monkeypatch.setattr(IL, "_node_tech_scout", lambda s: {})
        monkeypatch.setattr(IL, "_node_run_sandbox", lambda s: {"execution_result": None})
        monkeypatch.setattr(IL, "_node_runtime_verify", lambda s: {})
        monkeypatch.setattr(IL, "_node_analyze_gap", fake_analyze_gap)
        monkeypatch.setattr(IL, "_node_retrospective", lambda s: {})
        monkeypatch.setattr(IL, "_node_curate_knowledge", lambda s: {})
        return chains

    def test_runs_at_least_two_iterations(self, tmp_path: Path, monkeypatch) -> None:
        self._install_stubs(monkeypatch, tmp_path)
        outcome = run_iterative_loop("loop-back 요청", outputs_dir=tmp_path, max_iterations=3)
        assert outcome.iterations_run == 2, (
            f"iter1 degenerate→IMPROVE→루프백→iter2 정상→COMPLETE 로 정확히 2 iter 여야 함. "
            f"실제: {outcome.iterations_run}"
        )

    def test_loop_back_fired(self, tmp_path: Path, monkeypatch) -> None:
        """루프백 발동 = iter1 의 prepare_feedback 가 feedback 1건 누적."""
        self._install_stubs(monkeypatch, tmp_path)
        outcome = run_iterative_loop("loop-back 요청", outputs_dir=tmp_path, max_iterations=3)
        assert len(outcome.feedback_history) == 1
        # 2개 iteration artifact (iter1 + iter2)
        assert len(outcome.iteration_artifacts) == 2

    def test_completes_with_best_iteration_output(self, tmp_path: Path, monkeypatch) -> None:
        """종단 verdict=COMPLETE, P15 가 정상 iter2(빌드 성공) 산출을 최종 채택."""
        chains = self._install_stubs(monkeypatch, tmp_path)
        outcome = run_iterative_loop("loop-back 요청", outputs_dir=tmp_path, max_iterations=3)
        assert outcome.verdict == Verdict.COMPLETE
        assert outcome.blocked_cause == BlockedCause.NONE
        # 최종 산출 = iter2 의 유효 web chain (iter1 degenerate 아님)
        assert outcome.final_chain_result is chains[2]
        # best-iteration 채택 흔적
        assert "BEST_ITERATION_ADOPTED" in outcome.final_decision.reason


# =============================================================================
# 수정4 — detect_artifact_category web + _classify_skipped web SKIP
# =============================================================================
class TestS4WebTargetAware:
    def test_web_suffix_detected_as_web(self, tmp_path: Path) -> None:
        """.ts/.html 등 web 확장자 → 'web' (파일 존재 불필요 — suffix 우선)."""
        assert detect_artifact_category(target_script=tmp_path / "main.ts") == "web"
        assert detect_artifact_category(target_script=tmp_path / "index.html") == "web"
        assert detect_artifact_category(target_script=Path("app.tsx")) == "web"

    def test_web_content_marker_detected_as_web(self, tmp_path: Path) -> None:
        """web 확장자 아니어도 내용 마커(three.js/doctype 등) → 'web'."""
        f = tmp_path / "bundle.dat"  # 비-web 확장자
        f.write_text("<!DOCTYPE html>\n<html></html>\n", encoding="utf-8")
        assert detect_artifact_category(target_script=f) == "web"

    def test_web_exts_and_markers_present(self) -> None:
        """상수 무결성 — 핵심 web 마커 포함."""
        assert ".ts" in _WEB_TARGET_EXTS and ".html" in _WEB_TARGET_EXTS
        assert any("three" in m for m in _WEB_CONTENT_MARKERS)
        assert any("doctype" in m for m in _WEB_CONTENT_MARKERS)

    def test_desktop_gui_still_detected(self, tmp_path: Path) -> None:
        """데스크탑 GUI(.py + tkinter) 는 여전히 'gui' — 회귀 0."""
        f = tmp_path / "app.py"
        f.write_text("import tkinter\nroot = tkinter.Tk()\n", encoding="utf-8")
        assert detect_artifact_category(target_script=f) == "gui"

    def test_cli_still_detected(self, tmp_path: Path) -> None:
        """CLI(.py + argparse) 는 여전히 'cli' — 회귀 0."""
        f = tmp_path / "tool.py"
        f.write_text("import argparse\nargparse.ArgumentParser()\n", encoding="utf-8")
        assert detect_artifact_category(target_script=f) == "cli"

    def test_classify_skipped_web_skips_vision_and_stdin_tools(self) -> None:
        """web 카테고리 → gui(vision)/functional/robustness 모두 SKIP (FAIL 아님)."""
        for tool in ("gui", "functional", "robustness"):
            is_skipped, msg = _classify_skipped(tool, SimpleNamespace(success=False), "web")
            assert is_skipped is True, f"{tool} 미스킵 — P16 수정4 회귀"
            assert msg is not None and "web" in msg

    def test_classify_skipped_web_does_not_skip_code_qa(self) -> None:
        """code_qa 는 web 에서도 스킵 안 함 (pytest 실행은 web 산출과 무관 — 회귀 0)."""
        is_skipped, _ = _classify_skipped("code_qa", SimpleNamespace(success=True), "web")
        assert is_skipped is False

    def test_gui_category_unchanged(self) -> None:
        """데스크탑 gui 카테고리 동작 불변 — functional/robustness 만 스킵, gui 자체는 평가."""
        # functional/robustness → 기존대로 스킵
        is_skipped, _ = _classify_skipped("functional", SimpleNamespace(success=False), "gui")
        assert is_skipped is True
        # gui 도구 자체는 desktop 에서 스킵 안 함 (vision_qa 가 .exe 스크린샷 = 의미 있음)
        is_skipped_gui, _ = _classify_skipped("gui", SimpleNamespace(success=False), "gui")
        assert is_skipped_gui is False

    def test_web_failing_vision_does_not_trigger_retry(self) -> None:
        """⭐ 핵심 회귀: web 타깃 + vision 실패여도 retry-rebuild 미발동 (web 산출 보존)."""
        results = {
            "gui": SimpleNamespace(success=False, summary_line=lambda: "screenshots=0"),
            "code_qa": SimpleNamespace(success=True, summary_line=lambda: "pass"),
        }
        decision = evaluate_qa_results(results, retry_count=0, max_retries=3, artifact_category="web")
        assert "gui" in decision.skipped_qa_tools
        assert decision.overall_passed is True  # 실패한 gui 가 스킵 → 다른 도구만 평가
        assert decision.should_retry is False  # ★ retry 미발동

    def test_desktop_failing_vision_still_triggers_retry(self) -> None:
        """대비: 데스크탑 gui 타깃 + vision 실패 → 여전히 retry (desktop 동작 불변)."""
        results = {
            "gui": SimpleNamespace(success=False, summary_line=lambda: "screenshots=0"),
        }
        decision = evaluate_qa_results(results, retry_count=0, max_retries=3, artifact_category="gui")
        assert "gui" in decision.failed_qa_tools
        assert decision.overall_passed is False
        assert decision.should_retry is True  # desktop 은 retry 발동
