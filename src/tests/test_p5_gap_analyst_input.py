# -*- coding: utf-8 -*-
"""P5 Gap Analyst GUI-경로 입력 배선 회귀 test (PR #237).

출처: ``docs/diagnostics/phase6e_rerun_P0P1P2_verdict_20260529.md`` — 1차 원인(절대 블로커)

배경:
    P2-A 가 web 코드를 디스크에 저장(iter2 ~15파일)해도 판정기(Gap Analyst)가 못 봄.
    `_format_gap_analyst_input` 이 [ENGINEER_OUTPUT] 블록에 chain_result.engineer_output
    만 주입하는데, GUI 경로(`analyze_and_implement._run_gui_workflow`)는 engineer_output=""
    고정 → gui_code_output(실제 저장 web 코드)이 어느 블록에도 안 들어감 → [ENGINEER_OUTPUT]
    항상 공란 → 완벽한 web 산출도 "0 satisfied" → COMPLETE 영영 불가.

수정 (P5): 폴백 순서 engineer_output → gui_code_output → 저장 코드 발췌.

검증:
    P5-T1. GUI 경로 — engineer_output="" + gui_code_output=web → [ENGINEER_OUTPUT]에 web 주입(공란 아님).
    P5-T2. 정상 경로 — engineer_output 있음 → 기존대로(회귀 0), gui_code_output 미사용.
    P5-T3. 핵심 증명 — gui_code_output 의 three.js/WebGL 코드가 [ENGINEER_OUTPUT]에 포함 → "0 satisfied" 오판 재현 안 됨.
    P5-T3b. 가드 — engineer_output="" + gui_code_output="" + 디스크 저장 코드 → 저장 코드 발췌 폴백.
    P5-T4. 구조 무결성 — 5블록 전부 유지 + whitespace-only engineer_output 도 폴백.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.iterative_loop import _format_gap_analyst_input


_WEB_CODE = (
    "framework=react+vite+typescript\n"
    "// file: src/main.tsx\n"
    "import * as THREE from 'three';\n"
    "const renderer = new THREE.WebGLRenderer();\n"
    "import { IFCLoader } from 'web-ifc-three/IFCLoader';"
)


def _engineer_block(rendered: str) -> str:
    """[ENGINEER_OUTPUT] 섹션 본문만 추출 ([ENGINEER_OUTPUT]\\n ... \\n\\n[QA_REVIEW])."""
    start = rendered.index("[ENGINEER_OUTPUT]\n") + len("[ENGINEER_OUTPUT]\n")
    end = rendered.index("\n\n[QA_REVIEW]")
    return rendered[start:end]


def _cr(**kw) -> SimpleNamespace:
    """duck-typed chain_result. 기본값: 전부 빈 문자열 + saved_dir=None."""
    base = dict(engineer_output="", qa_review="qa", gui_code_output="", saved_dir=None)
    base.update(kw)
    return SimpleNamespace(**base)


# =============================================================================
# P5-T1. GUI 경로 — engineer_output="" + gui_code_output → 주입됨 (공란 아님)
# =============================================================================
class TestT1GuiPathFallback:
    def test_gui_code_injected_when_engineer_empty(self) -> None:
        cr = _cr(engineer_output="", gui_code_output="WEB_SPA_BLOB_12345")
        out = _format_gap_analyst_input("spec", cr, "", 1)
        block = _engineer_block(out)
        assert "WEB_SPA_BLOB_12345" in block
        assert block.strip() != ""  # 공란 아님 (이전 버그: 항상 공란)

    def test_gui_code_injected_into_engineer_output_section(self) -> None:
        cr = _cr(engineer_output="", gui_code_output=_WEB_CODE)
        out = _format_gap_analyst_input("spec", cr, "prev", 2)
        assert "[ENGINEER_OUTPUT]" in out
        assert "src/main.tsx" in _engineer_block(out)


# =============================================================================
# P5-T2. 정상 경로 — engineer_output 있음 → 기존대로 (회귀 0)
# =============================================================================
class TestT2NormalPathUnchanged:
    def test_engineer_output_takes_priority(self) -> None:
        cr = _cr(engineer_output="CLI_ENGINEER_MARKDOWN", gui_code_output="GUI_SHOULD_NOT_APPEAR")
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 1))
        assert "CLI_ENGINEER_MARKDOWN" in block
        # engineer_output 이 있으면 gui_code_output 은 사용 안 함 (회귀 0)
        assert "GUI_SHOULD_NOT_APPEAR" not in block

    def test_cli_path_no_gui_field(self) -> None:
        """gui_code_output 속성 자체가 없는 chain_result 도 안전(getattr 기본값)."""
        cr = SimpleNamespace(engineer_output="ENG_MD", qa_review="qa")
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 1))
        assert "ENG_MD" in block


# =============================================================================
# P5-T3. 핵심 증명 — three.js/WebGL 코드가 판정기 입력에 포함 (0 satisfied 오판 차단)
# =============================================================================
class TestT3WebCodeVisibleToJudge:
    def test_three_js_code_reaches_judge_input(self) -> None:
        cr = _cr(engineer_output="", gui_code_output=_WEB_CODE)
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 3))
        # 도메인 키워드(Rule 0/satisfied 판정의 근거)가 판정기 입력에 실제 도달
        assert "THREE" in block
        assert "WebGLRenderer" in block
        assert "IFCLoader" in block
        # 이전 버그(공란) 재현 안 됨
        assert block.strip() != ""


# =============================================================================
# P5-T3b. 가드 — engineer_output="" + gui_code_output="" + 디스크 저장 코드 → 폴백
# =============================================================================
class TestT3bDiskExcerptGuard:
    def test_disk_code_excerpt_fallback(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        code_dir.mkdir(parents=True)
        (code_dir / "app.py").write_text(
            "DISK_SAVED_MARKER\nimport sys\nprint('hi')", encoding="utf-8"
        )
        cr = _cr(engineer_output="", gui_code_output="", saved_dir=tmp_path)
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 1))
        # gui_code_output 도 비었지만 디스크 저장 코드를 발췌해 주입
        assert "DISK_SAVED_MARKER" in block

    def test_all_empty_stays_empty(self) -> None:
        """engineer/gui/디스크 전부 비면 공란 (truly empty — 무한 폴백 없음)."""
        cr = _cr(engineer_output="", gui_code_output="", saved_dir=None)
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 1))
        assert block.strip() == ""


# =============================================================================
# P5-T4. 구조 무결성 + whitespace 폴백
# =============================================================================
class TestT4StructureIntegrity:
    def test_five_blocks_present(self) -> None:
        cr = _cr(engineer_output="", gui_code_output="web")
        out = _format_gap_analyst_input("SPEC", cr, "PREV", 2)
        for marker in (
            "[REQUIREMENT_SPEC]",
            "[ENGINEER_OUTPUT]",
            "[QA_REVIEW]",
            "[EXECUTION_RESULT]",
            "[PREVIOUS_GAP_REPORT]",
        ):
            assert marker in out
        assert "본 iteration 번호: 2" in out
        assert "SPEC" in out

    def test_whitespace_only_engineer_falls_back(self) -> None:
        cr = _cr(engineer_output="   \n  ", gui_code_output="GUI_FALLBACK_OK")
        block = _engineer_block(_format_gap_analyst_input("spec", cr, "", 1))
        assert "GUI_FALLBACK_OK" in block
