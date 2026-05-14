# 🚀 Nexus Alpha 구성안 v7 — Alpha 외부 검증 + Security baseline + ⭐ v5 비전 (진짜 multi-agent collaboration) 신설

**━ 사용자의 한 마디에서 *데스크탑/웹 앱 + .exe* 까지 ━**

> **v6 대비 핵심 변경**: 친구 PC 첫 외부 라이브 빌드 성공 (Message_App.exe) + Security baseline 활성화 + 종합 점검 6 본질적 통찰 발견 + ⭐ **v5 비전 신설** (진짜 multi-agent collaboration = 자기 진화형 소프트웨어)
> **2026-05-14 (PR #137 머지 + 종합 점검 완료)**: 134 PR 누적, pytest 992 passed, 외부 PC 2대 검증, 본부 10 (Coordination/Communication) 신설 비전
> **본 버전 (v7) 갱신일**: **2026년 5월 14일**

---

## 📑 목차

1. [v6 → v7 핵심 변경](#1-v6--v7-핵심-변경)
2. [v4 비전 (자연어 → .exe) — 완료 상태 검증](#2-v4-비전-자연어--exe--완료-상태-검증)
3. [⭐ v5 비전 (진짜 multi-agent collaboration) — 신규](#3-v5-비전-진짜-multi-agent-collaboration--신규)
4. [v5 의 4 Phase 진화 경로](#4-v5-의-4-phase-진화-경로)
5. [본인이 발견한 6 통찰 (north star)](#5-본인이-발견한-6-통찰-north-star)
6. [v6 의 Tauri/Electron Beta 비전 vs v5 우선순위](#6-v6-의-tauri-electron-beta-비전-vs-v5-우선순위)
7. [변경 이력](#7-변경-이력)

---

## 1. v6 → v7 핵심 변경

| 항목 | v6 (PR #119 시점) | **v7 (PR #137 + 종합 점검)** |
|---|---|---|
| 누적 PR | 119 | **137** (+18) |
| pytest | 784 | **992** (+208) |
| **외부 PC 검증** | 1대 (Calculator.exe 10.73 MB) | ✅ **2대** (Calculator + Message_App.exe 9.86 MB / 33.11 min) |
| **Security 자동화** | 0 | ✅ gitleaks + dependabot + CodeQL + BFG 절차 |
| **Build 비용** | 33min / max_tokens 1024 (retry 폭증) | ~25min / max_tokens 4096 (~30%↓) |
| **본질적 통찰** | (스코프 외) | ⭐ **6 통찰 발견** (위장된 협업 / 소통 부재 / 가상 기업 갭 / 분업+공유+피드백 부재 / Observability 부재 / **본인 비전**) |
| **본부 수** | 9 (RV 신규) | **10** (Coordination/Communication 신규) |
| **에이전트 정원** | 50 | **54** (+4: Coordination/Communication) |
| **차세대 비전** | RV 비전 (DoD 9/9) | ⭐ **v5 비전: 진짜 multi-agent collaboration** |

---

## 2. v4 비전 (자연어 → .exe) — 완료 상태 검증

### v4 의 약속

> 사용자: "메모장 만들어줘"
>     ↓ (LLM + CrewAI + LangGraph)
> 완성품: Memo.exe (더블클릭 실행)

### v4 약속 vs 실제 (2026-05-14 기준)

| v4 약속 | 실제 | 상태 |
|---------|------|------|
| 자연어 → 사양 | CTO + Analyst + UI Designer + Engineer | ✅ 완료 (PR #1~#97) |
| 사양 → 코드 | GUI Code Generator + 테스트 | ✅ 완료 |
| 코드 → .exe | Build Engineer + PyInstaller | ✅ 완료 (PR #82) |
| .exe → 배포 | Distribution Agent + gh release | ✅ 완료 (PR #83) |
| 외부 PC 검증 | 친구 PC Message_App.exe 9.86 MB / 33.11 min | ✅ **2026-05-14 입증** |

→ **v4 비전 완료**. 다음은 v5.

---

## 3. ⭐ v5 비전 (진짜 multi-agent collaboration) — 신규

### v5 의 약속

> v4 = "자연어 → .exe" (산출물 자동화)
> **v5 = "AI 가상 기업이 *진짜로 협업해서* 산출물 자동화" (협업 자동화)**

### 왜 v5 가 필요한가 (환율 변환기 사례)

PR #133 의 5차 검증에서 발견:

```
[CTO]              "frankfurter API 사용 권장"     ← 실시간 가정
[Analyst]          "캐시 적중률 K3"                ← 실시간 가정
[UI Designer]      "조회 중 로딩 스피너 표시"      ← 실시간 가정
[GUI Code Gen]     "정적 환율 dict 내장"           ← 혼자 다름!
[QA Reviewer]      "코드 품질 양호"                ← 일관성 미검증 → 통과
                                                ↓
                  Currency_Converter.exe 정상 빌드
                  but 1 USD = 1365.5 stale (실제 ~1490, 9% 오차)
```

**4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함.** 코드 품질은 OK, 빌드는 성공, .exe 도 동작. 하지만 *cross-agent inconsistency* 가 사용자에게 stale 데이터로 나타남.

→ v4 가 산출물을 자동화했다면, v5 는 *협업 자체* 를 자동화해서 이런 결함을 사전 차단.

### v5 = "자기 진화형 소프트웨어" 의 진짜 의미

| 단어 | 진짜 의미 | 현재 상태 |
|------|--------|--------|
| **자기** | 알아서 협의 + 결정 | ❌ PM 이 매번 fixup 으로 패치 |
| **진화** | 회고 + 학습으로 매 빌드마다 점점 좋아짐 | ❌ PM 머릿속만 진화 (백스토리에 freeze) |
| **형 (型)** | 진짜 회사 같은 협업 체계 | ❌ "같은 건물의 프리랜서들" |

→ 현재 마케팅 ↔ 실제 갭 큼. v5 가 이 갭을 닫는 길.

### v5 의 핵심 메커니즘 — 본부 10 (Coordination/Communication) 신설

[조직도 v11](Nexus_Alpha_조직도_v11.md#본부-10-coordination-communication) 의 4 명 신규 에이전트:

1. **Meeting Facilitator** — 킥오프 회의 / 중간 점검 / 최종 검토 진행
2. **Cross-Agent Consultant** — 양방향 소통 채널 (CrewAI delegation)
3. **Knowledge Curator** (본부 5에서 promote) — 매 빌드 인덱싱 + RAG
4. **Retrospective Lead** — 매 빌드 후 회고 자동 작성

---

## 4. v5 의 4 Phase 진화 경로

### Phase 1 — Foundation (PR #138, Sprint 2 1순위)

**목표**: 에이전트가 *서로의 산출물을 볼 수 있게*. 인프라 먼저.

```
LangGraph state 에 shared_context: dict[str, dict] 추가
  ↓
모든 에이전트의 task description 에 "다른 에이전트들이 이미 결정한 내용" 자동 주입
  ↓
Meeting Facilitator (협의 에이전트 1명) 신설
  ↓
워크플로 시작 시 킥오프 회의 자동 진행 → shared_kickoff_decisions.yaml 산출
```

**효과**: 환율 사례 재현 시 — GUI Code Generator 가 CTO 의 "frankfurter API" 결정을 *볼 수 있음*. 실시간 가정 통일.

**작업 규모**: M (~300줄)

### Phase 2 — Bidirectional (PR #141, Sprint 2 2순위)

**목표**: 에이전트끼리 *대화 + 위임*.

```
Cross-Agent Consultant 신설 (질문 라우팅 + 답변 정리)
  ↓
CrewAI allow_delegation=True 부분 ON (Code Reviewer ↔ Engineer 만 시도)
  ↓
gui_test_executor.py (Vision API GUI 검증) 를 scripts/run.py 의 build 후 자동 호출
  ↓
mockup vs 실제 .exe GUI 일치 검증
  ↓
inconsistency 시 Engineer 에게 revision 요청 가능
```

**효과**: 환율 사례 재현 시 — Code Reviewer 가 "이 코드의 환율은 정적 dict, CTO 사양은 frankfurter API" 같은 inconsistency 를 *직접 검출* + Engineer 에게 revision 요청.

**작업 규모**: L (~500줄+)

### Phase 3 — Learning (PR #140 + 회고 PR sequence, Sprint 2 3순위 또는 Sprint 3)

**목표**: 매 빌드 회고 → 다음 빌드 반영. 진짜 자기 진화 시작.

```
Knowledge Curator 활성화 (post-run hook)
  ↓
매 빌드 종료 시 outputs/<run>/ 인덱싱 → outputs/_index.yaml 누적
  ↓
RAG Searcher 활성화 (pre-run hook)
  ↓
사용자 요청 직후 "이전에 비슷한 요청 본 적 있음" UX (top-K 과거 .exe + 메타)
  ↓
Retrospective Lead 신설 (매 빌드 후 회고 YAML 자동 작성)
  ↓
회고 → 다음 빌드의 Engineer prompt 에 컨텍스트로 주입
```

**효과**: PR #133 의 16 fixup 같은 "방어선 패턴" 데이터 자동 누적 → 다음 빌드 Engineer 가 패턴 학습 → PM 진화형 → *시스템 자기 진화형* 전환.

**작업 규모**: L (multi-PR sequence)

### Phase 4 — Visualization (PR #145 + Vision QA 확장, Sprint 3+)

**목표**: 사용자도 회의 참관 가능. Observability.

```
실시간 대시보드 (tqdm + 에이전트 활동 로그 + Quick Edit 끄기 안내)
  ↓
스크린샷 → Vision API 분석 결과를 사용자 화면에 표시
  ↓
회의 진행 중 사용자가 개입 가능 (선택 — Phase 4 후속)
```

**효과**: 22~33min 빌드 중 dead screen 결함 해결 + 친구 PC Quick Edit 사고 재발 방지.

**작업 규모**: M~L

---

## 5. 본인이 발견한 6 통찰 (north star)

| # | 통찰 | 처방 Phase |
|---|------|---------|
| 1 | 위장된 협업 (Pseudo-Collaboration) | Phase 1, 2 |
| 2 | 에이전트 간 소통 부재 (환율 사례) | Phase 1, 2 |
| 3 | AI 가상 기업 비전 갭 (회의/멘토링/회고/학습/ADR/갈등해결 모두 0) | Phase 3 |
| 4 | 분업 + 공유 + 피드백 메커니즘 부재 (D-1~D-5) | Phase 1, 2, 3 |
| 5 | 사용자 관점 Observability 부재 (Quick Edit 사고) | Phase 4 |
| **6** ⭐ | **본인의 본질적 비전 — 진짜 multi-agent collaboration** | **모든 PR 의 north star** |

→ 상세는 [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md).

---

## 6. v6 의 Tauri/Electron Beta 비전 vs v5 우선순위

### v6 의 배포 로드맵
```
Alpha (install.ps1) → Beta (Streamlit) → Release (Electron/Tauri)
```

### v7 의 결정: **v5 우선, Tauri/Electron 보류**

**이유**:
- v5 (진짜 협업) 미완 상태에서 UI 레이어 (Streamlit/Tauri) 추가 = 같은 결함이 더 화려한 UI 로 노출
- 1 외부 사용자 (친구 PC) → 134 PR 비율 = 무리한 scope 확장 위험
- v5 완료 후 진짜 검증된 시스템 위에 UI 레이어 올리는 것이 안전

→ **베타 cohort 5명 (~$250 budget) 으로 v5 검증 우선**. 그 후 Tauri/Electron 결정.

---

## 7. 변경 이력

| 버전 | 일자 | 핵심 변경 |
|------|------|---------|
| v5 | 2026-04-29 | 본부 4 (QA) 9/9 도달 |
| v6 | 2026-05-11 | Alpha 진입점 완성 + Public 전환 + RV 비전 |
| **v7** | **2026-05-14** | **외부 PC 2대 검증 + Security baseline + ⭐ v5 비전 신설 (본부 10 Coordination/Communication)** |

---

**관련 문서**:
- ⭐ [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — v5 비전의 6 통찰 + Phase 1~4 (북극성)
- [docs/architecture/Nexus_Alpha_조직도_v11.md](Nexus_Alpha_조직도_v11.md) — 본부 10 (Coordination/Communication) 신설 비전
- [docs/architecture/Nexus_Alpha_구성안_v6.md](Nexus_Alpha_구성안_v6.md) — 이전 v6 (RV 비전 + Track A/B)
- [docs/health_check/project_health_check_20260514.md](../health_check/project_health_check_20260514.md) — 종합 점검 evidence
- [docs/next_session_context.md](../next_session_context.md) — 다음 세션 핸드오프
