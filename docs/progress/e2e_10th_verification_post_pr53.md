# 10차 E2E 4·5차 + PR #53 (CrewAI converter rescue) — 부분 진척

**검증 대상**: PR #53 (`workflow-level rescue: ConverterError + ValidationError 둘 다 흡수`)
**실행 일시**: 2026-04-29 15:43~17:06 (KST, 4차 + 5차)
**핵심 결과**: **fatal exception 사라짐, 풀체인 30분 완주 가능해짐**. 다만 rescue 후 LLM 출력이 짧아져 코드 추출 실패 — 별도 후속 PR 필요.

---

## 🎯 한 줄 요약

| | 4차 (rescue v1) | **5차 (rescue v2)** |
|---|---|---|
| Status | FAILED (raw ValidationError escape) | **SUCCESS** (fatal 0) ⭐ |
| Elapsed | 18.71분 | **30.34분** (첫 완주) |
| 죽은 위치 | Installer Creator | (없음) |
| `code/` 파일 | n/a (조기 종료) | ❌ 0개 (rescue 후 LLM 출력 짧음) |
| build_executor / publish | ❌ | ❌ (코드 부재) |
| qa overall_passed | (미도달) | ✅ True (vacuous — 4종 모두 SKIPPED) |

**진척**: fatal 예외 → 풀체인 완주 가능 (대형 진척). 그러나 **secondary 결함** (rescue 후 짧은 출력) 으로 코드 추출 실패 — PR #54 후속.

---

## 1️⃣ 4차 시도 (15:43~16:02) — 새 결함 패턴 발견

### 실행 결과

```
Elapsed: 1122.48s (18.71 min)
Status: FAILED
[ERROR] ValidationError: 1 validation error for InstallerSpecOutput
        Invalid JSON: key must be a string at line 1 column 2
        [type=json_invalid, input_value='{{8F3C2A91-4E7B-4D5F-9B1...제 시 `{autodesktop}', input_type=str]
```

### 진단

PR #53 v1 의 rescue 헬퍼는 `ConverterError` 만 잡았으나, 4차에서 발견된 새 결함은
**raw `pydantic.ValidationError`** 가 CrewAI 를 그대로 통과해 escape:

```
crewai/utilities/converter.py:193 convert_to_model
  → handle_partial_json (JSONDecodeError 분기)
crewai/utilities/converter.py:260 handle_partial_json
  → model.model_validate_json(match.group())
crewai/utilities/converter.py:266 except ValidationError: raise   ← wrap 없이 재상승
crewai/task.py:817 _execute_core: raise e
```

CrewAI 의 `_JSON_PATTERN = r"({.*})"` (DOTALL, greedy) 가 LLM markdown 의
**Inno Setup GUID 구문** `{{8F3C2A91-4E7B-4D5F-9B1...}}` 와 placeholder
`{autodesktop}` 를 잘못 매칭한 후 `model_validate_json` 에서 ValidationError →
`except ValidationError: raise` 로 그대로 surface.

### 처방: rescue v2 — ValidationError 도 흡수

```python
# src/workflows/_common.py
def _rescuable_exc_classes() -> tuple[type[BaseException], ...]:
    """rescue 대상 = ConverterError + Pydantic ValidationError"""
    classes = []
    if _ConverterError is not None:
        classes.append(_ConverterError)
    if _PydanticValidationError is not None:
        classes.append(_PydanticValidationError)
    return tuple(classes)


def kickoff_with_converter_rescue(crew, tasks, max_rescue=1):
    rescuable = _rescuable_exc_classes()
    try:
        return crew.kickoff()
    except rescuable as e:        # ← Converter + Validation 둘 다
        # output_pydantic 벗기고 1회 재실행
        ...
```

신규 테스트 3개 (10 → 13 rescue 관련):
- `test_rescue_strips_pydantic_and_retries_on_validation_error`
- `test_rescue_validation_error_no_pydantic_reraises`
- `test_rescuable_exc_classes_includes_both_when_available`

전체 pytest: **442 → 445 passed (회귀 0)**.

---

## 2️⃣ 5차 시도 (16:35~17:05) — fatal 0, 첫 완주

### 실행 결과

```
Elapsed: 1820.32s (30.34 min)
Status: SUCCESS                    ← fatal 예외 0
End: 2026-04-29T17:05:55

