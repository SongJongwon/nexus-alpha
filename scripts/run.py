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
    vision_qa_summary: Optional[str] = None,
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
    if vision_qa_summary:
        print(f"  👁️  Vision : {vision_qa_summary}")
    if release_url:
        print(f"  🔗 Release: {release_url}")
    print()


# ---------------------------------------------------------------------------
# Vision QA — PR #141 Phase 2 (본인 비전 통찰 6, D-3)
# ---------------------------------------------------------------------------
def _run_vision_qa(
    exe_path: Path,
    outputs_dir: Path,
    *,
    skip_vision: bool = False,
) -> Optional[str]:
    """빌드된 .exe 에 대해 gui_test_executor 호출 → 한 줄 요약 반환.

    PR #141 Phase 2 (2026-05-15, 본인 비전 통찰 6 D-3 처방):
        ``gui_test_executor.run_gui_test`` 는 PR #133 단계에서 완성됐으나 production
        path 에서 호출 X (호출자는 docstring 예시 + 별도 E2E 스크립트만). 본 wiring
        으로 ``scripts/run.py --build`` 의 .exe 산출 직후 자동 검증 — 친구 베타의
        Message_App.exe 같이 *어떤 에이전트도 시각적으로 본 적 없는* .exe 회귀 차단.

    실패 격리:
        Vision QA 자체 실패 (pyautogui 미설치 / Vision API 키 누락 등) 는 워크플로
        차단 사유 아님 — 경고 메시지 + None 반환. ``--no-vision-qa`` 로 강제 skip.
    """
    try:
        from src.agents.qa.gui_test_executor import run_gui_test
    except ImportError:
        return None

    vision_dir = outputs_dir / "vision_qa"
    vision_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_gui_test(
            target_path=exe_path,
            output_dir=vision_dir,
            skip_vision=skip_vision,
        )
    except Exception as exc:  # noqa: BLE001 — wiring 실패는 정보로만
        return f"[VISION ERROR] {exc!r}"

    try:
        # PR #146 의 shared_kickoff_decisions.yaml 옆에 summary 함께 보존
        (vision_dir / "summary.txt").write_text(
            result.summary_line(), encoding="utf-8"
        )
    except OSError:
        pass
    return result.summary_line()


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

    # PR #141 Phase 2 — Vision QA wiring (build 산출 .exe 가 있고 --no-vision-qa 미지정)
    vision_summary: Optional[str] = None
    if exe_path and exe_path.exists() and not args.no_vision_qa:
        _print_section("Vision QA — 시각 검증")
        vision_summary = _run_vision_qa(exe_path, outputs_dir)
        if vision_summary:
            print(f"  {vision_summary}")
        else:
            print("  (Vision QA skip — gui_test_executor 호출 불가)")

    _print_result_summary("A", elapsed, outputs_dir, exe_path, release_url, vision_summary)
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


def _prompt_track(default_track: str, input_fn=input) -> str:
    """Track 선택 prompt — PR #115: 'b' 키 충돌 회피 (Build 옵션과 혼동 가능).

    숫자 1/2 로 선택 — 'a'/'b' 입력은 default 로 fallback.

    Args:
        default_track: 자동 감지된 Track ('A' or 'B').
        input_fn: ``input()`` 주입 (테스트용, 기본 builtins.input).
    """
    print(f"  자동 감지 Track: **{default_track}**")
    print("    1) Track A — Calculator-style GUI/CLI 앱")
    print("    2) Track B — 5 도메인 자동화 (스크래핑/RPA/API/파싱/DevOps)")
    try:
        choice = input_fn(f"  선택 [Enter={default_track} / 1 / 2]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default_track
    if choice == "1":
        return "A"
    if choice == "2":
        return "B"
    return default_track


def _prompt_build(input_fn=input) -> bool:
    """Build 옵션 인터랙티브 prompt — PR #115 신설.

    Track 결정 후 별도 단계로 호출. ``--build`` 플래그 미지정 + 인터랙티브 모드일 때만.
    PyInstaller .exe 빌드는 +30~60초 추가 시간이 들어 사용자 명시적 확인 필요.

    Args:
        input_fn: ``input()`` 주입 (테스트용, 기본 builtins.input).
    """
    print()
    print("  Build (.exe 생성)?")
    print("    y) PyInstaller 로 .exe 빌드 (+30~60초, 산출물에 .exe 포함)")
    print("    N) 코드 + 사양만 산출 (.exe 없음, 빠름)")
    try:
        choice = input_fn("  빌드 [y/N, Enter=N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return choice in ("y", "yes")


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
    parser.add_argument(
        "--no-vision-qa", action="store_true", default=False,
        help=(
            "PR #141 Phase 2 — Vision QA 강제 skip. 기본은 --build 시 자동 활성. "
            "pyautogui/Vision API 미설치 환경에서 강제 차단할 때 사용."
        ),
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

    # 2.5. Build 결정 (PR #115) — --build 미지정 + 인터랙티브 모드일 때 별도 prompt.
    # Track 선택 ('a'/'b' 키) 와 Build 옵션 ('b') 입력 혼동 방지.
    if not args.build and not args.non_interactive:
        args.build = _prompt_build()

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
