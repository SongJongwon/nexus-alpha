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

# ─── PR #125 — Native command 안전 호출 helper ─────────────────────────────
# 배경: ``& nativecmd 2>&1 | Out-String`` 패턴은 ``$ErrorActionPreference = 'Stop'``
# 하에서 NativeCommandError 트리거 — stderr 한 줄이라도 있으면 스크립트 abort.
# 해결: stderr 를 *file-handle level* 에서 discard (``2>$null``) — PowerShell pipeline
# 거치지 않으므로 NativeCommandError 미발생. exit code 는 별도 ``$LASTEXITCODE`` 로 확인.
function Invoke-NativeSafely {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$Executable,
        [string[]]$Arguments = @()
    )
    # PR #126 — 함수 내부 EAP 격리: 외부에서 'Stop' 이어도 내부는 'Continue'.
    # native command 의 stderr / non-zero exit 가 throw 되지 않음을 100% 보장.
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $stdout = ''
    $exit = -1
    try {
        $stdout = & $Executable @Arguments 2>$null | Out-String
        $exit = $LASTEXITCODE
    } catch {
        $stdout = ''
        $exit = -1
    } finally {
        $ErrorActionPreference = $savedEAP
    }
    [pscustomobject]@{
        StdOut    = if ($stdout) { $stdout.Trim() } else { '' }
        ExitCode  = $exit
        Succeeded = ($exit -eq 0)
    }
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

# ─── PR #128 — registry 기반 기존 Python 3.13 검출 (orphan MSI 식별) ─────
# 배경 (사용자 PC 인스톨러 로그 분석):
#   Python 공식 인스톨러 (Burn bundle) 가 ``Modify`` action + ``execute: None`` 으로
#   silent 종료 (exit=0) 하지만 실제 파일 미생성. 원인: 이전 시도에서 부분 설치된
#   MSI registry 가 남아 있어 인스톨러가 "이미 설치됨" 으로 판단.
# 본 helper:
#   - HKCU / HKLM 의 ``Software\Python\PythonCore\3.13\InstallPath`` 검사
#   - 검출 + python.exe 존재 → 경로 반환 (정상 재사용 시나리오)
#   - 검출 + python.exe 미존재 → orphan 신호 ($null + 별도 변수로 caller 에 전달)
# 반환: pscustomobject (Found=bool, Path=string, Orphan=bool)
function Get-ExistingPython313 {
    $regKeys = @(
        'HKCU:\Software\Python\PythonCore\3.13\InstallPath'
        'HKLM:\Software\Python\PythonCore\3.13\InstallPath'
        'HKLM:\SOFTWARE\Wow6432Node\Python\PythonCore\3.13\InstallPath'
    )
    foreach ($k in $regKeys) {
        if (-not (Test-Path $k)) { continue }
        $prop = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue
        if (-not $prop) { continue }
        # 우선순위: ExecutablePath > (default) + 'python.exe'
        $candidates = @()
        if ($prop.ExecutablePath) { $candidates += $prop.ExecutablePath }
        $defaultDir = $prop.'(default)'
        if ($defaultDir) { $candidates += (Join-Path $defaultDir 'python.exe') }
        foreach ($c in $candidates) {
            if (-not $c) { continue }
            if (Test-Path $c) {
                # 정상 검출 — 버전 확인
                $verResult = Invoke-NativeSafely -Executable $c -Arguments @('--version')
                if ($verResult.Succeeded -and $verResult.StdOut -match 'Python\s+3\.13') {
                    return [pscustomobject]@{ Found=$true; Path=$c; Orphan=$false; RegistryKey=$k }
                }
            }
        }
        # registry 존재하나 candidate 중 어느 것도 실 파일 없음 → orphan
        return [pscustomobject]@{ Found=$false; Path=''; Orphan=$true; RegistryKey=$k }
    }
    # 모든 registry key 없음
    return [pscustomobject]@{ Found=$false; Path=''; Orphan=$false; RegistryKey='' }
}

