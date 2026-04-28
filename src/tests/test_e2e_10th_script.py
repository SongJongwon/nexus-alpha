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
    """기본 max_qa_retries = 3 (PR #48 qa_feedback_loop default 와 일치)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "max_qa_retries = 3" in source


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
