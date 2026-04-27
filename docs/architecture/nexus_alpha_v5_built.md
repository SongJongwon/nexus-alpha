# 🏢 Nexus Alpha 실제 구축 구성안 v5



**━ AI 소프트웨어 자동 생성 공장 (Software Generation Factory) ━**

> **작성일**: 2026-04-21 (v5 — v1/v3/v4 통합·보강 최신판)
> **선행 문서**:
> - **v1** ([최종_상세_구성안.md](.) — 2026-04-17): RPA 원안
> - **v3** ([nexus_alpha_v3.md](./nexus_alpha_v3.md) — 2026-04-17): 자율 반복 루프 설계
> - **v4** ([nexus_alpha_v4.md](./nexus_alpha_v4.md) — 2026-04-17): 자연어 → .exe 풀 비전 설계
> - **v4 조직도** ([nexus_alpha_org_v4.md](./nexus_alpha_org_v4.md)): 9개 본부 24명 매핑
>
> **본 문서 (v5) 의 역할**: v1 의 RPA 비전 원안 + v3/v4 의 설계 깊이 + 2026-04-17~21
> 4일간 실제 구축된 상태를 **단일 문서로 통합**. "설계 vs 실제" 가 한 페이지에서 확인 가능.
>
> **현재 상태**: Phase 0 → Phase 5 완료, v3 반복 루프 + v4 풀 비전 통합
> **테스트 커버리지**: pytest **138 passed**
> **활성 PR**: PR #24 (E2E 재검증 결과 — Issue 4 발견)
> **다음 PR**: Issue 4 수정 (GUI 4개 에이전트의 Final Answer 본문 누락)

---

## 📑 v1 대비 핵심 변경

### 🔄 비전 피벗

| 구분          | v1 (원안)                             | v5 (실제)                                       |
| ----------- | ----------------------------------- | --------------------------------------------- |
| **포지셔닝**    | 업무 자동화 / RPA 전문 AI 가상 기업            | **소프트웨어 자동 생성 공장**                            |
| **결과물**     | Python 자동화 스크립트, Excel 크롤러, RPA 패키지 | **단독 실행 GUI/CLI 앱 + .exe 빌드 + 릴리스 사양**        |
| **타겟 시나리오** | 반복 업무 (보고서·이메일·ERP 자동화)             | **자연어 요청 → 코드 → .exe → 릴리스** ("계산기 만들어줘" 한 줄) |
| **핵심 사용자**  | 사무직 자동화 의뢰자                         | 개발자·기획자·일반 사용자 (자연어로 앱 의뢰)                    |

### 📊 구현 진행률

| 영역      | v1 계획                                          | v5 실제                                         | 상태                          |
| ------- | ---------------------------------------------- | --------------------------------------------- | --------------------------- |
| 에이전트 수  | ~30명 (6개 본부)                                   | **24명** (9개 본부)                               | 80% 구축                      |
| C-Level | CEO + CTO + CFO                                | **CTO + ConvergenceJudge**                    | 67% (CEO/CFO 미구축)           |
| 실행 엔진   | Playwright + PyAutoGUI + OpenPyXL              | **SandboxRunner** (Python 격리 실행)              | 30% (RPA 엔진 미구축)            |
| 빌드/배포   | DevOps Engineer + Docker                       | **Build 5인 + Release 4인 — 사양 산출만**            | 60% (실제 PyInstaller 호출 미통합) |
| UI      | Streamlit + Slack Bot                          | **CLI + 산출 파일 트리** (`outputs/workflow_<ts>/`) | 20%                         |
| 모니터링    | LangFuse + Helicone                            | **LangFuse 통합**                               | 100%                        |
| 지식 베이스  | Qdrant + Mem0 + Pattern Librarian              | **Curator + RAGSearcher** (메모리 기반)            | 40%                         |
| 보안 장치   | Credential Vault, Dry-Run, Rollback, Audit Log | **FakeProvider 테스트 격리만**                      | 10%                         |

---

## 🎯 실제 포지셔닝

> **Nexus Alpha v5 는 자연어 요청 한 줄을 받아 다중 AI 에이전트가 협업하여
> 분석 → 설계 → 코드 → 빌드 → 배포 전 과정을 자동 생성하는
> "소프트웨어 자동 생성 공장" 입니다.**

### 골든 패스

```
"계산기 만들어줘"
        ↓
[UI/UX Analyst] → form_factor=single_window, need_gui=yes
        ↓
[CTO] → Tkinter 전략, MVC 분리
        ↓
[GUI Designer] → 와이어프레임 + 위젯 트리
        ↓
[Theme Designer] → WCAG AA 컬러 토큰
        ↓
[GUI Code Generator] → calculator.py (단독 실행 가능)
        ↓
[Code Reviewer] → APPROVED / NEEDS_REVISION
        ↓
[Dep Analyzer → Build Engineer → Asset Manager → Installer Creator → Platform Tester]
        ↓ (Phase 4.5 빌드 사양)
[Release Manager → Changelog Generator → Update Checker → Distribution Agent]
        ↓ (Phase 5 릴리스 사양)
outputs/workflow_<ts>/  →  18개 .md + code/*.py
```

---

## 🏗️ 실제 조직도 (9개 본부, 24명)

### 0. C-Level (2명) ⚠️ 부분 구축

| 직책                    | 파일                                                                            | 역할                                                    | 상태                          |
| --------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- | --------------------------- |
| **CTO**               | [c_level/cto.py](../../src/agents/c_level/cto.py)                             | 기술 전략 / 구현 접근 / 리스크 / 권장 순서 4섹션 산출                    | ✅                           |
| **Convergence Judge** | [c_level/convergence_judge.py](../../src/agents/c_level/convergence_judge.py) | v3 반복 루프의 종결 판정 (COMPLETE / IMPROVE_NEEDED / BLOCKED) | ✅                           |
| ~~CEO~~               | —                                                                             | 전체 워크플로우 총괄, 사용자 요구 해석                                | ❌ 미구축                       |
| ~~CFO~~               | —                                                                             | 토큰/API 비용 모니터링, ROI 산출                                | ❌ 미구축 (LangFuse 자동 추적으로 대체) |