# ─── PR #133 — Orphan Python 3.13 MSI 잔재 수동 정리 ──────────────────────
# 배경 (사용자 라이브 검증, 2026-05-12, PR #133 1차 시도):
#   PR #128 이 도입한 ``Burn bundle /uninstall /quiet`` 가 ``exit=1603`` (ERROR_
#   INSTALL_FAILURE) 으로 실패 — Package Cache 의 .exe 가 corrupt 되어 Burn 이
#   자체 uninstall 불가. 이후 install 도 phantom "이미 설치됨" 판단으로 silent fail.
# 처방 (PR #133):
#   uninstall 실패 시 registry + Package Cache + Add/Remove Programs 항목을 *직접
#   강제 삭제* 후 install retry. 모든 정리는 ``Python 3.13`` 으로 *정확 매칭* — 다른
#   버전 (3.10/3.11/3.12/3.14+) 영향 0, 사용자 데이터 영향 0.
function Remove-OrphanPython313Artifacts {
    Write-Warn2 'orphan MSI registry / Package Cache 수동 정리 중 (uninstall 1603 fallback)...'
    $cleaned = 0

    # ① registry: HKCU/HKLM 의 PythonCore\3.13 키 직접 삭제
    $registryRoots = @(
        'HKCU:\Software\Python\PythonCore\3.13',
        'HKLM:\Software\Python\PythonCore\3.13',
        'HKLM:\SOFTWARE\Wow6432Node\Python\PythonCore\3.13'
    )
    foreach ($k in $registryRoots) {
        if (Test-Path $k) {
            try {
                Remove-Item -Path $k -Recurse -Force -ErrorAction Stop
                Write-Ok "registry 삭제: $k"
                $cleaned++
            } catch {
                Write-Warn2 "registry 삭제 실패 (권한 부족 가능): $k — $($_.Exception.Message)"
            }
        }
    }

    # ② MSI Package Cache — Python 3.13.x 만 매칭
    # Burn bundle 가 만드는 폴더는 GUID 기반. 폴더 안의 .exe 의 VersionInfo.ProductName 로 식별.
    $pcRoot = Join-Path $env:LocalAppData 'Package Cache'
    if (Test-Path $pcRoot) {
        $children = Get-ChildItem -Path $pcRoot -Directory -ErrorAction SilentlyContinue
        foreach ($d in $children) {
            $burnExe = Get-ChildItem -Path $d.FullName -Filter '*.exe' -File -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if (-not $burnExe) { continue }
            $prodName = ''
            try { $prodName = $burnExe.VersionInfo.ProductName } catch {}
            if ($prodName -match 'Python 3\.13') {
                try {
                    Remove-Item -Path $d.FullName -Recurse -Force -ErrorAction Stop
                    Write-Ok "Package Cache 정리: $($d.Name) [$prodName]"
                    $cleaned++
                } catch {
                    Write-Warn2 "Package Cache 삭제 실패: $($d.Name) — $($_.Exception.Message)"
                }
            }
        }
    }

    # ③ Add/Remove Programs — Python 3.13.x 의 Uninstall registry entry 직접 삭제
    $uninstallRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($base in $uninstallRoots) {
        if (-not (Test-Path $base)) { continue }
        Get-ChildItem -Path $base -ErrorAction SilentlyContinue | ForEach-Object {
            $prop = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
            if (-not $prop) { return }
            $dn = if ($prop.DisplayName) { [string]$prop.DisplayName } else { '' }
            if ($dn -match 'Python 3\.13') {
                try {
                    Remove-Item -Path $_.PSPath -Recurse -Force -ErrorAction Stop
                    Write-Ok "Add/Remove Programs entry 정리: $dn"
                    $cleaned++
                } catch {
                    Write-Warn2 "uninstall entry 삭제 실패: $dn — $($_.Exception.Message)"
                }
            }
        }
    }

    if ($cleaned -gt 0) {
        Write-Ok "orphan 정리 완료 ($cleaned 항목 처리됨)"
    } else {
        Write-Warn2 'orphan 정리 대상 없음 (이미 모두 정리됨 또는 권한 부족)'
    }
    return $cleaned
}

