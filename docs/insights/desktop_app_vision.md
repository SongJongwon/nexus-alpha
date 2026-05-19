# 🎨 Desktop App Vision — Agent Office Visualizer (Tauri)

> **2026-05-19 본 세션 마감 시점 PM 의 새 비전** — paradigm-shift 의 *마지막 차원* (사용자 가시화) 완성.
>
> 기존 비전 (통찰 6 — 진짜 자기 진화형 소프트웨어, [agent_collaboration_paradigm_shift.md](agent_collaboration_paradigm_shift.md)) 가 *백엔드/오케스트레이션* 차원이었다면, 본 비전은 그 위에 **사용자 가시화** 를 얹는다. **PowerShell 탈피** → *AI 가상 기업 의 일하는 모습을 직접 본다*.

## 1. 비전 핵심 — PowerShell 탈피, 사용자 가시화 끝판왕

### 현재 사용자 경험 (PowerShell, 2026-05-19 시점)
```powershell
.venv\Scripts\python.exe scripts\run.py --request "네이버 쇼핑 크롤러" --track B --build --max-iterations 1 --non-interactive
```
→ 8.11min 동안 *콘솔 텍스트 stream* 으로만 진행 상황 확인. 어느 agent 가 뭘 하는지 *추론* 필요.

### 본 비전 — 데스크탑 앱 (Tauri 기반)
- **PowerShell 대체** — GUI 자연어 입력창
- **에이전트 오피스 그리드** — 부서별 색상 + 픽셀 아이콘 + working 펄스 애니메이션
- **실시간 대화 panel** — agent 간 메시지 stream (관찰 가능한 협업)
- **iteration progress + 결과 패널** — 사용자가 *몇 단계* 인지 시각화

→ **사용자가 "AI 가상 기업"이 일하는 모습을 직접 본다**. 통찰 6 의 *사실화* 의 마지막 1m.

## 2. UI 요구사항 (참고 컨셉: "Agent Office Visualizer")

### 레이아웃

```
┌─────────────────────────────────────────────────────────────┐
│ [자연어 입력창]  ←── PowerShell 대체                          │
├─────────┬───────────────────────────────────────────────────┤
│ 메뉴    │ [부서별 색상 카드 그리드]                            │
│         │                                                    │
│ • 시스템 │  ┌─기획──────┐  ┌─개발──────┐  ┌─학습──────┐    │
│   개요  │  │ 🎨 CTO    │  │ 🔧Engineer│  │ 📚Curator │    │
│ • 에이전트│  │ 🎨Analyst │  │ 🔧Reviewer│  │ 📚Retro Lead│  │
│   오피스 │  │ 🎨MeetFac │  │ 🔧GUI Dev │  │ 📚Vision QA│  │
│ • 실시간 │  └───────────┘  │ 🔧Pytest  │  └───────────┘    │
│   모니터 │                  └───────────┘                    │
│ • 대화   │                                                    │
│   로그   │  ✨ working agent: 테두리 강조 + 펄스 애니메이션    │
│ • 산출물 │                                                    │
│ • 사용   │  💬 agent 위 말풍선 클릭 → 해당 agent 대화 로그    │
│   통계   │                                                    │
├─────────┴───────────────────────────────────────────────────┤
│ [실시간 대화 panel — agent 간 메시지 stream]                 │
│ iteration 1/3 ────────────────────────────────────  ●○○      │
│ [Iterate verdict] [Vision] [QA loop] [📦 .exe]               │
└─────────────────────────────────────────────────────────────┘
```

### 부서별 색상 매핑

| 부서 | 색상 | 멤버 |
|------|------|------|
| **기획 부서** | 🔵 파랑 | CTO / Analyst / Meeting Facilitator |
| **개발 부서** | 🟣 보라 | Engineer / Reviewer / GUI Dev / Pytest |
| **학습 부서** | 🟢 청록 | Curator / Retrospective Lead / Vision QA |

(향후 *영업/품질/배포 부서* 추가 가능 — 본부 10 전체 멤버 확장 시)

### 핵심 UI 요소

- **귀여운 픽셀 아이콘** — 사진 스타일 (예: 부서 캐릭터 일러스트)
- **working agent**: 테두리 강조 + **펄스 애니메이션** (CSS animation, ~1Hz)
- **말풍선 클릭** → 해당 agent 대화 로그 panel 펼침
- **iteration progress** — 1/3 → 2/3 → 3/3 (자기 진화 cycle 시각화)
- **결과 패널** — 본 세션 PR #174/#162 로 정착된 라인 형식 (`verdict=BLOCKED(ITERATION_CAP) ... partial output 산출 완료, --max-iterations 늘려 추가 개선 가능` / `.exe SKIPPED — exit=-5 reason=...`)

