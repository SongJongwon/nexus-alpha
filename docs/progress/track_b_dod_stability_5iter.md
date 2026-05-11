# Track B DoD 7/7 안정성 반복 검증 (후보 N, 5-iter)

> 실시 일자: **2026-05-11**
> 대상: Track B 풀체인 (`run_e2e_10th_verification.py --enable-automate-*`)
> 시나리오: `네이버 쇼핑 가격 크롤링 스크립트` (PR #97 baseline 과 동일)
> 검증 도구: `scripts/run_dod_stability.py` (본 PR 신설)
> 산출 디렉터리:
> - `outputs/dod_stability_20260511_100350/` (iter 1~3)
> - `outputs/dod_stability_20260511_104920/` (iter 4~5)

---

## TL;DR

- **5-iter 안정성: 3/5 PASS (60%)** — PR #97 의 1/1 single-shot PASS 가
  대표적이지 않음을 empirical 입증.
- **5 인프라 항목 (publish / release_url / download_urls / draft / executor)
  은 5/5 = 100% 안정** — gh CLI + PyInstaller deterministic.
- **변동성은 6_qa_overall_passed 단일 항목에 집중** — LLM variance + 1개의
  *deterministic defect*.
- **N-failure rule trigger**: ITER 2 + ITER 5 가 동일 root cause
  (`ImportError: cannot import name 'expect' from 'playwright.async_api'`)
  로 fail → *LLM variance 가 아닌 결정적 결함* (Pytest Author stub 의 `expect`
  심볼 누락).
- **권장 후속**: Pytest Author 의 `playwright.async_api` stub 보강 (PR #100
  후보) 또는 `__getattr__` fallback 도입 → 5/5 도달 기대.

---

## 1. 5-iter 결과 매트릭스

| iter | PASS | elapsed | retry | attempt1 cat | attempt2 cat | fail root cause |
|---|---|---|---|---|---|---|
| 1 | ✅ | 16.83min | 1 | library | external_dependent | (retry flip 으로 PASS) |
| 2 | ❌ | 16.37min | 1 | external_dependent | library | `expect` ImportError → SyntaxError |
| 3 | ✅ | 8.64min | 0 | external_dependent | — | (first-shot PASS) |
| 4 | ✅ | 7.09min | 0 | external_dependent | — | (first-shot PASS) |
| 5 | ❌ | 12.41min | 1 | external_dependent | library | `expect` ImportError (assert-style) |

**총 elapsed**: 61.34min (≈ 평균 12.27min/iter, PR #97 의 13.06min 부합).

### DoD 항목별 PASS 비율 (5-iter)

| DoD key | PASS 회수 | ratio |
|---|---|---|
| 1_publish_success | 5/5 | 100% |
| 2_release_url_issued | 5/5 | 100% |
| 3_download_urls_count (>=1) | 5/5 | 100% |
| 4_is_draft | 5/5 | 100% |
| 5_executor_success | 5/5 | 100% |
| **6_qa_overall_passed** | **3/5** | **60%** ⚠️ |
| 7_qa_iterations_within_budget | 5/5 | 100% |

---

## 2. ITER 2 fail — 2-attempt 다른 fail mode

**Attempt 1** (`outputs/automate_workflow_20260511_102351/`):
- `scrape.py`: playwright 기반, `from playwright.async_api import (async_playwright, expect, TimeoutError)`
- `test_scrape.py`: 전체 `playwright.async_api` stub 등록 — but `expect` 심볼 누락
- pytest 결과: `errors=1` (collection error — `ImportError`)
- artifact_category=external_dependent (functional/robustness SKIPPED, code_qa active → FAIL)

```
ImportError: cannot import name 'expect' from 'playwright.async_api' (unknown location)
```

**Attempt 2** (`outputs/automate_workflow_20260511_103042/` — retry):
- LLM 이 `requests + bs4` 로 *완전히 다른 접근* 재생성 (artifact_category 가 library 로 flip)
- `test_scrape.py` line 52 에 SyntaxError — `@pytest.fixture(autouse=True)\n_no_gui = None` (decorator 위에 assignment)
- pytest 결과: `errors=1` (SyntaxError during collection)
- `'str' object has no attribute 'decode'` env 이슈로 functional+robustness 도 fail

→ BUDGET_EXHAUSTED, 6_qa_overall_passed=False.

## 3. ITER 5 fail — N-failure rule confirm

**Attempt 1** (`outputs/automate_workflow_20260511_105910/`):
- `scrape.py`: 다시 playwright + `expect` import
- `test_scrape.py`: defensive `try: import scrape; except ImportError as e: _scrape_import_error = e` 패턴
- `test_happy_module_imports` 가 `assert _scrape is not None` 으로 실패 표면화
- pytest 결과: `passed=16 failed=1 errors=0` (1 명시적 fail)

```
AssertionError: import 실패: cannot import name 'expect' from 'playwright.async_api' (unknown location)
```

**Attempt 2** (`outputs/automate_workflow_20260511_110535/` — retry):
- 동일 패턴 반복 → BUDGET_EXHAUSTED.

### N-failure 결론

| iter | attempt | root cause |
|---|---|---|
| 2 | 1 | `expect` ImportError (stub 누락) |
| 2 | 2 | SyntaxError (LLM 코드 결함) |
| 5 | 1 | `expect` ImportError (stub 누락) |
| 5 | 2 | `expect` ImportError (stub 누락) |

**ITER 2 attempt 1 + ITER 5 attempt 1 + ITER 5 attempt 2 = 3회 동일 root cause**
(`expect` 심볼 누락) → 프로젝트 memory 의 *Same N-failure rule* (동일 패턴
N회 실패 = 결정적 결함) 직접 trigger.

---

## 4. 분류기 retry trajectory 의 *방향 비대칭*

| iter | attempt 1 → attempt 2 | 효과 |
|---|---|---|
| 1 | library → external_dependent | **유익 flip** — robustness 가 SKIP 되어 PASS |
| 2 | external_dependent → library | **해로운 flip** — 더 많은 도구 활성 → 추가 fail 노출 |
| 5 | external_dependent → library | **해로운 flip** — 동일 ImportError 반복 + library 활성 도구 fail |

PR #95/#96 의 `external_dependent > CLI` priority fix 가 *first-shot* 분류는
안정화했지만, *retry* 시 LLM 이 코드 접근 (`playwright` ↔ `requests/bs4`) 을
재선택하면 분류가 *flip* 됨.

**해법 후보**:
- (안전) Sticky classification — 한 번 결정된 artifact_category 를 retry 에서도 고정
- (정밀) retry 시 LLM 에게 *동일 library* 사용 directive 추가 (PR #88 패턴 재사용)

---

## 5. 핵심 학습

### 5-1. Single-shot PASS 는 stability 가 아님

PR #97 의 1/1 PASS 는 "external_dependent + 첫 attempt + 운 좋은 stub 호환"
의 조합. 5-iter sample 에선 동일 trajectory (iter 3, 4) 가 2회 재현되지만,
LLM 이 `expect` 를 자유롭게 import 하는 경우 (iter 2, 5) 는 stub 미커버.

→ DoD 7/7 자체는 *측정 가능한 metric*, 하지만 *60% stability* 가 현실.

### 5-2. cross-agent contract gap 의 첫 식별

Engineer (PythonEngineer / WebScrapingSpecialist) 와 Pytest Author 가
*독립 LLM call* 로 생성하기 때문에 *암묵적 라이브러리 사용 패턴* 이 mismatch:
- Engineer 는 `expect()` 를 fluent assertion 으로 자연스럽게 채용
- Pytest Author 의 stub 은 `expect` 미열거

이는 PR #88 의 *import path* directive 가 cover 못한 *symbol-level* gap.

### 5-3. retry 가 *양날의 검*

- iter 1: retry 가 robustness fail 을 회피하기 위해 external_dependent 로 flip → PASS
- iter 2, 5: retry 가 다른 fail mode 노출 → FAIL

retry 가 stability 를 *증가* 시키지 않고, 단지 *fail 패턴 분포* 만 변경.
budget=1 의 의미는 "한 번 더 LLM 운빨" 에 가깝다.

---

## 6. 권장 후속 — 후보 O (신규)

**후보 O: Pytest Author stub 의 `__getattr__` fallback 도입**

```python
# 현재 (iter 2, 5 fail)
_sub = types.ModuleType("playwright.async_api")
_sub.async_playwright = _async_playwright
_sub.Browser = _StubBrowser
# ... 명시적 enumeration → expect 누락 → ImportError

# 후보 O 패치
class _PlaywrightSubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        # 모든 미정의 심볼은 no-op MagicMock 반환
        return _UNIVERSAL_NOOP
_sub = _PlaywrightSubModule("playwright.async_api")
```

또는 단순히 `_sub.expect = _async_noop_assertion`, `_sub.Selectors = object`, 등 자주 사용되는 심볼 추가.

**예상 효과**: 2/5 → 0/5 ImportError. 5/5 stability 도달 기대.

**작업 규모**: pytest_author.py backstory + qa_executor stub 보강 (예상 20~50 라인).

---

## 7. 후속 검증 계획

1. **PR #100 (가칭)** — `__getattr__` fallback stub 도입
2. **재 5-iter 검증** — `scripts/run_dod_stability.py --iterations 5`
3. **목표**: 5/5 PASS 도달
4. **부산물**: retry trajectory sticky classification (PR #101 후보)

본 보고서는 *측정 결과* 만 기록. 수정 작업은 별도 PR 로 분리.

---

## 8. 산출 정리

```
outputs/dod_stability_20260511_100350/
├── aggregate.json            (3-iter sweep)
├── iter_1.log ... iter_3.log

outputs/dod_stability_20260511_104920/
├── aggregate.json            (2-iter extension)
├── iter_1.log iter_2.log     (= iter 4, 5)

outputs/automate_workflow_20260511_*/   (각 attempt 의 code/build/release)
outputs/e2e_10th_verification_20260511_*/  (각 iter 의 summary.json)
```

`scripts/run_dod_stability.py` — 본 PR 신설 wrapper.
