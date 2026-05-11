# Track B PR #100 — stub 심볼 enumeration + `__getattr__` fallback directive (후보 O)

> 실시 일자: **2026-05-11**
> 직접 후속: PR #99 (후보 N — 5-iter 검증 = 3/5 PASS)
> 작업 단위: directive enhancement (방어선 패턴 *12 차* 재사용)
> 산출 파일: `src/workflows/automate_workflow.py`, `src/tests/test_track_b_qa_loop.py`

---

## 1. 문제 정의

PR #99 의 5-iter 안정성 검증 결과:
- 인프라 5 항목: 5/5 = 100% 안정
- 6_qa_overall_passed: **3/5 = 60%** (variance)
- **ITER 2 + 5 동일 root cause**:
  ```
  ImportError: cannot import name 'expect' from 'playwright.async_api' (unknown location)
  ```

이는 *Same N-failure rule* trigger — LLM variance 가 아닌 *결정적 결함*:
Pytest Author 가 stub 에 `expect` 등 일부 심볼을 enumerate 하지 않음.
PR #88 의 `_inject_track_b_import_directive` 는 import *라인* 만 강제 →
LLM 이 어떤 *심볼* 을 stub 에 등록해야 하는지 암묵적 추론.

## 2. 처방 — directive 2 layer

### Layer 1: 심볼 enumeration

`from playwright.async_api import (async_playwright, expect, TimeoutError as PWT)`
→ `{playwright.async_api: [async_playwright, expect, TimeoutError]}` 추출 →
directive 본문에 명시:

```
- ``playwright.async_api``: ``async_playwright``, ``expect``, ``TimeoutError``
```

### Layer 2: `__getattr__` fallback

LLM 이 enumerate 누락해도 흡수할 수 있도록 `__getattr__` 패턴 의무화:

```python
class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return _UNIVERSAL_NOOP

class _Noop:
    def __call__(self, *a, **k): return self
    def __getattr__(self, name): ...
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def __await__(self):
        import asyncio
        return asyncio.sleep(0).__await__()
_UNIVERSAL_NOOP = _Noop()
```

두 layer 모두 directive 본문에 명시 → LLM 의 *명시 enumeration* + *fallback*
두 방향 모두 cover.

## 3. 변경 사항

### 3-1. `src/workflows/automate_workflow.py`

| 신규 / 변경 | 함수 | 효과 |
|---|---|---|
| 신규 | `_extract_imported_symbols_from_track_b_code_block` | `from X import a, b as c, (...)` → `{X: [a, b]}` |
| 신규 | `_flatten_multiline_imports` | 괄호 멀티라인 import 한 줄 결합 |
| 신규 | `_inject_track_b_stub_getattr_directive` | PR #100 directive 주입 |
| 변경 | `_run_track_b_pytest_and_qa` | directive chain 에 PR #100 추가 |

파싱 규칙:
- `from X import a, b` → `{X: [a, b]}`
- `from X import a as A` → `{X: [a]}` (alias 제거)
- `from X import (\n  a,\n  b,\n)` → 멀티라인도 동일 매핑
- `import X` (from 없음) → 매핑 제외
- `from X import *` → 매핑 제외

### 3-2. `src/tests/test_track_b_qa_loop.py`

신규 15 테스트:
- `_extract_imported_symbols_from_track_b_code_block` 9 케이스
  - inline / alias 제거 / 멀티라인 괄호 / 다중 모듈 / dedup / plain import 제외 /
    빈 입력 / 별표 import skip / **PR #99 ITER 2 실 payload regression**
- `_inject_track_b_stub_getattr_directive` 6 케이스
  - enumeration / `__getattr__` 템플릿 / 빈 매핑 skip / 심볼 truncate /
    모듈 truncate / 멱등성

기존 통합 테스트 (`test_qa_loop_actually_injects_import_directive_into_pytest_task`)
에 PR #100 assertion 3 줄 추가 (PR #100, `__getattr__`, `_UNIVERSAL_NOOP`).

