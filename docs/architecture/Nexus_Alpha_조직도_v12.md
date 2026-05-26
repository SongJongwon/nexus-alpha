# 🏛️ Nexus Alpha 공식 조직도 v12 (코드 기준 갱신 + 미구현 15명 직책 명시)

**개정일**: 2026-05-26 (Sprint 6 UI 개편 PR #206 이후 — 54명 전체 UI 표현 요구)
**최신 구조**: 경영진 + **10 개 본부** (v11 동일), 총 **54 명 에이전트**
**현재 상태**: **39/54 명 구현 (72%)** — v11 동일 + 미구현 15 명의 *구체 직책* 본 v12 에서 명시

---

## 🚀 v11 → v12 핵심 변경사항

v12 는 *조직 변경* 이 아닌 **명세 보강** 이 목적:

| 항목 | v11 (2026-05-14) | **v12 (2026-05-26)** |
|------|------------------|----------------------|
| 정원 / 구현 / 미구현 | 54 / 39 / 15 | **동일** (변경 0) |
| 본부 수 | 10 | 동일 |
| **미구현 15 명의 구체 직책** | "Phase 9 예정" 등 추상 | ⭐ **본 v12 에서 명시 명단 작성** |
| **본부별 정원 분배** | v8 인용 (상세 명단 X) | ⭐ **본 v12 에서 코드 인벤토리 기준 재명시** |
| **코드 디렉터리 ↔ 본부 매핑** | 미명시 | ⭐ **src/agents/{c_level,analysis,...} ↔ 본부 N** 명시 |
| **사용자 가시화 (UI)** | 활성 13 agent 만 | ⭐ **54 명 전체 표시 + 미구현 회색 처리** ([App.tsx](../../frontend/src/App.tsx)) |
| 백엔드 코드 변경 | n/a | **0** (조직도 docs + UI 만) |

---

## 📊 본부별 정원 + 명단 (코드 기준)

### 본부 0: C-Level — 1/3 (33%)

| # | 직책 | 구현 | 코드 위치 | 비고 |
|---|------|------|----------|------|
| 1 | **CTO** | ✅ | [c_level/cto.py](../../src/agents/c_level/cto.py) | run_chain 의 다중 LLM 중 1 |
| 2 | CEO | ❌ | (미구현) | v10 Phase 8 예정 |
| 3 | CFO | ❌ | (미구현) | v10 Phase 8 예정 |
| 보조 | Convergence Judge | ✅ | [c_level/convergence_judge.py](../../src/agents/c_level/convergence_judge.py) | 본부 4 (QA) 의 *결정론 verdict* 도구. 디렉터리는 c_level 이지만 *논리적* 본부 4. |

### 본부 1: 업무 분석 — 3/5 (60%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Requirement Expander** | ✅ | [analysis/requirement_expander.py](../../src/agents/analysis/requirement_expander.py) |
| 2 | **Gap Analyst** | ✅ | [analysis/gap_analyst.py](../../src/agents/analysis/gap_analyst.py) |
| 3 | **Data Analyst** | ✅ | [analysis/data_analyst.py](../../src/agents/analysis/data_analyst.py) (Track B) |
| 4 | Business Process Analyst | ❌ | (미구현) |
| 5 | Use Case Specialist | ❌ | (미구현) |

### 본부 2: 기획 및 설계 — 1/3 (33%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **UI/UX Analyst** | ✅ | [planning/ui_ux_analyst.py](../../src/agents/planning/ui_ux_analyst.py) |
| 2 | Product Manager | ❌ | (미구현) |
| 3 | Project Coordinator | ❌ | (미구현) |

### 본부 3: 개발 (Track A + Track B) — 6/8 (75%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Python Engineer** | ✅ | [engineering/python_engineer.py](../../src/agents/engineering/python_engineer.py) (Track A 핵심) |
| 2 | **Web Scraping Specialist** | ✅ | [engineering/web_scraping_specialist.py](../../src/agents/engineering/web_scraping_specialist.py) (Track B) |
| 3 | **API Integration Developer** | ✅ | [engineering/api_integration_developer.py](../../src/agents/engineering/api_integration_developer.py) (Track B) |
| 4 | **Data Parser Engineer** | ✅ | [engineering/data_parser_engineer.py](../../src/agents/engineering/data_parser_engineer.py) (Track B) |
| 5 | **Desktop Automation Specialist** | ✅ | [engineering/desktop_automation_specialist.py](../../src/agents/engineering/desktop_automation_specialist.py) (Track B) |
| 6 | **DevOps Engineer** | ✅ | [engineering/devops_engineer.py](../../src/agents/engineering/devops_engineer.py) (Track B) |
| 7 | Mobile Developer | ❌ | (미구현, v10 Phase 9 예정) |
| 8 | Embedded Specialist | ❌ | (미구현, v10 Phase 9 예정) |

### 본부 4: 품질 검증 — 10/10 (100%) ✅

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Code Reviewer** | ✅ | [qa/code_reviewer.py](../../src/agents/qa/code_reviewer.py) |
| 2 | **Pytest Author** | ✅ | [qa/pytest_author.py](../../src/agents/qa/pytest_author.py) |
| 3 | **Code QA Agent** | ✅ | [qa/code_qa_agent.py](../../src/agents/qa/code_qa_agent.py) |
| 4 | **Functional Test Agent** | ✅ | [qa/functional_test_agent.py](../../src/agents/qa/functional_test_agent.py) |
| 5 | **GUI Test Agent** | ✅ | [qa/gui_test_agent.py](../../src/agents/qa/gui_test_agent.py) |
| 6 | **Performance Engineer** | ✅ | [qa/performance_engineer.py](../../src/agents/qa/performance_engineer.py) |
| 7 | **Security Auditor** | ✅ | [qa/security_auditor.py](../../src/agents/qa/security_auditor.py) |
| 8 | **Compliance Officer** | ✅ | [qa/compliance_officer.py](../../src/agents/qa/compliance_officer.py) |
| 9 | **Robustness Tester** | ✅ | [qa/robustness_tester.py](../../src/agents/qa/robustness_tester.py) |
| 10 | **Convergence Judge** | ✅ | [c_level/convergence_judge.py](../../src/agents/c_level/convergence_judge.py) (논리적 본부 4) |

### 본부 5: 지식 관리 — 2/3 (67%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Knowledge Curator** | ✅ | [knowledge/curator.py](../../src/agents/knowledge/curator.py) |
| 2 | **RAG Searcher** | ✅ | [knowledge/rag_searcher.py](../../src/agents/knowledge/rag_searcher.py) |
| 3 | Documentation Lead | ❌ | (미구현) |

### 본부 6: 운영 지원 — 1/2 (50%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Sandbox Runner** | ✅ | [operations/sandbox_runner.py](../../src/agents/operations/sandbox_runner.py) |
| 2 | Monitoring Engineer | ❌ | (미구현) |

### 본부 7: 디자인 — 3/3 (100%) ✅

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **GUI Code Generator** | ✅ | [design/gui_code_generator.py](../../src/agents/design/gui_code_generator.py) |
| 2 | **GUI Designer** | ✅ | [design/gui_designer.py](../../src/agents/design/gui_designer.py) |
| 3 | **Theme Designer** | ✅ | [design/theme_designer.py](../../src/agents/design/theme_designer.py) |

### 본부 8: 빌드 & 배포 — 9/9 (100%) ✅

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Build Engineer** | ✅ | [build_release/build_engineer.py](../../src/agents/build_release/build_engineer.py) |
| 2 | **Asset Manager** | ✅ | [build_release/asset_manager.py](../../src/agents/build_release/asset_manager.py) |
| 3 | **Changelog Generator** | ✅ | [build_release/changelog_generator.py](../../src/agents/build_release/changelog_generator.py) |
| 4 | **Dependency Analyzer** | ✅ | [build_release/dependency_analyzer.py](../../src/agents/build_release/dependency_analyzer.py) |
| 5 | **Distribution Agent** | ✅ | [build_release/distribution_agent.py](../../src/agents/build_release/distribution_agent.py) |
| 6 | **Installer Creator** | ✅ | [build_release/installer_creator.py](../../src/agents/build_release/installer_creator.py) |
| 7 | **Platform Tester** | ✅ | [build_release/platform_tester.py](../../src/agents/build_release/platform_tester.py) |
| 8 | **Release Manager** | ✅ | [build_release/release_manager.py](../../src/agents/build_release/release_manager.py) |
| 9 | **Update Checker** | ✅ | [build_release/update_checker.py](../../src/agents/build_release/update_checker.py) |

### 본부 9: Runtime Verification (RV) — 0/4 (0%) ⚠

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | Exe Runtime Tester | ❌ | v10 Phase A (1순위 후보) |
| 2 | UI Automation Specialist | ❌ | v10 Phase B |
| 3 | Runtime Failure Analyzer | ❌ | v10 Phase C |
| 4 | Auto-Fix Coordinator | ❌ | v10 Phase C |

### 본부 10: Coordination / Communication — 2/4 (50%)

| # | 직책 | 구현 | 코드 위치 |
|---|------|------|----------|
| 1 | **Meeting Facilitator** | ✅ | [coordination/meeting_facilitator.py](../../src/agents/coordination/meeting_facilitator.py) |
| 2 | **Retrospective Lead** | ✅ | [coordination/retrospective_lead.py](../../src/agents/coordination/retrospective_lead.py) |
| 3 | Cross-Agent Consultant | ❌ | v11 Phase 2 (PR #141 예정) |
| 4 | Knowledge Curator (promoted) | ❌ | v11 Phase 3 — 본부 5 의 Curator 를 본부 10 으로 *조직개편*. 별도 구현 X, 매핑/wiring 만 |

---

## 📊 집계표

| 본부 | 정원 | 구현 | 미구현 | % |
|------|------|------|--------|---|
| 0 C-Level | 3 | 1 (+1 보조 CJ) | 2 | 33% |
| 1 업무 분석 | 5 | 3 | 2 | 60% |
| 2 기획 및 설계 | 3 | 1 | 2 | 33% |
| 3 개발 | 8 | 6 | 2 | 75% |
| **4 품질 검증** ✅ | **10** | **10** | **0** | **100%** |
| 5 지식 관리 | 3 | 2 | 1 | 67% |
| 6 운영 지원 | 2 | 1 | 1 | 50% |
| **7 디자인** ✅ | **3** | **3** | **0** | **100%** |
| **8 빌드 & 배포** ✅ | **9** | **9** | **0** | **100%** |
| 9 Runtime Verification | 4 | 0 | 4 | 0% |
| 10 Coordination | 4 | 2 | 2 | 50% |
| **합계** | **54** | **38+CJ=39** | **15** | **72%** |

(Convergence Judge 는 c_level 디렉터리지만 본부 4 의 *결정론 도구*. 본 v12 에서는 본부 4 의 10번째 멤버로 카운트 → 합 39.)

---

## 🗺️ Telemetry 노드 ↔ 본부 매핑 ([src/monitoring/telemetry.py](../../src/monitoring/telemetry.py))

`_NODE_DEPARTMENT` 의 3 telemetry 부서 (planning/engineering/learning) 가 어느 11 본부로 매핑되는지:

| iterative_loop 노드 | telemetry 부서 | 실 호출 본부 | 비고 |
|--------------------|---------------|------------|------|
| `expand_requirements` | planning | 본부 1 | Requirement Expander |
| `kickoff_meeting` | planning | 본부 10 | Meeting Facilitator |
| `analyze_gap` | planning | 본부 1 | Gap Analyst |
| `prepare_feedback` | planning | (helper) | LLM 호출 없음 |
| `run_chain` | engineering | **본부 0 + 본부 3 + 본부 4 (+ 본부 7 GUI 분기)** | 다중 LLM (CTO + Engineer + Reviewer + 분기별 GUI Code Gen / Pytest Author) |
| `run_sandbox` | engineering | 본부 6 | Sandbox Runner (subprocess) |
| `recall_past_knowledge` | learning | 본부 5 | RAG Searcher |
| `judge_convergence` | learning | 본부 4 | Convergence Judge (결정론) |
| `retrospective` | learning | 본부 10 | Retrospective Lead |
| `retrospective_blocked` | learning | 본부 10 | 동일 (BLOCKED alias) |
| `curate_knowledge` | learning | 본부 5 | Knowledge Curator |
| `curate_knowledge_blocked` | learning | 본부 5 | 동일 (BLOCKED alias) |
| `finalize` / `escalate` | system | (오케스트레이션) | LLM 호출 없음 |

---

## 🎨 UI 차원 (Tauri Agent Office)

[frontend/src/App.tsx](../../frontend/src/App.tsx) 의 `HEADQUARTERS` 배열이 본 v12 의 11 본부 + 54 멤버를 *그대로* 표현. 미구현 15 명은 회색 character + "미구현" 뱃지로 시각화.

본부별 색상 (UI 차원):

| 본부 | 색상 |
|------|------|
| 0 C-Level | 🟡 amber |
| 1 업무 분석 | 🟦 sky |
| 2 기획 및 설계 | 🟣 violet |
| 3 개발 | 🟢 emerald |
| 4 품질 검증 | 🔴 red |
| 5 지식 관리 | 🟢 teal |
| 6 운영 지원 | ⬜ slate |
| 7 디자인 | 🩷 pink |
| 8 빌드 & 배포 | 🟢 lime |
| 9 RV | 🟠 orange |
| 10 Coordination | 🟣 purple |

---

## 📜 변경 이력

| 버전 | 일자 | 핵심 변경 |
|------|------|----------|
| v11 | 2026-05-14 | Coordination/Communication 본부 신설 (54명) — 통찰 6 반영 |
| **v12** | **2026-05-26** | **미구현 15 명 구체 직책 명시 + 코드 디렉터리 ↔ 본부 매핑 + Telemetry 노드 ↔ 본부 매핑 + UI 11 본부 grid (Sprint 6)** |

---

**관련 문서**:
- [Nexus_Alpha_조직도_v11.md](Nexus_Alpha_조직도_v11.md) — 직전 버전
- [agent_org_chart.md](agent_org_chart.md) — Tauri UI 3 부서 (v11) → 11 본부 (v12) 확장
- [system_architecture.md](system_architecture.md) — 3 계층 (백엔드 + Telemetry + Tauri sidecar)
- [../../src/monitoring/telemetry.py](../../src/monitoring/telemetry.py) — `_NODE_DEPARTMENT` 런타임 진실
- [../../frontend/src/App.tsx](../../frontend/src/App.tsx) — UI 표현 (Sprint 6 PR #206 + v12 PR)
