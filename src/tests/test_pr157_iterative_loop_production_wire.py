# -*- coding: utf-8 -*-
"""PR #157 — iterative_loop production wire 회귀 차단.

배경 (본 세션 PR #150~#155 후 식별된 마지막 갭):
    ``run_iterative_loop`` 는 LangGraph 풀체인 (recall → kickoff → chain → sandbox →
    gap → judge → retrospective → curate) 완성되어 있고 1196+ 테스트가 cover. 그러나
    ``scripts/run.py`` 의 Track A 진입은 ``run_analyze_and_implement`` *직접* 호출
    (1회만). 결과: production path 에서 *자기 진화 cycle 미작동*.

    추가 갭: ``run_iterative_loop`` 시그니처에 ``enable_executor`` / ``enable_publish``
    / ``publish_as_draft`` / ``executor_timeout_sec`` / ``publish_timeout_sec`` /
    ``verbose`` 누락 → 호출 시 .exe 빌드 + Draft Release 미실행.

PR #157 처방 (Path D — opt-in 기본 OFF, 단일 PR):
    1. ``run_iterative_loop`` 시그니처 + ``_LoopState`` + ``_node_run_chain`` 에 6
       args propagate
    2. ``--auto-iterate`` CLI 플래그 (Track A only, 기본 OFF) + ``--max-iterations N``
    3. 진입 시 ``run_iterative_loop`` 호출 → LoopOutcome.final_chain_result 를 result
       변수로 매핑 → Vision QA + retry + 결과 패널 동일 흐름 재사용
    4. 결과 패널에 ``🔄 Iterate: verdict=COMPLETE iterations=2/5`` 라인 추가

본 테스트:
    1. 시그니처 propagation: run_iterative_loop 6 신규 kwargs 수용
    2. _node_run_chain 이 state 의 신규 키들을 analyze_and_implement 에 전달
    3. CLI 플래그 등록 + 기본값
    4. _run_track_a 분기: auto_iterate=True → run_iterative_loop 호출
    5. _run_track_a 분기: auto_iterate=False (기본) → run_analyze_and_implement 직접 호출
    6. LoopOutcome → result 매핑 (final_chain_result 추출 + None fallback)
    7. _print_result_summary 가 iterative_summary 매개변수 수용
    8. 결과 패널에 🔄 Iterate 라인 출력
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr157", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr157"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. run_iterative_loop 시그니처 — 6 신규 kwargs
# ---------------------------------------------------------------------------


def test_run_iterative_loop_accepts_enable_executor_kwarg() -> None:
    """``run_iterative_loop`` 가 ``enable_executor`` 등 6 신규 kwargs 수용."""
    import inspect

    from src.workflows.iterative_loop import run_iterative_loop

    sig = inspect.signature(run_iterative_loop)
    params = sig.parameters
    for key in (
        "enable_executor",
        "executor_timeout_sec",
        "enable_publish",
        "publish_as_draft",
        "publish_timeout_sec",
        "verbose",
    ):
        assert key in params, (
            f"run_iterative_loop 시그니처에 ``{key}`` 누락 — PR #157 회귀"
        )


def test_run_iterative_loop_executor_defaults_off() -> None:
    """신규 kwargs 기본값 — backward compat 보존."""
    import inspect

    from src.workflows.iterative_loop import run_iterative_loop

    sig = inspect.signature(run_iterative_loop)
    assert sig.parameters["enable_executor"].default is False
    assert sig.parameters["enable_publish"].default is False
    assert sig.parameters["publish_as_draft"].default is True
    assert sig.parameters["verbose"].default is False


# ---------------------------------------------------------------------------
# 2. _node_run_chain — state 의 신규 키들을 analyze_and_implement 에 전달
# ---------------------------------------------------------------------------


def test_node_run_chain_propagates_enable_executor(monkeypatch) -> None:
    """_node_run_chain 이 state.enable_executor 를 analyze_and_implement 에 전달."""
    from src.workflows import iterative_loop as IL

    captured: dict = {}

    def _fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            saved_dir=Path("/tmp/fake_chain"),
            engineer_output="x",
            qa_review="y",
            executor_result=None,
        )

    monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)

    state = {
        "user_request": "test",
        "iteration": 0,
        "outputs_dir": "/tmp/fake_outputs",
        "feedback": "",
        "enable_executor": True,
        "executor_timeout_sec": 600,
        "enable_publish": True,
        "publish_as_draft": False,
        "publish_timeout_sec": 240,
        "verbose": True,
    }
    IL._node_run_chain(state)  # type: ignore[arg-type]

    # propagate 검증 — 6 args 모두 state 값 그대로 전달
    assert captured["enable_executor"] is True
    assert captured["executor_timeout_sec"] == 600
    assert captured["enable_publish"] is True
    assert captured["publish_as_draft"] is False
    assert captured["publish_timeout_sec"] == 240
    assert captured["verbose"] is True


def test_node_run_chain_defaults_when_state_missing(monkeypatch) -> None:
    """state 에 신규 키 없으면 안전한 기본값 (executor=False, verbose=False)."""
    from src.workflows import iterative_loop as IL

    captured: dict = {}

    def _fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            saved_dir=Path("/tmp/fake"),
            engineer_output="",
            qa_review="",
            executor_result=None,
        )

    monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_run)

    state = {
        "user_request": "test",
        "iteration": 0,
        "outputs_dir": "/tmp/fake_outputs",
        "feedback": "",
        # 신규 키 미포함 — backward compat
    }
    IL._node_run_chain(state)  # type: ignore[arg-type]

    assert captured["enable_executor"] is False
    assert captured["enable_publish"] is False
    assert captured["publish_as_draft"] is True
    assert captured["verbose"] is False


# ---------------------------------------------------------------------------
# 3. CLI 플래그 — --auto-iterate + --max-iterations
# ---------------------------------------------------------------------------


def test_argparse_has_auto_iterate_flag() -> None:
    text = RUN_PY.read_text(encoding="utf-8")
    assert "--auto-iterate" in text, (
        "argparse 에 --auto-iterate 미등록 — PR #157 회귀"
    )


def test_argparse_has_max_iterations_flag() -> None:
    text = RUN_PY.read_text(encoding="utf-8")
    assert "--max-iterations" in text


def test_auto_iterate_defaults_to_true(run_mod) -> None:
    """기본 ON — PR #163 (2026-05-18) 전환. 명시 OFF 는 --no-auto-iterate."""
    args = run_mod._parse_args(["--request", "x", "--non-interactive"])
    assert args.auto_iterate is True