[QA] 1/4 도구 활성 검증
[QA] artifact_category=unknown
[QA] [QA_LOOP PASS] retry=0/3, failed=0, skipped=1
[QA] PASS — 재시도 불필요

--- M5 + QA DoD 7가지 체크 ---
  1_publish_success             : ❌ False
  2_release_url_issued          : ❌ False
  3_download_urls_count         : ❌ 0
  4_is_draft                    : ⏭ None
  5_executor_success            : ❌ False
  6_qa_overall_passed           : ✅ True (vacuous — 코드 부재로 검증 대상 0)
  7_qa_iterations_within_budget : ✅ True
```

### Rescue 실 발동 — 2회 ⭐

콘솔 로그:
```
[converter rescue] ValidationError: tasks=[
    'Senior GUI Designer (Wireframe & Widget Tree)',
    'Senior Theme Designer (Design Tokens & Visual Language)',
    'Senior GUI Code Generator (Framework Selection & Code Synthesis)',
    'Senior Code Reviewer (Static QA)'
]; output_pydantic stripped, retrying once.
Original: 1 validation error for GUICodeOutput
  Invalid JSON: expected `:` at line 1 column 5
  [type=json_invalid, input_value='{"+", "−", "×", "÷"}... {self.engine.operator}', input_type=str]
```

**원인**: GUI Code Generator 가 Python set literal `{"+", "−", "×", "÷"}` 을 markdown
본문에 포함 → CrewAI `_JSON_PATTERN` 매칭 → `model_validate_json` 실패 →
ValidationError. 우리 rescue 가 정확히 잡아 4 task 의 `output_pydantic` 을 벗기고
재 kickoff → 통과 → 풀체인 완주.

### Secondary 결함 — 짧은 출력 후 코드 추출 실패

산출 디렉터리 (`outputs/workflow_20260429_163544/`):

```
00_user_request.txt     ✅
01_cto_strategy.md      ✅
...
13_gui_code_output.md   ⚠️ 71 byte
03_engineer_output.md   ⚠️ 66 byte
20_dependency_report.md ✅
...
33_distribution_spec.md ✅
code/                   ❌ (빈 디렉터리)
```

`13_gui_code_output.md` 내용 전문:
```
framework=tkinter+customtkinter, files=1개, entry=python calculator.py
```

→ `Final Answer:` 한 줄 summary 만 — 본 코드 블록 (`python\n# calculator.py\n...`) 부재.

#### 진단

1. 1차 kickoff 시 LLM 이 **markdown + Python set literal** 산출 → ValidationError
2. rescue v2 가 잡아 `output_pydantic=None` 으로 벗김
3. 같은 crew 재 kickoff
4. 두 번째 LLM 호출 시 schema instruction (`get_conversion_instructions`) 부재 →
   LLM 이 backstory 의 `정확한 출력 형태` 예시 (한 줄 Final Answer) 만 따름
5. raw output = 한 줄 → 코드 블록 추출 정규식 매칭 실패 → `code_paths = []`

`retry_short_tasks_in_chain` 도 도와주지 못함 — backstory 가 일관되게 짧은
패턴을 유도하므로 재시도해도 같은 짧은 결과.

#### Trade-off 정리

