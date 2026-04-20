# 세션 활동 로그 — 2026-04-17

- **기록 범위**: 2026-04-17 하루에 진행된 연속 세션들
- **작업 결과**: Phase 2-P1(pytest 하네스) 구현 + main merge + v3/v4 설계 문서 확정
- **누적 커밋 영향**: 로컬 2개 커밋 (`29e1ce1` + `fc009bc`), 원격 브랜치 2개 push, PR #1 생성·merge

---

## 1. 한눈에 보는 진척

| 세션 | 주요 산출 | 결과 |
|---|---|---|
| ① 계산기 워크플로우 A (넓은 요청) | `outputs/workflow_20260417_162709/` — 17 코드 파일 | 데이터 분석 파이프라인 생성 (요청 의도와 간극 발견) |
| ② 계산기 워크플로우 B (구체 요청) | `outputs/workflow_20260417_164414/calculator.py` + 17 파일 | 의도한 단일 `calculator.py` 성공 생성·실행 검증 |
| ③ Phase 2-P1 pytest 하네스 | `pyproject.toml`, `conftest.py`, 5 smoke pytest 전환 | **6 passed in 7.72s**, 네트워크 호출 0건 |
| ④ Push & PR #1 | PR https://github.com/SongJongwon/nexus-alpha/pull/1 | main merge 완료 (`c2c2a85`) |
| ⑤ v3/v4 설계 문서 반영 | `docs/architecture/` 3 파일, README·context 갱신 | `docs/architecture-v3-v4` push, PR 대기 |

---

## 2. 세션별 상세

### 세션 ① — 3명 에이전트 협업 실행 테스트 (넓은 요청)

**요청**: `run_analyze_and_implement("계산기를 만들어줘")`

**경과**:
- 기존 E2E 테스트(`test_workflow_analyze_and_implement.py`)와 동일한 패턴의 1회성 러너 스크립트 작성 (`src/tests/run_calculator_workflow.py`).
- 백그라운드 실행, 완료 알림 수신.

**산출**: `outputs/workflow_20260417_162709/`
- `01_cto_strategy.md` — CTO가 "웹 기반 공학용 계산기 MVP" 시나리오를 임의로 가정, 선행 질문 6개 제시, TypeScript/React/Vite 스택 결정.
- `02_analyst_brief.md` — Data Analyst가 **계산기 사용 로그** 분석 지시서 작성(실제 계산기 구현이 아님).
- `03_engineer_output.md` — Engineer가 `calc_report` Python 분석 파이프라인 생성 (17 파일).

**관찰**:
- 3명이 체인 전체에서 서로를 신뢰하며 컨텍스트 이어받음.
- **최종 산출이 "계산기 앱" 자체가 아니라 "계산기 사용 로그 분석 파이프라인"이 됨** — Engineer task 프롬프트가 `loader/transform/metrics/chart/render/cli` 데이터 분석 템플릿을 강제하는 구조적 편향 때문.
- Phase 2 우선순위 5(요청 라우팅) 필요성에 대한 강한 신호로 기록.

---

### 세션 ② — 구체화된 요청으로 재실행 + `.py` 실행 검증

**요청**: `run_analyze_and_implement("사칙연산 계산기 Python 앱을 만들어줘. ... 파일명: calculator.py")`

**경과**:
- 러너 스크립트 재사용, 요청만 교체해 백그라운드 재실행.
- 완료 후 생성된 `calculator.py`를 stdin pipe로 테스트 케이스 8종 투입.

**산출**: `outputs/workflow_20260417_164414/`
- [code/calculator.py](outputs/workflow_20260417_164414/code/calculator.py) — REPL 계산기 (타입힌트·docstring·dispatch 테이블 패턴).
- 번외로 `calc_analytics/` 데이터 분석 패키지까지 덤으로 생성됨 (Engineer task 프롬프트의 구조적 편향 재현).

**실행 결과** (PYTHONIOENCODING=utf-8):

| 입력 | 기대 | 실제 |
|---|---|---|
| `3 + 5` | 8 | `= 8` ✔ |
| `10 - 4` | 6 | `= 6` ✔ |
| `7 * 6` | 42 | `= 42` ✔ |
| `10 / 3` | 3.333... | `= 3.33333` ✔ |
| `5 / 0` | 에러 | `오류: 0으로 나눌 수 없습니다.` ✔ |
| `abc` | 에러 | `오류: 입력 형식은 '<숫자> <연산자> <숫자>' 입니다.` ✔ |
| `2 +` | 에러 | 동일 오류 메시지 ✔ |
| `quit` | 종료 | `종료합니다.` ✔ |

