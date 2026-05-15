# -*- coding: utf-8 -*-
"""PR #158 — Track B run_iterative_loop 진입 회귀 차단.

배경 (PR #157 사후 — Track A 만 wiring):
    PR #157 이 ``--auto-iterate`` 를 Track A 에 도입. Track B 는 ``run_automate_workflow``
    호출이라 iterative_loop 와 결과 구조 불일치 (``AutomateWorkflowResult`` 는
    ``agent_output``/``code_qa_result``, iterative_loop 는 ``engineer_output``/
    ``qa_review`` 요구). 결과: Track B 사용자에게 *자기 진화 cycle 미제공*.

PR #158 처방 (Option A — 어댑터 layer, 사용자 confirm):
    1. ``_adapt_automate_to_chain_result`` 신설 — AutomateWorkflowResult →
       WorkflowResult-like SimpleNamespace duck type. agent_output → engineer_output,
       code_qa_result.summary_line() → qa_review 매핑
    2. ``run_iterative_loop`` 에 ``track="A"|"B"`` + ``release_tag`` kwargs 추가
    3. ``_node_run_chain`` 이 state["track"]=="B" 면 ``run_automate_workflow`` 호출 →
       어댑터 → chain_result 로 사용. 나머지 노드 (recall/kickoff/sandbox/gap/judge/
       retrospective/curate) 동일 작동
    4. ``_run_track_b`` 에 ``--auto-iterate`` 분기 (PR #157 패턴 재사용)

본 테스트:
    1. _adapt_automate_to_chain_result 매핑 (agent_output → engineer_output 등)
    2. run_iterative_loop 시그니처 track + release_tag kwargs
    3. _node_run_chain 분기 (track="A" → analyze, track="B" → automate)
    4. _run_track_b 분기 (default → automate / auto_iterate → iterative_loop track="B")
    5. 결과 패널 iterative_summary 표시
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("alpha_run_pr158", RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run_pr158"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. _adapt_automate_to_chain_result 매핑
# ---------------------------------------------------------------------------


def test_adapter_maps_agent_output_to_engineer_output() -> None:
    """``agent_output`` → ``engineer_output`` 매핑 (Gap Analyst 입력 호환)."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    automate = SimpleNamespace(
        agent_output="web scraping 산출",
        code_qa_result=None,
        saved_dir=Path("/tmp/fake"),
        saved_code_files=[],
        executor_result=None,
        publish_result=None,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert adapted.engineer_output == "web scraping 산출"


def test_adapter_maps_code_qa_summary_to_qa_review() -> None:
    """``code_qa_result.summary_line()`` → ``qa_review`` 매핑."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    code_qa = SimpleNamespace(summary_line=lambda: "[CODE_QA PASS] pytest=4/4")
    automate = SimpleNamespace(
        agent_output="x",
        code_qa_result=code_qa,
        saved_dir=Path("/tmp"),
        saved_code_files=[],
        executor_result=None,
        publish_result=None,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert adapted.qa_review == "[CODE_QA PASS] pytest=4/4"


def test_adapter_falls_back_when_code_qa_missing() -> None:
    """code_qa_result=None → qa_review 에 폴백 안내 문자열."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    automate = SimpleNamespace(
        agent_output="x",
        code_qa_result=None,
        saved_dir=Path("/tmp"),
        saved_code_files=[],
        executor_result=None,
        publish_result=None,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert "no QA review" in adapted.qa_review
    assert "Track B" in adapted.qa_review


def test_adapter_passes_through_executor_and_publish_result() -> None:
    """executor_result / publish_result 직접 매핑 (Vision QA + 결과 패널 호환)."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    exe = SimpleNamespace(exe_path=Path("/tmp/app.exe"), success=True)
    pub = SimpleNamespace(release_url="https://github.com/...")
    automate = SimpleNamespace(
        agent_output="x",
        code_qa_result=None,
        saved_dir=Path("/tmp"),
        saved_code_files=[],
        executor_result=exe,
        publish_result=pub,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert adapted.executor_result is exe
    assert adapted.publish_result is pub


def test_adapter_sets_empty_gui_fields_for_track_b() -> None:
    """Track B 는 GUI/UI 디자인 산출 없음 → 빈 문자열로 매핑 (retry helper CLI 분기 보장)."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    automate = SimpleNamespace(
        agent_output="x", code_qa_result=None, saved_dir=Path("/tmp"),
        saved_code_files=[], executor_result=None, publish_result=None,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert adapted.gui_code_output == ""
    assert adapted.ui_spec == ""
    assert adapted.design_tokens == ""


