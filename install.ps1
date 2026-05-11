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
$INSTALL_DIR = if ($env:NEXUS_ALPHA_DIR)    { $env:NEXUS_ALPHA_DIR }    else { Join-Path $env:USERPROFILE 'nexus-alpha' }
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
    exit 1
}

# ─── 1. 사전 검사 ───────────────────────────────────────────────────────────
function Test-Prereqs {
    Write-Step 'Step 1/5 — 사전 요구사항 확인'

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

    # Python 3.13
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Fail @"
python 이 PATH 에 없습니다.

  설치: winget install --id Python.Python.3.13 -e
        또는 https://www.python.org/downloads/release/python-3130/
"@
    }
    $pyVersion = (& python --version 2>&1).ToString().Trim()
    if ($pyVersion -notmatch '^Python\s+3\.1[3-9]') {
        Write-Warn2 "현재 $pyVersion — Nexus Alpha 는 Python 3.13+ 권장 (CrewAI 1.14.1 호환)."
        Write-Warn2 '3.12 이하에서는 일부 의존성 오류 가능 — 계속 진행하지만 문제 시 3.13 재설치 권장.'
    } else {
        Write-Ok "python: $pyVersion"
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
function Get-Repo {
    Write-Step "Step 2/5 — 저장소 준비 ($REPO)"

    $parent = Split-Path $INSTALL_DIR -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }

    if (Test-Path (Join-Path $INSTALL_DIR '.git')) {
        Write-Ok "기존 저장소 발견 — 업데이트 (git pull)"
        Push-Location $INSTALL_DIR
        try {
            & git fetch origin $BRANCH 2>&1 | Out-Null
            $localBranch = (& git branch --show-current).Trim()
            if ($localBranch -eq $BRANCH) {
                & git pull --ff-only origin $BRANCH 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn2 'git pull --ff-only 실패 — 로컬 변경사항 있을 수 있습니다. 수동 확인 권장.'
                }
            } else {
                Write-Warn2 "현재 브랜치($localBranch) ≠ 대상($BRANCH) — 자동 checkout 생략. 수동: git checkout $BRANCH"
            }
        } finally {
            Pop-Location
        }
    } else {
        if (Test-Path $INSTALL_DIR) {
            Fail "$INSTALL_DIR 가 이미 존재하지만 git 저장소가 아닙니다. 다른 경로 또는 \$env:NEXUS_ALPHA_DIR 사용."
        }
        & git clone --branch $BRANCH "https://github.com/$REPO.git" $INSTALL_DIR 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "git clone 실패 (https://github.com/$REPO.git)" }
        Write-Ok "clone 완료"
    }
}

# ─── 3. 가상환경 + 의존성 ──────────────────────────────────────────────────
function Install-Venv {
    Write-Step 'Step 3/5 — 가상환경 + 의존성 설치'

    $venvDir = Join-Path $INSTALL_DIR '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'

    if (Test-Path $venvPython) {
        Write-Ok '.venv 이미 존재 — 의존성만 재설치'
    } else {
        Push-Location $INSTALL_DIR
        try {
            & python -m venv .venv 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Fail '가상환경 생성 실패 (python -m venv .venv)' }
        } finally {
            Pop-Location
        }
        Write-Ok '가상환경 생성: .venv'
    }

    Push-Location $INSTALL_DIR
    try {
        & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { Fail '의존성 설치 실패 (pip install -r requirements.txt)' }
    } finally {
        Pop-Location
    }
    Write-Ok '의존성 설치 완료 (requirements.txt)'
}

# ─── 4. smoke test ─────────────────────────────────────────────────────────
function Test-Install {
    if ($env:NEXUS_ALPHA_SKIP_SMOKE -eq '1') {
        Write-Step 'Step 4/5 — smoke test (skip, NEXUS_ALPHA_SKIP_SMOKE=1)'
        return
    }
    Write-Step 'Step 4/5 — smoke test (import 검증)'

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
    Write-Step 'Step 5/5 — 설치 완료'
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
    Test-Install
    Show-NextSteps
} catch {
    Fail $_.Exception.Message
}
