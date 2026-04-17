# Nexus Alpha — 새 세션 인계용 컨텍스트

> **이 문서 한 장만 읽어도** 새 Claude Code 세션이 현재와 동일한 수준으로
> 작업을 이어갈 수 있도록 작성한 단일 진실 출처입니다.
> 마지막 업데이트: **2026-04-17** (Phase 1 MVP 완료 시점)

---

## 1. 한눈에 보는 현재 상태

| 항목 | 값 |
|---|---|
| 프로젝트명 | Nexus Alpha — 업무 자동화/RPA 전문 AI 가상 기업 시스템 |
| 현재 단계 | **Phase 1 MVP 완료**, Phase 2 착수 대기 |
| 작업 루트 | `C:\projects\nexus-alpha` |
| 주 언어 | Python 3.13.13 (가상환경 `.venv/`) |
| 오케스트레이션 | CrewAI 1.14.1 (Process.sequential) |
| LLM 접속 경로 | Claude Agent SDK (MAX 구독) 기본 / 필요 시 API Key로 전환 가능 |
| 모니터링 | LangFuse Cloud v4.3.1 (OpenTelemetry 기반) |
| GitHub | https://github.com/SongJongwon/nexus-alpha (main 브랜치) |
| 최신 커밋 | `160947c 🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우 성공` |
| 마지막 엔드투엔드 산출물 | `outputs/workflow_20260417_160617/` (Git 추적 제외) |

**한 문장 요약**: LLM Provider 추상화 → CrewAI 어댑터 → 3명 에이전트(CTO/Data Analyst/Python Engineer) → 순차 협업 워크플로우까지 완비되었고, 단일 사용자 요청 하나로 실행 가능한 Python 패키지가 자동 생성되는 상태입니다.

---

## 2. 완료된 작업 목록 (커밋 단위)

```
160947c  🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우 성공    ← 완료 보고서
70af92b  🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우         ← 구현 + E2E 검증
52d8e3c  🧹 .claude 로컬 설정 파일 정리
079451d  ✨ LangFuse 모니터링 통합 완료
a6f0911  🎉 Phase 0 완료: Nexus Alpha 기반 구축
```

### Phase 0 (기반)
- Python 3.13 가상환경 (`.venv/`) 구축 — 이전 3.14 venv는 crewai 비호환으로 폐기·재생성
- `requirements.txt` 작성 및 한국어 주석 포함 설치
- 에이전트 디렉터리 구조 완성 (`src/agents/{c_level,analysis,planning,engineering,qa,knowledge,operations}` + workflows/ + config/ + tests/ + outputs/ + logs/)
- `.gitignore` 최종 형태 (`.env`, `.venv/`, `outputs/`, `logs/`, `.claude/` 등)
- 루트 `README.md` (기술 스택·설치·구조·진행 현황)
- Hello Agent smoke test (Provider만 사용하는 초간단 버전)

### Phase 0 보강 — LLM Provider 시스템
- `src/llm/base_provider.py` — `BaseLLMProvider` 추상 클래스. **Template Method** 패턴으로 `generate()`가 `_generate_impl()`을 래핑하고 LangFuse 자동 기록.
- `src/llm/agent_sdk_provider.py` — `claude-agent-sdk`의 `query()` 사용 (Claude Code MAX 경로).
- `src/llm/api_key_provider.py` — `langchain-anthropic` 사용 (API Key 경로).
- `src/llm/factory.py` — `.env`의 `LLM_PROVIDER` 값으로 분기.
- `src/monitoring/langfuse_client.py` — LangFuse v4 OTel API 기반 싱글톤. 키 누락 시 조용히 no-op.

### Phase 1 — CrewAI 통합 & 3명 에이전트
- `src/llm/crewai_adapter.py` — `NexusAlphaLLM(BaseLLM)` 어댑터. Pydantic 필드 충돌 때문에 외부 접근은 `backend_provider` 프로퍼티 사용.
- 에이전트 팩토리 3개:
  - `src/agents/c_level/cto.py` → `create_cto_agent()`
  - `src/agents/analysis/data_analyst.py` → `create_data_analyst_agent()`
  - `src/agents/engineering/python_engineer.py` → `create_python_engineer_agent()`
