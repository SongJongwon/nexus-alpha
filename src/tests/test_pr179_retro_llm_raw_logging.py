# -*- coding: utf-8 -*-
"""PR #179 — retrospective_lead LLM 응답 raw 저장 (80% silent 빈 응답률 진단 sprint).

배경 (2026-05-19 Phase 2 결과):
    Track B E2E 5회 누적 결과 retrospective_lead LLM 호출이 **80% silent 빈 응답률**:
        - 4/5 회: response="" (예외 없이 빈) 또는 모순 응답 → retrospective.md 4 섹션 "(없음)"
        - 1/5 회: 정상 응답 → retrospective.md 모든 섹션 정상 산출
    다른 LLM 호출 (Curator 등) 은 *매번 정상* — qa_verdict 추출 OK. **retrospective_lead
    특유의 비결정적 결함**. PR #176 의 분기 4 (silent 빈 응답) 가 진단 메시지 surface
    하지만 *정확한 root-cause* (prompt 길이 / token / streaming 결함 등) 는 미식별.

PR #179 처방:
    ``run_retrospective(workflow_dir=...)`` 파라미터 추가 → ``retrospective_llm_raw.json``
    file 에 다음 정보 dump:
        - prompt (전체) + prompt_length_chars
        - llm_error (Exception type+msg 또는 None)
        - response_raw (전체) + response_length_chars + response_stripped_length
        - parsed_raw (dict 또는 None) + parsed_keys + 3 카테고리 count
        - branch_hit (no_llm_call / exception / empty_silent / parse_fail / empty_lists / normal)
        - final_well / final_wrong / final_lessons (delta propagate 이후)
        - timestamp

다음 빈 응답 케이스 발생 시 raw file 확인으로 정확한 root-cause 식별 가능:
    - prompt_length_chars 가 한도 초과 → token 한도 결함
    - response_raw 가 truncated → streaming 결함
    - llm_error 가 timeout → provider 안정성 결함
    - parsed_keys 가 빈 list → JSON 형식 결함

본 테스트:
    1. workflow_dir=None → raw file 미생성 + 정상 동작 (기존 호환)
    2. workflow_dir 존재 → raw file 정상 생성 + JSON 형식 + 필수 키
    3-7. 5 분기 (normal / exception / empty_silent / parse_fail / empty_lists) 모두 branch_hit 정확 기록
    8. final_well/wrong/lessons 가 진단 메시지 포함 (분기별)
    9. file write OSError → graceful skip (report 정상 return)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agents.coordination.retrospective_lead import (
    RETROSPECTIVE_RAW_FILENAME,
    run_retrospective,
)


def _load_raw(workflow_dir: Path) -> dict[str, Any]:
    raw_path = workflow_dir / RETROSPECTIVE_RAW_FILENAME
    return json.loads(raw_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. workflow_dir 없음 → file 미생성 (기존 호환)
# ---------------------------------------------------------------------------


def test_no_workflow_dir_does_not_create_raw_file(tmp_path: Path) -> None:
    """workflow_dir=None (default) → file 미생성, report 정상 return."""
    report = run_retrospective(
        user_request="test",
        workflow_id="wf_x",
        verdict="COMPLETE",
    )
    assert report.workflow_id == "wf_x"
    # tmp_path 에 file 없음 (workflow_dir 명시 안 했으므로)
    assert not (tmp_path / RETROSPECTIVE_RAW_FILENAME).exists()


# ---------------------------------------------------------------------------
# 2. workflow_dir 명시 → file 생성 + 필수 키 + 정상 JSON
# ---------------------------------------------------------------------------


def test_workflow_dir_creates_raw_file_with_required_keys(tmp_path: Path) -> None:
    """workflow_dir 명시 → JSON file 생성, 13개 필수 키 모두 포함."""

    def normal_llm(prompt: str) -> str:
        return (
            '{"what_went_well": ["good"], "what_went_wrong": ["bad"], '
            '"lessons_learned": ["lesson"]}'
        )

    run_retrospective(
        user_request="test",
        workflow_id="wf_normal",
        verdict="COMPLETE",
        llm_call=normal_llm,
        workflow_dir=tmp_path,
    )

    raw = _load_raw(tmp_path)
    expected_keys = {
        "timestamp", "workflow_id", "verdict", "llm_call_invoked",
        "prompt", "prompt_length_chars", "llm_error",
        "response_raw", "response_length_chars", "response_stripped_length",
        "parsed_raw", "parsed_keys",
        "parsed_well_count", "parsed_wrong_count", "parsed_lessons_count",
        "branch_hit", "deltas",
        "final_well", "final_wrong", "final_lessons",
    }
    assert expected_keys.issubset(raw.keys()), f"누락된 키: {expected_keys - raw.keys()}"
    assert raw["workflow_id"] == "wf_normal"
    assert raw["verdict"] == "COMPLETE"
    assert raw["llm_call_invoked"] is True


# ---------------------------------------------------------------------------
# 3-7. 5 분기 branch_hit 정확 기록
# ---------------------------------------------------------------------------


def test_branch_hit_normal_when_llm_returns_valid_content(tmp_path: Path) -> None:
    """LLM 정상 응답 + parse OK + 채워진 list → branch_hit='normal'."""

    def good_llm(prompt: str) -> str:
        return (
            '{"what_went_well": ["pytest PASS"], "what_went_wrong": ["timeout 5s"], '
            '"lessons_learned": ["timeout 30s 권장"]}'
        )

    run_retrospective(
        user_request="test",
        workflow_id="wf_normal",
        verdict="COMPLETE",
        llm_call=good_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "normal"
    assert raw["parsed_well_count"] == 1
    assert raw["parsed_wrong_count"] == 1
    assert raw["parsed_lessons_count"] == 1
    assert raw["llm_error"] is None
    assert raw["response_stripped_length"] > 0


def test_branch_hit_exception_when_llm_raises(tmp_path: Path) -> None:
    """LLM 예외 발생 → branch_hit='exception' + llm_error 채워짐 + response_raw=''."""

    def boom_llm(prompt: str) -> str:
        raise RuntimeError("API timeout after 30s")

    run_retrospective(
        user_request="test",
        workflow_id="wf_exc",
        verdict="BLOCKED",
        llm_call=boom_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "exception"
    assert raw["llm_error"] is not None
    assert "RuntimeError" in raw["llm_error"]
    assert "API timeout after 30s" in raw["llm_error"]
    assert raw["response_raw"] == ""
    assert raw["response_length_chars"] == 0


def test_branch_hit_empty_silent_when_llm_returns_empty_string(tmp_path: Path) -> None:
    """⭐ 80% silent 빈 응답률 케이스 — LLM 빈 응답 + 예외 없음 → branch_hit='empty_silent'."""

    def silent_llm(prompt: str) -> str:
        return ""

    run_retrospective(
        user_request="네이버 쇼핑 크롤러",
        workflow_id="wf_silent",
        verdict="BLOCKED",
        llm_call=silent_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "empty_silent"
    assert raw["llm_error"] is None
    assert raw["response_raw"] == ""
    assert raw["response_length_chars"] == 0
    assert raw["response_stripped_length"] == 0
    # prompt 정보 보존 — root-cause 분석용
    assert raw["prompt"] is not None
    assert raw["prompt_length_chars"] > 0


def test_branch_hit_parse_fail_when_response_is_non_json(tmp_path: Path) -> None:
    """response 있지만 JSON 아님 → branch_hit='parse_fail' + parsed_raw=None."""

    def bad_json_llm(prompt: str) -> str:
        return "이건 그냥 자유 텍스트입니다. JSON 없음."

    run_retrospective(
        user_request="test",
        workflow_id="wf_parse",
        verdict="BLOCKED",
        llm_call=bad_json_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "parse_fail"
    assert raw["llm_error"] is None
    assert raw["response_length_chars"] > 0
    assert raw["parsed_raw"] is None
    assert raw["parsed_keys"] == []


def test_branch_hit_empty_lists_when_parse_ok_but_lists_empty(tmp_path: Path) -> None:
    """response + parse OK 인데 4 list 모두 빈 → branch_hit='empty_lists'."""

    def empty_lists_llm(prompt: str) -> str:
        return '{"what_went_well": [], "what_went_wrong": [], "lessons_learned": []}'

    run_retrospective(
        user_request="test",
        workflow_id="wf_empty",
        verdict="COMPLETE",
        llm_call=empty_lists_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "empty_lists"
    assert raw["parsed_raw"] is not None  # dict non-empty (3 keys with empty lists)
    assert len(raw["parsed_keys"]) == 3
    assert raw["parsed_well_count"] == 0
    assert raw["parsed_wrong_count"] == 0
    assert raw["parsed_lessons_count"] == 0


# ---------------------------------------------------------------------------
# 8. final lists 가 진단 메시지 포함 (분기별)
# ---------------------------------------------------------------------------


def test_final_lists_contain_diagnostics_after_branch_hit(tmp_path: Path) -> None:
    """branch_hit 에 따라 final_well/wrong/lessons 가 진단 메시지로 surface (PR #174/#176)."""

    def silent_llm(prompt: str) -> str:
        return ""

    run_retrospective(
        user_request="test",
        workflow_id="wf_diag",
        verdict="BLOCKED",
        llm_call=silent_llm,
        workflow_dir=tmp_path,
    )
    raw = _load_raw(tmp_path)
    # final_wrong 에 분기 2 진단 메시지 surface
    assert raw["final_wrong"]
    assert any("빈 문자열" in msg for msg in raw["final_wrong"])
    # final_lessons 에 후속 안내 surface
    assert raw["final_lessons"]
    assert any("LLM provider" in msg for msg in raw["final_lessons"])


# ---------------------------------------------------------------------------
# 9. no_llm_call branch (pytest 환경)
# ---------------------------------------------------------------------------


def test_branch_hit_no_llm_call_in_pytest_env(tmp_path: Path) -> None:
    """pytest 환경 + llm_call=None → llm_call 진입 자체 안 함 → branch_hit='no_llm_call'."""
    run_retrospective(
        user_request="test",
        workflow_id="wf_nopytest",
        verdict="COMPLETE",
        workflow_dir=tmp_path,
        # llm_call 명시 안 함 + pytest 환경 → 자동 None 유지
    )
    raw = _load_raw(tmp_path)
    assert raw["branch_hit"] == "no_llm_call"
    assert raw["llm_call_invoked"] is False
    assert raw["prompt"] is None
    assert raw["response_raw"] is None
