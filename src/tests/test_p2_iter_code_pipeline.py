# -*- coding: utf-8 -*-
"""P2 iter→code 파이프라인 회귀 test (PR #236).

출처: ``docs/diagnostics/phase6e_rerun_P0P1_verdict_20260529.md`` 하류 3중 결함 (A)(B)

배경:
    P0/P1 라이브 검증에서 시스템이 iter2 에 완전한 Three.js+Vite+TS SPA(10파일)를
    산출했으나 BLOCKED. 원인:
      (A) extraction 단절 — `_extract_code_blocks` 가 ```python 펜스만 매칭 →
          web(.ts/.html/.css) 0개 저장, tkinter test stub 만 남음.
      (B) 옵션 B(#232)↔P1(#235) 충돌 — `_build_prev_code_context` 가 stale PyQt
          코드를 web 의도 iter 에 재주입 + "구조 유지" 가 P1 무력화 → 재드리프트.

검증:
    P2-T1. extraction: 다중 web 파일(.ts/.html/package.json) → code/ 에 web 파일 정상 저장(0개 아님).
    P2-T2. extraction: "SPA(single-page-app)" web 컨텍스트 → web 파일 추출(python stub 오매핑 안 함).
    P2-T3. 손실 가드: 다중 web 헤더인데 web 추출 0개 → `_detect_extraction_loss` 경고 발동.
    P2-T4. B platform-aware: platform_intent=web + 직전 PyQt → 재주입 안 함, "백지 재작성" 경고 대체.
    P2-T5. 회귀: platform_intent=desktop + 직전 코드 → B 기존대로 재주입(불변).
    P2-T6. P0/P1 호환 — P0 종료 가드 + P1 PLATFORM_DRIFT 동작 불변.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    Verdict,
    judge_convergence,
)
from src.workflows.analyze_and_implement import (
    _WEB_CODE_LANGS,
    _detect_extraction_loss,
    _extract_code_blocks,
)
from src.workflows.iterative_loop import _build_prev_code_context


# 완전한 web SPA 산출 (iter2 가 실제로 만든 것과 같은 형태) — file 헤더 다중 주석 스타일
_WEB_SPA_OUTPUT = """\
framework=vite+typescript+three.js+web-ifc-three, files=3개, entry=npm run dev

```typescript
// file: src/main.ts
import * as THREE from 'three';
import { IFCLoader } from 'web-ifc-three/IFCLoader';
const renderer = new THREE.WebGLRenderer();
```

```html
<!-- file: index.html -->
<!DOCTYPE html><html><body><canvas id="app"></canvas></body></html>
```

