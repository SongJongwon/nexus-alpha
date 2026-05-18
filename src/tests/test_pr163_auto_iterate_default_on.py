# -*- coding: utf-8 -*-
"""PR #163 — --auto-iterate 기본 ON 전환 + 비용 안내 banner.

배경 (2026-05-18 E2E 재재검증 PASS):
    PR #160a+b + PR #162 라이브 검증 완료 — `--auto-iterate --max-iterations 1` 실
    행 결과 verdict=COMPLETE iterations=1/1 / Vision SKIPPED / QA loop PASS skipped=1
    / .exe 10.70 MB 정상 산출 / GUI 동작 확인. 본 PR 이 자기 진화 cycle 의
    *production default* 화 마지막 단계.

PR #163 처방:

    A. `--auto-iterate` default=False → True
        명시 OFF flag `--no-auto-iterate` 추가 (action=store_false). 기존 사용자가
        명시 인자 없이 호출 시 *auto-iterate 활성* 으로 작동.

    B. `--max-iterations` default 5 → 3 (보수적)
        design doc §7-1 의 *5회 초과 = 요구 정의 자체 의심* 신호 기준에서 보수적
        하향. 사용자 대기 시간 소지감 + 비용 폭증 회피 (~125min/$25 → ~75min/$15).

    C. 비용 안내 banner + Enter 대기 (`_confirm_auto_iterate_cost`)
        main() 의 "실행 시작" 직후 호출. max_iterations × ~25min × ~$5/iter 최악치
        표시 + 명시 confirm. non-interactive 모드는 안내만 (자동 confirm).
        Ctrl-C / EOF / 'n' 답변 시 중단 (exit 1).

본 테스트:
    1. argparse 기본값 — auto_iterate=True / max_iterations=3
    2. --no-auto-iterate flag → auto_iterate=False
    3. `_confirm_auto_iterate_cost` 비용 추정 정확성
    4. `_confirm_auto_iterate_cost` interactive 분기 (Enter / 'n' / KeyboardInterrupt / EOF)
    5. `_confirm_auto_iterate_cost` non-interactive 분기 (자동 True)
    6. main() 통합 — auto_iterate=True 시 banner 호출 + 사용자 중단 시 exit 1
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr163", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr163"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. argparse 기본값 — auto_iterate=True + max_iterations=3
# ---------------------------------------------------------------------------


def test_default_auto_iterate_is_true(run_mod):
    """기본 호출 시 auto_iterate=True (PR #163 기본 ON 전환)."""
    args = run_mod._parse_args(["--request", "테스트", "--non-interactive"])
    assert args.auto_iterate is True


def test_default_max_iterations_is_three(run_mod):
    """기본 max_iterations=3 (PR #163 5 → 3 하향)."""
    args = run_mod._parse_args(["--request", "테스트", "--non-interactive"])
    assert args.max_iterations == 3


def test_explicit_auto_iterate_flag_still_works(run_mod):
    """`--auto-iterate` 명시 시도 동일 결과 (회귀 차단)."""
    args = run_mod._parse_args(
        ["--request", "테스트", "--non-interactive", "--auto-iterate"]
    )
    assert args.auto_iterate is True


# ---------------------------------------------------------------------------
# 2. --no-auto-iterate opt-out flag
# ---------------------------------------------------------------------------


def test_no_auto_iterate_flag_disables(run_mod):
    """`--no-auto-iterate` 명시 시 auto_iterate=False."""
    args = run_mod._parse_args(
        ["--request", "테스트", "--non-interactive", "--no-auto-iterate"]
    )
    assert args.auto_iterate is False


def test_no_auto_iterate_overrides_default_only(run_mod):
    """`--no-auto-iterate` 만 줘도 다른 기본값 영향 없음."""
    args = run_mod._parse_args(
        ["--request", "테스트", "--non-interactive", "--no-auto-iterate"]
    )
    assert args.auto_iterate is False
    assert args.max_iterations == 3  # 기본값 유지


def test_explicit_both_flags_last_wins(run_mod):
    """`--auto-iterate --no-auto-iterate` 순서대로 — argparse 자체 규칙 (마지막 wins)."""
    args = run_mod._parse_args(
        ["--request", "테스트", "--non-interactive",
         "--auto-iterate", "--no-auto-iterate"]
    )
    assert args.auto_iterate is False
    # 역순
    args2 = run_mod._parse_args(
        ["--request", "테스트", "--non-interactive",
         "--no-auto-iterate", "--auto-iterate"]
    )
    assert args2.auto_iterate is True


# ---------------------------------------------------------------------------
# 3. _confirm_auto_iterate_cost 비용 추정 정확성
# ---------------------------------------------------------------------------


def test_cost_banner_shows_max_iterations_min_usd(run_mod, capsys):
    """banner 가 max_iter × 25min × $5/iter 최악 비용 표시."""
    args = SimpleNamespace(max_iterations=3, non_interactive=True)
    run_mod._confirm_auto_iterate_cost(args)
    out = capsys.readouterr().out
    assert "auto-iterate" in out
    assert "max_iterations = 3" in out
    # 3 × 25 = 75min
    assert "75min" in out
    # 3 × 5 = $15
    assert "$15" in out
    # cycle 요약 포함
    assert "recall" in out
    assert "curate" in out


def test_cost_banner_scales_with_max_iterations(run_mod, capsys):
    """max_iterations 가 1 / 5 / 10 일 때 정확하게 스케일."""
    for n, expected_min, expected_usd in [(1, 25, 5), (5, 125, 25), (10, 250, 50)]:
        args = SimpleNamespace(max_iterations=n, non_interactive=True)
        run_mod._confirm_auto_iterate_cost(args)
        out = capsys.readouterr().out
        assert f"max_iterations = {n}" in out
        assert f"{expected_min}min" in out
        assert f"${expected_usd}" in out


def test_cost_banner_clamps_zero_iterations(run_mod, capsys):
    """max_iterations=0 — 1 로 clamp (banner 표시 깔끔성)."""
    args = SimpleNamespace(max_iterations=0, non_interactive=True)
    run_mod._confirm_auto_iterate_cost(args)
    out = capsys.readouterr().out
    # clamp 결과 — 비용 = 1 × $5 = $5
    assert "$5" in out


# ---------------------------------------------------------------------------
# 4. _confirm_auto_iterate_cost interactive 분기
# ---------------------------------------------------------------------------


def test_confirm_returns_true_on_enter(run_mod):
    """Enter (빈 입력) → True 반환 (계속 진행)."""
    args = SimpleNamespace(max_iterations=3, non_interactive=False)
    result = run_mod._confirm_auto_iterate_cost(args, input_fn=lambda _: "")
    assert result is True


def test_confirm_returns_false_on_n(run_mod):
    """'n' 답변 → False (중단)."""
    args = SimpleNamespace(max_iterations=3, non_interactive=False)
    result = run_mod._confirm_auto_iterate_cost(args, input_fn=lambda _: "n")
    assert result is False


def test_confirm_returns_false_on_no(run_mod):
    """'no' 답변 → False (중단)."""
    args = SimpleNamespace(max_iterations=3, non_interactive=False)
    result = run_mod._confirm_auto_iterate_cost(args, input_fn=lambda _: "no")
    assert result is False


def test_confirm_returns_false_on_keyboard_interrupt(run_mod):
    """Ctrl-C (KeyboardInterrupt) → False."""
    def _raise(_):
        raise KeyboardInterrupt

    args = SimpleNamespace(max_iterations=3, non_interactive=False)
    result = run_mod._confirm_auto_iterate_cost(args, input_fn=_raise)
    assert result is False


def test_confirm_returns_false_on_eof(run_mod):
    """EOF (Ctrl-D, pipe 닫힘) → False."""
    def _raise(_):
        raise EOFError

    args = SimpleNamespace(max_iterations=3, non_interactive=False)
    result = run_mod._confirm_auto_iterate_cost(args, input_fn=_raise)
    assert result is False


# ---------------------------------------------------------------------------
# 5. non-interactive 분기 — 자동 confirm
# ---------------------------------------------------------------------------


def test_confirm_auto_returns_true_in_non_interactive(run_mod, capsys):
    """non-interactive 모드 — input 호출 없이 True 반환 (자동 confirm)."""
    args = SimpleNamespace(max_iterations=3, non_interactive=True)

    def _should_not_call(_):
        raise AssertionError("non-interactive 모드인데 input_fn 호출됨")

    result = run_mod._confirm_auto_iterate_cost(args, input_fn=_should_not_call)
    assert result is True
    out = capsys.readouterr().out
    assert "non-interactive" in out
    assert "자동 확인" in out


# ---------------------------------------------------------------------------
# 6. main() 통합 — auto_iterate=True 시 banner 호출
# ---------------------------------------------------------------------------


def test_main_aborts_on_cost_confirm_decline(run_mod, capsys):
    """auto_iterate=True + 사용자 'n' → main() exit=1."""
    with patch.object(run_mod, "_confirm_auto_iterate_cost", return_value=False) as confirm, \
         patch.object(run_mod, "_run_track_a") as run_a:
        exit_code = run_mod.main([
            "--request", "테스트",
            "--track", "A",
            "--build",
            "--non-interactive",
        ])
        # _confirm_auto_iterate_cost 가 False → main exit=1, _run_track_a 미호출
        confirm.assert_called_once()
        run_a.assert_not_called()
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "사용자 중단" in err


def test_main_proceeds_when_no_auto_iterate(run_mod):
    """--no-auto-iterate 시 banner 호출 없이 직진 (회귀 차단)."""
    with patch.object(run_mod, "_confirm_auto_iterate_cost") as confirm, \
         patch.object(run_mod, "_run_track_a", return_value=0) as run_a:
        exit_code = run_mod.main([
            "--request", "테스트",
            "--track", "A",
            "--build",
            "--non-interactive",
            "--no-auto-iterate",
        ])
        confirm.assert_not_called()
        run_a.assert_called_once()
    assert exit_code == 0


def test_main_proceeds_when_cost_confirmed(run_mod):
    """auto_iterate=True (기본) + confirm=True → _run_track_a 정상 호출."""
    with patch.object(run_mod, "_confirm_auto_iterate_cost", return_value=True) as confirm, \
         patch.object(run_mod, "_run_track_a", return_value=0) as run_a:
        exit_code = run_mod.main([
            "--request", "테스트",
            "--track", "A",
            "--build",
            "--non-interactive",
        ])
        confirm.assert_called_once()
        run_a.assert_called_once()
    assert exit_code == 0


# ---------------------------------------------------------------------------
# 7. file-text — argparse default 변경이 코드에 명시 반영 (회귀 차단)
# ---------------------------------------------------------------------------


def test_run_py_argparse_default_true():
    """scripts/run.py 의 --auto-iterate default=True (PR #163)."""
    text = RUN_PY.read_text(encoding="utf-8")
    # action="store_true", default=True 패턴 (auto_iterate 만)
    assert 'dest="auto_iterate", action="store_true", default=True' in text


def test_run_py_no_auto_iterate_flag_exists():
    """--no-auto-iterate flag 등록 (PR #163 opt-out)."""
    text = RUN_PY.read_text(encoding="utf-8")
    assert "--no-auto-iterate" in text
    assert 'dest="auto_iterate", action="store_false"' in text


def test_run_py_max_iterations_default_three():
    """--max-iterations default=3 (PR #163 5 → 3)."""
    text = RUN_PY.read_text(encoding="utf-8")
    # default=3 으로 표기되어 있어야 함
    assert "default=3" in text