**관찰**:
- 요청 구체화(단일 파일명 명시)로 의도한 산출에 도달.
- 그러나 **워크플로우 관성은 여전함** — `calc_analytics/` 분석 패키지가 불필요하게 함께 생성됨.
- Windows bash 콘솔에서 한글이 cp949로 깨짐 → `PYTHONIOENCODING=utf-8 + -X utf8` 로 정상 출력 확인.

---

### 세션 ③ — Phase 2 우선순위 1: pytest 하네스 정식화

**선행 설계 결정 (사용자 승인 후 진행)**:

1. **FakeProvider 응답 포맷 = A안** (`Thought: ...\nFinal Answer: ...`)
   - CrewAI 1.14.1 `crewai.agents.parser`의 `FINAL_ANSWER_ACTION = "Final Answer:"` 와 1:1 정합.
   - `requirements.txt`에서 `crewai==1.14.1` 버전 고정.
2. **최소 침습** — 에이전트·워크플로우 코드는 수정 금지. `get_llm_provider`를 **두 네임스페이스**에서 monkeypatch.
3. **`tmp_path`로 `outputs/` 격리** — 워크플로우 E2E 테스트.
4. **pytest-socket 추가는 승인**했지만 실행 중 Windows 호환 이슈 발견.

**구현 순서**:
1. `git checkout -b phase2/pytest-harness`
2. CrewAI parser 소스 확인 (`.venv/Lib/site-packages/crewai/agents/parser.py`), `FINAL_ANSWER_ACTION` 상수 확인.
3. `pyproject.toml` 신규 — `[tool.pytest.ini_options]` + `[tool.ruff]` (line-length 100, py313).
4. `requirements.txt` — pytest 3종 추가 + CrewAI 버전 고정 근거 주석.
5. `.venv/Scripts/pip install pytest pytest-mock pytest-socket` — pytest 9.0.3 / mock 3.15.1 / socket 0.7.0 설치.
6. `src/tests/conftest.py` 작성 — FakeProvider + 3개 autouse fixture.
7. 어댑터 테스트 단독 통과 검증.

**중간 발견된 이슈 (설계 재검토)**:
- **`pytest-socket`의 `disable_socket()` 이 Windows `ProactorEventLoop`의 내부 `socket.socketpair()`까지 차단**.
- 원인: `NexusAlphaLLM.call()` → `anyio.run()` → `asyncio.new_event_loop()` → `ProactorEventLoop.__init__` → `_make_self_pipe()` → `socket.socketpair()`.
- 로컬 파이프 생성까지 막혀 **테스트 인프라 자체가 작동 불가**.
- **결정 (사용자 승인)**: pytest-socket autouse 제거, `requirements.txt`·`conftest.py`·`pyproject.toml`에 근거 주석, Linux CI에서 `--disable-socket` opt-in으로 분리. 완료 보고서 §3-1에 기록.

**구현 완료 후 검증**:
```
collected 6 items
src/tests/test_crewai_adapter.py::test_adapter_uses_backend_provider_from_factory PASSED
src/tests/test_crewai_adapter.py::test_adapter_call_returns_fake_response PASSED
src/tests/test_cto_agent.py::test_cto_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_data_analyst_agent.py::test_data_analyst_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_python_engineer_agent.py::test_python_engineer_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_workflow_analyze_and_implement.py::test_run_analyze_and_implement_produces_three_stage_artifacts PASSED
6 passed, 42 warnings in 7.72s
```

**산출물**:
- 신규: `pyproject.toml`, `src/tests/conftest.py`, `docs/progress/phase2_priority1_complete.md`
- 수정: `requirements.txt`, `docs/context/next_session_context.md`, 5개 `src/tests/test_*.py`
- 커밋: `29e1ce1 🧪 Phase 2 우선순위 1: pytest 하네스 정식화`

---

### 세션 ④ — Push & Pull Request

**경과**:
1. `git status` / `git log --oneline -3` 로 커밋 상태 확인.
2. `gh` CLI 미설치 확인.
3. `git push -u origin phase2/pytest-harness` 성공.
4. 원격 head가 로컬 `29e1ce1` 과 동일함을 `ls-remote`로 재확인.
5. PR 생성 URL 및 본문 초안을 사용자에게 제공.
6. (사용자 측) 웹에서 PR #1 생성 후 main에 merge → merge commit `c2c2a85` 생성.