# ─── PR #133 — Embeddable Python 경로 *완전 제거* ─────────────────────────
# 배경 (사용자 라이브 검증, 2026-05-12):
#   PR #129 가 도입한 embeddable Python fallback 은 venv 생성까지는 통과시켰으나
#   **embeddable distribution 은 tkinter (Tcl/Tk GUI 백엔드) 를 원천적으로 미포함**.
#   결과: PyInstaller 가 GUI .exe (customtkinter 등) 를 빌드해도 런타임에
#   ``ModuleNotFoundError: No module named 'tkinter'`` 발생 → GUI .exe 풀체인 실패.
# 처방:
#   embeddable fallback 전면 제거 → 풀 Python 3.13 (python.org Windows installer)
#   만 사용. MSI 가 실패하면 명확한 메시지로 Fail (조용한 추락보다 명시적 실패가
#   사용자에게 더 도움). Install-EmbeddablePython 함수 + 보조 Invoke-VirtualenvVenvCreation
#   helper 삭제, ``$script:PYTHON_VENV_EMBEDDABLE`` 분기 삭제.

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
    # PR #125 — Invoke-NativeSafely 로 NativeCommandError 회피
    $launcherVer = ''
    $launcherExitCode = -1
    $hasLauncher = $null -ne (Get-Command py -ErrorAction SilentlyContinue)
    if ($hasLauncher) {
        $r = Invoke-NativeSafely -Executable 'py' -Arguments @('-3.13', '--version')
        $launcherVer = $r.StdOut
        $launcherExitCode = $r.ExitCode
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

    # PR #128 — 부모 디렉토리 미생성 시 인스톨러 silent fail 사례 (사용자 보고).
    # Install-LocalPython313 은 Step 1/6 (Get-Repo 이전) 에서 호출되므로 $INSTALL_DIR
    # 가 아직 미존재 가능. Python 공식 인스톨러는 TargetDir 의 *부모 폴더 자동 생성*
    # 을 보장하지 않음 → 수동 사전 생성.
    if (-not (Test-Path $INSTALL_DIR)) {
        try {
            New-Item -ItemType Directory -Path $INSTALL_DIR -Force -ErrorAction Stop | Out-Null
            Write-Ok "설치 폴더 사전 생성: $INSTALL_DIR (Python 인스톨러 TargetDir 부모)"
        } catch {
            Fail "설치 폴더 생성 실패 ($INSTALL_DIR): $($_.Exception.Message)"
        }
    }

    # 기존 로컬 설치 재사용 (idempotent) — PR #125 NativeCommandError 회피
    # PR #133 — 재사용 전 tkinter 검증 추가: embeddable Python 잔재 (PR #129~#132)
    # 가 reuse 되는 것 차단 (Test-Prereqs 의 cleanup 이 file lock 등으로 실패한 경우 대비).
    if (Test-Path $pyExe) {
        $existingVer = (Invoke-NativeSafely -Executable $pyExe -Arguments @('--version')).StdOut
        if ($existingVer -match 'Python\s+3\.13') {
            # PR #133 — tkinter 검증
            $existingTk = Invoke-NativeSafely -Executable $pyExe -Arguments @('-c', 'import tkinter')
            if ($existingTk.Succeeded) {
                Write-Ok "기존 로컬 Python 검출: $existingVer ($pyExe) — 재사용 (tkinter OK)"
                $script:PYTHON_VENV_EXE  = $pyExe
                $script:PYTHON_VENV_ARGS = @()
                return
            }
            Write-Warn2 "기존 로컬 Python ($existingVer) 가 tkinter 미포함 (embeddable 잔재) — 폴더 삭제 후 풀 Python 재설치"
            try { Remove-Item -Path $pyDir -Recurse -Force -ErrorAction Stop } catch {
                Fail "embeddable Python 폴더 삭제 실패: $($_.Exception.Message) | 수동 삭제: Remove-Item -Recurse -Force '$pyDir'"
            }
        } else {
            Write-Warn2 "기존 로컬 Python 손상 추정 ($existingVer) — 폴더 삭제 후 재설치"
            try { Remove-Item -Path $pyDir -Recurse -Force -ErrorAction Stop } catch {
                Fail "기존 로컬 Python 폴더 삭제 실패: $($_.Exception.Message) | 수동 삭제: $pyDir"
            }
        }
    }

    # PR #128 — registry 기반 기존 Python 3.13 검출
    #   사용자 보고: PR #127 의 인스톨러가 ``Modify`` action + ``execute: None`` 으로
    #   silent 종료 (exit=0) → 파일 미생성. 원인: 이전 시도의 MSI 잔존 registry.
    # 처방:
    #   ① registry 검출 + python.exe 존재 → 그 경로 재사용 (install 스킵)
    #   ② registry 존재하나 python.exe 미존재 → orphan 으로 식별, install 전 uninstall
    $reg = Get-ExistingPython313
    if ($reg.Found) {
        Write-Ok "기존 Python 3.13 registry 검출: $($reg.Path) — 재사용 (install 스킵)"
        $script:PYTHON_VENV_EXE  = $reg.Path
        $script:PYTHON_VENV_ARGS = @()
        return
    }
    $orphanedRegistry = $reg.Orphan
    if ($orphanedRegistry) {
        Write-Warn2 "Python 3.13 MSI registry 잔존 ($($reg.RegistryKey)) — 파일 없음 → orphan 정리 필요"
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

    # PR #128 — orphan MSI registry 정리: 다운로드한 인스톨러로 /uninstall /quiet 호출.
    # Burn bundle 이 "이미 설치됨" 으로 잘못 판단해 install 을 ``Modify execute: None``
    # 으로 변환하는 문제 해결. uninstall 은 실제 파일이 없어도 안전 (실패해도 무시).
    # PR #133 — uninstall 이 1603 등으로 실패 시 (Burn cache 손상) registry + Package
    # Cache + Add/Remove Programs entry 를 *직접 강제 삭제* 로 fallback.
    if ($orphanedRegistry) {
        Write-Warn2 "Orphan MSI registry uninstall 중 (~10초) — Burn bundle 잘못된 'Modify' 회피"
        $uninstallLog = Join-Path $env:TEMP "nexus-alpha-python-uninstall-$pyVer.log"
        $uninstallExit = -1
        try {
            $procUn = Start-Process -FilePath $installerPath `
                -ArgumentList @('/uninstall', '/quiet', '/log', $uninstallLog) `
                -Wait -PassThru -NoNewWindow
            $uninstallExit = $procUn.ExitCode
        } catch {
            Write-Warn2 "Uninstall 시도 예외 ($($_.Exception.Message)) — 계속 진행"
        }
        if ($uninstallExit -eq 0) {
            Write-Ok 'Orphan MSI registry 정리 완료'
        } else {
            # PR #133 — uninstall 실패 (Burn cache 손상 추정) → 수동 강제 정리
            Write-Warn2 "Uninstall exit=$uninstallExit (로그: $uninstallLog) — 수동 강제 정리 시도"
            $null = Remove-OrphanPython313Artifacts
        }
    }

    # 로컬 격리 설치 (~30 sec)
    Write-Warn2 "Python $pyVer 로컬 설치 중 (~30초, 시스템 영향 없음) ..."
    # PR #128 — Python 인스톨러 로그 capture (silent fail 진단용)
    $installLog = Join-Path $env:TEMP "nexus-alpha-python-install-$pyVer.log"
    # TargetDir + DefaultJustForMeTargetDir: install 폴더 내부에 격리 (PR #128 — 일부
    #   환경에서 TargetDir 단독으로는 무시되고 DefaultJustForMeTargetDir 가 사용되는
    #   보고. 둘 다 지정해 둘 중 어느 쪽이 사용돼도 동일 경로 보장).
    # InstallAllUsers=0: per-user, 관리자 권한 불필요
    # PrependPath=0: PATH 미변경 (시스템 영향 회피)
    # Include_launcher=0: py.exe launcher 미설치 (시스템 영향 회피)
    # Include_pip=1: pip 포함 (venv 생성 후 의존성 설치 가능)
    # Shortcuts=0 + AssociateFiles=0: 바로가기 / .py 파일 연결 미변경
    # SimpleInstall=1 제거 (PR #128): /quiet 와 중복 + 일부 환경에서 사용자 정의
    #   옵션을 무시하고 기본 위치로 설치하는 사례 보고됨.
    # PR #133 — Include_tcltk=1 명시: 풀 Python 의 tkinter (Tcl/Tk GUI 백엔드) 강제 포함.
    # python.org 인스톨러 기본값이 1 이지만 belt-and-suspenders. embeddable fallback
    # 제거 후 GUI .exe (customtkinter 등) 빌드 시 tkinter 필수.
    $installArgs = @(
        '/quiet'
        '/log'
        $installLog
        "TargetDir=$pyDir"
        "DefaultJustForMeTargetDir=$pyDir"
        'InstallAllUsers=0'
        'PrependPath=0'
        'Include_launcher=0'
        'Include_pip=1'
        'Include_tcltk=1'
        'Include_doc=0'
        'Include_test=0'
        'Shortcuts=0'
        'AssociateFiles=0'
        'CompileAll=0'
    )

    # PR #133 — installer .exe 는 retry 가능성 때문에 *함수 끝* 에서만 삭제.
    # 과거: finally { Remove-Item $installerPath } 이 1차 install 직후 인스톨러를
    # 삭제 → orphan cleanup 후 retry 시 "지정된 파일을 찾을 수 없습니다" 예외 발생.
    try {
        $proc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
        $exitCode = $proc.ExitCode
    } catch {
        Remove-Item -Path $installerPath -ErrorAction SilentlyContinue
        Fail "Python 인스톨러 실행 예외: $($_.Exception.Message)"
    }

    if ($exitCode -ne 0) {
        $logHint = if (Test-Path $installLog) { "`n  인스톨러 로그: $installLog" } else { '' }
        Fail @"
Python $pyVer 로컬 인스톨러 실행 실패 (exit=$exitCode).$logHint

가능한 원인:
  - 디스크 공간 부족 ($pyDir 가용 공간 확인)
  - 파일 잠금 (이전 설치 잔존)
  - $pyDir 경로에 한글 등 비-ASCII 문자
  - AntiVirus / EDR 차단

수동 fallback:
  https://www.python.org/downloads/release/python-3137/ 다운로드 후
  TargetDir = $pyDir 로 수동 설치 → install.ps1 재실행.
"@
    }

    # PR #128 — 검증: TargetDir 위치 확인 + 일부 환경에서 무시될 경우 기본 위치 fallback
    # PR #133 — MSI 실패 시 orphan 강제 정리 + 재시도 (1회) 후 Fail
    if (-not (Test-Path $pyExe)) {
        # 기본 user 위치 (per-user install) 확인 — TargetDir 가 무시된 경우
        $userDefaultDir = Join-Path $env:LocalAppData 'Programs\Python\Python313'
        $userDefaultExe = Join-Path $userDefaultDir 'python.exe'
        if (Test-Path $userDefaultExe) {
            Write-Warn2 "TargetDir ($pyExe) 미생성, 기본 user 위치 검출: $userDefaultExe"
            Write-Warn2 '인스톨러가 TargetDir 를 무시하고 기본 위치에 설치함 — 해당 경로 사용 (격리는 부분적: %LocalAppData% 안에 설치됨)'
            $pyExe = $userDefaultExe
            $pyDir = $userDefaultDir
        } else {
            # PR #133 — MSI phantom install 발견 → orphan 수동 강제 정리 후 재시도 (1회).
            Write-Warn2 'MSI install 후 python.exe 미생성 — orphan 잔재 의심, 수동 강제 정리 + 재시도 1회'
            $extraCleaned = Remove-OrphanPython313Artifacts

            # 안전망 (PR #133): installer 파일이 어떤 이유로든 사라졌으면 재다운로드.
            if (-not (Test-Path $installerPath)) {
                Write-Warn2 'installer 파일 부재 (TEMP 정리됨) — 재다운로드'
                try {
                    $oldProg = $ProgressPreference
                    $ProgressPreference = 'SilentlyContinue'
                    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
                    $ProgressPreference = $oldProg
                } catch {
                    Fail "재시도용 Python 인스톨러 다운로드 실패: $($_.Exception.Message)"
                }
            }

            Write-Warn2 "Python $pyVer MSI 재설치 중 (cleanup 후, ~30초)..."
            $retryLog = Join-Path $env:TEMP "nexus-alpha-python-install-$pyVer-retry.log"
            # $installArgs 중 /log 만 새 경로로 교체. 나머지 인자는 동일.
            $retryArgs = @()
            $i = 0
            while ($i -lt $installArgs.Count) {
                if ($installArgs[$i] -eq '/log') {
                    $retryArgs += '/log'
                    $retryArgs += $retryLog
                    $i += 2
                } else {
                    $retryArgs += $installArgs[$i]
                    $i += 1
                }
            }
            $retryExit = -1
            try {
                $procRetry = Start-Process -FilePath $installerPath -ArgumentList $retryArgs -Wait -PassThru -NoNewWindow
                $retryExit = $procRetry.ExitCode
            } catch {
                Write-Warn2 "재설치 예외: $($_.Exception.Message)"
            }
            if ($retryExit -eq 0 -and (Test-Path $pyExe)) {
                Write-Ok "Python $pyVer 재설치 성공 (orphan 정리 후)"
            } elseif ($retryExit -eq 0 -and (Test-Path $userDefaultExe)) {
                Write-Warn2 "재설치도 TargetDir 무시 — 기본 위치 사용: $userDefaultExe"
                $pyExe = $userDefaultExe
                $pyDir = $userDefaultDir
            } else {
                # PR #133 — 재시도도 실패 → 명시적 Fail (사용자에게 actionable guidance).
                $logHint = ''
                if (Test-Path $retryLog) {
                    $logHint = "`n  재시도 로그: $retryLog"
                } elseif (Test-Path $installLog) {
                    $logHint = "`n  최초 로그: $installLog"
                }
                Fail @"
Python $pyVer MSI 인스톨러 실행 후 python.exe 미생성 [TargetDir + LocalAppData 모두 없음].
원인 추정: MSI Burn bundle phantom install — registry 잔재 + MSI cache 손상 동시 발생.$logHint

수동 조치 [관리자 권한 불필요]:
  1. https://www.python.org/downloads/release/python-3137/ 에서 'Windows installer 64-bit' 다운로드
  2. 실행 후 'Install Now' 선택 [per-user 설치]
     - 'Add python.exe to PATH' 체크 권장
  3. 설치 완료 확인: 새 PowerShell 창에서 'py -3.13 --version' 정상 출력 확인
  4. install.ps1 재실행 [irm | iex]

깊은 진단 [MSI Burn bundle 손상 시]:
  - %LocalAppData%\Package Cache\ 의 Python 관련 폴더 검사 + 손상 항목 수동 삭제
  - Windows '앱 및 기능' 에서 'Python 3.13' 항목 모두 제거 [있다면]
  - install.ps1 재실행

PR #129~#132 의 embeddable Python fallback 은 tkinter 미포함 문제로 PR #133 에서 제거됨.
GUI 앱 [.exe] 빌드에는 풀 Python 인스톨러 필수.
"@
            }
        }
    }
    # PR #125 — Invoke-NativeSafely 로 NativeCommandError 회피
    $installedVer = (Invoke-NativeSafely -Executable $pyExe -Arguments @('--version')).StdOut
    if (-not $installedVer -or $installedVer -notmatch 'Python\s+3\.13') {
        Fail "로컬 Python 설치는 했으나 버전 확인 실패: '$installedVer'"
    }
    # PR #133 — tkinter 포함 검증 (Include_tcltk=1 이 실제 작동했는지 확인).
    # 풀 Python 의 표준 라이브러리이므로 import 가능해야 함.
    $tkResult = Invoke-NativeSafely -Executable $pyExe -Arguments @('-c', 'import tkinter; print("tk OK")')
    if (-not $tkResult.Succeeded -or $tkResult.StdOut -notmatch 'tk OK') {
        Fail @"
로컬 Python 설치 완료했으나 tkinter import 실패:
  python.exe = $pyExe
  output = $($tkResult.StdOut)
  exit = $($tkResult.ExitCode)

원인: 인스톨러가 Tcl/Tk 컴포넌트 미포함 (Include_tcltk=1 무시됨).
조치: 인스톨러로 직접 ``Customize installation`` → 'tcl/tk and IDLE' 체크박스 켜고 재설치.
"@
    }
    Write-Ok "Python 로컬 설치 완료: $installedVer ($pyExe)"
    Write-Ok 'tkinter 검증 통과 (GUI 백엔드 작동)'
    Write-Ok '시스템 Python / PATH / registry / py launcher 모두 미변경 (격리 보장)'

    # PR #133 — 성공 시 installer .exe 정리 (TEMP 청소). Fail 시는 OS 가 자동 cleanup.
    Remove-Item -Path $installerPath -ErrorAction SilentlyContinue

    # Install-Venv 가 *로컬 Python* 으로 venv 생성하도록 설정
    $script:PYTHON_VENV_EXE  = $pyExe
    $script:PYTHON_VENV_ARGS = @()
}

# ─── 1. 사전 검사 ───────────────────────────────────────────────────────────
function Test-Prereqs {
    Write-Step 'Step 1/6 — 사전 요구사항 확인'

    # PR #126 — Test-Prereqs 전체에서 EAP 격리: native command (git/python/py) 의
    # stderr / non-zero exit 가 외부 EAP=Stop 영향 받지 않음 100% 보장.
    # 모든 native 호출은 Invoke-NativeSafely 또는 동등 패턴 사용.
    $savedEAPPrereqs = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {

    # git
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Fail @"
git 이 PATH 에 없습니다.

  설치: winget install --id Git.Git -e
        또는 https://git-scm.com/download/win
"@
    }
    $gitVerResult = Invoke-NativeSafely -Executable 'git' -Arguments @('--version')
    Write-Ok "git: $($gitVerResult.StdOut)"

    # PR #112 — 기존 .venv 검출 시 시스템 python 체크 skip.
    # 사용자가 ``py -3.13 -m venv $HOME\nexus-alpha\.venv`` 로 *수동* 으로 venv 만든
    # 경우 (시스템 python 이 3.14+ 여도) 설치 흐름 진행 가능. PR #110 안내 §2 워크플로
    # 직접 지원.
    # PR #133 — 기존 .venv 의 tkinter import 검증. embeddable Python 으로 만들어진
    # .venv (PR #129~#132 이력) 라면 tkinter 미포함 → 자동 정리 후 fresh install.
    $existingVenvPython = Join-Path $INSTALL_DIR '.venv\Scripts\python.exe'
    if (Test-Path $existingVenvPython) {
        $tkCheck = Invoke-NativeSafely -Executable $existingVenvPython -Arguments @('-c', 'import tkinter')
        if (-not $tkCheck.Succeeded) {
            Write-Warn2 "기존 .venv 의 Python 이 tkinter 미포함 (embeddable Python 잔재 추정: $existingVenvPython)"
            Write-Warn2 '자동 정리 후 풀 Python 인스톨러로 재설치 진행 (PR #133)'
            # .venv + 로컬 embeddable python313/ 정리. 사용자 데이터 (.env, src/, outputs/) 무관.
            try {
                Remove-Item -Path (Join-Path $INSTALL_DIR '.venv') -Recurse -Force -ErrorAction Stop
                Write-Ok '기존 .venv 삭제 완료'
            } catch {
                Fail "기존 .venv 삭제 실패: $($_.Exception.Message) | 수동 조치: Remove-Item -Recurse -Force '$INSTALL_DIR\.venv'"
            }
            $embedPyDir = Join-Path $INSTALL_DIR 'python313'
            if (Test-Path $embedPyDir) {
                # python313/ 가 embeddable 인지 확인 (Lib\site-packages\virtualenv 존재 = embeddable 잔재)
                $embedExe = Join-Path $embedPyDir 'python.exe'
                $embedTkCheck = if (Test-Path $embedExe) {
                    Invoke-NativeSafely -Executable $embedExe -Arguments @('-c', 'import tkinter')
                } else {
                    @{ Succeeded = $false }
                }
                if (-not $embedTkCheck.Succeeded) {
                    try {
                        Remove-Item -Path $embedPyDir -Recurse -Force -ErrorAction Stop
                        Write-Ok "기존 embeddable python313/ 삭제: $embedPyDir"
                    } catch {
                        Write-Warn2 "python313/ 삭제 실패 ($($_.Exception.Message)) — 계속 진행, 풀 Python 별도 위치 설치"
                    }
                }
            }
            # 정리 후 일반 flow 로 진입 (Python 검출 → Install-LocalPython313)
        } else {
            $venvVersion = (Invoke-NativeSafely -Executable $existingVenvPython -Arguments @('--version')).StdOut
            Write-Ok "python (기존 .venv): $venvVersion (tkinter OK)"
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
    # PR #126 — Invoke-NativeSafely 로 NativeCommandError 완전 회피.
    $pyVerResult = Invoke-NativeSafely -Executable 'python' -Arguments @('--version')
    $pyVersion = $pyVerResult.StdOut
    $pyVersionExit = $pyVerResult.ExitCode
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
            # PR #126 — 단순 2-단 분기 (PR #125 의 ``py install 3.13`` 단계 제거):
            #   ① ``py -3.13 --version`` 검출 (이미 설치 시 happy path)
            #   ② 실패 시 ``Install-LocalPython313`` (deterministic)
            # 제거 이유: ``py install`` 명령은 일부 환경에서 *대화형 prompt* 또는 *hang*
            # 위험 (Windows Hello 인증 prompt / Microsoft Store 페이지 등). generic 보장을
            # 위해 외부 변수 의존 제거.
            Write-Warn2 "시스템 python: $pyVersion (CrewAI 1.14.x 미지원). ``py -3.13`` launcher 검출..."
            $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
            $pyOk = $false
            if ($pyLauncher) {
                $r1 = Invoke-NativeSafely -Executable 'py' -Arguments @('-3.13', '--version')
                if ($r1.Succeeded -and $r1.StdOut -match 'Python\s+3\.13') {
                    $pyOk = $true
                    Write-Ok "py -3.13 검출: $($r1.StdOut) (venv 생성에 사용)"
                }
            }
            if ($pyOk) {
                $script:PYTHON_VENV_EXE  = 'py'
                $script:PYTHON_VENV_ARGS = @('-3.13')
            } else {
                # PR #128 — registry 기반 기존 Python 3.13 검출 (py launcher 가 못 찾는 경우 대응)
                $regHit = Get-ExistingPython313
                if ($regHit.Found) {
                    Write-Ok "Python 3.13 registry 검출: $($regHit.Path) (venv 생성에 사용)"
                    $script:PYTHON_VENV_EXE  = $regHit.Path
                    $script:PYTHON_VENV_ARGS = @()
                } else {
                    # 최후의 안전망: 로컬 격리 설치 (시스템 미터치, deterministic)
                    # Install-LocalPython313 가 내부에서 orphan registry 도 정리.
                    Write-Warn2 'py -3.13 / registry 모두 미가용 → 로컬 격리 Python 설치 (기존 시스템 Python 보존)'
                    Install-LocalPython313
                }
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

    } finally {
        # PR #126 — EAP 복원 (정상 종료 / Fail / 예외 모두 cover)
        $ErrorActionPreference = $savedEAPPrereqs
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
        # PR #130 — 비-git $INSTALL_DIR 자동 recovery
        # 배경 (사용자 보고): Install-LocalPython313 / Install-EmbeddablePython 의
        #   이전 시도가 ``$INSTALL_DIR\python313\`` 폴더를 남기고 Get-Repo 전에 종료
        #   → 다음 실행 시 ``$INSTALL_DIR`` 가 존재하나 .git 없음 → Fail.
        # 처방: 폴더 내용이 *우리 artifact 만* 이면 안전 recovery (백업 → clone → 복원).
        #       사용자 데이터가 있으면 기존대로 Fail (안전 우선).
        $children = @(Get-ChildItem -Path $INSTALL_DIR -Force -ErrorAction SilentlyContinue)
        # 우리 artifacts: python313/ (Install-LocalPython313/Embeddable), .env (Initialize-EnvFile),
        # .venv/ (Install-Venv), broken backup 폴더 등.
        $ourArtifacts = @('python313', '.env', '.venv')
        $unknownChildren = $children | Where-Object {
            $_.Name -notin $ourArtifacts -and $_.Name -notlike '*.broken.*'
        }

        if ($unknownChildren) {
            $sample = (($unknownChildren | Select-Object -First 5).Name) -join ', '
            $more = if ($unknownChildren.Count -gt 5) { "...(+$($unknownChildren.Count - 5))" } else { '' }
            Fail @"
$INSTALL_DIR 가 이미 존재하지만 git 저장소가 아닙니다.
  알 수 없는 항목 검출 (사용자 데이터 보호 위해 자동 정리 안 함):
    $sample$more

수동 조치:
  ① 폴더 백업 후 삭제:
       Move-Item -Path '$INSTALL_DIR' -Destination '$INSTALL_DIR.bak'
       irm https://raw.githubusercontent.com/$REPO/$BRANCH/install.ps1 | iex
  ② 또는 다른 경로 지정:
       `$env:NEXUS_ALPHA_DIR = 'C:\다른경로'
       irm https://raw.githubusercontent.com/$REPO/$BRANCH/install.ps1 | iex
"@
        }

        # 우리 artifacts 만 있음 → 안전 recovery
        Write-Warn2 "$INSTALL_DIR 에 이전 시도의 artifact 만 존재 — 자동 정리 후 fresh clone"
        $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $tempBackup = Join-Path $env:TEMP "nexus-alpha-recovery-$timestamp"
        New-Item -ItemType Directory -Path $tempBackup -Force | Out-Null

        # python313/ 백업 (있으면)
        $pythonDir = Join-Path $INSTALL_DIR 'python313'
        $pythonBackedUp = $false
        if (Test-Path $pythonDir) {
            try {
                Move-Item -Path $pythonDir -Destination (Join-Path $tempBackup 'python313') -ErrorAction Stop
                $pythonBackedUp = $true
                Write-Ok "python313/ 임시 백업 → $tempBackup\python313 (로컬 격리 Python 보존)"
            } catch {
                Write-Warn2 "python313/ 백업 실패 ($($_.Exception.Message)) — fresh install 진행"
            }
        }
        # .env 백업 (있으면)
        $envFile = Join-Path $INSTALL_DIR '.env'
        $envBackedUp = $false
        if (Test-Path $envFile) {
            try {
                Copy-Item -Path $envFile -Destination (Join-Path $tempBackup '.env') -ErrorAction Stop
                $envBackedUp = $true
                Write-Ok ".env 백업 → $tempBackup\.env"
            } catch {
                Write-Warn2 ".env 백업 실패 ($($_.Exception.Message))"
            }
        }

        # 남은 INSTALL_DIR 삭제 (이제 우리 artifact 만 남음)
        try {
            Remove-Item -Path $INSTALL_DIR -Recurse -Force -ErrorAction Stop
        } catch {
            Fail "기존 $INSTALL_DIR 삭제 실패: $($_.Exception.Message) | 수동 삭제: Remove-Item -Recurse -Force '$INSTALL_DIR'"
        }

        # Fresh clone
        Invoke-CleanClone

        # 백업한 artifacts 복원
        if ($pythonBackedUp) {
            try {
                Move-Item -Path (Join-Path $tempBackup 'python313') -Destination $pythonDir -ErrorAction Stop
                Write-Ok 'python313/ 복원 완료 (로컬 격리 Python 재사용)'
            } catch {
                Write-Warn2 "python313/ 복원 실패 ($($_.Exception.Message)) — Install-Venv 가 시스템 Python 사용"
            }
        }
        if ($envBackedUp) {
            try {
                Copy-Item -Path (Join-Path $tempBackup '.env') -Destination $envFile -ErrorAction Stop
                Write-Ok '.env 복원 완료'
            } catch {
                Write-Warn2 ".env 복원 실패 ($($_.Exception.Message))"
            }
        }
        Remove-Item -Path $tempBackup -Recurse -Force -ErrorAction SilentlyContinue
        return
    }
    Invoke-CleanClone
}

# ─── 3. 가상환경 + 의존성 ──────────────────────────────────────────────────
# PR #133 — Invoke-VirtualenvVenvCreation helper 삭제. embeddable Python 경로 제거로
# 더 이상 ``python -m virtualenv`` fallback 이 필요 없음 (풀 Python 3.13 은 venv
# 모듈을 표준 포함). PR #131/#132 의 helper 및 EAP 격리 로직은 이력으로 git 에 보존.

function Install-Venv {
    Write-Step 'Step 3/6 — 가상환경 + 의존성 설치'

    $venvDir = Join-Path $INSTALL_DIR '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'

    # PR #132 — Install-Venv 전체에서 EAP 격리 (Test-Prereqs PR #126 패턴 그대로).
    # 배경 (사용자 보고): PR #131 의 ``2>$stderrFile`` 리디렉션이 외부 EAP=Stop 하에서
    #   NativeCommandError 트리거 → $LASTEXITCODE 검사 이전에 throw → ``No module named
    #   venv`` 자동 감지 분기 못 탐. 외부 catch 가 직접 Fail 호출 → 사용자에게 raw
    #   stderr 한 줄만 표시됨.
    # 처방: 함수 진입 시 EAP=Continue 격리 + finally 복원. 모든 native command
    #   (& py / & python / & venvPython) 가 NativeCommandError 회피.
    $savedEAPVenv = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {

    if (Test-Path $venvPython) {
        Write-Ok '.venv 이미 존재 — 의존성만 재설치'
    } else {
        # PR #114/#123 — $script:PYTHON_VENV_EXE / $script:PYTHON_VENV_ARGS 는 Test-Prereqs 에서 설정.
        # 가능 값:
        #   - 'python' (3.10~3.13 정상) — venv 모듈 사용
        #   - 'py' + @('-3.13') (3.14+ py launcher fallback) — venv 모듈 사용
        #   - '<INSTALL_DIR>\python313\python.exe' (PR #123 로컬 격리 설치 시 절대 경로) — venv 모듈 사용
        # PR #133 — embeddable Python 경로 제거. 풀 Python 만 사용.
        # 미설정 (.venv 이미 존재해서 Test-Prereqs 가 early return 한 경우) → 'python' 기본.
        if (-not $script:PYTHON_VENV_EXE) { $script:PYTHON_VENV_EXE = 'python' }
        if ($null -eq $script:PYTHON_VENV_ARGS) { $script:PYTHON_VENV_ARGS = @() }

        Push-Location $INSTALL_DIR
        try {
            # PR #133 — 풀 Python 만 사용. ``python -m venv .venv`` 또는 ``py -3.13 -m venv .venv``.
            # ``No module named venv`` 발생 시 embeddable Python 의심 → 명시적 Fail (embeddable
            # fallback 제거됨). PR #131 의 stderr file 캡처 패턴은 진단 정보를 위해 유지.
            $stderrFile = Join-Path $env:TEMP "nexus-alpha-venv-create-$([System.Guid]::NewGuid().ToString('N')).log"
            $venvCmdArgs = $script:PYTHON_VENV_ARGS + @('-m', 'venv', '.venv')
            & $script:PYTHON_VENV_EXE $venvCmdArgs 2>$stderrFile | Out-Null
            $venvExit = $LASTEXITCODE
            $venvErr = ''
            if (Test-Path $stderrFile) {
                $venvErr = Get-Content -Path $stderrFile -Raw -ErrorAction SilentlyContinue
                if (-not $venvErr) { $venvErr = '' }
            }
            Remove-Item -Path $stderrFile -ErrorAction SilentlyContinue

            if ($venvExit -eq 0) {
                $cmdSummary = ("$($script:PYTHON_VENV_EXE) " + (($script:PYTHON_VENV_ARGS + @('-m','venv')) -join ' ')).Trim()
                Write-Ok "가상환경 생성: .venv (via $cmdSummary)"
            } elseif ($venvErr -match 'No module named venv') {
                $missingVenvCmd = ($script:PYTHON_VENV_EXE + ' ' + ($script:PYTHON_VENV_ARGS -join ' ')).Trim()
                Fail @"
검출된 Python 이 venv 모듈을 포함하지 않습니다: $missingVenvCmd
이는 embeddable Python (zip 배포본) 의 특징입니다.

PR #133 부터 embeddable Python 경로는 지원하지 않습니다 (tkinter 미포함 문제).
풀 Python 3.13 인스톨러 사용이 필요합니다.

수동 조치 [관리자 권한 불필요]:
  1. https://www.python.org/downloads/release/python-3137/ 에서 'Windows installer 64-bit' 다운로드
  2. 실행 후 'Install Now' 선택 [per-user 설치]
  3. install.ps1 재실행 [irm | iex]
"@
            } else {
                $cmdStr = ("$($script:PYTHON_VENV_EXE) " + ($venvCmdArgs -join ' ')).Trim()
                $errHint = if ($venvErr) { "`nstderr: $($venvErr.TrimEnd())" } else { '' }
                Fail "가상환경 생성 실패 ($cmdStr)$errHint"
            }

            # PR #133 — 생성된 venv 의 tkinter 검증: 풀 Python 인스톨러는 tkinter 표준 포함.
            # 실패 시 embeddable Python 잔재 의심 — 명시적 Fail.
            $venvTkResult = Invoke-NativeSafely -Executable $venvPython -Arguments @('-c', 'import tkinter; print("tk OK")')
            if (-not $venvTkResult.Succeeded -or $venvTkResult.StdOut -notmatch 'tk OK') {
                Fail @"
가상환경 생성은 성공했으나 tkinter import 실패:
  python.exe = $venvPython
  output     = $($venvTkResult.StdOut)
  exit       = $($venvTkResult.ExitCode)

원인: 베이스 Python 이 Tcl/Tk 미포함 (embeddable distribution 또는 손상된 인스톨).
조치: 풀 Python 3.13 (https://python.org/downloads/release/python-3137/) 재설치 후 다시 시도.
"@
            }
            Write-Ok 'tkinter 검증 통과 (Tcl/Tk GUI 백엔드 작동)'
        } finally {
            Pop-Location
        }
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

    } finally {
        # PR #132 — EAP 복원 (정상 종료 / Fail / 예외 모두 cover)
        $ErrorActionPreference = $savedEAPVenv
    }
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
    # PR #126 — smoke test 도 EAP 격리 + stderr 를 *file handle* 로 redirect:
    # ``2>&1 | Out-String`` 사용 금지 (NativeCommandError 트리거). stderr 는 임시 파일로
    # 분리 capture → 안전 + 진단 정보 양쪽 모두 확보.
    $savedEAPSmoke = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $stderrFile = Join-Path $env:TEMP "nexus-alpha-smoke-stderr-$([System.Guid]::NewGuid().ToString('N')).txt"
    try {
        $smoke = @'
import sys
sys.path.insert(0, '.')
import src.workflows.analyze_and_implement  # noqa: F401
import src.workflows.automate_workflow  # noqa: F401
print("OK")
'@
        # stderr → 임시 파일 (PowerShell pipeline 미경유 → NativeCommandError 미발생)
        $stdout = $smoke | & $venvPython - 2>$stderrFile | Out-String
        $smokeExit = $LASTEXITCODE
        $stderrText = ''
        if (Test-Path $stderrFile) {
            $stderrText = Get-Content -Path $stderrFile -Raw -ErrorAction SilentlyContinue
            if (-not $stderrText) { $stderrText = '' }
        }
        if ($smokeExit -ne 0 -or $stdout -notmatch 'OK') {
            Write-Warn2 "smoke test 경고 — 일부 모듈 import 실패 (exit=$smokeExit, 실 사용 시 오류 가능):"
            if ($stdout) { Write-Host $stdout -ForegroundColor DarkGray }
            if ($stderrText) { Write-Host $stderrText -ForegroundColor DarkGray }
        } else {
            Write-Ok 'workflow 모듈 import OK'
        }
    } finally {
        Remove-Item -Path $stderrFile -ErrorAction SilentlyContinue
        $ErrorActionPreference = $savedEAPSmoke
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
