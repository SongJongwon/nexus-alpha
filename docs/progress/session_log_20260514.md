# 📝 세션 로그 — 2026-05-14 (PR #134-A 머지 + 친구 PC 첫 .exe 라이브 빌드 성공)

> 본 세션은 PR #133 머지 직후 친구 PC 베타 테스트에서 발견된 install.ps1 결함을
> 추측 기반 자동 복구가 아닌 *진단 보강* 으로 해결 (PR #134-A) → 친구 PC 라이브
> 재검증에서 install + .exe 빌드 풀체인 모두 성공 → Nexus Alpha 베타 배포 *작성자
> PC 외부* 첫 입증.

## TL;DR

- **PR #134-A 머지** (squash `76f96db`) — install.ps1 진단 보강 (자동 복구 0)
- **pytest 937 → 972 passed** (+35, 회귀 0)
- **친구 PC 라이브 빌드 성공** — `Message_App.exe` 9.86 MB / 33.11 min / GUI 정상 동작
- **추측 기반 처방 회피** — 친구 1명 PC 케이스로 처방 굳히지 않고 환경 비종속 진단 인프라 구축

## 세션 흐름

### Phase 1 — 친구 PC 1차 시도 결함 보고 (사용자)

PR #133 머지 (commit `0060bd9`, 2026-05-14 새벽) 직후 친구 PC 첫 베타 시도. PowerShell 출력:

```
✓ Python 3.13.7 다운로드 완료 (~25 MB)
✓ Orphan MSI registry uninstall (1603 fallback 으로 수동 정리 성공)
✓ Add/Remove Programs entry 정리 (8개)
✓ Windows Installer Products 정리 (8개)
✓ HKLM UserData entry 정리 (6개)
✓ Orphan 정리 완료 (21 항목 처리됨)
✓ Python 3.13.7 로컬 설치 진행 (~30초)
✗ 설치 실패: 로컬 Python 설치 완료했으나 tkinter import 실패:
  python.exe = C:\Users\work\nexus-alpha\python313\python.exe
  output =
  exit = 1
원인: 인스톨러가 Tcl/Tk 컴포넌트 미포함 (Include_tcltk=1 무시됨)
```

사용자 가설: silent install 자체는 성공했으나 `Include_tcltk=1` 플래그가 무시됨. 3단계 자동 복구 PR #134 제안 (alternative options → force redownload → repair mode → manual guide + error ID).

### Phase 2 — 진단 우선 결정 (Claude 검토)

코드 검토 후 사용자 가설에 *반대* 의견 제시:

1. [install.ps1:538](../../install.ps1#L538) 에 이미 `Include_tcltk=1` 명시되어 있음
2. [install.ps1:685-686](../../install.ps1#L685-L686) 의 안내문구는 *가설 한 가지를 사용자 친화적으로 적은 것* — 확정된 원인 X
3. 친구 PC 출력의 `output = / exit = 1` 에서 **stderr 가 안 보임** — 정상이라면 stderr 에 `ModuleNotFoundError` 가 떠야 함
4. [feedback_n_failure_diagnosis](C:\Users\woker\.claude\projects\c--projects-nexus-alpha\memory\feedback_n_failure_diagnosis.md) 룰: 1대 PC 1회 실패는 결정적 결함 단정 전 단계

**핵심 발견**: [install.ps1:83](../../install.ps1#L83) 의 PR #126 EAP 격리가 *stderr 폐기* (`2>$null`) 로 잘못 구현 — 친구 PC 의 빈 `output =` 은 정확히 이 결함의 결과.

**선택지 4 중 사용자 결정**: "진단 우선 (PR #134-A → B 분리)" — 친구 PC 1대 데이터로 처방 굳히지 않고 진단 보강만 먼저.

### Phase 3 — PR #134-A 작성 (commit 1: 진단 기본)

브랜치: `pr-134-a-tkinter-diagnostic-boost`

| 항목 | 변경 |
|------|------|
| `Invoke-NativeSafely` | `2>$stderrFile` (file-handle 레벨 redirect) → NativeCommandError 미발생 보장 유지 + stderr 캡처. `StdErr` 필드 추가, 기존 200+ caller 영향 0 |
| `Get-TkinterDiagnostics` 신규 | tkinter 검증 실패 시 6 섹션 dump — [1] tkinter import StdOut/**StdErr**/Exit, [2] `_tkinter` C ext 직접 import, [3] sys.path/prefix, [4] 파일 probe (DLLs/_tkinter.pyd, tcl86t.dll, tk86t.dll, Lib/tkinter, tcl/), [5] silent install 명령 echo, [6] 인스톨러 로그 마지막 200 줄 |
| silent install 명령 echo | 1차 + retry 양쪽에서 `Start-Process` 직전 화면 + `$script:LAST_INSTALL_CMD` 저장 |
| tkinter Fail 메시지 | 단정 안내 ("Include_tcltk=1 무시됨") 제거 → 진단 [4] ✗ 보고 사용자 판단 유도 |

신규 15 tests. 기존 PR #126 EAP 회귀 테스트 regex 1개 갱신 (nested cleanup `if` 수용).

전체 952 passed.

### Phase 4 — 사용자 추가 요구 → 환경 비종속 보강 (commit 2)

사용자가 작업 진행 중 추가 요구: "친구 1명 PC 환경에 맞춘 처방은 다른 9명에서 또 다른 결함 → fixup 무한 루프. 진단 단계에서 PC 환경 *전체* 분류해야 PR #134-B 가 환경 분기 처방 가능."

5 카테고리 환경 정보 + 에러 ID 분류 + JSON 누적 인프라 구축:

| helper | 역할 |
|--------|------|
| `Get-EnvironmentContext` | Python 4 source 전수 (`py -0p` / `where python` / `Get-Command -All` / Registry HKLM+HKCU+Wow6432Node) + Tcl/Tk 충돌 (PATH / 다른 Python `_tkinter.pyd` / 시스템 DLL) + PC ctx (OS / PS / IsAdmin / DomainJoined) + AV (`Get-MpPreference` / SecurityCenter2 `AntiVirusProduct` / 서비스 패턴 — 한국 v3/ahnlab + 글로벌) + 인스톨러 SHA256. **모든 query try/catch 격리** → 단일 query 실패가 진단 전체 abort 시키지 않음 |
| `Get-TkinterErrorIds` | TKINTER-001 (옵션 무시) / 002 (DLL 의존성) / 003 (AV 격리) / 004 (회사 정책) / 005 (다중 Python 충돌) / 000 (fallthrough). **단정 회피**: 복합 신호 매칭 (AV + partialMissing 동시, 다중 Python + PYTHONHOME 동시 등) |
| `ConvertTo-DiagnosticJson` | schema-versioned (`nexus-alpha-tkinter-diagnostic-v1`), `BEGIN_DIAGNOSTIC_JSON` / `END_DIAGNOSTIC_JSON` 마커, ConvertTo-Json 실패 시 fallback (caller crash 회피) |
| `Get-TkinterDiagnostics` 확장 | 섹션 [7] PC ctx, [8] Python 전수, [9] Tcl/Tk 충돌, [10] AV, [11] 인스톨러 SHA256, [12] 자동 분류 ID, [13] JSON dump |

신규 +20 tests (총 35). 기존 PR #112 `.venv` skip 회귀 테스트 anchor 갱신 (`Get-EnvironmentContext` 의 `Get-Command python` 진단 호출이 `Test-Prereqs` 의 시스템 체크보다 앞에 등장 → anchor 를 Test-Prereqs 본문 시작 이후로 격리).

전체 972 passed.

### Phase 5 — 친구 PC 2차 시도 (PR #134-A 머지 전 라이브 검증)

```
$env:NEXUS_ALPHA_BRANCH='pr-134-a-tkinter-diagnostic-boost'
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/pr-134-a-tkinter-diagnostic-boost/install.ps1 | iex
```

**install.ps1 정상 완주** — 이전 tkinter 결함 *재현 안 됨*. PR #134-A 의 진단 dump 트리거 X. 친구가 자발적으로 `scripts/run.py` 실행 → 자연어 요청 입력 단계 도달.

**가설**: 이전 친구 PC 시도의 부분 설치 잔재를 PR #133 의 orphan cleanup + retry 로직이 정리 → fresh install 성공. PR #134-A 의 진단 보강은 미래 보험으로 retain.

### Phase 6 — 친구 PC .exe 빌드 라이브

| 항목 | 결과 |
|------|------|
| 요청 | "입력한 메세지에 따라 선택한 유형으로 시스템메세지 뜨게 하는 프로그램 만들어줘" |
| 자동 라우팅 | Track A (Calculator-style GUI/CLI) — 정확 |
| 빌드 시간 | **33.11 min** (LLM retry 포함, 가이드 20~25분 대비 약간 길지만 정상 범위) |
| `.exe` | `C:\Users\work\nexus-alpha\outputs\alpha_run_20260514_132348\workflow_20260514_132353\build_output\dist\Message_App.exe` / **9.86 MB** |
| GUI 동작 | ✅ "메시지 박스 데모" — 메시지 본문 입력 + info/warning/error/question 라디오 + "메시지 보기 (Enter)" 버튼 → 시스템 MessageBox 정상 |
| 자동 복구 작동 | `[converter rescue capture]` (Issue #6 패턴) + `retry_task_if_short` (backstory 결함) 모두 정상 |
| PR #133 fixup #14 (정적 attribute 검증) | false positive 0 (정상 GUI 차단 안 함) |

**Nexus Alpha 베타 배포 *작성자 PC 외부* 첫 .exe 풀체인 입증.**

### Phase 7 — PR #134-A 머지

`gh pr merge 134 --squash --delete-branch` → squash commit `76f96db`. CI ubuntu/py3.13 SUCCESS. main pull + 로컬 브랜치 정리.

## 핵심 교훈 / 갱신할 메모리

1. **추측 기반 처방 회피 룰** ([feedback_n_failure_diagnosis](C:\Users\woker\.claude\projects\c--projects-nexus-alpha\memory\feedback_n_failure_diagnosis.md) 의 확장 적용):
   - 1대 PC 1회 실패는 *결정적 결함 단정 전 단계* — 진단 데이터 0 인 상태로 자동 복구 설계 시 fixup 무한 루프 위험
   - PR #134-A 가 정확히 이 룰 적용 → 진단 보강만 먼저, 자동 복구 0
2. **친구 PC 환경 (한 데이터 포인트)**:
   - 회사 PC 추정 (사용자명 `work`)
   - Windows 10/11 (정확히 미확인)
   - 이전 시도의 21개 orphan registry 가 PR #133 의 cleanup 로직으로 정리 → 2차 시도 fresh install 성공
3. **진단 인프라 재사용 가능**:
   - tkinter / native command 진단이 또 필요하면 PR #134-A 의 helper 패턴 (`Get-TkinterDiagnostics` / `Get-EnvironmentContext` / `Get-TkinterErrorIds` / `ConvertTo-DiagnosticJson`) 재사용 가능
   - JSON schema (`nexus-alpha-tkinter-diagnostic-v1`) 가 다중 PC 누적용 → 베타 사용자 dump 모이면 패턴 자동 분석 가능

## 식별된 후속 작업 (갱신)

- **PR #134-B (보류)**: 친구 PC + 추가 베타 PC 의 진단 dump 누적 후 환경 분기 처방 설계. 1대 성공으로 보류, TKINTER-001~005 중 실제 분류된 ID 가 나오면 그때 진행.
- **PR #135**: 좀비 프로세스 cleanup (Flet Flutter daemon 등 Windows subprocess 잔존) + LangFuse traces 401 graceful fallback + langgraph cache deprecation 명시.
- **PR #136**: README 알려진 한계 명시 + 베타 배포 가이드 (사용자 매뉴얼) — 친구 PC 첫 빌드 데이터 (33min, Message_App.exe 9.86 MB) 를 가이드에 포함.

## 통계

| 지표 | 값 |
|------|-----|
| 머지된 PR | 133 → **136** (+3 squash: #134-A `76f96db`, #135 `b645bb1`, #137/GH#136 `6aa07ca`) |
| pytest 통과 | 937 → **992** (+55, 회귀 0) |
| 신규 helper | 4 (`Invoke-NativeSafely` 보강 + `Get-TkinterDiagnostics` / `Get-EnvironmentContext` / `Get-TkinterErrorIds` / `ConvertTo-DiagnosticJson`) |
| 진단 dump 섹션 | 13 |
| 자동 분류 에러 ID | 5 + fallthrough |
| 친구 PC 라이브 검증 | 2회 (1차 install fail → 2차 install + 빌드 성공) |
| 외부 PC `.exe` 빌드 첫 입증 | ✅ Message_App.exe 9.86 MB / 33.11 min |
| 종합 점검 영역 | 11 (A~K) — 3 에이전트 병렬 |
| 식별된 새 PR 후보 | 8개 (#136 README / #138 input / #139 cost / #140 Knowledge / #141 Vision / #142 Win CI / #143 release / #144 telemetry) |

## Phase 8 — 종합 점검 (Project Health Check) + Sprint 1 일부

PR #134-A 머지 후 PM 의 직관 ("내가 찾지 못한 결함도 있을 수 있다") 검증 위해 11 영역
종합 점검 진행. 3 에이전트 병렬 (Product / Engineering / Ops) → evidence-based 평가.

### 핵심 발견 (3 에이전트 *독립적으로* 같은 패턴 발견 = 시스템적 결함)
1. **Build-but-Forget anti-pattern**: 5+ 모듈이 *구현 + 테스트 + production path 호출 X*.
   - `iterative_loop.py` (704 LOC, 자기 진화 엔진) — `scripts/run.py` 가 호출 X
   - `qa_feedback_loop.py` — Engineer ↔ QA 양방향 재시도, 호출 X
   - `gui_test_executor.py` (Vision API GUI 검증) — 호출 X
   - `knowledge/curator.py` + `rag_searcher.py` — cross-run 학습, 호출 X
   - PR #133 의 16 fixup = `qa_feedback_loop` 가 안 돌아서 PM 이 손으로 패치한 결과
2. **"자기 진화형" 비전 vs 실제**: 코드는 다 있으나 호출 0 → 실제는 *PM 진화형*
3. **CrewAI 협업 기능 모두 OFF**: `allow_delegation=False` 24/24 에이전트, `Process.sequential` 만, `memory=False`
4. **Telemetry 0**: 친구 PC 실패가 maintainer 에게 invisible — 다음 N명 베타 디버깅 blind 반복 위험
5. **빠른 ROI**: `max_tokens=1024` → `retry_task_if_short` 매 빌드 트리거 → 33min 의 ~25%, 비용 ~30% 낭비

### Sprint 1 일부 진행 (이번 세션, ~2시간)
- **PR #135** (`b645bb1`) — `max_tokens 1024 → 4096` + 회귀 테스트 2개
  - 효과: 33min → ~25min, 비용 ~30% 감소 추정
  - pytest 974 (972 → +2)
- **PR #137** (GitHub #136, `6aa07ca`) — Security baseline:
  - `.github/workflows/gitleaks.yml` (push/PR/weekly + fetch-depth=0)
  - `.github/dependabot.yml` (pip + github-actions weekly 월요일 09:00 KST)
  - `.github/workflows/codeql.yml` (python security-extended)
  - `docs/security/bfg_rotation_procedure.md` (BFG 7-step + 영향 평가 + force-push 경고)
  - 첫 CI 결과: gitleaks SUCCESS / CodeQL alert 0 / pytest SUCCESS
  - pytest 992 (974 → +18)

### Sprint 1 보류 (친구 베타 1주일 후)
- PR #136 README truth pass — 친구 베타 데이터 합쳐서
- PR #138 input hardening (prompt injection 방어)
- PR #139 token/cost meter (베타 cohort 결정 시점)

### Sprint 2 후보 (다음 2주, paradigm shift)
- **PR #140 Knowledge Curator + RAG Searcher 와이어링** ⭐⭐⭐ — Vision A + Self-Evolution I + UX B 동시 해결
- **PR #141 Vision QA wiring** ⭐⭐⭐ — `gui_test_executor` 를 `scripts/run.py --build` 후 자동 호출
- PR #142 CI Windows runner + install.ps1 lint
- PR #143 v0.x.x 태그 + release.yml + `NEXUS_ALPHA_REF` 지원
- PR #144 Telemetry fallback (LangFuse silent → local jsonl)

### 친구 후속 베타 메시지 발송 (사용자, 1주일 여유)
- 추천 요청 4개 (customtkinter / Flet / PyQt / dearpygui)
- TKINTER-001~005 진단 dump 캡처 안내
- 보너스: 주변 1-2명 추가 모집 (회사 PC + 다른 OS)

## BFG 실 실행 시점 (PM 결정 권장)
PR #137 은 자동화만, BFG 실 실행은 별도 시점. LOW risk (public key 라 write 권한 X).
- (a) Sprint 1 끝 — 깔끔
- (b) 친구 베타 1주일 후 — 안전
- (c) PR #134-B 와 묶음
- (d) 무기한 보류 — gitleaks 가 신규 leak 만 차단
