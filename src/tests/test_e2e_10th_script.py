# -*- coding: utf-8 -*-
"""scripts/run_e2e_10th_verification.py 회귀 방지 테스트 (PR #49).

실 LLM 풀체인은 60-90분 소요라 본 테스트에서 실행 안 함. 대신:
  1. 스크립트 syntax check (ast.parse)
  2. _try_import_qa_modules 가 lazy import 패턴으로 graceful degrade 하는지
  3. _dump_safely 가 다양한 입력에서 안전하게 직렬화하는지
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_e2e_10th_verification.py"


def test_script_syntax_is_valid() -> None:
    """스크립트 자체가 syntax 오류 없이 파싱되는지."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    ast.parse(source)


def test_script_has_main_entry() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "def main()" in source
    assert "if __name__ == \"__main__\":" in source


def test_script_uses_utf8_reconfigure() -> None:
    """cp949 인코딩 회피 — PR #41 와 동일 패턴 사용 여부."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "reconfigure(encoding=\"utf-8\"" in source


def test_script_imports_lazily() -> None:
    """QA 모듈을 try/except ImportError 패턴으로 lazy import 하는지."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # 4종 QA 도구 + qa_feedback_loop 가 try/except 안에 있어야 함
    assert "_try_import_qa_modules" in source
    assert "qa_feedback_loop" in source
    assert "code_qa_executor" in source
    assert "functional_test_executor" in source
    assert "gui_test_executor" in source
    assert "robustness_executor" in source


