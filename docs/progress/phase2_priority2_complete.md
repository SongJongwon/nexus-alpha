# Phase 2 우선순위 2 완료 보고서 — QA 에이전트(Code Reviewer)

- **완료일**: 2026-04-17
- **상태**: ✅ 전 목표 달성
- **범위**: 4번째 에이전트(Code Reviewer)를 추가하고 `analyze_and_implement` 워크플로우를 3-agent → 4-agent로 확장. Phase 2-P1 pytest 하네스를 그대로 활용해 회귀 보호 유지.
- **브랜치**: `phase2/qa-agent` (main `c2c2a85`에서 분기)
- **선행 조건**: Phase 1 MVP + Phase 2-P1(pytest 하네스) merge 완료

---

## 1. 달성 내용 요약

| 축 | 목표 | 결과 |
|---|---|---|
| 신규 에이전트 | Code Reviewer 팩토리 (`품질 검증` 본부 첫 인원) | `src/agents/qa/code_reviewer.py` + `__init__.py` exports |
| 단위 테스트 | FakeProvider 패턴으로 회귀 보호 | `src/tests/test_code_reviewer_agent.py` — pytest 7 passed |
| 워크플로우 확장 | 3-agent → 4-agent (CTO → Analyst → Engineer → **QA**) | `src/workflows/analyze_and_implement.py` |
| 산출 저장 규약 | `04_qa_review.md` 추가 | 워크플로우 디렉터리에 자동 저장 |
| 회귀 검증 | Phase 2-P1 안전망 위에서 통과 | **7 passed in 11.46s** (네트워크 호출 0건) |

### 완료 기준 체크

- [x] `src/agents/qa/code_reviewer.py` — `create_code_reviewer_agent()` 팩토리 동작
- [x] `src/agents/qa/__init__.py` exports 갱신, `from src.agents.qa import create_code_reviewer_agent` 정상
- [x] `src/tests/test_code_reviewer_agent.py` — FakeProvider autouse 경로로 통과
- [x] `analyze_and_implement` 워크플로우의 4번째 Task로 QA 추가, `WorkflowResult.qa_review` 필드 신설
- [x] `outputs/workflow_<ts>/04_qa_review.md` 자동 저장
- [x] `.venv/Scripts/pytest.exe` 한 명령으로 7개 테스트 전부 통과 (네트워크 차단 상태)
- [x] 기존 `python src/tests/test_*.py` 직접 실행 경로 보존 (Code Reviewer 단독 + 워크플로우 E2E 모두)

---

## 2. Step별 진행

### Step 1 — Code Reviewer 에이전트 구현 + smoke test

**신규 파일**:
- `src/agents/qa/code_reviewer.py` — `CODE_REVIEWER_*` 4개 상수 + `create_code_reviewer_agent()` 팩토리. CTO/Analyst/Engineer와 동일한 시그니처(`llm=None, verbose=True, max_iter=3, allow_delegation=False`).
- `src/agents/qa/__init__.py` — exports 갱신 (이전엔 빈 패키지).
- `src/tests/test_code_reviewer_agent.py` — Phase 2-P1 패턴(`main()` 직접 실행 + `test_*` pytest 분리) 그대로 적용.

**Code Reviewer 백스토리 핵심**:
- *읽기만 한다, 실행하지 않는다* — 정적 점검 전담. 실행은 후속 Sandbox Runner(2-P4) 책임.
- 5가지 정적 점검 항목: ① 타입 힌트 / ② docstring / ③ pytest 실행 가능성 / ④ 경계 예외 처리 / ⑤ 모듈 분리.
- 심각도 분류: BLOCKER (즉시 사고) / MAJOR (운영 진입 전 필수) / MINOR (스타일·문서 흠집).
- 출력 규약: 5단 한국어 마크다운 + 마지막 줄 `Final Answer:` 종합 판정(APPROVED / NEEDS_REVISION).

**smoke test 시나리오**:
- 의도적 결함 4종(타입힌트 0 / docstring 0 / pytest 0 / 내부 함수 광범위 except)을 가진 `calc.py` sample을 리뷰 대상으로 주입.
- 직접 실행 시 실제 LLM이 결함을 인지하는지 확인 가능, pytest 경로에서는 FakeProvider가 고정 응답을 돌려주므로 체인 통과만 검증.