### 3-3. 회귀 차단 테스트

`test_extract_symbols_pr99_iter2_real_payload`:
- ITER 2 attempt 1 의 실 `scrape.py:20` import 패턴 그대로 입력
- `expect` 가 추출됨을 assert → PR #99 N-failure 재발 차단

## 4. 검증

### 4-1. pytest 회귀

```
$ .venv/Scripts/pytest.exe -q --no-header
... 742 passed, 1327 warnings in 26.14s
```

- 727 → **742** (+15 PR #100 신규)
- 회귀 0
- 기존 `_inject_track_b_import_directive` 테스트 유지

### 4-2. 실 LLM 1-iter quick check ✅

```
.venv/Scripts/python.exe scripts/run_dod_stability.py --iterations 1
```

| 항목 | 값 |
|---|---|
| 결과 | **DoD 7/7 ALL PASSED** ⭐⭐⭐ |
| Elapsed | **6.41min** (PR #99 5-iter 평균 12.27min 대비 -47%) |
| retry | **0** (first-attempt PASS) |
| artifact_category | external_dependent |
| 산출 | `outputs/automate_workflow_20260511_123613/` |

**directive 가 실 LLM 산출에 100% 반영 검증**:

`outputs/automate_workflow_20260511_123613/code/test_scrape.py`:

```python
class _Noop:
    def __call__(self, *a, **k): return self
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    ...
_UNIVERSAL_NOOP = _Noop()

class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _UNIVERSAL_NOOP

# --- playwright stub: 루트 + async_api 서브모듈 모두 등록 (PR #88·#100) ---
_pw_root = _StubModule("playwright")
_pw_sub = _StubModule("playwright.async_api")
...
# 명시 enumeration (PR #100) — 누락 심볼은 __getattr__ fallback 흡수
_pw_sub.async_playwright = _UNIVERSAL_NOOP
_pw_sub.expect = _UNIVERSAL_NOOP
```

LLM 이 **PR #88·#100** 마커까지 자율적으로 주석에 추가 → directive 통제력 강함.
ITER 2/5 fail 의 `expect` 심볼이 명시 + fallback 두 layer 로 흡수.

`scrape.py:27` 에 `expect` import + `:72` 에 `await expect(card.first).to_be_visible(...)`
호출도 정상 — Engineer 산출 패턴 그대로 유지하면서 Pytest Author 가 cover.

## 5. 다음 단계

### A. 본 PR 머지 후 (다음 세션)

`scripts/run_dod_stability.py --iterations 5` 로 *full 5-iter sweep* 실시.
PR #99 의 3/5 → **5/5 도달** 목표.

### B. 만약 5-iter 가 여전히 variance 발생

**옵션 B1 — Post-processing 결정형 fallback (PR #101 후보)**:
- Pytest Author 의 산출 `test_*.py` 를 파싱
- `_sub = types.ModuleType("playwright.async_api")` 발견 시 자동으로
  `__getattr__` injection
- 가장 강력하지만 파싱 복잡도 증가

**옵션 B2 — Sticky artifact_category (PR #102 후보)**:
- retry 시 첫 attempt 의 `artifact_category` 고정
- PR #99 의 retry trajectory 양방향 비대칭 차단

## 6. 핵심 학습 누적

PR #66 → PR #88 → PR #100 으로 *directive 강화 패턴* 3 차 재사용:
- PR #66: file header 자동 마커 (`# file: <name>`)
- PR #88: import path 강제 (sys.modules 서브모듈 등록)
- **PR #100: stub 심볼 enumeration + `__getattr__` fallback**

각 PR 모두 *LLM 자유 영역의 빈틈을 결정형 directive 로 점진 흡수*. 본 PR 은
**Same N-failure rule** 가 식별한 결함의 직접 fix → empirical 효과 검증.

방어선 패턴 *12 차* 재사용 누적.
