# Nexus Alpha — 새 세션 인계용 컨텍스트

> **이 문서 한 장만 읽어도** 새 Claude Code 세션이 현재와 동일한 수준으로
> 작업을 이어갈 수 있도록 작성한 단일 진실 출처입니다.
> 마지막 업데이트: **2026-04-17** (Phase 2-P2 QA 에이전트 완료 + v3/v4 설계 문서 반영)

---

## 1. 한눈에 보는 현재 상태

| 항목 | 값 |
|---|---|
| 프로젝트명 | Nexus Alpha — 업무 자동화/RPA 전문 AI 가상 기업 시스템 |
| 최종 비전 (v4) | **"계산기 만들어줘" 한 마디 → .exe 완성품**까지 자동 도달 |
| 현재 단계 | **Phase 2 우선순위 2 완료** (QA 에이전트 + 4-agent 워크플로우) + **v3/v4 설계 확정**. 우선순위 3(Knowledge) 또는 1-B(Linux CI) 착수 대기 |
| 작업 루트 | `C:\projects\nexus-alpha` |
| 주 언어 | Python 3.13.13 (가상환경 `.venv/`) |
| 오케스트레이션 | **CrewAI 1.14.1 (버전 고정)** + LangGraph (v3 루프 도입 예정) |
| LLM 접속 경로 | Claude Agent SDK (MAX 구독) 기본 / 필요 시 API Key로 전환 가능 |
| 모니터링 | LangFuse Cloud v4.3.1 (OpenTelemetry 기반) — 워크플로우 단일 trace 아래 4 generation |
| 테스트 하네스 | pytest 9.0.3 + pytest-mock 3.15.1 + pytest-socket 0.7.0 (opt-in) |
| 워크플로우 | CTO → Data Analyst → Python Engineer → **Code Reviewer** (4-agent sequential) |
| 조직도 | C-Level 3 + 8 본부 = **46명 풀 조직** (현재 4명 구현, ~8.7%) |
| GitHub | https://github.com/SongJongwon/nexus-alpha (`main` + 작업 브랜치) |
| 최신 main 커밋 | `b9c178c Merge pull request #2 from SongJongwon/phase2/qa-agent` |
| 마지막 엔드투엔드 산출물 | `outputs/workflow_20260417_164414/` (Git 추적 제외) |

**한 문장 요약**: Phase 2-P1 pytest 하네스 위에 Code Reviewer(4-agent 워크플로우)까지 main에 안착했고, **자기 진화 엔진(v3)** + **완전 자율 빌드(v4)** 설계가 `docs/architecture/`에 확정 기록되어 다음 단계 진입 준비 완료된 상태입니다.

---

## 2. 완료된 작업 목록 (커밋 단위)

```
(작업브랜치) 📝 docs: 2026-04-17 세션 작업 로그 추가                 ← docs/architecture-v3-v4
(작업브랜치) 📐 docs: v3/v4 설계 문서 및 조직도 반영                 ← docs/architecture-v3-v4
b9c178c  Merge pull request #2 from SongJongwon/phase2/qa-agent       ← Phase 2-P2 main merge
c30f794  🧪 Phase 2 우선순위 2: QA 에이전트(Code Reviewer) 추가
c2c2a85  Merge pull request #1 from SongJongwon/phase2/pytest-harness ← Phase 2-P1 main merge
29e1ce1  🧪 Phase 2 우선순위 1: pytest 하네스 정식화
354ccfb  📌 다음 세션 컨텍스트 파일 추가
160947c  🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우 성공
70af92b  🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우
52d8e3c  🧹 .claude 로컬 설정 파일 정리
079451d  ✨ LangFuse 모니터링 통합 완료
a6f0911  🎉 Phase 0 완료: Nexus Alpha 기반 구축
```

### Phase 2 우선순위 2 — QA 에이전트(Code Reviewer) + 4-agent 워크플로우 (2026-04-17)
- **신규 에이전트**: `src/agents/qa/code_reviewer.py` → `create_code_reviewer_agent()`. `CODE_REVIEWER_*` 4 상수 + 팩토리 시그니처는 기존 3개 에이전트와 동일.
- **백스토리 5대 점검 항목**: 타입 힌트 / docstring / pytest 실행 가능성 / 경계 예외 처리 / 모듈 분리. *읽기만 한다, 실행하지 않는다* 원칙 — 실행은 후속 Sandbox Runner(2-P4) 책임.
- **출력 규약**: 5단 한국어 마크다운 + 마지막 줄 `Final Answer:` 종합 판정(APPROVED/NEEDS_REVISION).
- **smoke test**: `src/tests/test_code_reviewer_agent.py` — 의도적 결함 4종(타입힌트/docstring/pytest/광범위 except) sample 포함. FakeProvider 패턴 그대로 적용.
- **워크플로우 확장**: `src/workflows/analyze_and_implement.py`
  - `WorkflowResult.qa_review: str` 필드 추가
  - `qa_review_task` Task 추가 — `context=[engineer_task]` (Engineer 산출만 컨텍스트로, 비용·관심사 분리)
  - `Crew(agents=[..., reviewer], tasks=[..., qa_review_task])` 4-agent 등록
  - `outputs/workflow_<ts>/04_qa_review.md` 자동 저장
