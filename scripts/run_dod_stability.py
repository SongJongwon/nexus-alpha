"""DoD 7/7 안정성 반복 검증 (후보 N — next_session_context.md §6).

Track B 풀체인 E2E (`run_e2e_10th_verification.py --enable-automate-*`)를
N 회 반복 실행하여 DoD 7/7 ALL PASSED 의 일관성을 입증.

PR #97 의 1회 PASS 가 LLM variance 에 robust 한지 (i.e. *결정형 후처리
패턴 의 누적효과* 가 single-shot 의 lucky-pass 가 아닌지) 확인.

Usage:
    .venv/Scripts/python.exe scripts/run_dod_stability.py --iterations 3
    .venv/Scripts/python.exe scripts/run_dod_stability.py --iterations 5 \\
        --request "네이버 쇼핑 가격 크롤링 스크립트"

Output:
    outputs/dod_stability_{timestamp}/
      ├── iter_1.log ... iter_N.log   각 회 E2E stdout/stderr
      └── aggregate.json              종합 결과 + DoD 매트릭스

Exit codes:
    0 — 모든 iteration 이 DoD 7/7 ALL PASSED
    2 — 일부 iteration 실패 (보고서 확인)
    1 — wrapper 자체 오류
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
E2E_SCRIPT = PROJECT_ROOT / "scripts" / "run_e2e_10th_verification.py"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

DOD_KEYS = (
    "1_publish_success",
    "2_release_url_issued",
    "3_download_urls_count",
    "4_is_draft",
    "5_executor_success",
    "6_qa_overall_passed",
    "7_qa_iterations_within_budget",
)


def _latest_summary_after(since_ts: float) -> Path | None:
    """주어진 mtime 이후 작성된 가장 최근 summary.json 경로."""
    candidates = sorted(
        OUTPUTS_DIR.glob("e2e_10th_verification_*/summary.json"),
        key=lambda p: p.stat().st_mtime,
    )
    after = [p for p in candidates if p.stat().st_mtime >= since_ts]
    return after[-1] if after else (candidates[-1] if candidates else None)


def _run_one_iteration(
    iter_idx: int,
    request: str,
    tag: str,
    max_retries: int,
    log_dir: Path,
) -> dict:
    """한 회 E2E 를 subprocess 로 실행하고 결과 dict 반환."""
    iter_log = log_dir / f"iter_{iter_idx}.log"
    pre_run_ts = datetime.now().timestamp()
    cmd = [
        sys.executable,
        str(E2E_SCRIPT),
        "--request", request,
        "--enable-automate-branch",
        "--enable-automate-qa-loop",
        "--enable-automate-build",
        "--enable-automate-release",
        "--automate-repo", "SongJongwon/nexus-alpha",
        "--automate-release-tag", tag,
        "--max-retries", str(max_retries),
    ]
    print(
        f"[ITER {iter_idx}] launching subprocess — log={iter_log}",
        flush=True,
    )

    wall_start = datetime.now()
    with open(iter_log, "w", encoding="utf-8") as f:
        proc = subprocess.run(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
    wall_elapsed = (datetime.now() - wall_start).total_seconds()

    summary_path = _latest_summary_after(pre_run_ts)
    if summary_path is None:
        return {
            "iteration": iter_idx,
            "exit_code": proc.returncode,
            "wall_elapsed_sec": wall_elapsed,
            "summary_path": None,
            "all_passed": False,
            "error": "no summary.json produced",
        }

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    dod = summary.get("m5_qa_dod_checks") or {}
    qa_decision = summary.get("qa_decision_final") or {}
    return {
        "iteration": iter_idx,
        "exit_code": proc.returncode,
        "wall_elapsed_sec": wall_elapsed,
        "summary_path": str(summary_path.relative_to(PROJECT_ROOT)),
        "status": summary.get("status"),
        "elapsed_sec": summary.get("elapsed_sec"),
        "dod_checks": {k: dod.get(k) for k in DOD_KEYS},
        "all_passed": bool(dod.get("all_passed")),
        "qa_retry_count": qa_decision.get("retry_count") if isinstance(qa_decision, dict) else None,
        "artifact_category": (
            summary.get("result_introspection", {}) or {}
        ).get("artifact_category") if isinstance(
            summary.get("result_introspection"), dict
        ) else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="후보 N — Track B DoD 7/7 안정성 반복 검증"
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--request",
        type=str,
        default="네이버 쇼핑 가격 크롤링 스크립트",
    )
    parser.add_argument("--max-retries", type=int, default=1)
    args = parser.parse_args(argv)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUTS_DIR / f"dod_stability_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[STABILITY] start ts={ts} iterations={args.iterations}", flush=True)
    print(f"[STABILITY] request={args.request!r}", flush=True)
    print(f"[STABILITY] output_dir={out_dir.relative_to(PROJECT_ROOT)}", flush=True)

    results: list[dict] = []
    for i in range(1, args.iterations + 1):
        tag = f"v0.1.0-dod-stability-{ts}-iter{i}"
        print(
            f"\n========== ITER {i}/{args.iterations} (tag={tag}) ==========",
            flush=True,
        )
        try:
            res = _run_one_iteration(
                iter_idx=i,
                request=args.request,
                tag=tag,
                max_retries=args.max_retries,
                log_dir=out_dir,
            )
        except Exception as exc:  # noqa: BLE001
            res = {
                "iteration": i,
                "all_passed": False,
                "error": repr(exc),
            }
        results.append(res)

        marker = "PASS" if res.get("all_passed") else "FAIL"
        elapsed_min = (res.get("elapsed_sec") or res.get("wall_elapsed_sec") or 0) / 60
        print(
            f"[ITER {i}] result={marker} elapsed={elapsed_min:.2f}min "
            f"retry={res.get('qa_retry_count')} "
            f"category={res.get('artifact_category')}",
            flush=True,
        )

        with open(out_dir / "aggregate.json", "w", encoding="utf-8") as f:
            json.dump(
                _build_aggregate(args, ts, results),
                f,
                indent=2,
                ensure_ascii=False,
            )

    aggregate = _build_aggregate(args, ts, results)
    with open(out_dir / "aggregate.json", "w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2, ensure_ascii=False)

    print(
        f"\n[STABILITY] DONE pass={aggregate['pass_count']}/{args.iterations} "
        f"total_elapsed={aggregate['total_elapsed_min']:.2f}min",
        flush=True,
    )
    print(f"[STABILITY] aggregate={out_dir / 'aggregate.json'}", flush=True)

    return 0 if aggregate["pass_count"] == args.iterations else 2


def _build_aggregate(args, ts: str, results: list[dict]) -> dict:
    pass_count = sum(1 for r in results if r.get("all_passed") is True)
    fail_count = sum(1 for r in results if not r.get("all_passed"))
    total_elapsed_sec = sum(
        (r.get("elapsed_sec") or r.get("wall_elapsed_sec") or 0.0)
        for r in results
    )
    return {
        "candidate": "N — DoD 7/7 stability",
        "started_at_ts": ts,
        "finished_at": datetime.now().isoformat(),
        "iterations_requested": args.iterations,
        "iterations_completed": len(results),
        "request": args.request,
        "max_retries": args.max_retries,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "stability_ratio": (
            pass_count / len(results) if results else 0.0
        ),
        "total_elapsed_min": total_elapsed_sec / 60.0,
        "results": results,
    }


if __name__ == "__main__":
    sys.exit(main())
