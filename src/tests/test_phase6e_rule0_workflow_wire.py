# -*- coding: utf-8 -*-
"""v13 Phase 6.E (PR #231) — Rule 0 workflow wire 단위 test.

PM 진단 처방 옵션 A — Phase 6.2 PR #226 의 build_domain_checklist + Rule 0 를
iterative_loop 의 production workflow 에 실제 연결.

검증 범위:
    1. _node_expand_requirements 가 build_domain_checklist 호출 + state 보존
    2. _LoopState 의 domain_checklist 필드 (TypedDict)
    3. _extract_engineer_output_excerpt — saved_dir/code/*.py + .md 합산
    4. _extract_qa_review_excerpt — 04_qa_review.md + 14_pytest_suite.md
    5. _node_judge_convergence 가 Rule 0 인자 3개 전달 (회귀 0)
    6. 회귀 0 보장 — 3D 키워드 없는 user_request → domain_checklist=[] → Rule 0 skip
    7. ⭐ BIM 본질 시나리오 — 3D 요청 + Engineer 산출 키워드 없음 → IMPROVE 강제
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import ChecklistItem, build_domain_checklist
from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    Verdict,
)
from src.workflows.iterative_loop import (
    _extract_engineer_output_excerpt,
    _extract_qa_review_excerpt,
    _node_judge_convergence,
)


# =============================================================================
# 1. _extract_engineer_output_excerpt — saved_dir/code/*.py 발췌
# =============================================================================
class TestExtractEngineerExcerpt:
    def test_none_chain_result_returns_empty(self) -> None:
        assert _extract_engineer_output_excerpt(None) == ""

    def test_no_saved_dir_returns_empty(self) -> None:
        chain = SimpleNamespace(saved_dir=None)
        assert _extract_engineer_output_excerpt(chain) == ""

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        chain = SimpleNamespace(saved_dir=tmp_path / "nope")
        assert _extract_engineer_output_excerpt(chain) == ""

    def test_code_dir_py_files_concatenated(self, tmp_path: Path) -> None:
        """⭐ saved_dir/code/*.py 모두 발췌 — Rule 0 매칭 입력."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "viewport.py").write_text(
            "import OrbitControls\n# PerspectiveCamera",
            encoding="utf-8",
        )
        (code_dir / "app.py").write_text("# entry point", encoding="utf-8")
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _extract_engineer_output_excerpt(chain)
        assert "OrbitControls" in result
        assert "PerspectiveCamera" in result
        assert "viewport.py" in result  # 파일명 헤더
        assert "app.py" in result

    def test_gui_code_output_md_included(self, tmp_path: Path) -> None:
        """Track A GUI 분기 — 13_gui_code_output.md 도 발췌."""
        (tmp_path / "13_gui_code_output.md").write_text(
            "## GUI code\nWebGLRenderer setup", encoding="utf-8"
        )
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _extract_engineer_output_excerpt(chain)
        assert "WebGLRenderer" in result

    def test_max_chars_truncates(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "huge.py").write_text("A" * 100_000, encoding="utf-8")
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _extract_engineer_output_excerpt(chain, max_chars=1000)
        assert len(result) <= 1000


# =============================================================================
# 2. _extract_qa_review_excerpt
# =============================================================================
class TestExtractQAExcerpt:
    def test_qa_review_md_included(self, tmp_path: Path) -> None:
        (tmp_path / "04_qa_review.md").write_text(
            "QA: rotateY verified", encoding="utf-8"
        )
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _extract_qa_review_excerpt(chain)
        assert "rotateY" in result

    def test_no_qa_files_returns_empty(self, tmp_path: Path) -> None:
        chain = SimpleNamespace(saved_dir=tmp_path)
        assert _extract_qa_review_excerpt(chain) == ""

    def test_none_chain_result_returns_empty(self) -> None:
        assert _extract_qa_review_excerpt(None) == ""


# =============================================================================
# 3. _node_expand_requirements 가 domain_checklist 채움 (mock LLM)
# =============================================================================
class TestExpandRequirementsBuildsChecklist:
    """⭐ Phase 6.E ★ — expand_requirements 가 build_domain_checklist 호출."""

    @patch("src.workflows.iterative_loop.create_requirement_expander_agent")
    @patch("src.workflows.iterative_loop.Crew", create=True)
    def test_3d_request_yields_4_item_checklist(
        self, _mock_crew_cls, _mock_factory
    ) -> None:
        """3D BIM 요청 → domain_checklist 5 항목 (3D 도메인 템플릿, P14 scene-render 추가)."""
        # 우회 — 직접 build_domain_checklist 만 호출 (LLM Crew 우회)
        checklist = build_domain_checklist("3D BIM 건축 모델 뷰어")
        assert len(checklist) == 5
        ids = {c.id for c in checklist}
        assert "3d-camera-orbit" in ids
        assert "3d-real-3d-not-isometric" in ids

    def test_non_3d_request_yields_empty_checklist(self) -> None:
        """3D 아닌 요청 → 빈 checklist → Rule 0 skip → 회귀 0."""
        checklist = build_domain_checklist("REST API server")
        assert checklist == []


# =============================================================================
# 4. _node_judge_convergence 에 Rule 0 인자 전달 + 회귀 0
# =============================================================================
class TestJudgeNodeWireRule0:
    def _make_state(self, **overrides: object) -> dict:
        base = {
            "gap_report": GapReport(satisfied_count=5, unsatisfied_blockers=0),
            "max_iterations": 5,
            "budget_tokens_remaining": -1,
            "fake_packages": None,
            "consecutive_fake_iterations": 0,
            "domain_checklist": None,
            "chain_result": None,
        }
        base.update(overrides)
        return base

    def test_default_none_checklist_preserves_complete(self) -> None:
        """⭐ 회귀 0 — domain_checklist=None → Rule 0 skip → Rule 1 COMPLETE."""
        state = self._make_state()
        result = _node_judge_convergence(state)
        assert result["decision"].verdict == Verdict.COMPLETE

    def test_empty_checklist_preserves_complete(self) -> None:
        """⭐ 회귀 0 — domain_checklist=[] → Rule 0 skip → Rule 1 COMPLETE."""
        state = self._make_state(domain_checklist=[])
        result = _node_judge_convergence(state)
        assert result["decision"].verdict == Verdict.COMPLETE

    def test_3d_checklist_with_matching_excerpt_passes(
        self, tmp_path: Path
    ) -> None:
        """3D 체크리스트 + Engineer 산출에 키워드 모두 → Rule 0 통과 → COMPLETE."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        # 5 체크리스트 항목 모두의 detect_keywords 가 포함된 코드 (P14: scene-render-loop 추가)
        (code_dir / "viewport.py").write_text(
            "OrbitControls + rotate + camera.position\n"
            "WebGLRenderer + three.js\n"
            "zoom + pan + reset + wheel + controls.update\n"
            "rotateY + rotation.z + Vector3 + PerspectiveCamera + DirectionalLight\n"
            "new THREE.Scene + renderer.render + scene.add + requestAnimationFrame\n",
            encoding="utf-8",
        )
        chain = SimpleNamespace(saved_dir=tmp_path)
        state = self._make_state(
            domain_checklist=build_domain_checklist("3D BIM 뷰어"),
            chain_result=chain,
        )
        result = _node_judge_convergence(state)
        assert result["decision"].verdict == Verdict.COMPLETE
        assert result["decision"].domain_unsatisfied == []

    def test_3d_checklist_with_empty_excerpt_forces_improve(
        self,
    ) -> None:
        """⭐ BIM 본질 시나리오 — 3D 요청 + chain_result 없음 → 모든 항목 미충족 → IMPROVE."""
        state = self._make_state(
            domain_checklist=build_domain_checklist("3D BIM 뷰어"),
            chain_result=None,
        )
        result = _node_judge_convergence(state)
        assert result["decision"].verdict == Verdict.IMPROVE_NEEDED
        # Rule 0 가 5 항목 모두 미충족 강제 (P14: scene-render-loop 추가)
        assert len(result["decision"].domain_unsatisfied) == 5
        assert "3d-real-3d-not-isometric" in result["decision"].domain_unsatisfied

    def test_3d_checklist_with_isometric_only_forces_improve(
        self, tmp_path: Path
    ) -> None:
        """⭐ BIM 퇴행 시나리오 — Engineer 가 isometric 2D 산출 → Rule 0 IMPROVE 강제."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        # 2D isometric — 4 항목 detect_keywords 모두 없음
        (code_dir / "main.py").write_text(
            "import tkinter as tk\n"
            "canvas.create_polygon(...)  # 2D isometric projection\n",
            encoding="utf-8",
        )
        chain = SimpleNamespace(saved_dir=tmp_path)
        state = self._make_state(
            domain_checklist=build_domain_checklist("3D BIM 건축 모델"),
            chain_result=chain,
        )
        result = _node_judge_convergence(state)
        # Gap Analyst 가 COMPLETE 라도 (must_fix=0) Rule 0 가 override
        assert result["decision"].verdict == Verdict.IMPROVE_NEEDED
        assert result["decision"].blocked_cause == BlockedCause.NONE
        assert len(result["decision"].domain_unsatisfied) == 5  # P14: scene-render-loop 추가

    def test_fake_packages_still_takes_priority_over_rule0(self) -> None:
        """⭐ Rule -1 (fake) > Rule 0 (domain) 우선순위 보존."""
        state = self._make_state(
            domain_checklist=build_domain_checklist("3D BIM"),
            fake_packages=["bim_repository"],
            consecutive_fake_iterations=2,
        )
        result = _node_judge_convergence(state)
        # Rule -1 BLOCKED(FAKE_PACKAGE) 가 Rule 0 IMPROVE 보다 우선
        assert result["decision"].verdict == Verdict.BLOCKED
        assert result["decision"].blocked_cause == BlockedCause.FAKE_PACKAGE