- 워크플로우: `src/workflows/analyze_and_implement.py` → `run_analyze_and_implement(user_request)` / `WorkflowResult` 데이터클래스.
- smoke test 5종:
  - `src/tests/test_crewai_adapter.py`
  - `src/tests/test_cto_agent.py`
  - `src/tests/test_data_analyst_agent.py`
  - `src/tests/test_python_engineer_agent.py`
  - `src/tests/test_workflow_analyze_and_implement.py` ← E2E
- 완료 보고서: `docs/progress/phase1_complete.md`

---

## 3. 현재 파일 구조

```
nexus-alpha/
├── README.md
├── requirements.txt
├── .env                      # Git 제외 — LLM_PROVIDER, LANGFUSE_* 등
├── .gitignore
├── docs/
│   ├── context/
│   │   └── next_session_context.md   # ← 본 문서
│   └── progress/
│       └── phase1_complete.md
└── src/
    ├── __init__.py
    ├── README.md
    ├── agents/
    │   ├── __init__.py
    │   ├── README.md
    │   ├── c_level/
    │   │   ├── __init__.py
    │   │   ├── cto.py                  # create_cto_agent
    │   │   └── README.md
    │   ├── analysis/
    │   │   ├── __init__.py
    │   │   ├── data_analyst.py         # create_data_analyst_agent
    │   │   └── README.md
    │   ├── engineering/
    │   │   ├── __init__.py
    │   │   ├── python_engineer.py      # create_python_engineer_agent
    │   │   └── README.md
    │   ├── planning/        (__init__.py + README만 — Phase 2 이후 채움)
    │   ├── qa/              (    〃    )
    │   ├── knowledge/       (    〃    )
    │   └── operations/      (    〃    )
    ├── llm/
    │   ├── __init__.py                 # exports: BaseLLMProvider, NexusAlphaLLM, get_llm_provider
    │   ├── base_provider.py            # Template Method + 자동 LangFuse 기록
    │   ├── agent_sdk_provider.py       # claude-agent-sdk (MAX)
    │   ├── api_key_provider.py         # langchain-anthropic (API Key)
    │   ├── factory.py                  # LLM_PROVIDER 분기
    │   ├── crewai_adapter.py           # NexusAlphaLLM (BaseLLM 상속)
    │   └── README.md
    ├── monitoring/
    │   ├── __init__.py                 # exports: LangFuseClient, get_langfuse_client
    │   ├── langfuse_client.py          # OTel 싱글톤
    │   └── README.md
    ├── config/              (__init__.py + README만)
    ├── tests/
    │   ├── __init__.py
    │   ├── hello_agent.py              # Provider + LangFuse smoke (CrewAI 미사용)
    │   ├── hello_agent_old.py.bak      # 초기(CrewAI LLM 버전) 백업
    │   ├── test_crewai_adapter.py      # NexusAlphaLLM 직접 호출
    │   ├── test_cto_agent.py
    │   ├── test_data_analyst_agent.py
    │   ├── test_python_engineer_agent.py
    │   ├── test_workflow_analyze_and_implement.py   # E2E 3-agent
    │   └── README.md
    └── workflows/
        ├── __init__.py                 # exports: run_analyze_and_implement, WorkflowResult
        ├── analyze_and_implement.py    # CTO → Analyst → Engineer
        └── README.md
```

**Git 추적 제외** (`.gitignore`): `.env`, `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`, `outputs/`, `logs/`, `*.log`, `.vscode/`, `.idea/`, `.claude/`, `Thumbs.db`, `desktop.ini`, `*.tmp`, `*.temp`.

---

## 4. 핵심 설계 결정 사항

### 4-1. LLM 접근은 항상 Provider 추상화를 통한다
- 에이전트/워크플로우가 직접 Anthropic SDK를 호출하는 코드를 **금지**.
- 어떤 백엔드든 `BaseLLMProvider` 인터페이스 뒤로 숨긴다.
- 전환 스위치는 `.env`의 `LLM_PROVIDER` (값: `agent_sdk` | `api_key`).