- **워크플로우 E2E 테스트 갱신**: pytest 함수명 `_three_stage_` → `_four_stage_artifacts`, `04_qa_review.md` 검증 + `result.qa_review` marker 검증, 직접 실행 경로에 ④ Code Reviewer preview 패널 추가.
- **회귀 검증**: `.venv/Scripts/pytest.exe` → **7 passed in ~11s** (Phase 2-P1 6건 + Code Reviewer 1건, 네트워크 호출 0건).
- **Code Reviewer 명명 결정**: `next_session_context.md`의 잠정 명명 `create_qa_reviewer_agent()` 대신 어근 일관성을 우선해 `create_code_reviewer_agent()` 채택. 기존 3개 에이전트와 동일한 *역할-기반 이름* 패턴 유지.
- **보고서**: `docs/progress/phase2_priority2_complete.md`

### v3 / v4 설계 문서 확정 (2026-04-17)
- `docs/architecture/` 폴더 신설 — 모든 아키텍처 설계서의 단일 출처.
- **`nexus_alpha_v3.md`** — 자기 진화 엔진 (Phase 2.5):
  - 신규 에이전트 4종 — Requirement Expander / Gap Analyst / Convergence Judge / Iteration Controller
  - LangGraph StateGraph로 루프 제어 (entry → expand → chain → gap → judge → {finalize|feedback→chain|escalate})
  - 종료 조건 3종: COMPLETE / IMPROVE_NEEDED / BLOCKED (stagnation·budget·iteration cap)
  - 안전장치: max_iterations=5, budget gate, stagnation detection (2회 연속 0개 해소 시 BLOCKED)
- **`nexus_alpha_v4.md`** — 완전 자율 빌드 (Phase 4 / 4.5 / 5):
  - 비전: "계산기 만들어줘" → 다운로드 가능한 setup.exe
  - 신규 에이전트 13종 (Phase 4: 4명 / Phase 4.5: 5명 / Phase 5: 4명)
  - 빌드 도구 우선순위: PyInstaller → Nuitka → cx_Freeze
  - 배포 채널 우선순위: GitHub Releases → 사내 서버 → S3 presigned → 로컬
- **`nexus_alpha_org_v4.md`** — 확정 조직도:
  - C-Level 3 + 8 본부 = 9개 조직 단위, **총 46명**
  - 본부 8개: 업무 분석(5) / 기획·설계(4) / 개발(9) / 품질 검증(6) / 지식 관리(3) / 운영 지원(4) / 🆕 디자인(3) / 🆕 빌드 & 배포(9)
  - 신설 디렉터리: `src/agents/design/` (Phase 4), `src/agents/build_release/` (Phase 4.5)
  - **UI/UX Analyst는 디자인 본부가 아닌 기획·설계 본부 소속** (관심사 분리: 분석 vs 시각 디자인 생산)

### Phase 2 우선순위 1 — pytest 하네스 정식화 (2026-04-17)
- `pyproject.toml` 신규 — `[tool.pytest.ini_options]`, `[tool.ruff]` (line-length 100, py313)
- `requirements.txt` — pytest/pytest-mock/pytest-socket 추가, **crewai/crewai-tools `==1.14.1` 버전 고정** (ReAct 파서 포맷이 FakeProvider에 결합)
- `src/tests/conftest.py` 신규:
  - `FakeProvider`(BaseLLMProvider 상속) + `fake_provider` / `fake_provider_factory` fixture
  - autouse `_patch_llm_factory` — `src.llm.factory.get_llm_provider` **와** `src.llm.crewai_adapter.get_llm_provider` 두 네임스페이스를 동시 monkeypatch
  - autouse `_silence_langfuse` — LangFuseClient 로깅 메서드 전부 no-op
  - (제외) `pytest-socket` autouse — Windows ProactorEventLoop의 내부 socketpair까지 막아 부작용. Linux CI에서만 opt-in 예정
