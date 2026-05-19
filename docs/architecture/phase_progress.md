# 📈 Nexus Alpha — Phase Progress Timeline

> **신설일**: 2026-05-19 (세션 진짜 마감 docs PR)
> **목적**: Phase 1~8 *완료* + Sprint 4~6 *예정* 의 진화 timeline 을 단일 mermaid 다이어그램으로 시각화. 누가 *어디까지 왔고 어디로 가는지* 한눈에 파악.

---

## 1. Master Timeline (Phase 1 → Sprint 6)

```mermaid
timeline
    title Nexus Alpha 진화 timeline (2026-04 → 2026-06 ETA)

    section Phase 1~3 (백엔드 핵심)
        2026-04-17 : Phase 1 — MVP 자기 진화 cycle
                   : LangGraph + CrewAI 통합
        2026-04-21 : Phase 2 — Track A/B 분리
                   : 5 도메인 분류
        2026-05-08 : Phase 3 — Sandbox + Gap Analyst
                   : Knowledge Curator + RAG

    section Phase 4~6 (production 도달)
        2026-05-11 : Phase 4 — GUI 분기 + Phase 5 Release wiring
                   : Vision QA prototype
        2026-05-14 : Phase 6 — 외부 PC 검증 2대 성공
                   : 본부 10 (Coordination/Communication) 신설 비전
                   : Calculator.exe + Message_App.exe
        2026-05-15 : PR #133 풀체인 완성
                   : 16 fixup 누적 머지
                   : alpha 베타 배포 준비

    section Phase 7~8 (paradigm-shift 완성)
        2026-05-18 : 자기 진화 paradigm production default
                   : PR #163 --auto-iterate=True
                   : dep 4건 통합 (anyio/pandas/langgraph/langchain)
        2026-05-19 : fail-silent 5단계 cycle 완성
                   : silent 빈 응답률 80% → 0% 도달
                   : Track B 도메인 3중 안전망 완비
                   : Phase 7 — Tauri 비전 보존
                   : Phase 8 — Sprint 4 Telemetry foundation
                   : Architecture docs 단일 진입점

    section Sprint 5~6 (데스크탑 앱)
        2026-05-26 ETA : Sprint 5 — Tauri shell + React UI 골격
                       : Rust + Python sidecar + jsonl tail
        2026-06-02 ETA : Sprint 6 — 시각화 완성
                       : 픽셀 아이콘 + 펄스 + 다크 모드
                       : 베타 cohort 5명 배포 가능
```

---

## 2. Phase 별 상세 + 핵심 산출

```mermaid
gantt
    title Phase 1~8 완료 + Sprint 4~6 예정 (실제 일자 기반)
    dateFormat YYYY-MM-DD
    axisFormat %m-%d
    todayMarker stroke-width:3px,stroke:#ef4444

    section Phase 1~3 (백엔드 핵심)
    Phase 1 MVP 자기 진화 cycle      :done,    p1, 2026-04-15, 2026-04-19
    Phase 2 Track A/B + 5 도메인     :done,    p2, 2026-04-21, 2026-04-29
    Phase 3 Sandbox + Curator + RAG  :done,    p3, 2026-04-30, 2026-05-08

    section Phase 4~6 (production)
    Phase 4 GUI + Phase 5 Release    :done,    p4, 2026-05-09, 2026-05-13
    Phase 6 외부 PC 검증 + 본부 10 비전:done,  p6, 2026-05-14, 2026-05-15

    section Phase 7~8 (paradigm-shift)
    PR 133 풀체인 + 16 fixup         :done,    p133, 2026-05-15, 2026-05-15
    PR 163 paradigm production default :done,  p163, 2026-05-18, 2026-05-18
    Phase 7 Tauri 비전 보존          :done,    p7,   2026-05-19, 2026-05-19
    Phase 8 Sprint 4 Telemetry       :done,    p8,   2026-05-19, 2026-05-19
    Architecture docs 단일 진입점    :done,    pdoc, 2026-05-19, 2026-05-19

    section Sprint 5~6 (데스크탑 앱)
    Sprint 5 Tauri shell + React 골격 :active, s5,   2026-05-20, 2026-05-26
    Sprint 6 시각화 완성 (픽셀+펄스)  :         s6,   2026-05-26, 2026-06-02
    베타 cohort 5명 배포              :         beta, 2026-06-02, 2026-06-05
```

---

## 3. 핵심 마일스톤 (절대 not-bypass 차원)