def test_script_specifies_dod_checks() -> None:
    """M5 + QA DoD 7가지 체크 명시 여부."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for key in [
        "1_publish_success",
        "2_release_url_issued",
        "3_download_urls_count",
        "4_is_draft",
        "5_executor_success",
        "6_qa_overall_passed",
        "7_qa_iterations_within_budget",
    ]:
        assert key in source, f"DoD 체크 누락: {key}"


def test_script_max_qa_retries_is_3() -> None:
    """기본 max_qa_retries = 3 (PR #48 qa_feedback_loop default 와 일치).

    PR #71 이후: argparse `--max-retries` default=3 또는 직접 할당 패턴 모두 허용.
    """
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # PR #71 argparse 도입 — default=3 또는 max_qa_retries = 3 둘 중 하나
    assert ("max_qa_retries = 3" in source) or ("default=3" in source), (
        "기본 max_qa_retries=3 의 신호가 스크립트에서 사라짐 (PR #71 argparse 또는 직접 할당)"
    )


# ---------------------------------------------------------------------------
# 모듈 lazy import 패턴 동작 검증 — main 에 QA 모듈 없을 때 graceful degrade
# ---------------------------------------------------------------------------


def test_try_import_qa_modules_returns_dict_with_known_keys() -> None:
    """현 main 베이스 (PR #42-#48 미머지) 에서도 호출 안전 + dict 반환."""
    # 스크립트를 모듈로 로드 (sys.path 조정)
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        # exec 로 직접 실행하지 않고 importlib 사용 — 부작용 (메인 진입) 방지
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_e2e_10th_verification", SCRIPT_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        # __name__ != "__main__" 이라 main() 자동 실행 안 됨
        spec.loader.exec_module(mod)

        modules = mod._try_import_qa_modules()
        assert isinstance(modules, dict)
        expected_keys = {
            "evaluate_qa_results",
            "build_feedback_message",
            "detect_artifact_category",
            "run_code_qa",
            "run_test_cases",
            "run_gui_test",
            "run_robustness_scenarios",
        }
        assert set(modules.keys()) == expected_keys
        # 각 값은 callable 또는 None
        for k, v in modules.items():
            assert v is None or callable(v), f"{k}: {v!r} 는 callable 도 None 도 아님"
    finally:
        sys.path.remove(str(PROJECT_ROOT / "scripts"))


def test_dump_safely_handles_basic_types() -> None:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_e2e_10th_verification", SCRIPT_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod._dump_safely(None) is None
        assert mod._dump_safely(42) == 42
        assert mod._dump_safely("hello") == "hello"
        assert mod._dump_safely([1, 2, 3]) == [1, 2, 3]
        assert mod._dump_safely({"a": 1}) == {"a": 1}
        assert mod._dump_safely(Path("/tmp/x")) == str(Path("/tmp/x"))
    finally:
        sys.path.remove(str(PROJECT_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# PR #57 — DOD_PASS_RULES + _dod_marker single source of truth
#
# 10차 E2E 6차 출력에서 발견된 cosmetic bug:
#   `3_download_urls_count: ❌ (2)` — 정수 카운트가 ❌ 로 표시됨.
#   원인: marker 로직이 `val in (True,)` 만 ✅ 처리 → 정수 2 가 ❌ 로 떨어짐.
#   영향: 종합 판정 (all_passed) 은 정상이라 실 동작 무관 — 콘솔 표시만.
# 본 PR fix:
#   DOD_PASS_RULES dict 가 marker (display) 와 all_passed (judgment) 의 single
#   source of truth. 향후 키 추가/변경 시 본 dict 만 수정.
# ---------------------------------------------------------------------------


def _load_script_module():
    """importlib 로 스크립트를 모듈처럼 로드 (main() 자동 실행 안 됨)."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_e2e_10th_verification", SCRIPT_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(PROJECT_ROOT / "scripts"))


def test_dod_pass_rules_covers_all_seven_dod_keys() -> None:
    """DOD_PASS_RULES 가 7개 DoD 키를 모두 포함 — main() 의 m5_qa_checks 와 키 일치."""
    mod = _load_script_module()
    expected = {
        "1_publish_success",
        "2_release_url_issued",
        "3_download_urls_count",
        "4_is_draft",
        "5_executor_success",
        "6_qa_overall_passed",
        "7_qa_iterations_within_budget",
    }
    assert set(mod.DOD_PASS_RULES.keys()) == expected


def test_dod_marker_handles_6th_e2e_all_pass_pattern() -> None:
    """10차 E2E 6차 (PR #55) 실 값 — 모두 ✅ 여야 cosmetic bug fix 검증."""
    mod = _load_script_module()
    sixth_checks = {
        "1_publish_success": True,
        "2_release_url_issued": True,
        "3_download_urls_count": 2,  # ⭐ 핵심 — 정수 카운트가 ✅ 로 표시
        "4_is_draft": True,
        "5_executor_success": True,
        "6_qa_overall_passed": True,
        "7_qa_iterations_within_budget": True,
    }
    for key, val in sixth_checks.items():
        assert mod._dod_marker(key, val) == "✅", (
            f"6차 패턴: {key}={val!r} 가 ✅ 가 아님 — cosmetic bug 회귀"
        )


def test_dod_marker_returns_skipped_for_none() -> None:
    """None 은 ⏭️ (skip) 로 표시 — 미수행 항목 구분."""
    mod = _load_script_module()
    for key in mod.DOD_PASS_RULES:
        assert mod._dod_marker(key, None) == "⏭️"


def test_dod_marker_returns_x_for_failure_patterns() -> None:
    """실패 값들은 ❌."""
    mod = _load_script_module()
    failures = {
        "1_publish_success": False,
        "2_release_url_issued": False,
        "3_download_urls_count": 0,  # 0개 → ❌
        "4_is_draft": False,
        "5_executor_success": False,
        "6_qa_overall_passed": False,
        "7_qa_iterations_within_budget": False,
    }
    for key, val in failures.items():
        assert mod._dod_marker(key, val) == "❌", (
            f"실패 패턴: {key}={val!r} 가 ❌ 가 아님"
        )


def test_dod_marker_unknown_key_returns_x_conservatively() -> None:
    """규칙 등록 안 된 키는 보수적으로 ❌ — 미정의 키가 silent ✅ 표시되는 사고 방지."""
    mod = _load_script_module()
    assert mod._dod_marker("99_unknown_future_check", True) == "❌"


def test_download_urls_count_must_be_exactly_two() -> None:
    """3_download_urls_count 는 .exe + .sha256.txt 두 자산만 PASS — 1개나 3개는 ❌."""
    mod = _load_script_module()
    rule = mod.DOD_PASS_RULES["3_download_urls_count"]
    assert rule(2) is True
    assert rule(0) is False
    assert rule(1) is False
    assert rule(3) is False


def test_qa_keys_treat_none_as_pass_for_optional_qa_modules() -> None:
    """6_qa_overall_passed / 7_qa_iterations_within_budget 는 None 도 PASS — QA 모듈
    부재 환경에서 풀체인 그 자체는 통과로 간주 (호환성)."""
    mod = _load_script_module()
    for key in ("6_qa_overall_passed", "7_qa_iterations_within_budget"):
        rule = mod.DOD_PASS_RULES[key]
        assert rule(True) is True
        assert rule(None) is True
        assert rule(False) is False


def test_all_passed_uses_dod_pass_rules_directly() -> None:
    """all_passed 계산이 DOD_PASS_RULES 를 사용하는지 (single source of truth 보장)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # main() 안에서 all_passed 계산이 DOD_PASS_RULES 를 직접 참조
    assert "DOD_PASS_RULES[k]" in source or "DOD_PASS_RULES.items()" in source, (
        "all_passed 가 DOD_PASS_RULES 를 사용하지 않음 — single source of truth 깨짐"
    )


# ---------------------------------------------------------------------------
# PR #71 — argparse 도입 + retry user_request 하드코딩 제거
# ---------------------------------------------------------------------------


def test_script_has_argparse_request_flag() -> None:
    """`--request` CLI 인자 도입 — 임의 시나리오 재사용 가능 (PR #71)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "argparse" in source, "argparse import 누락"
    assert "--request" in source, "--request CLI 인자 누락"
    # parser factory 함수
    assert "_parse_args" in source or "argparse.ArgumentParser" in source


def test_script_retry_preserves_original_user_request() -> None:
    """retry 시 원본 요청 보존 — '계산기 만들어줘' 하드코딩 제거 검증 (PR #71).

    배경: PR #70 까지 retry 시 user_request 가 '계산기 만들어줘'로 덮어쓰이는
    버그가 있어 임의 시나리오 (Excel 분석 등) 검증이 불가능했음.
    """
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # 원본 보존 변수
    assert "user_request_initial" in source, "user_request_initial 변수 누락"
    # retry 보강 코드에서 user_request_initial 사용
    assert "{user_request_initial}" in source, (
        "retry 보강 코드에서 user_request_initial 참조 누락 — 하드코딩 회귀 위험"
    )


def test_script_summary_uses_dynamic_user_request_initial() -> None:
    """summary.json 의 user_request_initial 도 동적 변수 사용 (PR #71)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # f-string 또는 변수 직접 사용 (하드코딩 '계산기 만들어줘' 검증 — summary 안에는 없어야)
    assert '"user_request_initial": user_request_initial' in source, (
        "summary 의 user_request_initial 이 변수가 아닌 하드코딩 — PR #71 fix 누락"
    )


def test_parse_args_returns_default_when_no_argv() -> None:
    """`_parse_args([])` 가 default '계산기 만들어줘' 반환 (backward compat)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args([])
        assert ns.request == "계산기 만들어줘"
        assert ns.max_retries == 3
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_parse_args_accepts_custom_request() -> None:
    """`_parse_args(['--request', '...'])` 가 custom request 반영."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args(["--request", "Excel 분석 PDF 보고서"])
        assert ns.request == "Excel 분석 PDF 보고서"
        # 짧은 형식 -r 도 동작
        ns2 = module._parse_args(["-r", "다른 요청"])
        assert ns2.request == "다른 요청"
    finally:
        sys.modules.pop("_e2e_10th_script", None)


# ---------------------------------------------------------------------------
# PR #73 — `--force-cli` 플래그 (active 4/4 도달용)
# ---------------------------------------------------------------------------


def test_script_has_force_cli_flag() -> None:
    """`--force-cli` CLI 인자 도입 — Track A Engineer 강제 CLI 산출 (PR #73)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--force-cli" in source, "--force-cli CLI 인자 누락"
    assert "force_cli" in source, "force_cli 변수 누락"
    # detect_artifact_category 의 'cli' 경로로 functional/robustness active 도달 의도 명시
    assert "functional" in source.lower() or "active" in source.lower()


def test_parse_args_force_cli_default_false() -> None:
    """`_parse_args([])` 기본값 force_cli=False (backward compat)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args([])
        assert ns.force_cli is False, "기본값은 False (기존 GUI 분기 흐름 유지)"
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_parse_args_force_cli_set_true() -> None:
    """`_parse_args(['--force-cli'])` → force_cli=True (action='store_true')."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args(["--force-cli"])
        assert ns.force_cli is True
        # 다른 인자와 같이 사용 가능
        ns2 = module._parse_args(
            ["--request", "Excel 분석 도구", "--force-cli", "--max-retries", "1"]
        )
        assert ns2.force_cli is True
        assert ns2.request == "Excel 분석 도구"
        assert ns2.max_retries == 1
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_script_applies_force_cli_to_enable_gui_branch() -> None:
    """force_cli=True 시 enable_gui_branch=False 강제 적용 검증 (정적 grep)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    # `not args.force_cli` 또는 동등 패턴 사용
    assert (
        "not args.force_cli" in source
        or "enable_gui_branch_for_run" in source
    ), (
        "force_cli → enable_gui_branch=False 강제 로직 누락 — "
        "PR #73 fix 미적용"
    )


def test_script_summary_includes_force_cli() -> None:
    """summary.json 에 force_cli + enable_gui_branch 저장 (재현성)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '"force_cli": args.force_cli' in source, (
        "summary.json 에 force_cli 저장 누락"
    )
    assert '"enable_gui_branch": enable_gui_branch_for_run' in source, (
        "summary.json 에 enable_gui_branch 저장 누락"
    )


# ---------------------------------------------------------------------------
# PR #75 — `--enable-automate-branch` 플래그 (Track B 풀체인 sample 검증용)
# ---------------------------------------------------------------------------


def test_script_has_enable_automate_branch_flag() -> None:
    """`--enable-automate-branch` CLI 인자 도입 (PR #75)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--enable-automate-branch" in source, "--enable-automate-branch CLI 인자 누락"
    assert "enable_automate_branch" in source, "enable_automate_branch 변수 누락"
    # Track B 라우팅 의도 명시 (Track A fallback 안내 포함)
    assert "Track B" in source or "Phase 6" in source


def test_parse_args_enable_automate_branch_default_false() -> None:
    """`_parse_args([])` 기본값 enable_automate_branch=False (backward compat)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args([])
        assert ns.enable_automate_branch is False, (
            "기본값은 False (Track A 흐름 유지)"
        )
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_parse_args_enable_automate_branch_set_true() -> None:
    """`_parse_args(['--enable-automate-branch'])` → enable_automate_branch=True."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    try:
        spec.loader.exec_module(module)
        ns = module._parse_args(["--enable-automate-branch"])
        assert ns.enable_automate_branch is True
        # 다른 인자와 같이 사용 가능
        ns2 = module._parse_args(
            [
                "--request",
                "네이버 쇼핑 가격 크롤링",
                "--enable-automate-branch",
                "--max-retries",
                "1",
            ]
        )
        assert ns2.enable_automate_branch is True
        assert ns2.request == "네이버 쇼핑 가격 크롤링"
        assert ns2.max_retries == 1
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_script_passes_enable_automate_branch_to_workflow() -> None:
    """run_analyze_and_implement 호출에 enable_automate_branch 전달 검증 (정적 grep)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert (
        "enable_automate_branch=enable_automate_branch_for_run" in source
    ), "run_analyze_and_implement 에 enable_automate_branch 전달 누락"


def test_script_summary_includes_enable_automate_branch() -> None:
    """summary.json 에 enable_automate_branch 저장."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert (
        '"enable_automate_branch": enable_automate_branch_for_run' in source
    ), "summary.json 에 enable_automate_branch 저장 누락"


# ---------------------------------------------------------------------------
# PR #84 — Track B 풀체인 CLI 플래그 (PR #81 QA / PR #82 Build / PR #83 Release)
# ---------------------------------------------------------------------------


def test_script_has_track_b_full_chain_flags() -> None:
    """5 신규 CLI 인자 도입 — PR #81/#82/#83 노출."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for flag in (
        "--enable-automate-qa-loop",
        "--enable-automate-build",
        "--enable-automate-release",
        "--automate-repo",
        "--automate-release-tag",
    ):
        assert flag in source, f"PR #84: {flag} CLI 인자 누락"


def _load_script_module():
    """``run_e2e_10th_verification.py`` 를 임시 모듈로 로드 (재사용 헬퍼)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_e2e_10th_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_e2e_10th_script"] = module
    spec.loader.exec_module(module)
    return module


def test_parse_args_track_b_full_chain_flags_default_false() -> None:
    """기본값 — 모든 신규 플래그 False / 빈 문자열 (backward compat)."""
    try:
        module = _load_script_module()
        ns = module._parse_args([])
        assert ns.enable_automate_qa_loop is False
        assert ns.enable_automate_build is False
        assert ns.enable_automate_release is False
        assert ns.automate_repo == ""
        assert ns.automate_release_tag == ""
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_parse_args_track_b_full_chain_flags_all_set() -> None:
    """모든 신규 플래그 set 시 Namespace 정확 반영."""
    try:
        module = _load_script_module()
        ns = module._parse_args(
            [
                "--enable-automate-branch",
                "--enable-automate-qa-loop",
                "--enable-automate-build",
                "--enable-automate-release",
                "--automate-repo",
                "owner/repo",
                "--automate-release-tag",
                "v0.1.0-track-b-test",
            ]
        )
        assert ns.enable_automate_branch is True
        assert ns.enable_automate_qa_loop is True
        assert ns.enable_automate_build is True
        assert ns.enable_automate_release is True
        assert ns.automate_repo == "owner/repo"
        assert ns.automate_release_tag == "v0.1.0-track-b-test"
    finally:
        sys.modules.pop("_e2e_10th_script", None)


def test_script_passes_track_b_full_chain_flags_to_workflow() -> None:
    """run_analyze_and_implement 호출에 5 신규 플래그 전달 검증 (정적 grep)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for line in (
        "enable_automate_qa_loop=enable_automate_qa_loop_for_run",
        "enable_automate_build=enable_automate_build_for_run",
        "enable_automate_release=enable_automate_release_for_run",
        "automate_repo_url=automate_repo_for_run",
        "automate_release_tag=automate_release_tag_for_run",
    ):
        assert line in source, f"PR #84: 호출에 '{line}' 누락"


def test_script_summary_includes_track_b_full_chain_flags() -> None:
    """summary.json 에 5 신규 플래그 echo (재현성)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for key in (
        '"enable_automate_qa_loop":',
        '"enable_automate_build":',
        '"enable_automate_release":',
        '"automate_repo":',
        '"automate_release_tag":',
    ):
        assert key in source, f"PR #84: summary.json 에 {key} 누락"
