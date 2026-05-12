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


def test_install_ps1_skips_python_check_when_venv_exists() -> None:
    """install.ps1 이 기존 .venv 검출 시 시스템 python 체크 skip (PR #112).

    배경:
        PR #110 의 ``minor -ge 14 → Fail`` 정책이 ``py -3.13 -m venv`` 로 수동 venv 만든
        사용자에게도 적용되어 install 진행 불가 (시스템 ``python`` 이 3.14 라도
        venv 는 3.13). PR #110 안내 §2 워크플로 (3.13/3.14 공존 환경) 가
        Step 1/6 에서 미리 차단됨.

    PR #112 처방:
        - ``Test-Path $INSTALL_DIR\\.venv\\Scripts\\python.exe`` 검출 시 시스템
          python 체크 skip
        - 대신 venv 의 python 버전을 표시 (투명성)
        - gh CLI 체크는 그대로 수행 후 함수 종료 (``return``)

    회귀 차단 — 본 테스트가 깨지면 PR #110 안내 §2 워크플로 (수동 venv) 가 다시
    Step 1/6 차단에 부딪힘.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # PR #112 skip 분기 키워드
    assert "existingVenvPython" in text or "기존 .venv" in text, (
        "기존 .venv 검출 skip 분기 누락"
    )
    assert "\\.venv\\Scripts\\python.exe" in text, "venv python 경로 빌드 누락"
    assert "시스템 python" in text and "skip" in text, (
        "시스템 python skip 메시지 누락 (사용자 투명성)"
    )
    # skip 분기가 시스템 python 체크 *앞에* 위치 (early return).
    # 안정적 anchor: "Get-Command python" (시스템 python 체크의 첫 단계).
    skip_pos = text.find("기존 .venv")
    strict_pos = text.find("Get-Command python")
    assert skip_pos > 0 and strict_pos > skip_pos, (
        ".venv skip 분기가 시스템 python 체크보다 *뒤에* 배치됨 — early return 미작동"
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
    # 3.14+ 차단/fallback 분기 (PR #114 에서 즉시 Fail 대신 py -3.13 fallback 추가)
    assert "minor -ge 14" in text, "3.14+ branch missing"
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


# ---------------------------------------------------------------------------
# PR #114 — 3.14+ 자동 py -3.13 fallback (Test-Prereqs + Install-Venv)
# ---------------------------------------------------------------------------


def test_install_ps1_auto_py313_fallback_for_python_314_plus() -> None:
    """install.ps1 이 시스템 python 3.14+ 감지 시 자동으로 ``py -3.13`` fallback (PR #114).

    배경:
        PR #110 은 3.14+ 시 즉시 Fail + 수동 안내. 사용자가 매번 ``py -3.13 -m venv ...``
        수동 수행해야 함 (PR #112 의 .venv 검출 후 재실행 워크플로).

    PR #114 처방:
        Test-Prereqs 가 3.14+ 감지 시 ``Get-Command py`` + ``py -3.13 --version`` 확인:
        - launcher 있고 3.13 사용 가능 → ``$script:PYTHON_VENV_EXE='py'``,
          ``$script:PYTHON_VENV_ARGS=@('-3.13')`` 설정 후 진행
        - launcher 없거나 3.13 미설치 → Fail (3.13 설치 안내)

        Install-Venv 가 ``$script:PYTHON_VENV_EXE`` + ``$script:PYTHON_VENV_ARGS`` 로
        venv 생성 → ``py -3.13 -m venv .venv`` 자동 실행.

    회귀 차단 — 본 테스트가 깨지면 3.14 환경 사용자가 수동 venv 생성으로 되돌아감.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # script-scoped 변수 (Test-Prereqs 와 Install-Venv 간 공유)
    assert "$script:PYTHON_VENV_EXE" in text, (
        "$script:PYTHON_VENV_EXE 변수 누락 — Install-Venv 가 venv 생성 명령 모름"
    )
    assert "$script:PYTHON_VENV_ARGS" in text, "$script:PYTHON_VENV_ARGS 변수 누락"
    # 3.14+ fallback 의 핵심 키워드
    assert "py -3.13" in text, "py -3.13 launcher 참조 누락"
    assert "Get-Command py" in text, "py launcher 존재 확인 누락"
    assert "py -3.13 --version" in text, "py -3.13 버전 검증 누락"
    assert "fallback" in text.lower() or "fallback" in text, "fallback 키워드 누락"
    # Install-Venv 가 새 변수 사용
    import re as _re
    install_venv_match = _re.search(
        r"function Install-Venv\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert install_venv_match is not None, "Install-Venv 함수 추출 실패"
    install_body = install_venv_match.group(1)
    assert "$script:PYTHON_VENV_EXE" in install_body, (
        "Install-Venv 에서 $script:PYTHON_VENV_EXE 미사용 — Test-Prereqs 변수 미연결"
    )
    # 기존 hardcoded "& python -m venv" 가 fallback 변수로 교체되었어야 함
    body_no_comments = _re.sub(r"#.*", "", install_body)
    assert "& python -m venv" not in body_no_comments, (
        "Install-Venv 안에 hardcoded '& python -m venv' 잔존 — PR #114 fallback 변수 미적용"
    )


def test_install_ps1_auto_winget_python_install() -> None:
    """install.ps1 이 Python 3.13 미설치 시 winget 으로 자동 설치 (PR #117).

    배경:
        PR #114 의 ``py -3.13`` fallback 은 *Python 3.13 이 이미 어딘가 설치된*
        경우에만 작동. 3.13 자체가 없으면 (또는 3.14+ 단독 환경) 여전히 사용자
        수동 ``winget install Python.Python.3.13`` 필요.

    PR #117 처방:
        ``Install-Python313ViaWinget`` 함수 신설 — 3 시나리오에서 자동 호출:
        1. ``python`` 이 PATH 에 없음 (전혀 미설치)
        2. ``python`` 이 3.14+ 이고 ``py -3.13`` launcher fallback 도 실패
        3. ``python`` 이 3.10 미만 (3.9 / 3.8 등 EOL)

        자동 설치는 ``winget install --id Python.Python.3.13 -e --silent``
        + 약관 자동 수락. Python 공식 인스톨러는 메이저.마이너 별로 별도 디렉터리
        에 설치 — 기존 다른 Python 버전 *영향 없음* (side-by-side).

        설치 후 ``py -3.13 --version`` 검증 → 성공 시 ``$script:PYTHON_VENV_EXE='py'``
        + ``$script:PYTHON_VENV_ARGS=@('-3.13')`` 설정 → Install-Venv 가 자동 사용.

    회귀 차단 — 본 테스트가 깨지면 사용자가 3.14 단독 / 3.9 단독 / 미설치
    환경에서 ``irm | iex`` 시 다시 수동 winget 안내로 회귀.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 신규 함수 존재
    assert "function Install-Python313ViaWinget" in text, (
        "Install-Python313ViaWinget 함수 정의 누락"
    )
    # winget 명령 키워드
    assert "winget install --id Python.Python.3.13" in text, (
        "winget install --id Python.Python.3.13 호출 누락"
    )
    assert "--silent" in text, "--silent 비인터랙티브 설치 플래그 누락"
    assert "--accept-source-agreements" in text and "--accept-package-agreements" in text, (
        "winget 약관 자동 수락 플래그 누락 (사용자 비인터랙티브 보장)"
    )
    # 3 시나리오 모두 자동 설치 호출
    install_calls = text.count("Install-Python313ViaWinget")
    # 1 정의 + 3 호출 = 최소 4 occurrences
    assert install_calls >= 4, (
        f"Install-Python313ViaWinget 호출 횟수 부족 ({install_calls} 회) — "
        "3 시나리오 (python 미설치 / 3.14+ fallback fail / <3.10) 모두 자동 설치 호출 필요"
    )
    # side-by-side 안내 — 기존 Python 버전 보존 메시지
    assert "side-by-side" in text or "기존 Python 버전" in text, (
        "side-by-side 설치 (기존 버전 보존) 안내 누락"
    )
    # 자동 설치 후 PYTHON_VENV_EXE/ARGS 설정 — Install-Venv 가 py -3.13 사용하도록
    import re as _re
    install_func_match = _re.search(
        r"function Install-Python313ViaWinget\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert install_func_match is not None, "Install-Python313ViaWinget 함수 본문 추출 실패"
    install_body = install_func_match.group(1)
    assert "$script:PYTHON_VENV_EXE" in install_body, (
        "Install-Python313ViaWinget 가 $script:PYTHON_VENV_EXE 미설정 — Install-Venv 와 미연결"
    )
    assert "'-3.13'" in install_body, "py -3.13 launcher 인자 미설정"


def test_install_ps1_winget_uses_scope_user() -> None:
    """install.ps1 의 winget 명령이 ``--scope user`` 사용 — 관리자 권한 불필요 (PR #120).

    배경:
        PR #117 의 ``winget install`' 명령에 ``--scope`` 미지정 시 winget 의 기본값은
        패키지 manifest 의 scope 를 따름 — Python 3.13 의 경우 machine scope 가 기본 →
        UAC 권한 prompt 또는 비-admin 사용자 fail 위험.

    PR #120 처방:
        ``--scope user`` 명시 → ``%LOCALAPPDATA%\\Programs\\Python\\Python313\\`` 에
        per-user 설치 (관리자 권한 불필요, 기존 buang Python 버전 절대 미영향).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # --scope user 플래그 명시
    assert "--scope user" in text, (
        "winget --scope user 플래그 누락 — PR #120 의 관리자 권한 불필요 요구 미반영"
    )
    # winget 명령 자체에 --scope user 포함 (다른 곳에 떠도는 키워드 아니라)
    import re as _re
    winget_cmd = _re.search(
        r"winget install --id Python\.Python\.3\.13[^\n]*", text
    )
    assert winget_cmd is not None, "winget install 명령 자체 추출 실패"
    assert "--scope user" in winget_cmd.group(0), (
        "winget install 명령 자체에 --scope user 누락 — 다른 곳에만 떠 있을 가능성"
    )


def test_install_ps1_fail_prevents_window_close() -> None:
    """Fail 함수가 PowerShell 창 자동 닫힘 방지 (PR #120).

    배경:
        ``irm | iex`` 시나리오에서 ``Fail`` 의 ``exit 1`` 은 PowerShell 창을 즉시
        닫음 → 사용자가 에러 메시지를 못 읽음.

    PR #120 처방:
        ``Fail`` 이 ``exit`` 전에 ``Read-Host`` (또는 ``ReadKey``) 로 사용자 입력
        대기 — 창을 열린 상태로 유지. CI 환경 (``NEXUS_ALPHA_NO_PAUSE=1``) 에선
        즉시 종료 (CI 차단 회피).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # Fail 함수 본문 추출
    import re as _re
    fail_match = _re.search(r"function Fail\s*\{(.*?)\n\}\n", text, _re.DOTALL)
    assert fail_match is not None, "Fail 함수 본문 추출 실패"
    fail_body = fail_match.group(1)
    # ReadKey 또는 Read-Host 로 입력 대기
    assert "ReadKey" in fail_body or "Read-Host" in fail_body, (
        "Fail 함수에 입력 대기 (ReadKey/Read-Host) 누락 — 창 자동 닫힘 위험"
    )
    # CI 환경 회피 — NEXUS_ALPHA_NO_PAUSE 환경 변수
    assert "NEXUS_ALPHA_NO_PAUSE" in fail_body, (
        "CI 비인터랙티브 회피 (NEXUS_ALPHA_NO_PAUSE) 누락 — CI 무한 대기 위험"
    )


def test_install_ps1_winget_install_uses_try_catch() -> None:
    """Install-Python313ViaWinget 의 winget 호출이 try/catch 로 감싸짐 (PR #120).

    PowerShell 자체 예외 (network / authn / permission) 발생 시도 graceful 에러
    메시지 + Fail (pause) — 창이 즉시 닫히지 않도록 보장.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    install_func = _re.search(
        r"function Install-Python313ViaWinget\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert install_func is not None, "Install-Python313ViaWinget 함수 추출 실패"
    body = install_func.group(1)
    # try/catch + 상세 안내 메시지
    assert "try {" in body or "try{" in body, "winget 호출에 try 블록 누락"
    assert "} catch {" in body or "}catch{" in body, "winget 호출에 catch 블록 누락"
    # 수동 설치 fallback URL — 사용자 안내
    assert "python.org/downloads/release/python-3137" in body, (
        "수동 설치 fallback URL 누락 — 사용자가 자동 설치 실패 시 막힘"
    )


# ---------------------------------------------------------------------------
# PR #115 — scripts/run.py 의 _prompt_track / _prompt_build (Build 입력 혼동 회피)
# ---------------------------------------------------------------------------


def test_prompt_track_uses_numeric_choices(run_mod) -> None:
    """_prompt_track 이 'a'/'b' 대신 '1'/'2' 사용 (PR #115).

    배경: 사용자가 'b' 누르면 Track B 로 바뀌어서 Build 옵션과 혼동.
    PR #115: 숫자 1/2 로만 선택, 'a'/'b' 입력은 default 로 fallback.
    """
    # '1' → A
    monkey_in = _MockInput(["1"])
    assert run_mod._prompt_track("B", input_fn=monkey_in) == "A"
    # '2' → B
    assert run_mod._prompt_track("A", input_fn=_MockInput(["2"])) == "B"
    # 빈 입력 → default
    assert run_mod._prompt_track("A", input_fn=_MockInput([""])) == "A"
    assert run_mod._prompt_track("B", input_fn=_MockInput([""])) == "B"
    # 'a'/'b' 는 default 로 fallback (Build 혼동 회피)
    assert run_mod._prompt_track("A", input_fn=_MockInput(["b"])) == "A"
    assert run_mod._prompt_track("B", input_fn=_MockInput(["a"])) == "B"


def test_prompt_build_function_exists(run_mod) -> None:
    """_prompt_build 함수가 신규 정의되어 있어야 한다 (PR #115)."""
    assert callable(getattr(run_mod, "_prompt_build", None)), (
        "_prompt_build 함수 누락 — PR #115 분리 prompt 미구현"
    )


def test_prompt_build_yes_returns_true(run_mod) -> None:
    """y / yes → True, 그 외 → False (default off, 명시적 opt-in)."""
    assert run_mod._prompt_build(input_fn=_MockInput(["y"])) is True
    assert run_mod._prompt_build(input_fn=_MockInput(["Y"])) is True
    assert run_mod._prompt_build(input_fn=_MockInput(["yes"])) is True
    # 빈 입력 / N / 잘못된 입력 → False
    assert run_mod._prompt_build(input_fn=_MockInput([""])) is False
    assert run_mod._prompt_build(input_fn=_MockInput(["n"])) is False
    assert run_mod._prompt_build(input_fn=_MockInput(["x"])) is False


def test_run_py_source_has_prompt_build_function() -> None:
    """``scripts/run.py`` 소스에 ``_prompt_build`` 정의 + ``main()`` 에서 호출."""
    text = RUN_PY_PATH.read_text(encoding="utf-8")
    assert "def _prompt_build" in text, "_prompt_build 함수 정의 누락"
    assert "_prompt_build(" in text.replace("def _prompt_build(", ""), (
        "_prompt_build 호출 누락 — main() 통합 미완료"
    )
    # 기존 ``a / b`` UI 텍스트가 사라졌어야 함 (PR #115 혼동 회피)
    assert "[Enter=수락 / a / b]" not in text, (
        "기존 'a / b' prompt 잔존 — PR #115 Track 선택 UI 변경 미완료"
    )


# ---------------------------------------------------------------------------
# Helper — input mock for prompt 함수 테스트
# ---------------------------------------------------------------------------


class _MockInput:
    """``input()`` 호출 mock — list 순차 pop, 빈 list 시 EOFError."""

    def __init__(self, responses):
        self._responses = list(responses)

    def __call__(self, prompt=""):
        if not self._responses:
            raise EOFError("MockInput exhausted")
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# PR #121 — UTF-8 BOM 회귀 차단 (한국어 Windows 에서 즉시 닫힘 fix)
# ---------------------------------------------------------------------------


def test_install_ps1_has_no_utf8_bom() -> None:
    """install.ps1 이 UTF-8 BOM 으로 시작하면 *안 된다* (PR #122 — PR #121 revert).

    배경 (PR #121 실패):
        PR #121 가 BOM 을 추가해 한국 Windows ANSI mojibake 를 차단하려 했으나,
        ``irm | iex`` 시나리오에서 새 결함 발생:

        1. ``irm`` 가 GitHub raw 응답을 UTF-8 으로 decode 시 BOM 글자 (``\\uFEFF``)
           를 string 첫 글자로 *보존*
        2. ``iex`` 가 ``"\\uFEFF<# ..."`` 를 parse 시 ``\\uFEFF<#`` 를 하나의 cmdlet
           이름으로 인식 → ``"The term '\\uFEFF<#' is not recognized"`` 에러
        3. 사용자 PowerShell 창에 parse 에러 줄줄 → 실패

        라이브 검증 (PR #121 머지 후 사용자 보고):
            irm ... | iex
            iex : 위치 줄:10 문자:22
            +    (Electron/Tauri) 는 후속 단계.    ← comment block 내부가 code 로 파싱됨

    PR #122 처방:
        BOM 제거 (PR #121 revert) — ``irm | iex`` 정상 작동 복원.

        한국 Windows ANSI mojibake 위험은 *별도 경로* (README 의 file-based
        install 안내 또는 향후 PR) 에서 해결.

    회귀 차단 — 본 테스트가 깨지면 ``irm | iex`` 가 다시 실패.
    """
    bytes_data = INSTALL_PS1_PATH.read_bytes()
    assert len(bytes_data) >= 3, "install.ps1 크기가 충분하지 않음"
    bom_marker = bytes_data[:3]
    assert bom_marker != b"\xef\xbb\xbf", (
        f"install.ps1 첫 3 bytes 가 UTF-8 BOM ({bom_marker.hex()}) — "
        "irm | iex 시나리오에서 'unrecognized cmdlet' 에러 유발. BOM 제거 필요."
    )


def test_install_ps1_starts_with_powershell_comment_block() -> None:
    """install.ps1 이 PowerShell comment block (``<#``) 으로 시작해야 한다 (PR #122).

    BOM 없이 첫 2 bytes 가 ``<#`` 이어야 parser 가 comment-based help 로 인식.
    """
    bytes_data = INSTALL_PS1_PATH.read_bytes()
    assert bytes_data[:2] == b"<#", (
        f"install.ps1 본문이 '<#' 으로 시작 안 함 (실제: {bytes_data[:2].hex()}). "
        "comment-based help 미인식 → parse 에러 위험."
    )
