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
    # PR #123 — winget 은 ``python 미설치`` 시나리오 1건만 호출 (시스템 Python 없음)
    # 기존 Python 존재 (3.14+ / <3.10) 시는 Install-LocalPython313 (격리) 사용 — 시스템 미터치.
    # winget 함수는 fallback chain 내부에서 Install-LocalPython313 도 호출 (winget 실패 시).
    install_calls = text.count("Install-Python313ViaWinget")
    assert install_calls >= 2, (
        f"Install-Python313ViaWinget 호출 횟수 부족 ({install_calls} 회) — "
        "최소 1 정의 + 1 호출 (python 미설치 시나리오) 필요"
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
    # PR #123 — winget 실패 시 로컬 격리 fallback 호출
    assert "Install-LocalPython313" in install_body, (
        "winget 실패 시 Install-LocalPython313 fallback 호출 누락 — PR #123 graceful 회피 미구현"
    )


def test_install_ps1_local_python_install_for_wrong_version() -> None:
    """install.ps1 이 기존 Python 호환 안 됨 시 *로컬 격리 설치* 사용 (PR #123).

    배경 (사용자 정책 갱신):
        PR #117/#120 의 winget 자동 설치는 *시스템 / user-profile* 에 Python 추가 →
        사용자가 기존 Python 환경을 보존하고 싶을 때 부담스러움. 사용자 요청:

        "이미 설치되어있는 파이썬은 건들지 말고, 해당 프로그램 동작에 필요한
         Python 을 *install 로컬 폴더에 격리 설치* 해서 진행"

    PR #123 처방:
        - ``python`` 미설치: ``Install-Python313ViaWinget`` 호출 (시스템 깨끗하므로 추가 안전)
        - ``python`` 있으나 호환 안 됨 (3.14+ + py -3.13 미가용 / <3.10):
            ``Install-LocalPython313`` 호출 — Python 공식 ``.exe`` 인스톨러를
            ``TargetDir=$INSTALL_DIR\\python313`` 으로 로컬 격리 설치.

        로컬 인스톨러 옵션:
          - ``InstallAllUsers=0`` (per-user, 관리자 권한 불필요)
          - ``PrependPath=0`` (PATH 미변경, 시스템 영향 0)
          - ``Include_launcher=0`` (py.exe launcher 미설치, 시스템 영향 0)
          - ``Include_pip=1`` (venv 생성 후 의존성 설치 가능)

    회귀 차단 — 본 테스트가 깨지면 사용자가 의도와 달리 시스템 Python 환경이
    오염됨 (winget 광범위 사용 등).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 신규 함수 존재
    assert "function Install-LocalPython313" in text, (
        "Install-LocalPython313 함수 정의 누락"
    )
    # Python 공식 인스톨러 URL
    assert "python.org/ftp/python" in text, "python.org/ftp/python 다운로드 URL 누락"
    assert "amd64.exe" in text, "Windows amd64 인스톨러 파일명 패턴 누락"
    # 격리 설치 옵션 (시스템 영향 0)
    assert "TargetDir=" in text, "TargetDir 격리 경로 누락"
    assert "InstallAllUsers=0" in text, "InstallAllUsers=0 (per-user) 누락"
    assert "PrependPath=0" in text, "PrependPath=0 (PATH 미변경) 누락"
    assert "Include_launcher=0" in text, "Include_launcher=0 (py launcher 미설치) 누락"
    assert "Include_pip=1" in text, "Include_pip=1 (pip 포함) 누락"
    # 함수 본문에서 PYTHON_VENV_EXE 절대 경로 설정
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None, "Install-LocalPython313 함수 본문 추출 실패"
    body = local_func.group(1)
    assert "$script:PYTHON_VENV_EXE" in body, (
        "Install-LocalPython313 가 $script:PYTHON_VENV_EXE 미설정"
    )
    # 절대 경로 사용 (`<INSTALL_DIR>\python313\python.exe`)
    assert "python313" in body, "로컬 Python 격리 폴더 (python313) 참조 누락"
    # idempotent — 기존 로컬 Python 검출 시 재사용
    assert "재사용" in body or "Test-Path" in body, (
        "idempotent 처리 누락 — 재실행 시 중복 다운로드 위험"
    )


def test_install_ps1_test_prereqs_routes_correctly() -> None:
    """Test-Prereqs 가 시나리오별 정확한 설치 함수 호출 (PR #123 + PR #124).

    - python 미설치 → Install-Python313ViaWinget
    - 3.14+ + py -3.13 실패 → Install-LocalPython313
    - <3.10 → Install-LocalPython313
    - **(PR #124) MS Store stub / python --version 실패 → Install-LocalPython313**
    - **(PR #124) 정규식 매치 실패 (비표준 출력) → Install-LocalPython313**
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    # Test-Prereqs 함수 본문 추출
    prereqs = _re.search(r"function Test-Prereqs\s*\{(.*?)\n\}\n", text, _re.DOTALL)
    assert prereqs is not None, "Test-Prereqs 본문 추출 실패"
    body = prereqs.group(1)
    # PR #123 (3.14+/<3.10) + PR #124 (Store stub + 매치 실패) = 최소 4 호출
    local_calls = body.count("Install-LocalPython313")
    assert local_calls >= 4, (
        f"Install-LocalPython313 호출 횟수 부족 ({local_calls} 회) — "
        "PR #123 2 시나리오 + PR #124 2 시나리오 (Store stub / 매치 실패) 모두 호출 필요"
    )
    winget_calls = body.count("Install-Python313ViaWinget")
    assert winget_calls >= 1, (
        f"Install-Python313ViaWinget 호출 누락 ({winget_calls} 회) — "
        "python 미설치 시나리오에서 winget 호출 필요"
    )


def test_install_ps1_detects_microsoft_store_python_stub() -> None:
    """Test-Prereqs 가 Microsoft Store Python stub alias 검출 (PR #124).

    배경 (사용자 보고):
        Windows 10+ 의 ``python`` PATH stub 은 ``ms-windows-store://`` 페이지 열기 →
        ``python --version`` 호출 시 빈 출력 / "Microsoft Store" 메시지 / "Reparse" 등.
        이전 (PR #110~#123) 은 정규식 매치 실패 시 단순 ``Write-Warn2`` → 설치 함수
        미호출 → Step 2/6 부터 venv 생성 실패. 사용자 화면에서 "매치 안 됨" 만 보임.

    PR #124 처방:
        ``python --version`` 출력에 ``Microsoft Store`` / ``Reparse`` / ``App Installer``
        키워드 검출 OR ``$LASTEXITCODE`` 비-0 OR 빈 출력 → Store stub 으로 간주 →
        ``Install-LocalPython313`` 호출 (로컬 격리 설치).

    회귀 차단 — 본 테스트가 깨지면 Store stub 환경 사용자가 "Step 1/6 매치 안 됨"
    으로 막힘.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # Store stub 검출 키워드 (검출 분기 식별자)
    assert "Microsoft Store" in text or "Reparse" in text, (
        "Microsoft Store stub 검출 키워드 누락"
    )
    # $LASTEXITCODE 검사 — python --version 자체 실행 실패 케이스
    assert "$pyVersionExit" in text or "LASTEXITCODE" in text, (
        "python --version 실행 실패 검사 누락"
    )
    # IsNullOrWhiteSpace 또는 동등 빈 출력 검사
    assert "IsNullOrWhiteSpace" in text or "isStoreStub" in text, (
        "빈 출력 검사 누락 — Store stub 의 빈 stdout 시나리오 미커버"
    )
    # 검출 시 Install-LocalPython313 호출
    import re as _re
    store_detect = _re.search(
        r"isStoreStub.*?Install-LocalPython313", text, _re.DOTALL
    )
    assert store_detect is not None, (
        "Store stub 검출 후 Install-LocalPython313 호출 누락 — "
        "사용자가 'Step 1/6 매치 안 됨' 으로 막힘"
    )


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
    # try/catch + Install-LocalPython313 fallback (PR #123 — winget 실패 시 로컬 격리)
    assert "try {" in body or "try{" in body, "winget 호출에 try 블록 누락"
    assert "} catch {" in body or "}catch{" in body, "winget 호출에 catch 블록 누락"
    # PR #123 — winget 실패 시 graceful fallback: Install-LocalPython313 호출
    # (수동 설치 URL 안내는 Install-LocalPython313 의 fail 메시지로 이동)
    assert "Install-LocalPython313" in body, (
        "winget 실패 시 Install-LocalPython313 graceful fallback 누락"
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


# ---------------------------------------------------------------------------
# PR #125 — Invoke-NativeSafely + py install 3.13 happy path (Native ErrCmd fix)
# ---------------------------------------------------------------------------


def test_install_ps1_has_invoke_native_safely_helper() -> None:
    """install.ps1 이 ``Invoke-NativeSafely`` helper 정의 (PR #125).

    배경 (사용자 보고):
        ``& py -3.13 --version 2>&1 | Out-String`` 패턴이 ``$ErrorActionPreference = 'Stop'``
        하에서 py launcher 의 stderr 에러 메시지 ("No runtime installed that matches 3.13.
        Try running 'py install 3.13'.") 를 NativeCommandError 로 wrap → script abort →
        ``Install-LocalPython313`` fallback 미호출 → 사용자 화면에 "X 설치 실패: [ERROR]
        No runtime installed..." 만 보임.

    PR #125 처방:
        ``Invoke-NativeSafely`` 신설 — ``2>$null`` 로 stderr 를 *file handle level* 에서
        discard → PowerShell pipeline 미경유 → NativeCommandError 미발생. 모든 native
        query (``--version``) 가 본 helper 사용.

    회귀 차단 — 본 테스트가 깨지면 py launcher 의 stderr 가 다시 script 를 abort.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # helper 함수 정의
    assert "function Invoke-NativeSafely" in text, "Invoke-NativeSafely helper 정의 누락"
    # stderr discard (2>$null) — NativeCommandError 회피 핵심
    assert "2>$null" in text, "stderr discard (2>\\$null) 패턴 누락"
    # 결과 객체 형식 (StdOut / ExitCode / Succeeded)
    assert "Succeeded" in text and "ExitCode" in text, (
        "Invoke-NativeSafely 결과 객체 (Succeeded / ExitCode) 누락"
    )


def test_install_ps1_py_install_3_13_removed() -> None:
    """install.ps1 의 py launcher 분기에서 ``py install 3.13`` 명령 제거 (PR #126).

    배경 (PR #126 결정):
        PR #125 가 ``py install 3.13`` 을 happy path 2 단계로 도입했으나, 라이브
        PowerShell 시뮬레이션 중 *hang* 발생 — py launcher 가 일부 환경에서
        Microsoft Store 인증 / Windows Hello prompt / 네트워크 throttle 등으로
        진행 불가. ``irm | iex`` 시나리오에서 사용자 창이 멈춤 → UX 최악.

    PR #126 처방:
        ``py install 3.13`` 단계 *완전 제거* — fallback chain 단순화:
        ① ``py -3.13 --version`` 검출 (3.13 이미 설치 시 happy path)
        ② 실패 시 ``Install-LocalPython313`` (deterministic, 시스템 미터치)

        deterministic = 외부 변수 (py 의 store 상태, network) 의존 0. generic.

    회귀 차단 — 본 테스트가 깨지면 ``py install`` 단계 부활 → hang risk 재발.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    # 주석 제외 (PR #126 의 결정 사유 설명은 주석 안에 OK)
    lines = text.splitlines()
    code_lines = [l for l in lines if not _re.match(r"^\s*#", l)]
    code_text = "\n".join(code_lines)
    # 실 명령으로 'py install 3.13' 또는 array 인자 형식이 호출되면 안 됨
    assert "'install', '3.13'" not in code_text, (
        "실 코드에 py install 3.13 인자 array 잔존 — PR #126 결정 (hang risk) 미반영"
    )
    # 또한 ``py install 3.13`` literal 도 호출 안 함
    # (주석 안에는 OK — code_text 에서만 검사)
    # ``& py install 3.13`` / ``py install 3.13`` 직접 호출 패턴
    invoke_pattern = _re.search(r"(?:&\s*)?py\s+install\s+3\.13", code_text)
    assert invoke_pattern is None, (
        "실 코드에 ``py install 3.13`` 직접 호출 잔존 — PR #126 hang risk 결정 미반영"
    )


def test_install_ps1_py_branch_is_two_step_only() -> None:
    """3.14+ 의 py launcher 분기가 2-단 (detect 또는 LocalPython313) 만 사용 (PR #126).

    PR #125 의 3-단 chain (detect → py install → LocalPython313) 에서 중간 단계
    제거 → 분기 단순화 + 외부 변수 의존 제거.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    # ``minor -ge 14`` 분기 본문 추출 — 다음 ``} else {`` 또는 ``}`` 까지
    branch_match = _re.search(
        r"elseif\s*\(.*?minor\s+-ge\s+14.*?\)\s*\{(.*?)\n\s{8}\}",
        text, _re.DOTALL
    )
    assert branch_match is not None, (
        "3.14+ elseif 분기 본문 추출 실패 — 분기 구조 변경 가능성"
    )
    body = branch_match.group(1)
    # 주석 줄 제외 (코멘트 안의 "Install-LocalPython313" 멘션은 카운트 안 함)
    body_lines = body.splitlines()
    code_lines = [l for l in body_lines if not _re.match(r"^\s*#", l)]
    code_body = "\n".join(code_lines)
    # 본문에 정확히 1 회의 ``Install-LocalPython313`` (실 호출)
    assert code_body.count("Install-LocalPython313") == 1, (
        f"3.14+ 분기에 Install-LocalPython313 호출 정확히 1회여야 함 "
        f"(현재: {code_body.count('Install-LocalPython313')})"
    )
    # py install 3.13 패턴 부재 (코드 영역)
    assert "'install', '3.13'" not in code_body, (
        "3.14+ 분기에 py install 3.13 인자 array 잔존 — PR #126 미반영"
    )


def test_install_ps1_no_native_2andredirect_outstring_pattern() -> None:
    """install.ps1 이 ``2>&1 | Out-String`` 패턴 사용 안 함 (PR #125 + #126 회귀 차단).

    배경:
        ``2>&1`` 은 ``$ErrorActionPreference = 'Stop'`` 하에서 NativeCommandError
        트리거 — Helper / EAP 격리 / stderr file redirect 으로 대체.
        주석 (``# 배경: ...``) 에서 패턴 설명은 OK — 실 호출 안 함.

    PR #126 확장:
        ``2>&1 | Out-String`` 뿐 아니라 ``2>&1`` 단독 사용도 실 코드에서 부재해야 함.
        대안: ``2>$null`` (discard) 또는 ``2>$tempFile`` (file redirect).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    # 주석 줄 제거 후 실 코드만 검사
    lines = text.splitlines()
    code_lines = [
        l for l in lines
        if not _re.match(r"^\s*#", l)  # # 로 시작하는 주석 줄 제외
    ]
    code_text = "\n".join(code_lines)
    assert "2>&1 | Out-String" not in code_text, (
        "실 코드에 '2>&1 | Out-String' 잔존 — Invoke-NativeSafely / EAP 격리 / file redirect 로 교체 필요"
    )
    # PR #126 — ``2>&1`` 단독 사용도 부재 (NativeCommandError 회피 100% 보장)
    # ``2>&1`` 패턴 (앞뒤 글자 무관) 검색
    bare_2andredirect = _re.search(r"2>&1", code_text)
    assert bare_2andredirect is None, (
        f"실 코드에 '2>&1' (단독) 잔존 — PR #126: NativeCommandError 100% 회피 위해 "
        f"'2>$null' 또는 '2>$file' 사용 필요 (잔존 위치: {bare_2andredirect.group(0) if bare_2andredirect else 'unknown'})"
    )


# ---------------------------------------------------------------------------
# PR #126 — 종합 시나리오 검증 (모든 native command 경로 NativeCommandError 회피)
# ---------------------------------------------------------------------------


def test_install_ps1_invoke_native_safely_has_eap_isolation() -> None:
    """``Invoke-NativeSafely`` 함수 내부에서 EAP 격리 — 외부 ``Stop`` 영향 0 (PR #126).

    배경 (사용자 다른 PC 보고):
        ``2>$null`` + try/catch 만으로는 일부 환경에서 NativeCommandError 회피 불충분.
        외부 ``$ErrorActionPreference = 'Stop'`` 가 *함수 내부에도 전파* — native command
        의 stderr / non-zero exit 가 throw → catch 진입 → 결과 빈 객체 + 분기 오작동.

    PR #126 처방:
        함수 진입 시 ``$savedEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'``
        + finally 에서 복원. 외부 EAP 와 *완전 분리* → native command stderr 가 100%
        조용히 처리됨.

    회귀 차단 — 본 테스트가 깨지면 다른 PC 에서 동일 NativeCommandError 재발.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    func_match = _re.search(
        r"function Invoke-NativeSafely\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert func_match is not None, "Invoke-NativeSafely 함수 본문 추출 실패"
    body = func_match.group(1)
    # EAP 저장 + Continue 로 설정 + finally 복원 — 3 키워드 모두 필수
    assert "$savedEAP" in body or "savedEAP" in body, (
        "Invoke-NativeSafely 가 외부 EAP 저장 안 함 — finally 복원 불가"
    )
    assert "$ErrorActionPreference = 'Continue'" in body, (
        "Invoke-NativeSafely 함수 본문에 EAP='Continue' 명시 누락 — "
        "외부 'Stop' 영향 받아 throw 가능"
    )
    assert "finally" in body, (
        "Invoke-NativeSafely 에 finally 블록 누락 — 예외 발생 시 EAP 복원 실패"
    )
    # EAP 복원 패턴 — finally 안에서 saved 값으로 되돌림
    restore_pattern = _re.search(
        r"finally\s*\{[^}]*\$ErrorActionPreference\s*=\s*\$savedEAP",
        body, _re.DOTALL
    )
    assert restore_pattern is not None, (
        "finally 블록에서 EAP 복원 (=$savedEAP) 누락 — 함수 종료 후 EAP 영구 변경 위험"
    )


def test_install_ps1_test_prereqs_has_eap_isolation() -> None:
    """``Test-Prereqs`` 함수 전체에 EAP 격리 wrapper (PR #126).

    배경:
        ``Invoke-NativeSafely`` 내부 격리만으로는 *직접 호출되는* native command
        (``& git --version``, ``gh --version`` 등) 의 NativeCommandError 회피 불가.
        Test-Prereqs 전체를 EAP=Continue 안에서 실행 → defense-in-depth.

    PR #126 처방:
        Test-Prereqs 본문 시작에서 ``$savedEAPPrereqs = $ErrorActionPreference;
        $ErrorActionPreference = 'Continue'`` + 함수 끝 finally 에서 복원.

    회귀 차단 — Test-Prereqs 내 native command 의 stderr 가 외부 catch 진입 → Fail
    호출 → 사용자 창 자동 닫힘 가능.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    func_match = _re.search(
        r"function Test-Prereqs\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert func_match is not None, "Test-Prereqs 함수 본문 추출 실패"
    body = func_match.group(1)
    assert "$savedEAPPrereqs" in body or "savedEAPPrereqs" in body, (
        "Test-Prereqs 가 외부 EAP 저장 안 함 — finally 복원 불가"
    )
    assert "$ErrorActionPreference = 'Continue'" in body, (
        "Test-Prereqs 본문에 EAP='Continue' 격리 누락"
    )
    # finally 블록 존재 — 정상 종료 / Fail / 예외 모두 cover
    assert "finally" in body, (
        "Test-Prereqs 에 finally 블록 누락 — EAP 복원 실패 시 외부 영구 영향"
    )
    # 복원 패턴
    restore_pattern = _re.search(
        r"finally\s*\{[^}]*\$ErrorActionPreference\s*=\s*\$savedEAPPrereqs",
        body, _re.DOTALL
    )
    assert restore_pattern is not None, (
        "Test-Prereqs finally 블록의 EAP 복원 누락 — 함수 종료 후 외부 EAP 변경 위험"
    )


def test_install_ps1_smoke_test_uses_safe_pattern() -> None:
    """smoke test 의 venv python 호출도 NativeCommandError 안전 패턴 사용 (PR #126).

    배경:
        Step 5/6 의 smoke test (``$smoke | & $venvPython - 2>&1``) 도 외부 catch
        에서 abort 가능 — 사용자가 import 에러를 못 보고 ``Fail`` 즉시 호출됨.

    PR #126 처방:
        ① EAP 격리 (Continue) + ② stderr 를 *file* 로 redirect (``2>$stderrFile``)
        → pipeline 미경유 → NativeCommandError 미발생. 출력 분리 capture.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    func_match = _re.search(
        r"function Test-Install\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert func_match is not None, "Test-Install 함수 본문 추출 실패"
    body = func_match.group(1)
    # 주석 줄 제외 — 코멘트 안의 패턴 멘션은 카운트 안 함
    body_lines = body.splitlines()
    code_lines = [l for l in body_lines if not _re.match(r"^\s*#", l)]
    code_body = "\n".join(code_lines)
    # EAP 격리
    assert "$savedEAPSmoke" in body or "savedEAPSmoke" in body, (
        "Test-Install (smoke test) 에 EAP 격리 누락"
    )
    assert "$ErrorActionPreference = 'Continue'" in code_body, (
        "Test-Install 본문에 EAP='Continue' 격리 누락"
    )
    # stderr file redirect 패턴
    assert "2>$stderrFile" in code_body or "2>$stderr" in code_body, (
        "Test-Install 에 stderr file redirect 누락 — '2>&1' 미회피"
    )
    # 2>&1 단독 사용 부재 (코드 영역에서)
    assert "2>&1" not in code_body, (
        "Test-Install 본문 코드에 '2>&1' 잔존 — PR #126 stderr file redirect 미적용"
    )


def test_install_ps1_all_native_calls_use_safe_helper_or_redirect() -> None:
    """모든 native command 호출이 안전 패턴 (helper / file redirect / EAP 격리) 사용 (PR #126).

    배경:
        사용자 보고: "수정 후 다른 pc에서 실행했는데 이렇게 나온다. 이문제는 왜 해결을
        안해주는거야? 모든 경우의 수를 생각해서 테스트 검증이필요할듯하다"

    PR #126 처방 (종합 회귀 차단):
        - ``& python --version`` / ``& py -3.13 --version`` / ``& $existingVenvPython
          --version`` 등 모든 ``--version`` query 는 ``Invoke-NativeSafely`` 사용
        - ``& git clone`` / ``& git fetch`` / ``& git reset`` 등은 ``| Out-Null`` 사용
          (Out-Null 은 NativeCommandError 미트리거)
        - ``Test-Prereqs`` 본문 전체 EAP=Continue 격리 (defense-in-depth)
        - smoke test 는 stderr file redirect + EAP 격리
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # version query 가 직접 호출 (helper 미경유) 형태로 잔존하면 안 됨.
    # 패턴: ``& <executable> --version`` 가 ``Invoke-NativeSafely`` 호출 직전이 아닌
    # 또는 ``| Out-Null`` 없이 단독 사용된 경우 위험.
    import re as _re
    lines = text.splitlines()
    code_lines = [l for l in lines if not _re.match(r"^\s*#", l)]
    code_text = "\n".join(code_lines)
    # 직접 ``& python --version`` 호출이 helper 미경유로 잔존 안 함
    direct_python_version = _re.search(
        r"&\s+python\s+--version", code_text
    )
    assert direct_python_version is None, (
        "실 코드에 '& python --version' 직접 호출 잔존 — Invoke-NativeSafely 필요"
    )
    # ``& py -3.13 --version`` 직접 호출도 부재 (Invoke-NativeSafely 경유)
    direct_py_version = _re.search(
        r"&\s+py\s+-3\.13\s+--version", code_text
    )
    assert direct_py_version is None, (
        "실 코드에 '& py -3.13 --version' 직접 호출 잔존 — Invoke-NativeSafely 필요"
    )
    # ``& $existingVenvPython --version`` 도 부재 (Invoke-NativeSafely 경유)
    direct_venv_version = _re.search(
        r"&\s+\$existingVenvPython\s+--version", code_text
    )
    assert direct_venv_version is None, (
        "실 코드에 '& $existingVenvPython --version' 직접 호출 잔존 — Invoke-NativeSafely 필요"
    )
    # ``& $pyExe --version`` 도 부재 (Install-LocalPython313 내부도 helper 경유)
    direct_pyexe_version = _re.search(
        r"&\s+\$pyExe\s+--version", code_text
    )
    assert direct_pyexe_version is None, (
        "실 코드에 '& $pyExe --version' 직접 호출 잔존 — Invoke-NativeSafely 필요"
    )


def test_install_ps1_native_safely_helper_called_multiple_times() -> None:
    """Invoke-NativeSafely 가 모든 native query 시나리오에서 호출됨 (PR #126).

    PR #126 호출 시나리오 (최소):
        1. Test-Prereqs: git --version
        2. Test-Prereqs: 기존 .venv python --version
        3. Test-Prereqs: 시스템 python --version
        4. Test-Prereqs: py -3.13 --version (3.14+ 분기)
        5. Install-Python313ViaWinget: py -3.13 --version (winget 후 검증)
        6. Install-LocalPython313: $pyExe --version (idempotent 재사용 확인)
        7. Install-LocalPython313: $pyExe --version (설치 후 검증)

    최소 7회 호출 (defensive coverage).
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    # 정의 1회 + 호출 N회 = 총 (N+1) 발생
    occurrences = text.count("Invoke-NativeSafely")
    assert occurrences >= 8, (
        f"Invoke-NativeSafely 발생 횟수 부족 ({occurrences} 회) — "
        "최소 1 정의 + 7 호출 (PR #126 종합 시나리오) 필요"
    )


def test_install_ps1_powershell_parses_cleanly() -> None:
    """install.ps1 이 PowerShell parser 로 정상 토큰화 (PR #126 syntax 회귀 차단).

    배경:
        PR #121 의 BOM 추가 / 향후 인코딩 변경 등으로 token error 발생 시 ``irm | iex``
        시나리오에서 사용자 창이 즉시 닫힘 (no actionable error).

    PR #126 검증:
        ``[System.Management.Automation.PSParser]::Tokenize`` 가 parse 에러 0 으로
        완료. 토큰 수도 합리적 범위 (최소 1000) — 빈 파일 / 손상 파일 조기 발견.
    """
    import subprocess

    # PowerShell parse 검증 — Windows only (CI on Windows runner)
    if sys.platform != "win32":
        pytest.skip("PowerShell parse 검증은 Windows 한정")

    # PowerShell 5.1 의 Get-Content -Raw 는 system codepage 사용 → 한국어 Windows 에서
    # UTF-8 파일을 CP949 로 읽으면 garbled 토큰화 됨. 명시적 UTF-8 ReadAllText 사용.
    script = (
        f'$ErrorActionPreference = "Stop"; '
        f'$text = [System.IO.File]::ReadAllText("{INSTALL_PS1_PATH}", [System.Text.Encoding]::UTF8); '
        f'$errors = $null; '
        f'$tokens = [System.Management.Automation.PSParser]::Tokenize($text, [ref]$errors); '
        f'if ($errors -and $errors.Count -gt 0) {{ '
        f'  Write-Host ("PARSE_ERRORS: " + $errors.Count); '
        f'  $errors | ForEach-Object {{ Write-Host $_.Message }}; '
        f'  exit 1 '
        f'}}; '
        f'Write-Host ("TOKENS: " + $tokens.Count)'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"PowerShell parse 실패 (exit={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "TOKENS:" in result.stdout, (
        f"PowerShell parse 결과에 TOKENS 키워드 누락: {result.stdout}"
    )
    # 토큰 수 합리성 (빈 파일 회귀 차단)
    import re
    token_match = re.search(r"TOKENS:\s*(\d+)", result.stdout)
    assert token_match is not None, f"TOKENS 라인 파싱 실패: {result.stdout}"
    token_count = int(token_match.group(1))
    assert token_count >= 1000, (
        f"PowerShell 토큰 수 비정상 ({token_count}) — 파일 손상 / 비정상 단축 가능"
    )


# ---------------------------------------------------------------------------
# PR #128 — Install-LocalPython313 인스톨러 실패 fix
# ---------------------------------------------------------------------------


def test_install_ps1_installs_python_creates_parent_dir() -> None:
    """Install-LocalPython313 이 인스톨러 호출 전에 $INSTALL_DIR 사전 생성 (PR #128).

    사용자 보고 (PR #126 머지 후):
        flow 가 ``Install-LocalPython313`` 까지 정상 도달했지만 인스톨러 종료 후
        ``python.exe 미생성 — 인스톨러 동작 이상`` 으로 실패. 원인 추정:
        Install-LocalPython313 은 Step 1/6 (Get-Repo 이전) 에서 호출 → $INSTALL_DIR
        가 아직 미존재. Python 공식 인스톨러는 TargetDir 의 *부모 폴더 자동 생성*
        을 보장하지 않음 → silent fail.

    PR #128 처방:
        ``Test-Path $INSTALL_DIR`` 확인 후 미존재 시 ``New-Item -ItemType Directory``
        로 사전 생성. 부모 폴더 보장 후 인스톨러 호출.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None, "Install-LocalPython313 함수 추출 실패"
    body = local_func.group(1)
    # 부모 폴더 사전 생성 패턴 검출
    parent_create = _re.search(
        r"if\s*\(\s*-not\s*\(\s*Test-Path\s+\$INSTALL_DIR\s*\)\s*\)\s*\{[^}]*New-Item\s+-ItemType\s+Directory",
        body, _re.DOTALL
    )
    assert parent_create is not None, (
        "Install-LocalPython313 에 $INSTALL_DIR 사전 생성 로직 누락 — "
        "PR #128: Python 인스톨러 silent fail 회피 미적용"
    )
    # New-Item 위치가 인스톨러 실행 (Start-Process) 보다 앞에 있어야 함
    create_pos = body.find("New-Item -ItemType Directory")
    start_proc_pos = body.find("Start-Process -FilePath")
    assert 0 < create_pos < start_proc_pos, (
        f"New-Item 이 Start-Process 보다 앞에 위치해야 함 "
        f"(create={create_pos}, start_proc={start_proc_pos})"
    )


def test_install_ps1_removes_simple_install_flag() -> None:
    """Install-LocalPython313 의 ``SimpleInstall=1`` 인자 제거 (PR #128).

    배경:
        Python 공식 인스톨러 옵션 ``SimpleInstall=1`` 은 ``/quiet`` 와 *중복* +
        일부 환경에서 사용자 정의 옵션 (TargetDir, InstallAllUsers 등) 을 무시
        하고 기본 위치로 설치하는 보고 존재.

    PR #128 처방:
        ``SimpleInstall=1`` 인자 제거. ``/quiet`` 로 UI 비표시는 충분.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None, "Install-LocalPython313 함수 추출 실패"
    body = local_func.group(1)
    # 주석 제외한 실 코드만 검사
    body_lines = body.splitlines()
    code_lines = [l for l in body_lines if not _re.match(r"^\s*#", l)]
    code_body = "\n".join(code_lines)
    # SimpleInstall=1 인자 부재 (string literal)
    assert "'SimpleInstall=1'" not in code_body, (
        "Install-LocalPython313 의 $installArgs 에 'SimpleInstall=1' 잔존 — "
        "PR #128: TargetDir 무시 보고로 제거 필요"
    )
    assert '"SimpleInstall=1"' not in code_body, (
        "Install-LocalPython313 의 $installArgs 에 \"SimpleInstall=1\" 잔존"
    )


def test_install_ps1_uses_default_just_for_me_target_dir() -> None:
    """Install-LocalPython313 이 ``DefaultJustForMeTargetDir`` 도 설정 (PR #128).

    배경:
        Python 인스톨러는 ``InstallAllUsers=0`` 시 ``TargetDir`` 대신
        ``DefaultJustForMeTargetDir`` 를 우선 사용하는 환경 존재. 두 옵션 모두
        지정해 어느 쪽이 사용돼도 동일 경로 보장.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None, "Install-LocalPython313 함수 추출 실패"
    body = local_func.group(1)
    assert "DefaultJustForMeTargetDir=" in body, (
        "Install-LocalPython313 의 $installArgs 에 'DefaultJustForMeTargetDir=' 누락 — "
        "PR #128: TargetDir 무시 환경 대응 미적용"
    )
    # TargetDir 도 여전히 존재 (제거되지 않음)
    assert "TargetDir=" in body, "TargetDir 옵션 누락"


def test_install_ps1_captures_installer_log() -> None:
    """Install-LocalPython313 이 Python 인스톨러 로그를 capture (PR #128).

    인스톨러 silent fail 진단을 위해 ``/log <file>`` 인자 추가 — 사용자가 실패
    재현 시 로그 파일로 root cause 식별 가능.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None
    body = local_func.group(1)
    # /log 인자 + 로그 파일 변수
    assert "'/log'" in body or '"/log"' in body, (
        "/log 인자 누락 — Python 인스톨러 진단 로그 미캡처"
    )
    assert "$installLog" in body, (
        "$installLog 변수 누락 — 로그 경로 미설정"
    )


# ---------------------------------------------------------------------------
# PR #128 — Orphan MSI registry detection + uninstall (Burn bundle Modify=None fix)
# ---------------------------------------------------------------------------


def test_install_ps1_has_get_existing_python313_helper() -> None:
    """install.ps1 이 registry 기반 Python 3.13 검출 helper 정의 (PR #128).

    배경 (사용자 PC 인스톨러 로그 분석):
        Python 공식 인스톨러 (Burn bundle) 가 ``Modify`` action + ``execute: None``
        으로 silent 종료 (exit=0) 하지만 실제 파일 미생성. 원인: 이전 시도에서
        부분 설치된 MSI registry 가 남아 있어 인스톨러가 "이미 설치됨" 으로 판단.

    PR #128 처방:
        ``Get-ExistingPython313`` helper 가 registry (HKCU/HKLM/Wow6432Node) 를
        검사 → ``Found / Path / Orphan / RegistryKey`` 객체 반환:
          - Found=True : 실 파일 존재 → 재사용
          - Orphan=True: registry 만 존재 (파일 없음) → install 전 uninstall 필요

    회귀 차단 — helper 누락 시 silent fail 회피 로직 미작동.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    assert "function Get-ExistingPython313" in text, (
        "Get-ExistingPython313 helper 정의 누락"
    )
    # 핵심 registry key 3종 (HKCU + HKLM + Wow6432Node) 모두 검사
    assert "HKCU:\\Software\\Python\\PythonCore\\3.13\\InstallPath" in text, (
        "HKCU registry key 검사 누락"
    )
    assert "HKLM:\\Software\\Python\\PythonCore\\3.13\\InstallPath" in text, (
        "HKLM registry key 검사 누락"
    )
    assert "Wow6432Node" in text, (
        "32-bit Python on 64-bit OS (Wow6432Node) registry 검사 누락"
    )
    # 반환 객체 필드
    assert "Found=" in text, "Get-ExistingPython313 결과 객체 Found 필드 누락"
    assert "Orphan=" in text, "Get-ExistingPython313 결과 객체 Orphan 필드 누락"


def test_install_ps1_reuses_existing_python_via_registry() -> None:
    """Install-LocalPython313 이 registry 검출 시 fresh install 스킵 + 재사용 (PR #128).

    회귀 차단: 사용자가 이미 Python 3.13 을 설치한 상태에서 install.ps1 재실행 시
    불필요한 인스톨러 호출 회피 + (특히) 인스톨러 silent fail 위험 회피.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None
    body = local_func.group(1)
    # registry helper 호출
    assert "Get-ExistingPython313" in body, (
        "Install-LocalPython313 에서 Get-ExistingPython313 호출 누락 — fresh install 스킵 로직 미연결"
    )
    # Found=True 분기 — 재사용 후 return
    found_branch = _re.search(
        r"if\s*\(\s*\$reg\.Found\s*\)\s*\{(.*?)return", body, _re.DOTALL
    )
    assert found_branch is not None, (
        "Get-ExistingPython313 Found=True 시 즉시 return 분기 누락"
    )
    found_body = found_branch.group(1)
    assert "$script:PYTHON_VENV_EXE" in found_body, (
        "Found=True 분기에서 $script:PYTHON_VENV_EXE 설정 누락"
    )


def test_install_ps1_uninstalls_orphan_msi_before_install() -> None:
    """Install-LocalPython313 이 orphan MSI 잔존 시 uninstall 후 fresh install (PR #128).

    핵심: Python BURN bundle 이 "Already installed" 으로 판단하면 install 을 ``Modify``
    action 으로 변환 → ``execute: None`` 으로 실제 설치 안 함 → exit=0 silent fail.
    uninstall 로 MSI 잔존 정리 후 install 호출 → fresh install 강제.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None
    body = local_func.group(1)
    # orphan registry 감지 변수
    assert "$orphanedRegistry" in body or "orphanedRegistry" in body, (
        "orphanedRegistry 플래그 누락"
    )
    # /uninstall 인자 사용
    assert "'/uninstall'" in body or '"/uninstall"' in body, (
        "/uninstall 인자 누락 — orphan MSI 정리 미시도"
    )
    # uninstall 이 install 보다 앞에 위치
    uninstall_pos = body.find("'/uninstall'")
    install_pos = body.find('$installArgs = @(')
    assert 0 < uninstall_pos < install_pos, (
        f"/uninstall 이 install 보다 앞에 있어야 함 "
        f"(uninstall={uninstall_pos}, install={install_pos})"
    )


def test_install_ps1_test_prereqs_registry_fallback_for_python_314_plus() -> None:
    """Test-Prereqs 의 3.14+ 분기가 py -3.13 실패 시 registry 도 시도 (PR #128).

    배경:
        사용자 PC: 시스템 python 3.14.2 + py launcher 없음 → ``py -3.13`` 검출 실패
        + Install-LocalPython313 에서도 orphan registry 로 silent fail.

    PR #128 추가 안전망:
        ``py -3.13`` 실패 시 ``Install-LocalPython313`` 호출 전에 registry 검사 →
        이미 설치된 Python 3.13 발견 시 즉시 재사용. 인스톨러 silent fail 사이클 회피.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    prereqs = _re.search(
        r"function Test-Prereqs\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert prereqs is not None
    body = prereqs.group(1)
    # 3.14+ 분기 추출 (minor -ge 14)
    branch_match = _re.search(
        r"elseif\s*\(.*?minor\s+-ge\s+14.*?\)\s*\{(.*?)\n\s{8}\}",
        body, _re.DOTALL
    )
    assert branch_match is not None
    branch_body = branch_match.group(1)
    # Get-ExistingPython313 호출이 분기 안에 존재
    assert "Get-ExistingPython313" in branch_body, (
        "3.14+ 분기에 Get-ExistingPython313 fallback 호출 누락 — "
        "py -3.13 실패 시 registry 검사 시도 안 됨"
    )


def test_install_ps1_checks_fallback_python_location() -> None:
    """Install-LocalPython313 이 TargetDir 미생성 시 기본 user 위치도 검사 (PR #128).

    배경:
        일부 환경에서 Python 인스톨러가 TargetDir 를 무시하고 기본 user 위치
        (``%LocalAppData%\\Programs\\Python\\Python313\\``) 에 설치하는 경우 발견.
        ``Test-Path $pyExe`` 만 검사하면 false negative.

    PR #128 처방:
        TargetDir 위치 미존재 시 ``$env:LocalAppData\\Programs\\Python\\Python313\\python.exe``
        도 검사 → 발견 시 $pyExe / $pyDir 를 해당 경로로 갱신 후 진행.
    """
    text = INSTALL_PS1_PATH.read_text(encoding="utf-8")
    import re as _re
    local_func = _re.search(
        r"function Install-LocalPython313\s*\{(.*?)\n\}\n", text, _re.DOTALL
    )
    assert local_func is not None
    body = local_func.group(1)
    # LocalAppData 기본 위치 검사 키워드
    assert "$env:LocalAppData" in body or "LocalAppData" in body, (
        "Install-LocalPython313 에 기본 user 위치 ($env:LocalAppData) fallback 검사 누락"
    )
    assert "Programs\\Python\\Python313" in body or "Programs/Python/Python313" in body, (
        "기본 user Python 경로 (Programs\\Python\\Python313) 미참조 — PR #128 fallback 미적용"
    )
    # python.exe 미발견 시 변수 갱신 + 진행
    fallback_branch = _re.search(
        r"if\s*\(\s*-not\s*\(\s*Test-Path\s+\$pyExe\s*\)\s*\).*?LocalAppData",
        body, _re.DOTALL
    )
    assert fallback_branch is not None, (
        "TargetDir 미생성 → LocalAppData fallback 분기 누락"
    )
