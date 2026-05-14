# 🩺 Project Health Check — 2026-05-14

> **Auditor**: Claude Opus 4.7 (3 병렬 에이전트, evidence-based)
> **Trigger**: PM 직관 "내가 찾지 못한 결함도 있을 수 있다" — PR #134-A 머지 직후
> **방법**: 11 영역 (A~K) 을 3 그룹으로 분담, 각 에이전트 독립 read-only 점검
>
> **본 보고서가 답해야 할 질문**:
> - 영역별 평가 + evidence
> - 식별 결함 + 잠재 결함
> - PR 후보 우선순위 매트릭스
> - 본인 발견 결함 6개 → PR 매핑
> - 권장 진행 순서 (단기 / 중기 / 장기)
> - 결정 보류 5가지 (PM 판단 필요)
>
> **⭐ 본질적 통찰은 별도 파일**: [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — 1주일 후 본인 첫 행동은 그 문서부터.

---

## Executive Summary

3 에이전트가 *독립적으로* 같은 결함 패턴을 발견 → **시스템적 결함 확정**:

1. **Build-but-Forget anti-pattern** — `iterative_loop` (704 LOC), `qa_feedback_loop`, `gui_test_executor` (Vision API GUI 검증), Knowledge Curator + RAG Searcher 모두 *구현 완료 + 테스트 통과 + production path 호출 X*. PR #133 의 16 fixup 은 `qa_feedback_loop` 가 안 돌아서 PM 이 손으로 패치한 결과.
2. **"자기 진화형" 비전 vs 실제** — 자기 진화 코드 다 있으나 호출 0. 실제는 *PM 진화형* (PM 이 패턴 학습 → 백스토리에 freeze).
3. **CrewAI 협업 기능 모두 OFF** — `allow_delegation=False` (24/24), `Process.sequential` 만, `memory=False`. "AI 가상 기업" org chart 50명 / 실제 협업 0개.
4. **Telemetry 0** — 친구 PC 실패가 maintainer 에게 invisible. 다음 N명 베타 디버깅 blind 반복 위험.
5. **빠른 ROI** — `max_tokens=1024` 가 `retry_task_if_short` 매 빌드 트리거 → 33min 의 ~25%, 비용 ~30% 낭비. **30초 fix** (PR #135 로 처리됨).

→ **본질적 처방은 [통찰 문서](../insights/agent_collaboration_paradigm_shift.md)** — 본 보고서는 evidence + PR 후보 매트릭스.

---

## 영역별 평가 (3 에이전트 종합)

### 점수 표 (1-10)

| 영역 | 점수 | 한 줄 정당화 |
|------|------|-----------|
| **A. Vision vs 구현 갭** | 6/10 | Track A 비전은 delivered, "자기 진화형 가상 기업"은 scaffolded 하지만 unwired |
| **B. 사용자 여정** | 5/10 | `irm | iex` 작동, 그러나 33min 빌드 중 progress indicator 0 + Quick Edit 사고 |
| **C. 코드 품질** | 6/10 | agent boundary 잘됨, workflow god-modules (1764 LOC) + 16 fixup inline 누적 |
| **D. Multi-agent 워크플로우** | 4/10 | 단방향 파이프라인, CrewAI 협업 기능 모두 disabled |
| **E. 운영/배포** | 4/10 | Pipeline 단위 잘됨, 그러나 git tag 0, release 자동화 0, telemetry 0, rollback X |
| **F. 도메인/비즈니스** | 4/10 | 실제 산출물 (.exe) 있으나 1 외부 사용자 / cost 측정 0 / 페르소나 정의 X |
| **G. 보안** | 5/10 | 방어 의식 있음, 그러나 prompt injection 0 방어, leaked key history 잔존, sandbox = sandbox 아님 |
| **H. 성능** | 5/10 | 33min 의 70% 가 sequential LLM, 병렬화 가능 영역 다수, max_tokens=1024 가 retry 폭증 (수정됨) |
| **I. 자기 진화** | 2/10 | 거의 전부 aspirational. iterative_loop / Knowledge Curator / RAG / qa_feedback_loop 모두 호출 X |
| **J. Cross-platform** | 3/10 | README "Cross-platform" 거짓 — 실제 Windows-only. install.sh 0, WSL 미고려 |
| **K. 문서화** | 5/10 | docs/ 풍부 (60+ 파일), README 2개월 stale, INDEX 0, LICENSE 0 |

### 영역별 핵심 결함 (각 2-3개)

#### A. Vision vs 구현 갭
- `iterative_loop.py` (704 LOC, 자기 진화 엔진) → `scripts/run.py` 호출 X (production path 에서 dead code)
- 조직도 v10 "39/50 명 구현 (78%)" — agent = LLM personality definition 만으로 카운트 (실제 wiring 무관)
- README §3 stuck at "Phase 2 우선순위 2 (다음): QA 에이전트" — PR #1~#134 머지된 상태와 ~2개월 stale

#### B. 사용자 여정
- 33min 빌드 중 `_run_track_a` ([scripts/run.py:160-188](../../scripts/run.py#L160-L188)) 가 synchronous 호출 + 결과만 print → progress indicator 0
- 친구 PC PowerShell Quick Edit Mode 사고 (선택 시 프로세스 정지) = 이 결함의 정확한 재현
- README §A "Python 3.13.x 사전 설치" — 실은 install.ps1 이 자동 설치 (PR #117/#123) — README 가 능력 과소 표현

#### C. 코드 품질
- `build_workflow.py` 1764 LOC — 12개 `# PR #133 fixup #N` inline 누적, 추출 0
- 4개 entry-picker 병존 (`_pick_entry_file` / `_select_entry_point` / `_detect_entry_hint` + sandbox runner) — drift 위험
- `kickoff_with_converter_rescue` ([_common.py:264](../../src/workflows/_common.py#L264)) class-level monkey-patch — concurrent workflow race condition

#### D. Multi-agent 워크플로우 (가장 본질)
- `allow_delegation=False` (24/24 에이전트)
- `Process.sequential` (11/11 Crew, hierarchical 0)
- `memory=False` (cross-run 학습 0)
- `gui_test_executor.py` (Vision API GUI 검증) 호출자: docstring + e2e script 만, **`scripts/run.py` 호출 X** → 친구 PC .exe 는 *어떤 에이전트도 시각적으로 본 적 없는* .exe
- `qa_feedback_loop.py` 호출자 0 (Engineer ↔ QA 양방향 재시도 dead code)

#### E. 운영/배포
- `git tag` empty (134 PR 머지 / 0 tag)
- `gh release` 는 per-NL-request 만, project-version pipeline 0
- install.ps1 의 `git fetch + reset --hard origin/$BRANCH` — friend PC 가 항상 main 동기화 → rollback 불가
- LangFuse 키 없으면 silent no-op → 친구 PC 실패 telemetry 0

#### F. 도메인/비즈니스
- 1 외부 사용자 (친구) → 134 PR / 1 user (worrying ratio)
- cost meter 0 — 베타 cohort 결정 데이터 없음
- 타겟 페르소나 미정의 — "쇼핑몰 사장님 RPA" vs "AI hobbyist" 결정 X

#### G. 보안
- LangFuse public key (`pk-lf-09fedad5-...`) git history 잔존 (PR #103 가 main 만 정리, history 4 commit 미정리) — **PR #137 의 BFG 절차 문서화로 처방, 실 실행은 별도**
- prompt injection 0 방어 — `scripts/run.py:233` user input → `analyze_and_implement.py:312` 직접 concat (delimiter 0, 길이 cap 0). 4가지 attack vector 작성 가능
- sandbox = sandbox 아님 (sandbox_runner.py:25-37 의 honest 경고 — 생성 코드가 user 권한으로 실행, FS/Network/Registry 전부 접근)
- `irm | iex` unsigned + SHA256 미공개 — RCE 채널 (maintainer creds phish → 모든 친구 PC RCE)

#### H. 성능
- LLM 호출 inventory (Track A GUI build): 8 GUI + 5 build = **13 calls**, retry 포함 ceiling ~30
- 33min breakdown: ~6.5 min LLM (sequential) + ~10 min PyInstaller + ~4 min pip + ~2 min 기타 = 22-27 min computed, 6 min 추가 = AV 스캔 (Defender)
- **`max_tokens=1024` (api_key_provider.py:37) → Pytest Author 1200 chars 요구와 구조적 충돌 → retry 폭증** — **PR #135 로 4096 변경, ~25% 시간 + 30% 비용 절감**
- 병렬화 가능: Asset Manager + Dep Analyzer 독립, Pytest Author + Code Reviewer 독립 → LangGraph migration 시 ~2-3 min 절감
- 동시 사용자 limits: `kickoff_with_converter_rescue` class-level patch race + 단일 outputs/ dir collision

#### I. 자기 진화 (가장 낮은 점수)
- `iterative_loop` (704 LOC) — Convergence Judge + Gap Analyst + 자기 진화 모두 구현, 호출 0
- Knowledge Curator → outputs/ 인덱싱 X, RAG Searcher → 과거 워크플로 추천 X
- `qa_feedback_loop` 인트라-run 만 (process 종료 시 garbage collected)
- "방어선 패턴 13차 누적" = PM 이 손으로 새 directive 백스토리에 추가한 것 — *시스템 자기 진화 X, PM 진화*

#### J. Cross-platform
- `install.sh` 존재 안 함 (`git log -- install.sh` empty)
- `install.ps1` WSL 미작동 (`Get-CimInstance Win32_*` Linux PowerShell 충돌)
- `pyproject.toml:9` `requires-python = ">=3.13"` — CrewAI 호환 범위 (3.10-3.13) 보다 좁음
- README "Cross-platform 지원 (Windows / macOS / Linux)" 거짓 — `irm | iex` 시나리오는 Windows 전용

#### K. 문서화
- README 2개월 stale (Phase 2 / 4 agents 라고 적혀 있음, 실제는 PR #134 + 39 agents)
- `docs/progress/` 60+ 파일 / INDEX.md 0 — 새 contributor 발견 불가
- `LICENSE` 파일 없음 (PR #103 PUBLIC 전환 후) — README 는 "All Rights Reserved"
- `CONTRIBUTING.md` 0
- **install.ps1 의 에러 메시지가 best-in-class** ([install.ps1:1128-1147](../../install.ps1#L1128-L1147)) — 19줄 actionable, README 에 promote 가능

---

## 본인 발견 결함 6개 → PR 매핑 (PM 정리)

| # | 결함 | 처리 PR | 상태 |
|---|------|--------|------|
| **1** | tkinter 환경 결함 (친구 PC stderr 폐기) | PR #134-A | ✅ **완료** (`76f96db`) |
| **2** | 환율 stale (1 USD = 1365.5, 실제 ~1490, 9% 오차) | **미식별 → PR #138 (Shared Context Pool) 후보** ⚠️ 점검 보고서의 #138 (input hardening) 와 충돌 — 다음 세션 번호 재배정 | ❌ 미해결 |
| **3** | Observability 부재 (33min 빌드 중 progress 0) | **미식별 → PR #145 (실시간 대시보드) 후보** | ❌ 미해결 |
| **4** | 에이전트 협의 부재 | **PR #141 (Vision QA + CrewAI delegation 부분 ON)** ⭐⭐⭐ | ❌ 미해결 (Sprint 2 1순위) |
| **5** | 시각적 QA 부재 (gui_test_executor 호출 X) | **PR #141 (Vision QA wiring)** ⭐⭐⭐ | ❌ 미해결 (Sprint 2 1순위) |
| **6** | AI 가상 기업 비전 갭 | **PR #140 (Knowledge Curator + RAG) + PR #141 통합** ⭐⭐⭐ | ❌ 미해결 (Sprint 2) |

→ **본인 발견 결함 6개 중 5개 미해결**. 5개 모두 통찰 1~5 와 직접 매핑 — [insights 문서](../insights/agent_collaboration_paradigm_shift.md) 참조.

---

## PR 후보 우선순위 매트릭스 (가치 vs 비용 vs 시급성)

### Sprint 1 — 완료 (이번 세션)

| PR | 제목 | commit | 효과 |
|----|------|--------|------|
| **#135** | max_tokens 1024 → 4096 | `b645bb1` | 33min → ~25min, 비용 ~30%↓ |
| **#137** (GH#136) | Security baseline (gitleaks + dependabot + CodeQL + BFG 문서화) | `6aa07ca` | 보안 자동화 0 → 활성, 첫 스캔 SUCCESS |

### Sprint 1 — 보류 (친구 베타 1주일 후 데이터 합쳐서)

| PR | 제목 | Effort | 가치 | 시급성 |
|----|------|--------|------|------|
| **#136** | README truth pass — "Cross-platform" 거짓 제거 + 30분 quickstart + 비용 추정 + 알려진 한계 | M | high | 친구 데이터 후 |
| **#138-input** | Input hardening (prompt injection — `user_request` 길이 cap + delimiter) | S | high | 친구 데이터 후 |
| **#139** | Token + cost meter (`outputs/<run>/_cost.json`) | M | high | 베타 cohort 결정 시 |

### Sprint 2 — Paradigm Shift (다음 2주, 친구 데이터 + 통찰 매핑)

| PR | 제목 | Effort | 가치 | 시급성 | 처리 통찰 |
|----|------|--------|------|------|---------|
| **#141** ⭐⭐⭐ | **Vision QA + CrewAI delegation 부분 ON** | L | **VERY HIGH** | **Sprint 2 1순위** | 1, 2, 4 (D-2/D-3) |
| **#140** ⭐⭐⭐ | **Knowledge Curator + RAG Searcher wiring** | M+M | **VERY HIGH** | Sprint 2 | 4 (D-1) — 첫 cross-run 학습 |
| **#138-pool** ⚠️ | **Shared Context Pool** (본인 통찰 매핑 — 점검 #138 과 번호 충돌, 재배정 필요) | M | high | Sprint 2 | 1, 2 |
| **#142** | CI Windows runner + install.ps1 lint | M | high | Sprint 2 | E (운영) |
| **#143** | v0.x.x 태그 + release.yml + `NEXUS_ALPHA_REF` | S+M | high | Sprint 2 | E (운영) — rollback 가능 |
| **#144** | Telemetry fallback (LangFuse silent → local jsonl) | M | high | Sprint 2 | 다음 베타 blind 방지 |

### Sprint 3+ — Backlog (1-2개월)

| PR | 제목 | 처리 통찰 |
|----|------|---------|
| **#145** | 실시간 대시보드 (tqdm + Quick Edit 끄기 안내 + 에이전트 활동 로그) | 5 (Observability) |
| 신규 sequence | 회의/멘토링/회고/학습 메커니즘 (multi-PR) | 3 ("AI 가상 기업" 비전) |
| 좀비 cleanup (기존 #135 후보) | Flet Flutter daemon 등 Windows subprocess 정리 | C latent |
| iterative_loop production wire (`--auto-revise N` 플래그) | 자기 진화 엔진 실제 ON | I |
| build_workflow LangGraph migration (Dep + Asset 병렬) | 33min → ~28min | H |
| install.ps1 SHA256 + Authenticode signing | RCE 채널 1차 방어 | G |
| outputs/ rotation + pip wheel cache | 디스크 + 첫 빌드 시간 | E |
| kickoff_with_converter_rescue instance-level patch | 동시 사용자 race 차단 | C/H |
| 4 entry-picker 통합 → strategy pattern | 유지보수 | C |
| docs/INDEX.md + LICENSE + CONTRIBUTING.md | PUBLIC repo 위생 | K |

### 의도적 보류 (5명 베타 cohort 데이터 이전)

- Tauri / Streamlit / Electron / RV 본부 (구성안 v6 의 UX 본부 v6) — 1대 외부 PC 데이터로 결정 X
- install.sh (macOS / Linux) — Windows 베타 cohort 우선
- 진짜 sandbox (WSL/Docker/firejail) — 베타 1대 → ~5대 검증 후
- PR #134-B 환경 분기 처방 — TKINTER-001~005 실제 분류 케이스 1+ 누적 후

---

## 권장 진행 순서

### 단기 (1주일, Sprint 1 잔여 + 친구 베타 대기)

```
[사용자]   친구 베타 메시지 발송 (docs/templates/friend_beta_request.md)
[사용자]   1주일 동안 친구 결과 수집 (4 GUI 라이브러리 시도)
[Claude]   다른 작업 없음 — 데이터 대기
[사용자]   (선택) LangFuse public key rotate
```

### 중기 (1개월, Sprint 2)

```
[Claude]   친구 데이터 받으면:
           - 결함 발견 시 그 결함 PR 우선
           - 모두 성공 시 PR #141 (Vision QA + delegation) 즉시 시작
[Claude]   PR #141 → PR #140 → PR #136 (README) → PR #138-input → PR #139 → PR #142~#144
```

### 장기 (3개월+, Sprint 3+)

```
[Claude]   PR #145 (Observability) — Sprint 3 1순위
[Claude]   회의/회고/학습 메커니즘 multi-PR sequence — "AI 가상 기업" 비전 충족
[사용자]   5명 베타 cohort 결정 → Tauri/RV/install.sh 등 scope 확장
```

---

## 결정 보류 5가지 (PM 판단 필요)

| # | 결정 | 옵션 | 권장 시점 |
|---|------|------|---------|
| **1** | "자기 진화형" 마케팅 | (a) `iterative_loop` 즉시 wire (PR sequence) → 비전 충족 / (b) "패턴 누적형" honest rename → 마케팅 일치 | Sprint 2 시작 전 |
| **2** | BFG 실 실행 시점 | (a) Sprint 1 끝 / (b) 친구 베타 1주일 후 / (c) PR #134-B 와 묶음 / (d) 무기한 보류 (LOW risk) | 본인 페이스 |
| **3** | `outputs/` rotation 정책 | (a) `NEXUS_ALPHA_KEEP_RUNS=10` env / (b) `--clean` 명령 / (c) 자동 cleanup (시간 N일 이상 삭제) | Sprint 2 — outputs/ 가 1GB 넘기 전 |
| **4** | CrewAI `allow_delegation=True` 부분 ON | (a) Code Reviewer ↔ Engineer 만 ON 시도 / (b) 전체 ON (비용 폭증 위험) / (c) 비활성 유지 | PR #141 시 결정 |
| **5** | 베타 cohort 5명 ($50 API budget × 5 = $250) | (a) PM 자비 / (b) 후원 / (c) 무료 (소규모 친구만) | 친구 베타 결과 + PR #144 telemetry 후 |

---

## 본 보고서의 한계 (정직하게)

- **3 에이전트 점검은 read-only** — 실제 LLM 호출 없이 코드 + 문서 분석. 따라서 "런타임 동작" 결함 (예: 친구 PC 의 Quick Edit Mode 사고) 은 직접 관찰 불가. PM 의 라이브 검증 + 친구 베타가 보완.
- **점수는 상대적** — Nexus Alpha 라는 *프로젝트 self-context* 안에서의 점수. 산업 표준 (예: SOC2) 와 1:1 매핑 X.
- **PR 후보 effort 추정은 ±50%** — 실 작업 시 fixup 시퀀스 가능성 (PR #133 의 16 fixup 패턴).
- **5명 베타 cohort 비용 추정 ($250)** — Sonnet 4.6 기준, Opus 사용 시 ~$1750. 모델 선택 + retry 빈도가 큰 변수.

---

**관련 문서**:
- ⭐ [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — 본질적 통찰 5가지 (1주일 후 첫 행동 첫 읽기)
- [docs/context/next_session_context.md](../context/next_session_context.md) — 다음 세션 핸드오프
- [docs/progress/session_log_20260514.md](../progress/session_log_20260514.md) — 이번 세션 활동 로그
- [docs/templates/friend_beta_request.md](../templates/friend_beta_request.md) — 친구 베타 메시지 템플릿
- [docs/security/bfg_rotation_procedure.md](../security/bfg_rotation_procedure.md) — BFG 실행 시점 결정 시 참조
- [docs/WORK_STATUS.md](../WORK_STATUS.md) — 프로젝트 전체 현황