**검증**:
```
src/tests/test_code_reviewer_agent.py::test_code_reviewer_agent_runs_through_crew_with_fake_provider PASSED
======================= 7 passed, 49 warnings in 9.10s ========================
```
(이 시점에는 Workflow E2E가 여전히 3-agent였음. 7건 = 6건 + Code Reviewer 1건)

### Step 2 — `analyze_and_implement` 워크플로우 4-agent 확장

**`src/workflows/analyze_and_implement.py` 변경**:
- 모듈 docstring을 4-agent 설계(CTO → Analyst → Engineer → **Code Reviewer**)로 갱신, Phase 2-P2 변경 사항 명시.
- `from src.agents.qa import create_code_reviewer_agent` import 추가.
- `WorkflowResult` 데이터클래스에 `qa_review: str` 필드 추가 (Optional 아님 — 워크플로우 정상 종료 시 항상 채워진다).
- 본체:
  - `reviewer = create_code_reviewer_agent(verbose=verbose)` 생성.
  - `qa_review_task = Task(... agent=reviewer, context=[engineer_task])` — Engineer 산출물만 컨텍스트로 받음. CTO/Analyst까지 전달하면 토큰 비용 증가에 비해 정적 점검 품질 향상이 크지 않다는 판단.
  - `Crew(agents=[..., reviewer], tasks=[..., qa_review_task], process=Process.sequential, ...)` 로 등록.
  - `qa_review = _task_output_text(qa_review_task) or fallback`. **fallback을 `qa_review`에 둔 이유**: 마지막 Task의 raw가 `crew_result.raw`와 동일하므로 안정성 향상.
- 산출 저장에 `04_qa_review.md` 추가.

**`src/tests/test_workflow_analyze_and_implement.py` 변경**:
- pytest 함수명 `_three_stage_` → `_four_stage_artifacts` (의미 일치).
- 검증 파일 목록에 `04_qa_review.md` 추가.
- `result.qa_review` marker 검증 추가.
- 직접 실행 경로(`main()`)에 ④ Code Reviewer preview 패널 추가, LangFuse 안내 문구 "3개 generation" → "4개 generation".

### Step 3 — 회귀 검증

```
$ .venv/Scripts/pytest.exe
============================= test session starts =============================
platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
rootdir: c:\projects\nexus-alpha
configfile: pyproject.toml
testpaths: src/tests
plugins: anyio-4.13.0, langsmith-0.7.32, mock-3.15.1, socket-0.7.0
collected 7 items

src/tests/test_crewai_adapter.py::test_adapter_uses_backend_provider_from_factory PASSED
src/tests/test_crewai_adapter.py::test_adapter_call_returns_fake_response PASSED
src/tests/test_code_reviewer_agent.py::test_code_reviewer_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_cto_agent.py::test_cto_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_data_analyst_agent.py::test_data_analyst_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_python_engineer_agent.py::test_python_engineer_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_workflow_analyze_and_implement.py::test_run_analyze_and_implement_produces_four_stage_artifacts PASSED

======================= 7 passed, 56 warnings in 11.46s =======================
```

- **7 passed** (Phase 2-P1 6건 + Code Reviewer 1건).
- **11.46s** (Phase 2-P1: 7.72s, Workflow E2E가 3 → 4 Crew kickoff 으로 늘어 ~3.7초 증가. 예상 범위).
- 네트워크 호출 0건 — FakeProvider가 `get_llm_provider()` 두 네임스페이스에서 모두 monkeypatch 되어 있어 외부 도달 불가.

---

## 3. 알려진 이슈·설계 결정

### 3-1. Code Reviewer 명명 — `create_code_reviewer_agent()` 채택
- `next_session_context.md`의 잠정 명명은 `create_qa_reviewer_agent()` 였으나, 기존 3개 에이전트(`cto.py`/`CTO_NAME`/`create_cto_agent`)와의 **어근 일관성**을 우선해 `code_reviewer.py` / `CODE_REVIEWER_NAME = "CodeReviewer"` / `create_code_reviewer_agent()` 로 통일.
- `src/agents/qa/` 디렉터리에 향후 Test Engineer / Security Auditor 등 다른 QA 본부 인원이 추가될 때도 동일한 *역할-기반 이름* 패턴 유지 권장.