**v1 대비**: CEO/CFO 미구축 — 사용자 요구 해석은 **UI/UX Analyst** 와 **CTO** 의 첫 단계 분석으로 분산. 비용 모니터링은 **LangFuse trace + cost** 로 자동화.

---

### 1. 분석 본부 (3명)

| 직책                       | 파일                                                                                    | 역할                                         |
| ------------------------ | ------------------------------------------------------------------------------------- | ------------------------------------------ |
| **Data Analyst**         | [analysis/data_analyst.py](../../src/agents/analysis/data_analyst.py)                 | 데이터 품질 / 지표 5개 / 차트 3종 / 이상치 / 분석가 코멘트 5섹션 |
| **Gap Analyst**          | [analysis/gap_analyst.py](../../src/agents/analysis/gap_analyst.py)                   | v3 반복 루프 — 사양 vs 산출 갭 분석                   |
| **Requirement Expander** | [analysis/requirement_expander.py](../../src/agents/analysis/requirement_expander.py) | 모호한 요청을 구체적 사양으로 확장                        |

**v1 대비**: Process Discovery / BA / ROI Calculator / Feasibility Checker 미구축 (RPA 특화 분석 — 비전 피벗으로 불요).

---

### 2. 기획 및 설계 본부 (1명)

| 직책                | 파일                                                                      | 역할                                                      |
| ----------------- | ----------------------------------------------------------------------- | ------------------------------------------------------- |
| **UI/UX Analyst** | [planning/ui_ux_analyst.py](../../src/agents/planning/ui_ux_analyst.py) | GUI vs CLI 판정 (1순위), form_factor 5종 결정, ui_spec YAML 산출 |

**v1 대비**: PM / Workflow Designer / Integration Architect / Error Handling Designer 미구축 — UI/UX Analyst 단독으로 진입 라우팅 담당.

---

### 3. 디자인 본부 (3명) — 신규 (v1 부재)

| 직책                     | 파일                                                                            | 역할                                                         |
| ---------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **GUI Designer**       | [design/gui_designer.py](../../src/agents/design/gui_designer.py)             | 와이어프레임 + 위젯 트리 + 인터랙션 흐름                                   |
| **Theme Designer**     | [design/theme_designer.py](../../src/agents/design/theme_designer.py)         | WCAG AA 컬러 토큰 / 타이포 / 스페이싱 JSON                            |
| **GUI Code Generator** | [design/gui_code_generator.py](../../src/agents/design/gui_code_generator.py) | Tkinter / customtkinter / Flet / PyQt6 중 선택 → 실행 가능 GUI 코드 |

**v1 → v5 추가 본부**: GUI 앱 생성을 위한 *시각 디자인 → 실행 코드* 변환 전담. v1 의 "자동화 스크립트" 비전에는 없던 부서.

---

### 4. 엔지니어링 본부 (1명)

| 직책                  | 파일                                                                                | 역할                                  |
| ------------------- | --------------------------------------------------------------------------------- | ----------------------------------- |
| **Python Engineer** | [engineering/python_engineer.py](../../src/agents/engineering/python_engineer.py) | 단독 실행 가능한 Python 코드 + pytest 단위 테스트 |

