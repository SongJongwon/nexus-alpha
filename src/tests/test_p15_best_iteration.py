# -*- coding: utf-8 -*-
"""P15 최고 iteration 보존 / 회귀·degenerate 종단 금지 회귀 test (v13 Phase 6.E).

결정적 발견(ERP 런, max-iter=2): iter1 이 완전한 ERP web 프로젝트 + dist/ 빌드 성공(요청대로
정확)했으나, iter2 가 깨진 stub(package.json 없음, 55-char 단축)으로 회귀. 종단 verdict 가
iter2 기준 BLOCKED(ITERATION_CAP)으로 계산돼, 루프가 *자기 성공(iter1)을 버리고* 깨진 iter2 로
끝났다. 앵커링(P14)은 성공했고 루프가 최고 iteration 을 채택하지 못한 게 유일한 문제.

처방:
    - _iteration_quality: iteration 별 품질 점수(degenerate/build_ok/domain_ok/must_fix).
    - _select_best_iteration: 최고 점수 record (degenerate 는 유효 iter 보다 항상 낮게).
    - _resolve_best_output: 종단 시 마지막이 아니라 *최고* iteration 산출 채택.
      · 최고가 빌드 성공(dist/.exe)+도메인 충족 → COMPLETE(후속 회귀 note).
      · 그 외 → 최고 *유효* iter surface (깨진 stub 말고), gap 유지.
      · 유효 iter 없으면(모두 degenerate) 현행(마지막) 폴백 — 회귀 0.

검증: P15-T1~T8. 회귀 0.
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
    JudgmentDecision,
    Verdict,
)
from src.workflows.iterative_loop import (
    _iteration_quality,
    _resolve_best_output,
    _select_best_iteration,
)


def _valid_web_chain(tmp_path: Path, *, build_ok: bool) -> SimpleNamespace:
    """유효한 web 프로젝트 chain_result (index.html + package.json + src, >200B)."""
    d = tmp_path / "code"
    d.mkdir(parents=True, exist_ok=True)
    idx = d / "index.html"
    idx.write_text("<!doctype html><html><body></body></html>\n" * 6, encoding="utf-8")
    (d / "package.json").write_text('{"name":"erp","scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (d / "src__main.ts").write_text("import x from 'three';\n" * 30, encoding="utf-8")
    code_files = [idx, d / "package.json", d / "src__main.ts"]
    exec_res = SimpleNamespace(
        success=build_ok, exit_code=0 if build_ok else -8,
        exe_path=(d / "dist" / "index.html") if build_ok else None,
    )
    return SimpleNamespace(saved_code_files=code_files, executor_result=exec_res, saved_dir=tmp_path)


def _degenerate_chain(tmp_path: Path) -> SimpleNamespace:
    """깨진 stub chain_result (단축 산출, entry/manifest 부재)."""
    d = tmp_path / "code2"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "block01.py"
    f.write_text("x=1\n", encoding="utf-8")  # 55-char 류 단축
    return SimpleNamespace(saved_code_files=[f], executor_result=None, saved_dir=tmp_path)


# =============================================================================
# P15-T1. _iteration_quality — 품질 신호
# =============================================================================
class TestT1IterationQuality:
    def test_valid_build_success_high_score(self, tmp_path: Path) -> None:
        q = _iteration_quality(
            _valid_web_chain(tmp_path, build_ok=True),
            GapReport(unsatisfied_blockers=0, unsatisfied_majors=0, iteration=1),
            JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "r", "n", 0),
            "web",
        )
        assert q["degenerate"] is False
        assert q["build_ok"] is True
        assert q["domain_ok"] is True
        assert q["score"] > 100  # build(100)+domain(50)

    def test_degenerate_low_score(self, tmp_path: Path) -> None:
        q = _iteration_quality(
            _degenerate_chain(tmp_path),
            GapReport(unsatisfied_blockers=2, iteration=2),
            JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "r", "n", 2),
            "web",
        )
        assert q["degenerate"] is True
        assert q["build_ok"] is False
        assert q["score"] < 0  # disqualified


# =============================================================================
# P15-T2. _select_best_iteration — degenerate/마지막 아님
# =============================================================================
class TestT2SelectBest:
    def test_picks_valid_over_degenerate_last(self, tmp_path: Path) -> None:
        valid = _iteration_quality(
            _valid_web_chain(tmp_path, build_ok=True),
            GapReport(iteration=1), JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "", "", 0), "web",
        )
        degen = _iteration_quality(
            _degenerate_chain(tmp_path),
            GapReport(iteration=2), JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "", "", 0), "web",
        )
        best = _select_best_iteration([valid, degen])  # degen 이 마지막(iter2)
        assert best["iteration"] == 1  # 유효 iter1 채택 (마지막 degenerate 아님)

    def test_empty_returns_none(self) -> None:
        assert _select_best_iteration([]) is None


# =============================================================================
# P15-T3. (acceptance a) 중간 빌드 성공 → 마지막 degenerate → COMPLETE 로 최고 채택
# =============================================================================
class TestT3MidSuccessLastDegenerateCompletes:
    def test_adopts_success_iter_as_complete(self, tmp_path: Path) -> None:
        valid_chain = _valid_web_chain(tmp_path, build_ok=True)
        degen_chain = _degenerate_chain(tmp_path)
        rec_valid = _iteration_quality(
            valid_chain, GapReport(unsatisfied_blockers=1, iteration=1),
            JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "", "", 1), "web",
        )
        rec_degen = _iteration_quality(
            degen_chain, GapReport(unsatisfied_blockers=3, iteration=2),
            JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "", "", 3), "web",
        )
        final_state = {
            "chain_result": degen_chain,  # 루프 마지막 = 깨진 stub
            "execution_result": None,
            "iteration": 2,
            "iteration_records": [rec_valid, rec_degen],
        }
        last_decision = JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "cap", "n", 3)
        sel_chain, sel_exec, sel_gap, sel_decision = _resolve_best_output(
            final_state, last_decision, GapReport(iteration=2)
        )
        # 최종 산출 = iter1 의 유효 chain (깨진 stub 아님)
        assert sel_chain is valid_chain
        # 빌드 성공 + 도메인 충족 → COMPLETE + 회귀 note
        assert sel_decision.verdict == Verdict.COMPLETE
        assert sel_decision.blocked_cause == BlockedCause.NONE
        assert "BEST_ITERATION_ADOPTED" in sel_decision.reason
        assert "회귀" in sel_decision.reason or "degenerate" in sel_decision.reason


# =============================================================================
# P15-T4. (acceptance b) 모든 iter 유효 → 마지막(최고) 그대로 (종전대로)
# =============================================================================
class TestT4AllValidUnchanged:
    def test_all_valid_keeps_last(self, tmp_path: Path) -> None:
        c1 = _valid_web_chain(tmp_path / "a", build_ok=True)
        c2 = _valid_web_chain(tmp_path / "b", build_ok=True)
        r1 = _iteration_quality(c1, GapReport(iteration=1), JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "", "", 0), "web")
        r2 = _iteration_quality(c2, GapReport(iteration=2), JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "", "", 0), "web")
        final_state = {"chain_result": c2, "execution_result": None, "iteration": 2, "iteration_records": [r1, r2]}
        sel_chain, _, _, sel_decision = _resolve_best_output(
            final_state, JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "", "", 0), GapReport(iteration=2)
        )
        # 동점(둘 다 build_ok+domain_ok) → 후기 iter2(마지막) 채택 = 종전대로
        assert sel_chain is c2
        assert sel_decision.verdict == Verdict.COMPLETE


# =============================================================================
# P15-T5. build_ok 인데 도메인 미충족(예: 3D 요청에 대시보드) → COMPLETE 아님
# =============================================================================
class TestT5BuildOkButDomainFail:
    def test_domain_unsatisfied_not_completed(self, tmp_path: Path) -> None:
        chain = _valid_web_chain(tmp_path, build_ok=True)
        improve_dec = JudgmentDecision(
            Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "domain miss", "fix 3d",
            must_fix_count=0, domain_unsatisfied=["3d-scene-render-loop"],
        )
        rec = _iteration_quality(chain, GapReport(iteration=1), improve_dec, "web")
        assert rec["domain_ok"] is False
        final_state = {"chain_result": chain, "execution_result": None, "iteration": 1, "iteration_records": [rec]}
        _, _, _, sel_decision = _resolve_best_output(final_state, improve_dec, GapReport(iteration=1))
        # build_ok 여도 도메인 미충족 → COMPLETE 아님, 최고 유효 iter 의 결정(IMPROVE) surface
        assert sel_decision.verdict == Verdict.IMPROVE_NEEDED
        assert sel_decision.domain_unsatisfied == ["3d-scene-render-loop"]


# =============================================================================
# P15-T6. 모든 iter degenerate → 현행(마지막) 폴백 (회귀 0)
# =============================================================================
class TestT6AllDegenerateFallback:
    def test_all_degenerate_keeps_last(self, tmp_path: Path) -> None:
        d1 = _degenerate_chain(tmp_path / "x")
        d2 = _degenerate_chain(tmp_path / "y")
        r1 = _iteration_quality(d1, GapReport(iteration=1), JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "", "", 0), "web")
        r2 = _iteration_quality(d2, GapReport(iteration=2), JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "", "", 0), "web")
        last_dec = JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "cap", "n", 0)
        final_state = {"chain_result": d2, "execution_result": None, "iteration": 2, "iteration_records": [r1, r2]}
        sel_chain, _, _, sel_decision = _resolve_best_output(final_state, last_dec, GapReport(iteration=2))
        # 유효 iter 없음 → 현행(마지막) 폴백: chain=last, decision=last (verdict 불변)
        assert sel_chain is d2
        assert sel_decision is last_dec


# =============================================================================
# P15-T7. iteration_records 없음 → 현행(마지막) 폴백 (회귀 0)
# =============================================================================
class TestT7NoRecordsFallback:
    def test_no_records_keeps_last(self) -> None:
        last_chain = SimpleNamespace(saved_code_files=[], executor_result=None)
        last_dec = JudgmentDecision(Verdict.COMPLETE, BlockedCause.NONE, "ok", "n", 0)
        final_state = {"chain_result": last_chain, "execution_result": None, "iteration": 1}
        sel_chain, sel_exec, sel_gap, sel_decision = _resolve_best_output(
            final_state, last_dec, GapReport(iteration=1)
        )
        assert sel_chain is last_chain
        assert sel_decision is last_dec


# =============================================================================
# P15-T8. desktop(.exe) 최고 iter 도 채택 (build_ok = exe_path)
# =============================================================================
class TestT8DesktopBestAdopted:
    def test_desktop_exe_best_completes(self, tmp_path: Path) -> None:
        d = tmp_path / "code"
        d.mkdir()
        app = d / "app.py"
        app.write_text("from PyQt6.QtWidgets import QApplication\n" * 30, encoding="utf-8")
        exe = d / "dist" / "App.exe"
        chain = SimpleNamespace(
            saved_code_files=[app],
            executor_result=SimpleNamespace(success=True, exit_code=0, exe_path=exe),
            saved_dir=tmp_path,
        )
        degen = _degenerate_chain(tmp_path)
        r1 = _iteration_quality(chain, GapReport(iteration=1), JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "", "", 0), "desktop")
        r2 = _iteration_quality(degen, GapReport(iteration=2), JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "", "", 0), "desktop")
        final_state = {"chain_result": degen, "execution_result": None, "iteration": 2, "iteration_records": [r1, r2]}
        sel_chain, _, _, sel_decision = _resolve_best_output(
            final_state, JudgmentDecision(Verdict.BLOCKED, BlockedCause.ITERATION_CAP, "", "", 0), GapReport(iteration=2)
        )
        assert sel_chain is chain  # .exe 성공 iter 채택
        assert sel_decision.verdict == Verdict.COMPLETE
