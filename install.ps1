<#
.SYNOPSIS
    Nexus Alpha Alpha installer — irm 한 줄 설치 (Windows PowerShell 5.1+).

.DESCRIPTION
    자연어 → .exe + Draft Release URL 풀체인을 로컬에서 즉시 실행 가능하도록
    Python 3.13 가상환경 + 의존성 + Nexus Alpha 코드베이스를 설치합니다.

    *Alpha 단계* — 내부 / 얼리 어답터 대상. Beta (Streamlit) / Release
    (Electron/Tauri) 는 후속 단계.

.EXAMPLE
    # irm 한 줄 설치 (main 브랜치)
    irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex

.EXAMPLE
    # 로컬 실행 (이미 clone 받은 경우)
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.NOTES
    환경 변수로 동작 조정 가능:
      $env:NEXUS_ALPHA_DIR    — 설치 경로 (기본: $HOME\nexus-alpha)
      $env:NEXUS_ALPHA_REPO   — git 저장소 (기본: SongJongwon/nexus-alpha)
      $env:NEXUS_ALPHA_BRANCH — 브랜치 (기본: main)
      $env:NEXUS_ALPHA_SKIP_SMOKE — '1' 이면 smoke test 생략
#>

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# ─── 기본 설정 ──────────────────────────────────────────────────────────────
$REPO       = if ($env:NEXUS_ALPHA_REPO)   { $env:NEXUS_ALPHA_REPO }   else { 'SongJongwon/nexus-alpha' }
$BRANCH     = if ($env:NEXUS_ALPHA_BRANCH) { $env:NEXUS_ALPHA_BRANCH } else { 'main' }
$INSTALL_DIR = if ($env:NEXUS_ALPHA_DIR)    { $env:NEXUS_ALPHA_DIR }    else { Join-Path $HOME 'nexus-alpha' }
$PYTHON_MIN = '3.13'

function Write-Banner {
    Write-Host ''
    Write-Host '╔══════════════════════════════════════════════════════════════╗' -ForegroundColor Cyan
    Write-Host '║  Nexus Alpha — Alpha installer                              ║' -ForegroundColor Cyan
    Write-Host '║  자연어 한 마디 → .exe + Draft Release URL 풀체인             ║' -ForegroundColor Cyan
    Write-Host '╚══════════════════════════════════════════════════════════════╝' -ForegroundColor Cyan
    Write-Host ''
    Write-Host "  Repo    : $REPO ($BRANCH)" -ForegroundColor DarkGray
    Write-Host "  Install : $INSTALL_DIR"        -ForegroundColor DarkGray
    Write-Host ''
}

function Write-Step {
    param([string]$Message)
    Write-Host "▶ $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Warn2 {
    param([string]$Message)
    Write-Host "  ! $Message" -ForegroundColor DarkYellow
}

