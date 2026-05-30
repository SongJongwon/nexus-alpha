# -*- coding: utf-8 -*-
"""P3 GUI 플랫폼 드리프트 즉시 reject+재생성 회귀 test (v13 Phase 6.E).

출처: ``docs/diagnostics/phase6e_rerun_P7_verdict_20260530.md`` (진범=P3) + 설계 보고.

배경:
    동일 web 안건인데 GUI Code Generator 가 런마다 PyQt 데스크탑으로 확률적 드리프트
    (P7 verdict: web 4/5 → 1/5). 기존 P1 PLATFORM_DRIFT 는 judge 단계(post-iteration)
    라 IMPROVE 1라운드 소모. P3 는 gui_code 생성 *직후* 같은 iteration 안에서
    detect_desktop_markers(P1 재사용) 로 즉시 reject → 코더 task 만 N회 hardened-
    directive 재생성 (iter 카운터 불변). 소진 시 기존 judge 백스톱.

검증:
    P3-T1. web + 데스크탑 마커 → 재생성 트리거 (in-iteration, 카운터 개념 없음).
    P3-T2. web + clean Three.js → pass-through (재생성 0회).
    P3-T3. desktop + PyQt → no-op (회귀 0).
    P3-T4. unspecified(+default) + PyQt → no-op (회귀 0).
    P3-T5. N 소진 → bounded·예외 없음·fall-through + judge PLATFORM_DRIFT 백스톱 유지.
    P3-T6. 재생성/예방 directive 에 날조 거부 + Three.js + schema 사실 문구 포함.
    P3-T7. pytest 중 production 래퍼 = no-op (실 Crew 미호출).
    P3-T8. 배선 backward-compat — platform_intent default "unspecified" (기존 호출 불변).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level.convergence_judge import (
    GapReport,
    Verdict,
    detect_desktop_markers,
)
from src.workflows.analyze_and_implement import (
    _P3_MAX_DRIFT_RETRIES,
    _build_drift_regen_directive,
    _build_gui_code_gen_task,
    _build_web_platform_directive,
    _maybe_regenerate_on_platform_drift,
    _regenerate_until_clean,
    _run_gui_branch_chain,
    _should_regenerate_for_drift,
    run_analyze_and_implement,
)
from src.agents.c_level.convergence_judge import judge_convergence

_PYQT_OUTPUT = (
    "# file: app.py\nimport sys\nfrom PyQt6.QtWidgets import QApplication, QMainWindow\n"
    "class MainWindow(QMainWindow): ...\napp = QApplication(sys.argv)"
)
_THREEJS_OUTPUT = (
    "// file: src/viewer.ts\nimport * as THREE from 'three';\n"
    "import { IFCLoader } from 'web-ifc-three/IFCLoader';\n"
    "const renderer = new THREE.WebGLRenderer();"
)


# =============================================================================
# P3-T1. web + 데스크탑 마커 → 재생성 트리거 (in-iteration, 카운터 불변)
# =============================================================================
class TestT1RegenerateTriggered:
    def test_predicate_true_for_web_with_pyqt(self) -> None:
        assert _should_regenerate_for_drift("web", _PYQT_OUTPUT) is True

    def test_regenerate_flips_to_clean(self) -> None:
        calls: list[int] = []

        def _regen(markers, attempt):
            calls.append(attempt)
            # 1차 재생성에서 clean web 산출로 교정
            return _THREEJS_OUTPUT

        out, attempts = _regenerate_until_clean(
            _PYQT_OUTPUT, platform_intent="web", regen_fn=_regen
        )
        assert out == _THREEJS_OUTPUT
        assert attempts == 1
        assert calls == [1]  # 정확히 1회 재생성

    def test_loop_owns_no_iteration_counter(self) -> None:
        """카운터 불변 보장의 구조적 증거 — 재생성 루프는 iteration 파라미터가 없다.

        iteration 카운터는 상위 ``_node_run_chain`` 소유(state['iteration']+1).
        본 루프는 단일 iteration 내부에 중첩되어 loop-back 엣지를 넘지 않으므로
        카운터를 만질 수 없다. 시그니처에 'iteration' 키워드가 없음을 박제.
        """
        params = inspect.signature(_regenerate_until_clean).parameters
        assert "iteration" not in params
        assert "max_retries" in params  # 재생성 상한은 iteration 과 무관한 별도 축


# =============================================================================
# P3-T2. web + clean Three.js → pass-through (재생성 0회)
# =============================================================================
class TestT2CleanPassThrough:
    def test_predicate_false_for_clean_web(self) -> None:
        assert _should_regenerate_for_drift("web", _THREEJS_OUTPUT) is False

    def test_no_regeneration_when_clean(self) -> None:
        calls: list[int] = []

        def _regen(markers, attempt):
            calls.append(attempt)
            return _PYQT_OUTPUT  # 호출되면 안 됨

        out, attempts = _regenerate_until_clean(
            _THREEJS_OUTPUT, platform_intent="web", regen_fn=_regen
        )
        assert out == _THREEJS_OUTPUT  # 입력 그대로
        assert attempts == 0
        assert calls == []  # 재생성 미호출


# =============================================================================
# P3-T3. desktop + PyQt → no-op (회귀 0)
# =============================================================================
class TestT3DesktopNoOp:
    def test_predicate_false_for_desktop(self) -> None:
        assert _should_regenerate_for_drift("desktop", _PYQT_OUTPUT) is False

    def test_desktop_pyqt_passes_through_unchanged(self) -> None:
        called = {"n": 0}

        def _regen(markers, attempt):
            called["n"] += 1
            return _THREEJS_OUTPUT

        out, attempts = _regenerate_until_clean(
            _PYQT_OUTPUT, platform_intent="desktop", regen_fn=_regen
        )
        assert out == _PYQT_OUTPUT  # PyQt 그대로 허용
        assert attempts == 0
        assert called["n"] == 0


# =============================================================================
# P3-T4. unspecified(+default) + PyQt → no-op (회귀 0)
# =============================================================================
class TestT4UnspecifiedNoOp:
    def test_predicate_false_for_unspecified(self) -> None:
        assert _should_regenerate_for_drift("unspecified", _PYQT_OUTPUT) is False

    def test_unspecified_passes_through_unchanged(self) -> None:
        out, attempts = _regenerate_until_clean(
            _PYQT_OUTPUT, platform_intent="unspecified", regen_fn=lambda m, a: _THREEJS_OUTPUT
        )
        assert out == _PYQT_OUTPUT
        assert attempts == 0


# =============================================================================
# P3-T5. N 소진 → bounded·예외 없음·fall-through + judge PLATFORM_DRIFT 백스톱
# =============================================================================
class TestT5ExhaustionFallThrough:
    def test_persistent_drift_bounded_by_max_retries(self) -> None:
        calls: list[int] = []

        def _regen(markers, attempt):
            calls.append(attempt)
            return _PYQT_OUTPUT  # 영구 드리프트 — 절대 clean 안 됨

        out, attempts = _regenerate_until_clean(
            _PYQT_OUTPUT, platform_intent="web", regen_fn=_regen
        )
        # 소진: 정확히 _P3_MAX_DRIFT_RETRIES 회 재생성, 예외 없음, 마지막 산출 반환
        assert attempts == _P3_MAX_DRIFT_RETRIES
        assert calls == list(range(1, _P3_MAX_DRIFT_RETRIES + 1))
        assert out == _PYQT_OUTPUT  # fall-through (여전히 드리프트)

    def test_judge_backstop_still_fires_after_exhaustion(self) -> None:
        """소진 후 fall-through 한 드리프트는 기존 judge PLATFORM_DRIFT(P1)가 잡는다."""
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=1),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.platform_drift is True


# =============================================================================
# P3-T6. directive 문구 — 날조 거부 + Three.js + schema 사실
# =============================================================================
class TestT6DirectiveContent:
    def test_regen_directive_rejects_fabrication(self) -> None:
        directive = _build_drift_regen_directive(["qapplication", "qmainwindow"])
        assert "Three.js" in directive
        assert "금지" in directive
        assert "날조" in directive  # 근거 날조 거부
        assert "사용자가" in directive  # "사용자가 PyQt 지정" 류 거부
        assert "code_blocks" in directive and "자유 형식" in directive  # schema 사실
        assert "qapplication" in directive  # 검출된 마커 preview 포함

    def test_preventive_directive_has_same_guards(self) -> None:
        directive = _build_web_platform_directive()
        assert "Three.js" in directive
        assert "금지" in directive
        assert "날조" in directive
        # 완전 web 프로젝트 강제 — index.html + package.json
        assert "index.html" in directive
        assert "package.json" in directive


# =============================================================================
# P3-T7. pytest 중 production 래퍼 = no-op (실 Crew 미호출)
# =============================================================================
class TestT7PytestNoOp:
    def test_wrapper_is_noop_under_pytest(self) -> None:
        # pytest 환경(현재)에선 web 의도 + PyQt 여도 즉시 입력 반환 — Crew 미생성.
        # code_gen_task 자리에 더미를 넘겨도 건드리지 않음(early-return 보장).
        dummy_task = SimpleNamespace(description="x", expected_output="y")
        out = _maybe_regenerate_on_platform_drift(
            _PYQT_OUTPUT,
            code_gen_task=dummy_task,
            coder=None,
            context_tasks=[],
            platform_intent="web",
            verbose=False,
        )
        assert out == _PYQT_OUTPUT  # 변경 0 (Crew 미호출)

    def test_wrapper_noop_for_non_web_even_outside_guard(self) -> None:
        dummy_task = SimpleNamespace(description="x", expected_output="y")
        out = _maybe_regenerate_on_platform_drift(
            _PYQT_OUTPUT,
            code_gen_task=dummy_task,
            coder=None,
            context_tasks=[],
            platform_intent="desktop",
            verbose=False,
        )
        assert out == _PYQT_OUTPUT


# =============================================================================
# P3-T8. 배선 backward-compat — platform_intent default "unspecified"
# =============================================================================
class TestT8PlumbingBackwardCompat:
    def test_run_analyze_and_implement_default(self) -> None:
        sig = inspect.signature(run_analyze_and_implement)
        assert sig.parameters["platform_intent"].default == "unspecified"

    def test_run_gui_branch_chain_default(self) -> None:
        sig = inspect.signature(_run_gui_branch_chain)
        assert sig.parameters["platform_intent"].default == "unspecified"

    def test_build_gui_code_gen_task_default(self) -> None:
        sig = inspect.signature(_build_gui_code_gen_task)
        assert sig.parameters["platform_intent"].default == "unspecified"

    def test_detect_markers_reused_not_adhoc(self) -> None:
        """마커 검출은 기존 detect_desktop_markers 재사용 (새 ad-hoc substring 금지)."""
        assert _should_regenerate_for_drift("web", _PYQT_OUTPUT) == bool(
            detect_desktop_markers(_PYQT_OUTPUT)
        )
