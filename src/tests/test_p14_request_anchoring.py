# -*- coding: utf-8 -*-
"""P14 요청 앵커링 / 시스템 컨텍스트 격리 + 도메인 충실도 + 출력 무결성 회귀 test.

배경 (P13 런 iter4): 코드 생성기가 사용자 요청("3D BIM 뷰어")이 아니라 시스템(Nexus Alpha)
자기 자신의 관제 대시보드(에이전트 명단 테이블 등)를 생성. 시스템 내부 컨텍스트가 제품 생성
프롬프트에 새어들어(특히 kickoff directive 의 부서별 책임=에이전트 명단 + RAG recall) 사용자
요청의 지배력을 잃은 앵커링 버그.

처방:
    수정1 — _build_product_anchor: 사용자 요청을 최상위 권위 앵커로 + 시스템 컨텍스트 격리 directive.
        to_kickoff_context_directive(product_scoped=True): 부서 명단/cross-agent 역할명/RAG recall 제거.
        _build_gui_code_gen_task 가 user_request 앵커 prepend + product_scoped 적용.
    수정2 — _TEMPLATE_3D_CHECKLIST 에 3d-scene-render-loop must-item 추가: 일반 대시보드 산출은
        Three.js Scene+render 부재로 Rule 0 미충족 → 빌드돼도 COMPLETE 아님 (IMPROVE).
    수정3 — _is_degenerate_codegen: 비현실적 단축/entry·manifest 부재 산출 = 생성 실패 처리.

스코프: product 코드 생성 경로 — 빌드/판정 게이트·Track A·B/python-only/desktop 불변.
검증: P14-T1~T10. 회귀 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.analysis import build_domain_checklist
from src.agents.c_level.convergence_judge import GapReport, Verdict, judge_convergence
from src.agents.coordination.schemas import SharedAssumption, SharedKickoffDecisions
from src.workflows._common import format_kickoff_context_directive
from src.workflows.analyze_and_implement import (
    _build_gui_code_gen_task,
    _build_product_anchor,
    _is_degenerate_codegen,
)

_USER_REQ = "3D BIM 건축 모델 뷰어: Three.js + BIM 라이브러리, 카메라 회전, 클릭 시 속성 표시, 다크 관제센터"


def _decisions_with_system_context() -> SharedKickoffDecisions:
    """부서별 책임(시스템 에이전트 명단) + RAG recall(과거 시스템 정보) 포함 kickoff 결정."""
    return SharedKickoffDecisions(
        user_request=_USER_REQ,
        spec_summary="3D BIM 뷰어",
        shared_assumptions=[
            SharedAssumption(id="A1", owner="CTO", decision="플랫폼=web/Three.js", rationale="요청 명시")
        ],
        agent_responsibilities={
            "GUI Designer": ["와이어프레임"],
            "Code Generator": ["코드 작성"],
            "Code Reviewer": ["리뷰"],
        },
        recalled_knowledge_markdown="## 과거 빌드 RAG_RECALL: Nexus Alpha 관제 대시보드 패턴 재사용",
    )


# =============================================================================
# P14-T1. _build_product_anchor — 사용자 요청 최상위 앵커 + 시스템 격리 directive
# =============================================================================
class TestT1ProductAnchor:
    def test_anchor_contains_request_and_isolation(self) -> None:
        anchor = _build_product_anchor(_USER_REQ)
        assert "최상위 권위 앵커" in anchor
        assert _USER_REQ in anchor  # 사용자 요청 그대로 앵커
        assert "컨텍스트 격리" in anchor
        # 시스템 누수 금지 — 에이전트 명단/자체 대시보드는 제품 내용 아님 명시
        assert "Nexus Alpha" in anchor
        assert "Code Generator" in anchor  # 금지 목록에 시스템 에이전트명 명시
        assert "모니터링 대시보드" in anchor

    def test_empty_request_empty_anchor(self) -> None:
        assert _build_product_anchor("") == ""
        assert _build_product_anchor("   ") == ""


# =============================================================================
# P14-T2. to_kickoff_context_directive(product_scoped) — 시스템 누수 제거
# =============================================================================
class TestT2ProductScopedDirective:
    def test_product_scoped_strips_system_context(self) -> None:
        sk = _decisions_with_system_context()
        full = sk.to_kickoff_context_directive(["GUI Designer", "Theme Designer"])
        scoped = sk.to_kickoff_context_directive(
            ["GUI Designer", "Theme Designer"], product_scoped=True
        )
        # 기존(full): 부서별 책임 + RAG recall + cross-agent 역할명 포함
        assert "부서별 책임" in full
        assert "RAG_RECALL" in full
        assert "Cross-agent" in full
        # product_scoped: 셋 다 제거 (시스템 누수 차단)
        assert "부서별 책임" not in scoped
        assert "RAG_RECALL" not in scoped
        assert "Cross-agent" not in scoped
        # 제품 관련 결정(shared_assumptions)은 유지
        assert "web/Three.js" in scoped

    def test_format_kickoff_product_scoped_none(self) -> None:
        # decisions=None + product_scoped → 빈 string (cross-agent 역할명도 미주입)
        assert format_kickoff_context_directive(None, ["GUI Designer"], product_scoped=True) == ""
        # 기존(default): consistency directive 주입 (회귀 0)
        assert format_kickoff_context_directive(None, ["GUI Designer"]) != ""


# =============================================================================
# P14-T3. _build_gui_code_gen_task — 앵커 prepend + 시스템 명단 미포함
# =============================================================================
class TestT3CodeGenTaskAnchored:
    def _coder_and_ctx(self):
        from crewai import Task

        from src.agents.design import create_gui_code_generator_agent

        coder = create_gui_code_generator_agent(verbose=False)
        ctx = [
            Task(description="ui spec", expected_output="o", agent=coder),
            Task(description="design", expected_output="o", agent=coder),
            Task(description="theme", expected_output="o", agent=coder),
        ]
        return coder, ctx

    def test_description_anchors_request_and_drops_system_roster(self) -> None:
        coder, ctx = self._coder_and_ctx()
        task = _build_gui_code_gen_task(
            coder, ctx[0], ctx[1], ctx[2],
            shared_kickoff_decisions=_decisions_with_system_context(),
            platform_intent="web",
            user_request=_USER_REQ,
        )
        desc = task.description
        # 사용자 요청이 최상위 권위 앵커로 prepend
        assert "최상위 권위 앵커" in desc
        assert _USER_REQ in desc
        # 시스템 누수 제거 (product_scoped): 부서별 책임/RAG recall 미포함
        assert "부서별 책임" not in desc
        assert "RAG_RECALL" not in desc
        # 격리 directive 존재
        assert "컨텍스트 격리" in desc

    def test_no_user_request_no_anchor_but_builds(self) -> None:
        # user_request 미전달(기본 "") → 앵커 없음, task 는 정상 생성 (회귀 0)
        coder, ctx = self._coder_and_ctx()
        task = _build_gui_code_gen_task(
            coder, ctx[0], ctx[1], ctx[2], platform_intent="unspecified"
        )
        assert "최상위 권위 앵커" not in task.description
        assert task.agent is coder


# =============================================================================
# P14-T4/T5. 도메인 충실도 (수정2) — Three.js scene-render-loop must-item
# =============================================================================
class TestT4DomainChecklistFidelity:
    def test_3d_template_has_scene_render_item(self) -> None:
        checklist = build_domain_checklist("3D BIM Three.js 뷰어")
        ids = {c.id for c in checklist}
        assert "3d-scene-render-loop" in ids
        item = next(c for c in checklist if c.id == "3d-scene-render-loop")
        assert item.must_satisfy is True
        assert any("THREE.Scene" in k or "renderer.render" in k for k in item.detect_keywords)

    def test_dashboard_output_not_complete_even_if_built(self) -> None:
        """⭐ 빌드는 되지만 도메인 틀린 산출(시스템 대시보드) → COMPLETE 아님 (IMPROVE)."""
        checklist = build_domain_checklist(_USER_REQ)
        dashboard = (
            "활성 Agent 8 / 진행 작업 12 / 성공률 94.2% — 좌측 메뉴 대시보드/파이프라인/Agent. "
            "Requirement·GUI Designer·Theme·Code Gen·Reviewer 테이블. (Three.js·Scene·render 없음)"
        )
        decision = judge_convergence(
            GapReport(satisfied_count=8, unsatisfied_blockers=0, iteration=2),
            max_iterations=5,
            domain_checklist=checklist,
            engineer_output_excerpt=dashboard,
        )
        # must_fix=0(빌드 OK) 이어도 도메인 미충족 → Rule 0 IMPROVE (빌드 성공 ≠ COMPLETE)
        assert decision.verdict == Verdict.IMPROVE_NEEDED

    def test_real_threejs_viewer_completes(self) -> None:
        """진짜 Three.js 3D 뷰어(Scene+render+controls) → 5 항목 충족 → COMPLETE."""
        checklist = build_domain_checklist(_USER_REQ)
        viewer = (
            "import * as THREE from 'three'; "
            "const scene = new THREE.Scene(); const renderer = new THREE.WebGLRenderer(); "
            "const camera = new THREE.PerspectiveCamera(); scene.add(mesh); "
            "renderer.render(scene, camera); requestAnimationFrame(animate); "
            "const controls = new OrbitControls(camera, dom); controls.update(); "
            "zoom pan reset addEventListener wheel; rotateY Vector3 PointLight"
        )
        decision = judge_convergence(
            GapReport(satisfied_count=9, unsatisfied_blockers=0, iteration=2),
            max_iterations=5,
            domain_checklist=checklist,
            engineer_output_excerpt=viewer,
        )
        assert decision.verdict == Verdict.COMPLETE


# =============================================================================
# P14-T6. 출력 무결성 (수정3) — degenerate 생성 실패 판정
# =============================================================================
class TestT6DegenerateCodegen:
    def test_tiny_output_is_degenerate(self, tmp_path: Path) -> None:
        f = tmp_path / "block01.py"
        f.write_text("x = 1  # 31 bytes 정도", encoding="utf-8")  # < 200 bytes
        assert _is_degenerate_codegen([f], "web") is True

    def test_no_real_files_is_degenerate(self, tmp_path: Path) -> None:
        t = tmp_path / "test_app.py"
        t.write_text("def test_x(): assert True\n" * 20, encoding="utf-8")
        # test_*.py 만 있고 실제 산출 없음 → degenerate
        assert _is_degenerate_codegen([t], "web") is True

    def test_web_missing_entry_and_manifest_is_degenerate(self, tmp_path: Path) -> None:
        f = tmp_path / "src__util.ts"
        f.write_text("export const x = 1;\n" * 30, encoding="utf-8")  # > 200 bytes 이지만
        # web 인데 index.html / package.json 둘 다 없음 → degenerate
        assert _is_degenerate_codegen([f], "web") is True

    def test_normal_web_output_not_degenerate(self, tmp_path: Path) -> None:
        idx = tmp_path / "index.html"
        idx.write_text("<!doctype html><html><body></body></html>\n" * 5, encoding="utf-8")
        main = tmp_path / "src__main.ts"
        main.write_text("import * as THREE from 'three';\n" * 30, encoding="utf-8")
        assert _is_degenerate_codegen([idx, main], "web") is False

    def test_normal_desktop_output_not_degenerate(self, tmp_path: Path) -> None:
        app = tmp_path / "app.py"
        app.write_text("from PyQt6.QtWidgets import QApplication\n" * 30, encoding="utf-8")
        # desktop(unspecified) — entry/manifest 검사 안 함, 바이트 충분 → 정상
        assert _is_degenerate_codegen([app], "unspecified") is False
