# 📝 세션 로그 — 2026-05-15 (Phase 4 D-3 cycle 완성 + Phase 3 학습 cycle 갭 해결 + RAG 인프라 정착 + Track B 확장)

> 본 세션은 PR #150~#155 6 PR 머지로 본인 비전 통찰 6 의 **Phase 4 (D-3 시각 검증)
> cycle 완성** + **Phase 3 (학습 cycle) 갭 해결** + **RAG 인덱스 인프라 정착
> (누적 회귀 차단 + LRU 회전)** + **Track B Vision QA 확장** 까지 달성. 모든 PR
> CI 4종 (pytest/CodeQL/analyze/gitleaks) pass + squash merge.

## TL;DR

| PR | 머지 commit | 효과 | pytest |
|----|-----------|------|--------|
| #150 | `6d108d5` | PhaseTracker (대시보드) + Vision QA → qa_feedback_loop verdict 가시화 (`🔁 QA loop`) | 1160 (+31) |
| #151 | `6bfea8e` | should_retry → Engineer+Build 만 (~5min) 재호출 wiring + `--vision-qa-max-retries N` CLI | 1174 (+14) |
| #152 | `9ae4394` | RAG recall → SharedKickoffDecisions.recalled_knowledge_markdown → 모든 agent task prompt 자동 주입 | 1185 (+11) |
| #153 | `9870c96` | RAG knowledge_index 다중 누적 회귀 차단 (11 테스트) + `outputs/_index.yaml` 오기억 정정 | 1196 (+11) |
| #154 | `5066626` | LRU 회전 정책 (N=50 기본, `NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES` env var) | 1211 (+15) |
| #155 | `11fb07d` | Track B Vision QA wiring (`detect_artifact_category` 자동 감지 → "gui" 만 트리거) | 1226 (+15) |

**pytest 누적**: 1129 → **1226** (+97, 회귀 0)
**누적 머지 PR**: 132 → **155** (+6 단일 세션)
**Phase 4 시각 검증 cycle**: PR #147 wiring → PR #150 verdict 가시화 → **PR #151 재호출 (D-3 닫힘)** + PR #155 Track B 확장
**Phase 3 학습 cycle**: PR #148 wiring → **PR #152 prompt 주입 갭 해결** + PR #153/154 인프라 정착

## 세션 흐름

### Phase 1 — Vision QA × qa_feedback_loop 통합 (PR #150)