- 5개 smoke test에 pytest 진입점 추가 (기존 `if __name__ == "__main__"` 경로는 **수정 없이 보존**)
- FakeProvider 기본 응답: `Thought: ...\nFinal Answer: 이것은 FakeProvider가 반환한 고정 응답입니다.` — CrewAI 1.14.1 `crewai/agents/parser.py`의 `FINAL_ANSWER_ACTION = "Final Answer:"` 와 1:1 정합
- 실행 결과: **6 passed in 7.72s** (네트워크 호출 0건)
- 보고서: `docs/progress/phase2_priority1_complete.md`

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
├── requirements.txt          # pytest-* / crewai==1.14.1 (고정)
├── pyproject.toml            # pytest + ruff 설정 (Phase 2-P1)
├── .env                      # Git 제외 — LLM_PROVIDER, LANGFUSE_* 등
├── .gitignore
├── docs/
│   ├── architecture/                  # 설계 문서 (단일 출처) — 본 세션 신설
│   │   ├── nexus_alpha_v3.md          #   자율 반복 루프 (Phase 2.5)
│   │   ├── nexus_alpha_v4.md          #   완전 자율 빌드 (Phase 4/4.5/5)
│   │   └── nexus_alpha_org_v4.md      #   확정 조직도 (46명, 8 본부)
│   ├── context/
│   │   └── next_session_context.md   # ← 본 문서
│   └── progress/
│       ├── phase1_complete.md
│       ├── phase2_priority1_complete.md
│       └── phase2_priority2_complete.md   # Phase 2-P2 — 본 세션
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
    │   ├── qa/                          # Phase 2-P2 — 본 세션
    │   │   ├── __init__.py              # exports: create_code_reviewer_agent
    │   │   ├── code_reviewer.py         # create_code_reviewer_agent
    │   │   └── README.md
    │   ├── planning/        (__init__.py + README만 — Phase 2 이후 채움)
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
    │   ├── conftest.py                 # Phase 2-P1 — FakeProvider + autouse fixtures
    │   ├── hello_agent.py              # Provider + LangFuse smoke (CrewAI 미사용)
    │   ├── hello_agent_old.py.bak      # 초기(CrewAI LLM 버전) 백업
    │   ├── test_crewai_adapter.py      # NexusAlphaLLM 직접 호출 + pytest 2건
    │   ├── test_cto_agent.py           # + pytest 1건 (FakeProvider)
    │   ├── test_data_analyst_agent.py  # + pytest 1건
    │   ├── test_python_engineer_agent.py # + pytest 1건
    │   ├── test_code_reviewer_agent.py # Phase 2-P2 — pytest 1건 (본 세션)
    │   ├── test_workflow_analyze_and_implement.py   # E2E 4-agent + pytest 1건 (tmp_path)
    │   └── README.md
    └── workflows/
        ├── __init__.py                 # exports: run_analyze_and_implement, WorkflowResult
        ├── analyze_and_implement.py    # CTO → Analyst → Engineer → Code Reviewer (4-agent)
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

### 4-9. pytest 하네스는 FakeProvider로 CrewAI 경로 완주 (Phase 2-P1)
- `conftest.py`의 autouse fixture가 `get_llm_provider`를 **두 네임스페이스**(`src.llm.factory` + `src.llm.crewai_adapter`)에서 동시 monkeypatch.
- FakeProvider 기본 응답은 `"Thought: ...\nFinal Answer: ..."` — CrewAI 1.14.1 `crewai/agents/parser.py`의 `FINAL_ANSWER_ACTION = "Final Answer:"` 계약에 정합해 단일 호출로 AgentFinish 수렴.
- 에이전트/워크플로우 코드는 pytest를 위해 **절대 수정하지 않음** (최소 침습). 기존 `if __name__ == "__main__"` 경로는 그대로 실제 LLM을 호출.
- Windows에서는 pytest-socket autouse를 쓰지 않음 — ProactorEventLoop의 내부 socketpair까지 차단하는 부작용. Linux CI에서 `pytest --disable-socket` opt-in 예정.

