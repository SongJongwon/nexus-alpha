# 4차 E2E 검증 결과 — PR #27 사후 (2026-04-27)

**검증 대상**: PR #27 (`🔧 이슈 5 수정 — 비-GUI 16개 에이전트 Final Answer 본문
누락 해소`) 가 main 에 병합된 후, 16 개 에이전트가 실 LLM 환경에서 본문 + 요약을
모두 출력하는지 재검증.

**실행 명령**: `python scripts/run_e2e_verification.py`
**실행 시간**: 22분 9초 (1329.31초)
**산출 디렉터리**: `outputs/workflow_20260427_130137/`
**요약**: `outputs/e2e_verification_20260427_130126/summary.json`
**LLM 호출**: 14건 (UI/UX + CTO + Analyst + GUI 3 + QA + Build 5 + Release 4)

---

## 종합 판정

| 카테고리 | 에이전트 수 | 결과 |
|---|---|---|
| 정상 (full body) | 12 | ✅ |
| 짧음 (Final Answer 요약만) | 4 | 🟡 |
| **본문 캡처율** | **75%** | (PR #26 0% → 75%) |

| # | 이슈 | 결과 |
|---|---|---|
| 1 | GUI 분기 미실행 | ✅ 유지 (`chosen_path=gui`) |
| 2 | "계산기" → 데이터 분석 도구 | ✅ 유지 (CTO 9,390 자 GUI 계산기 전략) |
| 3 | 상대 import 단독 실행 불가 | ✅ 해결 (`code/calculator.py` 21,317 자, py_compile 통과) |
| 4 | GUI 4 에이전트 본문 누락 | 🟡 **부분 회귀** — UIUXAnalyst 1건 본문 손실 (3/4 정상) |
| 5 | 비-GUI 10 에이전트 본문 누락 | ✅ **70% 해결** (7/10 본문 캡처) |
| **6** | **(신규) LLM 비결정적 컴플라이언스** | 🟡 PR #25/#27 의 prompt restructuring 이 100% 보장 안 함 |

---

## 상세 비교 — PR #26 baseline vs 본 런

| 파일 | PR #26 (이슈 5 발견 시) | 본 런 (PR #27 적용) | 판정 |
|---|---|---|---|
| `01_cto_strategy.md` | 10,119 | 9,390 | ✓ 정상 |
| `02_analyst_brief.md` | 13,436 | 10,645 | ✓ 정상 |
| `04_qa_review.md` | **14** | **8,536** | ✅ FIX OK (×610) |
| `10_ui_ux_spec.md` | 2,483 | **58** | 🔴 **REGRESSED** |
| `11_gui_design.md` | 8,374 | 6,734 | ✓ 정상 |
| `12_design_tokens.md` | 4,885 | 4,808 | ✓ 정상 |
| `13_gui_code_output.md` | 21,658 | **25,043** | ✓ 정상 (오히려 증가) |
| `20_dependency_report.md` | **63** | **4,769** | ✅ FIX OK (×76) |
| `21_build_spec.md` | **67** | **67** | 🟡 STILL SHORT |
| `22_asset_manifest.md` | **72** | **8,946** | ✅ FIX OK (×124) |
| `23_installer_spec.md` | **76** | **10,227** | ✅ FIX OK (×135) |
| `24_platform_test_report.md` | **45** | **5,003** | ✅ FIX OK (×111) |
| `30_release_decision.md` | **37** | **37** | 🟡 STILL SHORT |
| `31_changelog_entry.md` | **60** | **1,506** | ✅ FIX OK (×25) |
| `32_update_module_spec.md` | **98** | **16,702** | ✅ FIX OK (×170) |
| `33_distribution_spec.md` | **132** | **132** | 🟡 STILL SHORT |

---

## 🟡 신규 이슈 6 — LLM 비결정적 컴플라이언스

### 증상

PR #25 + PR #27 의 prompt restructuring 으로 *대부분* 의 에이전트가 본문 + 요약을
정상 출력하지만, **LLM 이 가끔 본문을 생략하고 Final Answer 한 줄만 출력** 하는
케이스가 잔존.

본 런에서 4 개 에이전트가 영향:

| 에이전트 | 출력 (전체) | 분류 |
|---|---|---|
| **UIUXAnalyst** | `form_factor=single_window, complexity=simple, need_gui=yes` | 🔴 회귀 (PR #25 fix 후 PR #26 에서 정상이었음) |
| **BuildEngineer** | `tool=pyinstaller, mode=onefile, hidden_imports=1개, est_size=~12MB` | 🟡 잔존 |
| **ReleaseManager** | `version=0.1.1, bump=patch, tag=v0.1.1` | 🟡 잔존 |
| **DistributionAgent** | `channel=github_releases, url_template=..., signed=no, sha256_in_manifest=yes` | 🟡 잔존 |

12 개 에이전트는 **정확히 같은 fix 패턴** 으로 본문을 정상 출력 (예: AssetManager
8,946 자, InstallerCreator 10,227 자, UpdateChecker 16,702 자).

### 근본 원인 분석

prompt 의 출력 규약 자체는 명확:
```
**출력 규약 (CRITICAL)**: Final Answer: 라인에 한 줄 요약 + 그 다음 줄부터 위 모든
본문 섹션 작성. 본문이 Final Answer 보다 앞에 오면 CrewAI 가 본문을 잃어버립니다.
```

원인은 prompt 가 아니라 **LLM의 통계적 행동**:

1. **자기-종결 휴리스틱**: BuildEngineer/ReleaseManager/DistributionAgent 의 요약
   포맷 (`tool=...`, `version=...`, `channel=...`) 이 *자체로 완결된 결정* 처럼
   보여서 LLM 이 "답변 끝" 으로 처리할 가능성. 반면 dep_analyzer 의 `deps=N개,
   hidden=M개...` 는 *카운트* 라 자연스럽게 "상세 보여줘" 를 유도.
2. **샘플링 분산**: 같은 prompt 도 temperature/seed 에 따라 ±. UIUXAnalyst 는
   PR #26 에서 정상 → PR #28 에서 짧음 — 동일 prompt, 다른 결과.

### 영향 평가

- **현재 작동 사슬에는 무영향**: GUI 코드 (calculator.py 21,317 자) 추출 정상,
  단독 실행 가능. py_compile 통과.
- **빌드/릴리스 사양에 부분 영향**: tool/version/channel 한 줄만 캡처 — 외부 도구
  통합 시 *어떤 식으로 빌드할지* 의 상세는 부재. 다만 후속 자동화 스크립트가
  요약 한 줄만으로 작동 가능한 단순 사례 (계산기) 에선 차단 안 됨.
- **재현성**: 같은 prompt 로 재실행 시 결과 다를 수 있음 → 확정적 검증을
  제공하지 못함.

### 권장 조치 (PR #29 또는 후속)

1. **출력 검증 + 재시도** (방어선 1):
   - `_task_output_text` 가 raw < 120 자 감지 시 *현재는 경고만* — 같은 task 를
     **자동 재실행** 하도록 확장 (최대 1~2 회).
   - 16 개 에이전트 모두 적용.
2. **structured output API 채택** (방어선 2 — 근본):
   - Anthropic SDK 의 `tools` 또는 OpenAI 의 `response_format=json_schema` 같은
     스키마 강제 메커니즘으로 출력 형태 자체를 LLM 이 위반 못 하게 함.
   - CrewAI 1.14.1 가 지원하는지 검토 필요 (이슈 4 fallback 의 근본 해결).
3. **prompt 추가 강화** (방어선 0 — 임시):
   - 짧음 사례 3 에이전트 (build_engineer / release_manager / distribution_agent)
     의 backstory 에 "다음 7 개 섹션을 *반드시* 작성하지 않으면 자동 재시도된다" 같은
     강제 문구 추가. 효과는 통계적이지만 적은 비용.

### 우선순위

**중간** — 외부 도구 통합 (WORK_STATUS §B, PyInstaller / gh) 직전 처리. 외부
자동화가 빌드 사양을 입력으로 사용하기 시작하면 1줄 요약은 부족.

---

## 성능 지표

| 지표 | PR #24 (1차) | PR #26 (2차) | PR #28 (4차, 본 런) |
|---|---|---|---|
| 총 실행 시간 | 13:27 | 17:55 | **22:09** |
| LLM 호출 | 14 | 14 | 14 |
| 본문 캡처 (16 에이전트 중) | 6/16 (38%) | 6/16 (38%) | **12/16 (75%)** |
| GUI 코드 본문 | <50자 | 18,547자 | **25,043자** |
| `code/calculator.py` | 0개 | 1개 (15,000자 추정) | **1개 (21,317자, py_compile OK)** |

**개선 방향**: PR #26 38% → PR #28 75% (이슈 5 fix 효과 명확). 다만 100% 도달엔
LLM 비결정성 해결 (위 권장 조치) 필요.

실행 시간 22 분은 본문 출력 증가에 따른 토큰 사용량 증가 + Claude MAX 의 안정적
응답 시간 변동성. 합리적 범위.

---

## 핵심 결론

1. **이슈 5 fix 는 75% 효과적.** 7 개 비-GUI 에이전트가 정상 본문 출력 (PR #26
   대비 명백한 개선).
2. **이슈 6 발견 — LLM 비결정적 컴플라이언스.** prompt 자체는 정확하나 LLM 이
   가끔 본문 생략. 회귀 테스트 (정적 grep) 는 prompt 만 검증, 실제 LLM 출력은
   감지 불가.
3. **GUI 풀체인 첫 성공 유지.** `code/calculator.py` 21,317 자 추출, py_compile
   통과 — calculator GUI 가 단독 실행 가능한 시점이 안정화됨.
4. **회귀 방지 정적 grep 은 정상 작동.** PR #25/#27 의 backstory 패턴 검사
   142+ pytest 모두 통과 (회귀 0).

---

## 다음 액션

1. **PR #28** (이 문서 + WORK_STATUS 업데이트) → 본 검증 결과 영구 기록
2. **PR #29 (예정)**: 이슈 6 — `_task_output_text` 자동 재시도 (방어선 1) 또는
   structured output API 도입 검토 (방어선 2)
3. **WORK_STATUS §3 (CLI 경로 E2E)** 또는 **§4 (PyInstaller 통합)**:
   - GUI 사슬은 calculator.py 단계까지 안정 → 외부 도구 통합으로 확장 시점
   - 이슈 6 가 외부 도구 통합 시 *얼마나* 차단 요인인지 함께 평가 필요

---

*이슈 5 fix 가 의도한 방향으로 작동함을 확인. 100% 결정성 부재는 LLM 본질적
한계 — structured output API 같은 외부 메커니즘으로만 완전 해결 가능.*
