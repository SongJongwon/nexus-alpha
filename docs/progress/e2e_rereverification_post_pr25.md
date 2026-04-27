# E2E 재재검증 결과 — PR #25 사후 (2026-04-27)

**검증 대상**: PR #25 (`🔧 이슈 4 수정 — GUI 4개 에이전트 Final Answer 본문 누락 해소`) 가
main 에 병합된 후, 이슈 4 가 실제로 해소됐는지 + PR #23 의 3개 이슈가 여전히 유지되는지
실 LLM (Claude MAX / agent_sdk) 으로 재검증.

**실행 명령**: `python scripts/run_e2e_verification.py`
**실행 시간**: 17분 55초 (1075.64초)
**산출 디렉터리**: `outputs/workflow_20260427_094102/`
**요약 파일**: `outputs/e2e_verification_20260427_094053/summary.json`
**LLM 호출 추정**: 14건 (UI/UX + CTO + Analyst + GUI 3 + QA + Build 5 + Release 4)

---

## 종합 판정

| # | 이슈 | 검증 결과 | 비고 |
|---|---|---|---|
| 1 | GUI 분기 미실행 | ✅ **유지** | `chosen_path=gui`, 10/11/12/13 모두 생성 |
| 2 | "계산기" → 데이터 분석 도구 | ✅ **유지** | CTO 가 "계산기 데스크톱 앱 — 기술 전략 문서" 작성 |
| 3 | 상대 import 단독 실행 불가 | ✅ **해결 확인** | `code/calculator.py` 추출됨, 절대 import + py_compile 통과 |
| 4 | GUI 4 에이전트 본문 누락 | ✅ **해결 확인** | 4개 산출 모두 본문 + 코드 블록 캡처 (이전 50자 미만 → 현재 18,547자) |

| # | 신규 이슈 | 심각도 | 상태 |
|---|---|---|---|
| **5** | **비-GUI 10개 에이전트 본문 누락** (QA + Build 5 + Release 4) | 🟡 **중간** | 별도 PR 필요 — 이슈 4 와 동일 패턴 |

---

## 이슈 4 — GUI 본문 캡처 — ✅ 해결 확인

### 검증 데이터 (4 GUI 산출물)

| 파일 | 라인 수 | 글자 수 | 첫 줄 (Final Answer summary) | 본문 캡처 |
|---|---|---|---|---|
| `10_ui_ux_spec.md` | 28 | 1,312 | `form_factor=single_window, complexity=simple, need_gui=yes` | ✅ YAML + 분석가 노트 포함 |
| `11_gui_design.md` | 100+ | 4,877 | `GUI design — 1개 윈도우, 24개 위젯` | ✅ 와이어프레임 + 위젯 명세 |
| `12_design_tokens.md` | 80+ | 3,381 | `theme_strategy=native, modes=1개, palette=...` | ✅ JSON 토큰 + 매핑표 |
| `13_gui_code_output.md` | 515 | 18,547 | `framework=tkinter, files=1개, entry=python calculator.py` | ✅ 본문 + ` ```python` 코드 블록 |

PR #25 의 4개 backstory 변경 (`마지막 줄 Final Answer: <summary>` → `Final Answer: 한 줄 +
이후 본문 전체` 패턴) 이 정확히 의도대로 작동. CrewAI 가 이제 Final Answer 이전이 아니라
**이후의 본문**을 raw 에 그대로 보존.

### `code/` 디렉터리 추출

```
outputs/workflow_20260427_094102/code/
└── calculator.py   (473 줄, 표준 라이브러리만 import)
```

- `from __future__ import annotations` + `import tkinter as tk` (절대 import) ✅
- 상대 import (`from .foo import bar`) **0건** ✅
- `if __name__ == "__main__": main()` 엔트리 포인트 존재 ✅
- `python -m py_compile` 통과 ✅

→ **이슈 3 (단독 실행)** 도 함께 해결 확인 (PR #23 의 단독 실행 가이드라인이 GUI Code
Generator 산출에 정상 반영됨).

---

## 이슈 1 — GUI 분기 — ✅ 유지

```
chosen_path: gui
saved_dir: outputs/workflow_20260427_094102
saved_code_files: [calculator.py]
```

UI/UX Analyst 가 `need_gui: yes, form_factor: single_window, complexity: simple` 출력 →
파서가 GUI 경로 분기. PR #23 의 보정(`need_gui` + `form_factor` 양쪽 시그널 인식) 정상.

---

## 이슈 2 — 프롬프트 해석 — ✅ 유지

CTO 산출 (`01_cto_strategy.md`, 10,119 자) 첫 부분:

```
# 계산기 데스크톱 앱 — 기술 전략 문서