### 3-2. QA Task의 context는 Engineer만 전달 — 관심사 분리
- `qa_review_task`에 `context=[engineer_task]` 만 주입(CTO/Analyst 제외).
- 이유: Code Reviewer는 *코드 자체를 정적 점검*하는 역할이지, 비즈니스 요구나 분석 지시서의 충족 여부를 판정하지 않는다. 그것은 v3의 **Gap Analyst**(`docs/architecture/nexus_alpha_v3.md`) 책임.
- 결과: 현재 워크플로우의 QA는 코드 *품질*만 본다. *요구 충족도*는 v3 도입 시 별도 단계로.

### 3-3. `WorkflowResult.qa_review`는 Optional 아닌 필수 필드
- 정상 종료 시 항상 채워지는 것이 계약. 비어 있으면 워크플로우 자체가 실패한 것.
- 다만 fallback으로 `crew_result.raw`를 사용해 마지막 Task가 비어 있어도 무언가는 들어가도록 안전망 유지.

### 3-4. `04_qa_review.md` 저장 — Engineer까지 동일 규칙
- `00_user_request.txt` / `01_cto_strategy.md` / `02_analyst_brief.md` / `03_engineer_output.md` / **`04_qa_review.md`** — 번호 순 자연스러운 확장.
- 코드 추출(`code/` 디렉터리)은 여전히 `engineer_output`만 대상. Code Reviewer는 코드를 만들지 않으므로 추출 대상 아님.

### 3-5. LangFuse trace는 그대로 단일 trace, generation 4개로 자연 확장
- 워크플로우 시작 시 `monitor.log_trace(name="analyze_and_implement", ...)`로 root span 1개 생성, 4명의 에이전트가 각자 `_current_trace`를 부모로 generation을 1건씩 매단다.
- `BaseLLMProvider.generate()`의 Template Method 훅 덕분에 워크플로우 코드에 LangFuse 직접 호출 추가 불필요.

### 3-6. CrewAI DeprecationWarning 49 → 56건
- 워크플로우 E2E가 4-agent로 늘면서 CrewAI 내부 deprecation 경고가 7건 더 발생(Crew kickoff 1회당 ~7건). 테스트 통과를 막지 않으므로 별도 suppress 추가하지 않음. CrewAI 마이너 업그레이드 시 자연 해소 예상.

### 3-7. 실제 LLM 검증은 별도 일정
- pytest 경로는 FakeProvider 고정 응답으로 통과만 검증한다(체인 무결성).
- *Code Reviewer가 실제로 결함 4종을 짚어내는지*는 직접 실행 경로(`python src/tests/test_code_reviewer_agent.py`)와 워크플로우 E2E(`test_workflow_analyze_and_implement.py`)에서 확인 가능. **PR merge 후 별도 실행 예정** (사용자 요청).

---

## 4. 새로 추가/수정된 파일

```
src/agents/qa/code_reviewer.py             # NEW — Code Reviewer 팩토리
src/agents/qa/__init__.py                  # UPD — exports 갱신 (이전엔 빈 패키지)
src/tests/test_code_reviewer_agent.py      # NEW — smoke + pytest
src/workflows/analyze_and_implement.py     # UPD — 4-agent 확장 + qa_review 필드/저장
src/tests/test_workflow_analyze_and_implement.py # UPD — 4-stage 검증, ④ panel 추가
docs/progress/phase2_priority2_complete.md # NEW — 본 보고서
docs/context/next_session_context.md       # UPD — Phase 2-P2 완료 반영
```

---

## 5. 다음 작업 — Phase 2 우선순위 후보

`docs/context/next_session_context.md` §6의 로드맵을 참조하면, 우선순위 2 완료 후 자연스러운 다음 진입점은 두 갈래:

| 후보 | 소요 추정 | 선행 조건 | 가치 |
|---|---|---|---|
| **2-P3 Knowledge 에이전트** (`src/agents/knowledge/knowledge_curator.py` + `rag_searcher.py`) | 중간 | 없음 — 즉시 시작 가능 | 과거 `outputs/workflow_*` 적재·검색으로 다음 워크플로우 품질 향상 |
| **2-P1B Linux GitHub Actions CI** (`pytest --disable-socket` opt-in) | 작음 | Linux 환경 | 회귀 방어선을 자동화. 다중 기여자 진입 전 필수 |

**권장**: 2-P1B 먼저 (작고 자동화 가치가 즉각적). 그 후 2-P3로 넘어가면 Knowledge 에이전트 추가 시 회귀 자동 검증 보장.

다만 **사용자 요청에 따라** 본 보고서 작성 시점 결정은 보류 — PR merge 후 사용자가 다음 우선순위를 지정.