### 4-2. Template Method 훅으로 자동 로깅
- `BaseLLMProvider.generate()`가 공개 API. 하위 클래스는 `_generate_impl()`만 구현.
- `generate()` 종료 시 반드시 `LangFuseClient.log_generation()` 호출.
- 로깅 실패는 메인 경로를 절대 차단하지 않음 (try/finally + 내부 except).

### 4-3. CrewAI 어댑터는 얇게, stateless에 가깝게
- `NexusAlphaLLM`은 (a) 메시지 포맷 변환, (b) async→sync 브리지, 두 가지 역할만.
- 실제 호출·로깅은 `BaseLLMProvider` 일임.
- **새 Provider 추가 시 어댑터와 에이전트 코드는 수정 불필요.**

### 4-4. Pydantic 필드 이름 충돌 회피
- CrewAI `BaseLLM`이 이미 `provider: str = "openai"` 필드를 가지고 있음.
- 내부에서 쓰는 Provider 참조는 **`backend_provider` 프로퍼티**로 노출.
- `self._provider` (PrivateAttr)에 저장, `@property`로 읽기 전용 공개.

### 4-5. async → sync 브리지는 loop 감지 + ThreadPoolExecutor fallback
- `NexusAlphaLLM.call()`에서 `asyncio.get_running_loop()`로 상태 감지.
- 루프가 없으면 `anyio.run()`, 있으면 새 스레드 + 새 loop.
- 중첩 이벤트 루프 문제(“cannot be called from a running event loop”) 방지.

### 4-6. 단일 LangFuse trace 원칙
- 워크플로우 진입 시 `monitor.log_trace(name=...)` 호출 → `_current_trace`에 저장.
- 이후 Provider.generate()가 자동으로 이 trace의 자식으로 generation을 붙임.
- `finally`에서 `end_trace() + flush()` 보장.
- 결과: Phase 1 `analyze_and_implement` trace 하나 아래에 CTO/Analyst/Engineer 3 generation 기록.

### 4-7. Windows 한글/유니코드 안전성
- 모든 실행 스크립트 최상단에서 sys.stdout/stderr를 UTF-8로 재설정:
  ```python
  if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8")
      sys.stderr.reconfigure(encoding="utf-8")
  ```
- cp949(Windows 기본) 환경에서도 한글·이모지·em-dash 모두 안전.

### 4-8. sys.path 주입으로 절대 경로 import 지원
- `src.llm`, `src.agents.*` 같은 절대 경로 import는 CWD가 프로젝트 루트여야 동작.
- 모든 테스트 스크립트 상단에 `PROJECT_ROOT = Path(__file__).resolve().parents[2]` + `sys.path.insert(0, str(PROJECT_ROOT))`.

### 4-9. 코드 생성 결과 저장 규약
- 에이전트의 Python 코드 응답은 마크다운 내부 `python ... ` 블록 형태.
- 자동 추출을 위해 엔지니어 에이전트에게 **첫 줄에 `# file: <상대경로>` 헤더를 넣도록** 백스토리에서 강제.
- 워크플로우 저장 디렉터리 구조:
  ```
  outputs/workflow_<ts>/
    00_user_request.txt
    01_cto_strategy.md
    02_analyst_brief.md
    03_engineer_output.md
    code/   ← 추출된 .py (이름은 `# file:` 헤더를 기준)
  ```

---

## 5. 환경 설정 정보

### 5-1. Python & 가상환경
- **Python 3.13.13** (winget 설치 `Python.Python.3.13`)
- **가상환경 경로**: `C:\projects\nexus-alpha\.venv`
- **실행 파일**: `C:\projects\nexus-alpha\.venv\Scripts\python.exe`, `pip.exe`
- bash 활성화: `source .venv/Scripts/activate`
- PowerShell 활성화: `.venv\Scripts\Activate.ps1`

### 5-2. 설치된 주요 라이브러리 (Phase 1 검증 시점)

| 라이브러리 | 버전 |
|---|---|
| crewai | 1.14.1 |
| crewai-tools | 1.14.1 |
| langgraph | 1.1.6 |
| langchain | 1.2.15 |
| langchain-anthropic | 1.4.0 |
| claude-agent-sdk | 0.1.61 |
| anyio | 4.13.0 |
| langfuse | 4.3.1 |
| pandas | 3.0.2 |
| openpyxl | 3.1.5 |
| pydantic | 2.11.10 |
| python-dotenv | 1.1.1 |
| PyYAML | 6.0.3 |
| rich | 14.3.4 |

재설치: `.venv/Scripts/pip.exe install -r requirements.txt`

### 5-3. `.env` 구성 (실제 값은 로컬 `.env`에만 — Git 제외)
```env
# LLM Provider 선택
LLM_PROVIDER=agent_sdk              # 또는 api_key
USE_API_KEY=false                   # 레거시 플래그 (hello_agent_old.py.bak 호환용)