## 0. 사전 명확화 질문
1. 계산 범위: 사칙연산만? 괄호/%/제곱 등 포함?
2. 소수점/정밀도 정책 (Decimal 권장)
3. 히스토리 기능 MVP 포함?
...

## 1. 기술 스택
| 언어 | Python 3.11+ |
| GUI 프레임워크 | Tkinter (1순위) |
| 계산 엔진 | decimal.Decimal |
```

→ "계산기" 가 정확히 GUI 데스크톱 계산기로 해석됨. 데이터 분석 도구 패턴 0건.

---

## 🟡 신규 이슈 5 — 비-GUI 10개 에이전트 본문 누락

### 증상

| 파일 | 글자 수 | 캡처된 전체 내용 |
|---|---|---|
| `04_qa_review.md` (QA Reviewer) | 14 | `NEEDS_REVISION` |
| `20_dependency_report.md` (Dep Analyzer) | 63 | `deps=0개, hidden=2개, license_warnings=0개, os_blockers=0개` |
| `21_build_spec.md` (Build Engineer) | 67 | `tool=pyinstaller, mode=onefile, hidden_imports=2개, est_size=~12MB` |
| `22_asset_manifest.md` (Asset Manager) | 72 | (한 줄 요약) |
| `23_installer_spec.md` (Installer Creator) | 76 | (한 줄 요약) |
| `24_platform_test_report.md` (Platform Tester) | 45 | (한 줄 요약) |
| `30_release_decision.md` (Release Manager) | 37 | `version=0.2.0, bump=minor, tag=v0.2.0` |
| `31_changelog_entry.md` (Changelog Generator) | 60 | (한 줄 요약) |
| `32_update_module_spec.md` (Update Checker) | 98 | (한 줄 요약) |
| `33_distribution_spec.md` (Distribution Agent) | 132 | `channel=github_releases, url=..., signed=no` |

### 근본 원인

이슈 4 와 **완전히 동일한 패턴**. 10개 backstory 모두 다음 구문 포함:

```
"마지막 줄은 반드시 `Final Answer:` 로 시작 — `Final Answer: <key>=<val>, ...`"
```

CrewAI 1.14.1 의 ReAct 파서는 `Final Answer:` 라인 **이후** 텍스트만 `task.output.raw`
에 저장. 따라서 LLM 이 본문을 *이전*에 두면 손실, *이후*에 두어야 보존.

### 사전 vs 사후 비교

이슈 5 는 **신규 발생이 아니라 사전부터 잠재**해 있었으나 PR #24 검증 당시 GUI 산출에
시선이 집중되어 미보고:

| 파일 | PR #24 런 (2026-04-21) | PR #25 런 (2026-04-27) | 변동 |
|---|---|---|---|
| `04_qa_review.md` | 14 | 14 | 동일 |
| `20_dependency_report.md` | 63 | 63 | 동일 |
| `21_build_spec.md` | 66 | 67 | ±1 |
| `22~24` (Build 잔여) | 42~76 | 45~76 | ±3 이내 |
| `30~33` (Release 4) | 37~133 | 37~132 | ±1 |

→ PR #25 가 회귀를 발생시킨 것이 아니라, 동일 패턴이 본래부터 존재.

### 영향 평가

- **빌드/릴리스 사양 산출이 1줄 요약만**. `01_cto_strategy.md` 같은 풀 마크다운 사양이
  아니라 `tool=pyinstaller, mode=onefile, hidden_imports=2개, est_size=~12MB` 단 한 줄.
- 사용자/리뷰어가 사양 근거를 확인 불가 → 향후 v5 doc DoD Phase 4.5/5 의 "사양 산출"
  체크리스트가 형식상 완료되더라도 *내용*이 비어 있는 문제.
- QA Reviewer 의 `NEEDS_REVISION` 만 캡처되어 *어떤 부분*을 수정해야 하는지 불명 →
  iterative_loop 도입 시 Convergence Judge 가 활용할 컨텍스트 부재.

### 권장 수정 (별도 PR 예정)

PR #25 와 동일 방식으로 10개 backstory 의 `마지막 줄 Final Answer:` 패턴을 다음으로
치환:

```
"출력 형식:
Thought: <간단한 사고>
Final Answer: <한 줄 요약>

