# Phase 5.E — 자율 진화 루프 라이브 검증 가이드

> **목적**: Phase 1~5.4 의 *백엔드 풀체인* (RV silent fail 감지 → Strategist 안건 발제 → Boardroom 회의 → Cross-Agent Consultant 3 라운드 티키타카 → Goal Alignment + Token Budget 의결 → decision.yaml v2 산출) 을 **1 cycle 실 라이브 실행** 으로 검증.
>
> **실행 위치**: PM 본인 PC (Claude Code 가 아닌 사용자 머신).
> **예상 소요**: 25~40분 (max_iterations 5 × ~5-8분/iter).
> **예상 비용**: ~$5-15 (Opus 4.7 + LangFuse 트레이스).

---

## 0. 사전 체크리스트

| 항목 | 확인 명령 |
|------|----------|
| Python 환경 | `.venv\Scripts\python.exe -V` (3.11+ 권장) |
| Claude Code CLI 인증 | `claude auth status` (loggedIn=true) |
| 의존성 동기화 | `.venv\Scripts\pip.exe install -r requirements.txt` |
| 작업 디렉터리 clean | `git status --short` (변경 없거나 commit 완료) |
| `outputs/` 정리 (선택) | 기존 `outputs/board_decisions/`, `outputs/_boardroom_sessions/` 가 있어도 무해 — 새 timestamp 디렉터리로 분리됨 |

---

## 1. 추천 `--request` 문구 (5회 BLOCKED 누적 유도)

자율 진화 루프 발동 조건 = **5회 silent fail 누적** 또는 **BLOCKED 비율 50% 이상**. 다음 문구는 *결정론 매처* (`_proposal_silent_fail_pattern` / `_proposal_blocked_ratio`) 가 발동될 가능성이 높은 시나리오를 의도적으로 유발:

### 옵션 A (추천) — 모호한 GUI + 빠듯한 acceptance criteria

```
실시간 양자 회로 시뮬레이터 GUI 앱: tkinter + numpy 로 단일 큐비트 회전 게이트 (RX/RY/RZ) + 측정 + Bloch sphere 시각화. 5초 내 시작 + 측정 결과 정확도 99.9% + JSON export. PyInstaller 단일 .exe.
```

**왜 BLOCKED 누적 가능성 높은가**:
- *모호한 acceptance criteria* — "정확도 99.9%" 가 자동 검증 어려움 → QA NEEDS_REVISION 누적
- *복잡한 도메인* — Bloch sphere 시각화 + tkinter 결합 → GUI 결함 가능성 ↑
- *빠듯한 시작 시간* — "5초 내 시작" → numpy import 만으로도 거의 한계 → RV silent fail 가능

### 옵션 B (가벼움) — 단순하지만 잠재 결함 유발

```
파일 동기화 데몬: 두 디렉터리를 양방향 실시간 동기. 충돌 시 timestamp 우선. tkinter 트레이 아이콘 + 로그 윈도우. 메모리 50MB 이내.
```

### 옵션 C (보수적) — 4 iter PASS / 1 iter BLOCKED 시나리오

```
회의록 자동 요약기: docx 파일 입력 → 3문장 요약 + 5개 액션 아이템 추출. CrewAI 멀티 에이전트. CLI 모드.
```

→ Track B 분류 → 도메인 분류 정상 → 의외로 PASS 가능. BLOCKED 비율 < 50% 시 Strategist *unknown fallback* 발제.

---

## 2. 실행 명령어 (복사-붙여넣기)

### 추천 (옵션 A — 풀체인 발동 시도)

PowerShell:
```powershell
.venv\Scripts\python.exe scripts\run.py `
  --request "실시간 양자 회로 시뮬레이터 GUI 앱: tkinter + numpy 로 단일 큐비트 회전 게이트 (RX/RY/RZ) + 측정 + Bloch sphere 시각화. 5초 내 시작 + 측정 결과 정확도 99.9% + JSON export. PyInstaller 단일 .exe." `
  --track A --build `
  --enable-rv --enable-strategist --enable-boardroom --enable-tikitaka `
  --auto-iterate --max-iterations 5 `
  --emit-events outputs\events.jsonl `
  --non-interactive
```