### 4-10. 코드 생성 결과 저장 규약
- 에이전트의 Python 코드 응답은 마크다운 내부 `python ... ` 블록 형태.
- 자동 추출을 위해 엔지니어 에이전트에게 **첫 줄에 `# file: <상대경로>` 헤더를 넣도록** 백스토리에서 강제.
- 워크플로우 저장 디렉터리 구조 (Phase 2-P2 4-agent 기준):
  ```
  outputs/workflow_<ts>/
    00_user_request.txt
    01_cto_strategy.md
    02_analyst_brief.md
    03_engineer_output.md
    04_qa_review.md           ← Code Reviewer 정적 리뷰 (Phase 2-P2)
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

## 6. 로드맵 (v4까지의 풀 스코프)

> 근거: `docs/progress/phase{1,2_priority1,2_priority2}_complete.md` + `docs/architecture/nexus_alpha_v3.md`, `nexus_alpha_v4.md`, `nexus_alpha_org_v4.md`.

| Phase | 항목 | 상태 |
|---|---|---|
| 0 | 기반 구축 (venv, Provider, LangFuse) | ✅ 완료 |
| 1 | MVP 3명 에이전트 협업 (CTO/Analyst/Engineer) | ✅ 완료 |
| 2-P1 | pytest 하네스 정식화 | ✅ **완료 + main merge** |
| **2-P2** | **QA 에이전트 (Code Reviewer) + 4-agent 워크플로우** | ✅ **완료 + main merge (2026-04-17)** |
| 2-P1B | Linux GitHub Actions CI (`--disable-socket` opt-in) | 🟡 **다음 후보 ①** |
| 2-P3 | Knowledge 에이전트 (Curator + RAG Searcher) | 🟡 **다음 후보 ②** |
| 2-P4 | Operations 에이전트 (Sandbox Runner) — Code Reviewer의 "동적 검증" 짝 | 🟡 대기 |
| 2-P5 | 요청 라우팅 + 하이브리드 UI | 🟡 대기 |
| **2.5 (v3)** | **자기 진화 엔진** — Requirement Expander / Gap Analyst / Convergence Judge / Iteration Controller | 📐 설계 확정 |
| 3 | 실행 엔진 통합 (Sandbox 빌드·실행) | 🟡 대기 |
| **4 (v4)** | **GUI 자동 생성** — UI/UX Analyst + 디자인 본부 3명 | 📐 설계 확정 |
| **4.5 (v4)** | **빌드 & 패키징** — Build/Dependency/Asset/Installer/Platform Tester (5명) | 📐 설계 확정 |
| **5 (v4)** | **배포 자동화** — Release/Changelog/Update/Distribution (4명) | 📐 설계 확정 |

**권장 진입 순서**: ~~`2-P1`~~ → ~~`2-P2`~~ → **`2-P1B`** (작고 즉시 효과 큼) → **`2-P3` (Knowledge)** → `2-P4` → `2-P5` → `2.5 (v3 루프)` → `3` → `4` → `4.5` → `5`.

### 다음 작업을 시작할 때 제일 먼저 할 일

#### 후보 ① — Phase 2-P1B (Linux GitHub Actions CI)
1. 새 브랜치 생성: `git checkout -b phase2/linux-ci`
2. `.github/workflows/pytest.yml` — Python 3.13 + pip cache + `pytest --disable-socket` 실행. socket 차단으로 회귀 안전망 확보.
3. (선택) `pytest -m integration` 분리 러너 — 실제 LLM 검증용 (LangFuse·API 키 secrets 필요).
4. README badge 추가, PR 템플릿에 CI 통과 항목 명시.

#### 후보 ② — Phase 2-P3 (Knowledge 에이전트)
1. 새 브랜치 생성: `git checkout -b phase2/knowledge-agent`
2. `src/agents/knowledge/knowledge_curator.py` — 과거 `outputs/workflow_*` 폴더 스캔, summary·tag 생성.
3. `src/agents/knowledge/rag_searcher.py` — 사용자 새 요청과 과거 워크플로우 사이 유사도 검색(임베딩 또는 키워드 기반 1차).
4. Code Reviewer와 동일 패턴: factory 함수 + smoke test + pytest 함수.
5. (선택) `analyze_and_implement` 진입 시 RAG Searcher가 유사 사례를 CTO 컨텍스트에 주입하는 5-agent 확장 검토.

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

### 7-3. 동작 확인용 명령

**(pytest 하네스 — 네트워크 없이, 7초 내 전체 통과)**
```bash
.venv/Scripts/pytest.exe                 # 전체 6개 테스트
.venv/Scripts/pytest.exe src/tests/test_workflow_analyze_and_implement.py -v
```

**(기존 직접 실행 — 실제 LLM 호출, 수 분 소요, LangFuse 기록 포함)**
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
- **진행 보고서**: `docs/progress/phase1_complete.md`, `docs/progress/phase2_priority1_complete.md`
- **설계 문서**: `docs/architecture/nexus_alpha_v3.md`, `nexus_alpha_v4.md`, `nexus_alpha_org_v4.md`
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
6. **pytest-socket은 Windows에서 autouse 불가**. `ProactorEventLoop`의 내부 `socket.socketpair()`까지 차단해 `anyio.run()` 경로가 전부 실패합니다. 네트워크 차단은 FakeProvider monkeypatch로 이미 달성되어 있고, pytest-socket은 Linux CI에서 `pytest --disable-socket` opt-in으로만 씁니다. 자세한 기록은 `docs/progress/phase2_priority1_complete.md` §3-1.
7. **CrewAI 버전은 `==1.14.1`로 고정됨**. FakeProvider 응답이 `crewai/agents/parser.py`의 `FINAL_ANSWER_ACTION` 상수에 결합되어 있어 메이저/마이너 업그레이드 시 테스트 재검증 필요.
