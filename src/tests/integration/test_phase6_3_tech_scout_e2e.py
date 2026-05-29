# -*- coding: utf-8 -*-
"""v13 Phase 6.3 Tech Scout 통합 E2E test (PR #230).

검증 시나리오 (BIM 빌드 사례 정조준):
    1. Tech Scout 노드 — enable_tech_scout=True 시 requirements.txt 검증
    2. Rule -1 1차 발동 — 가짜 패키지 1차 발견 → IMPROVE_NEEDED + 힌트
    3. Rule -1 2차 발동 — 가짜 패키지 2회 연속 → BLOCKED(FAKE_PACKAGE)
    4. consecutive_fake_iterations reset — 가짜 사라지면 카운터 0
    5. enable_tech_scout=False (default) → 회귀 0
    6. requirements.txt 미존재 → graceful (회귀 0)
    7. validate_requirements_txt + extract_fake_packages — pip 형식 파싱
    8. integration — real PyPI BIM 본질 케이스
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
    judge_convergence,
)
from src.agents.research import (
    PyPIResult,
    extract_fake_packages,
    validate_requirements_txt,
)


# =============================================================================
# 1. validate_requirements_txt — pip 형식 파싱
# =============================================================================
class TestValidateRequirementsTxt:
    def _make_session(self, fake_names: set[str]) -> MagicMock:
        """이름이 fake_names 에 있으면 404, 아니면 200 반환."""

        def side_effect(url, **kwargs):
            response = MagicMock()
            # url 예: https://pypi.org/pypi/<name>/json
            name = url.rstrip("/").split("/")[-2]
            if name.lower() in fake_names:
                response.status_code = 404
            else:
                response.status_code = 200
                response.json.return_value = {
                    "info": {"version": "1.0"},
                    "urls": [],
                }
            return response

        session = MagicMock()
        session.get.side_effect = side_effect
        return session

    def test_pip_requirements_parsing(self, tmp_path: Path) -> None:
        """pip 형식 — version pin / comment / 빈 줄 / VCS / -e 무시."""
        req = tmp_path / "requirements.txt"
        req.write_text(
            "# 주석 무시\n"
            "requests>=2.31.0\n"
            "\n"
            "numpy ; python_version>='3.10'\n"
            "-e ./local-pkg\n"
            "git+https://github.com/foo/bar.git\n"
            "bim_repository==0.0.1\n",
            encoding="utf-8",
        )
        session = self._make_session(fake_names={"bim_repository"})
        results = validate_requirements_txt(
            req, cache_dir=tmp_path / "cache", session=session
        )
        names = [r.name for r in results]
        # requests, numpy, bim_repository — 3개만 (주석/VCS/-e 제외)
        assert "requests" in names
        assert "numpy" in names
        assert "bim_repository" in names
        assert len(names) == 3

    def test_extract_fake_packages_filters_only_false(self) -> None:
        results = [
            PyPIResult(name="real-pkg", exists=True),
            PyPIResult(name="fake-pkg", exists=False),
            PyPIResult(name="server-error-pkg", exists=None),
        ]
        fake = extract_fake_packages(results)
        assert fake == ["fake-pkg"]  # exists=None 은 가짜 list 제외 (보수적)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert validate_requirements_txt(tmp_path / "nope.txt") == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text("# 주석만\n\n", encoding="utf-8")
        assert validate_requirements_txt(req, cache_dir=tmp_path) == []


# =============================================================================
# 2. judge_convergence Rule -1 — fake_packages 분기
# =============================================================================
class TestRuleMinusOneFakePackage:
    def _gap_must_fix_0(self) -> GapReport:
        return GapReport(satisfied_count=5, unsatisfied_blockers=0)

    def test_1st_occurrence_yields_improve(self) -> None:
        """⭐ 1차 가짜 발견 → IMPROVE_NEEDED + '실존 패키지' 힌트."""
        decision = judge_convergence(
            self._gap_must_fix_0(),
            fake_packages=["bim_repository", "fake_pkg2"],
            consecutive_fake_iterations=0,
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert decision.blocked_cause == BlockedCause.NONE
        assert "1st occurrence" in decision.reason
        assert "bim_repository" in decision.reason
        assert "real PyPI packages" in decision.next_action

    def test_2nd_consecutive_yields_blocked(self) -> None:
        """⭐ 2차 연속 가짜 → BLOCKED(FAKE_PACKAGE) 강제."""
        decision = judge_convergence(
            self._gap_must_fix_0(),
            fake_packages=["bim_repository"],
            consecutive_fake_iterations=2,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.FAKE_PACKAGE
        assert "2 consecutive" in decision.reason or "consecutive iterations" in decision.reason
        assert "bim_repository" in decision.reason

    def test_3rd_consecutive_still_blocked(self) -> None:
        """3차+ → BLOCKED 유지."""
        decision = judge_convergence(
            self._gap_must_fix_0(),
            fake_packages=["a", "b"],
            consecutive_fake_iterations=3,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.FAKE_PACKAGE

    def test_no_fake_packages_skips_rule_minus_one(self) -> None:
        """fake_packages=None 또는 [] → Rule -1 skip → Rule 1 COMPLETE."""
        decision = judge_convergence(
            self._gap_must_fix_0(),
            fake_packages=None,
        )
        assert decision.verdict == Verdict.COMPLETE

        decision2 = judge_convergence(
            self._gap_must_fix_0(),
            fake_packages=[],
            consecutive_fake_iterations=5,  # count 크지만 list 빈 → skip
        )
        assert decision2.verdict == Verdict.COMPLETE

    def test_rule_minus_one_1st_occurrence_below_cap_improves(self) -> None:
        """1차 가짜 + iter < max → IMPROVE_NEEDED (Rule -1 정상, 회귀 0)."""
        gap = GapReport(unsatisfied_blockers=1, iteration=3)
        decision = judge_convergence(
            gap,
            max_iterations=5,
            fake_packages=["fake1"],
            consecutive_fake_iterations=0,  # 1차
        )
        assert decision.verdict == Verdict.IMPROVE_NEEDED

    def test_rule_minus_one_1st_occurrence_at_cap_blocked_by_p0_guard(self) -> None:
        """★ P0 회귀 수정 (PR #234): 1차 가짜라도 iter==max 면 하드 종료 가드가
        BLOCKED(ITERATION_CAP) 로 강제 전환.

        이전엔 Rule -1 1차 IMPROVE 가 Rule 4(ITERATION_CAP)를 *선점* 해(Rule 0 와
        동일한 cap-override 버그 패턴) max_iterations 를 넘겨 무한 IMPROVE 위험이
        있었다. P0 가드("IMPROVE + iter>=max → BLOCKED, must_fix 조건 무관")가
        '종료 > 품질' 원칙으로 교정한다. (가짜 패키지의 1차 IMPROVE 기회는
        iter < max 일 때만 의미 — 위 below_cap test 가 보존 검증.)
        """
        gap = GapReport(unsatisfied_blockers=1, iteration=5)
        decision = judge_convergence(
            gap,
            max_iterations=5,
            fake_packages=["fake1"],
            consecutive_fake_iterations=0,  # 1차
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.ITERATION_CAP


# =============================================================================
# 3. Tech Scout 노드 — iterative_loop 통합
# =============================================================================
class TestTechScoutNodeBehavior:
    def test_default_off_no_state_change(self, tmp_path: Path) -> None:
        """⭐ enable_tech_scout=False (default) → 회귀 0."""
        from src.workflows.iterative_loop import _node_tech_scout

        chain = MagicMock()
        chain.saved_dir = tmp_path
        state = {
            "enable_tech_scout": False,
            "chain_result": chain,
        }
        result = _node_tech_scout(state)
        assert result == {}  # state 변경 0

    def test_no_chain_result_returns_empty_fake(self, tmp_path: Path) -> None:
        from src.workflows.iterative_loop import _node_tech_scout

        state = {"enable_tech_scout": True, "chain_result": None}
        result = _node_tech_scout(state)
        assert result == {"fake_packages": []}

    def test_missing_requirements_resets_counter(self, tmp_path: Path) -> None:
        """requirements.txt 미존재 → fake_packages=[] + counter=0."""
        from src.workflows.iterative_loop import _node_tech_scout

        chain = MagicMock()
        chain.saved_dir = tmp_path  # requirements.txt 없음
        state = {
            "enable_tech_scout": True,
            "chain_result": chain,
            "consecutive_fake_iterations": 5,
        }
        result = _node_tech_scout(state)
        assert result["fake_packages"] == []
        assert result["consecutive_fake_iterations"] == 0  # ★ reset

    def test_fake_package_detected_increments_counter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """가짜 발견 → fake_packages 채움 + counter += 1."""
        from src.workflows.iterative_loop import _node_tech_scout

        req = tmp_path / "requirements.txt"
        req.write_text("bim_repository==0.0.1\nrequests>=2.31.0\n", encoding="utf-8")

        # mock validate_requirements_txt
        def mock_validate(req_path, **kwargs):
            return [
                PyPIResult(name="bim_repository", exists=False),
                PyPIResult(name="requests", exists=True, latest_version="2.31.0"),
            ]

        monkeypatch.setattr(
            "src.agents.research.validate_requirements_txt", mock_validate
        )

        chain = MagicMock()
        chain.saved_dir = tmp_path
        state = {
            "enable_tech_scout": True,
            "chain_result": chain,
            "consecutive_fake_iterations": 0,
        }
        result = _node_tech_scout(state)
        assert result["fake_packages"] == ["bim_repository"]
        assert result["consecutive_fake_iterations"] == 1

    def test_no_fake_resets_counter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """⭐ 가짜 사라지면 카운터 reset (1차 IMPROVE 후 Engineer 교체 성공 케이스)."""
        from src.workflows.iterative_loop import _node_tech_scout

        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31.0\n", encoding="utf-8")

        def mock_validate(req_path, **kwargs):
            return [PyPIResult(name="requests", exists=True)]

        monkeypatch.setattr(
            "src.agents.research.validate_requirements_txt", mock_validate
        )

        chain = MagicMock()
        chain.saved_dir = tmp_path
        state = {
            "enable_tech_scout": True,
            "chain_result": chain,
            "consecutive_fake_iterations": 1,  # 이전 iter 가짜 1회 있었음
        }
        result = _node_tech_scout(state)
        assert result["fake_packages"] == []
        assert result["consecutive_fake_iterations"] == 0  # ★ reset


# =============================================================================
# 4. ⭐ BIM 풀체인 시나리오 — judge_convergence + Tech Scout 결합
# =============================================================================
class TestBIMBenchmarkScenario:
    """⭐ BIM 환각 패키지 사례 — 1차 IMPROVE → 2차 연속 BLOCKED 흐름."""

    def test_bim_repository_first_iter_yields_improve(self) -> None:
        """Engineer 가 'bim_repository' 산출 (1차) → IMPROVE_NEEDED."""
        gap = GapReport(unsatisfied_blockers=0)  # Gap Analyst 는 COMPLETE 라고 함
        decision = judge_convergence(
            gap,
            fake_packages=["bim_repository"],
            consecutive_fake_iterations=0,
        )
        # Gap Analyst COMPLETE 라도 가짜 패키지 → Rule -1 IMPROVE 강제
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert "bim_repository" in decision.reason

    def test_bim_repository_persists_2_iters_yields_blocked(self) -> None:
        """Engineer 가 1차 IMPROVE 받고도 가짜 패키지 다시 산출 → BLOCKED."""
        gap = GapReport(unsatisfied_blockers=0)
        decision = judge_convergence(
            gap,
            fake_packages=["bim_repository_v2"],  # 다른 가짜
            consecutive_fake_iterations=2,
        )
        assert decision.verdict == Verdict.BLOCKED
        assert decision.blocked_cause == BlockedCause.FAKE_PACKAGE


# =============================================================================
# 5. CLI integration — --enable-tech-scout flag
# =============================================================================
class TestCLIFlag:
    def test_flag_parses_default_off(self) -> None:
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = ["run.py", "--request", "X", "--non-interactive"]
            from scripts.run import _parse_args

            args = _parse_args()
            assert args.enable_tech_scout is False
        finally:
            _sys.argv = prev

    def test_flag_parses_explicit_on(self) -> None:
        import sys as _sys

        prev = _sys.argv
        try:
            _sys.argv = [
                "run.py", "--request", "X", "--enable-tech-scout", "--non-interactive",
            ]
            from scripts.run import _parse_args

            args = _parse_args()
            assert args.enable_tech_scout is True
            # 기존 flag 와 독립
            assert args.enable_boardroom is False
            assert args.enable_tikitaka is False
        finally:
            _sys.argv = prev

    def test_run_iterative_loop_accepts_enable_tech_scout(self) -> None:
        import inspect

        from src.workflows.iterative_loop import run_iterative_loop

        sig = inspect.signature(run_iterative_loop)
        assert "enable_tech_scout" in sig.parameters
        assert sig.parameters["enable_tech_scout"].default is False


# =============================================================================
# 6. Telemetry — tech_scout 노드 dept="learning" 매핑
# =============================================================================
class TestTechScoutTelemetryDept:
    def test_tech_scout_node_in_department_mapping(self) -> None:
        from src.monitoring.telemetry import (
            LEARNING,
            _NODE_DEPARTMENT,
            department_for_node,
        )

        assert _NODE_DEPARTMENT["tech_scout"] == LEARNING
        assert department_for_node("tech_scout") == "learning"


# =============================================================================
# 7. ⭐ Integration — real PyPI (BIM 본질, CI 기본 실행에서 제외 권장)
# =============================================================================
@pytest.mark.integration
class TestRealPyPIBIMCase:
    def test_real_pypi_bim_repository_fake_detected(self, tmp_path: Path) -> None:
        """⭐ 실제 BIM 환각 사례 — 'bim_repository' PyPI 404 확정 검증."""
        req = tmp_path / "requirements.txt"
        req.write_text(
            "requests>=2.31.0\n"
            "bim_repository==0.0.1\n",  # ← 환각 패키지
            encoding="utf-8",
        )
        results = validate_requirements_txt(req, cache_dir=tmp_path / "cache")
        names = {r.name: r.exists for r in results}
        # 5xx 변동성 cover — None 도 허용
        assert names.get("requests") in (True, None)
        # bim_repository 는 PyPI 에 *실존 안 함* — False 또는 5xx 시 None
        assert names.get("bim_repository") in (False, None)

        fake = extract_fake_packages(results)
        # 5xx 변동 시 fake 빈 list 가능 — 단 'requests' 는 제외 확정
        assert "requests" not in fake