### Bash (WSL/macOS 호환)

```bash
.venv/Scripts/python.exe scripts/run.py \
  --request "실시간 양자 회로 시뮬레이터 GUI 앱: tkinter + numpy 로 단일 큐비트 회전 게이트 (RX/RY/RZ) + 측정 + Bloch sphere 시각화. 5초 내 시작 + 측정 결과 정확도 99.9% + JSON export. PyInstaller 단일 .exe." \
  --track A --build \
  --enable-rv --enable-strategist --enable-boardroom --enable-tikitaka \
  --auto-iterate --max-iterations 5 \
  --emit-events outputs/events.jsonl \
  --non-interactive
```

### 핵심 flag 설명

| Flag | 효과 |
|------|------|
| `--enable-rv` | 본부 9 Runtime Verification — .exe 실행 검증 + silent fail 감지 (Phase 1) |
| `--enable-strategist` | 본부 1 System Refactoring Strategist — silent fail 5회 누적 시 안건 발제 (Phase 2) |
| `--enable-boardroom` | 본부 10 Boardroom Facilitator — 회의실 인프라 (Phase 3) |
| `--enable-tikitaka` ⭐ | 본부 10 Cross-Agent Consultant — 3 라운드 양방향 토론 (Phase 5.4 ★ NEW) |
| `--auto-iterate` | iterative_loop production 모드 (PR #163, default ON) |
| `--max-iterations 5` | 1 cycle = 5 iter — BLOCKED 누적 가능성 + 안건 발제 trigger |
| `--emit-events events.jsonl` | telemetry 파일 출력 (Tauri UI 가 tail) |
| `--non-interactive` | banner 확인 자동 confirm (CI 호환) |

---

## 3. 실행 후 확인 — 산출 파일 + grep 명령어

### 3.1 Strategist 안건 발제 확인

```powershell
Get-ChildItem outputs\_refactoring_proposals\*.md |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 3 |
  ForEach-Object { Write-Host "=== $($_.Name) ==="; Get-Content $_.FullName -TotalCount 20 }
```

**기대 출력**: 안건 markdown 의 제목 + root_cause_analysis + proposed_changes. 결정론 매칭 시 `analysis_method: rule`, LLM fallback 시 `analysis_method: llm`.

### 3.2 회의록 (Phase 3 산출) 확인

```powershell
Get-ChildItem outputs\_boardroom_sessions\*.md |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  Get-Content
```

**기대 출력**: `# Boardroom Session — <안건>` + Attendees + Tikitaka Rounds + Goal Alignment Check + Budget Brake + Final Decision.

### 3.3 ⭐ decision.yaml v2 확인 (Phase 5.4 핵심)

```powershell
Get-ChildItem outputs\board_decisions\*\decision.yaml |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  Get-Content
```

**기대 schema v2 검증 포인트**:
- `schema_version: "v2"` ⭐
- `session.session_id` 12자 hex
- `alignment.status`: `"approved"` 또는 `"rejected"` (forbidden 키워드 매칭 X 이면 approved)
- `budget.status`: `"approved"` (낮은 cost) 또는 `"throttled"`
- `final_decision.outcome`: `"approved"` 또는 `"blocked"`
- ⭐ **`rounds:` 배열** — 1~3 라운드 발언 기록
- ⭐ **`consensus:`** — mediator 타협안 또는 round 1 종합

### 3.4 ⭐ Cross-Agent Consultant 텔레메트리 (라운드 발동 evidence)

```powershell
Get-Content outputs\events.jsonl |
  Select-String "cross_agent_consultant" |
  Select-Object -First 20
```

**기대 출력**: `agent_status` 이벤트 (`working` + `done`) 가 라운드별 emit. detail 에 `round=1` / `round=2` / `round=3` 포함.

### 3.5 alignment / budget 의결 텔레메트리

```powershell
Get-Content outputs\events.jsonl |
  Select-String 'goal_alignment_check|budget_brake' |
  Select-Object -First 10
```

**기대 출력**: dept="c-level" 이벤트 4건 (각 working/done × 2 노드). `status=approved` / `status=rejected` / `status=throttled` 의 의결 결과.

### 3.6 UI 가시화 (옵션)

Tauri 앱 실행:
```powershell
cd src-tauri
cargo tauri dev
```

→ 왼쪽 사이드바 "이사회 의결" 메뉴 클릭 → 우방 패널에서:
- **Tikitaka Rounds 카드** (purple v2 badge) — 라운드별 statements 표시
- **Consensus 카드** — mediator 타협안
- **Goal Alignment / Budget / Final Decision** — Phase 4 의결

→ `rounds=[]` 인 경우 *"이번 회의는 enable_tikitaka=False 로 진행"* 안내 (PR #225 빈 state).

---

## 4. 실패 시나리오 + 디버깅 가이드

| 시나리오 | 증상 | 진단 / 처방 |
|----------|------|------------|
| Strategist 안건 미발제 | `outputs/_refactoring_proposals/` 비어있음 | silent fail 5회 미달 + BLOCKED 50% 미달 — LLM fallback 도 안 발동. → `--max-iterations` ↑ 또는 더 어려운 안건 |
| Boardroom 회의 미진행 | `outputs/_boardroom_sessions/` 비어있음 | `--enable-boardroom` flag 누락 또는 Strategist 가 안건 미발제 |
| `decision.yaml` 미생성 | `outputs/board_decisions/` 비어있음 | Boardroom 회의 자체 미진행 — 3.2 먼저 확인 |
| `rounds: []` (v2 인데 빈 list) | Tikitaka 진행 안 됨 | `--enable-tikitaka` flag 누락 또는 budget throttled 즉시 종료 (consensus 에 throttled 메시지 확인) |
| `final.outcome: "blocked"` | 의결 거부 | `blocked_by` 확인 — alignment forbidden 키워드 매칭 / budget 한도 초과. 의도된 안전 brake. |
| LLM rate limit | telemetry 에 error 이벤트 | NEXUS_BOARDROOM_BUDGET_LIMIT_USD 환경변수로 한도 조정 후 재시도 |

---

## 5. 성공 판정 — Phase 5.E Definition of Done

✅ **자율 진화 루프 1 cycle 완주** 시 다음 7개 모두 true:

1. `outputs/_refactoring_proposals/<ts>_*.md` 1건 이상 존재
2. `outputs/_boardroom_sessions/<ts>_<session_id>.md` 1건 존재
3. `outputs/board_decisions/<ts>_<session_id>/decision.yaml` 1건 존재
4. `decision.yaml` 의 `schema_version == "v2"`
5. `decision.yaml.rounds` 배열 길이 ≥ 1 (티키타카 라운드 1회 이상 실행)
6. `events.jsonl` 에 `cross_agent_consultant` 이벤트 ≥ 2건 (working + done)
7. Tauri UI "이사회 의결" 탭에서 RoundCard 가 시각적으로 렌더링 (dissent 색상 강조 또는 consensus 표시)

→ 7/7 통과 시 **v13 자율 진화 시스템의 최초 라이브 evidence 확보**. 베타 cohort 5명 배포 가능 상태 도달.

---

## 6. 다음 sprint (실 검증 결과 기반)

| 라이브 결과 | 다음 작업 |
|-------------|----------|
| 7/7 PASS | Phase 5.2 (백엔드 3명) + 베타 cohort 5명 ($250) 배포 |
| 부분 PASS (예: rounds 빈 list) | 디버깅 sprint — telemetry 분석 + 분기 진단 보강 |
| LLM cost 폭증 | `NEXUS_BOARDROOM_BUDGET_LIMIT_USD` 보수적 default (15 → 5?) 검토 |
| dissent 미감지 | `_DISSENT_KEYWORDS` 확장 + LLM 응답 패턴 분석 |

---

**관련 PR**: #217 (Phase 1 RV) · #219 (Phase 2 Strategist) · #221 (Phase 3 Boardroom) · #222 (Phase 4 의결권) · #223 (Phase 5.1 UI viewer) · #224 (Phase 5.4 티키타카) · **#225 (Phase 5.E wire + empty state + 본 가이드)**

**최종 검증 시점**: 2026-05-28 (PM 본인 PC 실행 예정).
