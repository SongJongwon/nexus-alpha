# 🏢 Nexus Alpha

자기 진화형 소프트웨어 공장 — *"한 마디 요청 → .exe 완성품"*

> **상태 (2026-05-14)**: v4 비전 (자연어 → .exe) ✅ 외부 PC 2대 검증 완료 (Calculator.exe + Message_App.exe). v5 비전 (진짜 multi-agent collaboration) 진행 중 — [docs/insights/agent_collaboration_paradigm_shift.md](docs/insights/agent_collaboration_paradigm_shift.md) 참조.

## 🚀 빠른 시작 (Windows)

> ⚠️ **Python 3.13 필수** — CrewAI 1.14.x 가 Python 3.14 미지원 (의존성 빌드 실패).
> 3.14 사용자는 [수동 설치](#b-수동-설치-모든-환경-python-314-포함) 사용.

### A. 자동 설치 (Python 3.13 환경 한정)

시스템 `python` 이 3.13.x 인 경우 PowerShell 한 줄:

```powershell
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex
```

설치 후 실행:

```powershell
cd $HOME\nexus-alpha
.\.venv\Scripts\python.exe scripts\run.py
# 또는 자연어 한 줄로
.\.venv\Scripts\python.exe scripts\run.py --request "계산기 만들어줘"
```

> 🛑 **현재 `irm` 방식은 시스템 `python` 이 3.13 인 경우에만 동작합니다.**
> Python 3.14+ 환경에선 Step 1/6 에서 차단되며 아래 수동 설치 안내가 출력됩니다.

### B. 수동 설치 (모든 환경, Python 3.14 포함)

Python 3.14 가 설치된 환경에서도 `py -3.13` launcher 로 3.13 전용 venv 를 만들어 우회.

1. **Python 3.13 설치**:
   ```powershell
   winget install --id Python.Python.3.13 -e
   ```
   또는 https://www.python.org/downloads/release/python-3137/ 직접 다운로드.

2. **저장소 받기**:
   ```powershell
   git clone https://github.com/SongJongwon/nexus-alpha.git $HOME\nexus-alpha
   ```

3. **가상환경 생성** — `py -3.13` 으로 3.13 명시:
   ```powershell
   py -3.13 -m venv $HOME\nexus-alpha\.venv
   ```

4. **의존성 설치**:
   ```powershell
   cd $HOME\nexus-alpha
   .\.venv\Scripts\pip install -r requirements.txt
   ```

5. **실행**:
   ```powershell
   .\.venv\Scripts\python scripts\run.py
   # 또는 자연어 한 줄로
   .\.venv\Scripts\python scripts\run.py --request "계산기 만들어줘"
   ```

배포 로드맵: **Alpha (install.ps1)** → Beta (Streamlit) → Release (Electron/Tauri).
자세한 비전: [docs/context/next_session_context.md §10](docs/context/next_session_context.md).

## 🎯 비전 — v4 (완료) → v5 (진행 중)

### v4 — 산출물 자동화 ✅
> 사용자가 **"계산기 만들어줘"** 라고 말하면, Nexus Alpha가 알아서
> GUI를 디자인하고, 코드를 작성하고, `.exe`로 빌드하고, 설치 관리자로 패키징하고,
> 다운로드 가능한 형태로 **배포까지 자동 완료**한다.

→ **2026-05-14 외부 PC 2대 검증 완료** (Calculator.exe / Message_App.exe).
자세한 v4 설계: [docs/architecture/nexus_alpha_v4.md](docs/architecture/nexus_alpha_v4.md)

### v5 ⭐ — 협업 자동화 (진행 중)
> v4 = "자연어 → .exe" (산출물 자동화)
> **v5 = "AI 가상 기업이 *진짜로 협업해서* 산출물 자동화" (협업 자동화)**

PR #133 의 환율 변환기 사례에서 발견 — 4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함 (1 USD = 1365.5 stale). 진짜 회사 같은 회의/회고/학습 메커니즘이 필요.

**v5 의 4 Phase 진화 경로** (Sprint 2 부터):
- Phase 1: Shared Context Pool + Meeting Facilitator 신설 (PR #138)
- Phase 2: Vision QA + CrewAI delegation 부분 ON (PR #141)
- Phase 3: Knowledge Curator + RAG + Retrospective Lead (PR #140)
- Phase 4: 실시간 대시보드 + Vision QA 확장 (PR #145)

자세한 v5 설계: [docs/architecture/Nexus_Alpha_구성안_v7.md](docs/architecture/Nexus_Alpha_구성안_v7.md) + [조직도 v11](docs/architecture/Nexus_Alpha_조직도_v11.md) + [insights](docs/insights/agent_collaboration_paradigm_shift.md)

## 📖 프로젝트 개요

Nexus Alpha는 사용자의 반복 업무 또는 소프트웨어 요구를 분석하여 자동화 스크립트·앱·
배포 가능한 실행 파일을 생성하는 **AI 가상 기업 시스템**입니다.

### 조직 구조 (v11 — 본부 10 신설 비전, 2026-05-14)

**C-Level 3명 + 10개 본부 = 11개 조직 단위, 총 54명 에이전트** (39 구현 / 15 비전)

> v4 의 46명 → v10 의 50명 (RV 본부 +4) → **v11 의 54명** (Coordination/Communication 본부 +4)
> 자세한 v11: [docs/architecture/Nexus_Alpha_조직도_v11.md](docs/architecture/Nexus_Alpha_조직도_v11.md)

**v4 확정안 (legacy reference)**: C-Level 3명 + 8개 본부 = 9개 조직 단위, 총 46명 에이전트

| 본부 | 인원 | 역할 |
|---|---:|---|
| C-Level | 3 | CEO · CTO · Convergence Judge |
| 업무 분석 | 5 | Data Analyst, Requirement Expander, Gap Analyst 등 |
| 기획 및 설계 | 4 | System Architect, UI/UX Analyst 등 |
| 개발 | 9 | Python · Backend · Frontend · Automation Engineer 등 |
| 품질 검증 | 6 | Code Reviewer, Test Engineer, Security Auditor 등 |
| 지식 관리 | 3 | Knowledge Curator, RAG Searcher, Decision Recorder |
| 운영 지원 | 4 | Sandbox Runner, Scheduler, Log Analyzer 등 |
| 🆕 디자인 (Phase 4) | 3 | GUI Designer, GUI Code Generator, Theme Designer |
| 🆕 빌드 & 배포 (Phase 4.5/5) | 9 | Build Engineer, Installer Creator, Distribution Agent 등 |

자세한 조직도: [docs/architecture/nexus_alpha_org_v4.md](docs/architecture/nexus_alpha_org_v4.md)

자율 반복 루프(자기 진화 엔진) 설계: [docs/architecture/nexus_alpha_v3.md](docs/architecture/nexus_alpha_v3.md)

## 🛠️ 기술 스택

- **언어**: Python 3.13 (3.14 미지원 — CrewAI 1.14.x 의 `requires_python = ">=3.10,<3.14"` 제약)
- **오케스트레이션**: CrewAI `>=1.14.1,<1.15.0` (Process.sequential) + LangGraph (v3 도입 예정)
- **LLM 연동**: Claude Agent SDK (MAX 구독) / Anthropic API Key
- **모니터링**: LangFuse Cloud v4 (OpenTelemetry 기반)
- **테스트**: pytest 9 + pytest-mock + pytest-socket (Linux opt-in)
- **데이터 처리**: Pandas, OpenPyXL
- **검증**: Pydantic
- **유틸**: Rich (콘솔 UI), PyYAML, python-dotenv

## ✨ 주요 기능

- 🔄 **LLM Provider 추상화** — MAX 구독 ↔ API Key 자유 전환 (`.env` 한 줄 변경)
- 🏗️ **Factory 패턴** 기반 확장성 — 새 Provider 추가 시 기존 에이전트 코드 무수정
- 📁 체계적인 프로젝트 구조 — 역할별 에이전트 디렉터리 분리
- 🌐 Cross-platform 지원 (Windows / macOS / Linux)

## 🛠️ 개발자 / 크로스플랫폼 상세 설치

> 위 "빠른 시작" 으로 안 되는 macOS/Linux 환경 또는 개발자용 상세 안내.

### 사전 준비

- **Python 3.13** (3.14+ 미지원 — CrewAI 1.14.x 의 `requires_python = ">=3.10,<3.14"` 제약)
- (선택) Claude Code 로그인 (MAX 구독 모드 사용 시)
- (선택) Anthropic API Key (`sk-ant-...`) — API Key 모드 사용 시

### 1) 저장소 클론

```bash
git clone https://github.com/SongJongwon/nexus-alpha.git
cd nexus-alpha
```

### 2) 가상환경 생성 및 활성화

Windows (bash):
```bash
py -3.13 -m venv .venv
source .venv/Scripts/activate
```

Windows (PowerShell):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:
```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 3) 의존성 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4) 환경변수 설정

`.env` 파일(루트)을 편집하세요.

```env
# MAX 구독 모드 (기본, 무료)
LLM_PROVIDER=agent_sdk

# API Key 모드로 전환하려면 아래 두 줄을 활성화
# LLM_PROVIDER=api_key
# ANTHROPIC_API_KEY=sk-ant-...
```

### 5) Hello Agent 테스트

```bash
.venv/Scripts/python.exe src/tests/hello_agent.py
# 또는 (macOS/Linux)
python src/tests/hello_agent.py
```

정상 동작 시 Provider 이름과 한국어 인사 응답이 출력됩니다.

## 📂 프로젝트 구조

```
nexus-alpha/
├── README.md                  # 본 문서
├── requirements.txt           # Python 의존성
├── .env                       # 환경변수 (Git 추적 제외)
├── .gitignore
├── src/
│   ├── agents/                # 역할별 에이전트 모듈
│   │   ├── c_level/           #   C-Level (경영 의사결정)
│   │   ├── analysis/          #   데이터 분석
│   │   ├── planning/          #   기획
│   │   ├── engineering/       #   구현/개발
│   │   ├── qa/                #   품질 보증
│   │   ├── knowledge/         #   지식 관리
│   │   └── operations/        #   운영
│   ├── llm/                   # LLM Provider 추상화
│   │   ├── base_provider.py   #   BaseLLMProvider (ABC)
│   │   ├── agent_sdk_provider.py  # Claude Code MAX 경로
│   │   ├── api_key_provider.py    # Anthropic API Key 경로
│   │   ├── factory.py         #   LLM_PROVIDER → Provider 인스턴스
│   │   └── README.md
│   ├── workflows/             # 에이전트 간 워크플로우 정의
│   ├── config/                # 공통 설정 파일
│   └── tests/                 # 통합/단위 테스트
│       └── hello_agent.py     #   Provider 시스템 smoke test
├── outputs/                   # 실행 산출물 (Git 추적 제외)
└── logs/                      # 실행 로그 (Git 추적 제외)
```

## 📊 진행 현황

- ✅ **Phase 0**: 기반 구축 완료 (2026-04-17)
- ✅ **Phase 1**: MVP 3명 에이전트 협업 워크플로우 완료 (CTO → Analyst → Engineer)
  - 보고서: [docs/progress/phase1_complete.md](docs/progress/phase1_complete.md)
- ✅ **Phase 2 우선순위 1**: pytest 하네스 정식화 완료 (`.venv/Scripts/pytest.exe` 한 명령으로 6 passed in ~8s, 네트워크 호출 0건)
  - 보고서: [docs/progress/phase2_priority1_complete.md](docs/progress/phase2_priority1_complete.md)
- 🟡 **Phase 2 우선순위 2** (다음): QA 에이전트 (Code Reviewer)
- 📐 **Phase 2.5 (v3)**: 자기 진화 엔진 — 설계 확정, 구현 대기
- ⬜ Phase 3: 실행 엔진 통합 (Sandbox 빌드·실행)
- 📐 **Phase 4 (v4)**: GUI 자동 생성 — 설계 확정
- 📐 **Phase 4.5 (v4)**: 빌드 & 패키징 — 설계 확정
- 📐 **Phase 5 (v4)**: 배포 자동화 — 설계 확정

진행률: **46명 풀 조직 중 4명 구현 완료 (~6.5%)**

## 🧪 테스트 실행

```bash
# (네트워크 없이) pytest 전체 — ~8초
.venv/Scripts/pytest.exe

# (실제 LLM 호출) 엔드투엔드 워크플로우 — 수 분
.venv/Scripts/python.exe src/tests/test_workflow_analyze_and_implement.py
```

## 📝 라이선스

Private Project — All Rights Reserved