function Fail {
    param([string]$Message)
    Write-Host ''
    Write-Host "✗ 설치 실패: $Message" -ForegroundColor Red
    Write-Host ''
    # PR #120 — PowerShell 창 자동 닫힘 방지 (irm | iex 시나리오).
    # NEXUS_ALPHA_NO_PAUSE=1 (CI 등 비인터랙티브) 시 즉시 종료.
    if (-not $env:NEXUS_ALPHA_NO_PAUSE) {
        Write-Host '계속하려면 아무 키나 누르세요 (창이 자동 닫히는 것을 방지합니다)...' -ForegroundColor DarkGray
        try { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') } catch { }
    }
    exit 1
}

# ─── PR #117/#120 — Python 3.13 자동 설치 via winget (시스템 미설치 시) ──
# 사용 시점 (PR #123 갱신): *Python 이 시스템에 전혀 없을 때만*. 기존 Python
# 버전이 있는 경우는 ``Install-LocalPython313`` (로컬 격리) 사용 — 사용자의
# 기존 Python 환경 보호.
function Install-Python313ViaWinget {
    Write-Warn2 'Python 3.13 자동 설치 (winget --scope user, 관리자 권한 불필요)'

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Warn2 'winget 미설치 → 로컬 격리 설치로 전환 (Install-LocalPython313)'
        Install-LocalPython313
        return
    }

    $installExitCode = -1
    try {
        & winget install --id Python.Python.3.13 -e --scope user --silent `
            --accept-source-agreements --accept-package-agreements | Out-Null
        $installExitCode = $LASTEXITCODE
    } catch {
        Write-Warn2 "winget 예외 발생 ($($_.Exception.Message)) → 로컬 격리 설치로 전환"
        Install-LocalPython313
        return
    }
    if ($installExitCode -ne 0) {
        Write-Warn2 "winget 설치 실패 (exit=$installExitCode) → 로컬 격리 설치로 전환"
        Install-LocalPython313
        return
    }
    Write-Ok 'winget Python 3.13 설치 완료 (--scope user)'

    # py launcher 검출
    $launcherVer = $null
    $launcherExitCode = -1
    $hasLauncher = $null -ne (Get-Command py -ErrorAction SilentlyContinue)
    if ($hasLauncher) {
        try {
            $launcherVer = (& py -3.13 --version 2>&1 | Out-String).Trim()
            $launcherExitCode = $LASTEXITCODE
        } catch { $launcherVer = $null }
    }
    if (-not $hasLauncher -or $launcherExitCode -ne 0 -or $launcherVer -notmatch 'Python\s+3\.13') {
        Write-Warn2 'winget 설치 후 py launcher 미가용 → 로컬 격리 설치로 전환'
        Install-LocalPython313
        return
    }
    Write-Ok "py -3.13 검출: $launcherVer (venv 생성에 사용)"

    $script:PYTHON_VENV_EXE  = 'py'
    $script:PYTHON_VENV_ARGS = @('-3.13')
}

# ─── PR #123 — Python 3.13 로컬 격리 설치 (기존 Python 있을 때 사용) ────
# 핵심 보장:
#   ① 기존 Python 버전 (3.10/3.11/3.12/3.14 등) *완전 무관* — 시스템 / 사용자
#      Python 설치 어디에도 영향 X. 본 프로그램 전용 Python 을 *install 폴더 내부*
#      (``$INSTALL_DIR\python313\``) 에 격리 설치.
#   ② Python 공식 Windows 인스톨러 (.exe) 직접 호출 — winget 의존성 0
#      ``TargetDir=$INSTALL_DIR\python313 InstallAllUsers=0 PrependPath=0``
#   ③ PATH / 시스템 Python registry / py launcher 모두 미변경
#      (``PrependPath=0 Include_launcher=0``)
#   ④ 관리자 권한 불필요 (``InstallAllUsers=0``)
# 본 함수 종료 시 ``$script:PYTHON_VENV_EXE=<로컬 python.exe 절대경로>``,
# ``$script:PYTHON_VENV_ARGS=@()`` 설정 → Install-Venv 가 *로컬 Python 으로* venv 생성.
function Install-LocalPython313 {
    $pyVer = if ($env:NEXUS_ALPHA_PYTHON_VERSION) { $env:NEXUS_ALPHA_PYTHON_VERSION } else { '3.13.7' }
    $pyDir = Join-Path $INSTALL_DIR 'python313'
    $pyExe = Join-Path $pyDir 'python.exe'

    Write-Warn2 "Python $pyVer 로컬 격리 설치 시도 — 시스템/사용자 Python 영향 0 (대상 폴더: $pyDir)"

    # 기존 로컬 설치 재사용 (idempotent)
    if (Test-Path $pyExe) {
        $existingVer = $null
        try { $existingVer = (& $pyExe --version 2>&1 | Out-String).Trim() } catch { }
        if ($existingVer -match 'Python\s+3\.13') {
            Write-Ok "기존 로컬 Python 검출: $existingVer ($pyExe) — 재사용"
            $script:PYTHON_VENV_EXE  = $pyExe
            $script:PYTHON_VENV_ARGS = @()
            return
        }
        Write-Warn2 "기존 로컬 Python 손상 추정 ($existingVer) — 폴더 삭제 후 재설치"
        try { Remove-Item -Path $pyDir -Recurse -Force -ErrorAction Stop } catch {
            Fail "기존 로컬 Python 폴더 삭제 실패: $($_.Exception.Message) | 수동 삭제: $pyDir"
        }
    }

    # 다운로드
    $installerUrl  = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-amd64.exe"
    $installerPath = Join-Path $env:TEMP "nexus-alpha-python-$pyVer-amd64.exe"

    Write-Warn2 "Python $pyVer Windows 인스톨러 다운로드 중 (~25 MB) ..."
    try {
        $oldProg = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        $ProgressPreference = $oldProg
    } catch {
        Fail @"
Python $pyVer 다운로드 실패: $($_.Exception.Message)

가능한 원인:
  - 네트워크 연결 / 프록시 / 방화벽 (https://www.python.org 차단)
  - DNS 해석 실패

수동 fallback:
  1. https://www.python.org/downloads/release/python-3137/ 에서 직접 다운로드
  2. 'python-$pyVer-amd64.exe' 실행 시 'Customize installation' 선택
  3. Install Location = $pyDir (정확히)
  4. 'Install for all users' 체크 *해제*
  5. install.ps1 재실행 (로컬 Python 검출 → 의존성만 설치)
"@
    }
    if (-not (Test-Path $installerPath)) {
        Fail "Python 인스톨러 다운로드 후 파일 미존재: $installerPath"
    }
    Write-Ok "Python $pyVer 인스톨러 다운로드 완료"

    # 로컬 격리 설치 (~30 sec)
    Write-Warn2 "Python $pyVer 로컬 설치 중 (~30초, 시스템 영향 없음) ..."
    # SimpleInstall=1: 인스톨러 UI 미표시
    # TargetDir: install 폴더 내부에 격리
    # InstallAllUsers=0: per-user, 관리자 권한 불필요
    # PrependPath=0: PATH 미변경 (시스템 영향 회피)
    # Include_launcher=0: py.exe launcher 미설치 (시스템 영향 회피)
    # Include_pip=1: pip 포함 (venv 생성 후 의존성 설치 가능)
    # Shortcuts=0 + AssociateFiles=0: 바로가기 / .py 파일 연결 미변경
    $installArgs = @(
        '/quiet'
        "TargetDir=$pyDir"
        'InstallAllUsers=0'
        'PrependPath=0'
        'Include_launcher=0'
        'Include_pip=1'
        'Include_doc=0'
        'Include_test=0'
        'Shortcuts=0'
        'AssociateFiles=0'
        'CompileAll=0'
        'SimpleInstall=1'
    )

    try {
        $proc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
        $exitCode = $proc.ExitCode
    } catch {
        Remove-Item -Path $installerPath -ErrorAction SilentlyContinue
        Fail "Python 인스톨러 실행 예외: $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $installerPath -ErrorAction SilentlyContinue
    }

    if ($exitCode -ne 0) {
        Fail @"
Python $pyVer 로컬 인스톨러 실행 실패 (exit=$exitCode).

가능한 원인:
  - 디스크 공간 부족 ($pyDir 가용 공간 확인)
  - 파일 잠금 (이전 설치 잔존)
  - $pyDir 경로에 한글 등 비-ASCII 문자

수동 fallback:
  https://www.python.org/downloads/release/python-3137/ 다운로드 후
  TargetDir = $pyDir 로 수동 설치 → install.ps1 재실행.
"@
    }

    # 검증 — python.exe 생성 + 버전 확인
    if (-not (Test-Path $pyExe)) {
        Fail "Python 설치 후 $pyExe 미생성 — 인스톨러 동작 이상"
    }
    $installedVer = $null
    try { $installedVer = (& $pyExe --version 2>&1 | Out-String).Trim() } catch { }
    if (-not $installedVer -or $installedVer -notmatch 'Python\s+3\.13') {
        Fail "로컬 Python 설치는 했으나 버전 확인 실패: '$installedVer'"
    }
    Write-Ok "Python 로컬 설치 완료: $installedVer ($pyExe)"
    Write-Ok '시스템 Python / PATH / registry / py launcher 모두 미변경 (격리 보장)'

    # Install-Venv 가 *로컬 Python* 으로 venv 생성하도록 설정
    $script:PYTHON_VENV_EXE  = $pyExe
    $script:PYTHON_VENV_ARGS = @()
}

# ─── 1. 사전 검사 ───────────────────────────────────────────────────────────
function Test-Prereqs {
    Write-Step 'Step 1/6 — 사전 요구사항 확인'

    # git
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Fail @"
git 이 PATH 에 없습니다.

  설치: winget install --id Git.Git -e
        또는 https://git-scm.com/download/win
"@
    }
    Write-Ok "git: $(git --version)"

    # PR #112 — 기존 .venv 검출 시 시스템 python 체크 skip.
    # 사용자가 ``py -3.13 -m venv $HOME\nexus-alpha\.venv`` 로 *수동* 으로 venv 만든
    # 경우 (시스템 python 이 3.14+ 여도) 설치 흐름 진행 가능. PR #110 안내 §2 워크플로
    # 직접 지원.
    $existingVenvPython = Join-Path $INSTALL_DIR '.venv\Scripts\python.exe'
    if (Test-Path $existingVenvPython) {
        $venvVersion = (& $existingVenvPython --version 2>&1).ToString().Trim()
        Write-Ok "python (기존 .venv): $venvVersion"
        Write-Warn2 '시스템 python 버전 체크 skip — .venv 가 이미 검증된 환경으로 간주'
        # gh CLI 만 마저 검증 후 함수 종료
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if ($gh) {
            Write-Ok "gh CLI: $((gh --version | Select-Object -First 1))"
        } else {
            Write-Warn2 'gh CLI 미설치 — Draft Release 발행 단계는 skip 됩니다.'
            Write-Warn2 '  설치: winget install --id GitHub.cli -e  (선택)'
        }
        return
    }

    # Python 3.13
    # PR #114 — 시스템 python 3.14+ 감지 시 ``py -3.13`` 자동 fallback 으로 venv 생성.
    # $script:PYTHON_VENV_EXE + $script:PYTHON_VENV_ARGS 가 Install-Venv 에서 venv 생성에 사용됨.
    # 기본은 system 'python' — 3.14+ 일 때만 'py -3.13' 으로 전환.
    $script:PYTHON_VENV_EXE  = 'python'
    $script:PYTHON_VENV_ARGS = @()

    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        # PR #117 — python 미설치 시 winget 으로 Python 3.13 자동 설치 후 진행
        Write-Warn2 'python 이 PATH 에 없음 → Python 3.13 자동 설치 시도'
        Install-Python313ViaWinget
        # 자동 설치 성공 시 PYTHON_VENV_EXE/ARGS 설정됨 → gh CLI 만 마저 검증 후 return
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if ($gh) {
            Write-Ok "gh CLI: $((gh --version | Select-Object -First 1))"
        } else {
            Write-Warn2 'gh CLI 미설치 — Draft Release 발행 단계는 skip 됩니다.'
            Write-Warn2 '  설치: winget install --id GitHub.cli -e  (선택)'
        }
        return
    }
    # PR #124 — python --version 실행 실패 / Microsoft Store stub alias 검출 강화.
    # Windows 10+ 는 ``python`` PATH stub 으로 Microsoft Store 페이지를 열 수 있음 →
    # ``python --version`` 호출 시 stderr 만 출력 / 빈 출력 / "Reparse" 메시지.
    # 이전 (PR #110~#123) 은 정규식 매치 실패 시 단순 Warn → 설치 함수 미호출 →
    # Step 2/6 부터 venv 생성 fail.
    $pyVersionOutput = & python --version 2>&1
    $pyVersionExit = $LASTEXITCODE
    $pyVersion = if ($null -ne $pyVersionOutput) { ($pyVersionOutput | Out-String).Trim() } else { '' }
    $isStoreStub = ($pyVersion -match 'Microsoft Store|Reparse|App Installer') -or `
                   ($pyVersionExit -ne 0) -or `
                   ([string]::IsNullOrWhiteSpace($pyVersion))
    if ($isStoreStub) {
        Write-Warn2 "python 실행 비정상 (exit=$pyVersionExit, output='$pyVersion') — Microsoft Store stub 추정. 로컬 격리 설치로 진행."
        Install-LocalPython313
        # gh CLI 만 마저 검증 후 return (Step 1/6 완료)
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if ($gh) { Write-Ok "gh CLI: $((gh --version | Select-Object -First 1))" }
        else {
            Write-Warn2 'gh CLI 미설치 — Draft Release 발행 단계는 skip 됩니다.'
            Write-Warn2 '  설치: winget install --id GitHub.cli -e  (선택)'
        }
        return
    }
    # PR #110 — CrewAI 1.14.1 의 Python 지원 범위는 ``>=3.10,<3.14``.
    # 3.14+ 에서 의존성 (chromadb / instructor / pydantic-core) 빌드 실패 (사용자 보고).
    # PR #114 — 3.14+ 시 즉시 Fail 대신 ``py -3.13`` launcher 자동 fallback 시도.
    if ($pyVersion -match 'Python\s+(\d+)\.(\d+)') {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        if ($major -eq 3 -and $minor -ge 10 -and $minor -le 13) {
            # 3.10 ~ 3.13 (정상 범위)
            if ($minor -eq 13) {
                Write-Ok "python: $pyVersion"
            } else {
                Write-Ok "python: $pyVersion (3.13 권장, 현재 버전도 호환)"
            }
        } elseif ($major -gt 3 -or ($major -eq 3 -and $minor -ge 14)) {
            # PR #114 — 3.14+ 자동 fallback: ``py -3.13`` launcher 시도
            Write-Warn2 "시스템 python: $pyVersion (CrewAI 1.14.x 미지원). ``py -3.13`` launcher 시도..."
            $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
            $launcherVer = $null
            if ($pyLauncher) {
                $launcherVer = (& py -3.13 --version 2>&1 | Out-String).Trim()
            }
            if ($pyLauncher -and $LASTEXITCODE -eq 0 -and $launcherVer -match 'Python\s+3\.13') {
                # py launcher 의 3.13 사용 가능 → venv 생성에 사용
                $script:PYTHON_VENV_EXE  = 'py'
                $script:PYTHON_VENV_ARGS = @('-3.13')
                Write-Ok "py -3.13 fallback: $launcherVer (venv 생성에 사용)"
            } else {
                # PR #123 — 기존 Python 있음 (호환 안 됨) → 로컬 격리 설치 (시스템 미터치)
                Write-Warn2 'py -3.13 launcher 가용 불가 → 로컬 격리 Python 설치 (기존 시스템 Python 보존)'
                Install-LocalPython313
            }
        } else {
            # 3.10 미만 (3.9, 3.8 등 EOL) — PR #123 로컬 격리 (기존 Python 미터치)
            Write-Warn2 "현재 $pyVersion (CrewAI 미지원) → 로컬 격리 Python 설치 (기존 시스템 Python 보존)"
            Install-LocalPython313
        }
    } else {
        # PR #124 — 정규식 매치 실패 = python 명령은 있지만 표준 출력 형식 아님.
        # 비정상 상태로 간주 → 로컬 격리 설치 (시스템 미터치).
        Write-Warn2 "Python 버전 파싱 실패 ($pyVersion) — 로컬 격리 설치로 진행 (시스템 미터치)"
        Install-LocalPython313
    }

    # gh CLI (선택 — Draft Release 발행용)
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        Write-Ok "gh CLI: $((gh --version | Select-Object -First 1))"
    } else {
        Write-Warn2 'gh CLI 미설치 — Draft Release 발행 단계는 skip 됩니다.'
        Write-Warn2 '  설치: winget install --id GitHub.cli -e  (선택)'
    }
}

