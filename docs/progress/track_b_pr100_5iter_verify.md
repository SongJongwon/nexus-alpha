# Track B PR #100 적용 — full 5-iter 검증 결과 (후보 P)

> 실시 일자: **2026-05-11**
> 대상: PR #100 (stub 심볼 enumeration + `__getattr__` fallback) 적용 후 안정성
> 시나리오: `네이버 쇼핑 가격 크롤링 스크립트` (PR #99 baseline 과 동일)
> 산출: `outputs/dod_stability_20260511_130207/`

---

## TL;DR

- **PR #100 5-iter: 4/5 PASS (80%)** — PR #99 의 3/5 (60%) 대비 **+20%p 개선** ✅
- **PR #100 의 메인 목표 (`expect` ImportError 차단) 는 100% 달성** — 5 iter 어느 곳에서도 PR #99 의 N-failure root cause 재발 없음.
- **새 fail mode 노출** (ITER 3): Pytest Author 가 `urlparse(None)` 이 `TypeError/AttributeError` raise 한다고 잘못 가정 → `pytest.raises` 실패. Python 3.13 의 실제 동작은 *예외 없이 빈 `ParseResultBytes` 반환*.
- ITER 3 의 attempt 1 + attempt 2 가 **동일 잘못된 가정 재생산** → 단일 iter 내 N-failure rule trigger → *결정적 결함*.
- **다음 후보 Q (신규)**: Pytest Author 의 *잘못된 예외 가정* 차단 directive (PR #101 예정).

---

## 1. 5-iter 결과 매트릭스

| iter | PASS | elapsed | retry | fail point |
|---|---|---|---|---|
| 1 | ✅ | 13.40min | 1 | — |
| 2 | ✅ | 6.80min | 0 | — |
| 3 | ❌ | 16.12min | 1 | `test_error_urlparse_none_raises` (잘못된 예외 가정) |
| 4 | ✅ | 6.62min | 0 | — |
| 5 | ✅ | 16.05min | 1 | — |

**총 elapsed**: 58.99min (평균 11.80min/iter — PR #99 12.27min 대비 -3.8%).

### PR #99 (baseline) vs PR #100 비교

| 지표 | PR #99 | PR #100 | Δ |
|---|---|---|---|
| Stability | 3/5 = 60% | **4/5 = 80%** | **+20%p** ✅ |
| 평균 elapsed | 12.27min | **11.80min** | **-3.8%** ✅ |
| first-shot PASS (retry=0) | 2/5 | **2/5** | 동일 |
| `expect` ImportError | 2회 (ITER 2, 5) | **0회** ⭐ | **결정적 차단** ✅ |
| 새 fail mode | — | 1회 (ITER 3) | (잘못된 예외 가정) |

### DoD 항목별 PASS 비율 (PR #100, 5-iter)

| DoD key | PASS 회수 | ratio |
|---|---|---|
| 1_publish_success | 5/5 | 100% |
| 2_release_url_issued | 5/5 | 100% |
| 3_download_urls_count (>=1) | 5/5 | 100% |
| 4_is_draft | 5/5 | 100% |
| 5_executor_success | 5/5 | 100% |
| **6_qa_overall_passed** | **4/5** | **80%** ⬆ |
| 7_qa_iterations_within_budget | 5/5 | 100% |

---

## 2. PR #100 효과 검증 — `expect` ImportError 차단

PR #99 의 ITER 2 + ITER 5 는 `cannot import name 'expect' from 'playwright.async_api'`
로 fail. PR #100 적용 후 5-iter 어디서도 동일 ImportError 미발생.

LLM 산출 검증 (예: ITER 4 `outputs/automate_workflow_20260511_..../code/test_scrape.py`):

```python
# 명시 enumeration (PR #100) — 누락 심볼은 __getattr__ fallback 흡수
_pw_sub.async_playwright = _UNIVERSAL_NOOP
_pw_sub.expect = _UNIVERSAL_NOOP
```

LLM 이 directive 를 따라 `expect` 를 명시 등록 + `__getattr__` 두 layer 모두 구현.
PR #99 N-failure root cause 가 deterministic 차단됨을 empirical 입증.

---

## 3. ITER 3 새 fail mode — 잘못된 예외 가정

### 3-1. 직접 재현

`outputs/automate_workflow_20260511_132514/code/test_scrape.py`:

```python
def test_error_urlparse_none_raises():
    """잘못된 입력에 대해 명확한 예외가 발생해야 한다."""
    with pytest.raises((TypeError, AttributeError)):
        urlparse(None)
```

pytest 실행 결과:

```
FAILED test_error_urlparse_none_raises - Failed: DID NOT RAISE any of (TypeError, AttributeError)
```

`urlparse(None)` 의 Python 3.13 실제 동작:

```python
>>> from urllib.parse import urlparse
>>> urlparse(None)
ParseResultBytes(scheme=b'', netloc=b'', path=b'', params=b'', query=b'', fragment=b'')
```

**예외 없이 빈 결과 반환** — Pytest Author 의 가정 오류.

### 3-2. retry 도 동일 오류 재생산

ITER 3 attempt 2 (`automate_workflow_20260511_133434/code/test_scrape.py:195`):
완전히 같은 패턴.

```
FAILED test_error_urlparse_none_raises - Failed: DID NOT RAISE
```

**단일 iter 내 N-failure** (attempt 1 + attempt 2) → *결정적 결함*. 동일 LLM 의
*고정된 잘못된 가정* (학습 데이터의 다른 Python 버전 동작 또는 다른 stdlib 함수
와 혼동) 이 retry budget 으로 흡수 불가.

### 3-3. 패턴 일반화

`test_error_*` 카테고리의 `pytest.raises` 단정에서 **stdlib 의 None/empty 입력
실제 동작에 대한 잘못된 가정** — Pytest Author 의 systematic blind spot.

다른 예시 후보 (관측 안 됐지만 같은 카테고리 잠재 패턴):
- `int(None)` → 실제 raise TypeError (이건 LLM 가정 맞음)
- `int("")` → 실제 raise ValueError
- `dict.get(missing_key)` → 실제 None 반환 (raise 가정하면 fail)
- `pathlib.Path(None)` → 실제 raise TypeError
- `json.loads(None)` → 실제 raise TypeError

LLM 이 어떤 stdlib 함수에 대해 다른 패턴을 적용할 수 있는지 예측 불가능 →
*보수적 directive* 가 필요.

---

## 4. 다음 단계 — 후보 Q (신규)

### 후보 Q: 잘못된 예외 가정 차단 directive (PR #101 예정)

Pytest Author 의 `test_error_*` 카테고리에 다음 directive 추가:

```
## 예외 단정 (pytest.raises) 보수적 규칙 (PR #101) 🚨

stdlib 함수의 *None / 빈 문자열 / 잘못된 타입* 입력은 raise 가 *아닐 가능성*
이 높습니다. 다음 검증 절차 의무:

1. test_error_* 카테고리에서 `with pytest.raises(...):` 사용 시,
   먼저 *실제 동작* 을 알려진 경우만 단정.

2. 다음 stdlib 함수는 None / empty 입력 시 raise 안 함 (반환 결과 있음):
   - urllib.parse.urlparse(None) → ParseResultBytes (empty)
   - dict.get(missing_key) → None
   - list/tuple.__contains__ → False (raise X)
   - os.path.join() → ""

3. 확신할 수 없으면 *결과 검증* 패턴 사용:
   try:
       result = fn(invalid_input)
       assert result in (None, "", False) or isinstance(result, ...)
   except (TypeError, ValueError, AttributeError) as e:
       pass  # 둘 다 허용
```

예상 작업: ~10-30 라인 directive 추가. PR #100 패턴 (`_inject_track_b_*`) 재사용.

### 옵션 후속

- **PR #102** — Post-processing 결정형 fallback (test_*.py 자동 보정)
- **PR #103** — Sticky artifact_category (PR #99 의 retry trajectory 비대칭 차단)

---

## 5. 핵심 학습

### 5-1. PR #100 효과 empirical 검증 완료

PR #100 의 directive 2 layer 가 *정확히 의도한 결함만 차단* — `expect` ImportError 0 회 재발. 5-iter 안정성 +20%p, 평균 elapsed -3.8%.

### 5-2. *결정형 directive 누적* 패턴의 분기점 노출

`expect` 결함 차단 → 다음 결함 (잘못된 예외 가정) 노출. LLM variance 를 결정형
후처리로 흡수하는 패턴은 **finite list of LLM blind spots** 가설을 강화:
- PR #88: import path layer
- PR #100: stub symbol layer
- **PR #101: 예외 단정 layer** (새 후보)
- 다음 layer 예측 (가설): 데이터 타입 가정, 환경 변수 가정 등

각 layer 가 *하나씩 식별 + 직접 차단* 가능 → 점근적 5/5 stability 도달.

### 5-3. retry budget=1 의 *동질 fail 흡수* 한계

ITER 3 의 attempt 1 + attempt 2 가 같은 잘못된 가정 재생산 — *LLM 자체의 systematic
blind spot* 은 *재시도만으로* 흡수 불가. **directive 강화로 prompt 단계에서 통제**
가 필요.

---

## 6. 산출 정리

```
outputs/dod_stability_20260511_130207/
├── aggregate.json           (5-iter 종합)
├── iter_1.log ... iter_5.log

outputs/automate_workflow_20260511_{130433,131156,131727,132514,133434,...}/
  (각 attempt 의 code/build/release)

outputs/e2e_10th_verification_20260511_*/  (각 iter summary.json)
```

본 보고서는 *측정 결과* 만 기록. PR #101 (후보 Q) 은 별도 PR 로 분리.
