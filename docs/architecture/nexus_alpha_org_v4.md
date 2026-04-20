# Nexus Alpha — 조직도 v4 (확정)

- **확정일**: 2026-04-17
- **유효 범위**: v3 자율 반복 루프(Phase 2.5) + v4 완전 자율 빌드(Phase 4~5) 까지의 최종 모습
- **합계**: **C-Level 3명 + 8개 본부 = 9개 조직 단위, 총 46명 에이전트**

---

## 1. 조직도 한눈에 보기

```
                          ┌─────────────────────────────┐
                          │        C-Level (3명)         │
                          │  CEO · CTO · CFO/Convergence │
                          └──────────────┬──────────────┘
                                         │
       ┌────────────┬────────────┬───────┼──────┬───────────┬────────────┬────────────┐
       ▼            ▼            ▼       ▼      ▼           ▼            ▼            ▼
   ┌────────┐  ┌──────────┐  ┌─────┐ ┌──────┐ ┌───────┐ ┌──────────┐ ┌────────┐ ┌────────────┐
   │ 업무   │  │ 기획·설계 │  │ 개발 │ │ 품질  │ │ 지식  │ │ 운영 지원 │ │ 디자인 │ │ 빌드 & 배포 │
   │ 분석   │  │           │  │      │ │ 검증  │ │ 관리  │ │           │ │ 🆕    │ │ 🆕         │
   │ (5명) │  │  (4명)    │  │(9명)│ │(6명) │ │(3명) │ │  (4명)    │ │ (3명) │ │  (9명)     │
   └────────┘  └──────────┘  └─────┘ └──────┘ └───────┘ └──────────┘ └────────┘ └────────────┘
```

### 본부별 인원 합계 검증

| 본부 | 인원 | 누계 |
|---|---:|---:|
| C-Level | 3 | 3 |
| 업무 분석 | 5 | 8 |
| 기획 및 설계 | 4 | 12 |
| 개발 | 9 | 21 |
| 품질 검증 | 6 | 27 |
| 지식 관리 | 3 | 30 |
| 운영 지원 | 4 | 34 |
| 🆕 디자인 | 3 | 37 |
| 🆕 빌드 & 배포 | 9 | **46** |

✅ 총 46명 (C-Level 3 + 8 본부 43)

---

## 2. C-Level (3명)

| 역할 | 이름 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| CEO | Chief Executive Officer | 사용자 의도 최종 해석, 우선순위 결정 | `src/agents/c_level/ceo.py` | 2 (신규) |
| CTO | Chief Technology Officer | 기술 스택·아키텍처 결정, 엔지니어링 방향성 | `src/agents/c_level/cto.py` | 1 (완료) |
| Convergence Judge | (CFO 역할 수행) | 반복 루프 종료 판정, 예산 집행 | `src/agents/c_level/convergence_judge.py` | 2.5 (v3) |

> Convergence Judge는 별도 본부 부서장 격이지만, 결정권의 무게로 인해 C-Level에 편제. 일반 LLM 호출이 아닌 **결정표 기반**으로 동작.

---

## 3. 8개 본부 상세

### 3-1. 본부 ① 업무 분석 (5명)

요청을 데이터·요구·비즈니스 관점에서 분해하는 분석 역할군.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Data Analyst | 데이터 품질·지표·차트 지시서 작성 | `src/agents/analysis/data_analyst.py` | 1 (완료) |
| 2 | Requirement Expander | 사용자 요청을 요구 스펙 YAML로 확장 (가정·미해결 질문 명시) | `src/agents/analysis/requirement_expander.py` | 2.5 (v3) |
| 3 | Gap Analyst | 산출물과 요구 스펙 비교 → 미달/잉여/모호 항목 보고 | `src/agents/analysis/gap_analyst.py` | 2.5 (v3) |
| 4 | Business Analyst | 비즈니스 로직·도메인 규칙 분해 | `src/agents/analysis/business_analyst.py` | 3 |
| 5 | Process Mining Analyst | 사용자 RPA 대상 업무의 실제 흐름 추출 | `src/agents/analysis/process_mining_analyst.py` | 3 |

### 3-2. 본부 ② 기획 및 설계 (4명)

