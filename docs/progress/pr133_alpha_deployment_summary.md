# PR #133 — Alpha 테스트 배포 작업 정리

**작성일**: 2026-05-13
**브랜치**: `pr-133-full-python-tkinter`
**PR**: https://github.com/SongJongwon/nexus-alpha/pull/133
**관련 커밋**: 53788ce → 1550b83 → 6764245 → 12d6c40 → 242f0ce → 2a83183 (총 6개)

---

## 1. 작업 목표

자연어 한 줄 (`irm | iex`) → GUI .exe 풀체인이 다른 사람 PC 에서도 *사용자 수동 작업 0* 으로 동작.

**핵심 요구사항:**
- 친구분 PC 에 Python 14.x 가 이미 깔려있어도 영향 0
- Nexus Alpha 전용 Python 3.13 을 *로컬 격리* 설치 (`$INSTALL_DIR\python313\`)
- GUI 앱 (`customtkinter` 사용) 빌드 + 실행 가능
- 관리자 권한 *불필요*

---

## 2. 발견된 결함 (사용자 라이브 검증으로 노출)

### 2.1 첫 번째 결함 — Calculator.exe 의 `ModuleNotFoundError: customtkinter`

**증상:** Track A 워크플로가 18분 걸려 `.exe` 를 만들었는데 더블클릭 실행 시 `No module named 'customtkinter'`.

**근본 원인:**
- Design agent (`gui_code_generator`) 가 `import customtkinter` 가 포함된 `calculator.py` 생성
- Dependency Analyzer LLM 이 `direct_dependencies: customtkinter` 를 markdown 보고서로 정확히 산출
- 그러나 `build_workflow.py` 가 **그 보고서를 markdown 파일에만 저장하고 `pip install` 단계를 안 함**
- PyInstaller 가 `.venv` 의 customtkinter 못 찾고 warning 만 띄운 채 빈 껍데기 `.exe` 생성

**자연어 → .exe 풀체인 자동화의 끊어진 첫 번째 고리.**

### 2.2 두 번째 결함 — `No module named 'tkinter'`

**증상:** customtkinter 를 수동 `pip install` 한 뒤 다시 빌드해도 .exe 가 다른 종류의 에러로 실패.

**근본 원인:**
- `install.ps1` 의 PR #129~#132 era 의 **embeddable Python fallback** 이 tkinter (Tcl/Tk GUI 백엔드) 를 *원천적으로 미포함*
- 사용자 PC 의 MSI Burn bundle 이 phantom install 상태라 풀 Python MSI 가 실패 → embeddable 로 fallback → tkinter 부재
- customtkinter 가 내부에서 `import tkinter` 호출 → 실패

**끊어진 두 번째 고리.**

---

## 3. PR #133 의 수정 사항

### 3.1 `install.ps1` — embeddable 경로 완전 제거 + tkinter 강제 보장

| 변경 | 내용 |
|------|------|
| `Install-EmbeddablePython` 함수 삭제 | tkinter 미포함 문제 원천 차단 |
| `Invoke-VirtualenvVenvCreation` helper 삭제 | embeddable 의존 helper 제거 |
| `Install-LocalPython313` 강화 | `/quiet` 인자에 `Include_tcltk=1` 명시 + 설치 후 `import tkinter` 검증 |
| MSI phantom install 시 embeddable fallback → 명시적 Fail | python.org URL 안내 |
| `Install-Venv` 의 `$script:PYTHON_VENV_EMBEDDABLE` 분기 제거 | embeddable 코드 경로 0 |
| `Install-Venv` venv 생성 후 `import tkinter` 검증 | embeddable 잔재 차단 |
| `Test-Prereqs` 기존 `.venv` 검출 시 tkinter 검증 | 잔재 자동 정리 → fresh install |

### 3.2 `src/workflows/build_workflow.py` — Track A B안 구현

| 변경 | 내용 |
|------|------|
| `_parse_deps_from_report(report) -> (direct_deps, hidden_imports)` 신설 | Dependency Analyzer 의 YAML 보고서 파싱 (PyYAML + regex fallback) |
| `_install_dependencies_for_build(deps)` 신설 | venv 의 `pip.exe` 직접 호출 (graceful failure) |
| `execute_pyinstaller` 호출 직전 자동 `pip install` + `hidden_imports` 전달 | 끊어진 고리 복원 |
| `25_executor_result.md` 에 자동 설치 결과 prepend | 감사 추적 |

### 3.3 `src/workflows/automate_workflow.py` — Track B B안 구현

| 변경 | 내용 |
|------|------|
| `_scan_imports_from_py(entry_path) -> list[str]` 신설 | entry `.py` 의 AST 스캔 → 외부 패키지 추출 (stdlib 제외) |
| `_run_track_b_build()` 가 PyInstaller 직전 자동 `pip install` | Track B 도 동일 처리 |

### 3.4 테스트: 824 → 849 (+25)

- `test_alpha_run_entry.py`: PR #129/#131/#132 의 embeddable 테스트들을 PR #133 anti-assertion 으로 교체 + 신규 테스트 (Include_tcltk=1, tkinter 검증, 기존 .venv 검사, orphan helper)
- `test_pr133_deps_autoinstall.py` 신규: B안 격리 검증 20 테스트

---

## 4. 사용자 PC 라이브 검증 과정에서 추가로 발견된 결함 (5번의 fixup)

PR #133 본체 머지 검증 중 친구분 PC 에서 *연쇄적으로* 5개의 추가 결함이 노출되었고, 각각을 fixup commit 으로 해결.

### fixup #1: orphan MSI registry 강제 정리 (uninstall 1603 fallback)

**증상:** `Uninstall exit=1603` (Package Cache .exe corrupt) → install 도 phantom Modify=None 으로 실패.

**해결:** `Remove-OrphanPython313Artifacts` helper 신설 — registry / Package Cache / Add/Remove Programs 항목을 직접 강제 삭제. 모두 `Python 3.13` 정확 매칭 — 다른 버전 영향 0.

### fixup #2: installer .exe 를 retry 까지 유지

**증상:** `재설치 예외: 지정된 파일을 찾을 수 없습니다.` — orphan cleanup 후 retry 시 installer .exe 가 사라진 상태.

**근본 원인:** `try/catch/finally` 의 `finally { Remove-Item $installerPath }` 가 1차 install 직후 인스톨러를 삭제.

**해결:** `finally` 블록 제거 → 함수 끝까지 installer 유지 → retry 가능.

### fixup #3: retry 직전 installer 항상 재다운로드

**증상:** fixup #2 이후에도 같은 "지정된 파일을 찾을 수 없습니다" 재발.

**근본 원인:** AntiVirus quarantine, NTFS reparse point, 파일 잠금 등 다양한 edge case 에서 `Test-Path` 가 true 여도 `Start-Process` 가 실패.

**해결:** retry 직전 *조건 없이* 기존 installer 삭제 + 재다운로드 → 매번 fresh copy 보장 (~10초 추가 비용).

### fixup #4: Windows Installer per-user MSI 등록 정리 ⭐ **결정적 단서**

**증상:** fixup #1~#3 후에도 MSI Burn bundle 이 또 phantom install.

**MSI 로그 분석으로 발견된 핵심:**
```
i101: Detected package: core_JustForMe, state: Present, cached: Complete
i101: Detected package: tcltk_JustForMe, state: Present, cached: Complete
...
i201: Planned package: core_JustForMe, ..., execute: None
i201: Planned package: tcltk_JustForMe, ..., execute: None
```

→ 각 sub-MSI 가 "이미 설치됨" 으로 인식 → "execute: None" → 아무 파일 설치 안 됨.

**근본 원인:** PR #128 이 정리하던 `HKCU\Software\Python\PythonCore\3.13` 외에 *Windows Installer 의 per-user MSI 자체 등록* 이 별도 위치에 잔존:
- `HKCU\Software\Microsoft\Installer\Products\<obfuscated_code>`
- `HKCU\Software\Microsoft\Installer\Features\<code>`
- `HKCU\Software\Classes\Installer\Products\<code>`
- `HKLM\...\UserData\<SID>\Products\<code>` (있는 경우)

**해결:** `Remove-OrphanPython313Artifacts` 에 ④ ⑤ 단계 추가. ProductName 매칭으로 `Python 3.13.x` 만 정확 식별. 라이브 검증에서 **21개 항목 정리됨** (registry 1 + Package Cache 1 + Add/Remove 7 + Installer Products 7 + UserData 7).

### fixup #5: 모든 Python 검출 경로에 tkinter 검증 추가

**증상:** fixup #4 후 MSI 가 정상 실행되는 단계에 도달했으나, Test-Prereqs 가 *MSI 호출 전에* `py -3.13` 으로 embeddable 잔재를 검출 → venv 가 tkinter 없는 상태로 생성.

**근본 원인:** Python 검출 3경로 (py -3.13 / Get-ExistingPython313 / python313 directory) 모두 `--version` 매칭만 확인. embeddable 도 `Python 3.13.7` 로 보고하므로 통과.

**해결:**
- `Test-Prereqs` 의 py -3.13 분기에 `import tkinter` 검증 추가
- registry (`Get-ExistingPython313`) 결과에도 `import tkinter` 검증 추가
- `Get-Repo` 의 python313/ recovery 가 backup 전에 tkinter 검증 (embeddable 이면 백업 X, 폐기)
- 검증 실패 시 자동으로 `Install-LocalPython313` (풀 Python MSI) 으로 fallback

---

## 5. 현재 상태 — fixup #5 까지 완료 후 미해결 잔재

### 5.1 완료된 부분 ✅

- `install.ps1` parser 0 errors (5102 tokens)
- pytest 849/849 (full suite)
- PR #133 + 5 fixup 모두 push 됨 (`pr-133-full-python-tkinter` 브랜치)

### 5.2 미해결 잔재 ⚠️

친구분 PC 에서 라이브 검증 시 **마지막 단계** 에서 막힘:

```
Plan: 모든 sub-MSI (core/exe/dev/lib/tcltk/pip) state: Absent, execute: Install  ← OK
Apply: result: 0x0 (success)  ← OK 보고
실제 결과: python.exe + tcltk 파일 *어디에도 없음*  ← BAD
```

**진단 (사용자 측 추가 검증으로 확정):**
- `C:\Users\work\nexus-alpha\python313\python.exe` — 부재
- `$env:LocalAppData\Programs\Python\` — 부재
- `C:\Program Files\Python*\` — 부재
- DLLs (`_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`) — 부재
- tcl/ 폴더, Lib/tkinter/ — 부재

**판정:** Windows Installer Apply 단계가 "성공" 보고하면서 *파일을 어디에도 안 씀*. 이건 PowerShell 스크립트 cleanup 범위 *밖*. 추정 원인 (사용자 PC 별 환경):
1. AntiVirus / EDR 가 Python 인스톨러의 파일 쓰기를 무음 차단
2. GroupPolicy 가 사용자 프로파일 폴더에 실행 파일 쓰기 차단
3. Windows Installer 서비스 자체 손상

---

## 6. 다음 작업 (우선순위 순)

### 6.1 즉시 — 친구분 PC 에서 마지막 1회 시도 (5분)

PowerShell 을 **"관리자 권한"** 으로 열고:
```powershell
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/pr-133-full-python-tkinter/install.ps1 | iex
```

관리자 권한이면 AntiVirus / EDR 차단을 우회할 수 있음. MSI install 이 1회 성공하면 그 다음부터는 install.ps1 이 정상 동작 (이미 설치된 Python 재사용).

### 6.2 정 안 되면 — PR #134 검토

**PR #134 (옵션 A): Embeddable Python + tcltk 번들 동봉** (~2-3h)
- `tcltk_bundle/` 폴더를 저장소에 추가 (~10MB):
  - `_tkinter.pyd` + `tcl86t.dll` + `tk86t.dll` + `tcl/` + `Lib/tkinter/`
- install.ps1 이 MSI 실패 시 embeddable + tcltk 복사로 fallback
- Tradeoff: 저장소 ~10MB 증가, Python 3.13.x 버전 종속

**PR #134 (옵션 B): MSI Apply 단계 진단 자동화**
- install.ps1 이 Apply 후 python.exe 부재 검출 시 Windows Defender 격리 로그 / 정책 진단 출력
- 사용자가 보고할 진단 정보를 자동 수집

### 6.3 PR #133 자체 검증 (별도, 친구분 PC 와 무관)

PR #133 의 핵심 가치는 *workflow 의 자동 pip install* (B안). 이건 친구분 PC 의 MSI 상태와 *무관* 합니다. 따라서:

1. **본인 PC (PR #133 install.ps1 가 정상 동작하는 PC) 에서** 라이브 검증:
   ```powershell
   $env:NEXUS_ALPHA_BRANCH = 'pr-133-full-python-tkinter'
   irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/pr-133-full-python-tkinter/install.ps1 | iex
   cd $HOME\nexus-alpha
   .\.venv\Scripts\python.exe scripts\run.py
   # 요청: "계산기를 예쁜 ui와 애니메이션이 들어간 UX 적용된걸로 만들어줘"
   # Track: Enter (A), Build: y
   ```
2. ~18분 후 산출 `.exe` 더블클릭 → **GUI 창이 정상으로 뜨면** B안 검증 완료
3. 검증 후 PR #133 머지

### 6.4 머지 후 후속 작업

- 메모리 업데이트: PR #129~#132 의 embeddable Python gap → PR #133 에서 해결됨 표시
- WORK_STATUS.md 갱신: customtkinter+tkinter 자동화 풀체인 검증 완료
- `requirements.txt` 에 customtkinter 추가 여부 검토 (현재는 B안 의 workflow 자동 설치에 의존)

---

## 7. 사용자 매뉴얼

### 7.1 친구분 PC 에 설치 (1줄)

PowerShell 창에서 (관리자 권한 권장):

```powershell
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex
```

설치 진행:
- Step 1/6 — 사전 요구사항 확인 (git / Python 3.13 자동 설치)
- Step 2/6 — 저장소 clone (`$HOME\nexus-alpha\`)
- Step 3/6 — 가상환경 + 의존성 설치 (~5분, requirements.txt)
- Step 4/6 — `.env` 초기화 (`.env.example` 복사)
- Step 5/6 — smoke test
- Step 6/6 — 완료

성공 메시지:
```
🎉 Nexus Alpha 가 준비됐습니다.
```

### 7.2 실행 (자연어 → .exe)

PowerShell 새 창에서:

```powershell
cd $HOME\nexus-alpha
.\.venv\Scripts\python.exe scripts\run.py
```

대화형 메뉴:
1. 자연어 요청 입력 (예: `계산기를 예쁜 ui로 만들어줘`)
2. Track 선택 (`Enter` = A 자동 감지, `1` = Track A, `2` = Track B)
3. Build 여부 (`y` = PyInstaller .exe 생성, `N` = 코드만)

결과 위치 (Track A + Build=y 기준):
```
$HOME\nexus-alpha\outputs\alpha_run_<timestamp>\workflow_<timestamp>\build_output\dist\Calculator.exe
```

소요 시간: ~18분 (LLM 호출 + PyInstaller).

### 7.3 `.env` 설정 (선택)

LangFuse 모니터링 / API Key 모드 사용 시:

```ini
LLM_PROVIDER=api_key
ANTHROPIC_API_KEY=sk-ant-xxxxx
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxx
```

`.env` 파일 위치: `$HOME\nexus-alpha\.env` (install.ps1 이 자동 생성 — 사용자가 값 채워 넣기).

### 7.4 환경 변수 옵션

| 변수 | 효과 |
|------|------|
| `NEXUS_ALPHA_DIR` | 설치 경로 (기본: `$HOME\nexus-alpha`) |
| `NEXUS_ALPHA_REPO` | git 저장소 (기본: `SongJongwon/nexus-alpha`) |
| `NEXUS_ALPHA_BRANCH` | 브랜치 (기본: `main`) |
| `NEXUS_ALPHA_SKIP_SMOKE` | `1` 이면 Step 5/6 smoke test 생략 |
| `NEXUS_ALPHA_NO_PAUSE` | `1` 이면 Fail 시 키 입력 대기 생략 (CI 용) |

PR 브랜치 테스트 시:
```powershell
$env:NEXUS_ALPHA_BRANCH = 'pr-133-full-python-tkinter'
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/pr-133-full-python-tkinter/install.ps1 | iex
```

### 7.5 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| `"문자 인식 안 됨"` (paste 시) | Markdown 따옴표가 smart quote 로 변환 | 작은 따옴표 `'...'` 사용 또는 직접 타이핑 |
| PowerShell `>>` 계속 대기 | 미완성 multi-line 입력 | **Ctrl+C** 로 취소 |
| Step 3/6 에서 `No module named 'venv'` | Python 이 embeddable 임 | PR #133 후엔 자동 감지 + 풀 Python 재설치 — 그래도 실패 시 관리자 권한으로 재시도 |
| Calculator.exe 가 `No module named 'customtkinter'` | 워크플로 의 자동 pip install 결함 (PR #133 이전) | PR #133 머지된 main 으로 재실행 |
| Calculator.exe 가 `No module named 'tkinter'` | 베이스 Python 이 embeddable (PR #129~#132 era 잔재) | PR #133 의 fixup #5 가 자동 감지 + 풀 Python 재설치 |
| MSI install 0x0 success 인데 python.exe 없음 | AntiVirus / EDR / GroupPolicy 의 무음 차단 | 관리자 권한으로 재시도 또는 manual install (https://python.org/downloads/release/python-3137/) |

---

## 8. 메모리·기록 갱신 항목

- `[Track B stub expect gap]` (project_track_b_stub_gap.md) — PR #100 으로 해결됨 표시
- `[install.ps1 local file 인코딩 gap]` (project_install_ps1_encoding_gap.md) — 여전히 미해결 (irm | iex 경로는 안전, 로컬 file 실행은 한국어 Windows 에서 CP949 디코딩 parse 실패)
- 신규: PR #133 에서 발견된 *Windows Installer per-user MSI 등록* (`HKCU\Software\Microsoft\Installer\Products`) 잔재 패턴 — 향후 MSI 자동 설치 시 cleanup 필수

---

**작성자:** Claude Code (PR #133 작업 세션, 2026-05-12 ~ 2026-05-13)
**검토 필요:** 사용자 본인 PC 에서 6.3 검증 후 머지 결정
