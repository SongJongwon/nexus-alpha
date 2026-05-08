"""
10차 E2E Verification — PR #49 (M5 + QA 자동 피드백 루프 풀체인 검증)

9차 (PR #41) 와 차이점:
    - 9차: enable_publish=True 활성 → 자연어 → 다운로드 URL (M5 풀체인)
    - 10차: 9차 + **자동 QA 피드백 루프** — Code QA / Functional Test / GUI Test
      / Robustness 4종 도구 결과를 합산해 buggy 산출물 감지 시 *재생성* 시도
      (max_qa_retries 회).

검증 기준:
    1. 9차 DoD 5/5 (publish.success / release_url / download_urls=2 / is_draft /
       executor.success) — M5 풀체인 유지
    2. **NEW**: QAFeedbackDecision.overall_passed == True (모든 QA 도구 PASS 또는
       skipped)
    3. **NEW**: 재시도 필요 시 max_qa_retries 내에 PASS 수렴 또는 budget 소진
       명시
    4. **NEW**: 풀체인 elapsed = E2E + QA + (재시도 × E2E) — 상한 제한 (보통
       60-120분)

실행 방법:
    cd C:\\projects\\nexus-alpha
    .venv\\Scripts\\activate
    python scripts\\run_e2e_10th_verification.py

산출물:
    outputs/e2e_10th_verification_<timestamp>/summary.json
    outputs/workflow_<timestamp>/  (워크플로우 산출 + QA 보고서들)

Note: 본 스크립트는 PR #42~#48 의 QA 모듈에 의존. 해당 PR들이 main 에 머지
되기 전에는 QA 모듈 lazy import 가 None 반환 → 9차와 동일 풀체인만 검증되고
QA 루프는 자동 skip.
"""
import argparse
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Windows cp949 회피 — PR #41 와 동일
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.analyze_and_implement import run_analyze_and_implement


# ---------------------------------------------------------------------------
# QA 모듈 lazy import — PR #42~#48 머지 전에는 None 반환 (9차 풀체인만 검증)
# ---------------------------------------------------------------------------


def _try_import_qa_modules() -> dict[str, Any]:
    """4종 QA 도구 + qa_feedback_loop 를 안전하게 import. 없으면 None."""
    modules: dict[str, Any] = {
        "evaluate_qa_results": None,
        "build_feedback_message": None,
        "detect_artifact_category": None,
        "run_code_qa": None,
        "run_test_cases": None,
        "run_gui_test": None,
        "run_robustness_scenarios": None,
    }
    try:
        from src.workflows.qa_feedback_loop import (
            build_feedback_message_for_engineer,
            detect_artifact_category,
            evaluate_qa_results,
        )
        modules["evaluate_qa_results"] = evaluate_qa_results
        modules["build_feedback_message"] = build_feedback_message_for_engineer
        modules["detect_artifact_category"] = detect_artifact_category
    except ImportError:
        pass
    try:
        from src.agents.qa.code_qa_executor import run_code_qa
        modules["run_code_qa"] = run_code_qa
    except ImportError:
        pass
    try:
        from src.agents.qa.functional_test_executor import run_test_cases
        modules["run_test_cases"] = run_test_cases
    except ImportError:
        pass
    try:
        from src.agents.qa.gui_test_executor import run_gui_test
        modules["run_gui_test"] = run_gui_test
    except ImportError:
        pass
    try:
        from src.agents.qa.robustness_executor import run_robustness_scenarios
        modules["run_robustness_scenarios"] = run_robustness_scenarios
    except ImportError:
        pass
    return modules


# ---------------------------------------------------------------------------
# QA 결과 수집
# ---------------------------------------------------------------------------