요구 → 시스템/UX 설계로 구체화.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | System Architect | 모듈 구조·인터페이스·데이터 흐름 설계 | `src/agents/planning/system_architect.py` | 2 |
| 2 | API Designer | 외부/내부 API 시그니처·계약 설계 | `src/agents/planning/api_designer.py` | 2 |
| 3 | UI/UX Analyst | **GUI 형태(form factor) 추론**, 위젯 트리·레이아웃 사양 작성 | `src/agents/planning/ui_ux_analyst.py` | 4 (v4) |
| 4 | Workflow Planner | 멀티 에이전트 워크플로우 설계 | `src/agents/planning/workflow_planner.py` | 3 |

> **UI/UX Analyst를 디자인 본부가 아닌 기획·설계에 둔 이유**:
> 이 역할은 *"어떤 UI 패턴이 적절한가"* 를 **판정**하는 분석가에 가깝지, 시각 디자인을 직접 만들지 않는다. 디자인 본부는 분석 결과를 받아 실제 디자인·코드를 만든다. 관심사 분리(Analysis vs Production).

### 3-3. 본부 ③ 개발 (9명)

실제 코드를 생산하는 엔지니어링 역할군.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Python Engineer | 비즈니스 로직 Python 코드 (CLI·라이브러리) | `src/agents/engineering/python_engineer.py` | 1 (완료) |
| 2 | Backend Engineer | API 서버·데이터 영속화 | `src/agents/engineering/backend_engineer.py` | 2 |
| 3 | Frontend Engineer | 웹 프론트엔드 (React/Vue 등) | `src/agents/engineering/frontend_engineer.py` | 2 |
| 4 | Database Engineer | 스키마 설계·마이그레이션 | `src/agents/engineering/database_engineer.py` | 2 |
| 5 | Integration Engineer | 외부 API 연동·인증 처리 | `src/agents/engineering/integration_engineer.py` | 3 |
| 6 | Automation Engineer | RPA·셀레니움·OS 자동화 스크립트 | `src/agents/engineering/automation_engineer.py` | 3 |
| 7 | Performance Engineer | 프로파일링·병목 제거·캐싱 | `src/agents/engineering/performance_engineer.py` | 3 |
| 8 | Refactoring Engineer | 코드 정리·중복 제거·패턴 적용 | `src/agents/engineering/refactoring_engineer.py` | 3 |
| 9 | Documentation Engineer | 코드 docstring·README·사용자 매뉴얼 | `src/agents/engineering/documentation_engineer.py` | 3 |

### 3-4. 본부 ④ 품질 검증 (6명)

산출물의 품질·안정성·보안을 검증.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Code Reviewer | 정적 점검 (타입 힌트·docstring·복잡도) | `src/agents/qa/code_reviewer.py` | 2 (다음 작업) |
| 2 | Test Engineer | 단위·통합 테스트 자동 생성 | `src/agents/qa/test_engineer.py` | 2 |
| 3 | Security Auditor | OWASP·시크릿 노출·의존성 취약점 점검 | `src/agents/qa/security_auditor.py` | 3 |
| 4 | Accessibility Checker | UI 접근성(WCAG, 키보드 내비) 점검 | `src/agents/qa/accessibility_checker.py` | 4 |
| 5 | Performance Tester | 부하·메모리·시작 시간 측정 | `src/agents/qa/performance_tester.py` | 3 |
| 6 | Regression Detector | 이전 산출물 대비 회귀 자동 감지 | `src/agents/qa/regression_detector.py` | 3 |

### 3-5. 본부 ⑤ 지식 관리 (3명)

과거 산출·결정·실패 사례를 자산화.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Knowledge Curator | `outputs/workflow_*` 적재·요약·태깅 | `src/agents/knowledge/knowledge_curator.py` | 2 |
| 2 | RAG Searcher | 과거 결정·산출에서 유사 사례 검색 | `src/agents/knowledge/rag_searcher.py` | 2 |
| 3 | Decision Recorder | C-Level/Judge의 판정 근거를 ADR 형태로 기록 | `src/agents/knowledge/decision_recorder.py` | 3 |

### 3-6. 본부 ⑥ 운영 지원 (4명)

산출물의 실행·관측·장애 대응.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Sandbox Runner | 생성된 코드를 격리 환경에서 실행 | `src/agents/operations/sandbox_runner.py` | 2 |
| 2 | Scheduler | 정기 실행·트리거 설정 | `src/agents/operations/scheduler.py` | 2 |
| 3 | Log Analyzer | 실행 로그에서 이상·실패 패턴 추출 | `src/agents/operations/log_analyzer.py` | 3 |
| 4 | Incident Responder | 실패 발생 시 자동 진단·대응 | `src/agents/operations/incident_responder.py` | 3 |