---

### 세션 ⑤ — v3/v4 설계 문서 반영

**작업**:
1. `git checkout main && git pull origin main` → `c2c2a85` 동기화.
2. `git checkout -b docs/architecture-v3-v4`
3. `docs/architecture/` 폴더 신설 + 3개 문서 작성:

#### A) [nexus_alpha_v3.md](../architecture/nexus_alpha_v3.md) — 자율 반복 루프

- Phase 2.5 신설.
- 신규 에이전트 4종:
  - **Requirement Expander** — 자연어 요청 → 요구 스펙 YAML (assumptions / open_questions 명시).
  - **Gap Analyst** — 산출물 vs 스펙 비교, stagnation 필드 포함.
  - **Convergence Judge** — 결정표 기반 (LLM 자유 추론 배제). `COMPLETE` / `IMPROVE_NEEDED` / `BLOCKED`.
  - **Iteration Controller** — LangGraph `StateGraph`, LLM 호출하지 않는 결정론 레이어.
- 안전장치 5종: `max_iterations=5`, budget gate, stagnation detection (2연속 0 해소), feedback 순환 방지, LangFuse 관측.
- 열린 질문 4개를 본문 §10에 기록.

#### B) [nexus_alpha_v4.md](../architecture/nexus_alpha_v4.md) — 완전 자율 빌드

- 비전: *"계산기 만들어줘" 한 마디 → 다운로드 가능한 `setup.exe`*.
- 간극 분석: 기존 산출이 "코드 스니펫", 사용자 기대가 "실행 파일" — 디자인/빌드/패키징/배포 4단계 부재가 원인.
- Phase 4 (GUI 자동 생성, 4명): UI/UX Analyst · GUI Designer · GUI Code Generator · Theme Designer.
- Phase 4.5 (빌드 & 패키징, 5명): Build Engineer · Dependency Analyzer · Asset Manager · Installer Creator · Platform Tester.
- Phase 5 (배포 자동화, 4명): Release Manager · Changelog Generator · Update Checker · Distribution Agent.
- 기술 선택 매트릭스: PyInstaller→Nuitka→cx_Freeze, Tkinter→Flet→PyQt6, GitHub Releases→S3→로컬.
- 열린 질문 6개를 본문 §10에 기록.

#### C) [nexus_alpha_org_v4.md](../architecture/nexus_alpha_org_v4.md) — 확정 조직도

- **C-Level 3 + 8 본부 = 9개 조직 단위, 총 46명**.
- 본부 합계 검증: 3 + 5 + 4 + 9 + 6 + 3 + 4 + 3 + 9 = **46 ✓**.
- 신설 본부: 🆕 디자인(3, Phase 4), 🆕 빌드 & 배포(9, Phase 4.5/5).
- 디렉터리 매핑: `src/agents/design/`(Phase 4), `src/agents/build_release/`(Phase 4.5).
- UI/UX Analyst는 **디자인 본부가 아닌 기획·설계 본부** — 관심사 분리(Analysis vs Production).
- 현재 진행률: **46명 중 4명 구현 완료 (~6.5%)**.

#### 부수 갱신

- `README.md` — 최종 비전 + 8 본부 인원 표 + Phase 진행 현황 + 테스트 실행 가이드.
- `docs/context/next_session_context.md` — Phase 2-P1 main merge 반영, v3/v4 경로 기록, 로드맵을 v4까지 풀 스코프로 확장.

**커밋**: `fc009bc 📐 docs: v3/v4 설계 문서 및 조직도 반영` (5 files changed, +1090/-32).

**Push**: `git push -u origin docs/architecture-v3-v4` 성공. PR URL: https://github.com/SongJongwon/nexus-alpha/pull/new/docs/architecture-v3-v4

---

## 3. 커밋/브랜치 요약

```
(현재 로컬 브랜치 docs/architecture-v3-v4)

fc009bc 📐 docs: v3/v4 설계 문서 및 조직도 반영       ← 본 세션 (세션 ⑤)
c2c2a85 Merge pull request #1 from SongJongwon/phase2/pytest-harness  ← 세션 ④ 결과
29e1ce1 🧪 Phase 2 우선순위 1: pytest 하네스 정식화   ← 본 세션 (세션 ③)
354ccfb 📌 다음 세션 컨텍스트 파일 추가
160947c 🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우 성공
70af92b 🎉 Phase 1 MVP 완료: 3명 에이전트 협업 워크플로우
...
```