def _collect_qa_results(
    workflow_result: Any,
    qa_modules: dict[str, Any],
) -> dict[str, Any]:
    """워크플로우 산출물을 4종 QA 도구로 검증 → results dict.

    각 도구가 미가용 (PR 미머지) 이면 None 반환.
    """
    results: dict[str, Any] = {
        "code_qa": None,
        "functional": None,
        "gui": None,
        "robustness": None,
    }

    saved_dir = getattr(workflow_result, "saved_dir", None)
    if saved_dir is None:
        return results

    saved_dir = Path(saved_dir) if not isinstance(saved_dir, Path) else saved_dir

    # target script 추정 — workflow_result 에 saved_code_files 또는
    # build_output/dist/Calculator.exe 등
    target_script: Optional[Path] = None
    code_files = getattr(workflow_result, "saved_code_files", None)
    if code_files:
        # 첫 .py 파일을 entry 로 가정 (단순 휴리스틱)
        for f in code_files:
            f = Path(f) if not isinstance(f, Path) else f
            if f.suffix == ".py":
                target_script = f
                break

    target_exe: Optional[Path] = None
    executor = getattr(workflow_result, "executor_result", None)
    if executor and getattr(executor, "exe_path", None):
        target_exe = Path(executor.exe_path)

    # code_qa: workflow_dir 에 pytest 스위트가 있으면 실행
    if qa_modules["run_code_qa"] and saved_dir.exists():
        try:
            results["code_qa"] = qa_modules["run_code_qa"](
                target_dir=saved_dir, skip_ruff=False
            )
        except Exception as e:
            print(f"[QA] code_qa 실행 실패: {e}")

    # functional: target_script 가 CLI 형태면 실행
    if qa_modules["run_test_cases"] and target_script and target_script.exists():
        try:
            results["functional"] = qa_modules["run_test_cases"](
                target_script=target_script,
                per_case_timeout_sec=10,
            )
        except Exception as e:
            print(f"[QA] functional 실행 실패: {e}")

    # gui: target_exe (PyInstaller 산출) 가 있으면 GUI 검증
    if qa_modules["run_gui_test"] and target_exe and target_exe.exists():
        gui_output_dir = saved_dir / "gui_test_screenshots"
        try:
            # skip_vision=True 로 비용 절감 (실 vision 분석은 user 환경에서)
            results["gui"] = qa_modules["run_gui_test"](
                target_path=target_exe,
                output_dir=gui_output_dir,
                wait_sec=2.0,
                num_screenshots=1,
                timeout_sec=15,
                skip_vision=True,
            )
        except Exception as e:
            print(f"[QA] gui 실행 실패: {e}")

    # robustness: target_script 로 부하 시나리오
    if qa_modules["run_robustness_scenarios"] and target_script and target_script.exists():
        try:
            results["robustness"] = qa_modules["run_robustness_scenarios"](
                target_script=target_script, per_scenario_timeout_sec=15
            )
        except Exception as e:
            print(f"[QA] robustness 실행 실패: {e}")

    return results


# ---------------------------------------------------------------------------
# M5 + QA DoD 판정 규칙 — display marker 와 all_passed 의 single source of truth.
# PR #57: PR #51~#55 까지는 marker (display) 와 all_passed (judgment) 가 별도
# 표현이라 정수 카운트 키 (3_download_urls_count) 가 ❌ 로 표시되는 cosmetic
# bug 발생 (10차 E2E 6차 출력에서 관찰). 본 PR 에서 단일 dict 로 통합.
# 규칙 추가/변경 시 본 PASS_RULES 만 수정하면 marker 와 all_passed 가 함께 갱신.
# ---------------------------------------------------------------------------
DOD_PASS_RULES: dict[str, Any] = {
    "1_publish_success": lambda v: v is True,
    "2_release_url_issued": lambda v: v is True,
    # PR #92 — v == 2 → v >= 1 (Track B 호환). Track A 는 .exe + .sha256.txt (2개)
    # 업로드, Track B 는 .exe 1개만 업로드 → rule 을 ``≥ 1`` 로 완화. 두 Track
    # 모두 PASS 가능. release 의 *최소 1개 다운로드 URL 발급* = publish 성공의
    # 충분 조건.
    "3_download_urls_count": lambda v: v >= 1,
    "4_is_draft": lambda v: v is True,
    "5_executor_success": lambda v: v is True,
    "6_qa_overall_passed": lambda v: v in (True, None),
    "7_qa_iterations_within_budget": lambda v: v in (True, None),
}


def _dod_marker(key: str, val: Any) -> str:
    """DoD 체크 항목 한 칸을 ✅/⏭️/❌ 중 하나로 표시.

    None → ⏭️ (skip / 미수행), 그 외엔 DOD_PASS_RULES 기준으로 판정.
    """
    if val is None:
        return "⏭️"
    rule = DOD_PASS_RULES.get(key)
    if rule is None:
        # 알 수 없는 키 — 보수적으로 ❌ (실수 방지)
        return "❌"
    return "✅" if rule(val) else "❌"


