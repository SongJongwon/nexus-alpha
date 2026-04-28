"""
9차 E2E Verification — PR #41 (M5 published mode 검증)

8차 (PR #38) 와 차이점: ``enable_publish=True`` 활성 → 풀체인 검증
    자연어 "계산기 만들어줘"
        → CTO + Python Engineer + GUI 4 + Build 5 + Release 4 (총 14 LLM 호출)
        → build_executor (PyInstaller subprocess) → Calculator.exe 산출
        → distribution_executor (gh release create --draft) → GitHub draft release
        → release_url + download_urls 2개 (.exe + .sha256.txt)

검증 기준 (M5 DoD):
    1. result.publish_result.success == True
    2. result.publish_result.release_url 발급 (URL 형식)
    3. result.publish_result.download_urls == 2개 (.exe + .sha256.txt)
    4. result.publish_result.is_draft == True (안전 default)
    5. GitHub UI 에서 draft release 확인 가능 (인증 사용자만)

실행 방법:
    cd C:\\projects\\nexus-alpha
    .venv\\Scripts\\activate
    python scripts\\run_e2e_9th_verification.py

산출물:
    outputs/e2e_9th_verification_<timestamp>/summary.json
    outputs/workflow_<timestamp>/  (워크플로우 산출 파일 14~17개 + 34_publish_result.md)
"""
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path

# Windows cp949 코덱 회피 — 한글/em dash/이모지 print 가능하도록 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.workflows.analyze_and_implement import run_analyze_and_implement