```json
// file: package.json
{"name": "bim-viewer", "scripts": {"dev": "vite"}}
```
"""

_PYQT_OUTPUT = (
    "# file: app.py\n"
    "import sys\n"
    "from PyQt6.QtWidgets import QApplication, QMainWindow\n"
    "app = QApplication(sys.argv)"
)


def _make_chain_result_with_pyqt(tmp_path: Path) -> SimpleNamespace:
    """saved_dir/code/app.py 가 PyQt 인 가짜 chain_result."""
    code_dir = tmp_path / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "app.py").write_text(_PYQT_OUTPUT, encoding="utf-8")
    return SimpleNamespace(saved_dir=tmp_path)


# =============================================================================
# P2-T1. extraction — 다중 web 파일 정상 저장 (0개 아님)
# =============================================================================
class TestT1WebExtraction:
    def test_web_files_extracted(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir, languages=_WEB_CODE_LANGS)
        names = {p.name for p in saved}
        # web 3종 모두 저장 (이전엔 0개였음)
        assert "src__main.ts" in names  # src/main.ts → / 가 __ 로
        assert "index.html" in names
        assert "package.json" in names
        assert len(saved) == 3

    def test_web_files_content_preserved(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir, languages=_WEB_CODE_LANGS)
        ts = (code_dir / "src__main.ts").read_text(encoding="utf-8")
        assert "THREE.WebGLRenderer" in ts
        assert "web-ifc-three" in ts

    def test_default_python_only_unchanged(self, tmp_path: Path) -> None:
        """기본 languages(python-only)면 web 블록 추출 안 함 (회귀 0)."""
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir)  # default python-only
        assert saved == []  # web 블록은 python-only 에서 무시


# =============================================================================
# P2-T2. "SPA" web 컨텍스트 → python stub 오매핑 안 함
# =============================================================================
class TestT2NoStubMismapping:
    def test_spa_context_extracts_web_not_python(self, tmp_path: Path) -> None:
        md = (
            "single-page-app (SPA) 구현.\n\n"
            "```typescript\n// file: spa.ts\nexport const app = 'SPA';\n```\n"
        )
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(md, code_dir, languages=_WEB_CODE_LANGS)
        # web .ts 만 추출, python stub(.py) 0개
        assert {p.name for p in saved} == {"spa.ts"}
        assert not any(p.suffix == ".py" for p in saved)

    def test_pure_web_output_no_py_files(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir, languages=_WEB_CODE_LANGS)
        assert not any(p.suffix == ".py" for p in saved)


# =============================================================================
# P2-T3. 손실 가드 — 다중 web 헤더인데 web 추출 0개 → 경고
# =============================================================================
class TestT3ExtractionLossGuard:
    def test_loss_detected_when_web_dropped(self, tmp_path: Path) -> None:
        # 옛 버그 재현: python-only 추출 → web 파일 0개
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir)  # python-only
        warning = _detect_extraction_loss(_WEB_SPA_OUTPUT, saved)
        assert warning is not None
        assert "extraction loss" in warning
        assert "web 파일 0개" in warning

    def test_no_loss_when_web_extracted(self, tmp_path: Path) -> None:
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_WEB_SPA_OUTPUT, code_dir, languages=_WEB_CODE_LANGS)
        assert _detect_extraction_loss(_WEB_SPA_OUTPUT, saved) is None

    def test_no_loss_for_non_web_output(self, tmp_path: Path) -> None:
        """web 헤더 없는 일반 산출 → 가드 미발동 (회귀 0)."""
        code_dir = tmp_path / "code"
        saved = _extract_code_blocks(_PYQT_OUTPUT, code_dir)
        assert _detect_extraction_loss(_PYQT_OUTPUT, saved) is None


# =============================================================================
# P2-T4. B platform-aware — web 의도 + 직전 PyQt → 재주입 안 함, 경고 대체
# =============================================================================
class TestT4BuildPrevCodeWebDrift:
    def test_web_intent_pyqt_prev_no_reinject(self, tmp_path: Path) -> None:
        cr = _make_chain_result_with_pyqt(tmp_path)
        ctx = _build_prev_code_context(cr, platform_intent="web")
        # stale PyQt 코드 재주입 안 함
        assert "이전 iter 코드 발췌" not in ctx
        assert "QApplication" not in ctx
        # 백지 web 재작성 경고로 대체
        assert "플랫폼 위반" in ctx
        assert "Three.js" in ctx
        assert "백지" in ctx


# =============================================================================
# P2-T5. 회귀 — desktop 의도면 B 기존대로 재주입 (불변)
# =============================================================================
class TestT5RegressionNonWeb:
    def test_desktop_intent_reinjects_prev_code(self, tmp_path: Path) -> None:
        cr = _make_chain_result_with_pyqt(tmp_path)
        ctx = _build_prev_code_context(cr, platform_intent="desktop")
        # 기존 동작 — 이전 코드 발췌 그대로 주입
        assert "이전 iteration 산출 코드" in ctx
        assert "이전 iter 코드 발췌" in ctx
        assert "QApplication" in ctx  # PyQt excerpt 포함

    def test_default_intent_reinjects_prev_code(self, tmp_path: Path) -> None:
        """platform_intent 미지정(default unspecified) → 기존 동작 불변."""
        cr = _make_chain_result_with_pyqt(tmp_path)
        ctx = _build_prev_code_context(cr)  # default unspecified
        assert "이전 iter 코드 발췌" in ctx
        assert "QApplication" in ctx

    def test_empty_prev_returns_empty(self) -> None:
        assert _build_prev_code_context(None, platform_intent="web") == ""


# =============================================================================
# P2-T6. P0/P1 호환 — 종료 가드 + PLATFORM_DRIFT 불변
# =============================================================================
class TestT6P0P1Compat:
    def test_p0_termination_guard_intact(self) -> None:
        """P0: IMPROVE + iter==max → BLOCKED(ITERATION_CAP)."""
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=5),
            max_iterations=5,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP

    def test_p1_platform_drift_intact(self) -> None:
        """P1: web 의도 + PyQt 산출 → PLATFORM_DRIFT IMPROVE (iter<max)."""
        decision = judge_convergence(
            GapReport(unsatisfied_blockers=1, iteration=2),
            max_iterations=5,
            platform_intent="web",
            engineer_output_excerpt="from PyQt6.QtWidgets import QApplication",
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.platform_drift is True