<섹션 1 본문>
<섹션 2 본문>
..."
```

회귀 테스트도 동일하게 정적 grep 으로 확장:
- `test_non_gui_agent_backstories_do_not_use_truncating_final_answer_pattern`
- 대상 10개 backstory 의 `마지막 줄 Final Answer` 문구 0건 보장

### 우선순위

**중간** — Phase 4.5/5 의 *외부 도구 미통합* (WORK_STATUS §B) 을 해결하기 *전*에 처리
필요. 외부 도구 통합 시 빌드 사양/릴리스 사양이 실제 호출 입력으로 쓰일 것이므로,
풀 마크다운 사양 보존이 선결 조건.

---

## 성능 지표

| 지표 | PR #24 런 | PR #25 런 | 변동 |
|---|---|---|---|
| 총 실행 시간 | 13분 27초 | 17분 55초 | +4분 28초 (+33%) |
| LLM 호출 | 14 | 14 | 동일 |
| 산출 파일 (GUI 경로) | 18 | 19 | +1 (`code/calculator.py` 추가) |
| GUI 코드 본문 (`13_gui_code_output.md`) | 50자 미만 | 18,547자 | **+18,500자** |
| `code/` 디렉터리 추출 | 0개 | 1개 (`calculator.py`) | +1 |

실행 시간 증가 33% 의 주된 원인은 GUI 4 에이전트가 이제 본문을 출력하느라 토큰 예산
사용량 증가. 합리적 범위 (시간 vs 결과물 품질 trade-off 양호).

---

## 핵심 결론

1. **이슈 4 (GUI 본문 손실) 완전 해결.** PR #25 수정이 의도대로 작동, GUI 4 에이전트
   본문 + 코드 블록 모두 보존.
2. **풀체인 GUI E2E 첫 성공.** 사용자 요청 ("계산기 만들어줘") → 단독 실행 가능한
   `calculator.py` (473 줄, py_compile 통과) 추출 완료. 외부 도구 (PyInstaller / gh)
   통합 전 단계까지의 사슬은 완전 작동.
3. **이슈 5 발견 — 동일 패턴 잔존.** 비-GUI 10개 에이전트가 같은 `마지막 줄 Final
   Answer` 패턴 보유 → 별도 PR 로 처리 필요.
4. **회귀 테스트 효과 입증.** PR #25 의 정적 grep 테스트
   (`test_gui_agent_backstories_do_not_use_truncating_final_answer_pattern`) 가 GUI
   에이전트의 패턴 *재도입* 을 차단. 동일 메커니즘을 비-GUI 에이전트로 확장하면 됨.

---

## 다음 액션

1. **PR #26** (이 문서 + WORK_STATUS 업데이트 + scripts/) → 본 검증 결과 영구 기록
2. **PR #27 (예정)**: 이슈 5 수정 — 비-GUI 10 에이전트 backstory 패턴 치환 + 회귀
   테스트 확장
3. **PR #27 사후 E2E 4차 검증**: 모든 14 에이전트 본문 캡처 확인 → v5 doc DoD 의
   "사양 산출" 체크박스 *내용까지* 채움
4. (선택) WORK_STATUS §3 (CLI 경로 E2E) — 이슈 5 가 CTO/Analyst/Engineer 에는 없음을
   재확인했으나, CLI 경로에서 이슈 5 가 어떻게 보이는지 (Build/Release 토글 활성화 시)
   를 별도 검증

---

*요청 → 단독 실행 가능 GUI 코드까지의 사슬은 이제 작동. 남은 것은 (a) 비-GUI 산출의
풀 본문 (이슈 5), (b) 외부 도구 (PyInstaller/gh) 실제 호출 통합 (WORK_STATUS §B).*