# ─── 2. 저장소 clone / update ───────────────────────────────────────────────
# PR #109 — 모든 native command 호출은 ``| Out-Null`` 만 사용 (``2>&1`` 사용 금지).
# 이유: Windows PowerShell 5.1 + ``$ErrorActionPreference = 'Stop'`` 조합에서
# ``& nativecmd 2>&1`` 은 stderr 각 줄을 NativeCommandError ErrorRecord 로 wrap
# 하여 스크립트를 중단시킴 (사용자 보고: "From https://... 오류로 실패"). 본 PR
# 부터 stderr 는 console 로 흘러 사용자가 git/pip 진행 상황을 볼 수 있다.
# (실패 검출은 ``$LASTEXITCODE`` 가 안정적으로 작동).
function Invoke-CleanClone {
    & git clone --branch $BRANCH "https://github.com/$REPO.git" $INSTALL_DIR | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "git clone 실패 (https://github.com/$REPO.git)" }
    Write-Ok "clone 완료"
}

function Update-ExistingRepo {
    # 반환: $true (정상 업데이트) / $false (실패 — caller 가 Reset-InstallDirAndClone 호출)
    #
    # PR #107 — git pull --ff-only 대신 git fetch + git reset --hard 사용.
    # *destructive sync* — 추적 파일의 로컬 변경 모두 폐기 후 origin/$BRANCH 강제 동기화.
    # 안전성: .env / .venv / outputs / logs / items.csv 등 모두 .gitignore 또는
    # untracked → reset 영향 없음. 추적된 src/, docs/, scripts/ 의 사용자 수정만 폐기
    # (installer 사용자는 일반적으로 코드 수정 안 함 — 의도된 동작).
    Push-Location $INSTALL_DIR
    try {
        & git fetch origin $BRANCH | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 'git fetch 실패 — fresh clone 으로 전환'
            return $false
        }
        $localBranch = (& git branch --show-current).Trim()
        if ($localBranch -ne $BRANCH) {
            # 다른 브랜치 → 강제 checkout (-B 로 브랜치 생성 또는 재설정)
            & git checkout -B $BRANCH "origin/$BRANCH" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "git checkout $BRANCH 실패 — fresh clone 으로 전환"
                return $false
            }
        }
        & git reset --hard "origin/$BRANCH" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "git reset --hard origin/$BRANCH 실패 (.git 손상 가능) — fresh clone 으로 전환"
            return $false
        }
        Write-Ok "git fetch + reset --hard origin/$BRANCH 완료 (로컬 변경 폐기)"
        return $true
    } finally {
        Pop-Location
    }
}

