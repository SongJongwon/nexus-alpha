"""
E2E Verification Script — v3 + Phase 4 + 4.5 + 5 Full Chain
Real Claude MAX LLM integration test.

실행 방법:
    cd C:\\projects\\nexus-alpha
    .venv\\Scripts\\activate
    python scripts\\run_e2e_verification.py

산출물:
    outputs/e2e_verification_<timestamp>/summary.json
    outputs/workflow_<timestamp>/  (워크플로우 산출 파일 13~17개)
"""
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/ 하위에서 실행 시 import 해결)
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
    if hasattr(obj, "__dict__"):
        return {k: dump_safely(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return repr(obj)


def main():
    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")

    print("=" * 72)
    print("E2E Verification — Real LLM (Claude MAX / agent_sdk)")
    print(f"Start: {start_time.isoformat()}")
    print(f"Request: 계산기 만들어줘")
    print(f"Flags: gui=True, build=True, release=True, prev=0.1.0")
    print("=" * 72)
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
    print("=" * 72)
    print(f"End: {end_time.isoformat()}")
    print(f"Elapsed: {elapsed:.2f}s  ({elapsed / 60:.2f} min)")
    print(f"Status: {status}")
    print("=" * 72)

    # 요약 저장
    output_dir = PROJECT_ROOT / "outputs" / f"e2e_verification_{timestamp_str}"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "elapsed_sec": elapsed,
        "status": status,
        "user_request": "계산기 만들어줘",
        "flags": {
            "enable_gui_branch": True,
            "enable_build_branch": True,
            "enable_release_branch": True,
            "previous_version": "0.1.0",
            "repo_url": "https://github.com/SongJongwon/nexus-alpha",
        },
        "error": error_info,
        "result_introspection": None,
    }

    if result is not None:
        try:
            summary["result_type"] = type(result).__name__
            summary["result_introspection"] = dump_safely(result)
        except Exception as e:
            summary["introspection_error"] = f"{type(e).__name__}: {e}"

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
            print(f"  Sandbox elapsed   : {getattr(fer, 'elapsed_sec', 'N/A')}s")
            print(f"  Sandbox timed_out : {getattr(fer, 'timed_out', 'N/A')}")

        iterations = getattr(result, "iterations", None)
        if iterations is not None:
            print(f"  Total iterations  : {iterations}")

        decision = getattr(result, "convergence_decision", None) or getattr(result, "verdict", None)
        if decision is not None:
            print(f"  Convergence       : {decision}")

        workflow_id = getattr(result, "workflow_id", None) or getattr(result, "timestamp", None)
        if workflow_id is not None:
            print(f"  Workflow folder   : outputs/workflow_{workflow_id}/")

    print()
    print("--- Next Steps ---")
    if status == "SUCCESS":
        print("  1. outputs/workflow_<timestamp>/ 폴더 내 산출 파일 개수·품질 확인")
        print("  2. LangFuse 대시보드에서 14 LLM trace 확인")
        print(f"  3. {summary_path} 공유")
        print("  4. docs/progress/e2e_verification_issues.md 에 결과 기록")
    elif status == "FAILED":
        print("  1. 위 traceback 공유")
        print(f"  2. {summary_path} 공유")
        print("  3. 실패 지점에 따라 재실행 또는 디버깅 진행")
    elif status == "INTERRUPTED":
        print("  1. 부분 산출물 outputs/workflow_<timestamp>/ 확인")
        print("  2. 재실행 여부 결정")

    return 0 if status == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
