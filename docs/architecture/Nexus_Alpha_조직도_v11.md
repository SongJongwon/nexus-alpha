# 🏛️ Nexus Alpha 공식 조직도 v11 (PR #134-A~#137 — Alpha 외부 검증 + Security baseline + ⭐ Coordination/Communication 본부 신설 비전)

**개정일**: 2026-05-14 (PR #137 머지 + 종합 점검 완료)
**최신 구조**: 경영진 + **10 개 본부** (Coordination/Communication 본부 신규), 총 **54 명 에이전트** (v10 의 50 + Coordination 4)
**현재 상태**: **39/54 명 구현 (72%)** — 본부 10 (Coordination/Communication) 0/4 신규 비전

---

## 🚀 v10 → v11 핵심 변경사항

| 항목 | v10 (PR #102~#118) | **v11 (PR #134-A~#137 + 종합 점검)** |
|---|---|---|
| 누적 PR | 118 | **137** (+19) |
| pytest | 784 | **992** (+208) |
| **외부 PC 검증** | 1대 (Calculator.exe 10.73 MB) | ✅ **2대** (Calculator.exe + Message_App.exe 9.86 MB / 33.11 min) |
| **Security 자동화** | 0 | ✅ gitleaks + dependabot + CodeQL workflow + BFG 절차 |
| **Build 비용** | 33min / 1024 max_tokens (retry 폭증) | ~25min / 4096 max_tokens (~30%↓) |
| **본질적 통찰 발견** | 알파 테스트 5 결함 → RV 본부 비전 | ⭐ **에이전트 간 소통 부재 → Coordination/Communication 본부 비전** |
| **본부 수** | 9 개 (RV 신규) | **10 개** (Coordination/Communication 신규) |
| **에이전트 정원** | 50 명 | **54 명** (+4: Coordination/Communication) |
| 구현률 | 39/50 (78%) | **39/54 (72%)** (정원 확대) |

---

## 🌟 v11 의 핵심 학습 — "에이전트 간 소통 부재" 가 진짜 결함

### 환율 변환기 사례 (정확한 evidence — 2026-05-14 PR #133 5차 검증에서 발견)

| 에이전트 | 산출물 | 실시간 가정 |
|---------|--------|----------|
| CTO | "frankfurter API 사용 권장" | ✅ 실시간 |
| Analyst | "캐시 적중률 K3 (Redis 추정)" | ✅ 실시간 (캐시는 보조) |
| UI Designer | "조회 중 로딩 스피너 표시" | ✅ 실시간 (로딩 = 비동기) |
| **GUI Code Generator** | **"정적 환율 dict 내장" `{"USD": 1365.5, ...}`** | ❌ **혼자 다름** |
| QA Reviewer | "코드 품질 양호" | ❌ **일관성 미검증 → 통과** |

**결과**: 친구 PC 에서 1 USD = **1,365.5 KRW** 표시 (실제 환율 ~1,490 → **9% 오차**). API 호출 코드 0줄. 로딩 스피너는 즉시 사라짐 (실은 dict lookup).

→ **4 에이전트가 다른 가정으로 일했지만 누구도 인지 못함.** 이게 v11 의 핵심 학습.

### 진단: 위장된 협업

- `allow_delegation=False` (24/24 에이전트)
- `Process.sequential` 만 (11/11 Crew, hierarchical 0)
- `memory=False` (cross-run 학습 0)
- `Task.context=[prev_task]` 단방향만

→ **"AI 가상 기업" 이 사실은 "같은 건물의 프리랜서들"** — 진짜 협업 메커니즘 0.

### 처방: Coordination/Communication 본부 신설

진짜 회사에는 *반드시* 있는데 nexus-alpha 에 **없는** 메커니즘:
- 회의 (epistemic exchange)
- 멘토링 (senior → junior 노하우)
- 회고 (한 빌드 끝나고 "뭘 배웠나")
- 학습 (다음 빌드에 반영)
- 의사결정 기록 (ADR)
- 갈등 해결
- 우선순위 협의

→ 이를 책임지는 *본부 10 (Coordination/Communication)* 신설.

---

## 🆕 본부 10: Coordination / Communication — **0/4 (0%)** ⭐ v11 신규

**책임**: 에이전트들 사이의 *소통 / 협의 / 합의 / 학습* 메커니즘 운영. 환율 사례 같은 cross-agent inconsistency 검출 + 진짜 자기 진화 가능하게.

**현황**: 0/4 구현 (PR #138 부터 점진 구현 비전)

### 4 명 신설 에이전트

| # | 직책 | 역할 | 주요 도구 | 구현 예정 PR |
|---|---|---|---|---|
| 1 | **Meeting Facilitator** ⭐ | 킥오프 회의 / 중간 점검 / 최종 검토 진행. 모든 부서 참여 + 의제 정리 + 합의 도출 | LangGraph state + Shared Context Pool + 의사결정 record | **PR #138 (Phase 1) ⭐⭐⭐** |
| 2 | **Cross-Agent Consultant** | 한 에이전트가 다른 에이전트에게 질문할 때 라우팅 + 답변 정리 (양방향 channel) | CrewAI `allow_delegation=True` + 호출 한도 관리 | PR #141 (Phase 2) |
| 3 | **Knowledge Curator** ⭐ (기존 본부 5에서 *promote*) | 매 빌드 후 인덱싱 → `outputs/_index.yaml` 누적 → RAG 검색 → 다음 빌드 학습 | LangChain RAG + outputs/ 자동 스캔 | PR #140 (Phase 3) |
| 4 | **Retrospective Lead** | 매 빌드 후 회고 자동 작성 → "뭘 배웠나" YAML → Knowledge Curator 가 인덱싱 | LangFuse traces + outputs 비교 + 회고 template | Phase 3 별도 PR |

### Phase 로드맵 (본인 비전 통찰 6 매핑)

| Phase | 작업 | PR 예상 | 효과 |
|---|---|---|---|
| **Phase 1** ⭐ Foundation | Meeting Facilitator + Shared Context Pool | **PR #138** | 협업 인프라 — 모든 에이전트 *서로의 산출물을 봄* |
| **Phase 2** Bidirectional | Cross-Agent Consultant + CrewAI delegation 부분 ON + Vision QA | PR #141 | 양방향 소통 — Engineer ↔ Reviewer 양방향, GUI mockup vs 실제 일치 검증 |
| **Phase 3** Learning | Knowledge Curator + Retrospective Lead + RAG wiring | PR #140 + 회고 PR | 자기 진화 — 매 빌드 회고 → 다음 빌드 반영 |
| **Phase 4** Visualization | 사용자도 회의 참관 — 실시간 대시보드 + Vision QA 확장 | PR #145 | UX — 22~33min 빌드 중 진행 상황 가시화 |

### 신규 의존성 (Coordination/Communication 본부)

기존 의존성 최대 재활용 — 신규 추가 0:
- LangGraph state (이미 사용)
- CrewAI delegation (이미 capability 있음, 단 OFF 상태)
- Shared Context Pool = LangGraph state 의 dict 추가

→ 본부 신설이지만 *runtime 비용 추가는 거의 0*. 핵심은 *기존 capability 활성화*.

### DoD 확장 (Coordination/Communication 이 도입하는 신규 항목)

| # | 항목 | 검증 |
|---|---|---|
| 10 | **`cross_agent_consistency`** ⭐ | 환율 사례 같은 cross-agent inconsistency 0 (Meeting Facilitator 가 킥오프 회의에서 가정 명시 + Vision QA 가 검증) |
| 11 | **`retrospective_persisted`** | 매 빌드 후 회고 YAML 자동 작성 + outputs/_index.yaml 등록 |

→ DoD 9/9 (RV 본부) → DoD 11/11 (Coordination 본부 추가).

---

## 📊 전체 조직 구성 (v11)

### 조직 단위 총 **11 개** (v10 의 10 개 → +1)
- **경영진 (C-Level)** — 1개 (1/3 구현, 33%)
- **실무 본부** — **10 개** (38/51 구현, 75%) ← Coordination/Communication 신설

### 에이전트 구현 현황 (v11, 2026-05-14)

| 구분 | 인수 | 비율 |
|---|---|---|
| 구현 완료 | **39 명** | **72%** |
| 미구현 | **15 명** | 28% (RV 4 + Coordination 4 + 기존 7) |
| **총계** | **54 명** | **100%** |

### 100% 완성 본부 🎉 (v10 동일)
- ✅ **본부 7: 디자인** (3명)
- ✅ **본부 8: 빌드 & 배포** (9명 + 도구 3종)
- ✅ **본부 4: 품질 검증** (9명 + Convergence Judge + 도구 5종)

### 신규 본부 🆕
- 🆕 **본부 9: Runtime Verification (RV)** — 4 명 (v10 부터, 0/4 구현)
- 🆕 **본부 10: Coordination / Communication** — 4 명 (v11 신규, 0/4 구현)

---

## 🏛️ 본부별 상세 (v11, 변경/유지)

### 본부 1~8: 변경 없음 (v10 와 동일)

### 본부 9: Runtime Verification (RV) — 0/4 (v10 신규 비전, 여전히 미구현)
PR #134-A 의 진단 보강 (`Get-TkinterDiagnostics` + 13 섹션 dump) 가 RV Phase A 의 *부분 prototype* 으로 볼 수 있음. 단 install.ps1 의 native command 검증만, .exe runtime 검증은 별도.

### 🆕 본부 10: Coordination / Communication (0/4, v11 신규)
(상기 §본부 10 섹션 참조)

→ **본부 9 (RV) 와 본부 10 (Coordination) 의 관계**:
- RV = `.exe` 의 *runtime* 검증 (시작 시간 / UI test / failure analyze)
- Coordination = *에이전트 간* 협업 검증 (회의 / 회고 / cross-agent 일관성)
- 둘 다 *기존 본부 4 (품질 검증)* 의 한계를 *서로 다른 축* 에서 보완

---

## 🆕 v11 의 핵심 마일스톤

### 1. 외부 PC 첫 라이브 빌드 성공 (PR #134-A → 친구 PC)

```powershell
$env:NEXUS_ALPHA_BRANCH='pr-134-a-tkinter-diagnostic-boost'
irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/pr-134-a-tkinter-diagnostic-boost/install.ps1 | iex

# 결과
✓ install.ps1 정상 완주 (이전 tkinter 결함 재현 X)
✓ "입력한 메세지에 따라 선택한 유형으로 시스템메세지 뜨게 하는 프로그램" → Track A
✓ Message_App.exe 9.86 MB / 33.11 min
✓ GUI 정상 동작 (메시지 본문 + info/warning/error/question 라디오 + MessageBox)
```

### 2. PR #135 — 30초 fix 의 ROI (Build 비용 ~30%↓)

`api_key_provider.py:37` `max_tokens=1024 → 4096`. Pytest Author 의 ≥1200 chars 요구와 구조적 충돌 해결 → `retry_task_if_short` 폭증 fix → 33min → ~25min.

### 3. PR #137 — Security baseline 활성화

PUBLIC repo 보안 자동화 0 → gitleaks (전체 history) + dependabot (pip + actions) + CodeQL (python security-extended) + BFG 절차 문서화.

### 4. ⭐ 종합 점검 (Project Health Check) — 6 본질적 통찰 발견

3 에이전트 병렬 evidence-based 점검 11 영역 (A~K). 통찰 1~5 (결함 발견) + **통찰 6 (본인 비전 = north star)**.

→ **본부 10 (Coordination/Communication) 비전 = 통찰 6 의 직접 처방.**

---

## 🗓️ 다음 단계 — v12 후보

| 시점 | 작업 | 인원 변화 | 비고 |
|---|---|---|---|
| **즉시 (Sprint 2 1순위)** | ⭐ **PR #138 — 본부 10 Phase 1 (Meeting Facilitator + Shared Context Pool)** | **+1 (39 → 40)** | 본부 10 첫 구현 ⭐⭐⭐ |
| 단기 | PR #141 — 본부 10 Phase 2 (Cross-Agent Consultant + CrewAI delegation 부분 ON + Vision QA wiring) | +1 (40 → 41) | 양방향 소통 |
| 중기 | PR #140 — 본부 10 Phase 3 (Knowledge Curator + RAG wiring + Retrospective Lead) | +2 (41 → 43) | 자기 진화 시작 |
| 장기 | PR #145 — Phase 4 (실시간 대시보드 + Vision QA 확장) | 0 (도구) | 사용자도 회의 참관 |
| 장기 | RV 본부 Phase A (Exe Runtime Tester) — v10 비전 잔여 | +1 (43 → 44) | DoD 8 |

---

## 변경 이력

| 버전 | 일자 | 핵심 변경 |
|------|------|---------|
| v6 | 2026-04-21 | 46명 조직 + Phase 6 Track B 5 |
| v7 | 2026-04-29 | 본부 4 (QA) 9/9 도달 |
| v8 | 2026-05-06 | 본부 8 (Build) 9/9 도달 |
| v9 | 2026-05-08 | 본부 4 + Convergence Judge |
| v10 | 2026-05-11 | RV 본부 신설 (50명) |
| **v11** | **2026-05-14** | **Coordination/Communication 본부 신설 (54명) — 본인 비전 통찰 6 반영** |

---

**관련 문서**:
- ⭐ [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — 본인 비전 통찰 6 + Phase 1~4 진화 경로 (북극성)
- [docs/architecture/Nexus_Alpha_구성안_v7.md](Nexus_Alpha_구성안_v7.md) — 구성안 v7 (v5 비전 진짜 multi-agent collab)
- [docs/architecture/Nexus_Alpha_조직도_v10.md](Nexus_Alpha_조직도_v10.md) — 이전 v10 (RV 본부 신설)
- [docs/health_check/project_health_check_20260514.md](../health_check/project_health_check_20260514.md) — 종합 점검 evidence
- [docs/next_session_context.md](../next_session_context.md) — 다음 세션 핸드오프
