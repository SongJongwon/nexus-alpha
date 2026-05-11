# -*- coding: utf-8 -*-
"""Alpha 진입점 (scripts/run.py) 정적 검증 (PR #102).

배경:
    install.ps1 + scripts/run.py 가 Nexus Alpha 의 Alpha 단계 진입점.
    실 LLM 호출 없이 *argparse + Track 라우팅 휴리스틱* 만 단위 검증.

본 테스트는 LLM 미호출 — FakeProvider / 워크플로 동작은 별도 test 파일에서 cover.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_PY_PATH = PROJECT_ROOT / "scripts" / "run.py"
INSTALL_PS1_PATH = PROJECT_ROOT / "install.ps1"


def _load_run_module():
    """``scripts/run.py`` 를 일반 모듈로 import.

    ``scripts/`` 은 ``sys.path`` 에 없으므로 importlib.util 로 직접 로드.
    """
    spec = importlib.util.spec_from_file_location("alpha_run", RUN_PY_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["alpha_run"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


# ---------------------------------------------------------------------------
# 1. 파일 존재 + 기본 구조
# ---------------------------------------------------------------------------


def test_install_ps1_exists_at_repo_root() -> None:
    """install.ps1 이 프로젝트 루트에 존재해야 한다 (irm 한 줄 설치 지원)."""
    assert INSTALL_PS1_PATH.exists(), "install.ps1 missing at repo root"
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 필수 키워드: irm 패턴 + step
    assert "Requires -Version 5.1" in text
    assert "NEXUS_ALPHA_DIR" in text  # 사용자 정의 설치 경로
    assert "git clone" in text or "git pull" in text
    assert "venv" in text
    assert "scripts\\run.py" in text or "scripts/run.py" in text


def test_env_example_exists_at_repo_root() -> None:
    """.env.example template 이 프로젝트 루트에 존재해야 한다 (PR #104)."""
    env_example = PROJECT_ROOT / ".env.example"
    assert env_example.exists(), ".env.example missing at repo root"
    text = env_example.read_text(encoding="utf-8")
    # 필수 환경변수 키 (값은 placeholder 만 — leak 차단)
    assert "LLM_PROVIDER=" in text
    assert "LANGFUSE_PUBLIC_KEY=" in text
    assert "LANGFUSE_SECRET_KEY=" in text
    assert "LANGFUSE_HOST=" in text
    # placeholder 패턴 (실 키 아님)
    assert "<your-public-key>" in text or "your-public-key" in text
    assert "pk-lf-" in text  # public key prefix 안내
    # 실 키 fragment 없음 (PR #103 leak 회귀 차단)
    assert "09fedad5" not in text, "actual LangFuse key leaked into .env.example"


def test_install_ps1_has_env_initialization_step() -> None:
    """install.ps1 이 .env.example → .env 자동 복사 로직을 포함 (PR #104)."""
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    assert "Initialize-EnvFile" in text, "Initialize-EnvFile function missing"
    assert ".env.example" in text
    assert "Copy-Item" in text
    # step 6/6 — PR #104 에서 5 → 6 으로 증가
    assert "Step 6/6" in text


def test_install_ps1_pull_failure_resets_and_reclones() -> None:
    """install.ps1 이 git 동기화 실패 시 fresh clone 으로 자동 복구 (PR #106).

    배경:
        PR #102/#104 의 ``Get-Repo`` 는 git pull --ff-only 실패 시 *경고만* 출력
        하고 계속 진행 → 사용자 환경이 broken 상태.

    PR #106 처방:
        - ``Update-ExistingRepo`` 가 단계별 ``$LASTEXITCODE`` 확인 → 실패 시 $false 반환
        - ``Reset-InstallDirAndClone`` 가 ``.env`` 백업 → ``.broken.{ts}`` rename →
          fresh clone → ``.env`` 복원

    회귀 차단 — 본 테스트가 깨지면 install.ps1 이 동기화 실패에서 자동 복구
    안 되어 사용자가 수동 정리를 강제 당함.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 3 신규 헬퍼 함수
    assert "function Update-ExistingRepo" in text
    assert "function Reset-InstallDirAndClone" in text
    assert "function Invoke-CleanClone" in text
    # 동기화 실패 recover 로직 키워드
    assert "fresh clone" in text, "fresh clone 복구 메시지 누락"
    assert ".broken." in text, ".broken.{timestamp} 백업 패턴 누락"
    # .env 보존 (사용자 시크릿 손실 방지)
    assert "envBackup" in text or "env_backup" in text, ".env 백업 로직 누락"
    # 안전한 rename 패턴 (즉시 Remove-Item -Recurse 가 아닌)
    assert "Rename-Item" in text, "Rename-Item 안전 백업 누락"


def test_install_ps1_uses_reset_hard_not_pull() -> None:
    """install.ps1 이 git pull --ff-only 대신 git fetch + reset --hard 사용 (PR #107).

    배경:
        PR #102~#106 의 ``Update-ExistingRepo`` 는 ``git pull --ff-only`` 사용.
        로컬 추적 파일 수정 / divergence 시 자주 fail → Reset-InstallDirAndClone
        (PR #106) fallback 으로 우회. 비용: ``.broken.{ts}`` 폴더 누적.

    PR #107 처방:
        ``git fetch origin $BRANCH`` + ``git reset --hard origin/$BRANCH`` 으로
        *destructive sync* — 추적 파일 로컬 변경 모두 폐기. .env / .venv /
        outputs 등 untracked 는 보존 (.gitignore 효과).

    효과:
        대부분 경우 reset --hard 만으로 동기화 성공 → ``.broken.{ts}`` fallback
        가능성 감소. 사용자 의도 (installer 는 코드 수정자 아님) 와 일치.

    회귀 차단 — 본 테스트가 깨지면 git pull 으로 회귀 또는 reset --hard 누락.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 신규 패턴: git fetch + reset --hard origin/$BRANCH
    assert "git fetch origin" in text, "git fetch origin 누락"
    assert "git reset --hard" in text, "git reset --hard 누락"
    assert 'origin/$BRANCH' in text, 'origin/$BRANCH 참조 누락'
    # Update-ExistingRepo 함수 본문에 git pull 잔존 없음
    import re
    match = re.search(
        r"function Update-ExistingRepo\s*\{(.*?)\n\}\n", text, re.DOTALL
    )
    assert match is not None, "Update-ExistingRepo 함수 추출 실패"
    update_body = match.group(1)
    # 주석 (#로 시작) 제거 후 git pull 호출 부재 검증
    import re as _re
    body_no_comments = _re.sub(r"#.*", "", update_body)
    assert "git pull" not in body_no_comments, (
        "Update-ExistingRepo 안에 git pull 실 호출 잔존 — PR #107 reset --hard 로 전환 미완료"
    )
    # destructive sync 안내 주석
    assert "destructive" in text or "로컬 변경 폐기" in text, (
        "destructive sync 의도 주석 누락 — 사용자 혼란 위험"
    )


def test_install_ps1_python_version_check_rejects_3_14_plus() -> None:
    """install.ps1 의 Python 버전 체크가 3.14+ 를 차단 (PR #110, PR #105 forward-proof 반전).

    배경:
        PR #105 는 ``major -gt 3 OR (major == 3 AND minor >= 13)`` 으로 4.x 까지
        forward-proof 허용. 그러나 CrewAI 1.14.1 의 Python 지원 범위는 ``>=3.10,<3.14``
        — 3.14+ 에서 의존성 (chromadb / instructor / pydantic-core) 빌드 실패.
        사용자 보고로 PR #110 에서 정책 반전.

    PR #110 처방:
        - 3.10 ~ 3.13.x: 정상 통과 (CrewAI 호환 범위)
        - 3.14+ / 4.x: ``Fail`` 호출 + 3.13 설치 안내 (winget + py launcher + PATH)
        - 3.10 미만: ``Fail`` 호출 + 3.13 설치 안내

    회귀 차단 — 본 테스트가 깨지면 사용자가 3.14 에서 install 시 의존성 빌드
    fail 단계까지 진행 후 mysterious 실패 (재발 사례).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 기존 restrictive regex 가 제거되었는지 (PR #105 부터 유지)
    assert "3.1[3-9]" not in text, "Restrictive regex from pre-PR #105 still present"
    # PR #110 정상 범위 비교 키워드 (3.10 ~ 3.13 = CrewAI 1.14.1 지원)
    assert "minor -ge 10" in text, "minor >= 10 lower bound missing"
    assert "minor -le 13" in text, "minor <= 13 upper bound missing"
    # 3.14+ 차단 분기
    assert "minor -ge 14" in text, "3.14+ rejection branch missing"
    # PR #105 의 forward-proof 분기가 *허용* 로직에 잔존하면 안 됨.
    # 새 로직: 허용은 ``$major -eq 3 -and $minor -ge 10 -and $minor -le 13``.
    import re as _re
    accept_match = _re.search(
        r"if\s*\(\s*\$major\s+-eq\s+3\s+-and\s+\$minor\s+-ge\s+10\s+-and\s+\$minor\s+-le\s+13\s*\)",
        text,
    )
    assert accept_match is not None, (
        "허용 조건 '$major -eq 3 -and $minor -ge 10 -and $minor -le 13' 누락 — "
        "PR #110 의 3.10~3.13 정상 범위 분기가 missing"
    )
    # 안내 메시지 핵심 키워드
    assert "CrewAI 1.14.1" in text, "CrewAI 호환 안내 누락"
    assert "py -3.13" in text, "py launcher 안내 누락"
    assert "winget install --id Python.Python.3.13" in text, (
        "winget 설치 안내 누락"
    )
    # 정규식 캡처 그룹 패턴 (유지)
    assert r"Python\s+(\d+)\.(\d+)" in text, "version capture regex missing"


def test_env_example_no_secret_values_committed() -> None:
    """``.env.example`` 에 sk-ant- / sk-lf- / pk-lf- 실 값이 없어야 한다.

    PR #103 의 leak 회귀 차단 — public 저장소에 실 secret 절대 금지.
    placeholder (``<your-...>`` 또는 16진 미만) 만 허용.
    """
    env_example = PROJECT_ROOT / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    import re
    # sk-ant- 뒤 영숫자 30자 이상 = 실 Anthropic 키 패턴
    real_anthropic = re.search(r"sk-ant-[a-zA-Z0-9_-]{30,}", text)
    assert real_anthropic is None, f"Real ANTHROPIC key in .env.example: {real_anthropic}"
    # sk-lf- 뒤 16진 30자 이상 = 실 LangFuse secret
    real_langfuse_sk = re.search(r"sk-lf-[a-f0-9-]{30,}", text)
    assert real_langfuse_sk is None, f"Real LangFuse secret in .env.example: {real_langfuse_sk}"
    # pk-lf- 뒤 16진 30자 이상 = 실 LangFuse public (PR #103 leak 회귀)
    real_langfuse_pk = re.search(r"pk-lf-[a-f0-9-]{30,}", text)
    assert real_langfuse_pk is None, f"Real LangFuse public in .env.example: {real_langfuse_pk}"


def test_run_py_exists_at_scripts() -> None:
    """scripts/run.py 가 존재해야 한다."""
    assert RUN_PY_PATH.exists(), "scripts/run.py missing"


def test_run_py_has_main_entrypoint(run_mod) -> None:
    """``main`` 함수 + ``if __name__ == '__main__'`` 진입점."""
    assert callable(getattr(run_mod, "main", None))


# ---------------------------------------------------------------------------
# 2. _detect_track 휴리스틱
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text,expected",
    [
        # Track A — 단순 GUI/CLI 앱 키워드
        ("계산기 만들어줘", "A"),
        ("Calculator 만들어줘", "A"),
        ("타이머 앱", "A"),
        ("Excel 매출 분석 보고서", "A"),  # '보고서' Track A
        ("", "A"),  # 빈 입력 → A (default)
        # Track B — 자동화/도메인 키워드
        ("네이버 쇼핑 가격 크롤링", "B"),
        ("Playwright 으로 스크래핑", "B"),
        ("Excel 파일 자동 입력 RPA", "B"),  # rpa Track B
        ("GitHub API 이슈 자동 생성", "B"),
        ("Docker Dockerfile 작성", "B"),
        ("CSV 처리 데이터 변환 스크립트", "B"),
    ],
)
def test_detect_track_heuristic(run_mod, request_text, expected) -> None:
    assert run_mod._detect_track(request_text) == expected


def test_detect_track_case_insensitive(run_mod) -> None:
    """대소문자 무관 매칭 — 'PLAYWRIGHT' 도 Track B."""
    assert run_mod._detect_track("PLAYWRIGHT 사용") == "B"
    assert run_mod._detect_track("CALCULATOR 만들기") == "A"


# ---------------------------------------------------------------------------
# 3. argparse 시그니처
# ---------------------------------------------------------------------------


def test_parse_args_defaults(run_mod) -> None:
    args = run_mod._parse_args([])
    assert args.request == ""
    assert args.track == "auto"
    assert args.build is False
    assert args.force_cli is False
    assert args.release is False
    assert args.repo == ""
    assert args.tag == ""
    assert args.verbose is False
    assert args.non_interactive is False


def test_parse_args_track_a_full(run_mod) -> None:
    args = run_mod._parse_args([
        "--request", "계산기 만들어줘",
        "--track", "A",
        "--build",
        "--force-cli",
    ])
    assert args.request == "계산기 만들어줘"
    assert args.track == "A"
    assert args.build is True
    assert args.force_cli is True


def test_parse_args_track_b_full(run_mod) -> None:
    args = run_mod._parse_args([
        "--request", "네이버 크롤링",
        "--track", "B",
        "--build",
        "--release",
        "--repo", "owner/name",
        "--tag", "v0.1.0-demo",
    ])
    assert args.request == "네이버 크롤링"
    assert args.track == "B"
    assert args.build is True
    assert args.release is True
    assert args.repo == "owner/name"
    assert args.tag == "v0.1.0-demo"


def test_parse_args_invalid_track_rejected(run_mod) -> None:
    with pytest.raises(SystemExit):
        run_mod._parse_args(["--track", "C"])


# ---------------------------------------------------------------------------
# 4. main exit code 시나리오 (LLM 호출 X)
# ---------------------------------------------------------------------------


def test_main_non_interactive_without_request_exits_2(run_mod, capsys) -> None:
    """``--non-interactive`` + ``--request`` 미지정 → exit 2."""
    rc = run_mod.main(["--non-interactive"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--request" in captured.err


def test_main_release_without_repo_exits_2(run_mod, capsys) -> None:
    """``--release`` + ``--repo`` 미지정 → exit 2."""
    rc = run_mod.main([
        "--non-interactive",
        "--request", "계산기",
        "--track", "A",
        "--release",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--repo" in captured.err