## 3. 추천 아키텍처 — Tauri 기반

| 계층 | 기술 | 이유 |
|------|------|------|
| **shell** | **Tauri** (~10MB .exe, Rust) | Electron (~100MB+) 대비 1/10 크기, 메모리 효율, 빠른 시작 |
| **UI** | **React + Tailwind** | 기존 web 자산 재사용 + 다크모드 색상 시스템 활용 |
| **백엔드** | **Python sidecar** (기존 `scripts/run.py` 그대로 wrap) | **백엔드 코드 수정 0** — 기존 자기 진화 cycle / fail-silent 처방 / Track A/B 모두 그대로 |
| **통신** | **WebSocket** 또는 **JSON Lines tail** | Python sidecar 가 event stream emit → Tauri shell 이 수신 → React state update |

### Why Tauri (Electron 비교)

| 항목 | Tauri | Electron |
|------|-------|----------|
| 배포 크기 | ~10 MB | ~100-150 MB |
| 메모리 | ~50 MB | ~300 MB |
| 시작 시간 | <1s | 2-3s |
| 한국 사용자 환경 | 다운로드 빠름 | 다운로드 느림 (지방 인터넷) |
| 보안 (sandbox) | 강함 (Rust shell) | 약함 (Node.js 노출) |

→ 베타 cohort 5명 배포 시 **다운로드 + 시작 경험** 결정적 차이.

### Python sidecar 전략

```
Tauri shell (Rust)
   ↓ spawn
Python sidecar (.venv\Scripts\python.exe scripts\run.py --request ... --emit-events)
   ↓ stdout / WebSocket
JSON Lines event stream (AgentStatusEvent / AgentMessageEvent / IterationProgressEvent / ResultEvent)
   ↓ tail
React state update (working agent 표시 / 대화 panel append / iteration progress)
```