function Reset-InstallDirAndClone {
    # PR #106 — git 동기화 실패 시 기존 폴더 backup 후 fresh clone (PR #107 기준 fetch/reset --hard).
    # .env 는 보존 (사용자 시크릿 손실 방지).
    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $brokenLeaf  = "$(Split-Path $INSTALL_DIR -Leaf).broken.$timestamp"
    $brokenPath  = Join-Path (Split-Path $INSTALL_DIR -Parent) $brokenLeaf
    $envBackup   = Join-Path ([System.IO.Path]::GetTempPath()) "nexus-alpha-env.$timestamp"

    # .env 백업 (있는 경우만)
    $envFile = Join-Path $INSTALL_DIR '.env'
    $envBackedUp = $false
    if (Test-Path $envFile) {
        try {
            Copy-Item -Path $envFile -Destination $envBackup -ErrorAction Stop
            $envBackedUp = $true
            Write-Ok ".env 백업: $envBackup"
        } catch {
            Write-Warn2 ".env 백업 실패: $($_.Exception.Message) (계속 진행 — 수동 복구 필요할 수 있음)"
        }
    }

    # 기존 폴더 → .broken.{timestamp} 로 이름 변경 (즉시 삭제 X — 안전망)
    try {
        Rename-Item -Path $INSTALL_DIR -NewName $brokenLeaf -ErrorAction Stop
        Write-Ok "기존 폴더 보관: $brokenPath (수동 확인 후 삭제 가능)"
    } catch {
        $errMsg = $_.Exception.Message
        Fail "기존 폴더 rename 실패 (파일 잠금 가능): $errMsg | 수동 조치: Python/VSCode/터미널 세션 종료 후 재시도, 또는 Remove-Item -Recurse -Force $INSTALL_DIR"
    }

    # fresh clone
    Invoke-CleanClone

    # .env 복원
    if ($envBackedUp) {
        try {
            Copy-Item -Path $envBackup -Destination $envFile -ErrorAction Stop
            Write-Ok ".env 복원 완료 (백업본 보존: $envBackup)"
        } catch {
            Write-Warn2 ".env 복원 실패: $($_.Exception.Message) — 수동 복구 필요"
        }
    }
}