**원격 브랜치 상태**:
- `main` — `c2c2a85` (Phase 2-P1 merge됨)
- `phase2/pytest-harness` — `29e1ce1` (PR #1로 main merge 후 잔존)
- `docs/architecture-v3-v4` — `fc009bc` (PR 대기)

**Git 미처리 상태**:
- `src/tests/run_calculator_workflow.py` — 세션 ①~② 에서 작성한 1회성 러너. Phase 2-P1 / docs 작업 범위 밖이라 untracked 유지. 필요 시 별도 정리 PR로 처리.

---

## 4. 핵심 설계 결정 기록

### 4-1. FakeProvider는 CrewAI 파서 계약에 정합 (세션 ③)
- `Thought: ...\nFinal Answer: ...` 포맷으로 단일 호출 AgentFinish 수렴.
- CrewAI 버전을 `==1.14.1` 로 고정, 업그레이드 시 테스트 재검증 필수.

### 4-2. 에이전트·워크플로우 코드는 테스트 위해 수정하지 않음 (세션 ③)
- `src.llm.factory.get_llm_provider` + `src.llm.crewai_adapter.get_llm_provider` 두 네임스페이스 동시 monkeypatch로 최소 침습.
- 기존 `if __name__ == "__main__"` 직접 실행 경로는 그대로 보존.

### 4-3. pytest-socket autouse 제거 (세션 ③)
- Windows ProactorEventLoop의 내부 socketpair까지 차단하는 부작용.
- 네트워크 차단은 FakeProvider가 주력 안전망.
- Linux CI에서 `pytest --disable-socket` opt-in으로 분리 (Phase 2-P1B).

### 4-4. 요청 라우팅 필요성 신호 (세션 ①~②)
- "계산기 만들어줘"가 데이터 분석 템플릿으로 귀결되는 구조적 편향 관찰.
- Engineer task 프롬프트의 `loader/transform/metrics/chart/render/cli` 강제 구조가 원인.
- Phase 2-P5(요청 라우팅)에서 "단일 파일 구현" vs "데이터 분석 파이프라인" 분기 필수.

### 4-5. v3 Convergence Judge는 결정표 기반 (세션 ⑤, v3 문서)
- LLM 자유 추론이 아닌 결정표로 판정해 루프 안정성 확보.
- LLM 호출은 근거 문장 생성 때만 사용.

### 4-6. v4의 UI/UX Analyst는 디자인 본부가 아닌 기획·설계 본부 (세션 ⑤, org 문서)
- *"어떤 UI 패턴이 적절한가"* 판정은 분석이고, 디자인 본부는 그 결과로 실제 시각 디자인·코드를 생산.
- 관심사 분리 (Analysis vs Production) 원칙.

---

## 5. 다음 세션에 넘기는 컨텍스트

- **즉시 진행 가능한 작업**: Phase 2 우선순위 2 — QA 에이전트 (`src/agents/qa/code_reviewer.py`). `docs/context/next_session_context.md` §6 참조.
- **진행 전 처리**: `docs/architecture-v3-v4` 브랜치의 PR 생성·merge.
- **선택 과제**: `src/tests/run_calculator_workflow.py` 정리 (유지 / 삭제 / 커밋 중 결정).
- **원격 정리 선택**: `phase2/pytest-harness` 브랜치는 merge 됐으므로 GitHub 웹에서 삭제 가능 (로컬도 `git branch -d phase2/pytest-harness` 로 정리 가능).

---

## 6. 참조 문서 빠른 링크

- [docs/architecture/nexus_alpha_v3.md](../architecture/nexus_alpha_v3.md) — 자율 반복 루프 설계
- [docs/architecture/nexus_alpha_v4.md](../architecture/nexus_alpha_v4.md) — 완전 자율 빌드 설계
- [docs/architecture/nexus_alpha_org_v4.md](../architecture/nexus_alpha_org_v4.md) — 확정 조직도 (46명)
- [docs/progress/phase1_complete.md](./phase1_complete.md) — Phase 1 MVP 완료 보고서
- [docs/progress/phase2_priority1_complete.md](./phase2_priority1_complete.md) — Phase 2-P1 완료 보고서
- [docs/context/next_session_context.md](../context/next_session_context.md) — 최신 세션 인계 문서