### 3-7. 본부 ⑦ 🆕 디자인 (3명) — Phase 4 신설

UI/UX Analyst의 사양을 실제 시각 디자인 + 코드로 구현.

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | GUI Designer | 와이어프레임·레이아웃·인터랙션 흐름 설계 | `src/agents/design/gui_designer.py` | 4 |
| 2 | GUI Code Generator | UI 사양 → 실제 GUI 코드 생성 (Tkinter/Flet/PyQt6) | `src/agents/design/gui_code_generator.py` | 4 |
| 3 | Theme Designer | 디자인 토큰(palette/typography/spacing) 결정 | `src/agents/design/theme_designer.py` | 4 |

**디렉터리 생성 시점**: Phase 4 착수 시 `src/agents/design/__init__.py` 와 README 신규 생성.

### 3-8. 본부 ⑧ 🆕 빌드 & 배포 (9명) — Phase 4.5 & Phase 5 신설

코드를 사용자가 즉시 사용 가능한 형태(.exe, 설치 관리자, 배포 URL)까지 변환.

#### Phase 4.5 (빌드 & 패키징, 5명)

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | Build Engineer | PyInstaller/Nuitka로 실행 파일 빌드 | `src/agents/build_release/build_engineer.py` | 4.5 |
| 2 | Dependency Analyzer | import 그래프·hidden imports·라이선스 점검 | `src/agents/build_release/dependency_analyzer.py` | 4.5 |
| 3 | Asset Manager | 아이콘·폰트·리소스 수집 및 빌드 포함 | `src/agents/build_release/asset_manager.py` | 4.5 |
| 4 | Installer Creator | Inno Setup/WiX 등으로 setup.exe 생성 | `src/agents/build_release/installer_creator.py` | 4.5 |
| 5 | Platform Tester | 깨끗한 환경에서 빌드 산출물 자동 실행 검증 | `src/agents/build_release/platform_tester.py` | 4.5 |

#### Phase 5 (배포 자동화, 4명)

| # | 에이전트 | 책임 | 파일 경로 | Phase |
|---|---|---|---|---|
| 6 | Release Manager | SemVer 결정, Git 태그, RELEASE.md 초안 | `src/agents/build_release/release_manager.py` | 5 |
| 7 | Changelog Generator | 한국어 사용자 친화 변경 사항 요약 | `src/agents/build_release/changelog_generator.py` | 5 |
| 8 | Update Checker | 산출물에 자동 업데이트 모듈 삽입 | `src/agents/build_release/update_checker.py` | 5 |
| 9 | Distribution Agent | GitHub Releases/S3 등에 배포, 다운로드 URL 반환 | `src/agents/build_release/distribution_agent.py` | 5 |

**디렉터리 생성 시점**: Phase 4.5 착수 시 `src/agents/build_release/__init__.py` 와 README 신규 생성. Phase 5는 동일 디렉터리에 4명 추가.

---

## 4. 디렉터리 매핑 정리

```
src/agents/
├── c_level/                     # 본부 0 — 3명 (CEO·CTO·Convergence Judge)
├── analysis/                    # 본부 ① — 5명
├── planning/                    # 본부 ② — 4명 (UI/UX Analyst 포함)
├── engineering/                 # 본부 ③ — 9명
├── qa/                          # 본부 ④ — 6명
├── knowledge/                   # 본부 ⑤ — 3명
├── operations/                  # 본부 ⑥ — 4명
├── design/        🆕 Phase 4    # 본부 ⑦ — 3명
└── build_release/ 🆕 Phase 4.5  # 본부 ⑧ — 9명 (4.5와 5 합산)
```

### 신설 디렉터리 생성 일정

| 디렉터리 | 생성 시점 | 초기 인원 | 최종 인원 |
|---|---|---|---|
| `src/agents/design/` | Phase 4 착수 시 | 3 | 3 |
| `src/agents/build_release/` | Phase 4.5 착수 시 | 5 | 9 (Phase 5에서 +4) |

---

## 5. 현재 상태(2026-04-17) 대비 진행률

| 본부 | 구현 완료 | 진행 중 | 미착수 | 본부 진행률 |
|---|---:|---:|---:|---:|
| C-Level | 1 (CTO) | 0 | 2 | 33% |
| 업무 분석 | 1 (Data Analyst) | 0 | 4 | 20% |
| 기획 및 설계 | 0 | 0 | 4 | 0% |
| 개발 | 1 (Python Engineer) | 0 | 8 | 11% |
| 품질 검증 | 0 | 1 (Code Reviewer 다음 작업) | 5 | 0% |
| 지식 관리 | 0 | 0 | 3 | 0% |
| 운영 지원 | 0 | 0 | 4 | 0% |
| 디자인 | 0 | 0 | 3 | 0% |
| 빌드 & 배포 | 0 | 0 | 9 | 0% |
| **합계** | **3** | **1** | **42** | **6.5%** |