function Get-Repo {
    Write-Step "Step 2/6 — 저장소 준비 ($REPO)"

    $parent = Split-Path $INSTALL_DIR -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }

    if (Test-Path (Join-Path $INSTALL_DIR '.git')) {
        Write-Ok "기존 저장소 발견 — 업데이트 시도 (git fetch + reset --hard)"
        $updated = Update-ExistingRepo
        if (-not $updated) {
            # PR #106 — 동기화 실패 시 backup + fresh clone (사용자 .env 보존)
            Reset-InstallDirAndClone
        }
        return
    }

    if (Test-Path $INSTALL_DIR) {
        Fail "$INSTALL_DIR 가 이미 존재하지만 git 저장소가 아닙니다. 다른 경로 또는 \$env:NEXUS_ALPHA_DIR 사용."
    }
    Invoke-CleanClone
}

# ─── 3. 가상환경 + 의존성 ──────────────────────────────────────────────────
function Install-Venv {
    Write-Step 'Step 3/6 — 가상환경 + 의존성 설치'

    $venvDir = Join-Path $INSTALL_DIR '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'

    if (Test-Path $venvPython) {
        Write-Ok '.venv 이미 존재 — 의존성만 재설치'
    } else {
        # PR #114/#123 — $script:PYTHON_VENV_EXE / $script:PYTHON_VENV_ARGS 는 Test-Prereqs 에서 설정.
        # 가능 값:
        #   - 'python' (3.10~3.13 정상)
        #   - 'py' + @('-3.13') (3.14+ py launcher fallback)
        #   - '<INSTALL_DIR>\python313\python.exe' (PR #123 로컬 격리 설치 시 절대 경로)
        # 미설정 (.venv 이미 존재해서 Test-Prereqs 가 early return 한 경우) → 'python' 기본.
        if (-not $script:PYTHON_VENV_EXE) { $script:PYTHON_VENV_EXE = 'python' }
        if ($null -eq $script:PYTHON_VENV_ARGS) { $script:PYTHON_VENV_ARGS = @() }
        $venvCmdArgs = $script:PYTHON_VENV_ARGS + @('-m', 'venv', '.venv')

        Push-Location $INSTALL_DIR
        try {
            & $script:PYTHON_VENV_EXE $venvCmdArgs | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $cmdStr = "$($script:PYTHON_VENV_EXE) $($script:PYTHON_VENV_ARGS -join ' ') -m venv .venv".Trim()
                Fail "가상환경 생성 실패 ($cmdStr)"
            }
        } finally {
            Pop-Location
        }
        $cmdSummary = "$($script:PYTHON_VENV_EXE) $($script:PYTHON_VENV_ARGS -join ' ')".Trim()
        Write-Ok "가상환경 생성: .venv (via $cmdSummary -m venv)"
    }

    Push-Location $INSTALL_DIR
    try {
        & $venvPython -m pip install --upgrade pip | Out-Null
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { Fail '의존성 설치 실패 (pip install -r requirements.txt)' }
    } finally {
        Pop-Location
    }
    Write-Ok '의존성 설치 완료 (requirements.txt)'
}