def dump_safely(obj):
    """객체를 JSON 직렬화 가능한 형태로 안전 변환."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [dump_safely(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): dump_safely(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return {k: dump_safely(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return repr(obj)


def main():
    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")

    print("=" * 76)
    print("9차 E2E Verification — M5 published mode 풀체인 (PR #41)")
    print(f"Start: {start_time.isoformat()}")
    print(f"Request: 계산기 만들어줘")
    print(f"Flags: gui=True, build=True, release=True, executor=True, publish=True (draft)")
    print("=" * 76)
    print()

    result = None
    error_info = None
    status = "UNKNOWN"

    try:
        result = run_analyze_and_implement(
            "계산기 만들어줘",
            enable_gui_branch=True,
            enable_build_branch=True,
            enable_release_branch=True,
            previous_version="0.1.0",
            repo_url="https://github.com/SongJongwon/nexus-alpha",
            enable_executor=True,           # PR #36/#37 — 실제 PyInstaller 호출
            executor_timeout_sec=600,        # 10분 (calculator 단순 GUI 빌드 충분)
            enable_publish=True,             # ⭐ PR #41 신규 — gh release create 활성
            publish_as_draft=True,           # 안전 default — public 노출 방지
            publish_timeout_sec=120,
        )
        status = "SUCCESS"
    except KeyboardInterrupt:
        status = "INTERRUPTED"
        print("\n[INTERRUPTED] 사용자 중단 (Ctrl+C)")
    except Exception as e:
        status = "FAILED"
        error_info = {
            "type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        print(traceback.format_exc())

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print()
    print("=" * 76)
    print(f"End: {end_time.isoformat()}")
    print(f"Elapsed: {elapsed:.2f}s  ({elapsed / 60:.2f} min)")
    print(f"Status: {status}")
    print("=" * 76)

    # 요약 저장
    output_dir = PROJECT_ROOT / "outputs" / f"e2e_9th_verification_{timestamp_str}"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "verification_round": 9,
        "pr_number": 41,
        "milestone": "M5 published mode 풀체인",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "elapsed_sec": elapsed,
        "status": status,
        "user_request": "계산기 만들어줘",
        "flags": {
            "enable_gui_branch": True,
            "enable_build_branch": True,
            "enable_release_branch": True,
            "enable_executor": True,
            "enable_publish": True,
            "publish_as_draft": True,
            "previous_version": "0.1.0",
            "repo_url": "https://github.com/SongJongwon/nexus-alpha",
        },
        "error": error_info,
        "m5_dod_checks": None,
        "result_introspection": None,
    }

    if result is not None:
        try:
            summary["result_type"] = type(result).__name__
            summary["result_introspection"] = dump_safely(result)
        except Exception as e:
            summary["introspection_error"] = f"{type(e).__name__}: {e}"

        # M5 DoD 5가지 체크
        publish = getattr(result, "publish_result", None)
        executor = getattr(result, "executor_result", None)
        m5_checks = {
            "1_publish_success": False,
            "2_release_url_issued": False,
            "3_download_urls_count": 0,
            "4_is_draft": None,
            "5_executor_success": False,
        }
        if publish is not None:
            m5_checks["1_publish_success"] = bool(getattr(publish, "success", False))
            m5_checks["2_release_url_issued"] = bool(getattr(publish, "release_url", None))
            m5_checks["3_download_urls_count"] = len(getattr(publish, "download_urls", []) or [])
            m5_checks["4_is_draft"] = getattr(publish, "is_draft", None)
        if executor is not None:
            m5_checks["5_executor_success"] = bool(getattr(executor, "success", False))
        m5_checks["all_passed"] = (
            m5_checks["1_publish_success"]
            and m5_checks["2_release_url_issued"]
            and m5_checks["3_download_urls_count"] == 2
            and m5_checks["4_is_draft"] is True
            and m5_checks["5_executor_success"]
        )
        summary["m5_dod_checks"] = m5_checks

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n[SAVED] {summary_path}")

    # 콘솔 핵심 요약
    print("\n--- Core Summary ---")
    if status == "SUCCESS" and result is not None:
        fer = getattr(result, "final_execution_result", None)
        if fer is not None:
            print(f"  Sandbox verdict   : {getattr(fer, 'verdict', 'N/A')}")
            print(f"  Sandbox exit_code : {getattr(fer, 'exit_code', 'N/A')}")

        iterations = getattr(result, "iterations", None)
        if iterations is not None:
            print(f"  Total iterations  : {iterations}")

        # PyInstaller executor (PR #36/#37)
        executor = getattr(result, "executor_result", None)
        if executor is not None:
            print()
            print("--- PyInstaller Executor (PR #36/#37) ---")
            print(f"  {executor.summary_line()}")

        # ⭐ Distribution executor (PR #39, 9차 검증 핵심)
        publish = getattr(result, "publish_result", None)
        if publish is not None:
            print()
            print("--- GitHub Release Publisher (PR #39, 9차 핵심) ---")
            print(f"  {publish.summary_line()}")
            if publish.release_url:
                print(f"  release_url   : {publish.release_url}")
            if publish.download_urls:
                print(f"  download_urls : {len(publish.download_urls)} 개")
                for url in publish.download_urls:
                    print(f"    - {url}")
            if publish.error_message:
                print(f"  error: {publish.error_message}")

        # M5 DoD 체크 결과
        m5 = summary.get("m5_dod_checks") or {}
        print()
        print("--- M5 DoD 체크 (5/5 통과 = published mode 풀체인 완성) ---")
        print(f"  1. publish.success           : {'✅' if m5.get('1_publish_success') else '❌'}")
        print(f"  2. release_url 발급          : {'✅' if m5.get('2_release_url_issued') else '❌'}")
        print(f"  3. download_urls == 2        : {'✅' if m5.get('3_download_urls_count') == 2 else '❌'} ({m5.get('3_download_urls_count')})")
        print(f"  4. is_draft == True          : {'✅' if m5.get('4_is_draft') is True else '❌'}")
        print(f"  5. executor.success          : {'✅' if m5.get('5_executor_success') else '❌'}")
        print(f"  --- 종합: {'🎉 ALL PASSED — M5 풀체인 검증 완료' if m5.get('all_passed') else '⚠️  일부 실패'}")

    print()
    print("--- Next Steps ---")
    if status == "SUCCESS":
        m5 = summary.get("m5_dod_checks") or {}
        if m5.get("all_passed"):
            print("  1. 검증 보고서 docs/progress/e2e_9th_verification_post_pr39.md 작성")
            print("  2. WORK_STATUS.md 갱신 (M5 풀체인 검증 완료)")
            print(f"  3. {summary_path} 공유")
            print("  4. (선택) GitHub UI 에서 draft release 확인 후 삭제 또는 publish")
        else:
            print("  1. 위 체크 결과 확인 → 실패 항목 디버깅")
            print(f"  2. {summary_path} 공유")
    elif status == "FAILED":
        print("  1. 위 traceback 공유")
        print(f"  2. {summary_path} 공유")
    elif status == "INTERRUPTED":
        print("  1. 부분 산출물 outputs/workflow_<timestamp>/ 확인")
        print("  2. 재실행 여부 결정")

    # exit code: M5 DoD 5/5 통과 시에만 0
    if status == "SUCCESS":
        m5 = summary.get("m5_dod_checks") or {}
        return 0 if m5.get("all_passed") else 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
