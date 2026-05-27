# 🏛️ Nexus Alpha 공식 조직도 v13 — Boardroom 기반 자기 진화형 소프트웨어 (Self-Evolving Software)

**개정일**: 2026-05-27 (PR #211 직후 — fixup #16 머지로 풀체인 .exe 자동화 완성)
**최신 구조**: 이사회(Board) + 10 개 본부, 총 **52 명 에이전트** (v12 의 54 → 정원 다이어트 -2)
**현재 상태**: **39/52 (75%)** — Boardroom Facilitator 가 *자기 진화 루프의 핵심 허브*

---

## 🚀 v12 → v13 핵심 변경 — 패러다임 shift

v13 는 *조직 명세* 가 아닌 **운영 패러다임의 근본적 재정의**:

| 항목 | v12 | **v13** |
|------|-----|---------|
| 패러다임 | 인간 요구사항을 처리하는 *수동형 파이프라인* | **시스템이 스스로 문제 감지 → 부서 대표 토론 → 자율 개선안 도출하는 *Boardroom 기반 자기 진화*** |
| 정원 / 구현 / 미구현 | 54 / 39 / 15 | **52 / 39 / 13** (다이어트) |
| C-Level CEO | (추상적 미구현) | ⭐ **Goal Alignment Agent** — 이사회 의장 (목적 + 보안 거버넌스 최종 조율) |
| C-Level CFO | (추상적 미구현) | ⭐ **Token Budget Optimizer** — 기술재무관 (LLM 비용 + 컴퓨팅 한도 *브레이크*) |
| Meeting Facilitator | 단순 회의 진행 (구현 ✅) | ⭐ **Boardroom Facilitator** — Telemetry 기반 *전략 이사회* 의장 (티키타카 리드) |
| 본부 1 분석직 | BPA + UCS (추상 미구현) | 🗑 삭제 + **System Refactoring Strategist** 신설 (자율 개선안 발제) |
| 본부 2 기획 | Project Coordinator (미구현) | 🗑 삭제 (Boardroom Facilitator 와 역할 중복) |
| 본부 9 RV 비고 | "Phase A 1순위 후보" | ⭐ **★자기 진화 루프의 핵심 노드로 최우선 구현 예정 (Phase 1순위)** |

### 변경 원칙 (PM 명시)

1. **에이전트 간 불필요한 인간식 행정 커뮤니케이션 오버헤드 제거** — Project Coordinator / BPA / UCS 같은 *과분화된 행정 직책* 다이어트
2. **추상적 경영진 + 중재자 재정의** — 모호한 CEO/CFO/Meeting Facilitator 를 *기술 자원 제어* + *집단 지성 토론(티키타카) 의장* 으로 명확화
3. **Telemetry 기반 자율 진화 루프 완비** — *감지(RV) → 전략토론(Boardroom) → 비용제어(Token Budget) → 자율배포(Build & Release)*

---

## 🌟 v13 의 핵심 — Boardroom 자율 진화 루프

```
┌────────────────────────────────────────────────────────────────┐
│  [Telemetry 감지 — 본부 9 RV ★최우선]                          │
│  Exe Runtime Tester / Failure Analyzer 가 시스템 다운 / 성능   │
│  저하 / silent fail 패턴을 자율 인지 → 이사회 긴급 회의 트리거 │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  [안건 발제 — 본부 1 System Refactoring Strategist]            │
│  런타임 로그 + Telemetry 분석 → 시스템 자율 개선안 작성        │
│  (예: "max_iterations 3 으로 상향" / "GUI sandbox SKIP 강화")  │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  [전략 이사회 소집 — 본부 10 Boardroom Facilitator 의장]        │
│  C-Level (Goal Alignment + Token Budget + CTO + Convergence    │
│  Judge) + 각 부서 대표 + System Refactoring Strategist 가       │
│  티키타카 토론                                                  │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  [의장단 조율]                                                  │
│  ▸ Goal Alignment Agent: "목적 + 보안 거버넌스 부합?"            │
│  ▸ Token Budget Optimizer: "예산 한도 초과 X? 토큰 견적은?"      │
│  ▸ Boardroom Facilitator: 합의 / 타협점 도출                    │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  [자율 배포 — 본부 8 Build & Release + 본부 7 Design 분기]      │
│  합의된 개선안을 코드/UI 변경 → PyInstaller → Release Manager   │
└────────────────────────────────────────────────────────────────┘
```

### 본부 4 (QA) + 본부 9 (RV) 의 관계 재정의

| 본부 | 책임 | v13 위치 |
|------|------|---------|
| 본부 4 (QA) | *코드 level* 검증 (pytest / ruff / Vision QA / Convergence Judge 결정론) | **개발 사이클** 내부 |
| **본부 9 (RV) ★** | *런타임 level* 검증 (.exe 동작 / UI 시나리오 / Failure trace 분석) | **자율 진화 루프** 의 *감지 노드* |

→ RV 가 본부 4 의 한계를 *자율 진화 차원* 에서 보완. v10 비전이 *Phase 1 순위* 로 격상.

---

## 📊 본부별 정원 + 명단 (v13 — 코드 기준 + 패러다임 재정의)

### 본부 0: C-Level (Boardroom) — 1/3 (33%)

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | **CTO** | ✅ | run_chain 의 첫 LLM — 기술 전략 결정 |
| 2 | **Goal Alignment Agent** ⭐ v13 | ❌ | (이전 CEO) 이사회 의장 역임. 시스템 궁극적 *목적* 및 *보안 거버넌스* 최종 조율 |
| 3 | **Token Budget Optimizer** ⭐ v13 | ❌ | (이전 CFO) 이사회 기술재무관. *LLM 호출 비용 + 컴퓨팅 자원 한도 기반 브레이크* |
| 보조 | Convergence Judge | ✅ | 본부 4 QA 의 *결정론 verdict* 도구 (디렉터리는 c_level 이지만 *논리적* 본부 4) |

### 본부 1: 업무 분석 — 3/4 (75%)

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | **Requirement Expander** | ✅ | 사용자 요청 YAML 확장 (요구사항 고도화 흡수) |
| 2 | **Gap Analyst** | ✅ | iteration feedback gap 분석 |
| 3 | **Data Analyst** | ✅ | Track B 분석 + instruction |
| 4 | **System Refactoring Strategist** ⭐ v13 | ❌ | 런타임 로그 + Telemetry 분석 → 이사회 *자율 개선안* 안건 발제 |

🗑 v12 의 *Business Process Analyst* / *Use Case Specialist* 삭제 (Requirement Expander 로 통합 — 행정 오버헤드 다이어트).

### 본부 2: 기획 및 설계 — 1/2 (50%)

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | **UI/UX Analyst** | ✅ | Track A GUI 분기 |
| 2 | Product Manager | ❌ | 제품 전략 (Phase 후보) |

🗑 v12 의 *Project Coordinator* 삭제 (Boardroom Facilitator 와 역할 중복).

### 본부 3: 개발 (Track A + Track B) — 6/8 (75%)

| # | 직책 | 구현 |
|---|------|------|
| 1 | **Python Engineer** | ✅ |
| 2 | **Web Scraping Specialist** | ✅ |
| 3 | **API Integration Developer** | ✅ |
| 4 | **Data Parser Engineer** | ✅ |
| 5 | **Desktop Automation Specialist** | ✅ |
| 6 | **DevOps Engineer** | ✅ |
| 7 | Mobile Developer | ❌ |
| 8 | Embedded Specialist | ❌ |

(v12 와 동일)

### 본부 4: 품질 검증 — 10/10 (100%) ✅

| # | 직책 | 구현 |
|---|------|------|
| 1~9 | (9 QA agents 동일) | ✅ × 9 |
| 10 | **Convergence Judge** | ✅ (c_level/ 디렉터리, 논리적 본부 4) |

(v12 와 동일)

### 본부 5: 지식 관리 — 2/3 (67%)

| # | 직책 | 구현 |
|---|------|------|
| 1 | **Knowledge Curator** | ✅ |
| 2 | **RAG Searcher** | ✅ |
| 3 | Documentation Lead | ❌ |

(v12 와 동일)

### 본부 6: 운영 지원 — 1/2 (50%)

| # | 직책 | 구현 |
|---|------|------|
| 1 | **Sandbox Runner** | ✅ |
| 2 | Monitoring Engineer | ❌ |

(v12 와 동일)

### 본부 7: 디자인 — 3/3 (100%) ✅

| # | 직책 | 구현 |
|---|------|------|
| 1 | **GUI Code Generator** | ✅ |
| 2 | **GUI Designer** | ✅ |
| 3 | **Theme Designer** | ✅ |

(v12 와 동일)

### 본부 8: 빌드 & 배포 — 9/9 (100%) ✅

| # | 직책 | 구현 |
|---|------|------|
| 1~9 | (9 build/release agents) | ✅ × 9 |

(v12 와 동일)

### 본부 9: Runtime Verification (RV) — 0/4 (0%) ★ Phase 1순위

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | Exe Runtime Tester | ❌ | **★자기 진화 루프의 핵심 노드로 최우선 구현 예정 (Phase 1순위)** — 시스템 다운/성능 저하 자율 인지 → 이사회 긴급 회의 트리거 |
| 2 | UI Automation Specialist | ❌ | ★Phase 1순위 후속 |
| 3 | Runtime Failure Analyzer | ❌ | ★Phase 1순위 후속 |
| 4 | Auto-Fix Coordinator | ❌ | ★Phase 1순위 후속 |

⭐ **v13 의 핵심 격상** — RV 가 *자율 진화 루프의 감지 노드*. v12 의 "Phase A 1순위 후보" 에서 **확정 1순위** 로 격상.

### 본부 10: Coordination / Communication — 2/4 (50%)

| # | 직책 | 구현 | 비고 |
|---|------|------|------|
| 1 | **Boardroom Facilitator** ⭐ v13 | ✅ | (이전 Meeting Facilitator) C-Level + 부서 대표 모여 *Telemetry 기반 시스템 개선안* 치열하게 토론 + 타협점 도출하는 **전략 이사회 의장**. 단순 행정 회의가 아닌 *집단 지성 티키타카 리드 리더 에이전트* |
| 2 | **Retrospective Lead** | ✅ | 4-step 회고 (v12 와 동일) |
| 3 | Cross-Agent Consultant | ❌ | v11 Phase 2 — 양방향 라우팅 |
| 4 | Knowledge Curator (promoted) | ❌ | v11 Phase 3 — 본부 5 → 본부 10 조직개편 |

---

## 📊 집계표 (v13 — 정원 52 / 구현 39 / 미구현 13)

| 본부 | 정원 | 구현 | 미구현 | 구현률 |
|------|------|------|--------|--------|
| 0 C-Level | 3 | 1 (+1 보조 CJ) | 2 | 33% |
| 1 업무 분석 | 4 | 3 | 1 | 75% |
| 2 기획 및 설계 | 2 | 1 | 1 | 50% |
| 3 개발 | 8 | 6 | 2 | 75% |
| **4 품질 검증** ✅ | **10** | **10** (9 QA + CJ) | **0** | **100%** |
| 5 지식 관리 | 3 | 2 | 1 | 67% |
| 6 운영 지원 | 2 | 1 | 1 | 50% |
| **7 디자인** ✅ | **3** | **3** | **0** | **100%** |
| **8 빌드 & 배포** ✅ | **9** | **9** | **0** | **100%** |
| 9 Runtime Verification ★ | 4 | 0 | 4 | 0% |
| 10 Coordination | 4 | 2 | 2 | 50% |
| **합계** | **52** | **38+CJ=39** | **13** | **75%** |

(Convergence Judge 는 c_level/ 디렉터리지만 본부 4 *결정론 verdict* 도구로 카운트 — v12 표기 일관성 유지)

### 수학적 정합성 검증

v12 → v13 변경:
- 정원 변화: -2 (BPA 삭제 -1, UCS 삭제 -1, Project Coordinator 삭제 -1, System Refactoring Strategist 신설 +1) = **-2** → 54 - 2 = **52** ✓
- 구현 변화: **0** (Meeting Facilitator → Boardroom Facilitator *명칭만 변경*) → 39 + 0 = **39** ✓
- 미구현 변화: -3 (BPA + UCS + Project Coordinator 삭제) + 1 (System Refactoring 신설) = **-2** → 15 - 2 = **13** ✓
- 합 검증: 39 + 13 = **52** ✓

---

## 🗺️ Telemetry 노드 ↔ 본부 매핑 (v12 동일 + Boardroom 추가)

`_NODE_DEPARTMENT` 와 향후 자율 진화 루프 진입 시점:

| iterative_loop 노드 | telemetry 부서 | 실 호출 본부 | v13 추가 의미 |
|--------------------|---------------|------------|--------------|
| `expand_requirements` | planning | 본부 1 | Requirement Expander |
| `kickoff_meeting` | planning | 본부 10 | **Boardroom Facilitator** (구 Meeting Facilitator) |
| `analyze_gap` | planning | 본부 1 | Gap Analyst |
| `prepare_feedback` | planning | (helper) | LLM 호출 없음 |
| `run_chain` | engineering | 본부 0 + 3 + 4 (+ 7 GUI) | 다중 LLM |
| `run_sandbox` | engineering | 본부 6 | Sandbox Runner |
| `recall_past_knowledge` | learning | 본부 5 | RAG Searcher |
| `judge_convergence` | learning | 본부 4 | Convergence Judge (결정론) |
| `retrospective` | learning | 본부 10 | Retrospective Lead |
| `curate_knowledge` | learning | 본부 5 | Knowledge Curator |
| `finalize` / `escalate` | system | (오케스트레이션) | — |
| **(v13 신설 예정)** `boardroom_trigger` | coordination | 본부 10 | **Boardroom Facilitator** — RV/Refactoring Strategist 가 발제 |
| **(v13 신설 예정)** `goal_alignment_check` | c-level | 본부 0 | **Goal Alignment Agent** |
| **(v13 신설 예정)** `budget_brake` | c-level | 본부 0 | **Token Budget Optimizer** |
| **(v13 신설 예정)** `runtime_verify` | rv | 본부 9 | RV 4 agent (감지 노드) |

---

## 🎨 UI 차원 (Tauri Agent Office — v13)

[frontend/src/App.tsx](../../frontend/src/App.tsx) 의 `HEADQUARTERS` 배열이 본 v13 의 11 본부 + 52 멤버를 그대로 표현.

### 주요 변경 (v12 → v13):
- 본부 0: CEO → Goal Alignment Agent, CFO → Token Budget Optimizer
- 본부 1: BPA + UCS 삭제, System Refactoring Strategist 신설 (5 → 4)
- 본부 2: Project Coordinator 삭제 (3 → 2)
- 본부 10: Meeting Facilitator → Boardroom Facilitator (구현 유지, 명칭만)
- 본부 9: 비고 ★Phase 1순위 격상

본부별 색상 (UI 차원, v12 와 동일):

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
| 9 RV ★ | 🟠 orange (★ Phase 1순위 — 향후 highlight 강화) |
| 10 Coordination | 🟣 purple (Boardroom 의장 본부) |

---

## 📜 변경 이력

| 버전 | 일자 | 핵심 변경 |
|------|------|----------|
| v11 | 2026-05-14 | Coordination/Communication 본부 신설 (54명) — 통찰 6 |
| v12 | 2026-05-26 | 미구현 15명 명단 명시 + 코드 디렉터리 매핑 + UI 11 본부 grid |
| **v13** | **2026-05-27** | ⭐ **Boardroom 기반 자기 진화 패러다임 + CEO/CFO 자율 진화 노드 재정의 + Meeting Facilitator → Boardroom Facilitator + 본부 1/2 다이어트 (52명) + 본부 9 RV ★Phase 1순위 격상** |

---

## 🛣 다음 단계 (v13 이후)

| 우선순위 | 작업 | 책임 본부 |
|----------|------|----------|
| **★ #1** | **본부 9 RV 4 agent 구현** (Exe Runtime Tester / UI Automation / Failure Analyzer / Auto-Fix Coordinator) | 본부 9 |
| #2 | System Refactoring Strategist 구현 | 본부 1 |
| #3 | Goal Alignment Agent + Token Budget Optimizer 구현 | 본부 0 |
| #4 | Boardroom Facilitator 의 *전략 이사회 process* 코드 강화 (v11 Phase 1 의 단순 회의 → v13 의 *티키타카 토론*) | 본부 10 |
| #5 | Cross-Agent Consultant 구현 (v11 Phase 2 — 양방향 라우팅) | 본부 10 |

---

**관련 문서**:
- [Nexus_Alpha_조직도_v12.md](Nexus_Alpha_조직도_v12.md) — 직전 버전 (54명 / 정원 명시 + 코드 매핑)
- [agent_org_chart.md](agent_org_chart.md) — Tauri UI 11 본부 매핑
- [system_architecture.md](system_architecture.md) — 3 계층 (백엔드 + Telemetry + Tauri)
- [../../src/monitoring/telemetry.py](../../src/monitoring/telemetry.py) — `_NODE_DEPARTMENT` 런타임 진실
- [../../frontend/src/App.tsx](../../frontend/src/App.tsx) — v13 UI 표현 (HEADQUARTERS)
