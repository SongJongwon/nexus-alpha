# 🏗️ Nexus Alpha 공식 조직도 v6 (PR #36 반영)

**개정일**: 2026-04-28
**최종 구조**: 경영진 + 8개 본부, 총 46명 에이전트
**현재 상태**: **23/46명 구현 (50%)** + **2개 본부 100% 완성** + **외부 도구 통합 시작**

---

## 📊 v5.1 → v6 핵심 변경사항

| 항목 | v5.1 (2026-04-20) | **v6 (2026-04-28, PR #36)** |
|---|---|---|
| 누적 PR | 20 | **36** (+16) |
| pytest | 124 | **199** (+75) |
| 이슈 close | — | **이슈 4 / 5 / 6 모두 close** |
| 외부 도구 통합 | 0 (사양만 산출) | **PyInstaller 실제 호출 (PR #36)** |
| 첫 `.exe` 산출 | 미달성 | **✅ Calculator.exe 10.7MB 생성** |
| 본문 캡처율 | 측정 전 | **94% (16 에이전트 중 15 정상)** |

---

## 📊 전체 조직 구성

### 조직 단위 총 9개
- **경영진 (C-Level)** — 1개 (최고 의사결정)
- **실행 본부** — 8개 (실무 수행)

### 에이전트 구현 현황 (2026-04-28)

| 구분 | 인원 | 비율 |
|---|---|---|
| 구현 완료 | **23명** | **50%** |
| 미구현 | 23명 | 50% |
| **총계** | **46명** | **100%** |

### 완성된 본부 (100%) 🎉
- ✅ **본부 7: 디자인** (3명 전체)
- ✅ **본부 8: 빌드 & 배포** (9명 전체) + **build_executor 도구** (PR #36 신규)

---

## 🎯 경영진 (C-Level Orchestrators) — 3명

**현황**: 1/3 구현 (33%)

| 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|
| CEO Agent | 전체 워크플로우 총괄, 사용자 요구 해석, 최종 승인 | Phase 8 | ⬜ |
| **CTO Agent** | 기술 전략, 자동화 방식 결정 | ✅ Phase 1 | ✅ |
| CFO Agent | 토큰/API 비용 모니터링, ROI 산출 | Phase 8 | ⬜ |

> **참고**: CFO 역할은 LangFuse trace 자동 추적으로 부분 대체. CEO 역할은 LangGraph StateGraph 자체가 흡수.

---

## 🏛️ 본부 1: 업무 분석 본부 (Business Analysis) — 5명

**책임**: 사용자 요구를 정량 가능한 명세로 변환
**현황**: 1/5 구현 (20%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | Process Discovery Analyst | As-Is 프로세스 매핑 | Phase 9 | ⬜ |
| 2 | Business Analyst (BA) | 병목·비효율 식별, 자동화 우선순위 | Phase 9 | ⬜ |
| 3 | ROI Calculator | 절감 시간/비용 추산 | Phase 9 | ⬜ |
| 4 | Feasibility Checker | 기술적 실행 가능성 판단 | Phase 9 | ⬜ |
| 5 | **Requirement Expander** | 암묵적 요구사항 추출 (v3 자율 반복) | ✅ Phase 2.5 | ✅ |

---

## 🏛️ 본부 2: 기획 및 설계 본부 (Planning & Design) — 4명

**책임**: 시스템 아키텍처와 프로세스 설계
**현황**: 1/4 구현 (25%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **UI/UX Analyst** | CLI vs GUI 판별, UX 요구사항 추출 | ✅ Phase 4 | ✅ |
| 2 | Product Manager | PRD 작성, 업무 우선순위 결정 | Phase 9 | ⬜ |
| 3 | Workflow Designer | BPMN 다이어그램으로 To-Be 설계 | Phase 9 | ⬜ |
| 4 | Error Handling Designer | 예외 시나리오 설계 | Phase 9 | ⬜ |

---

## 🏛️ 본부 3: 개발 본부 (Engineering) — 9명

**책임**: 실행 가능한 코드 생성 — **시스템의 핵심 엔진**
**현황**: 3/9 구현 (33%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **Data Analyst Agent** | 데이터 분석 지시서 작성 | ✅ Phase 1 | ✅ |
| 2 | **Python Engineer Agent** | Python 코드 작성 | ✅ Phase 1 | ✅ |
| 3 | **Gap Analyst** | 격차 분석 (v3 자율 반복) | ✅ Phase 2.5 | ✅ |
| 4 | Integration Architect | 연동 시스템 분석 (Excel/Web/API/DB) | Phase 6 | ⬜ |
| 5 | Web Scraping Specialist | Playwright/Selenium 웹 자동화 | Phase 6 | ⬜ |
| 6 | Desktop Automation Specialist | PyAutoGUI/PyWinAuto | Phase 6 | ⬜ |
| 7 | API Integration Developer | REST/GraphQL/Webhook | Phase 6 | ⬜ |
| 8 | Data Parser Engineer | Excel/PDF/CSV/JSON 파싱 | Phase 6 | ⬜ |
| 9 | DevOps Engineer | Docker, 스케줄링, CI/CD | Phase 6 | ⬜ |

---

## 🏛️ 본부 4: 품질 검증 본부 (QA & Review) — 6명

**책임**: 산출물 품질 보장 및 수렴 판정
**현황**: 2/6 구현 (33%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **Code Reviewer** | 코드 품질·가독성 검토 | ✅ Phase 2-P2 | ✅ |
| 2 | **Convergence Judge** | 수렴 판정 (v3 자율 반복) | ✅ Phase 2.5 | ✅ |
| 3 | Robustness Tester | 예외·부하 테스트 | Phase 7 | ⬜ |
| 4 | Security Auditor | 자격 증명 보호, 권한 검증 | Phase 7 | ⬜ |
| 5 | Performance Engineer | 대량 처리 성능 체크 | Phase 7 | ⬜ |
| 6 | Compliance Officer | robots.txt, 이용약관 준수 | Phase 7 | ⬜ |

---

## 🏛️ 본부 5: 지식 관리 본부 (Knowledge Hub) — 3명

**책임**: 과거 경험 축적 및 재활용
**현황**: 2/3 구현 (67%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **Knowledge Curator** | 워크플로우 산출물 색인 (Vector DB) | ✅ Phase 2-P3 | ✅ |
| 2 | **RAG Searcher** | 과거 사례 검색·추천 | ✅ Phase 2-P3 | ✅ |
| 3 | Documentation Agent | 사용자 매뉴얼 자동 생성 | Phase 9 | ⬜ |

---

## 🏛️ 본부 6: 운영 지원 본부 (Operations) — 4명

**책임**: 본부 간 조율 및 실행 관리
**현황**: 1/4 구현 (25%)

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **Sandbox Runner** | 격리된 subprocess로 코드 실행 검증 | ✅ Phase 2-P4 | ✅ |
| 2 | Project Coordinator | 부서 간 조율, 교착 상태 감지 | Phase 9 | ⬜ |
| 3 | Human Liaison | 하이브리드 모드 사용자 소통 | Phase 9 | ⬜ |
| 4 | Monitoring Agent | 배포된 봇 상태 모니터링 | Phase 9 | ⬜ |

> **참고**: Iteration Controller는 에이전트가 아닌 **LangGraph 오케스트레이터** (`src/workflows/iterative_loop.py`).

---

## 🏛️ 본부 7: 디자인 본부 (UI/UX Design) — 3명 — **100% 완성** ✅

**책임**: 사용자 인터페이스·경험 생산 (시각 디자인 및 GUI 코드)
**현황**: 3/3 구현 (100%) 🎉

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **GUI Designer** | 와이어프레임·레이아웃 설계 | ✅ Phase 4 | ✅ |
| 2 | **Theme Designer** | 색상·폰트·아이콘·스타일링 (WCAG AA 준수) | ✅ Phase 4 | ✅ |
| 3 | **GUI Code Generator** | Tkinter/PyQt6/Flet 코드 생성 | ✅ Phase 4 | ✅ |

**핵심 결정사항 (PR #25, #33 반영)**:
- 프레임워크 선택 정책: simple → Tkinter+customtkinter, medium → Flet, complex → PyQt6
- WCAG AA 절대 준수: 텍스트 4.5:1 / 큰 텍스트 3:1 대비
- **Pydantic 스키마 적용** (PR #33): UIUXSpecOutput, GUIDesignOutput, ThemeTokensOutput, GUICodeOutput — `output_pydantic` 으로 본문 손실 방지

---

## 🏛️ 본부 8: 빌드 & 배포 본부 (Build & Release) — 9명 + 도구 1개 — **100% 완성** ✅

**책임**: 실행 파일 생성 및 유통 — **사용자 산출물 제공의 핵심**
**현황**: 9/9 구현 (100%) + **build_executor 도구 추가 (PR #36)** 🎉

### 서브그룹 A: 빌드 엔지니어링 (5명) ✅

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 1 | **Build Engineer** | PyInstaller/Nuitka/cx_Freeze 자동 빌드 | ✅ Phase 4.5 | ✅ |
| 2 | **Dependency Analyzer** | Hidden imports/data/native/license/OS 감지 | ✅ Phase 4.5 | ✅ |
| 3 | **Asset Manager** | 아이콘·폰트·리소스 수집/배치 | ✅ Phase 4.5 | ✅ |
| 4 | **Installer Creator** | Inno Setup / WiX / pkgbuild / AppImage | ✅ Phase 4.5 | ✅ |
| 5 | **Platform Tester** | 깨끗한 환경(Windows Sandbox/Docker) 실행 검증 | ✅ Phase 4.5 | ✅ |

### 서브그룹 B: 릴리스 관리 (4명) ✅

| # | 직책 | 역할 | 구현 Phase | 상태 |
|---|---|---|---|---|
| 6 | **Release Manager** | 버전 관리 (SemVer 자동 판정) | ✅ Phase 5 | ✅ |
| 7 | **Changelog Generator** | 자동 변경 이력 (Keep a Changelog) | ✅ Phase 5 | ✅ |
| 8 | **Update Checker** | 자동 업데이트 모듈 사양 (HTTPS/TLS/SHA256/allowlist) | ✅ Phase 5 | ✅ |
| 9 | **Distribution Agent** | GitHub Releases / S3 / 사내 / 로컬 fallback | ✅ Phase 5 | ✅ |

### 🆕 도구 컴포넌트 (PR #36, 2026-04-28)

| # | 컴포넌트 | 역할 | 위치 | 상태 |
|---|---|---|---|---|
| 0 | **build_executor** (도구) | BuildSpec 사양 → 실제 `pyinstaller` subprocess 호출 → `.exe` 산출 → SHA256 | `src/agents/build_release/build_executor.py` | ✅ Phase 4.5 (PR #36) |

**핵심 결정사항 (PR #25-36 반영)**:
- 빌드 전략: PyInstaller 1순위, Nuitka는 성능 필요시, cx_Freeze는 크로스 플랫폼
- 배포 채널 우선순위: GitHub Releases → S3 → 사내 서버 → 로컬
- 보안 5원칙: HTTPS + TLS 검증 + 채널 화이트리스트 + SHA256 + no auto-apply
- **Pydantic 스키마 9개 적용** (PR #31, #33): BuildSpecOutput / DependencyReportOutput / AssetManifestOutput / InstallerSpecOutput / PlatformTestReportOutput / ReleaseDecisionOutput / ChangelogEntryOutput / UpdateModuleSpecOutput / DistributionSpecOutput

**🎯 PR #36 — 외부 도구 첫 호출 + 첫 진짜 `.exe` 산출**:
- Smoke test 결과: `Calculator.exe` 10.7 MB, SHA256 `7b66044e353edb10...`, 빌드 시간 18.4초
- 형식: PE32+ executable (GUI) x86-64, for MS Windows
- v5 doc DoD Phase 4.5 의 핵심 미완 항목 (외부 도구 미통합) **첫 해소**

---

## 📊 본부별 인원 및 진행률 요약

| 조직 단위 | 정원 | 현재 | 진행률 | Phase별 완성 예정 |
|---|---|---|---|---|
| 경영진 (C-Level) | 3명 | 1명 | 33% | Phase 8 |
| 본부 1: 업무 분석 | 5명 | 1명 | 20% | Phase 9 |
| 본부 2: 기획 및 설계 | 4명 | 1명 | 25% | Phase 9 |
| 본부 3: 개발 | 9명 | 3명 | 33% | Phase 6 |
| 본부 4: 품질 검증 | 6명 | 2명 | 33% | Phase 7 |
| 본부 5: 지식 관리 | 3명 | 2명 | 67% | Phase 9 |
| 본부 6: 운영 지원 | 4명 | 1명 | 25% | Phase 9 |
| **🏆 본부 7: 디자인** | 3명 | **3명** | **100%** ✅ | **Phase 4 완료** |
| **🏆 본부 8: 빌드 & 배포** | 9명 + 1도구 | **9명 + 1도구** | **100%** ✅ | **Phase 5 완료 + PR #36** |
| **총계** | **46명** | **23명** | **50%** | **Phase 9 완료 시** |

---

## 📁 파일 시스템 매핑

```
src/agents/
├── c_level/           → 경영진 (3명): CTO ✅
│
├── analysis/          → 본부 1: 업무 분석 (5명): Requirement Expander ✅
│                         + Data Analyst, Gap Analyst (실제 배치)
│
├── planning/          → 본부 2: 기획 및 설계 (4명): UI/UX Analyst ✅
│
├── engineering/       → 본부 3: 개발 (9명): Python Engineer ✅
│
├── qa/                → 본부 4: 품질 검증 (6명): Code Reviewer ✅
│                         + Convergence Judge (실제 배치)
│
├── knowledge/         → 본부 5: 지식 관리 (3명): Curator ✅, RAG Searcher ✅
│
├── operations/        → 본부 6: 운영 지원 (4명): Sandbox Runner ✅
│
├── design/            → 🏆 본부 7: 디자인 (3명) 100% ✅━━━
│   ├── gui_designer.py
│   ├── theme_designer.py
│   └── gui_code_generator.py
│
└── build_release/     → 🏆 본부 8: 빌드 & 배포 (9명 + 1도구) 100% ✅━━━━━━━━━
    ├── build_engineer.py
    ├── dependency_analyzer.py
    ├── asset_manager.py
    ├── installer_creator.py
    ├── platform_tester.py
    ├── release_manager.py
    ├── changelog_generator.py
    ├── update_checker.py
    ├── distribution_agent.py
    └── build_executor.py  ← 🆕 PR #36 (도구 컴포넌트, LLM 아님)
```

### 🆕 신설 워크플로우 인프라 (PR #29, #31, #33)

```
src/workflows/
├── _common.py        → 🆕 PR #29 — 공유 헬퍼 (task_output_text + retry)
├── _schemas.py       → 🆕 PR #31, #33 — 14 Pydantic 스키마 + sanitize 헬퍼
└── analyze_and_implement.py / build_workflow.py / release_workflow.py
   (모두 `output_pydantic` 강제 + auto-retry 적용)
```

---

## 🆕 v5.1 → v6 변경사항 (PR #25-36)

### 새로 도입된 인프라

| 항목 | PR | 효과 |
|---|---|---|
| Auto-retry 헬퍼 (`retry_short_tasks_in_chain`) | #29 | 짧은 출력 자동 재시도 (방어선 1) |
| Pydantic output schemas (14개) | #31 + #33 | LLM 출력 형식 강제 (방어선 2) |
| Cosmetic sanitize (`_strip_leading_section_header`) | #33 | LLM 의 자체 헤더 중복 자동 정리 |
| NexusAlphaLLM 호환성 fix | #32 | CrewAI converter 와의 호환성 확보 |
| **build_executor (도구)** | **#36** | **첫 외부 도구 호출 (`pyinstaller`) + 첫 `.exe`** |

### 해결된 이슈

| 이슈 | 증상 | 해결 PR |
|---|---|---|
| **이슈 4** | GUI 4 에이전트 본문 누락 (Final Answer 한 줄만) | PR #25 ✅ |
| **이슈 5** | 비-GUI 16 에이전트 동일 패턴 | PR #27 ✅ |
| **이슈 6** | LLM 비결정적 컴플라이언스 | PR #29 (방어선 1) → PR #31/#32 (방어선 2 시범) → PR #33 (전체 확장) ✅ |

### 캡처율 추이 (E2E 측정)

| E2E | PR | 본문 캡처율 | 누적 PR |
|---|---|---|---|
| 1차 | #21 | 38% | ~ #21 |
| 2차 | #24 | 38% | ~ #24 |
| 3차 (재재) | #26 | 38% | ~ #26 |
| 4차 | #28 | 75% | ~ #28 |
| 5차 (방어선 1) | #30 | 75% | ~ #30 |
| 6차 (시범) | #32 | 81% | ~ #32 |
| **7차 (확장)** | **#34** | **94%** | ~ **#34** |

---

## 🎯 조직 운영 원칙 (변경 없음)

### 원칙 1: 단일 책임 원칙
각 본부는 하나의 명확한 목적만 담당한다.

### 원칙 2: 관리폭 제한
본부당 최대 **10명** 이하 유지. 초과 시 서브그룹 분리 또는 본부 분할.

### 원칙 3: 본부 간 책임 경계 명확화
- **개발 본부** = 새 코드 창조 (**실행 로직** 중심)
- **디자인 본부** = 사용자 인터페이스 생산 (**시각 디자인** + **GUI 코드**)
- **기획·설계 본부** = 요구사항 분석·설계 (**판별·판정**)
- **품질 검증 본부** = 산출물 검증
- **빌드 & 배포 본부** = 실행 파일 생성 및 유통 + **외부 도구 통합** (PR #36~)

### 원칙 4: 에이전트 배치는 유연
에이전트를 다른 본부로 이동시킬 수 있다 (책임 경계가 바뀌지 않는 한).

### 원칙 5: 본부 신설은 신중
향후 신 본부 신설 시 기존 본부와 책임 겹침 없는지 반드시 검증.

### 원칙 6 (신규): 도구 컴포넌트 vs LLM 에이전트 구분
- **LLM 에이전트**: backstory + Task + LLM 호출로 자연어 출력 (예: Build Engineer)
- **도구 컴포넌트**: 결정론적 코드 (subprocess, SHA256 등) — LLM 아님 (예: build_executor)
- 도구는 본부 정원에 포함하지 않음 (build_executor 는 본부 8 의 도구 1개)

---

## 🎯 구현 진행 상황 (2026-04-28 기준)

### ✅ 완료 (23명)

#### Phase 1 (3명)
- CTO Agent (경영진)
- Data Analyst Agent (본부 1)
- Python Engineer Agent (본부 3)

#### Phase 2 (4명)
- Code Reviewer (본부 4)
- Knowledge Curator (본부 5)
- RAG Searcher (본부 5)
- Sandbox Runner (본부 6)

#### Phase 2.5 (3명)
- Requirement Expander (본부 1)
- Gap Analyst (본부 3)
- Convergence Judge (본부 4)

#### Phase 4 (4명)
- UI/UX Analyst (본부 2)
- GUI Designer (본부 7)
- Theme Designer (본부 7)
- GUI Code Generator (본부 7)

#### Phase 4.5 (5명 + 1 도구)
- Build Engineer (본부 8)
- Dependency Analyzer (본부 8)
- Asset Manager (본부 8)
- Installer Creator (본부 8)
- Platform Tester (본부 8)
- 🆕 **build_executor 도구** (PR #36, 2026-04-28)

#### Phase 5 (4명)
- Release Manager (본부 8)
- Changelog Generator (본부 8)
- Update Checker (본부 8)
- Distribution Agent (본부 8)

**구현률**: 23/46 = **50%**

### ⬜ 잔여 (Phase 6~9, 23명)

#### Phase 6 — 실행 엔진 확장 (5명)
- Web Scraping Specialist / Desktop Automation Specialist / API Integration Developer / Data Parser Engineer / DevOps Engineer (본부 3)
- (Integration Architect — 위치 미확정)

#### Phase 7 — 품질·보안 강화 (4명)
- Robustness Tester / Security Auditor / Performance Engineer / Compliance Officer (본부 4)

#### Phase 8 — C-Level 완성 (2명)
- CEO Agent / CFO Agent (경영진)

#### Phase 9 — 나머지 본부 완성 (12명)
- 본부 1: 4명 (Process Discovery / BA / ROI / Feasibility)
- 본부 2: 3명 (Product Manager / Workflow Designer / Error Handling Designer)
- 본부 5: 1명 (Documentation Agent)
- 본부 6: 3명 (Project Coordinator / Human Liaison / Monitoring Agent)

---

## 🚀 다음 단계 전망

### Track A: `.exe` 생성기 (목표: 외부 도구 풀체인)

| Phase | 상태 | 마일스톤 |
|---|---|---|
| ✅ Phase 4 | 완료 | GUI 자동 생성 |
| ✅ Phase 4.5 | 완료 | 빌드 사양 산출 |
| ✅ Phase 5 | 완료 | 배포 자동화 사양 |
| ✅ **PR #36** | **완료** | **외부 도구 첫 호출 + 첫 `.exe` 산출** |
| 🔄 Phase 5 풀체인 (PR #37~) | 진행 중 | E2E 자연어 → `.exe` 자동 생성 |
| ⬜ PR #38+ | 예정 | GitHub Release 자동 업로드 (gh release create) |

### Track B: 업무 자동화 완성 (목표: 46명 완성)

| Phase | 추가 에이전트 | 누적 | 마일스톤 |
|---|---|---|---|
| ⬜ Phase 6 | 5명 | 28명 | 실행 엔진 확장 |
| ⬜ Phase 7 | 4명 | 32명 | 품질·보안 강화 |
| ⬜ Phase 8 | 2명 | 34명 | C-Level 완성 |
| ⬜ Phase 9 | 12명 | **46명** | **M5: 전체 완성** |

---

## 🏆 주요 성과 (PR #25-36, 단일 세션 8시간)

### 2개 본부 100% 완성 + 외부 도구 통합 시작
- **본부 7: 디자인 본부** (3명 전체) — Phase 4 완료
- **본부 8: 빌드 & 배포 본부** (9명 전체) — Phase 5 완료
- **+ build_executor 도구** (PR #36) — 첫 외부 도구 호출 ✅

### 이슈 4 / 5 / 6 모두 close
- **이슈 4** (GUI 4 에이전트 본문 누락) — PR #25 fix
- **이슈 5** (비-GUI 16 에이전트) — PR #27 fix
- **이슈 6** (LLM 비결정적 컴플라이언스) — PR #29 (방어선 1) + PR #31/#33 (방어선 2)

### 첫 진짜 `.exe` 산출 (PR #36)
```
[BUILD SUCCESS] Calculator.exe (10.7 MB, sha256=7b66044e353edb10..., elapsed=18.4s)
- 형식: PE32+ executable (GUI) x86-64, for MS Windows
- 입력: 자연어 "계산기 만들어줘" → calculator.py (PR #34 산출, 21,332자)
- 출력: 실행 가능한 .exe 파일
```

### 기술 지표
- pytest **199개 통과** (네트워크 호출 0건, 누적 +75)
- 누적 **36개 PR 모두 main 안착** (단일 세션 +12)
- 14 에이전트 `output_pydantic` 적용 (시범 2 + 확장 12)
- 캡처율 **38% → 94%** (4차 → 7차 E2E)

---

## 📜 변경 이력

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v2.0 | 2026-04-17 | 최초 6개 본부 + 경영진 구조 |
| v3.0 | 2026-04-17 | 자율 반복 루프 4개 에이전트 추가 |
| v4.0 | 2026-04-17 | 디자인, 빌드 & 배포 본부 신설 → 8개 본부 |
| v5.0 | 2026-04-20 | Phase 4 완료 반영: 디자인 본부 100% |
| v5.1 | 2026-04-20 | Phase 4.5 + 5 완료 반영: 빌드 & 배포 본부 100%, 전체 50% 달성 |
| **v6** | **2026-04-28** | **PR #25-36 반영: 이슈 4/5/6 close + 외부 도구 통합 첫 시작 + 첫 `.exe` 산출** |

---

*본 조직도는 PR #36 머지 시점까지의 진행 상황을 반영한 최신 버전입니다.*
*총 46명 구조는 유지되며, 에이전트 배치는 책임 경계 유지 하에 유연하게 조정합니다.*
*도구 컴포넌트(build_executor)는 본부 8의 외부 도구 통합 첫 단계로, 정원에 포함되지 않습니다.*
