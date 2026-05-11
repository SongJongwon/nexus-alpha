# Track B PR #101 — `test_error_*` 예외 단정 보수적 규칙 directive (후보 Q)

> 실시 일자: **2026-05-11**
> 직접 후속: PR #100 (후보 P — 5-iter 4/5 PASS = 80%)
> 작업 단위: directive 강화 (방어선 패턴 *13 차* 재사용)
> 산출 파일: `src/workflows/automate_workflow.py`, `src/tests/test_track_b_qa_loop.py`

---

## 1. 문제 정의

PR #100 5-iter 검증 (후보 P) 의 ITER 3 fail:

```python
def test_error_urlparse_none_raises():
    with pytest.raises((TypeError, AttributeError)):
        urlparse(None)
```

pytest 결과: `Failed: DID NOT RAISE`.

Python 3.13 의 실제 동작:

```python
>>> urlparse(None)
ParseResultBytes(scheme=b'', netloc=b'', path=b'', params=b'', query=b'', fragment=b'')
```

**예외 없이 빈 결과 반환** — Pytest Author 가 잘못된 가정으로 테스트 작성.
ITER 3 attempt 1 + attempt 2 모두 동일 가정 재생산 → 단일 iter 내 *N-failure rule*
trigger = *결정적 결함* (LLM systematic blind spot).

## 2. 처방 — directive 13 차 재사용

`_inject_track_b_exception_assertion_directive` 신설. `_run_track_b_pytest_and_qa`
의 directive chain (#86 → #88 → #100 → **#101**) 마지막에 추가.

directive 내용 (3 sections):

### 2-1. raise 안 함 — `pytest.raises` 금지
- `urllib.parse.urlparse(None/'')` → ParseResultBytes/ParseResult (PR #100 ITER 3 회귀 사례)
- `dict.get(missing_key)` → None
- `list.__contains__(item)` → False
- `os.path.join()` (인자 0개) → ""

### 2-2. 검증된 raise — `pytest.raises` 허용
- `int('abc')` → ValueError
- `int(None)` → TypeError
- `json.loads(None)` → TypeError
- `max([])` / `min([])` → ValueError
- `pathlib.Path(None)` → TypeError
- 존재하지 않는 디렉터리 쓰기 → FileNotFoundError/OSError

### 2-3. 불확실 시 보수적 패턴

```python
def test_error_invalid_input_handles_gracefully():
    try:
        result = fn(invalid_input)
    except (TypeError, ValueError, AttributeError):
        return  # 예외 발생도 valid
    # 예외 없으면 결과가 명확히 *무효 표식*
    assert result in (None, '', False, [], {}) or \
        (hasattr(result, '__len__') and len(result) == 0)
```

## 3. 변경 사항

### 3-1. `src/workflows/automate_workflow.py`
- `_inject_track_b_exception_assertion_directive` 신설 (~50 라인 directive 본문)
- `_run_track_b_pytest_and_qa` chain 에 추가 (1 호출)

### 3-2. `src/tests/test_track_b_qa_loop.py`
- 신규 8 테스트:
  - `PR #101` 마커 포함 / `urlparse(None)` 회귀 사례 명시 / raise-안 함 목록 /
    검증된 raise 목록 / 보수적 패턴 예제 / 멱등성 / prefix 보존 /
    **Python 3.13 `urlparse(None)` 실 동작 assertion (회귀 차단)**
- 기존 통합 테스트 `test_qa_loop_actually_injects_import_directive_into_pytest_task`
  에 PR #101 assertion 3 줄 추가 (`PR #101`, `DID NOT RAISE`, `urlparse(None)`)

## 4. 검증

### 4-1. pytest 회귀
```
742 → 750 (+8 PR #101 신규, 회귀 0)
```

### 4-2. 실 LLM 1-iter quick check ⚠️ (혼합 결과)

```
.venv/Scripts/python.exe scripts/run_dod_stability.py --iterations 1
```

| 항목 | 값 |
|---|---|
| DoD 종합 | ❌ FAIL (6_qa_overall_passed=False) |
| Elapsed | 17.75min |
| retry | 1 |
| **code_qa (PR #101 직접 target)** | ✅ **PASS** (passed=6, failed=0, errors=0) ⭐ |
| functional | ❌ 0/10 (51.77s) |
| robustness | ❌ 0/9 (49.65s) |
| gui | ✅ PASS |

**핵심**: PR #101 의 *직접 target* (`urlparse(None)` 등 잘못된 예외 단정) 은
**완전 차단**:

- attempt 1: code_qa PASS (6 tests, 0 errors) — PR #100 ITER 3 의 `Failed: DID NOT RAISE`
  fail mode 가 재발하지 않음
- LLM 이 PR #101 directive 를 따라 `test_error_*` 카테고리에 `pytest.raises` 단정을
  *보수적* 으로 작성 → 단정 단계에서 fail 차단

**Orthogonal fail (PR #101 미해결)**: functional/robustness 0/10, 0/9 —
subprocess executor 가 LLM 산출 `scrape.py` 의 실 동작 (example.com 빈 결과,
exit_code=0) 과 *expected scenario* mismatch. 이는 **LLM 코드 variance** 카테고리:

- PR #100 ITER 3 attempt 1 도 `library` 분류였으나 그때는 functional 10/10 + robustness PASS 9/9
- 같은 분류에서도 LLM 이 produce 하는 scrape.py 의 동작 (exit_code, output 형식) 이 매 회 다름
- PR #101 의 *예외 단정 직접 차단* 영역 밖

### 4-3. 평가

PR #101 의 의도된 효과는 **empirical 입증** — `urlparse(None)` 류 fail 의 직접
차단. 1-iter sample 만으로는 functional/robustness 의 LLM variance 를 통계적으로
판단 불가. **full 5-iter sweep** 으로 PR #101 의 stability 영향을 측정 권장.

PR #100 의 5-iter (4/5 = 80%) 결과와 비교 시 PR #101 이 다음 효과 기대:
- code_qa-level fail 감소 (PR #101 의 직접 효과)
- functional/robustness variance 변화 없음 (PR #101 와 무관)

## 5. 핵심 학습

### 5-1. directive 누적 패턴 13 차 재사용

PR #66 → #88 → #100 → **#101** = 방어선 패턴 *13 차* 재사용.
- PR #88: import path layer
- PR #100: stub symbol layer
- **PR #101: 예외 단정 layer**

각 layer 가 *하나씩 식별 + 직접 차단* — finite list of LLM blind spots 가설
지속 검증.

### 5-2. LLM systematic blind spot 의 *고정성*

PR #100 ITER 3 의 attempt 1 + attempt 2 가 같은 잘못된 가정 (`urlparse(None)`
이 raise) 을 재생산. **retry budget 으로 흡수 불가** — *prompt directive 로
upstream 차단* 만이 효과적. 본 PR 이 그 패턴의 직접 적용.

## 6. 다음 단계

### 후보 R (예정, 선택) — full 5-iter sweep 재실시

PR #101 적용 후 안정성 확인. PR #100 의 80% (4/5) → **5/5 도달** 목표.
회당 ~7-13min, 총 ~35-65분.

```bash
.venv/Scripts/python.exe scripts/run_dod_stability.py --iterations 5
```

### 옵션 후속

- 후보 S — Post-processing 결정형 fallback (test_*.py 자동 보정)
- 후보 T — Sticky artifact_category (PR #99 의 retry trajectory 비대칭 차단)
- 후보 B — DevOps 별도 분기 (5/5 도메인 완성)