def test_max_iterations_defaults_to_3(run_mod) -> None:
    """기본 3 — PR #163 (2026-05-18) 보수적 하향 (이전 5)."""
    args = run_mod._parse_args(["--request", "x", "--non-interactive"])
    assert args.max_iterations == 3


def test_auto_iterate_can_be_enabled(run_mod) -> None:
    args = run_mod._parse_args(
        ["--request", "x", "--non-interactive", "--auto-iterate"]
    )
    assert args.auto_iterate is True


# ---------------------------------------------------------------------------
# 4. _run_track_a 분기 — auto_iterate 시 run_iterative_loop 호출
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> SimpleNamespace:
    base = {
        "request": "계산기",
        "verbose": False,
        "build": False,
        "force_cli": False,
        "release": False,
        "repo": "",
        "tag": "",
        "no_vision_qa": True,  # 테스트에서 Vision QA 분기 차단
        "vision_qa_max_retries": 0,
        "auto_iterate": False,
        "max_iterations": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_track_a_default_path_calls_analyze_and_implement(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """auto_iterate=False (기본) → run_analyze_and_implement 직접 호출 (backward compat)."""
    aai_calls: list = []
    iter_calls: list = []

    def _fake_aai(*args, **kwargs):
        aai_calls.append(kwargs)
        return SimpleNamespace(
            saved_dir=tmp_path,
            executor_result=None,
            publish_result=None,
            gui_code_output="",
        )

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        raise AssertionError("auto_iterate=False 인데 run_iterative_loop 호출됨")

    from src.workflows import analyze_and_implement as aai_mod
    monkeypatch.setattr(aai_mod, "run_analyze_and_implement", _fake_aai)
    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    args = _make_args()
    rc = run_mod._run_track_a(args)
    assert rc == 0
    assert len(aai_calls) == 1
    assert iter_calls == []


def test_track_a_auto_iterate_path_calls_run_iterative_loop(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """auto_iterate=True → run_iterative_loop 호출 (run_analyze_and_implement 직접 호출 X)."""
    aai_direct_calls: list = []
    iter_calls: list = []

    def _fake_aai_direct(*args, **kwargs):
        aai_direct_calls.append(kwargs)
        raise AssertionError("auto_iterate=True 인데 run_analyze_and_implement 직접 호출됨")

    fake_chain = SimpleNamespace(
        saved_dir=tmp_path,
        executor_result=None,
        publish_result=None,
        gui_code_output="",
    )

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        return SimpleNamespace(
            final_chain_result=fake_chain,
            verdict=SimpleNamespace(value="COMPLETE"),
            iterations_run=2,
        )

    from src.workflows import analyze_and_implement as aai_mod
    monkeypatch.setattr(aai_mod, "run_analyze_and_implement", _fake_aai_direct)
    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    args = _make_args(auto_iterate=True, max_iterations=3)
    rc = run_mod._run_track_a(args)
    assert rc == 0
    assert aai_direct_calls == []
    assert len(iter_calls) == 1
    # max_iterations 정확히 전달
    assert iter_calls[0]["max_iterations"] == 3


def test_track_a_auto_iterate_passes_executor_publish_args(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """auto_iterate + --build + --release → enable_executor/enable_publish True 전달."""
    iter_calls: list = []

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        return SimpleNamespace(
            final_chain_result=SimpleNamespace(
                saved_dir=tmp_path, executor_result=None, publish_result=None,
                gui_code_output="",
            ),
            verdict=SimpleNamespace(value="COMPLETE"),
            iterations_run=1,
        )

    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    args = _make_args(
        auto_iterate=True, build=True, release=True, repo="owner/repo"
    )
    run_mod._run_track_a(args)
    captured = iter_calls[0]
    assert captured["enable_executor"] is True
    assert captured["enable_publish"] is True
    assert captured["publish_as_draft"] is True
    assert captured["repo_url"] == "owner/repo"


def test_track_a_auto_iterate_falls_back_on_none_final_chain(
    run_mod, monkeypatch, tmp_path: Path, capsys
) -> None:
    """LoopOutcome.final_chain_result=None → dummy result fallback (AttributeError 회피)."""
    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(
        il_mod, "run_iterative_loop",
        lambda *a, **kw: SimpleNamespace(
            final_chain_result=None,
            verdict=SimpleNamespace(value="BLOCKED"),
            iterations_run=5,
        ),
    )

    args = _make_args(auto_iterate=True)
    rc = run_mod._run_track_a(args)
    assert rc == 0
    # 출력에 verdict/iterations 표시 — 워크플로 차단 X
    captured = capsys.readouterr().out
    assert "Iterate" in captured
    assert "BLOCKED" in captured


# ---------------------------------------------------------------------------
# 5. 결과 패널 — iterative_summary 매개변수
# ---------------------------------------------------------------------------


def test_print_result_summary_accepts_iterative_summary(
    run_mod, capsys
) -> None:
    """``_print_result_summary`` 가 ``iterative_summary`` kwarg 수용 + 출력."""
    run_mod._print_result_summary(
        track="A",
        elapsed_sec=600.0,
        outputs_dir=None,
        exe_path=None,
        release_url=None,
        iterative_summary="verdict=COMPLETE iterations=2/5",
    )
    captured = capsys.readouterr().out
    assert "Iterate" in captured
    assert "COMPLETE" in captured
    assert "2/5" in captured


def test_print_result_summary_signature_has_iterative_summary() -> None:
    """``_print_result_summary`` 시그니처 회귀 차단."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_print_result_summary\([^)]*\)", text, re.DOTALL
    )
    assert match is not None
    assert "iterative_summary" in match.group(0)


# ---------------------------------------------------------------------------
# 6. Wiring file-text 회귀 — Track A 분기 코드 존재
# ---------------------------------------------------------------------------


def test_track_a_imports_run_iterative_loop_in_auto_branch() -> None:
    """``_run_track_a`` 본문에 ``run_iterative_loop`` 호출 — auto-iterate wiring."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_a[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "run_iterative_loop" in body, (
        "Track A 가 run_iterative_loop 호출 안 함 — PR #157 회귀"
    )
    assert "args.auto_iterate" in body, (
        "Track A 가 args.auto_iterate 분기 안 함 — PR #157 회귀"
    )