| 마일스톤 | 일자 | 의미 |
|---------|------|------|
| ✅ **외부 PC 빌드 성공 2대** | 2026-05-14 | "친구 PC에서 .exe 동작" — 단순 dev box 아닌 *baseline cohort 가능성* 증명 |
| ✅ **PR #133 풀체인 완성** | 2026-05-15 | 자연어 → .exe → Draft Release 풀체인 1회 통과 |
| ✅ **자기 진화 paradigm production default** | 2026-05-18 (PR #163) | `--auto-iterate=True` 기본 — 통찰 6 의 *production* 도달 |
| ✅ **fail-silent 5단계 cycle 완성** | 2026-05-19 | 식별 → 진단 → 보존 → 처방 → 검증 sprint 방법론 정립 |
| ✅ **silent 빈 응답률 0% 도달** | 2026-05-19 (PR #181 Phase 5) | retrospective_lead LLM 호출 80% → 0% (단일 line fix) |
| ✅ **Track B 도메인 3중 안전망** | 2026-05-19 (PR #184) | 휴리스틱 + graceful + CLI explicit |
| ✅ **Sprint 4 Telemetry foundation** | 2026-05-19 (GH PR #188, 내부 "PR #187") | 데스크탑 앱 prerequisite 완성 |
| 🔜 **Tauri shell 첫 동작** | ETA 2026-05-26 | 옵션: hello-world + Python sidecar + jsonl tail |
| 🔜 **베타 cohort 5명 배포** | ETA 2026-06-02 | 데스크탑 앱 .exe 5명 분배 (PowerShell 아닌) |

---

## 4. paradigm-shift 통찰 ↔ 진화 매핑

본인 비전 통찰 6 (north star) 의 각 통찰이 어느 Phase 에서 *완성* 됐는가:

```mermaid
graph LR
    subgraph insights["paradigm-shift 통찰 6"]
        I1[통찰 1<br/>위장된 협업]
        I2[통찰 2<br/>에이전트 간 소통 부재]
        I3[통찰 3<br/>AI 가상 기업 비전 갭]
        I4[통찰 4<br/>분업+작업공유+피드백]
        I5[통찰 5<br/>Observability 부재]
        I6[통찰 6<br/>진짜 자기 진화 소프트웨어]
    end

    subgraph phases["완성 Phase"]
        P_K[Phase 1 Foundation<br/>Meeting Facilitator]
        P_L[Phase 3 Learning<br/>Curator + Retrospective]
        P_FS[Phase 8 fail-silent 5단계<br/>PR #176/#179/#181]
        P_PD[Phase 7-8 paradigm production<br/>PR #163 default + PR #188 telemetry]
        P_S5[Sprint 5/6<br/>Tauri 시각화]
    end

    I1 --> P_K
    I2 --> P_K
    I3 --> P_K
    I4 --> P_L
    I5 --> P_S5
    I5 -.->|backend 차원| P_FS
    I6 --> P_PD

    style P_K fill:#dbeafe
    style P_L fill:#d1fae5
    style P_FS fill:#fef3c7
    style P_PD fill:#e9d5ff
    style P_S5 fill:#fde2e8
```

- **통찰 5 (Observability 부재)** 가 *backend 차원* 은 fail-silent 5단계 cycle 로 처방 완료 (PR #181 0% 도달). *UI 차원* 은 Sprint 5/6 의 시각화로 완성 예정. 본 통찰이 *유일하게 두 차원* 에 걸침 — 데스크탑 앱이 *마지막 1m*.

---

## 5. pytest + PR 누적 graph

```mermaid
xychart-beta
    title "pytest 누적 (Phase 6 → 8)"
    x-axis ["05-14<br/>P6", "05-15<br/>PR133", "05-18<br/>PR163", "05-19<br/>PR176", "05-19<br/>PR181", "05-19<br/>PR184", "05-19<br/>PR188"]
    y-axis "pytest count" 900 --> 1500
    bar [992, 1268, 1354, 1356, 1370, 1385, 1400]
```

본 timeline 의 *결정적 evidence* — pytest **992 → 1400** (Phase 6 → 8), 8주 동안 +408 추가 + **회귀 0**.

---

## 6. 다음 결정 시점

| 시점 | 결정 | 의존성 | 가치 |
|------|------|--------|------|
| Sprint 5 진입 직전 | Tauri 프로젝트 scaffold 위치 (`src-tauri/` vs `frontend/`) | 본 architecture docs | 디렉터리 구조 *결정론* |
| Sprint 5 진행 중 | Python sidecar 동봉 vs 시스템 Python 의존 | 베타 cohort 환경 조사 | 배포 단순화 vs 크기 trade-off |
| Sprint 5 종료 | 베타 cohort 5명 ($250) 결정 | Tauri shell 동작 evidence | "데스크탑 앱 곧 도착" 가정으로 의미 |
| Sprint 6 진입 | 픽셀 아이콘 디자인 — 외주 vs AI 이미지 생성 | 비용 + 시간 trade-off | UI 완성도 |
| Sprint 6 종료 | 베타 cohort .exe 분배 + 피드백 수집 | Sprint 6 모두 완성 | 외부 검증 + 통찰 6 사실화 |

---

## 7. 관련 문서

- [agent_org_chart.md](agent_org_chart.md) ⭐ NEW — 본부 10 + 3 부서 매핑
- [system_architecture.md](system_architecture.md) ⭐ NEW — 백엔드 + Telemetry + Tauri 흐름
- [../insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — 통찰 6 north star
- [../insights/desktop_app_vision.md](../insights/desktop_app_vision.md) — Sprint 5/6 비전
- [../progress/session_log_20260519.md](../progress/session_log_20260519.md) — 본 세션 12 PR 누적
- [../WORK_STATUS.md](../WORK_STATUS.md) — 다음 세션 첫 입력 가이드

---

## 8. 변경 이력

| 일자 | 변경 |
|------|------|
| 2026-05-19 | 신설 — Phase 1~8 완료 + Sprint 4~6 예정 mermaid timeline + 마일스톤 + pytest graph. |
