# -*- coding: utf-8 -*-
"""P1 플랫폼 드리프트 가드레일 회귀 test (PR #235).

출처: ``docs/diagnostics/phase6e_rerun_crash_analysis_20260529.md`` §7 P1

배경:
    재실행에서 "Three.js BIM 뷰어"(web) 요청인데 엔지니어가 7/7 PyQt 데스크탑으로
    드리프트 → Three.js/WebGL 0매칭 → Rule 0 영구 IMPROVE → (P0 가드로) BLOCKED.
    P0 는 *종료* 만 보장. P1 은 *실제로 web/Three.js 로 수렴* 하게 만든다 (옵션 3:
    예방 + 탐지 + 매처 플랫폼 인식).

검증:
    P1-T1. _detect_platform — web/desktop/unspecified 분류.
    P1-T2. web 의도 → 엔지니어 프롬프트에 데스크탑 금지 제약 주입.
    P1-T3. web 요청 + 산출 PyQt 마커 → judge PLATFORM_DRIFT IMPROVE + 구체 reason.
    P1-T4. 회귀 0 — desktop/unspecified 면 제약 미주입 + PyQt 허용 (기존 동작 불변).
    P1-T5. P0 호환 — web 미수렴(드리프트) + iter==max → 여전히 BLOCKED(ITERATION_CAP).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import _detect_platform
from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    Verdict,
    detect_desktop_markers,
    judge_convergence,
)
from src.workflows.iterative_loop import _build_platform_constraint


_PYQT_OUTPUT = (
    "# file: app.py\nimport sys\nfrom PyQt6.QtWidgets import QApplication, QMainWindow\n"
    "class MainWindow(QMainWindow): ...\napp = QApplication(sys.argv)"
)
_THREEJS_OUTPUT = (
    "import * as THREE from 'three';\nconst renderer = new THREE.WebGLRenderer();\n"
    "const camera = new THREE.PerspectiveCamera(); // OrbitControls + Vector3"
)


# =============================================================================
# P1-T1. _detect_platform 분류
# =============================================================================
class TestT1DetectPlatform:
    def test_threejs_request_is_web(self) -> None:
        assert _detect_platform("3D BIM 뷰어: Three.js + WebGL 사용") == "web"

    def test_browser_korean_is_web(self) -> None:
        assert _detect_platform("브라우저에서 도는 HTML 대시보드") == "web"

    def test_pyqt_request_is_desktop(self) -> None:
        assert _detect_platform("PyQt 데스크탑 계산기 앱") == "desktop"

    def test_tkinter_is_desktop(self) -> None:
        assert _detect_platform("tkinter 메모장 만들어줘") == "desktop"

    def test_ambiguous_is_unspecified(self) -> None:
        # web/desktop 시그널 모두 없음
        assert _detect_platform("간단한 계산기 만들어줘") == "unspecified"

    def test_both_signals_is_unspecified(self) -> None:
        # web + desktop 둘 다 → 모호 → unspecified (제약 미주입, 회귀 안전)
        assert _detect_platform("Three.js 뷰어를 PyQt 셸에 임베드") == "unspecified"

    def test_empty_is_unspecified(self) -> None:
        assert _detect_platform("") == "unspecified"


# =============================================================================
# P1-T2. web 의도 → 엔지니어 프롬프트 데스크탑 금지 제약 주입
# =============================================================================
class TestT2PlatformConstraintInjection:
    def test_web_injects_desktop_ban(self) -> None:
        constraint = _build_platform_constraint("web")
        assert constraint != ""
        assert "Three.js" in constraint
        assert "PyQt" in constraint
        # 데스크탑 GUI 금지 + Track 기본값보다 우선 명시
        assert "금지" in constraint
        assert "우선" in constraint

    def test_desktop_no_web_constraint(self) -> None:
        """desktop 은 web 드리프트 제약(Three.js/PyQt 금지)을 받지 않는다 (회귀 0).

        단, v13 P25 로 desktop *단일 폼팩터* 계약(콘솔/GUI 혼재 금지)은 가산됨 — 별도 검증.
        """
        c = _build_platform_constraint("desktop")
        assert "Three.js" not in c and "PyQt" not in c  # web 드리프트 제약 아님
        assert "단일 폼팩터" in c and "혼재 금지" in c  # v13 P25 데스크탑 폼팩터 계약

    def test_unspecified_no_constraint(self) -> None:
        assert _build_platform_constraint("unspecified") == ""


# =============================================================================
# P1-T3. web 요청 + 산출 PyQt 마커 → judge PLATFORM_DRIFT IMPROVE + 구체 reason
# =============================================================================
class TestT3JudgePlatformDrift:
    def test_web_with_pyqt_output_yields_platform_drift_improve(self) -> None:
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=1),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.blocked_cause == BlockedCause.NONE
        assert decision.platform_drift is True
        # 구체 reason — 실행 가능 피드백
        assert "PLATFORM_DRIFT" in decision.reason
        assert "Three.js" in decision.next_action

    def test_web_with_threejs_output_no_drift(self) -> None:
        """web + Three.js 산출(데스크탑 마커 0) → PLATFORM_DRIFT 미발동."""
        decision = judge_convergence(
            GapReport(satisfied_count=5, unsatisfied_blockers=0, iteration=1),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt=_THREEJS_OUTPUT,
        )
        assert decision.platform_drift is False
        # 도메인 체크리스트 미주입 + must_fix=0 → COMPLETE (드리프트 아님)
        assert decision.verdict == Verdict.COMPLETE

    def test_detect_desktop_markers_helper(self) -> None:
        markers = detect_desktop_markers(_PYQT_OUTPUT)
        assert "qapplication" in markers
        assert "qmainwindow" in markers
        assert detect_desktop_markers(_THREEJS_OUTPUT) == []
        assert detect_desktop_markers("") == []


# =============================================================================
# P1-T4. 회귀 0 — desktop/unspecified 면 PyQt 허용 (드리프트 미발동)
# =============================================================================
class TestT4RegressionZeroNonWeb:
    def test_desktop_pyqt_no_drift(self) -> None:
        decision = judge_convergence(
            GapReport(satisfied_count=5, unsatisfied_blockers=0, iteration=1),
            max_iterations=5,
            platform_intent="desktop",
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.platform_drift is False
        assert decision.verdict == Verdict.COMPLETE

    def test_unspecified_pyqt_no_drift(self) -> None:
        decision = judge_convergence(
            GapReport(satisfied_count=5, unsatisfied_blockers=0, iteration=1),
            max_iterations=5,
            platform_intent="unspecified",
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.platform_drift is False
        assert decision.verdict == Verdict.COMPLETE

    def test_default_platform_intent_no_drift(self) -> None:
        """platform_intent 미지정(default 'unspecified') → 기존 동작 불변."""
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=2),
            max_iterations=5,
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.platform_drift is False
        assert decision.verdict == Verdict.IMPROVE_NEEDED  # Rule 5


# =============================================================================
# P1-T5. P0 호환 — web 미수렴(드리프트) + iter==max → BLOCKED(ITERATION_CAP)
# =============================================================================
class TestT5P0Compatibility:
    def test_platform_drift_at_cap_blocked(self) -> None:
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=5),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt=_PYQT_OUTPUT,  # 영구 드리프트
        )
        # P0 하드 가드 — IMPROVE(드리프트)도 cap 에서 BLOCKED 로 강제 전환
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP
        # 드리프트 플래그는 cap 종료 후에도 보존
        assert decision.platform_drift is True

    def test_platform_drift_below_cap_still_improves(self) -> None:
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=4),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt=_PYQT_OUTPUT,
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.platform_drift is True