def _dump_safely(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_dump_safely(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _dump_safely(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return {k: _dump_safely(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return repr(obj)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """CLI 인자 파싱 — `--request` 로 user_request 변경 가능 (PR #71).

    배경 (PR #71):
        기존 스크립트는 user_request 가 ``"계산기 만들어줘"`` 로 하드코딩되어
        CLI 시나리오 (Excel 분석 PDF 보고서 등) 검증이 불가능했음. argparse 도입
        + retry 시 원본 보존 로직 추가로 임의 시나리오 재사용 가능.

    Args:
        argv: 테스트 목적의 인자 주입. None 이면 sys.argv[1:] 사용.

    Returns:
        ``Namespace`` — request / max_retries 필드.
    """
    parser = argparse.ArgumentParser(
        description="10차 E2E Verification — M5 + QA 자동 피드백 루프"
    )
    parser.add_argument(
        "--request",
        "-r",
        default="계산기 만들어줘",
        help="사용자 요청 (자연어). 기본: '계산기 만들어줘' (Calculator.exe 풀체인).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="QA 자동 보정 최대 재시도 횟수. 기본 3.",
    )
    parser.add_argument(
        "--force-cli",
        action="store_true",
        default=False,
        help=(
            "GUI 분기 비활성화 (enable_gui_branch=False) → Python Engineer 단독 "
            "CLI 산출 강제 (PR #73). 산출 코드에 argparse / sys.argv 가 포함되어 "
            "detect_artifact_category 가 'cli' 반환 → functional / robustness "
            "QA 도구가 active PASS 도달. CLI 시나리오 (Excel 분석 / 데이터 변환 "
            "등) 검증에 사용."
        ),
    )
    parser.add_argument(
        "--enable-automate-branch",
        action="store_true",
        default=False,
        help=(
            "Track B (Phase 6) 활성화 — Web Scraping / Desktop Automation / "
            "API Integration / Data Parser / DevOps 5 도메인 중 휴리스틱 분류로 "
            "1명 호출 (PR #75). analyze_and_implement 라우팅이 UNKNOWN 도메인 시 "
            "Track A fallback (backward compat)."
        ),
    )
    # ─── Track B 풀체인 플래그 (PR #84 — PR #81/#82/#83 노출) ────────────────
    parser.add_argument(
        "--enable-automate-qa-loop",
        action="store_true",
        default=False,
        help=(
            "Track B + QA 피드백 루프 활성 (PR #81). 도메인 task 후 pytest_author "
            "+ code_qa 실행 → 03_pytest_suite.md + test_*.py 산출. devops 자동 "
            "skip. --enable-automate-branch 와 함께 사용."
        ),
    )
    parser.add_argument(
        "--enable-automate-build",
        action="store_true",
        default=False,
        help=(
            "Track B + Build (PyInstaller) 활성 (PR #82). 도메인 entry .py → .exe "
            "산출 + 04_executor_result.md. devops 자동 skip. "
            "--enable-automate-branch 와 함께 사용."
        ),
    )
    parser.add_argument(
        "--enable-automate-release",
        action="store_true",
        default=False,
        help=(
            "Track B + Release 활성 (PR #83). Update Checker LLM + updater.py "
            "auto-import + (옵션) gh release create. --automate-repo + "
            "--automate-release-tag 모두 제공 시 publish 실행. devops 자동 skip."
        ),
    )
    parser.add_argument(
        "--automate-repo",
        default="",
        help=(
            "Track B Release 의 GitHub repo (예: 'owner/name'). 빈 문자열이면 "
            "publish skip (Update Checker 통합만 실행). PR #83."
        ),
    )
    parser.add_argument(
        "--automate-release-tag",
        default="",
        help=(
            "Track B Release tag (예: 'v0.1.0-track-b'). 빈 문자열이면 publish "
            "skip. PR #83."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")

    user_request_initial = args.request
    max_qa_retries = args.max_retries
    # PR #73: --force-cli → enable_gui_branch=False (CLI 산출 강제)
    enable_gui_branch_for_run = not args.force_cli
    # PR #75: --enable-automate-branch → Track B 활성화
    enable_automate_branch_for_run = args.enable_automate_branch
    # PR #84: Track B 풀체인 플래그 (PR #81/#82/#83 노출)
    enable_automate_qa_loop_for_run = args.enable_automate_qa_loop
    enable_automate_build_for_run = args.enable_automate_build
    enable_automate_release_for_run = args.enable_automate_release
    automate_repo_for_run = args.automate_repo
    automate_release_tag_for_run = args.automate_release_tag

    print("=" * 80)
    print("10차 E2E Verification — M5 + QA 자동 피드백 루프 (PR #49)")
    print(f"Start: {start_time.isoformat()}")
    print(f"Request: {user_request_initial}")
    print(f"Max QA Retries: {max_qa_retries}")
    print(f"enable_gui_branch: {enable_gui_branch_for_run} "
          f"(force_cli={args.force_cli})")
    print(f"enable_automate_branch: {enable_automate_branch_for_run} "
          f"(Track B Phase 6)")
    if enable_automate_branch_for_run:
        track_b_chain = []
        if enable_automate_qa_loop_for_run:
            track_b_chain.append("QA loop")
        if enable_automate_build_for_run:
            track_b_chain.append("Build")
        if enable_automate_release_for_run:
            track_b_chain.append("Release")
        if track_b_chain:
            print(f"[NOTE] Track B 풀체인 활성 — {' + '.join(track_b_chain)} (PR #81~#83).")
            if enable_automate_release_for_run and not (automate_repo_for_run and automate_release_tag_for_run):
                print("       repo / release_tag 미제공 → publish skip (Update Checker 통합만).")
        else:
            print("[NOTE] Track B 활성 — 단일 에이전트 호출 (QA/Build/Release 비활성).")
            print("       DoD 7/7 일부 항목 실패 가능 (산출물 코드 검증이 목표).")
    print("=" * 80)
    print()

    qa_modules = _try_import_qa_modules()
    qa_available = sum(1 for v in qa_modules.values() if v is not None)
    print(f"[QA] 가용 모듈: {qa_available}/{len(qa_modules)}")
    if qa_available < len(qa_modules):
        missing = [k for k, v in qa_modules.items() if v is None]
        print(f"[QA] 미가용: {missing} (PR #42~#48 미머지 추정 — QA 루프는 부분 적용)")

    user_request = user_request_initial

    result = None
    qa_decision = None
    qa_results = None
    error_info = None
    status = "UNKNOWN"
    qa_iterations: list[dict[str, Any]] = []

    for attempt in range(max_qa_retries + 1):
        print(f"\n--- Attempt {attempt + 1}/{max_qa_retries + 1} ---")
        try:
            result = run_analyze_and_implement(
                user_request,
                enable_gui_branch=enable_gui_branch_for_run,
                enable_build_branch=True,
                enable_release_branch=True,
                previous_version="0.1.0",
                repo_url="https://github.com/SongJongwon/nexus-alpha",
                enable_executor=True,
                executor_timeout_sec=600,
                enable_publish=True,
                publish_as_draft=True,
                publish_timeout_sec=120,
                enable_automate_branch=enable_automate_branch_for_run,
                # PR #84 — Track B 풀체인 플래그 (PR #81/#82/#83)
                enable_automate_qa_loop=enable_automate_qa_loop_for_run,
                enable_automate_build=enable_automate_build_for_run,
                enable_automate_release=enable_automate_release_for_run,
                automate_repo_url=automate_repo_for_run,
                automate_release_tag=automate_release_tag_for_run,
            )
            status = "SUCCESS"
        except KeyboardInterrupt:
            status = "INTERRUPTED"
            print("\n[INTERRUPTED] 사용자 중단")
            break
        except Exception as e:
            status = "FAILED"
            error_info = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
            print(f"\n[ERROR] {type(e).__name__}: {e}")
            break

        # QA 검증
        qa_results = _collect_qa_results(result, qa_modules)
        active_count = sum(1 for v in qa_results.values() if v is not None)
        print(f"[QA] {active_count}/4 도구 활성 검증")

        if qa_modules["evaluate_qa_results"]:
            artifact_category = "unknown"
            if qa_modules["detect_artifact_category"]:
                target_script: Optional[Path] = None
                code_files = getattr(result, "saved_code_files", None) or []
                for f in code_files:
                    p = Path(f) if not isinstance(f, Path) else f
                    if p.suffix == ".py":
                        target_script = p
                        break
                target_exe: Optional[Path] = None
                ex_obj = getattr(result, "executor_result", None)
                if ex_obj and getattr(ex_obj, "exe_path", None):
                    target_exe = Path(ex_obj.exe_path)
                artifact_category = qa_modules["detect_artifact_category"](
                    target_script=target_script, target_exe=target_exe
                )
            print(f"[QA] artifact_category={artifact_category}")

            qa_decision = qa_modules["evaluate_qa_results"](
                qa_results,
                retry_count=attempt,
                max_retries=max_qa_retries,
                artifact_category=artifact_category,
            )
            print(f"[QA] {qa_decision.summary_line()}")
            qa_iterations.append({
                "attempt": attempt + 1,
                "decision_summary": qa_decision.summary_line(),
                "overall_passed": qa_decision.overall_passed,
                "should_retry": qa_decision.should_retry,
                "failed_qa_tools": qa_decision.failed_qa_tools,
            })

            if qa_decision.overall_passed:
                print(f"[QA] PASS — 재시도 불필요")
                break

            if not qa_decision.should_retry:
                print(f"[QA] BUDGET_EXHAUSTED — max_qa_retries({max_qa_retries}) 도달")
                break

            # 다음 시도를 위한 user_request 보강 (PR #71 — 원본 요청 보존)
            # 기존 버그: f"계산기 만들어줘\n\n..." 로 하드코딩 → 임의 시나리오로
            # 시작해도 retry 후 calculator.py 산출. CLI E2E 검증 (Excel 분석 등) 불가.
            feedback = qa_modules["build_feedback_message"](qa_decision, full_qa_reports=None)
            user_request = (
                f"{user_request_initial}\n\n"
                f"--- 이전 시도 ({attempt + 1} 회차) QA 검증 결과 ---\n"
                + feedback
            )
            print(f"[QA] 재시도 — feedback 메시지 길이 {len(feedback)} 자")
        else:
            print("[QA] qa_feedback_loop 미가용 — 재시도 없이 종료 (9차 모드)")
            break

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print()
    print("=" * 80)
    print(f"End: {end_time.isoformat()}")
    print(f"Elapsed: {elapsed:.2f}s ({elapsed / 60:.2f} min)")
    print(f"Status: {status}")
    print("=" * 80)

    output_dir = PROJECT_ROOT / "outputs" / f"e2e_10th_verification_{timestamp_str}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # M5 + QA DoD
    m5_qa_checks = {
        "1_publish_success": False,
        "2_release_url_issued": False,
        "3_download_urls_count": 0,
        "4_is_draft": None,
        "5_executor_success": False,
        "6_qa_overall_passed": None,
        "7_qa_iterations_within_budget": None,
    }
    if result is not None:
        publish = getattr(result, "publish_result", None)
        executor = getattr(result, "executor_result", None)
        if publish:
            m5_qa_checks["1_publish_success"] = bool(getattr(publish, "success", False))
            m5_qa_checks["2_release_url_issued"] = bool(getattr(publish, "release_url", None))
            m5_qa_checks["3_download_urls_count"] = len(getattr(publish, "download_urls", []) or [])
            m5_qa_checks["4_is_draft"] = getattr(publish, "is_draft", None)
        if executor:
            m5_qa_checks["5_executor_success"] = bool(getattr(executor, "success", False))
        if qa_decision:
            m5_qa_checks["6_qa_overall_passed"] = qa_decision.overall_passed
            m5_qa_checks["7_qa_iterations_within_budget"] = (
                qa_decision.retry_count <= max_qa_retries
            )

    m5_qa_checks["all_passed"] = all(
        DOD_PASS_RULES[k](m5_qa_checks[k]) for k in DOD_PASS_RULES
    )

    summary = {
        "verification_round": 10,
        "pr_number": 49,
        "milestone": "M5 + QA 자동 피드백 루프 풀체인",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "elapsed_sec": elapsed,
        "status": status,
        "user_request_initial": user_request_initial,
        "max_qa_retries": max_qa_retries,
        "force_cli": args.force_cli,
        "enable_gui_branch": enable_gui_branch_for_run,
        "enable_automate_branch": enable_automate_branch_for_run,
        # PR #84 — Track B 풀체인 플래그 (PR #81/#82/#83)
        "enable_automate_qa_loop": enable_automate_qa_loop_for_run,
        "enable_automate_build": enable_automate_build_for_run,
        "enable_automate_release": enable_automate_release_for_run,
        "automate_repo": automate_repo_for_run,
        "automate_release_tag": automate_release_tag_for_run,
        "qa_modules_available": {k: v is not None for k, v in qa_modules.items()},
        "qa_iterations": qa_iterations,
        "qa_decision_final": _dump_safely(qa_decision),
        "m5_qa_dod_checks": m5_qa_checks,
        "result_introspection": _dump_safely(result),
        "error": error_info,
    }

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n[SAVED] {summary_path}")

    # 핵심 콘솔 요약
    print("\n--- M5 + QA DoD 7가지 체크 ---")
    for key, val in m5_qa_checks.items():
        if key == "all_passed":
            continue
        marker = _dod_marker(key, val)
        print(f"  {key:30s}: {marker} ({val})")
    print(
        f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  종합: {'🎉 ALL PASSED' if m5_qa_checks['all_passed'] else '⚠️  일부 실패'}"
    )

    if status == "SUCCESS":
        return 0 if m5_qa_checks["all_passed"] else 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