**v1 대비**: Web Scraping Specialist / Desktop Automation Specialist / API Integration Developer / Data Parser Engineer / DevOps Engineer 미구축 — 비전 피벗으로 RPA 특화 엔지니어 불요. 일반 Python Engineer 1명으로 도메인 중립 (PR #23 에서 데이터 분석 편향 제거).

---

### 5. QA 본부 (1명)

| 직책                | 파일                                                          | 역할                                                                                                    |
| ----------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Code Reviewer** | [qa/code_reviewer.py](../../src/agents/qa/code_reviewer.py) | 5단 정적 점검 (타입 힌트 / docstring / pytest 가능성 / 경계 예외 / 모듈 분리), `Final Answer: APPROVED \| NEEDS_REVISION` |

**v1 대비**: Robustness Tester / Security Auditor / Performance Engineer / Compliance Officer 미구축 — Code Reviewer 1명으로 통합. 향후 보안·성능 분리 가능.

---

### 6. 빌드 & 배포 본부 (9명) — 신규 (v1 부재)

#### Phase 4.5 — 빌드 사슬 (5명)

| 직책                      | 파일                                                                                            | 역할                                              |
| ----------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **Dependency Analyzer** | [build_release/dependency_analyzer.py](../../src/agents/build_release/dependency_analyzer.py) | 코드에서 의존성 추출 + YAML 보고서                          |
| **Build Engineer**      | [build_release/build_engineer.py](../../src/agents/build_release/build_engineer.py)           | PyInstaller / cx_Freeze / Nuitka 중 선택 + spec 파일 |
| **Asset Manager**       | [build_release/asset_manager.py](../../src/agents/build_release/asset_manager.py)             | 아이콘 / 리소스 매니페스트                                 |
| **Installer Creator**   | [build_release/installer_creator.py](../../src/agents/build_release/installer_creator.py)     | NSIS / Inno Setup 인스톨러 스크립트                     |
| **Platform Tester**     | [build_release/platform_tester.py](../../src/agents/build_release/platform_tester.py)         | Sandbox 실행 + narration 보고서                      |

#### Phase 5 — 릴리스 사슬 (4명)

| 직책                      | 파일                                                                                            | 역할                                                  |
| ----------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **Release Manager**     | [build_release/release_manager.py](../../src/agents/build_release/release_manager.py)         | SemVer 결정 + RELEASE.md 초안                           |
| **Changelog Generator** | [build_release/changelog_generator.py](../../src/agents/build_release/changelog_generator.py) | Keep a Changelog 형식                                 |
| **Update Checker**      | [build_release/update_checker.py](../../src/agents/build_release/update_checker.py)           | 자동 업데이트 모듈 사양 (HTTPS / TLS / SHA256 / 채널 allowlist) |
| **Distribution Agent**  | [build_release/distribution_agent.py](../../src/agents/build_release/distribution_agent.py)   | GitHub Release / 채널별 배포 사양                          |

**v1 → v5 추가 본부**: v1 의 DevOps Engineer 1명을 **9명 사슬** 로 세분화. 단, **실제 PyInstaller 호출 / .exe 빌드 / 파일 업로드는 외부 자동화 위임** — 본 본부는 *사양 산출만* (LLM 9건).

---

### 7. 지식 본부 (2명)

| 직책               | 파일                                                                      | 역할              |
| ---------------- | ----------------------------------------------------------------------- | --------------- |
| **Curator**      | [knowledge/curator.py](../../src/agents/knowledge/curator.py)           | 과거 프로젝트 산출 큐레이션 |
| **RAG Searcher** | [knowledge/rag_searcher.py](../../src/agents/knowledge/rag_searcher.py) | 유사 패턴 검색        |

**v1 대비**: Pattern Librarian / Documentation Agent 미구축. Vector DB (Qdrant) 미통합 — 메모리 기반 단순 검색.

---

### 8. 운영 지원 본부 (1명)

| 직책                 | 파일                                                                            | 역할                                                          |
| ------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **Sandbox Runner** | [operations/sandbox_runner.py](../../src/agents/operations/sandbox_runner.py) | 격리 환경에서 생성 코드 실행 (deterministic 함수 + Agent narration 하이브리드) |

**v1 대비**: Project Coordinator / Human Liaison / Monitoring Agent 미구축. Monitoring 은 **LangFuse 자동화** 로 대체.

---

## 📊 실제 워크플로우

### 메인 워크플로우 — `analyze_and_implement`

[src/workflows/analyze_and_implement.py](../../src/workflows/analyze_and_implement.py)

```python
run_analyze_and_implement(
    user_request="계산기 만들어줘",
    enable_gui_branch=True,      # Phase 4 GUI 분기
    enable_build_branch=True,    # Phase 4.5 빌드 사슬
    enable_release_branch=True,  # Phase 5 릴리스 사슬
    previous_version="0.1.0",
    repo_url="https://github.com/...",
)
```

**4-agent 기본 (backward compat 보장)**:

```
CTO → Data Analyst → Python Engineer → Code Reviewer
```

**Phase 4 GUI 분기** (`enable_gui_branch=True`):

```
UI/UX Analyst → [need_gui 판정]
              ├── gui:  CTO → Analyst → GUI Designer → Theme → GUI Code Gen → Reviewer
              └── cli:  CTO → Analyst → Engineer → Reviewer (UI/UX context 추가)
```

**Phase 4.5 빌드 사슬** (`enable_build_branch=True`):

```
... 메인 체인 종료 ...
→ Dep Analyzer → Build Engineer → Asset Manager → Installer Creator → Platform Tester
```

**Phase 5 릴리스 사슬** (`enable_release_branch=True`):

```
... 빌드 사슬 종료 ...
→ Release Manager → Changelog Generator → Update Checker → Distribution Agent
```

### 보조 워크플로우

| 파일                                                             | 역할                                                     |
| -------------------------------------------------------------- | ------------------------------------------------------ |
| [iterative_loop.py](../../src/workflows/iterative_loop.py)     | v3 LangGraph StateGraph — 반복 개선 (Convergence Judge 결정) |
| [build_workflow.py](../../src/workflows/build_workflow.py)     | Phase 4.5 빌드 사슬 단독 실행 가능                               |
| [release_workflow.py](../../src/workflows/release_workflow.py) | Phase 5 릴리스 사슬 단독 실행 가능                                |
| [router.py](../../src/workflows/router.py)                     | Intent → 워크플로우 라우팅 (BUILD / ANALYZE / RELEASE)         |

---

## 🛠️ 실제 기술 스택

### 사용 중

| 카테고리        | v1 계획               | v5 실제                                 | 비고                              |
| ----------- | ------------------- | ------------------------------------- | ------------------------------- |
| **오케스트레이션** | CrewAI + LangGraph  | **CrewAI 1.14.1** + **LangGraph**     | v3 부터 LangGraph 도입              |
| **LLM 어댑터** | (미명시)               | **NexusAlphaLLM** + Anthropic SDK     | Claude Opus 4.7 / agent_sdk     |
| **모니터링**    | LangFuse + Helicone | **LangFuse**                          | Helicone 미통합                    |
| **테스트**     | pytest              | **pytest + FakeProvider monkeypatch** | 138 passed, 네트워크 차단 자동          |
| **CI**      | (미명시)               | **GitHub Actions (ubuntu, py3.13)**   | PR #22 에서 `--disable-socket` 제거 |
| **로컬 환경**   | (미명시)               | **Windows 11 + Python 3.13**          | ProactorEventLoop 호환            |

### 미통합 (v1 계획 대비)

- ❌ **AutoGen** (Reviewer ↔ Developer 대화 루프 — v3 LangGraph 로 대체)
- ❌ **LlamaIndex** (RAG — 단순 in-memory 검색으로 대체)
- ❌ **Qdrant / Mem0** (Vector DB — 미통합)
- ❌ **Playwright / PyAutoGUI** (RPA 실행 엔진 — 비전 피벗으로 불요)
- ❌ **Prefect / Airflow** (스케줄링 — CI 가 대체)
- ❌ **Streamlit / Gradio / Slack Bot** (UI — CLI + 파일 트리만)

---

## 🛡️ 실제 안전 장치

### v1 계획 대비

| 장치                      | v1             | v5                   | 비고                     |
| ----------------------- | -------------- | -------------------- | ---------------------- |
| **Dry-Run 모드**          | 필수             | ❌ 미구축                | Sandbox 격리 실행으로 부분 대체  |
| **Credential Vault**    | 필수             | ⚠️ `.env` + dotenv 만 | 암호화 미적용                |
| **Rate Limiting**       | 필수             | ❌ 미구축                | LLM API 호출만 — RPA 미사용  |
| **Rollback Script**     | 필수             | ❌ 미구축                | git revert 로 대체        |
| **Audit Log**           | 필수             | ✅ **LangFuse trace** | 자동                     |
| **Kill Switch**         | 필수             | ⚠️ Ctrl+C 만          | 런타임 중단 메커니즘 부재         |
| **Max Iteration Limit** | 3회             | ✅ **v3 ITER_CAP**    | Convergence Judge 가 강제 |
| **Token Budget Gate**   | CFO 80%/100%   | ✅ **v3 BUDGET 결정**   | LangFuse cost 기반       |
| **Consensus Protocol**  | CEO+CTO+CPO 3인 | ❌ 미구축                | CTO 단독 결정              |
| **HITL Checkpoint**     | 필수             | ⚠️ CLI 콘솔 출력만        | UI 부재로 비대화형            |

### 신규 안전 장치 (v1 부재)

- ✅ **FakeProvider monkeypatch** (autouse) — pytest 시 네트워크 차단 자동
- ✅ **LangFuse no-op** (autouse) — pytest 시 모니터링 호출 차단 자동
- ✅ **Sandbox 격리** — 생성 코드 실행 시 별도 프로세스 + 타임아웃
- ✅ **Update Checker 5원칙** — HTTPS / TLS verify / 채널 allowlist / SHA256 / no auto-apply

---

## 📁 실제 프로젝트 구조

```
nexus-alpha/
├── src/
│   ├── agents/                  # 9개 본부, 24명
│   │   ├── c_level/             #   CTO, ConvergenceJudge
│   │   ├── analysis/            #   DataAnalyst, GapAnalyst, RequirementExpander
│   │   ├── planning/            #   UIUXAnalyst
│   │   ├── design/              #   GUIDesigner, ThemeDesigner, GUICodeGenerator
│   │   ├── engineering/         #   PythonEngineer
│   │   ├── qa/                  #   CodeReviewer
│   │   ├── knowledge/           #   Curator, RAGSearcher
│   │   ├── operations/          #   SandboxRunner
│   │   └── build_release/       #   Build 5 + Release 4 = 9명
│   │
│   ├── workflows/               # 메인 + 보조 5개
│   │   ├── analyze_and_implement.py    # 메인 (4-agent + GUI/Build/Release 분기)
│   │   ├── iterative_loop.py           # v3 LangGraph 반복 개선
│   │   ├── build_workflow.py           # Phase 4.5 단독
│   │   ├── release_workflow.py         # Phase 5 단독
│   │   └── router.py                   # Intent 라우팅
│   │
│   ├── llm/                     # NexusAlphaLLM + CrewAI 어댑터
│   ├── monitoring/              # LangFuse 클라이언트
│   └── tests/                   # 33개 파일, 138 passed
│
├── docs/
│   ├── architecture/
│   │   ├── nexus_alpha_v3.md         # v3 (반복 루프) 설계
│   │   ├── nexus_alpha_v4.md         # v4 (풀 비전) 설계
│   │   ├── nexus_alpha_org_v4.md     # 조직도 v4
│   │   └── nexus_alpha_v5_built.md   # 본 문서 (실제 구축)
│   ├── progress/                # Phase 별 완료 보고서 + E2E 검증 기록
│   └── context/                 # CrewAI 호환성 노트 등
│
├── scripts/
│   └── run_e2e_verification.py  # 실 LLM E2E 시나리오
│
├── outputs/                     # 워크플로우 산출 (workflow_<ts>/)
├── .github/workflows/ci.yml     # ubuntu py3.13, pytest -v --tb=short
├── requirements.txt             # crewai==1.14.1 (pinned)
└── .env                         # ANTHROPIC_API_KEY, LANGFUSE_*
```

---

## 🗺️ Phase 진행 실적 (v1 로드맵 vs 실제)

| Phase              | v1 계획                  | v5 실제 결과                                                       | PR 번호     | 상태      |
| ------------------ | ---------------------- | -------------------------------------------------------------- | --------- | ------- |
| **Phase 0**        | 환경 준비 (3~5일)           | Python 3.13 + crewai 1.14.1 + pytest 하네스                       | —         | ✅       |
| **Phase 1**        | MVP — 3개 부서 추상화 (1~2주) | CTO + Data Analyst + Engineer (3-agent)                        | PR #1~3   | ✅       |
| **Phase 2**        | 6개 본부 구축 (2~3주)        | **4-agent + Code Reviewer (P2) + CI 안정화 (P1B)**                | PR #5~22  | ✅       |
| **Phase 2.5 / v3** | (v1 미계획)               | **LangGraph 반복 루프 + Convergence Judge**                        | PR #6~10  | ✅       |
| **Phase 3**        | 실행 엔진 통합 (2~3주)        | **Knowledge agents + Sandbox Runner** (RPA 엔진은 미통합)            | PR #11~14 | ⚠️      |
| **Phase 4**        | 하이브리드 UI (1~2주)        | **GUI 분기 (UI/UX Analyst + 디자인 본부 3명)**                         | PR #15~17 | ✅       |
| **Phase 4.5**      | (v1 미계획)               | **빌드 사슬 5명 (Dep / Build / Asset / Installer / Platform Test)** | PR #18    | ✅       |
| **Phase 5**        | 파일럿 실행 (2주)            | **릴리스 사슬 4명 + v4 풀 비전 통합**                                     | PR #19~21 | ✅       |
| **Phase 5 사후**     | (v1 미계획)               | **E2E 검증 → PR #23 수정 → PR #24 재검증 (이슈 4 발견)**                  | PR #23~24 | 🔄 진행 중 |

**총 PR**: 24개 / **누적 기간**: 4일 (2026-04-17 ~ 2026-04-21) / **테스트**: 138 passed

---

## 🚧 현재 미해결 이슈

### Issue 4 — GUI 에이전트 산출 본문 누락 (BLOCKING) 🔴

**증상**: 4개 GUI 에이전트 (UI/UX, Designer, Theme, Code Gen) 의 `task.output.raw` 가
Final Answer summary 한 줄만 캡처. 본문 마크다운 + 코드 블록 모두 손실.

**근본 원인**: 4개 backstory 의 `"마지막 줄은 반드시 Final Answer: <summary>로 시작..."`
지시가 LLM 으로 하여금 본문을 Final Answer **앞** 에 두게 함. CrewAI 의 파서는
**이후 텍스트만** 캡처 → 본문 영구 손실.

**영향**: GUI 경로의 `code/` 디렉터리 비어있음 → `python <entry>.py` 검증 불가.

**상세**: [docs/progress/e2e_verification_issues.md](../progress/e2e_verification_issues.md)

**해결 계획**: 별도 PR 에서 4개 backstory 수정 또는 `_task_output_text` 헬퍼에 길이 기반 fallback 추가.

---

## 🎨 Phase 4 — GUI 설계 상세 (v4 §3 통합)

### UI/UX Analyst 가 답해야 할 5가지 질문 (v4 §3-4)

| # | 질문 | 산출 필드 | 구축 상태 |
|---|---|---|---|
| 1 | 단일 윈도우인가, 다중 윈도우/탭인가? | `questions.windows` | ✅ |
| 2 | 데이터 입출력 단위는? (단일 값 / 표 / 시계열 / 미디어) | `questions.data_unit` | ✅ |
| 3 | 상태(state)는 휘발성인가, 영속인가? | `questions.state` | ✅ |
| 4 | 사용자 학습곡선은 몇 분인가? | `questions.learning_curve_min` | ✅ |
| 5 | 접근성 요구가 있는가? | `questions.accessibility` | ✅ |

5가지 답이 [`ui_spec.yaml`](../../src/agents/planning/ui_ux_analyst.py) 의 `questions:` 키에
모두 채워져야 함. 빠지면 GUI Designer 가 다음 단계에서 추측을 누적.

**1순위 결정 — `need_gui: yes/no`**: 5가지 질문보다 먼저 결정. PR #23 에서 키워드
명시화 (`계산기/편집기/뷰어/타이머/메모장/...` → `need_gui=yes` 강제) 로 보강됨.

### GUI 프레임워크 선택 정책 (v4 §3-3, 구축 확인)

| 요청 복잡도 | 기본 프레임워크 | 이유 | 실측 |
|---|---|---|---|
| 단순 (위젯 5개 이하, 단일 윈도우) | **Tkinter + customtkinter** | 표준 라이브러리, 의존성 0, .exe 작음 | E2E (계산기) 에서 자동 선택됨 ✅ |
| 중간 (멀티 윈도우, 차트, 테이블) | **Flet** (Flutter 기반) | 단일 코드베이스로 데스크톱·웹·모바일 동시 | 미검증 ⚠️ |
| 복잡 (미디어, 고급 인터랙션) | **PyQt6** | 성숙도, 위젯 풍부 | 미검증 ⚠️ |

**선택 주체**: GUI Code Generator 가 `recommended_framework_hint` 를 *참고만* 하고
최종 선택. UI/UX Analyst 의 hint 와 다르게 결정할 때는 *근거 한 줄* 필수.

---

## 📦 Phase 4.5 — 빌드 설계 상세 (v4 §4 통합)

### Dependency Analyzer 가 잡아야 할 4가지 함정 (v4 §4-4)

| # | 함정 | 위험 | 구축 상태 |
|---|---|---|---|
| 1 | **Hidden imports** | `numpy`, `pandas`, `matplotlib` 등의 lazy import 가 PyInstaller 에 누락 | 사전 화이트리스트 강제 포함 — 명세 ✅ / 자동화 ⚠️ |
| 2 | **Native binaries** | `cv2`, `tensorflow` 등의 `.dll`/`.so` 누락 → 런타임 실패 | 명세 ✅ / 검증 ❌ |
| 3 | **License conflicts** | GPL 의존성 포함 시 산출물 강제 GPL 화 | 명세 ✅ / 자동 검출 ❌ |
| 4 | **OS-specific deps** | `win32api` 가 macOS 빌드에 들어가면 즉시 실패 | 명세 ✅ / 자동 차단 ❌ |

[dependency_analyzer.py](../../src/agents/build_release/dependency_analyzer.py) 는
4가지 함정 모두 backstory 에 명시. 단, **실제 import 그래프 분석 자동화는 미통합**
— LLM 이 코드 텍스트를 읽고 분석하는 수준. 향후 `pipdeptree` / `modulegraph` 통합 권장.

### Platform Tester 검증 항목표 (v4 §4-5, 구축 확인)

| 검증 항목 | 기준 | 실패 시 라우팅 | 구축 상태 |
|---|---|---|---|
| 빌드 산출물 실제 실행 | exit code 0 | Build Engineer 로 피드백 | 명세 ✅ / 자동 ❌ |
| 메인 윈도우 표시 | UI Automation 으로 확인 | GUI Code Generator 로 피드백 | 명세 ✅ / 자동 ❌ |
| 핵심 기능 1개 시나리오 (예: "1+1=2") | 자동 입력 → 출력 검증 | Engineer 로 피드백 | 명세 ✅ / 자동 ❌ |
| 시작 시간 | < 5초 | 경고만, 차단 안함 | 명세 ✅ |
| 산출물 크기 | < 200MB | 경고만, 차단 안함 | 명세 ✅ |

[platform_tester.py](../../src/agents/build_release/platform_tester.py) 는 v3 의 [sandbox_runner.py](../../src/agents/operations/sandbox_runner.py) 의
`run_python_package_in_sandbox` 결과를 narration 입력으로 활용. **실제 .exe 실행
검증은 미통합** (PyInstaller 미호출). 본 본부는 *사양 + narration 산출만*.

### 빌드 도구 선택 정책 1→2→3 폴백 (v4 §4-3)

| 우선 | 도구 | 적용 조건 | 구축 |
|---|---|---|---|
| 1 | **PyInstaller** | 일반적인 Python 앱 — 가장 검증됨 | 명세 ✅ |
| 2 | **Nuitka** | 성능 중요 (C 컴파일) 또는 PyInstaller 실패 시 | 명세 ✅ |
| 3 | **cx_Freeze** | 위 둘 다 실패 시 fallback | 명세 ✅ |

모두 실패 시 v3 루프의 BLOCKED 경로로 에스컬레이션 — Convergence Judge 가 종결.

---

## 🚀 Phase 5 — 배포 설계 상세 (v4 §5 통합)

### Distribution Agent 의 채널 우선순위 (v4 §5-3)

| 우선 | 채널 | 적용 조건 | 구축 |
|---|---|---|---|
| 1 | **GitHub Releases** | public 또는 private repo 가 있을 때 — 무료, 검증됨 | 명세 ✅ / 자동 업로드 ❌ |
| 2 | **사내 파일 서버 / 회사 클라우드** | 기업용 산출물 (외부 노출 금지) | 명세 ✅ |
| 3 | **S3 + presigned URL** | 일회성 공유, 만료 시간 설정 가능 | 명세 ✅ |
| 4 | **로컬 파일링** | 모든 채널 거부 시 fallback. 사용자에게 경로만 안내 | 명세 ✅ |

`privacy_level=public/corporate-internal/one-time-share` 입력값에 따라 [distribution_agent.py](../../src/agents/build_release/distribution_agent.py) 가 채널 선택.

### 보안 5원칙 — Update Checker (v4 §5-4 + PR #21)

| # | 원칙 | 구현 위치 | 구축 |
|---|---|---|---|
| 1 | **HTTPS 만 허용** | updater.py 내 URL 검증 | 명세 ✅ |
| 2 | **TLS 인증서 검증 필수** | `verify=True` 강제 | 명세 ✅ |
| 3 | **채널 allowlist** | 화이트리스트된 도메인만 통신 | 명세 ✅ |
| 4 | **SHA256 체크섬 검증** | 다운로드 파일 무결성 | 명세 ✅ |
| 5 | **자동 적용 금지 (no auto-apply)** | 사용자 확인 후 적용 | 명세 ✅ |

[update_checker.py](../../src/agents/build_release/update_checker.py) 는 *참조 구현 사양만 산출*
— 실제 통합은 Engineer 단계의 별도 작업.

### 코드 서명 (Code Signing) 정책 (v4 §5-4)

| OS | 권장 도구 | 비용 | 구축 |
|---|---|---|---|
| Windows | `signtool` + EV cert | EV 인증서 연 $300~$500 | 명세 ✅ / 통합 ❌ |
| macOS | Apple Developer ID | Apple Developer Program 연 $99 | 명세 ✅ / 통합 ❌ |
| Linux | (관행상 미서명) | — | — |

**서명 미보유 시**: SmartScreen 경고를 사용자에게 사전 안내. `signing_available=False`
입력 시 Distribution Agent 가 안내 문구 자동 포함.

---

## 🛠️ 기술 선택 매트릭스 (v4 §7 통합 + 구축 마킹)

| 단계 | 1순위 | 2순위 | fallback | 구축 |
|---|---|---|---|---|
| GUI 프레임워크 (단순) | Tkinter + customtkinter | Flet | PyQt6 | ✅ E2E 검증 (계산기) |
| GUI 프레임워크 (복잡) | Flet | PyQt6 | (Electron 등 비-Python 검토) | 명세만 ⚠️ |
| 빌드 도구 | PyInstaller | Nuitka | cx_Freeze | 명세만 ⚠️ |
| 인스톨러 (Win) | Inno Setup | WiX | NSIS | 명세만 ⚠️ |
| 인스톨러 (mac) | pkgbuild + productbuild | DMG (create-dmg) | (zip만) | 명세만 ⚠️ |
| 인스톨러 (Linux) | AppImage | Flatpak | (tar.gz만) | 명세만 ⚠️ |
| 코드 서명 (Win) | signtool + EV cert | self-signed (개발용만) | 없음 + SmartScreen 안내 | 명세만 ⚠️ |
| 배포 채널 | GitHub Releases | S3 presigned | 로컬 파일링 | 명세만 ⚠️ |

**범례**:
- ✅ 실제 LLM E2E 로 1회 이상 검증됨
- ⚠️ 에이전트 backstory + Task 사양은 작성됨, 실제 외부 도구 호출 미통합

---

## ❓ 6가지 어려운 설계 질문 — 현재 답변 (v4 §10 + 2026-04-21 업데이트)

### 1. Cross-platform 우선순위
**v4 입장**: Windows-first 가정 — 사용자의 첫 사용 환경이 Windows.
**v5 현재**: ✅ 유지. 모든 E2E 검증은 Windows 11. macOS/Linux 빌드는 명세만 존재.

### 2. UI 추론 한계 — "REST API 만들어줘" 는?
**v4 입장**: UI/UX Analyst 의 1차 분기는 `need_gui? yes/no` — no 면 Phase 4 통째로 건너뜀.
**v5 현재**: ✅ 구축됨. [`_parse_ui_ux_path`](../../src/workflows/analyze_and_implement.py) 가
`need_gui` + `form_factor` 양쪽 시그널 파싱. PR #23 에서 파서 보강 완료.

### 3. 빌드 시간 예산
**v4 입장**: Nuitka 빌드는 5~30분. v3 budget gate 에 빌드 시간도 포함해야 함.
**v5 현재**: ❌ 미통합. v3 BUDGET 결정은 LLM 토큰 비용만 추적, 빌드 시간 미반영.
**해결 계획**: Build Engineer 사양에 `estimated_build_time_min` 필드 추가 + Convergence
Judge 의 BUDGET 결정에 빌드 시간 합산 → 다음 PR 후보.

### 4. 인증서 비용
**v4 입장**: EV 코드 서명 인증서 연 $300~$500. 사용자가 부담할지 사전 합의.
**v5 현재**: ⚠️ `signing_available` 플래그로 사용자 결정 위임. 비용 안내는 Distribution
Agent 의 RELEASE.md 초안에 포함되도록 backstory 명시.

### 5. 자동 업데이트의 보안 모델
**v4 입장**: Update Checker 가 임의 URL 에서 코드 받아 실행하면 공급망 공격면. 서명
검증 + 업데이트 채널 화이트리스트 필수.
**v5 현재**: ✅ Update Checker 5원칙 (HTTPS / TLS / allowlist / SHA256 / no auto-apply) 모두
backstory 에 명시 — Phase 5 PR #20 에서 반영 완료.

### 6. `.exe` 의 신뢰 문제
**v4 입장**: AI 가 자동 생성한 .exe 를 사용자가 신뢰할 수 있는가? 산출물에 "이 파일은
Nexus Alpha 가 자동 생성했습니다 + 코드 GitHub 링크 + 빌드 로그 hash" 라는 추적
정보(provenance) 동봉.
**v5 현재**: ❌ 미구축. Distribution Agent 가 SHA256 만 산출, provenance 자동 첨부는 향후 작업.
**해결 계획**: Phase 6 후보 — `release_summary.json` 에 `provenance` 필드 추가
(생성 timestamp, agent 체인 경로, GitHub commit SHA, 빌드 로그 hash).

---

## ✅ 단계별 Definition of Done — 체크 상태 반영 (v4 §8)

### Phase 4 (GUI)

- [x] "계산기 만들어줘" 요청에 대해 Tkinter 기반 GUI 코드가 자동 생성됨
       *(E2E 2026-04-21 — CTO 가 Tkinter 전략 수립, GUI Code Generator 가 framework=tkinter+customtkinter 결정)*
- [ ] **블로킹**: 생성된 GUI 가 PyInstaller 없이 `python` 으로 실행 가능
       *(이슈 4 로 인해 본문 코드가 추출되지 않음 — `code/` 디렉터리 비어있음)*
- [ ] UI/UX Analyst 가 단순/중간/복잡 요청 3종에 대해 서로 다른 ui_spec 산출
       *(단순 1종만 검증 — 중간/복잡 미검증)*

### Phase 4.5 (빌드)

- [ ] 위 GUI 코드를 PyInstaller 로 .exe 빌드 성공
       *(외부 도구 미통합 — Build Engineer 는 사양만 산출)*
- [ ] Windows Sandbox / 깨끗한 VM 에서 .exe 실행 → "1+1=2" 시나리오 자동 검증 통과
       *(미통합)*
- [ ] Inno Setup 으로 setup.exe 생성, 설치 → 시작 메뉴 등록 → 실행 시나리오 통과
       *(미통합)*

### Phase 5 (배포)

- [ ] GitHub Releases 에 setup.exe 자동 업로드
       *(외부 자동화 위임 — Release Manager 는 사양만)*
- [ ] CHANGELOG.md 자동 생성, RELEASE.md 한국어 요약 포함
       *(✅ 사양 산출 — [release_workflow.py](../../src/workflows/release_workflow.py) 로 4개 .md 생성)*
- [ ] 다운로드 URL + SHA256 hash 가 워크플로우 결과로 사용자에게 반환
       *(✅ 사양 산출 — `result.distribution_spec` 에 포함)*
- [ ] **최종 검증**: "계산기 만들어줘" 한 마디 → 다운로드 가능한 setup.exe URL 까지 자동 도달
       *(이슈 4 + 외부 도구 미통합으로 미완)*

**v5 종합**: Phase 4 의 *체인 자체* 는 작동, *코드 추출* 은 이슈 4 로 차단. Phase 4.5/5 의
*사양 산출* 은 작동, *실제 외부 도구 호출* 은 모두 미통합 (외부 자동화 위임 구조).

---

## 🔗 v3 + v4 통합 그림 — 실제 구축 반영 (v4 §9 업데이트)

```
                      [사용자]
                         │
                         ▼
         ┌───────────────────────────────┐
         │ Iteration Controller (v3)     │  ← src/workflows/iterative_loop.py
         │ ┌───────────────────────────┐ │
         │ │ Requirement Expander (v3) │ │  ✅
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ CTO ✅ → Analyst ✅ →      │ │  ← 메인 4-agent (Phase 1+2)
         │ │ + UI/UX Analyst ✅         │ │  ← Phase 4 (PR #15~17)
         │ │ + GUI Designer ✅          │ │  ← Phase 4 — 본문 누락 ❌ (이슈 4)
         │ │ + Theme Designer ✅        │ │  ← Phase 4 — 본문 누락 ❌ (이슈 4)
         │ │ + GUI Code Generator ✅    │ │  ← Phase 4 — 본문 누락 ❌ (이슈 4)
         │ │ + Engineer ✅              │ │  ← Phase 1
         │ │ + Code Reviewer ✅         │ │  ← Phase 2 (PR #5)
         │ │ + Dep Analyzer ✅          │ │  ← Phase 4.5 (PR #18) — 사양만
         │ │ + Build Engineer ✅        │ │  ← Phase 4.5 — 사양만
         │ │ + Asset Manager ✅         │ │  ← Phase 4.5 — 사양만
         │ │ + Installer Creator ✅     │ │  ← Phase 4.5 — 사양만
         │ │ + Platform Tester ✅       │ │  ← Phase 4.5 — sandbox 통합
         │ │ + Release Manager ✅       │ │  ← Phase 5 (PR #19) — 사양만
         │ │ + Changelog Generator ✅   │ │  ← Phase 5 — 사양만
         │ │ + Update Checker ✅        │ │  ← Phase 5 (PR #20) — 사양만
         │ │ + Distribution Agent ✅    │ │  ← Phase 5 — 사양만
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ Gap Analyst (v3) ✅        │ │
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ Convergence Judge (v3) ✅  │ │
         │ │ (COMPLETE/IMPROVE/BLOCKED)│ │
         │ └─────────────┬─────────────┘ │
         └───────────────┼───────────────┘
                         ▼
              ┌──────────────────────────────────┐
              │ outputs/workflow_<ts>/           │
              │   ├── 00~04 (메인 4-agent) ✅    │
              │   ├── 10~13 (GUI 분기) ⚠️ 본문   │
              │   │           누락 (이슈 4)       │
              │   ├── 20~24 (빌드 사양) ✅       │
              │   ├── 30~33 (릴리스 사양) ✅      │
              │   └── code/ ❌ (이슈 4 차단)     │
              └──────────────────────────────────┘

  ❌ 미달성 (외부 자동화 위임):
     dist/<product>-<version>-setup.exe
     + GitHub Releases URL + SHA256 + provenance
```

**범례**:
- ✅ 에이전트 구축 완료, 워크플로우에 통합됨
- ⚠️ 구축됐으나 알려진 이슈 있음 (이슈 4 등)
- ❌ 미구축 또는 외부 위임

---

## 📌 v1 → v5 핵심 학습

### 1. 비전 피벗은 자연스럽게 일어났다

v1 의 "RPA 자동화" 비전은 *사용자의 반복 업무를 대신하는 봇* 이었으나, 실제 구축
과정에서 "사용자가 자연어로 요청 → 시스템이 코드를 생성·빌드·배포" 라는 더 일반적인
*소프트웨어 공장* 으로 자연 수렴. RPA 특화 에이전트들 (Web Scraping Specialist 등)
은 이 비전 하에서 불요 — 향후 필요 시 별도 파이프라인으로 추가 가능.

### 2. CrewAI 의 Final Answer 파서는 양날의 검

`Thought + Final Answer` 패턴은 LLM 출력을 결정적으로 추출하기에 강력하나, 프롬프트가
"Final Answer 에는 한 줄 요약" 으로 작성되면 **본문 전체가 누락** (이슈 4). 모든
프롬프트는 `Final Answer:` 다음에 *전체 산출* 이 와야 함을 명시해야 함.

### 3. backward compat 토글 패턴이 효과적이었다

`enable_gui_branch=False` (기본) / `enable_build_branch=False` / `enable_release_branch=False`
3중 토글 덕분에 매 Phase 추가 시 기존 4-agent 테스트가 무중단으로 통과. 새 기능을
*기본값 비활성* 으로 추가하는 패턴은 향후 Phase 6+ 에도 계속 사용 권장.

### 4. CEO/CFO 미구축은 결과적으로 옳았다

원안의 CEO (총괄) 역할은 LangGraph StateGraph 자체가 흡수, CFO (비용 모니터링)
역할은 LangFuse trace 로 자동화. 별도 LLM 에이전트가 *오케스트레이션 결정* 을
내리는 것은 비결정적이라 위험 — **deterministic graph + LLM narration** 하이브리드가
더 안정적.

### 5. GUI 분기는 가장 큰 추가 가치

v1 에는 없던 GUI 분기 (UI/UX → Designer → Theme → Code Gen) 가 *자연어 → 데스크톱
GUI 앱* 이라는 v4 비전을 가능하게 함. v1 의 RPA 결과물보다 *사용자가 즉시 손에
쥘 수 있는 산출물* 이 더 직관적.

---

## 🔮 다음 단계 (Phase 6 이후 후보)

### 즉시 (이슈 4 수정 PR 후)

- [ ] **이슈 4 수정**: 4개 GUI 에이전트 backstory 의 Final Answer 패턴 교체 + `_task_output_text` 길이 fallback
- [ ] **E2E 재재검증**: Issue 4 해결 후 `code/app.py` 추출 → `python app.py` → 계산기 GUI 실행 확인

### 단기 (1~2주)

- [ ] **CLI 경로 E2E 검증**: 데이터 분석 도구 시나리오로 CLI 분기도 정상 작동 확인
- [ ] **PyInstaller 실제 호출 통합**: Phase 4.5 사양 → 실제 .exe 생성
- [ ] **GitHub Release 자동 업로드**: Phase 5 사양 → 실제 릴리스 게시

### 중기 (1~2개월)

- [ ] **Streamlit UI** 추가 (v1 계획 항목)
- [ ] **Vector DB 통합** (Qdrant) — Knowledge 본부 강화
- [ ] **Credential Vault** — 키 암호화 저장
- [ ] **RPA 분기 추가** (선택) — Web Scraping / Desktop Automation 에이전트 (v1 비전 부분 회귀)

### 장기 (3개월+)

- [ ] **CEO/CFO 에이전트 추가** (선택) — multi-project 동시 진행 시 의미 있을 수 있음
- [ ] **Helicone 통합** — 비용 세분 추적
- [ ] **Slack Bot** — 협업 환경 통합

---

## 📋 핵심 원칙 (v1 → v5 유지)

1. ✅ **작게 시작해서 점진적으로 확장** — Phase 0~5 단계별 진행 유지
2. ✅ **한 사이클이 완전히 작동한 후 다음 단계 진행** — 각 Phase 별 PR 분리
3. ✅ **모니터링 없이 개발 금지** — LangFuse 처음부터 연결
4. ✅ **파일럿으로 반드시 검증** — E2E 검증 (PR #24) 진행 중
5. ⚠️ **보안을 처음부터 제대로 설계** — 부분 적용 (FakeProvider 격리만, Credential Vault 미구축)

---

*본 v5 구성안은 2026-04-21 기준 실제 구축 상태를 반영합니다. 이슈 4 해결 후 v5.1 로 업데이트 예정.*

*v1 (2026-04-17 RPA 비전 원안) → v5 (2026-04-21 소프트웨어 공장 실제) 의 비전 피벗은
구현 과정에서 자연 발생한 정상적 진화이며, RPA 비전은 향후 Phase 6+ 의 선택적 분기로
재도입 가능합니다.*