| 측면 | rescue 적용 전 | rescue 적용 후 (PR #53) |
|---|---|---|
| Fatal 예외 | ConverterError / ValidationError 로 풀체인 abort | **0 — 30분 완주** |
| Pydantic schema 보장 | 있음 (성공 시) | rescue 발동 시 *해당 chain* 만 잃음 |
| LLM 산출 본문 길이 | 정상 (markdown 본문 + Final Answer) | rescue 후 *해당 chain* 짧아질 수 있음 |
| 코드 추출 | 본문 있으면 OK | 본문 짧으면 0 파일 (←5차 사례) |
| 풀체인 진행 가능성 | 즉사 위험 | 진행 가능, 단 산출 부분 결함 가능 |

**판단**: fatal 예외 회피가 *훨씬 더 큰 이득* — 30분의 LLM 비용을 0으로 만드는
대신 30분을 들여 부분 산출이라도 얻음. PR #54 에서 rescue 후 출력 보강
패턴 후속 보완.

---

## 3️⃣ PR #53 변경 내역

### `src/workflows/_common.py` — rescue 헬퍼 신설

- `_rescuable_exc_classes()` — `ConverterError ∪ ValidationError` 동적 합성 (각 import 실패 시 graceful)
- `kickoff_with_converter_rescue(crew, tasks, max_rescue=1)` — kickoff 호출 + 두 예외 흡수 + `output_pydantic=None` 으로 벗기고 1회 재시도

### 7개 kickoff 사이트 처제

| 파일 | 사이트 | 비고 |
|---|---|---|
| `analyze_and_implement.py` | UIUX (1), Classic chain (1), CLI chain (1), GUI chain (1) | 4 사이트 |
| `build_workflow.py` | Build 4 chain (1), Platform Tester (1) | 2 사이트 |
| `release_workflow.py` | Release 4 chain (1) | 1 사이트 |

`iterative_loop.py` 의 2 kickoff 는 `output_pydantic` 미사용 → rescue 불필요.

### 테스트 10개 추가

`src/tests/test_workflow_common.py`:
- ConverterError 7개 (happy / strip / multiple / no-pydantic-reraise / max_rescue=0 / non-converter / 2-call max)
- ValidationError 3개 (strip / no-pydantic-reraise / classes-include-both)

전체 pytest: **442 → 445 passed (회귀 0)**.

---

## 4️⃣ M5+QA DoD 진척

| | PR #51 (10차 2차) | PR #52 (단독 gui_test) | **PR #53 (10차 5차)** |
|---|---|---|---|
| 풀체인 fatal-free | ✅ (28분) | n/a (단독) | ✅ **30분 완주** ⭐ |
| Calculator.exe 산출 | ✅ | n/a | ❌ (코드 추출 실패) |
| Publish | ✅ draft | n/a | ❌ |
| active QA gating | 0/4 | 1/4 (gui_test 단독) | 0/4 (코드 부재) |
| rescue 인프라 | (없음) | (없음) | ✅ ConverterError + ValidationError 둘 다 |

---

## 🎯 다음 PR 후보 (PR #54)

### 목적

rescue 가 fatal 흡수 후 LLM 산출이 짧아지는 부수효과 보완. **풀체인 + 코드
추출 + .exe + publish + active QA** 를 한 번에 통과시킬 수 있도록.

### 후보 처방

#### A. Capture-before-rescue (가장 깔끔)

CrewAI converter 가 raise 하기 *전* LLM 의 raw 응답을 가로채 task.output 에
직접 주입 → rescue 시 재 kickoff 불필요 → schema 만 잃고 본문 보존.

구현 위치: `kickoff_with_converter_rescue` 에서 예외의 `__cause__` 또는
`task.output_history` 등에서 raw 텍스트 추출 시도.

#### B. Backstory hardening

GUI Code Generator / Build Engineer / Installer Creator 의 backstory 에 *항상*
markdown 본문을 길게 출력하도록 강조 (`Final Answer:` 한 줄만 제출 절대
금지). rescue 후에도 짧아지지 않도록 LLM 행동 안정화.

#### C. Custom converter_cls 주입

CrewAI Task 에 `converter_cls=` 로 우리만의 Converter 를 주입해 markdown ↔
JSON 변환을 우회. 가장 본질적이지만 CrewAI 내부 의존이 강해 유지보수 부담 큼.

**권장**: A 우선 시도, 실패 시 B 로 폴백.

---

## 📦 산출 / 검증

| 항목 | 값 |
|---|---|
| 5차 산출 디렉터리 | `outputs/workflow_20260429_163544/` |
| 5차 summary.json | `outputs/e2e_10th_verification_20260429_163534/summary.json` |
| pytest 결과 | 445 passed (회귀 0) |
| rescue 실 발동 횟수 | 2회 (5차 GUI chain ValidationError) |
| 6번 retry_short warnings | (정상 — 별도 메커니즘) |
| Calculator.exe / publish | (5차 미생성 — secondary 결함) |

---

*"4차에서 새 결함 패턴 발견 → rescue v2 확장 → 5차 fatal 0 완주.*
*다음 단계: rescue 후 짧은 출력 보완 (PR #54)."*