def test_adapter_swallows_code_qa_summary_exception() -> None:
    """code_qa_result.summary_line() 가 예외 → 폴백 (graceful)."""
    from src.workflows.iterative_loop import _adapt_automate_to_chain_result

    class _BrokenQA:
        def summary_line(self):
            raise RuntimeError("boom")

    automate = SimpleNamespace(
        agent_output="x", code_qa_result=_BrokenQA(), saved_dir=Path("/tmp"),
        saved_code_files=[], executor_result=None, publish_result=None,
    )
    adapted = _adapt_automate_to_chain_result(automate)
    assert "no QA review" in adapted.qa_review


# ---------------------------------------------------------------------------
# 2. run_iterative_loop 시그니처 — track + release_tag
# ---------------------------------------------------------------------------


def test_run_iterative_loop_accepts_track_kwarg() -> None:
    from src.workflows.iterative_loop import run_iterative_loop

    sig = inspect.signature(run_iterative_loop)
    assert "track" in sig.parameters
    assert sig.parameters["track"].default == "A"


def test_run_iterative_loop_accepts_release_tag_kwarg() -> None:
    from src.workflows.iterative_loop import run_iterative_loop

    sig = inspect.signature(run_iterative_loop)
    assert "release_tag" in sig.parameters
    assert sig.parameters["release_tag"].default == ""


# ---------------------------------------------------------------------------
# 3. _node_run_chain 분기 — track A → analyze, track B → automate
# ---------------------------------------------------------------------------


def test_node_run_chain_track_a_calls_analyze_and_implement(monkeypatch) -> None:
    from src.workflows import iterative_loop as IL

    aai_calls: list = []
    aw_calls: list = []

    def _fake_aai(*args, **kwargs):
        aai_calls.append(kwargs)
        return SimpleNamespace(
            saved_dir=Path("/tmp/aai"), engineer_output="x", qa_review="y",
            executor_result=None,
        )

    def _fake_aw(*args, **kwargs):
        aw_calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_aai)
    import src.workflows.automate_workflow as aw_mod
    monkeypatch.setattr(aw_mod, "run_automate_workflow", _fake_aw)

    state = {
        "user_request": "x", "iteration": 0, "outputs_dir": "/tmp/out", "feedback": "",
        "track": "A",
    }
    IL._node_run_chain(state)  # type: ignore[arg-type]
    assert len(aai_calls) == 1
    assert aw_calls == []


def test_node_run_chain_track_b_calls_automate_workflow(monkeypatch) -> None:
    from src.workflows import iterative_loop as IL

    aai_calls: list = []
    aw_calls: list = []

    def _fake_aai(*args, **kwargs):
        aai_calls.append(kwargs)
        return SimpleNamespace()

    def _fake_aw(*args, **kwargs):
        aw_calls.append(kwargs)
        return SimpleNamespace(
            agent_output="track B 산출",
            code_qa_result=None,
            saved_dir=Path("/tmp/aw"),
            saved_code_files=[],
            executor_result=None,
            publish_result=None,
        )

    monkeypatch.setattr(IL, "run_analyze_and_implement", _fake_aai)
    import src.workflows.automate_workflow as aw_mod
    monkeypatch.setattr(aw_mod, "run_automate_workflow", _fake_aw)

    state = {
        "user_request": "x", "iteration": 0, "outputs_dir": "/tmp/out", "feedback": "",
        "track": "B",
        "enable_build_branch": True,
        "enable_executor": True,
    }
    IL._node_run_chain(state)  # type: ignore[arg-type]
    assert aai_calls == []
    assert len(aw_calls) == 1
    # Track A → Track B args mapping 검증
    aw_kwargs = aw_calls[0]
    assert aw_kwargs["enable_build"] is True
    assert aw_kwargs["enable_qa_loop"] is True  # build 와 함께 활성


def test_node_run_chain_track_b_propagates_release_tag(monkeypatch) -> None:
    """Track B 가 release_tag 전달."""
    from src.workflows import iterative_loop as IL

    aw_calls: list = []

    def _fake_aw(*args, **kwargs):
        aw_calls.append(kwargs)
        return SimpleNamespace(
            agent_output="x", code_qa_result=None, saved_dir=Path("/tmp"),
            saved_code_files=[], executor_result=None, publish_result=None,
        )

    import src.workflows.automate_workflow as aw_mod
    monkeypatch.setattr(aw_mod, "run_automate_workflow", _fake_aw)

    state = {
        "user_request": "x", "iteration": 0, "outputs_dir": "/tmp/out", "feedback": "",
        "track": "B",
        "release_tag": "v0.5.0",
        "enable_publish": True,
    }
    IL._node_run_chain(state)  # type: ignore[arg-type]
    assert aw_calls[0]["release_tag"] == "v0.5.0"
    assert aw_calls[0]["enable_release"] is True


