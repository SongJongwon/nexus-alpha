"""Nexus Alpha 자연어 입력 진입점 (Alpha 단계 — PR #102).

사용자가 한 줄 자연어 요청을 입력 → Track 자동 라우팅 → 풀체인 실행 →
.exe + (선택) Draft Release URL 표시.

본 스크립트는 *Alpha* 단계 진입점입니다 (Streamlit Beta / Electron/Tauri
Release 의 *전 단계* — `docs/context/next_session_context.md` §10 참고).

사용 예 (인터랙티브):
    .venv/Scripts/python.exe scripts/run.py
    → 자연어 입력창 prompt → Track 자동 선택 → 풀체인 실행

사용 예 (CLI 인자):
    # Track A (Calculator-style GUI/CLI 앱)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "계산기 만들어줘" --track A --build

    # Track B (5 도메인 자동화)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "네이버 쇼핑 가격 크롤링" --track B --build

    # 자동 라우팅 (기본) — heuristic 으로 Track 결정
    .venv/Scripts/python.exe scripts/run.py --request "계산기 만들어줘"

    # Draft Release 발행 (gh CLI + repo 필수)
    .venv/Scripts/python.exe scripts/run.py \\
        --request "엑셀 분석 PDF 보고서" --track A --build --force-cli \\
        --release --repo "SongJongwon/nexus-alpha" --tag "v0.1.0-demo"

종료 코드:
    0 — 풀체인 정상 종료 (산출 .exe 또는 .py 생성)
    1 — 실행 중 오류 (Provider 초기화 / 의존성 등)
    2 — 사용자 입력 부재 (인터랙티브 prompt 빈 입력)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Track 자동 라우팅 휴리스틱
# ---------------------------------------------------------------------------
# Track B 키워드 — Track B 도메인 (자동화 / 데이터 / 스크래핑 / API / DevOps)
_TRACK_B_KEYWORDS = (
    "크롤링",
    "스크래핑",
    "scrap",
    "crawl",
    "playwright",
    "selenium",
    "rpa",
    "자동화 스크립트",
    "api",
    "webhook",
    "graphql",
    "엑셀",
    "excel",
    "pdf 파싱",
    "pdf parse",
    "csv 처리",
    "데이터 변환",
    "도커",
    "dockerfile",
    "github actions",
    "ci/cd",
)

# Track A 키워드 — Calculator 류 GUI/CLI 앱 (default fallback)
_TRACK_A_KEYWORDS = (
    "계산기",
    "calculator",
    "메모장",
    "notepad",
    "타이머",
    "timer",
    "변환기",
    "converter",
    "보고서",
    "report",
    "gui",
    "데스크탑 앱",
)


def _detect_track(request: str) -> str:
    """자연어 요청에서 Track A/B 자동 판단.

    매칭 규칙:
        - Track B 키워드 매칭 수 > Track A → 'B'
        - 그 외 → 'A' (default — Calculator-style GUI/CLI)

    Returns:
        ``'A'`` 또는 ``'B'``.
    """
    if not request:
        return "A"
    text = request.lower()
    b_score = sum(1 for k in _TRACK_B_KEYWORDS if k.lower() in text)
    a_score = sum(1 for k in _TRACK_A_KEYWORDS if k.lower() in text)
    return "B" if b_score > a_score else "A"


# ---------------------------------------------------------------------------
# 출력 helpers
# ---------------------------------------------------------------------------
def _print_banner() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Nexus Alpha — Alpha (자연어 입력 → .exe 풀체인)             ║")
    print("║  Track A: Calculator-style GUI/CLI                           ║")
    print("║  Track B: 5 도메인 자동화 (스크래핑/RPA/API/파싱/DevOps)     ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def _print_section(title: str) -> None:
    print()
    print(f"━━ {title} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def _print_result_summary(
    track: str,
    elapsed_sec: float,
    outputs_dir: Optional[Path],
    exe_path: Optional[Path],
    release_url: Optional[str],
) -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print(f"║  결과 — Track {track} ({elapsed_sec/60:.2f}min)" + " " * (45 - len(f"Track {track} ({elapsed_sec/60:.2f}min)")) + "║")
    print("╚══════════════════════════════════════════════════════════════╝")
    if outputs_dir:
        print(f"  📁 outputs : {outputs_dir}")
    if exe_path and exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  📦 .exe    : {exe_path} ({size_mb:.2f} MB)")
    elif exe_path:
        print(f"  📦 .exe (예상): {exe_path} — 생성 안 됨")
    if release_url:
        print(f"  🔗 Release: {release_url}")
    print()


# ---------------------------------------------------------------------------
# Track A / B 실행
# ---------------------------------------------------------------------------
def _run_track_a(args: argparse.Namespace) -> int:
    """Track A — Calculator-style GUI/CLI 앱 풀체인."""
    from src.workflows.analyze_and_implement import run_analyze_and_implement

    outputs_dir = PROJECT_ROOT / "outputs" / f"alpha_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    start = datetime.now()

    result = run_analyze_and_implement(
        args.request,
        outputs_dir=outputs_dir,
        verbose=args.verbose,
        enable_gui_branch=not args.force_cli,
        enable_build_branch=args.build,
        enable_release_branch=args.release,
        enable_executor=args.build,
        enable_publish=args.release,
        publish_as_draft=True,
        repo_url=args.repo,
    )

    elapsed = (datetime.now() - start).total_seconds()
    exe_path = getattr(result, "executor_result", None)
    exe_path = Path(exe_path.exe_path) if exe_path and getattr(exe_path, "exe_path", None) else None
    release_url = None
    publish = getattr(result, "publish_result", None)
    if publish:
        release_url = getattr(publish, "release_url", None)
    _print_result_summary("A", elapsed, outputs_dir, exe_path, release_url)
    return 0


def _run_track_b(args: argparse.Namespace) -> int:
    """Track B — 5 도메인 자동화 풀체인."""
    from src.workflows.automate_workflow import run_automate_workflow

    outputs_dir = PROJECT_ROOT / "outputs" / f"alpha_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    start = datetime.now()

    result = run_automate_workflow(
        args.request,
        outputs_dir=outputs_dir,
        verbose=args.verbose,
        enable_qa_loop=args.build,
        enable_build=args.build,
        enable_release=args.release,
        repo_url=args.repo,
        release_tag=args.tag,
        publish_as_draft=True,
    )

    elapsed = (datetime.now() - start).total_seconds()
    executor = getattr(result, "executor_result", None)
    exe_path = Path(executor.exe_path) if executor and getattr(executor, "exe_path", None) else None
    release_url = None
    publish = getattr(result, "publish_result", None)
    if publish:
        release_url = getattr(publish, "release_url", None)
    _print_result_summary("B", elapsed, result.saved_dir or outputs_dir, exe_path, release_url)
    return 0


# ---------------------------------------------------------------------------
# 인터랙티브 입력
# ---------------------------------------------------------------------------
def _prompt_request() -> str:
    """자연어 요청 prompt — 빈 입력은 종료."""
    _print_section("자연어 요청 입력")
    print("  예시:")
    print("    - 계산기 만들어줘")
    print("    - 매장별 시간 매출 Excel 분석 PDF 보고서")
    print("    - 네이버 쇼핑 가격 크롤링 스크립트")
    print()
    try:
        request = input("👉 요청: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return request


def _prompt_track(default_track: str) -> str:
    print(f"  자동 감지 Track: **{default_track}**")
    try:
        choice = input(f"  사용? [Enter=수락 / a / b]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default_track
    if choice in ("a", "b"):
        return choice.upper()
    return default_track


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nexus Alpha 자연어 입력 → .exe 풀체인 (Alpha 단계)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--request", "-r", default="",
        help="자연어 요청. 미지정 시 인터랙티브 prompt.",
    )
    parser.add_argument(
        "--track", choices=["A", "B", "auto"], default="auto",
        help="Track 강제 (기본: auto — 휴리스틱 라우팅).",
    )
    parser.add_argument(
        "--build", action="store_true", default=False,
        help="PyInstaller .exe 빌드 활성 (default off — 사양만 산출).",
    )
    parser.add_argument(
        "--force-cli", action="store_true", default=False,
        help="Track A 에서 GUI 분기 비활성 → CLI 산출 강제 (active 4/4 도달).",
    )
    parser.add_argument(
        "--release", action="store_true", default=False,
        help="gh release create --draft 활성 (gh CLI + --repo 필수).",
    )
    parser.add_argument(
        "--repo", default="",
        help="GitHub repo (예: 'owner/name'). --release 시 필수.",
    )
    parser.add_argument(
        "--tag", default="",
        help="Track B release tag (예: 'v0.1.0-demo'). --release 시 필수.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="CrewAI 중간 로그 출력.",
    )
    parser.add_argument(
        "--non-interactive", action="store_true", default=False,
        help="인터랙티브 prompt 비활성 — --request 필수.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    _print_banner()
    args = _parse_args(argv)

    # 1. 자연어 요청
    if not args.request:
        if args.non_interactive:
            print("✗ --non-interactive 모드 — --request 필수.", file=sys.stderr)
            return 2
        args.request = _prompt_request()
        if not args.request:
            print("✗ 빈 요청 — 종료.", file=sys.stderr)
            return 2

    # 2. Track 결정
    if args.track == "auto":
        detected = _detect_track(args.request)
        if args.non_interactive:
            args.track = detected
        else:
            args.track = _prompt_track(detected)

    # 3. release 검증
    if args.release:
        if not args.repo:
            print("✗ --release 사용 시 --repo 필수 (예: 'owner/name').", file=sys.stderr)
            return 2

    # 4. 실행 summary
    _print_section("실행 시작")
    print(f"  Track    : {args.track}")
    print(f"  Request  : {args.request!r}")
    print(f"  Build    : {args.build}")
    print(f"  Release  : {args.release}")
    if args.repo:
        print(f"  Repo     : {args.repo}")
    print()

    try:
        if args.track == "A":
            return _run_track_a(args)
        else:
            return _run_track_b(args)
    except KeyboardInterrupt:
        print("\n✗ 사용자 중단.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ 실행 실패: {exc!r}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
