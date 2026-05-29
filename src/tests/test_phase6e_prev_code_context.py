# -*- coding: utf-8 -*-
"""v13 Phase 6.E (PR #232) — iter 간 코드 컨텍스트 전달 단위 test.

PM 진단 처방 옵션 B — iter 2 퇴행 (BIM viewport.py → Nexus GUI 복사본) 의
root cause #1 (iter 간 코드 컨텍스트 손실) 해결.

검증 범위:
    1. _build_prev_code_context — chain_result 발췌 → prompt 텍스트
    2. None / 빈 saved_dir / 빈 code 시 빈 string (회귀 0)
    3. _node_run_chain — iter 1 (next_iter=1) 시 prev_code_context 미첨부
    4. _node_run_chain — iter 2+ (next_iter>1) 시 prev_code_context 첨부
    5. feedback + prev_code_context 결합 prompt 검증
    6. Track A 와 Track B 양쪽 동일 prompt 통과 (request_with_feedback 단일 경로)
    7. ⭐ BIM 퇴행 시나리오 — 이전 iter viewport.py 의 OrbitControls 가 prompt 에 포함
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.iterative_loop import (
    _build_prev_code_context,
    _node_run_chain,
)


# =============================================================================
# 1. _build_prev_code_context — 발췌 helper
# =============================================================================
class TestBuildPrevCodeContext:
    def test_none_returns_empty(self) -> None:
        assert _build_prev_code_context(None) == ""

    def test_no_saved_dir_returns_empty(self) -> None:
        chain = SimpleNamespace(saved_dir=None)
        assert _build_prev_code_context(chain) == ""

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        chain = SimpleNamespace(saved_dir=tmp_path / "nope")
        assert _build_prev_code_context(chain) == ""

    def test_empty_code_dir_returns_empty(self, tmp_path: Path) -> None:
        chain = SimpleNamespace(saved_dir=tmp_path)
        # code/ 디렉터리 없고 md 파일 없음 → 빈 발췌
        assert _build_prev_code_context(chain) == ""

    def test_code_dir_yields_wrapped_context(self, tmp_path: Path) -> None:
        """⭐ saved_dir/code/*.py 발견 → 한국어 wrapper 로 포장."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "viewport.py").write_text(
            "import OrbitControls\nclass ViewportPanel: pass", encoding="utf-8"
        )
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _build_prev_code_context(chain)
        assert "이전 iteration 산출 코드" in result
        assert "OrbitControls" in result
        assert "ViewportPanel" in result
        assert "viewport.py" in result
        assert "백지에서 다시 작성하는 것은 **퇴행**" in result
        assert "--- 끝 ---" in result

    def test_max_chars_respected(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "huge.py").write_text("X" * 100_000, encoding="utf-8")
        chain = SimpleNamespace(saved_dir=tmp_path)
        result = _build_prev_code_context(chain, max_chars=500)
        # wrapper 텍스트 + 500 chars 코드 발췌 → 전체 ~700 chars 미만
        assert len(result) < 1500


# =============================================================================
# 2. _node_run_chain — iter 1 (next_iter=1) prev_code_context 미첨부 (회귀 0)
# =============================================================================
class TestNodeRunChainIter1NoPrevCode:
    """⭐ 회귀 0 — 첫 iter (next_iter=1) 진입 시 prev_code_context 첨부 X."""

    @patch("src.workflows.iterative_loop.run_analyze_and_implement")
    def test_iter1_no_prev_context_in_prompt(
        self, mock_aai, tmp_path: Path
    ) -> None:
        """iter 0 → iter 1 진입 — chain_result=None → 빈 context."""
        mock_aai.return_value = SimpleNamespace(
            saved_dir=tmp_path, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 0,
            "user_request": "3D BIM 뷰어",
            "feedback": "",
            "chain_result": None,  # iter 1 진입 시점
            "outputs_dir": str(tmp_path),
            "track": "A",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        # mock_aai 호출의 첫 인자 = request_with_feedback
        called_request = mock_aai.call_args[0][0]
        assert called_request == "3D BIM 뷰어"  # 원본 그대로 (context X)
        assert "이전 iteration" not in called_request


# =============================================================================
# 3. _node_run_chain — iter 2+ prev_code_context 첨부 (★ 핵심 fix)
# =============================================================================
class TestNodeRunChainIter2PlusPrevCodeAttached:
    """⭐ Phase 6.E PR #232 핵심 — iter 2+ 진입 시 이전 코드 prompt 첨부."""

    @patch("src.workflows.iterative_loop.run_analyze_and_implement")
    def test_iter2_attaches_prev_code(self, mock_aai, tmp_path: Path) -> None:
        """⭐ iter 1 → iter 2 — 이전 chain_result 의 code 가 prompt 에 포함."""
        # 이전 iter (iter 1) 의 chain_result 시뮬레이션 — BIM viewport.py 산출
        prev_saved = tmp_path / "iter1_workflow"
        prev_code = prev_saved / "code"
        prev_code.mkdir(parents=True)
        (prev_code / "viewport.py").write_text(
            "from PyQt6.QtWebEngineWidgets import QWebEngineView\n"
            "class ViewportPanel:\n"
            "    THREEJS_HTML = '<canvas>OrbitControls + PerspectiveCamera</canvas>'\n",
            encoding="utf-8",
        )
        prev_chain = SimpleNamespace(saved_dir=prev_saved)

        # iter 2 진입용 mock
        new_saved = tmp_path / "iter2_workflow"
        new_saved.mkdir()
        mock_aai.return_value = SimpleNamespace(
            saved_dir=new_saved, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 1,  # 다음 = iter 2
            "user_request": "3D BIM 뷰어",
            "feedback": "must-fix 3건 추가 보정 필요",
            "chain_result": prev_chain,  # ← 이전 iter 산출
            "outputs_dir": str(tmp_path),
            "track": "A",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        called_request = mock_aai.call_args[0][0]
        # feedback + prev_code_context 모두 포함
        assert "must-fix 3건" in called_request
        assert "이전 iteration 산출 코드" in called_request
        assert "viewport.py" in called_request
        assert "OrbitControls" in called_request
        assert "PerspectiveCamera" in called_request
        assert "백지에서 다시 작성하는 것은 **퇴행**" in called_request

    @patch("src.workflows.iterative_loop.run_analyze_and_implement")
    def test_iter3_attaches_prev_iter2_code(
        self, mock_aai, tmp_path: Path
    ) -> None:
        """iter 2 → iter 3 — 동일 메커니즘."""
        prev_saved = tmp_path / "iter2_workflow"
        prev_code = prev_saved / "code"
        prev_code.mkdir(parents=True)
        (prev_code / "model_tree.py").write_text(
            "class ModelTreePanel: pass", encoding="utf-8"
        )
        prev_chain = SimpleNamespace(saved_dir=prev_saved)
        new_saved = tmp_path / "iter3"
        new_saved.mkdir()
        mock_aai.return_value = SimpleNamespace(
            saved_dir=new_saved, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 2,  # 다음 = iter 3
            "user_request": "X",
            "feedback": "",
            "chain_result": prev_chain,
            "outputs_dir": str(tmp_path),
            "track": "A",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        called_request = mock_aai.call_args[0][0]
        assert "model_tree.py" in called_request
        assert "ModelTreePanel" in called_request

    @patch("src.workflows.iterative_loop.run_analyze_and_implement")
    def test_iter2_with_none_chain_result_no_context(
        self, mock_aai, tmp_path: Path
    ) -> None:
        """⭐ iter 2 진입이지만 chain_result=None (이상 케이스) → 빈 context."""
        mock_aai.return_value = SimpleNamespace(
            saved_dir=tmp_path, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 1,  # 다음 = iter 2
            "user_request": "X",
            "feedback": "보정",
            "chain_result": None,  # 이상 케이스 — 안전 처리
            "outputs_dir": str(tmp_path),
            "track": "A",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        called_request = mock_aai.call_args[0][0]
        assert "이전 iteration" not in called_request
        # feedback 만 포함
        assert "보정" in called_request


# =============================================================================
# 4. Track B 도 동일 prompt 통과 (request_with_feedback 단일 경로)
# =============================================================================
class TestTrackBAlsoUsesPrevCode:
    @patch("src.workflows.iterative_loop._adapt_automate_to_chain_result")
    @patch("src.workflows.automate_workflow.run_automate_workflow")
    def test_track_b_iter2_attaches_prev_code(
        self, mock_aw, mock_adapt, tmp_path: Path
    ) -> None:
        """⭐ Track B 도 동일 — request_with_feedback 단일 변수 통과."""
        prev_saved = tmp_path / "iter1_automate"
        prev_code = prev_saved / "code"
        prev_code.mkdir(parents=True)
        (prev_code / "scraper.py").write_text(
            "import requests\nclass Scraper: pass", encoding="utf-8"
        )
        prev_chain = SimpleNamespace(saved_dir=prev_saved)
        new_saved = tmp_path / "iter2"
        new_saved.mkdir()
        mock_aw.return_value = SimpleNamespace(saved_dir=new_saved)
        mock_adapt.return_value = SimpleNamespace(
            saved_dir=new_saved, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 1,
            "user_request": "스크래퍼",
            "feedback": "",
            "chain_result": prev_chain,
            "outputs_dir": str(tmp_path),
            "track": "B",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        called_request = mock_aw.call_args[0][0]
        assert "scraper.py" in called_request
        assert "Scraper" in called_request


# =============================================================================
# 5. ⭐ BIM 본질 시나리오 — iter 2 가 BIM 코드 인지 → 퇴행 차단
# =============================================================================
class TestBIMRegressionScenario:
    """⭐ Phase 6.E PR #232 핵심 검증 — BIM viewport.py 가 다음 iter prompt 에 포함."""

    @patch("src.workflows.iterative_loop.run_analyze_and_implement")
    def test_bim_iter1_viewport_carries_to_iter2(
        self, mock_aai, tmp_path: Path
    ) -> None:
        """⭐ iter 1 의 BIM viewport.py (Three.js + WebGL) 가 iter 2 prompt 에 그대로."""
        # iter 1 산출 시뮬레이션 — 실제 BIM 코드 (Phase 6.E 사고 재현)
        iter1_dir = tmp_path / "workflow_iter1"
        iter1_code = iter1_dir / "code"
        iter1_code.mkdir(parents=True)
        (iter1_code / "viewport.py").write_text(
            "# BIM 핵심 — Three.js WebGLRenderer + OrbitControls\n"
            "from PyQt6.QtWebEngineWidgets import QWebEngineView\n"
            "THREEJS_HTML = '''<script type=module>\n"
            "import { OrbitControls } from 'three/addons/controls/OrbitControls.js';\n"
            "const camera = new THREE.PerspectiveCamera(60, ...);\n"
            "const renderer = new THREE.WebGLRenderer({antialias: true});\n"
            "</script>'''\n",
            encoding="utf-8",
        )
        (iter1_code / "main_window.py").write_text(
            "from viewport import ViewportPanel\n", encoding="utf-8"
        )
        prev_chain = SimpleNamespace(saved_dir=iter1_dir)
        iter2_dir = tmp_path / "iter2"
        iter2_dir.mkdir()
        mock_aai.return_value = SimpleNamespace(
            saved_dir=iter2_dir, executor_result=None, publish_result=None,
            gui_code_output="",
        )
        state = {
            "iteration": 1,
            "user_request": "3D BIM 건축 모델 뷰어",
            "feedback": "must-fix: PyQt6-WebEngine 의존성 추가",
            "chain_result": prev_chain,
            "outputs_dir": str(tmp_path),
            "track": "A",
            "iteration_artifacts": [],
        }
        _node_run_chain(state)
        called_request = mock_aai.call_args[0][0]
        # ★ iter 2 Engineer 는 *이전 viewport.py 의 BIM 본질* 을 인지
        assert "viewport.py" in called_request
        assert "main_window.py" in called_request
        assert "WebGLRenderer" in called_request
        assert "OrbitControls" in called_request
        assert "PerspectiveCamera" in called_request
        # 보정 지시도 그대로
        assert "PyQt6-WebEngine" in called_request
        # 퇴행 차단 안내 명시
        assert "기존 구조와 식별자" in called_request
        assert "최대한 유지" in called_request
