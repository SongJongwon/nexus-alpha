# 세션 로그 — 2026-04-27

**기간**: 2026-04-27 (단일 세션, 약 8시간)
**누적 PR**: 10개 (PR #25 ~ #34, 모두 머지)
**테스트**: pytest **138 → 184 passed** (누적 신규 +46, 회귀 0)
**핵심 성과**: **이슈 4 / 5 / 6 모두 close** + GUI 풀체인 7차 연속 안정

---

## 📊 PR 진행 한눈에

| # | 브랜치 | 머지 커밋 | 변경 | 핵심 |
|---|---|---|---|---|
| **#25** | `phase5/fix-issue-4-final-answer-truncation` | (사용자 머지) | 4 backstory + 회귀 테스트 3 | 이슈 4 fix — GUI 4 에이전트 본문 누락 |
| **#26** | `phase5/e2e-rereverification-issue4` | `17ffb5d` | session log + WORK_STATUS + scripts/ + 결과 문서 | E2E 재재검증 + **이슈 5 발견** (비-GUI 16 에이전트 동일 패턴) |
| **#27** | `phase5/fix-issue-5-non-gui-final-answer` | `58d5325` | 16 backstory 패턴 치환 + 회귀 테스트 1 | 이슈 5 fix — 16 에이전트 |
| **#28** | `phase5/e2e-4th-verification-issue5` | `72ac49d` | 결과 문서 + WORK_STATUS | 4차 E2E + **이슈 6 발견** (LLM 비결정적 컴플라이언스) |
| **#29** | `phase5/fix-issue-6-task-output-retry` | `591b052` | `_common.py` + retry 헬퍼 + 12 테스트 | 이슈 6 방어선 1 — auto-retry |
| **#30** | `phase5/e2e-5th-verification-issue6` | `df78a9a` | 결과 문서 + WORK_STATUS | 5차 E2E — 방어선 1 효과 미미 (75% 정체) |
| **#31** | `phase5/fix-issue-6-structured-output` | `ef27251` | `_schemas.py` + Build/Release 시범 + 9 테스트 | 이슈 6 방어선 2 시범 — output_pydantic 2 에이전트 |
| **#32** | `phase5/e2e-6th-verification-structured-output` | `b51e21a` | NexusAlphaLLM 호환 fix + 결과 문서 | 어댑터 fix + 6차 E2E (시범 100%) |
| **#33** | `phase5/fix-issue-6-extend-structured-output` | `dd732a8` | 12 schemas + 12 wiring + sanitize + 21 테스트 | 방어선 2 전체 확장 (14 active-chain 에이전트) |
| **#34** | `phase5/e2e-7th-verification-extended-structured-output` | `1418ecf` | 결과 문서 + WORK_STATUS | 7차 E2E — **94% 캡처율, 이슈 6 close** |

---

## 1️⃣ PR #25 — 이슈 4 fix (GUI 4 에이전트 본문 누락)

### 증상 (PR #24 발견)
4개 GUI 에이전트 (UI/UX, GUI Designer, Theme, Code Gen) 의 `task.output.raw` 가
Final Answer summary 한 줄만 캡처. 본문 마크다운 + 코드 블록 모두 손실 →
`outputs/workflow_<ts>/code/` 디렉터리 비어있음.

### 근본 원인
4 backstory 가 `"마지막 줄은 반드시 Final Answer: <summary>"` 패턴 사용 → LLM
이 본문을 Final Answer **앞** 에 배치 → CrewAI 는 **이후 텍스트만** 캡처.

### 교정
- 4 backstory 의 출력 규약을 `Final Answer: 라인 + 그 다음 줄부터 본문` 패턴으로
- `_task_output_text` 에 길이 기반 경고 추가 (defense-in-depth)
- 회귀 방지 테스트 3건 (정적 grep + raw 처리 + None 안전성)

### 결과: pytest 141 passed (138 + 3)

---

## 2️⃣ PR #26 — E2E 재재검증 + 이슈 5 발견

### 검증 결과 (실 LLM, 17분 55초)
- ✅ 이슈 1, 2, 3 유지/해결
- ✅ **이슈 4 완전 해결** — `13_gui_code_output.md` 50자 → **18,547자**, `code/calculator.py` 추출
- 🔴 **신규 이슈 5 발견** — 동일 패턴이 비-GUI 16 에이전트에 잔존

### 이슈 5 스코프
| 분류 | 에이전트 | 개수 |
|---|---|---|
| QA | code_reviewer (변형 표현) | 1 |
| Build | dependency_analyzer / build_engineer / asset_manager / installer_creator / platform_tester | 5 |
| Release | release_manager / changelog_generator / update_checker / distribution_agent | 4 |
| C-Level / Operations / Analysis / Knowledge | convergence_judge / sandbox_runner / requirement_expander / gap_analyst / curator / rag_searcher | 6 |
| **합계** | | **16** |

PR #26 리포트는 *현재 체인의 10 개* 만 보고했으나, 정적 grep 전수 감사 결과 동일 패턴 16 개에 존재.

---

## 3️⃣ PR #27 — 이슈 5 fix (비-GUI 16 에이전트)

### 교정
- 16 backstory 의 `마지막 줄 Final Answer:` 패턴 → `Final Answer: 한 줄 + 본문` 패턴으로
- 회귀 방지 테스트 1건 (16 에이전트 정적 grep + CRITICAL 마커 확인)

### 결과: pytest 142 passed (141 + 1)

총 보호 backstory: GUI 4 (PR #25) + 비-GUI 16 (PR #27) = **20**

---

## 4️⃣ PR #28 — 4차 E2E + 이슈 6 발견

### 검증 결과 (실 LLM, 22분 09초)
- ✅ 이슈 5 fix **75% 효과적** (7/10 비-GUI 본문 캡처)
- 🟡 **신규 이슈 6 발견** — **LLM 비결정적 컴플라이언스**

### 이슈 6 진단
- 동일 fix 패턴이 7 에이전트에서 작동하면서 4 에이전트에서 실패 → prompt 자체는
  정확, LLM 의 통계적 행동이 원인
- **자기-종결 휴리스틱 가설**: 결정형 요약 (`tool=...`, `version=...`) 은 LLM 이
  "답변 끝" 으로 처리. 카운트형 요약 (`deps=N개...`) 은 자연스럽게 본문 유도.

### 본문 캡처율: 38% → **75%** (PR #24 → PR #28)

---

## 5️⃣ PR #29 — 이슈 6 방어선 1 (auto-retry)

### 설계
- `src/workflows/_common.py` 신설 — 3 워크플로우 (analyze / build / release) 의 `_task_output_text` 통합
- 신규 헬퍼:
  - `task_output_text(task)` — 공유 출력 추출 + 길이 경고
  - `retry_task_if_short(task, kickoff_fn, max_retries=1)` — 순수 재시도 로직
  - `retry_short_tasks_in_chain(tasks)` — production 헬퍼 (pytest 환경 skip)
- 3 워크플로우의 `Crew.kickoff()` 직후 retry 호출 추가

### 회귀 방지 테스트 12건
- pure 재시도 로직 (long skip / short replace / max_retries cap / exception graceful / 2nd attempt success)
- task_output_text basic
- pytest 환경 skip

### 결과: pytest **154 passed** (142 + 12)

---

## 6️⃣ PR #30 — 5차 E2E (방어선 1 효과 미미)

### 검증 결과 (실 LLM, 21분 38초)
- ✅ 방어선 1 코드 정상 작동 (pytest pass + E2E exit 0)
- 🟡 **캡처율 75% 정체** (PR #28 와 동일)

### 진단
- `BuildEngineer` / `ReleaseManager` 양 런 동일 1줄 요약 → **체계적 실패** (p ≈ 1.0)
- 단순 재시도는 동일 LLM + 동일 prompt 라 동일 결과
- 수학적 한계: 평균 25% 짧음 + max_retries=1 → 이론 6.25% 실패율인데 실측 25% → 일부 에이전트가 systematic 임을 시사

### 결론: 방어선 1 만으론 부족 → 방어선 2 (structured output) 필요

---

## 7️⃣ PR #31 — 방어선 2 시범 (output_pydantic 2 에이전트)

### 설계
- `src/workflows/_schemas.py` 신설:
  - `BuildSpecOutput` (5단 + summary) + `to_markdown()` 렌더러
  - `ReleaseDecisionOutput` (4단 + summary) + `to_markdown()`
- 시범 대상 task 빌더에 `output_pydantic=<Schema>` 추가 (production-only, pytest skip)
- `task_output_text` 가 `task.output.pydantic.to_markdown()` 우선

### 회귀 방지 테스트 9건
- 스키마 인스턴스 + to_markdown 섹션 검증
- pydantic 우선·raw fallback (graceful degradation)

### 결과: pytest **163 passed** (154 + 9)

---

## 8️⃣ PR #32 — NexusAlphaLLM 호환성 fix + 6차 E2E

### 1차 시도 실패 — production crash
PR #31 직후 실 LLM E2E 가 12분 진행 후 ConverterError:
> `'NexusAlphaLLM' object has no attribute 'supports_function_calling'`

CrewAI 1.14.1 의 converter 가 LLM 객체에 `supports_function_calling()` 호출 →
NexusAlphaLLM 어댑터에 미구현 → AttributeError → 무한 재귀.

### 어댑터 fix (1줄)
```python
def supports_function_calling(self) -> bool:
    return False  # → CrewAI 가 prompt-based JSON instruction fallback
```

### 2차 시도 (어댑터 fix 후) 성공 — 22분 49초

| 파일 | PR #30 (시범 전) | PR #32 (시범 후) | 비율 |
|---|---|---|---|
| `21_build_spec.md` | 67 | **9,669** | ×144 |
| `30_release_decision.md` | 37 | **2,156** | ×58 |

→ **시범 2 에이전트 100% 성공** — systematic failure 가 완전 해결.

### 캡처율: 75% → **81%** (13/16)

### Cosmetic 발견: `### 1. 도구 선택` 헤더 중복 (LLM 이 필드 안에 자체 헤더 포함)

---

## 9️⃣ PR #33 — 방어선 2 전체 확장 (12 에이전트)

### 12 신규 스키마

| 분류 | 에이전트 | 스키마 | 섹션 |
|---|---|---|---|
| QA | CodeReviewer | `CodeReviewOutput` | 5 |
| Planning | UIUXAnalyst | `UIUXSpecOutput` | 2 |
| Design | GUIDesigner / Theme / GUICodeGen | 각 4/3/3 | 10 |
| Build | DepAnalyzer / Asset / Installer / Platform | 각 3/3/4/5 | 15 |
| Release | Changelog / UpdateChecker / Distribution | 각 2/5/5 | 12 |

### 신규 sanitize 유틸
`_strip_leading_section_header(text)` — LLM 이 필드 본문에 자체 `### N.` 헤더
포함한 경우 첫 줄 제거 (PR #32 cosmetic 이슈 해결).

### Task 빌더 12 wired (production-only)

### 회귀 방지 테스트 21건 신규
- 12 신규 스키마 인스턴스/to_markdown 검증
- sanitize parameterized 8 케이스
- to_markdown sanitize 통합 시나리오

### 결과: pytest **184 passed** (163 + 21)

---

## 🔟 PR #34 — 7차 E2E (확장 효과 입증, 이슈 6 close)

### 검증 결과 (실 LLM, 28분 29초)

| 지표 | PR #28 (4차) | PR #30 (5차) | PR #32 (6차) | **PR #34 (7차)** |
|---|---|---|---|---|
| 캡처율 | 75% | 75% | 81% | **94%** |
| Systematic failure | 2 | 2 | 0 | **0** |

### Systematic failure 5/5 모두 해결

| 에이전트 | 이전 byte | PR #34 byte |
|---|---|---|
| BuildEngineer | 67 | **10,267** |
| ReleaseManager | 37 | **2,573** |
| CodeReviewer | 14 | **2,749** |
| ThemeDesigner | 82 | **5,593** |
| PlatformTester | 45 | **2,432** |

### Cosmetic sanitize 작동 — 헤더 중복 0건

### 잔존 1건 — `20_dependency_report.md` 782자 (LLM content variance, 무처리)

Schema 강제 정상 + 4 필드 모두 채워짐 + LLM 이 "calculator.py 단일 파일 → 분석
대상 부족" 으로 의도적 빈 결과 응답. PR #32 같은 입력에서 4,796자 작성한 것과
대비 — LLM run-to-run variance, schema 강제와 무관.

### 결론: **이슈 6 사실상 close**

방어선 2 (CrewAI `output_pydantic`) 가 데이터로 입증된 옳은 답.

---

## 📈 누적 성과 (단일 세션, 8시간)

| 지표 | 시작 | 종료 | 변동 |
|---|---|---|---|
| PR 머지 | 24개 | **34개** | +10 |
| 테스트 | 138 passed | **184 passed** | +46 |
| 본문 캡처율 (16 에이전트) | 38% | **94%** | +56% |
| 이슈 close | — | **4, 5, 6** | +3 |
| GUI 풀체인 (calculator.py) | 0 | **7차 연속 안정** | +7 |

### 코드 변경 요약

| 영역 | 신규 | 변경 |
|---|---|---|
| `src/workflows/_common.py` | 신설 (4 헬퍼) | — |
| `src/workflows/_schemas.py` | 신설 (14 스키마 + sanitize) | — |
| `src/workflows/analyze_and_implement.py` | — | 5 task wiring + retry |
| `src/workflows/build_workflow.py` | — | 5 task wiring + retry + import unification |
| `src/workflows/release_workflow.py` | — | 4 task wiring + retry + import unification |
| `src/agents/*/backstory.py` | — | 20 backstory 패턴 치환 (PR #25 4 + PR #27 16) |
| `src/llm/crewai_adapter.py` | — | `supports_function_calling=False` |
| `src/tests/test_workflow_*.py` | 2 신규 파일 | — |

---

## 🎯 핵심 학습

### 1. 이슈는 *체계적* 일 수도, *통계적* 일 수도
- 이슈 4: 4 GUI 에이전트의 prompt 패턴 — backstory 수정으로 *결정적* 해결
- 이슈 5: 16 비-GUI 에이전트 동일 패턴 — 같은 방식으로 *결정적* 해결
- 이슈 6: LLM 의 *통계적* 행동 — prompt 만으론 100% 보장 불가, 외부 메커니즘 필요

### 2. 방어선 1 vs 방어선 2 — 측정으로 결정
- 방어선 1 (auto-retry): 직관적·간단·저비용. 그러나 systematic failure 에는 무력 (p ≈ 1.0 의 동일 LLM 재호출)
- 방어선 2 (structured output): 더 깊은 통합. **schema 강제로 출력 형태 자체를 LLM 이 위반 못 하게** 함
- 5차 → 6차 → 7차 E2E 의 캡처율 데이터 (75% → 81% → 94%) 가 결정의 객관적 근거

### 3. 어댑터 호환성 부채는 production 에서 노출됨
NexusAlphaLLM docstring (PR 이전): "구조화 출력(response_model) 미지원". PR #31
의 output_pydantic 시범이 이 한계와 충돌 → 1차 E2E ConverterError. PR #32 의
1줄 fix (`supports_function_calling=False`) 가 부분적 호환성 확보.

### 4. cosmetic 이슈도 측정해야 발견됨
PR #32 6차 E2E 에서 `### 1. 도구 선택` 헤더 중복 (LLM 이 필드 안에 자체 헤더
포함). 시범 단계 효과 측정 안 했으면 14 에이전트 확장 후 발견됐을 것.

### 5. graceful degradation 설계
방어선 2 의 모든 단계에 fallback:
- output_pydantic 파싱 실패 → task.output.pydantic = None → raw 사용
- to_markdown 예외 → raw fallback
- pytest 환경 → 모든 production 메커니즘 skip (FakeProvider 호환)

---

## 🚨 알려진 위험 / 기술 부채

### A. DepAnalyzer 의 LLM run-to-run variance
PR #34 에서 빈 결과로 응답. 같은 입력에서 LLM 이 다른 판단을 할 수 있음. 향후
런에서 자연스럽게 길어질 가능성 높음. 무처리 권장.

### B. CrewAI 1.14.1 핀 + output_pydantic 의존성
방어선 2 가 CrewAI 의 converter 동작에 의존. CrewAI 메이저 업그레이드 시
호환성 재검증 필요.

### C. 외부 도구 미통합 (잔존 핵심 부채)
사양 산출 사슬은 안정 but 실제 PyInstaller / gh release 호출은 부재. v5 doc
DoD 의 핵심 미완 항목.

---

## 🎯 다음 액션 — PR #35 PyInstaller 통합

### 목적
사양 → 실제 `.exe` 산출. 첫 진짜 외부 도구 호출. v5 doc DoD Phase 4.5 체크박스
실질적 채움.

### 설계 초안
- 위치: `src/agents/build_release/build_executor.py` (신규)
- 입력: `BuildSpecOutput` 인스턴스 + `code_files` 목록
- 처리:
  1. PyInstaller 명령 빌드 (BuildSpec 사양 기반)
  2. 별도 venv 또는 subprocess 로 실제 호출
  3. 산출 `.exe` 검증 (존재·크기)
  4. SHA256 산출
- 통합: `build_workflow.py` 의 5단 사슬 끝에 executor 추가 (사양 → 산출물 단계)

### 검증 계획
- pytest: build_executor 단위 테스트 + 모킹된 subprocess 테스트
- 8차 E2E: 실 PyInstaller 호출 → calculator.exe 생성 → 부팅 확인

### 트레이드오프
- **장점**: 첫 진짜 결과물 (`.exe`). v5 doc 의 핵심 비전 (자연어 → setup.exe) 1단계 도달
- **단점**: PyInstaller 설치·환경 의존성 (CI 와 production 양쪽 검증 필요), 실행 시간 증가 (~3~5분 추가)

### 후속 마일스톤
- PR #36 (조건부): GitHub Release 자동 업로드 (gh release create)
- PR #37 (조건부): Update Checker 실제 통합 (산출 코드에 updater.py 임포트)
- PR #38 (조건부): 전체 풀체인 E2E ('계산기' → 다운로드 가능 setup.exe URL)

---

## 📂 산출 문서 (오늘 신규)

| 파일 | 내용 |
|---|---|
| `docs/progress/e2e_rereverification_post_pr25.md` | 재재검증 (이슈 5 발견) |
| `docs/progress/e2e_4th_verification_post_pr27.md` | 4차 E2E (이슈 6 발견) |
| `docs/progress/e2e_5th_verification_post_pr29.md` | 5차 E2E (방어선 1 미미) |
| `docs/progress/e2e_6th_verification_post_pr31.md` | 6차 E2E (시범 100%) |
| `docs/progress/e2e_7th_verification_post_pr33.md` | 7차 E2E (확장 94%) |
| `docs/progress/session_log_20260427.md` | 본 세션 로그 |

---

*"이슈는 이슈를 낳는다 (4 → 5 → 6) — 그러나 측정 기반 결정은 점진적 해결을
가능케 한다. 8시간 동안 38% → 94% 의 변화."*