# ─── 4. .env 초기화 (PR #104 — .env.example 자동 복사) ─────────────────────
function Initialize-EnvFile {
    Write-Step 'Step 4/6 — .env 초기화'

    $envFile     = Join-Path $INSTALL_DIR '.env'
    $envExample  = Join-Path $INSTALL_DIR '.env.example'

    if (Test-Path $envFile) {
        Write-Ok '.env 이미 존재 — 변경 안 함 (사용자 값 보존)'
        return
    }
    if (-not (Test-Path $envExample)) {
        Write-Warn2 '.env.example 미존재 — .env 초기화 skip (저장소 무결성 확인 필요)'
        return
    }
    Copy-Item -Path $envExample -Destination $envFile -ErrorAction Stop
    Write-Ok ".env 생성 (.env.example 복사) — 키 값 채워 넣어 사용"
    Write-Warn2 '편집 필요:'
    Write-Host ('    ' + $envFile) -ForegroundColor DarkGray
    Write-Warn2 'LangFuse 사용 시 LANGFUSE_PUBLIC_KEY/SECRET_KEY 필수 (선택)'
    Write-Warn2 'API Key 모드 사용 시 ANTHROPIC_API_KEY 필수 (LLM_PROVIDER=api_key)'
}

# ─── 5. smoke test ─────────────────────────────────────────────────────────
function Test-Install {
    if ($env:NEXUS_ALPHA_SKIP_SMOKE -eq '1') {
        Write-Step 'Step 5/6 — smoke test (skip, NEXUS_ALPHA_SKIP_SMOKE=1)'
        return
    }
    Write-Step 'Step 5/6 — smoke test (import 검증)'

    $venvPython = Join-Path $INSTALL_DIR '.venv\Scripts\python.exe'
    Push-Location $INSTALL_DIR
    try {
        $smoke = @'
import sys
sys.path.insert(0, '.')
import src.workflows.analyze_and_implement  # noqa: F401
import src.workflows.automate_workflow  # noqa: F401
print("OK")
'@
        $output = $smoke | & $venvPython - 2>&1
        if ($LASTEXITCODE -ne 0 -or $output -notmatch 'OK') {
            Write-Warn2 'smoke test 경고 — 일부 모듈 import 실패 (실 사용 시 오류 가능):'
            Write-Host $output -ForegroundColor DarkGray
        } else {
            Write-Ok 'workflow 모듈 import OK'
        }
    } finally {
        Pop-Location
    }
}