> Phase 1 MVP에서 3명을 먼저 완성한 것은 의도된 선택이었다. 이 3명이 가장 뒤에 등장하는 본부의 출력 품질에까지 영향을 주므로, **체인 골격을 먼저 깔고 → 점진적으로 본부를 채워 가는** 방식을 채택했다.

---

## 6. 성장 경로 (어떤 순서로 본부를 채울 것인가)

```
현재 (Phase 1 + 2-P1)
  │
  ▼
Phase 2  : 품질 검증 1명 (Code Reviewer)        ← 다음 작업
  │       지식 관리 1명 (Knowledge Curator)
  │       운영 지원 1명 (Sandbox Runner)
  │       기획·설계 1~2명 (System Architect / API Designer)
  │
  ▼
Phase 2.5 (v3) : 업무 분석 +2 (Requirement Expander, Gap Analyst)
  │              C-Level +1 (Convergence Judge)
  │
  ▼
Phase 3  : 개발·QA·운영·지식 본부 본격 확장
  │
  ▼
Phase 4 (v4)   : 🆕 디자인 본부 신설 + UI/UX Analyst 합류
  │
  ▼
Phase 4.5 (v4) : 🆕 빌드 & 배포 본부 5명 신설
  │
  ▼
Phase 5 (v4)   : 빌드 & 배포 본부 +4명 (배포 자동화)
  │
  ▼
v4 완성 (46명 풀 조직)
```

### 우선순위 결정 원칙

1. **체인의 끊긴 곳을 먼저** — 코드는 만들지만 검증이 없으면 QA 먼저, 검증은 있지만 반복이 없으면 v3 루프 먼저.
2. **신뢰를 가장 빠르게 회복하는 것 먼저** — Phase 4 GUI는 사용자가 가장 빨리 효과를 체감할 수 있는 영역.
3. **선행 의존이 있는 것은 뒤로** — Distribution Agent는 Build/Installer가 있어야 의미 있다. Phase 5는 4.5 다음.

---

## 7. 조직 운영 원칙

### 7-1. 한 본부 = 한 디렉터리
- 본부 신설 시 항상 `src/agents/<dept>/__init__.py` + `README.md` 부터 만든다.
- 디렉터리가 README만 있고 `.py` 파일이 0개여도 무방 — "이 본부가 존재한다"는 신호 자체가 가치.

### 7-2. 한 에이전트 = 한 파일 = 한 팩토리 함수
- 파일명은 역할 기반 snake_case (예: `code_reviewer.py`).
- 팩토리 함수는 `create_<name>_agent(llm=None, verbose=True, max_iter=3, allow_delegation=False)` 시그니처 통일.
- 이 통일성 덕분에 워크플로우/테스트가 모든 에이전트를 동일하게 다룰 수 있음.

### 7-3. 본부 간 직접 호출 금지
- 본부 간 협업은 항상 워크플로우 계층(`src/workflows/*`)에서 조립.
- 에이전트 모듈이 다른 본부 모듈을 직접 import하지 않는다 — 결합도 폭발 방지.

### 7-4. 새 본부 추가 시 체크리스트
- [ ] 디렉터리 + `__init__.py` + `README.md` 생성
- [ ] 본부의 미션 한 문장을 README 최상단에 명시
- [ ] 본 조직도(`nexus_alpha_org_v4.md`)의 본부 카운트 갱신
- [ ] `next_session_context.md`의 진행 현황 표 갱신
- [ ] 첫 에이전트 1명을 추가하고 pytest로 검증

---

## 8. 향후 변경 시 주의 사항

- 인원수가 변경되면 **§1의 합계 검증 표**와 **§5의 진행률 표**를 동시에 갱신.
- 본부를 합치거나 분리하면 **§4의 디렉터리 매핑**과 **모든 에이전트의 파일 경로**가 바뀔 수 있다 — 그 경우 새 문서(`nexus_alpha_org_v5.md`) 로 분기하고 본 문서는 보존.
- 본 문서는 v4까지의 **확정안**이다. v5 이후 변경은 별도 문서로 관리한다.