**기존 `scripts/run.py` 의 *백엔드 코드 변경 0***:
- 신규 추가: `--emit-events` flag (JSON Lines stdout) + telemetry hook (Sprint 4)
- 기존 자기 진화 cycle / fail-silent 처방 (PR #176/#179/#181) / Track B 안전망 (PR #172/#184) 그대로 동작

## 4. 3 Sprint 분해

### Sprint 4 (~1주) — Telemetry Hook + LangFuse 정리

**목표**: agent event emit 기능을 *백엔드에 추가* (UI 없이도 동작). 데스크탑 앱 prerequisite + LangFuse fallback 동시 정리.

| Task | 산출 |
|------|------|
| `AgentStatusEvent` (working/idle/done) emit 추가 | 각 agent 진입/종료 시 JSON Lines emit |
| `AgentMessageEvent` (대화 로그) emit 추가 | agent 산출 task output → message stream |
| `IterationProgressEvent` (1/3 → 2/3) emit 추가 | iterative_loop 진입/종료 시 emit |
| `ResultEvent` (verdict + .exe) emit 추가 | format_iterative_summary 결과 + executor_result emit |
| **LangFuse fallback 동시 정리** | `LANGFUSE_BASE_URL` vs `LANGFUSE_HOST` 이름 불일치 fix + local jsonl fallback (LangFuse 미설정 시) |
| `--emit-events <path>` flag (scripts/run.py) | 옵션 (default OFF — 기존 사용자 영향 0) |

**Why Sprint 4 우선**:
1. 데스크탑 앱 prerequisite — event stream 없이 UI 못 만듦
2. 베타 cohort 5명 결정 *전*에 텔레메트리 확보 → 빈 응답률 / silent failure 모니터링 가능
3. LangFuse fix 통합 — 환경 설정 정리 (LANGFUSE_BASE_URL vs LANGFUSE_HOST 불일치 + local jsonl fallback)
4. 기존 백엔드 코드 *수정 최소* — emit 만 추가, 동작 변경 0

### Sprint 5 (~1주) — Tauri Shell + React UI 골격

**목표**: 데스크탑 앱 *동작하는 골격* — UI 디자인은 폴리싱 단계에서.

| Task | 산출 |
|------|------|
| Tauri 프로젝트 생성 | `src-tauri/` Rust shell + Cargo build |
| React + Tailwind 부서 그리드 (단순 카드) | 좌측 메뉴 + 자연어 입력창 + 부서 그리드 (placeholder 아이콘) |
| Python sidecar spawn + JSON Lines tail | Tauri commands: `start_run(request, track, ...)` → sidecar spawn → stdout tail |
| event 수신 → React state update | `useEffect` + WebSocket 또는 SSE |
| 자연어 입력 → sidecar 호출 | `--request` + `--track` + `--build` 등 args 매핑 |

**Sprint 5 종료 시점**: PowerShell 대체 가능한 *기본 GUI* — 동작은 하지만 UI 가 *예쁘지 않음* 단계.

### Sprint 6 (~1주) — 실시간 시각화 + 폴리싱

**목표**: 비전 UI 완성 — 사진 컨셉 픽셀 아이콘 + 펄스 애니메이션 + 대화 panel.

| Task | 산출 |
|------|------|
| 픽셀 아이콘 디자인 (사진 스타일) | 9~12 agent 별 캐릭터 일러스트 (외주 또는 AI 이미지 생성) |
| working 펄스 애니메이션 | CSS animation (~1Hz, agent.status==working 시) |
| 대화 panel + 말풍선 클릭 → 로그 펼침 | React component + modal/sidebar |
| iteration progress 시각화 (1/3 → 2/3 → 3/3) | 진행 바 + iteration 별 상세 (recall/kickoff/...) |
| 결과 패널 (Iterate / Vision / QA loop / .exe) | format_iterative_summary 결과 시각화 + .exe 다운로드 버튼 |
| 다크 모드 (기존 색상 시스템 활용) | Tailwind `dark:` variant |

**Sprint 6 종료 시점**: **베타 cohort 5명 배포 가능 상태** — Tauri .exe (10 MB) 단일 배포 → 사용자가 *AI 가상 기업의 일하는 모습을 직접 본다*.

## 5. 비전과 기존 paradigm-shift 통찰의 매핑

| 통찰 (paradigm_shift) | 데스크탑 앱 시각화 |
|---------------------|-------------------|
| 1. 위장된 협업 → 진짜 협업 | 대화 panel 에 *실제 agent 간 메시지* surface |
| 2. 에이전트 간 소통 부재 | Meeting Facilitator 의 kickoff 합의 시각화 (말풍선) |
| 3. AI 가상 기업 비전 갭 | 부서별 색상 카드 그리드 = 회사 조직도 시각화 |
| 4. 분업 + 작업 공유 + 피드백 | working agent 펄스 + iteration progress |
| 5. Observability 부재 | **본 비전의 핵심** — 33min 빌드 중 progress 0 → 매 step 가시화 |
| 6. 진짜 자기 진화형 소프트웨어 | iteration progress (1/3 → 2/3 → 3/3) = 자기 진화 cycle 시각화 |

→ **본 비전 = 통찰 5 (Observability 부재) 의 완전한 처방**. 다른 통찰 (1, 2, 3, 4, 6) 도 *시각화로 사실화*.

## 6. 다음 세션 시작 시 첫 행동

1. **본 비전 문서 읽기** (3분) — UI 요구사항 + Tauri 추천 + 3 Sprint 분해
2. [WORK_STATUS.md](../WORK_STATUS.md) 의 **#1 Telemetry Hook (Sprint 4) 진입** — 데스크탑 앱 prerequisite + LangFuse fix 통합
3. Sprint 4 종료 시점에 베타 cohort 5명 ($250 budget) 결정 — *데스크탑 앱이 곧 도착한다* 는 가정으로

## 7. 위험 / 의문

| # | 항목 | 검토 시점 |
|---|------|----------|
| 1 | Tauri 한국 환경 (Windows 11 한국어 locale) 동작 | Sprint 5 진입 시 hello-world Tauri 빌드 확인 |
| 2 | Python sidecar 의 venv 동봉 vs 시스템 Python 의존 | Sprint 5 — 배포 전략 결정 |
| 3 | WebSocket vs SSE vs JSON Lines tail — 어느게 가장 robust | Sprint 4 — emit 형식 결정 시 함께 |
| 4 | 픽셀 아이콘 디자인 (외주 비용 vs AI 생성) | Sprint 6 진입 시점 (Sprint 4/5 무관) |
| 5 | LLM cost 모델 (베타 cohort) — 데스크탑 앱이 Claude Code MAX 구독 가정 vs ANTHROPIC_API_KEY 가정 | Sprint 4 종료 시점 (cohort 결정 직전) |

## 8. 관련 문서

- [agent_collaboration_paradigm_shift.md](agent_collaboration_paradigm_shift.md) — 통찰 6 north star (본 비전의 백엔드 차원)
- [WORK_STATUS.md](../WORK_STATUS.md) — Sprint 4/5/6 우선순위
- [session_log_20260519.md](../progress/session_log_20260519.md) — 본 세션 11 PR 머지 + fail-silent 5단계 cycle 완성 evidence

---

**보존 시점**: 2026-05-19 세션 마감
**다음 결정 시점**: Sprint 4 시작 (Telemetry Hook 진입) — 본 비전이 *현실로 진입* 하는 첫 단계