# ---------------------------------------------------------------------------
# 4. _run_track_b 분기 — auto_iterate 시 run_iterative_loop(track="B") 호출
# ---------------------------------------------------------------------------


def _make_track_b_args(**overrides) -> SimpleNamespace:
    base = {
        "request": "네이버 쇼핑 가격 크롤링",
        "verbose": False,
        "build": False,
        "no_vision_qa": True,
        "vision_qa_max_retries": 0,
        "release": False,
        "repo": "",
        "tag": "",
        "auto_iterate": False,
        "max_iterations": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_track_b_default_path_calls_automate_workflow(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """auto_iterate=False (기본) → run_automate_workflow 직접 호출 (backward compat)."""
    aw_calls: list = []
    iter_calls: list = []

    def _fake_aw(*args, **kwargs):
        aw_calls.append(kwargs)
        return SimpleNamespace(
            saved_dir=tmp_path, saved_code_files=[],
            executor_result=None, publish_result=None,
        )

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        raise AssertionError("auto_iterate=False 인데 run_iterative_loop 호출됨")

    from src.workflows import automate_workflow as aw_mod
    monkeypatch.setattr(aw_mod, "run_automate_workflow", _fake_aw)
    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    rc = run_mod._run_track_b(_make_track_b_args())
    assert rc == 0
    assert len(aw_calls) == 1
    assert iter_calls == []


def test_track_b_auto_iterate_path_calls_run_iterative_loop_with_track_b(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """auto_iterate=True → run_iterative_loop 호출 + track="B" 전달."""
    aw_direct_calls: list = []
    iter_calls: list = []

    def _fake_aw_direct(*args, **kwargs):
        aw_direct_calls.append(kwargs)
        raise AssertionError("auto_iterate=True 인데 run_automate_workflow 직접 호출됨")

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        return SimpleNamespace(
            final_chain_result=SimpleNamespace(
                saved_dir=tmp_path, saved_code_files=[],
                executor_result=None, publish_result=None,
            ),
            verdict=SimpleNamespace(value="COMPLETE"),
            iterations_run=1,
        )

    from src.workflows import automate_workflow as aw_mod
    monkeypatch.setattr(aw_mod, "run_automate_workflow", _fake_aw_direct)
    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    rc = run_mod._run_track_b(_make_track_b_args(auto_iterate=True))
    assert rc == 0
    assert aw_direct_calls == []
    assert len(iter_calls) == 1
    assert iter_calls[0]["track"] == "B", (
        f"Track B 분기에서 run_iterative_loop 호출 시 track='B' 미전달 — "
        f"실제 track={iter_calls[0].get('track')!r}"
    )


def test_track_b_auto_iterate_passes_release_tag(
    run_mod, monkeypatch, tmp_path: Path
) -> None:
    """release_tag (args.tag) 가 run_iterative_loop 에 전달."""
    iter_calls: list = []

    def _fake_iter(*args, **kwargs):
        iter_calls.append(kwargs)
        return SimpleNamespace(
            final_chain_result=SimpleNamespace(
                saved_dir=tmp_path, saved_code_files=[],
                executor_result=None, publish_result=None,
            ),
            verdict=SimpleNamespace(value="COMPLETE"),
            iterations_run=1,
        )

    import src.workflows.iterative_loop as il_mod
    monkeypatch.setattr(il_mod, "run_iterative_loop", _fake_iter)

    rc = run_mod._run_track_b(
        _make_track_b_args(auto_iterate=True, release=True, tag="v0.3.0")
    )
    assert rc == 0
    assert iter_calls[0]["release_tag"] == "v0.3.0"
    assert iter_calls[0]["enable_release_branch"] is True
    assert iter_calls[0]["enable_publish"] is True


def test_track_b_auto_iterate_falls_back_on_none_final_chain(
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

    rc = run_mod._run_track_b(_make_track_b_args(auto_iterate=True))
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Iterate" in captured
    assert "BLOCKED" in captured


# ---------------------------------------------------------------------------
# 5. file-text 회귀
# ---------------------------------------------------------------------------


def test_track_b_imports_run_iterative_loop_in_auto_branch() -> None:
    """``_run_track_b`` 본문에 ``run_iterative_loop`` 호출 — auto-iterate wiring."""
    text = RUN_PY.read_text(encoding="utf-8")
    match = re.search(r"def\s+_run_track_b[\s\S]*?(?=\ndef\s|\Z)", text)
    assert match is not None
    body = match.group(0)
    assert "run_iterative_loop" in body, (
        "Track B 가 run_iterative_loop 호출 안 함 — PR #158 회귀"
    )
    assert 'track="B"' in body or "track='B'" in body, (
        "Track B 분기에서 track 'B' 미명시 — PR #158 회귀"
    )