이전 세션 (PR #138~#149) 에서 본부 10 4 멤버 완비 (Meeting Facilitator / Engineer↔Reviewer delegation / Knowledge Curator wiring / Retrospective Lead). 본 세션은 그 위에 **Phase 4 (실시간 대시보드 + Vision QA 확장)** 진행.

브랜치 `pr-150-phase4-dashboard-vision-qa-loop` 이미 partial work 존재 — `_run_vision_qa_full` / `_evaluate_vision_qa_via_feedback_loop` 호출은 있지만 정의 없음 + `_print_result_summary` 시그니처 불일치 (7 args vs 6 args). 모든 갭 메우고 회귀 테스트 16 추가 → fixup commit `2374494` push → merge.

| 핵심 도입 | 위치 |
|----------|------|
| `PhaseTracker` (의존성 0, set_total mid-flow 보정) | [scripts/run.py:148-205](../../scripts/run.py#L148-L205) |
| `_run_vision_qa_full` (GUITestResult 객체 반환) | [scripts/run.py:230-264](../../scripts/run.py#L230-L264) |
| `_evaluate_vision_qa_via_feedback_loop` (verdict 1줄, `max_retries=0`) | [scripts/run.py:284-305](../../scripts/run.py#L284-L305) |
| 결과 패널 `🔁 QA loop:` 라인 | [scripts/run.py:198-224](../../scripts/run.py#L198-L224) |
| 회귀 테스트 16 | [src/tests/test_pr150_phase4_dashboard_vision_loop.py](../../src/tests/test_pr150_phase4_dashboard_vision_loop.py) |

**효과**: 친구 PC 33min dead-screen 사고 처방 (Quick Edit Mode 부작용으로 selection 시 정지 + 사용자가 "멈춘 줄 알고" Ctrl+C) — 단계별 진행 + 누적 시간 가시화.

### Phase 2 — should_retry → Engineer+Build 재호출 wiring (PR #151)

PR #150 verdict 는 *결함을 보고도 고치지 않는 절반 wiring* 한계 — verdict 표시만, 자동 retry X. 사용자 confirm 후 진행. 풀체인 (~25min × N) 대신 Engineer+Build 만 (~5min) 재호출 wiring + CLI 플래그 `--vision-qa-max-retries N` (기본 1).

`_retry_engineer_with_vision_feedback` 5단계 (feedback 메시지 → 이전 코드 조립 → 단일 task Crew kickoff → `_extract_code_blocks` → `run_build_workflow`), 각 격리. `_evaluate_vision_qa_via_feedback_loop` 반환을 `(verdict, decision)` tuple 로 확장해 호출 측이 `should_retry` 분기 가능. 재 Vision QA 1회 + verdict 재평가 → `overall_passed` → break / budget exhausted → break.

회귀 테스트 14 (CLI 플래그 4 + tuple 반환 3 + retry helper 5 단계 격리 + Track A wiring 2). 머지 commit `6bfea8e`. **Phase 4 D-3 시각 검증 cycle 완성**.

### Phase 3 — RAG recall → next-build prompt 주입 (PR #152)

이전 세션 PR #148 후속 검증 작업. 사용자 질문: "RAG 인덱스 활용한 next-build prompt 주입 검증". 코드 grep 으로 **명확한 갭 발견**:
- `_node_recall_past_knowledge` 가 `state["recalled_entries"]` 에 저장만 함
- `format_recalled_entries_for_context` 호출 위치: **production 0건, 테스트 2건**
- `_node_recall_past_knowledge` docstring 에 `"... 컨텍스트로 주입 *가능*"` — "가능" 만 적혀 있고 실 wiring 미완

처방 (사용자 confirm Recommended: Meeting Facilitator + 모든 agent task):
- `SharedKickoffDecisions` 에 `recalled_knowledge_markdown: str = ""` 필드 신설
- `_node_kickoff_meeting` 이 `format_recalled_entries_for_context` 호출해 markdown 주입
- `to_kickoff_context_directive` 가 directive 끝에 append
- **결과**: 기존 shared_kickoff_decisions 의 모든 task description 주입 회로 (PR #138) 자동 재사용 → 모든 agent (CTO/Analyst/Engineer/Reviewer/GUI/Pytest) 가 과거 빌드 학습 인지

회귀 테스트 11 (schema + yaml round-trip + legacy 호환 + directive append 순서 + node 흐름 + E2E). 머지 commit `9ae4394`. **Phase 3 학습 cycle 종단 닫힘**.

### Phase 4 — RAG 인덱스 누적 검증 + 회귀 차단 (PR #153)

사용자 질문: "`outputs/_index.yaml` RAG 인덱스 누적 검증". 검증 결과 **`outputs/_index.yaml` (단일 파일) 미존재** — 실제는 `outputs/knowledge_index/<workflow_id>.yaml` *디렉터리 + 파일별 분리* 패턴 (동시 쓰기 충돌 + git diff 폭증 회피 의도). 사용자 메모리는 *오기억* 으로 식별, 정정.

라이브 검증 (3 builds 시뮬레이션) → 누적 + recall 정상 작동 확인. 다만 기존 회귀 테스트가 모두 1-entry 시나리오만 cover — 다중 누적 회귀 차단 부재. 11 회귀 테스트 추가:
- 다중 빌드 누적 / 동일 wid idempotent overwrite / recall 점수 내림차순 / score=0 제외 / 깨진 yaml graceful skip / NEEDS_REVISION + partial-output 페널티

머지 commit `9870c96`.

### Phase 5 — RAG 인덱스 LRU 회전 정책 (PR #154)

PR #153 사후 — 무제한 누적 시 recall glob+parse 비용 + disk 사용량 폭증 위험. 사용자 confirm Recommended (LRU by curated_at, N=50 기본, env var override).

`prune_knowledge_index_lru` 신설 — `curated_at` 내림차순 정렬 후 상위 N 유지, 나머지 hard delete. `NEXUS_KNOWLEDGE_INDEX_MAX_ENTRIES` env var override + `<= 0` 비활성. `curate_workflow` 종료부 자동 호출 (실패 격리). Tie break: workflow_id 알파벳 내림차순 + 깨진 yaml fallback 우선 삭제.

회귀 테스트 15 (기본 N=50 + over/under limit + override 우선순위 + invalid env fallback + 회전 비활성 + 부재/빈 디렉터리 graceful + tie break + 깨진 yaml + curate_workflow 통합 + 예외 격리).

**브랜치 stale 발견**: PR #153 브랜치가 PR #152 머지 전 origin/main 에서 분기 → PR #152 의 11 테스트가 누락된 채로 PR #153 베이스가 됨. PR #154 시작 시 stash → fresh `origin/main` 에서 새 브랜치 → stash pop 으로 정정. 결과: 1196 + 15 = 1211 정확 누적.

머지 commit `5066626`.

### Phase 6 — Track B Vision QA wiring (PR #155)

PR #150/151 Vision QA wiring 은 Track A 전용. Track B (5 도메인 자동화) 산출이 *GUI* 인 케이스 (tkinter wrapper + pywinauto 데스크탑 자동화) 미커버. 사용자 confirm — Recommended (Option B: `detect_artifact_category` 자동 감지 + Track A helper 재사용, retry 제외).

`_detect_track_b_gui_artifact` 신설 — `saved_code_files` 첫 entry (`test_*.py` 필터링) + `exe_path` 를 `qa_feedback_loop.detect_artifact_category` (PR #95/#96 검증 휴리스틱) 에 전달 → `"gui"` 만 True. `_run_track_b` 가 build 산출 직후 호출 → True 일 때만 Track A 와 동일한 `_run_vision_qa_full` + `_evaluate_vision_qa_via_feedback_loop` 파이프라인. CLI / library / external_dependent → 자동 skip. Retry **비활성** (`max_retries=0`) — Track B 자체 `enable_qa_loop` 와 2중 retry 회피.

회귀 테스트 15 (휴리스틱 단위 7 + file-text wiring 4 + 실행 동작 4). 머지 commit `11fb07d`.

## 핵심 통찰 (이번 세션)

### 1. "Build-but-Forget" anti-pattern 의 마지막 잔재 정리

이전 세션 [insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) 가 식별한 "Build-but-Forget" — 구현 완료 + 테스트 통과 + production 호출 X — 의 두 잔재가 본 세션에 노출:

| 결함 | 발견 PR | 처방 |
|------|--------|------|
| `gui_test_executor` (Vision QA) production 호출 X | 이전 세션 PR #147 wiring → PR #150 verdict → PR #151 재호출 | **D-3 cycle 완성** |
| `format_recalled_entries_for_context` production 호출 0건 | 본 세션 PR #152 grep 으로 식별 | **학습 cycle 종단 닫힘** |

### 2. Wiring vs Storage 가 다른 갭

PR #148 (Phase 3 Knowledge wiring) 머지 후 메모리 노트에는 *"다음 빌드 진입 시 자동 학습 cycle 시작"* 명시. 하지만 실제로는 *저장 cycle 만* 시작 — recall 산출 객체가 task description 에 흘러 들어가지 않았음. 다음 세션 자동 검증 또는 file-text grep ("호출 위치 N건") 회귀 테스트 가 필요.

### 3. 사용자 메모리 정정 메커니즘

사용자 메모리에 적혀 있던 `outputs/_index.yaml` (단일 파일) 은 *오기억* — 실 구조는 `outputs/knowledge_index/<wid>.yaml` 디렉터리. 회귀 테스트 + 라이브 검증으로 *현장 진실* 확인 → 메모리 정정. 패턴: "사용자 진술 ↔ 코드 grep 비교" 자동 검증 필요.

### 4. Stash + fresh branch 워크플로우 가치

PR #153 브랜치가 stale main 에서 분기되어 PR #152 의 11 테스트가 누락된 채로 PR #154 베이스가 될 뻔. fixture 가 1196 보고했지만 git log 확인 시 PR #152 머지 commit 부재 발견 → stash → 새 fresh branch → stash pop. 매 PR 시작 시 `git fetch origin main` 직후 `git checkout -b ... origin/main` 강제 패턴 필요.

## 다음 세션 첫 행동 (자동 컨텍스트 복원)

1. **메모리 (이미 로드됨)**: `MEMORY.md` + `project_paradigm_shift_pointer.md` — Phase 4 + Phase 3 cycle 완성 상태
2. **본 session_log** — 오늘 세션 evidence
3. **WORK_STATUS** — 프로젝트 전체 현황 (아래 갱신됨)
4. PM 에게 질문:
   - 실 E2E (~30min) 검증 원하시는지? (PR #151 retry + PR #154 LRU + PR #155 Track B Vision)
   - dependabot 보류 major bumps (langchain/langgraph/pandas 1.x + rich) 처리 시점?
   - Track B 자체 qa_loop + Vision QA verdict 종합 표시?

## 남은 작업 후보 (Sprint 다음)

| 후보 | 영역 | 비용 | 가치 |
|------|------|------|------|
| **실 E2E 검증** — 친구 PC 베타 환경에서 6 PR 통합 동작 라이브 확인 | A | M (~30min) | HIGH — paradigm shift evidence |
| **dependabot major bumps 검증** — langchain/langgraph/pandas 1.x + rich CI fail 4건 | E | L (~2-4h) | M — 보안 + 의존성 신선도 |
| **Track B qa_loop + Vision QA 종합 verdict** — 현재 두 결과 독립 표시. 1줄 통합 | A | S (~1h) | M — UX 일관성 |
| **iterative_loop production wire** — 4 entry-picker 통합 + `analyze_and_implement` 의 iter 진입 | A | XL (multi-PR) | VERY HIGH — *자기 진화* 실 작동 |
| **Telemetry fallback** (LangFuse silent → local jsonl) | E | M (~3h) | M — 친구 PC 실패 가시화 |
| **session_log auto-summarizer** — 메모리 패턴 자동화 (현재 매 세션 수동) | E | M | M — 인지 부담 감소 |

→ **VERY HIGH 후보**: `iterative_loop production wire`. 본 세션의 6 PR 이 *재료* — recall/retry/learn/index/Track B 모두 갖춰진 상태에서 *진입점* 만 wire 하면 *자기 진화* 가 실제로 돌아감.

---

**관련 산출물 (본 세션)**:
- [docs/progress/session_log_20260514.md](session_log_20260514.md) — 직전 세션 (본부 10 완비 + Phase 3 cycle)
- [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) — 본질적 통찰 5
- [docs/health_check/project_health_check_20260514.md](../health_check/project_health_check_20260514.md) — evidence
- 본 PR 6건 — `gh pr view <150~155>` 또는 GitHub `nexus-alpha/pulls?state=merged`

**메모리 갱신 위치**:
- `MEMORY.md` — Paradigm shift pointer 라인 Phase 4 ✅ + RAG 인프라 + Track B 반영
- `project_paradigm_shift_pointer.md` — PR #150~#155 entry 추가