# API Key (LLM_PROVIDER=api_key 일 때만)
# ANTHROPIC_API_KEY=sk-ant-...

# LangFuse 모니터링
LANGFUSE_PUBLIC_KEY="pk-lf-09fedad5-dcbf-4b8e-8f5d-f741922da92b"
LANGFUSE_SECRET_KEY="sk-lf-...(로컬 .env 참조)..."
LANGFUSE_HOST="https://cloud.langfuse.com"
```

> **LangFuse 계정**: Cloud 인스턴스 (`cloud.langfuse.com`). Organization/Project 이름은
> 로그인 후 대시보드 좌상단에서 확인하세요. 공개키 접두사 `pk-lf-09fedad5…` 로
> 프로젝트를 식별 가능합니다.

### 5-4. GitHub
- **저장소 URL**: https://github.com/SongJongwon/nexus-alpha
- **기본 브랜치**: `main`
- **원격명**: `origin`
- **인증**: Git Credential Manager 기반 (push 시 별도 프롬프트 없이 동작함)
- **Git 전역 설정**:
  - `user.name` = `머지봇_송종원`
  - `user.email` = `jwsong@ymx.co.kr`
  - (변경하려면 `git config --local user.name "SongJongwon"` 등으로 이 저장소에만 override)

---

## 6. Phase 2 다음 할 일 (우선순위 순)

> 근거: `docs/progress/phase1_complete.md` 4절.

| # | 항목 | 핵심 작업 | 수용 기준 (Definition of Done) |
|---|---|---|---|
| 1 | **pytest 하네스 정식화** | `pyproject.toml`에 `[tool.pytest.ini_options]` + `tests/conftest.py`(LangFuse 자동 비활성 fixture, Provider mock fixture) | `pytest` 한 명령으로 smoke 스크립트 대체. 네트워크 없이 CI에서 통과. |
| 2 | **QA 에이전트** (`src/agents/qa/code_reviewer.py`) | Engineer 산출 코드에 대해 타입 힌트·docstring·pytest 실행 여부 정적 점검. 4-agent 워크플로우로 확장. | `analyze_and_implement` 체인 끝에 QA 추가 시 리뷰 코멘트 생성, 실패 항목 표시. |
| 3 | **Knowledge 에이전트** (`src/agents/knowledge/*`) | `outputs/workflow_*` 적재·요약·검색. 재실행 시 과거 전략을 참고할 수 있는 RAG 경로. | "비슷한 요구를 이전에 처리한 적 있나?" 질의에 관련 산출물 링크 반환. |
| 4 | **Operations 에이전트** (`src/agents/operations/*`) | 생성된 코드의 스케줄 실행·로그 수집·실패 알림. | `workflow_<ts>/code/`를 실제로 실행하고 결과/에러를 LangFuse·파일에 기록. |
| 5 | **요청 라우팅 + UI** | Gradio/Streamlit 기반 단일 엔트리. 자연어 요청 → 적절한 워크플로우 자동 선택. | 브라우저에서 요청 투입 → 3~4명 체인 실행 → 산출 다운로드까지 엔드투엔드. |

**권장 진입 순서**: `1` → `2` → (`3` 또는 `4` 병렬) → `5`.
우선순위 1 없이는 나머지 작업이 회귀에 취약해집니다.

### Phase 2 작업을 시작할 때 제일 먼저 할 일

1. 새 브랜치 생성: `git checkout -b phase2/pytest-harness`
2. `pyproject.toml` 신규 작성 (pytest + ruff 설정 포함 권장)
3. `tests/conftest.py` — LangFuse 자동 no-op fixture(autouse, monkeypatch) + fake Provider fixture
4. 기존 smoke `src/tests/test_*.py`를 `pytest`로 실행되도록 최소 수정 (assertion 1~2개 추가)
5. GitHub Actions 워크플로우(옵션) 초안

---

## 7. 새 세션 시작 방법

### 7-1. 세션 초기 준비 체크리스트
```bash
# 프로젝트 디렉터리로 이동
cd C:/projects/nexus-alpha

# 가상환경 활성화
source .venv/Scripts/activate       # bash
# .venv\Scripts\Activate.ps1        # PowerShell

# 현재 상태 확인
git status
git log --oneline -5
.venv/Scripts/python.exe --version  # 3.13.13 이어야 함
```

### 7-2. 새 Claude Code 세션을 시작할 때 첫 프롬프트 템플릿

> 아래 텍스트를 그대로 복사해 붙여넣으면 새 세션이 바로 이어받습니다.

```
프로젝트 루트는 C:\projects\nexus-alpha 입니다.
docs/context/next_session_context.md 를 먼저 읽어서 현재 상태와
Phase 1까지의 설계 결정을 파악해 주세요.
그 다음 아래 작업을 이어서 진행하려고 합니다:

(여기에 구체 작업 내용, 예: "Phase 2 우선순위 1 — pytest 하네스 정식화 시작")
```

### 7-3. 동작 확인용 스모크 명령
```bash
# (A) Provider 단독 — 가장 빠름 (~5초)
.venv/Scripts/python.exe src/tests/hello_agent.py

# (B) CrewAI 어댑터 단독
.venv/Scripts/python.exe src/tests/test_crewai_adapter.py

# (C) 개별 에이전트 단독
.venv/Scripts/python.exe src/tests/test_cto_agent.py
.venv/Scripts/python.exe src/tests/test_data_analyst_agent.py
.venv/Scripts/python.exe src/tests/test_python_engineer_agent.py

# (D) 엔드투엔드 3-agent (가장 오래 걸림, 수 분)
.venv/Scripts/python.exe src/tests/test_workflow_analyze_and_implement.py
```

### 7-4. 주요 확인 지점
- **LangFuse 대시보드**: https://cloud.langfuse.com → Tracing → Traces
- **산출물**: `outputs/workflow_<timestamp>/code/`
- **진행 보고서**: `docs/progress/phase1_complete.md`
- **본 컨텍스트 파일**: `docs/context/next_session_context.md`

### 7-5. 자주 쓰는 단축 명령
```bash
# 의존성 재설치
.venv/Scripts/pip.exe install -r requirements.txt

# Provider 전환 (.env 수정)
#   LLM_PROVIDER=agent_sdk → MAX 구독
#   LLM_PROVIDER=api_key   → .env의 ANTHROPIC_API_KEY 사용

# 최신 원격 상태로 sync
git pull --rebase origin main

# 새 기능 브랜치
git checkout -b phase2/<주제>
```

---

## 부록 — 알려진 주의 사항

1. **`verbose=True`는 노이즈가 큽니다.** 에이전트 팩토리 기본이 `verbose=True`라 smoke 시 CrewAI의 🤖/✅ 패널이 콘솔을 가득 채웁니다. 운영 진입 시 `verbose=False`로 호출하세요.
2. **`python src/tests/hello_agent.py` 말고 venv의 python을 사용**. 시스템 Python(3.14)으로 실행하면 crewai 임포트 실패.
3. **async→sync 브리지의 한계**. CrewAI가 자체 async 경로를 더 공격적으로 쓰기 시작하면 `NexusAlphaLLM.call()`의 ThreadPoolExecutor 경로가 빈번히 돌 수 있습니다. 필요 시 `asyncio.Runner`로 재작성 검토.
4. **LangFuse v4는 OTel API**. v2 문법(`langfuse.trace(...)`)은 동작하지 않습니다. `start_observation(as_type=...)` 패턴을 그대로 유지하세요.
5. **`outputs/`는 `.gitignore`에 포함**. 산출물이 저장되어도 Git에 푸시되지 않습니다. 공유가 필요하면 압축해 첨부하거나 별도 Gist로 올리세요.
