# 🏛️ Nexus Alpha 공식 조직도 v10 (PR #102~#118 — Alpha 진입점 완성 + Public 전환 + 외부 검증 성공 + RV 본부 신설 비전)

**개정일**: 2026-05-11 (세션 마무리, PR #119)
**최신 구조**: 경영진 + **9 개 본부** (RV 본부 신규), 총 **50 명 에이전트** (기존 46 + RV 4)
**현재 상태**: **39/50 명 구현 (78%)** + 3 개 본부 100% + 본부 3 (개발) 67% + Track A·B DoD 7/7 + **Alpha 진입점 완성** + 🌐 **repo PUBLIC** + 외부 PC 검증 성공

---

## 🚀 v9 → v10 핵심 변경사항

| 항목 | v9 (PR #97~#101) | **v10 (PR #102~#118)** |
|---|---|---|
| 누적 PR | 101 | **118** (+17) |
| pytest | 750 | **784** (+34, 회귀 0) |
| **Alpha 진입점** | (백엔드 풀체인만) | ✅ **install.ps1 + scripts/run.py** ⭐ |
| **저장소 가시성** | Private | 🌐 **PUBLIC** (5/11 전환 완료) |
| **외부 PC 검증** | 없음 | ✅ **다른 PC `irm` → Calculator.exe 10.73 MB** ⭐ |
| **알파 테스트 결함 발견** | 0 | 5 PR 차단 (#109, #110, #112, #114, #115, #117) |
| **차세대 QA 비전** | (스코프 외) | ⭐ **§11 RV — 4 신규 에이전트 + DoD 9/9** |
| **본부 수** | 8 개 (실무) | **9 개 (RV 신규)** ⭐ |
| **에이전트 정원** | 46 명 | **50 명** (RV 본부 4 추가) |
| 구현률 | 39/46 (85%) | **39/50 (78%)** (정원 확대) |

---

## 🌟 v10 의 4 대 마일스톤

### 1. Alpha 진입점 완성 (PR #102~#117, 16 PR)

| 영역 | PR | 산출 |
|---|---|---|
| **irm 한 줄 설치** | #102 | `install.ps1` (6-step: 사전검사 → clone → venv → .env → smoke → 완료) |
| **자연어 입력창** | #102, #115 | `scripts/run.py` (Track A/B 자동 라우팅, Build 별도 prompt) |
| **보안 정리** | #103 | LangFuse public key + 이메일 placeholder (Public 전환 전) |
| **.env 자동화** | #104 | `.env.example` template + 자동 복사 |
| **Python 호환성** | #105, #110, #112, #114, #117 | 3.10~3.13 허용 + 3.14 차단 + `py -3.13` fallback + winget 자동 설치 |
| **git 동기화 강건성** | #106, #107, #108 | `fetch + reset --hard` + 실패 시 `.broken.{ts}` 백업 + 자동 reclone |
| **NativeCommandError 차단** | #109 | Windows PS 5.1 `2>&1` 결함 fix |
| **README 안내** | #113 | A. 자동 설치 / B. 수동 설치 (5-step) |
| **dependency unpin** | #111 | crewai `>=1.14.1,<1.15.0` (1.14.4 검증) |
| **경로 일관성** | #116 | `$env:USERPROFILE` → `$HOME` |

### 2. 🌐 Public 전환 (5/11)

- repo visibility: Private → **PUBLIC**
- description: "업무 자동화/RPA 전문 AI 가상 기업 시스템 (CrewAI + LangGraph + Claude Agent SDK)"
- 사전 보안 정리: PR #103 (LangFuse key + 이메일 placeholder)

### 3. ✅ 외부 PC Alpha 테스트 성공

```powershell
# 다른 PC 에서 한 줄로
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex

# 결과
✓ git: 2.45+
✓ python: Python 3.13.13
✓ Clone + venv + 의존성 + smoke 완주
→ scripts/run.py → "계산기 만들어줘" → Calculator.exe (10.73 MB) ⭐
```

**의의**: Nexus Alpha v4 비전 (자연어 → `.exe`) 이 *개발 환경 외부* 에서 empirical 검증됨.

### 4. ⭐ §11 RV 비전 신설 (PR #118)

알파 테스트에서 발견된 5 결함 (PR #109/#110/#112/#114/#115/#117) 모두 *기존 QA 가 못 잡은* 결함 — 사용자 직접 보고로 발견. 차세대 QA 비전:

- **Runtime Verification (RV) 본부 신설** — 본부 9 (신규), 4 명
- **DoD 확장** 7 → 9 항목 (exe_runtime_passed + ui_test_passed)
- **Phase A/B/C 로드맵** — 후보 V (Phase A) 가 다음 1순위

---

## 📊 전체 조직 구성 (v10)

### 조직 단위 총 **10 개** (v9 의 9 개 → +1)
- **경영진 (C-Level)** — 1개 (1/3 구현, 33%)
- **실무 본부** — **9 개** (38/47 구현, 81%) ← RV 본부 신규 추가

### 에이전트 구현 현황 (v10, 5/11 세션 마무리)

| 구분 | 인수 | 비율 |
|---|---|---|
| 구현 완료 | **39 명** | **78%** |
| 미구현 | **11 명** | 22% |
| **총계** | **50 명** | **100%** |

### 100% 완성 본부 🎉 (v9 동일)
- ✅ **본부 7: 디자인** (3명, v5 부터)
- ✅ **본부 8: 빌드 & 배포** (9명 + 도구 3종, v6 부터)
- ✅ **본부 4: 품질 검증** (9명 + Convergence Judge + 도구 5종, v7 부터)

### 신규 본부 🆕
- 🆕 **본부 9: Runtime Verification (RV)** — 4 명 신규 (PR #118 §11 비전, 0/4 구현)

---

## 🆕 본부 9: Runtime Verification (RV) — **0/4 (0%)** ⭐ v10 신규

**책임**: 빌드된 `.exe` + UI 동작의 *실 사용자 환경 검증* — 기존 본부 4 (품질 검증) 의 코드-level 한계를 보완.

**현황**: 0/4 구현 (PR #118 §11 비전만 — 후보 V 가 Phase A 첫 구현)

### 4 명 신설 에이전트

| # | 직책 | 역할 | 주요 도구 | 구현 예정 PR |
|---|---|---|---|---|
| 1 | **Exe Runtime Tester** | 빌드 `.exe` sandbox 실행 — 시작 시간 / 종료코드 / stdout-stderr / 메모리 peak | subprocess + psutil + Windows Job Objects | **후보 V (Phase A)** ⭐⭐⭐ |
| 2 | **UI Automation Specialist** | 사용자 시나리오 자동 수행 (클릭/키입력/윈도우 detect) | PyAutoGUI (GUI) + Playwright (Electron-Tauri-web) + WinAppDriver (Win32) | Phase B (후속) |
| 3 | **Runtime Failure Analyzer** | `.exe` 실행 fail / UI test fail trace 분석 → actionable feedback | trace pattern + LLM (Pytest Author 패턴 재사용) | Phase C |
| 4 | **Auto-Fix Coordinator** | RV failure 라우팅 + 재빌드 trigger + iteration budget 관리 | `qa_feedback_loop` 패턴 확장 | Phase C |

### Phase 로드맵

| Phase | 작업 | PR 예상 | 후보 |
|---|---|---|---|
| **A** Foundation | Exe Runtime Tester + `runtime_verify_workflow.py` 단순 버전 + DoD 8 | 1~2 PR | **V** ⭐⭐⭐ (1순위) |
| **B** UI Automation | UI Specialist + 시나리오 DSL (자연어 → PyAutoGUI/Playwright 호출) | 2~3 PR | (Phase B 후보) |
| **C** Auto-Fix Loop | Failure Analyzer + Coordinator + DoD 9/9 통합 | 2~3 PR | (Phase C 후보) |

### 신규 의존성 (RV 본부)

```python
psutil>=5.9            # 프로세스 모니터링 (CPU/mem/exit) — 신규
pyautogui>=0.9         # native Windows GUI — 본부 3 Desktop Automation 공유
playwright>=1.40       # Electron/Tauri/web UI — 본부 3 Web Scraping 공유
# (선택) WinAppDriver — Win32 UI Automation
```

기존 본부 3 의존성 최대 재활용 — `psutil` 만 신규.

### DoD 확장 (RV 가 도입하는 신규 2 항목)

| # | 항목 | 검증 |
|---|---|---|
| 8 | **`exe_runtime_passed`** ⭐ | `.exe` exit_code=0 + stderr critical error 0 |
| 9 | **`ui_test_passed`** ⭐ | UI 시나리오 전체 PASS (예: 계산기 "1+1=" → "2") |

---

## 🏛️ 본부별 상세 (v10, 변경/유지)

### 본부 1: 업무 분석 (1/5, 20%, v8 동일)

### 본부 2: 기획 및 설계 (1/4, 25%, v8 동일)

### 본부 3: 개발 (6/9, 67%, v8 동일)
서브그룹 A (핵심 3) + 서브그룹 B (Phase 6 Track B 5) + 서브그룹 C (미구현 3, Phase 9 예정).

### 본부 4: 품질 검증 (9/9+1, 100%, v7 부터)
PR #100 + #101 directive 12·13 차 재사용 (Pytest Author + qa_feedback_loop 의 *workflow-level* 강화).

### 본부 5: 지식 관리 (2/3, 67%, v8 동일)
### 본부 6: 운영 지원 (1/4, 25%, v8 동일)
### 본부 7: 디자인 (3/3, 100%, v5 부터)
### 본부 8: 빌드 & 배포 (9/9 + 도구 3종, 100%, v6 부터)
PR #99 의 `scripts/run_dod_stability.py` — N-iter 반복 검증 인프라 (v9 부터).

### 🆕 본부 9: Runtime Verification (0/4, v10 신규)
(상기 §본부 9 섹션 참조)

### 신규 진입점 / 인프라 (v10)

| 도구 | PR | 역할 |
|---|---|---|
| `install.ps1` | #102, #104~#117 | irm 한 줄 설치 — 6-step (사전검사 → clone → venv → .env → smoke → 완료) |
| `scripts/run.py` | #102, #115 | 자연어 입력창 — Track A/B 자동 라우팅 + Build 별도 prompt |
| `.env.example` | #104 | placeholder template (실 시크릿 0건) |
| `scripts/run_dod_stability.py` | #99 | N-iter DoD 안정성 반복 검증 |

---

## 🆕 v10 의 핵심 학습 — 알파 테스트 5 결함 = QA 의 구조적 한계

| PR | 결함 | 기존 QA 가 못 잡은 이유 | RV 가 잡았을 방식 |
|---|---|---|---|
| #109 | PowerShell `NativeCommandError` (`2>&1 | Out-Null` → stderr 첫 줄에 스크립트 중단) | pytest 는 Python 만, PowerShell 실행 시점 결함 미커버 | Exe Runtime Tester 가 *install.ps1 자체를 sandbox 실행* |
| #110/#117 | Python 3.14 차단 + winget 자동 설치 | pytest 는 .venv 환경만, 외부 Python 버전 호환성 미커버 | Exe Runtime Tester 가 *다른 Python 버전 환경* 자동 회귀 |
| #112/#114 | `.venv` 검출 + `py -3.13` fallback | pytest 는 post-install 만, install *시점* 분기 미커버 | UI Automation 이 *.venv 유/무* 두 시나리오 dispatch |
| #115 | `run.py` 의 `b` 입력 → Track B (Build 와 혼동) | UX 결함 — code path 정상이라 pytest fail 안 됨 | UI Automation 이 *실 키 입력* 시뮬레이션 → 결과 검증 |
| #106/#107 | `git pull --ff-only` 실패 broken state | install 외부 의존 (git, network) 결함 | Exe Runtime Tester 가 *broken .git* 시나리오 자동 재현 |

→ **5/5 모두 사용자 직접 보고로 발견** — RV 가 있었으면 자동 차단 가능. *§11 RV 비전 필요성 empirical 입증*.

---

## 🗓️ 다음 단계 — v11 후보

| 시점 | 작업 | 인원 변화 | 비고 |
|---|---|---|---|
| **즉시** | ⭐ **후보 V — RV Phase A** (Exe Runtime Tester + DoD 8) | **+1 (39 → 40)** | RV 본부 첫 구현 ⭐⭐⭐ |
| 단기 | RV Phase B (UI Automation Specialist + 시나리오 DSL) | +1 (40 → 41) | Phase B 후보 |
| 단기 | 후보 R (PR #101 5-iter sweep) | 0 | 95%+ 안정성 측정 |
| 중기 | RV Phase C (Failure Analyzer + Auto-Fix Coordinator) | +2 (41 → 43) | Phase C 후보 |
| 중기 | 후보 U (Streamlit Beta UI) | 0 | 외부 인터페이스 |
| ⬜ Phase 8 | 2 명 (CEO/CFO) | 43 → 45 | C-Level 완성 |
| ⬜ Phase 9 | 5 명 (분석/계획/지식/운영/본부 3 나머지) | **45 → 50** | **전체 50/50 완성** |

---

## 📜 변경 이력

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v2.0 | 2026-04-17 | 6개 본부 + 경영진 |
| v3.0 | 2026-04-17 | 자율 반복 루프 4명 추가 |
| v4.0 | 2026-04-17 | 디자인 + 빌드&배포 본부 신설 → 8개 |
| v5.0 | 2026-04-20 | Phase 4 완료: 디자인 100% |
| v5.1 | 2026-04-20 | Phase 4.5+5 완료: 빌드&배포 100% |
| v6 | 2026-04-28 | PR #25-36: 외부 도구 통합 첫 성공 + 첫 .exe |
| v7 | 2026-04-28 | PR #42-#48: 본부 4 (품질 검증) 100% + 자동 QA 피드백 루프 |
| v8 | 2026-05-07 | PR #49-#76: Phase 6 Track B 5명 + Update Checker 풀체인 통합 + active 4/4 도달 |
| v9 | 2026-05-11 (PR #101) | PR #97-#101: Track B DoD 7/7 + 안정성 empirical 사이클 + 배포 비전 Electron/Tauri |
| **v10** | **2026-05-11 (PR #119, 세션 마무리)** | **PR #102-#118: Alpha 진입점 완성 (install.ps1 + run.py) + 🌐 Public 전환 + 외부 PC 검증 성공 (Calculator.exe 10.73 MB) + 🆕 RV 본부 신규 4 명 + §11 비전** ⭐⭐⭐ |

---

*본 조직도는 PR #119 (세션 마무리, 2026-05-11) 시점 기준. 39/50 (78%) 구현률 — v9 의 39/46 (85%) 대비 분모 확대 (RV 본부 4 명 신규).*
*v11 후보: 후보 V (RV Phase A) → Phase B/C → 후보 U (Streamlit Beta) → Phase 8/9 (50/50 완성).*
