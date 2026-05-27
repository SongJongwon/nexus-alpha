# 🏢 Nexus Alpha

자기 진화형 소프트웨어 공장 — *"한 마디 요청 → .exe 완성품"*

> **상태 (2026-05-27)**:
> ✅ **v4 비전** (자연어 → .exe) 완료 — 외부 PC 2대 검증 (Calculator.exe / Message_App.exe)
> ✅ **Sprint 4/5/6 완료** — Telemetry foundation + Tauri 데스크탑 앱 + 11 본부 UI 개편
> ✅ **GUI 앱 자동 .exe 풀체인** (PR #210/#211) — AST 기반 sandbox SKIP + windowed 자동
> ⭐ **v8 (Boardroom 기반 자기 진화 SW) 진행 중** — [조직도 v13](docs/architecture/Nexus_Alpha_조직도_v13.md) / [구성안 v8](docs/architecture/Nexus_Alpha_구성안_v8.md)
> 📊 **누적 머지 PR 214+ 건 / pytest 1440 PASS (회귀 0)**

## 🚀 빠른 시작 (Windows)

> ⚠️ **Python 3.13 필수** — CrewAI 1.14.x 가 Python 3.14 미지원.

### A. 자동 설치 (Python 3.13 환경 한정)

```powershell
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex
```

설치 후:

```powershell
cd $HOME\nexus-alpha
.\.venv\Scripts\python.exe scripts\run.py --request "계산기 만들어줘"
```

### B. 수동 설치 (Python 3.14+ 환경)

```powershell
winget install --id Python.Python.3.13 -e
git clone https://github.com/SongJongwon/nexus-alpha.git $HOME\nexus-alpha
cd $HOME\nexus-alpha
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python scripts\run.py --request "계산기 만들어줘"
```

### C. Tauri 데스크탑 앱 (Sprint 5/6 완료, Boardroom UI)

```powershell
cd C:\projects\nexus-alpha\src-tauri
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
cargo tauri dev
```

→ 윈도우 자동 open + 11 본부 grid + Telemetry stream + 자연어 입력창 + .exe 자동 빌드 + 실행 버튼.

## 🎯 비전 진화 — v4 (완료) → v5 → ⭐ **v8** (진행 중)

### v4 — 산출물 자동화 ✅

> 사용자가 **"계산기 만들어줘"** 라고 말하면, Nexus Alpha 가 알아서
> GUI 를 디자인하고, 코드를 작성하고, `.exe` 로 빌드하고, 설치 관리자로 패키징하고,
> 다운로드 가능한 형태로 **배포까지 자동 완료** 한다.

→ **2026-05-14 외부 PC 2대 검증 완료** (Calculator.exe / Message_App.exe).
→ **2026-05-27 GUI 앱 풀체인 자동화** (PR #210/#211) — Tkinter mainloop sandbox 사고 처방 + `--windowed` 자동 적용.

자세한 v4 설계: [docs/architecture/nexus_alpha_v4.md](docs/architecture/nexus_alpha_v4.md)

### v5 — 협업 자동화 (Sprint 1~3 완료, Phase 1 Foundation 일부 적용)

> v4 = "자연어 → .exe" (산출물 자동화)
> **v5 = "AI 가상 기업이 *진짜로 협업해서* 산출물 자동화" (협업 자동화)**

PR #133 의 환율 변환기 사례 — 4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함 (1 USD = 1365.5 stale). 진짜 회사 같은 회의/회고/학습 메커니즘 필요.

- **Phase 1 (구현 ✅)**: Shared Context Pool + Meeting Facilitator (PR #138)
- Phase 2 (미구현): Cross-Agent Consultant + CrewAI delegation 부분 ON
- Phase 3 (일부 ✅): Knowledge Curator + RAG + Retrospective Lead
- Phase 4 (Sprint 5/6 완료 ✅): Tauri 실시간 대시보드 + UI 개편

### ⭐ v8 — 자율 진화 (진행 중, v13 조직도 기반)

> v5 까지 = *인간 요구사항을 받아 처리* 하는 수동형
> **v8 = "시스템이 *스스로 문제 감지 → 부서 대표 토론 → 자율 개선안 도출* 하는 Boardroom 자기 진화 SW"**

#### 자율 진화 루프

```
[Telemetry 감지 — 본부 9 RV ★]
     ↓
[안건 발제 — System Refactoring Strategist (본부 1)]
     ↓
[전략 이사회 — Boardroom Facilitator 의장 (본부 10)]
     ↓
[조율 — Goal Alignment Agent + Token Budget Optimizer (본부 0)]
     ↓
[자율 배포 — Build & Release (본부 8)]
```

#### v13 Phase 1~5 우선순위 로드맵

| Phase | 작업 | 책임 본부 | 우선순위 |
|-------|------|----------|----------|
| **Phase 1 ★** | **본부 9 RV 4명 구현** (Exe Runtime Tester / UI Automation Specialist / Runtime Failure Analyzer / Auto-Fix Coordinator) | 본부 9 | **최우선** — Telemetry 자율 인지 인프라 |
| Phase 2 | **System Refactoring Strategist** 구현 | 본부 1 | 이사회 안건 자율 발제 엔진 |
| Phase 3 | **4 핵심 노드 백엔드 wire** (`runtime_verify` / `boardroom_trigger` / `goal_alignment_check` / `budget_brake`) | 백엔드 workflow | 자율 진화 루프 작동 |
| Phase 4 | **Goal Alignment Agent + Token Budget Optimizer** 구현 | 본부 0 | 이사회 거버넌스 + 자원 브레이크 의결권 |
| Phase 5 | 나머지 6명 + **UI 이사회 토론 시각화 panel** | 다부서 + frontend | 52/52 완성 |

자세한 v8 / v13 설계:
- [docs/architecture/Nexus_Alpha_조직도_v13.md](docs/architecture/Nexus_Alpha_조직도_v13.md) — 단일 진실 공급원
- [docs/architecture/Nexus_Alpha_구성안_v8.md](docs/architecture/Nexus_Alpha_구성안_v8.md) — v8 패러다임
- [docs/architecture/system_architecture.md](docs/architecture/system_architecture.md) — 3 계층 + v13 신규 노드
- [docs/architecture/phase_progress.md](docs/architecture/phase_progress.md) — Phase 1~5 타임라인
- [docs/insights/agent_collaboration_paradigm_shift.md](docs/insights/agent_collaboration_paradigm_shift.md) — 6 통찰 north star
- [docs/WORK_STATUS.md](docs/WORK_STATUS.md) — v13 Gap Analysis + Phase DoD + 의존성 그래프

## 📖 프로젝트 개요

Nexus Alpha 는 사용자의 반복 업무 또는 소프트웨어 요구를 분석하여 자동화 스크립트 · 앱 · 배포 가능한 실행 파일을 생성하는 **AI 가상 기업 시스템** 입니다.

### 조직 구조 (v13 — Boardroom 기반 자기 진화, 2026-05-27)

**경영진(Board) + 10 개 본부 = 11 개 조직 단위, 총 52 명 에이전트** — **39 구현 (75%) / 13 미구현 (25%)**

> v4 (46명) → v10 (50명, RV +4) → v11 (54명, Coordination +4) → **v13 (52명, 정원 다이어트 -2)**
> v13 의 다이어트: BPA / UCS / Project Coordinator 삭제 + System Refactoring Strategist 신설

| 본부 | 정원 | 구현 | 핵심 역할 (v13) |
|------|------|------|-----------------|
| **0 C-Level** | 3 | 1 | **CTO** ✅ + **Goal Alignment Agent** 🔒 (이사회 의장) + **Token Budget Optimizer** 🔒 (기술재무관) + Convergence Judge ✅ (보조, 본부 4 도구) |
| **1 업무 분석** | 4 | 3 | Requirement Expander ✅, Gap Analyst ✅, Data Analyst ✅, **System Refactoring Strategist** 🔒 (이사회 안건 자율 발제) |
| **2 기획 및 설계** | 2 | 1 | UI/UX Analyst ✅, Product Manager 🔒 |
| **3 개발** | 8 | 6 | Python Engineer ✅ + Web/API/Data/Desktop/DevOps Specialists ✅ + Mobile 🔒 + Embedded 🔒 |
| **4 품질 검증** ✅ | 10 | 10 | 9 QA agents + Convergence Judge (100%) |
| **5 지식 관리** | 3 | 2 | Knowledge Curator ✅, RAG Searcher ✅, Documentation Lead 🔒 |
| **6 운영 지원** | 2 | 1 | Sandbox Runner ✅, Monitoring Engineer 🔒 |
| **7 디자인** ✅ | 3 | 3 | GUI Code Generator + GUI Designer + Theme Designer (100%) |
| **8 빌드 & 배포** ✅ | 9 | 9 | Build Engineer + 8 release agents (100%) |
| **★ 9 Runtime Verification** | 4 | 0 | **Phase 1 최우선 구현 예정** ★ — Exe Runtime Tester / UI Automation / Failure Analyzer / Auto-Fix Coordinator |
| **10 Coordination** | 4 | 3 | **Boardroom Facilitator** ✅ (구 Meeting Facilitator — *전략 이사회 의장 격상*) + Retrospective Lead ✅ + Knowledge Curator (promoted) ✅ + Cross-Agent Consultant 🔒 |
| **합계** | **52** | **39** | **75%** |

자세한 본부별 명단: [docs/architecture/Nexus_Alpha_조직도_v13.md](docs/architecture/Nexus_Alpha_조직도_v13.md)

## 🛠️ 기술 스택

### 백엔드
- **언어**: Python 3.13 (3.14 미지원 — CrewAI 1.14.x 의 `requires_python = ">=3.10,<3.14"` 제약)
- **오케스트레이션**: CrewAI `>=1.14.1,<1.15.0` (Process.sequential) + LangGraph 1.x
- **LLM 연동**: Claude Agent SDK (MAX 구독) / Anthropic API Key / **Claude Code CLI (`--force-cli`)**
- **모니터링**: LangFuse Cloud v4 + 자체 Telemetry (PR #188 — events.jsonl)
- **테스트**: pytest 9 (1440 PASS / 회귀 0)
- **검증**: Pydantic v2

### 데스크탑 앱 (Sprint 5/6 완료)
- **Shell**: Tauri 2.x (Rust 1.75+) — ~10 MB .exe
- **UI**: React 19 + TypeScript 6 + Tailwind v4 + Vite 8
- **Telemetry stream**: Python sidecar → JSON Lines → Rust tail → React state
- **Authentication**: Claude Code CLI integration (auth status/login/logout)

## ✨ 주요 기능

- 🔄 **LLM Provider 추상화** — MAX 구독 ↔ API Key ↔ Claude Code CLI 자유 전환
- 🏗️ **자기 진화 cycle** (LangGraph) — recall → kickoff → chain → sandbox → gap → judge → retrospective → curate
- 🛡️ **GUI 앱 자동 .exe 풀체인** — AST 기반 sandbox SKIP + PyInstaller `--windowed` 자동 + smoke test
- 🎨 **Tauri 데스크탑 앱** — 11 본부 grid + 실시간 Telemetry stream + 부서 펄스 + .exe 실행 버튼
- 📊 **Telemetry foundation** — 4 event type (agent_status / agent_message / iteration_progress / result)
- 🏛️ **(v8 진행 중)** Boardroom 자율 진화 루프 — Phase 1~5 로드맵

## 📂 프로젝트 구조

```
nexus-alpha/
├── README.md                    # 본 문서
├── install.ps1                  # irm 한 줄 설치 스크립트
├── scripts/run.py               # CLI 진입점 (--request 자연어)
├── requirements.txt
├── .env.example
│
├── src/                         # 백엔드 (Python)
│   ├── agents/                  # 본부별 에이전트 (39 구현)
│   │   ├── c_level/             #   본부 0: CTO + Convergence Judge
│   │   ├── analysis/            #   본부 1: Requirement Expander, Gap Analyst, Data Analyst
│   │   ├── planning/            #   본부 2: UI/UX Analyst
│   │   ├── engineering/         #   본부 3: Python Engineer + 5 도메인 Specialist
│   │   ├── qa/                  #   본부 4: 9 QA agents (100% ✅)
│   │   ├── knowledge/           #   본부 5: Curator + RAG Searcher
│   │   ├── operations/          #   본부 6: Sandbox Runner
│   │   ├── design/              #   본부 7: GUI Code Gen + Designer + Theme (100% ✅)
│   │   ├── build_release/       #   본부 8: 9 build/release agents (100% ✅)
│   │   └── coordination/        #   본부 10: Boardroom Facilitator + Retrospective Lead
│   ├── workflows/               # iterative_loop + build_workflow + ...
│   ├── monitoring/              # telemetry.py (Sprint 4)
│   ├── llm/                     # Provider 추상화
│   └── tests/                   # pytest 1440 PASS
│
├── src-tauri/                   # Rust shell (Sprint 5/6)
│   ├── Cargo.toml
│   ├── src/lib.rs               # claude_auth_* + start_run + open_exe commands
│   ├── tauri.conf.json
│   └── capabilities/default.json
│
├── frontend/                    # React + Tailwind (Sprint 6)
│   ├── package.json
│   ├── vite.config.ts
│   └── src/App.tsx              # 11 본부 grid + Telemetry stream
│
├── docs/
│   ├── WORK_STATUS.md           # v13 Gap Analysis + Phase 1~5 + Mermaid
│   ├── architecture/
│   │   ├── Nexus_Alpha_조직도_v13.md    # ⭐ 단일 진실 공급원
│   │   ├── Nexus_Alpha_구성안_v8.md      # v8 패러다임 (Boardroom)
│   │   ├── system_architecture.md       # 3 계층 + v13 신규 노드
│   │   ├── phase_progress.md            # Phase 1~5 타임라인
│   │   └── agent_org_chart.md           # 본부 ↔ Tauri UI 매핑
│   ├── insights/
│   │   ├── agent_collaboration_paradigm_shift.md  # 6 통찰 north star
│   │   └── desktop_app_vision.md                  # Sprint 5/6 비전 (완료)
│   └── progress/                # session_log_<date>.md
│
├── outputs/                     # 산출물 (alpha_run_<timestamp>/) — gitignored
└── logs/                        # 실행 로그 — gitignored
```

## 📊 진행 현황 (2026-05-27 기준)

### v4 — 완료 ✅

- ✅ **Phase 0~3**: 기반 + MVP + Sandbox 완료
- ✅ **Phase 4 (GUI 자동 생성)**: GUI Code Generator + Theme Designer 구현 (본부 7 100%)
- ✅ **Phase 4.5 (빌드 & 패키징)**: Build Engineer + PyInstaller 자동 통합 (본부 8 100%)
- ✅ **Phase 5 (배포 자동화)**: Distribution Agent + gh release 자동화

### Sprint 1~6 (Tauri 데스크탑 앱) — 완료 ✅

- ✅ **Sprint 1~3**: v5 협업 자동화 Foundation (Meeting Facilitator + RAG + Retrospective)
- ✅ **Sprint 4**: Telemetry foundation (PR #188 — events.jsonl + 4 event type emit)
- ✅ **Sprint 5**: Tauri shell + React + Python sidecar (PR #195~#197)
- ✅ **Sprint 6**: UI 개편 — 11 본부 grid + 통계바 + 부서 필터 + 280px 패널 + ACTIVE 펄스 (PR #206~#208)
- ✅ **GUI 자동 .exe 풀체인** (PR #210/#211): AST 기반 sandbox SKIP + `--windowed` 자동 + smoke test

### v13 Phase 1~5 (Boardroom 자율 진화) — 예정

- 🔜 **★ Phase 1 (최우선, ETA 2026-06)**: **본부 9 RV 4 agent 구현** — Telemetry 자율 인지 인프라
- 🔜 Phase 2: System Refactoring Strategist (이사회 안건 자율 발제)
- 🔜 Phase 3: 4 핵심 노드 백엔드 wire (runtime_verify / boardroom_trigger / goal_alignment_check / budget_brake)
- 🔜 Phase 4: Goal Alignment Agent + Token Budget Optimizer (이사회 의결권 활성화)
- 🔜 Phase 5: 나머지 6명 + UI 이사회 토론 시각화 panel (52/52 100%)

**구현률**: **52명 중 39명 구현 (75%)**

자세한 Phase DoD + 의존성 그래프: [docs/WORK_STATUS.md](docs/WORK_STATUS.md)

## 🧪 테스트 실행

```bash
# 백엔드 pytest 전체 (~40초, 1440 PASS)
.venv/Scripts/pytest.exe src/tests/

# Frontend Vite build (~150ms)
cd frontend && npm run build

# Rust Tauri shell build (~10초 incremental)
cd src-tauri && cargo check

# E2E — Tauri 윈도우 실행
cd src-tauri && cargo tauri dev
```

## 📝 라이선스

Private Project — All Rights Reserved

---

## 📚 Legacy Reference (구버전)

> 본 섹션은 *과거 참조용*. 모든 *현재 진실* 은 위의 v13 / v8 섹션 참조.

### v4 확정안 (2026-04 시점, 46명 체제)

| 본부 | 인원 | 비고 |
|------|------|------|
| C-Level | 3 | CEO · CTO · Convergence Judge — *v13 에서 CEO/CFO → Goal Alignment / Token Budget* |
| 업무 분석 | 5 | *v13 에서 4명 (BPA + UCS 삭제, System Refactoring Strategist 신설)* |
| 기획 및 설계 | 4 | *v13 에서 2명 (Project Coordinator 삭제)* |
| 개발 | 9 | *v13 에서 8명 (다이어트)* |
| 품질 검증 | 6 | *v13 에서 10명 (Convergence Judge 포함, 100% 완성)* |
| 지식 관리 | 3 | *v13 동일 (3명)* |
| 운영 지원 | 4 | *v13 에서 2명 (다이어트)* |
| 디자인 (Phase 4) | 3 | *v13 동일 (3명, 100%)* |
| 빌드 & 배포 (Phase 4.5/5) | 9 | *v13 동일 (9명, 100%)* |
| (v10 신설) RV | — | *v13 = 4명 (Phase 1 최우선)* |
| (v11 신설) Coordination | — | *v13 = 4명 (Boardroom 의장 본부)* |

→ 현재 정원 **52명** (v4 의 46 → v13 의 52). 자세한 변천: [phase_progress.md](docs/architecture/phase_progress.md) 의 변경 이력.