# ─── 5. 다음 단계 안내 ─────────────────────────────────────────────────────
function Show-NextSteps {
    Write-Step 'Step 6/6 — 설치 완료'
    Write-Host ''
    Write-Host '🎉 Nexus Alpha 가 준비됐습니다.' -ForegroundColor Green
    Write-Host ''
    Write-Host '다음 단계:' -ForegroundColor White
    Write-Host ''
    Write-Host "  cd `"$INSTALL_DIR`"" -ForegroundColor Cyan
    Write-Host '  .\.venv\Scripts\python.exe scripts\run.py' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '또는 자연어 한 줄로 (Track 자동 라우팅):' -ForegroundColor White
    Write-Host ''
    Write-Host '  .\.venv\Scripts\python.exe scripts\run.py --request "계산기 만들어줘"' -ForegroundColor Cyan
    Write-Host '  .\.venv\Scripts\python.exe scripts\run.py --request "네이버 쇼핑 가격 크롤링" --track B' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '환경 변수 (선택):' -ForegroundColor DarkGray
    Write-Host '  $env:ANTHROPIC_API_KEY     — Claude API Key (USE_API_KEY=true 시 필수)' -ForegroundColor DarkGray
    Write-Host '  $env:LANGFUSE_PUBLIC_KEY   — LangFuse 모니터링 (선택)' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '문서: https://github.com/SongJongwon/nexus-alpha#readme' -ForegroundColor DarkGray
    Write-Host ''
}

# ─── 진입점 ────────────────────────────────────────────────────────────────
Write-Banner
try {
    Test-Prereqs
    Get-Repo
    Install-Venv
    Initialize-EnvFile
    Test-Install
    Show-NextSteps
} catch {
    Fail $_.Exception.Message
}
