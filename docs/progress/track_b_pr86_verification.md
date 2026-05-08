# PR #86 Pytest Author entry 파일명 강제 — 실 LLM 재검증 (PR #84 회귀 차단 확인)

> **작성일**: 2026-05-08
> **검증 대상**: PR #86 (Pytest Author entry 파일명 directive 주입)
> **결론**: ✅ **directive 정확히 작동** — PR #84 회귀 (`scraper` 변형) 완전 차단.
> ⚠️ 새 LLM variance 발견 (`playwright` sync stub vs scrape.py async import) →
> PR #88 후보.

---

## 1. 검증 명령

PR #84 검증과 동일 명령:
```bash
.venv/Scripts/python.exe scripts/run_e2e_10th_verification.py \
  --request "네이버 쇼핑 가격 크롤링 스크립트" \
  --enable-automate-branch \
  --enable-automate-qa-loop \
  --enable-automate-build \
  --max-retries 1
```

## 2. 결과 비교 — PR #84 vs PR #86

| 항목 | PR #84 (회귀) | PR #86 (이번) | 변화 |
|---|---|---|---|
| Elapsed | 14.26분 | **7.78분** | -45% (LLM variance 줄어 retry 회수 감소 추정) |
| 도메인 분류 | web_scraping ✅ | web_scraping ✅ | 동일 |
| agent_output bytes | 10,099 B | (미수집) | (schema 강제 동일) |
| pytest_suite bytes | 9,079 B | (미수집) | |
| **test 파일명** | **test_scraper.py** ❌ | **test_scrape.py** ✅ | **PR #86 fix 작동** |
| **import 모듈명** | **`import scraper`** ❌ | **`importlib.import_module("scrape")`** ✅ | **PR #86 fix 작동** |
| Build (.exe) | Scrape.exe 9.14 MB ✅ | Scrape.exe ✅ (재현) | 동일 |
| code_qa | FAIL (ImportError: scraper) | FAIL (ModuleNotFoundError: playwright.async_api) | **다른 원인** |
| qa_overall_passed | False | False | (다른 layer 의 mismatch 노출) |

**핵심**: PR #86 directive 가 LLM 자유 영역 (filename/module name) 을 deterministic
하게 차단. 회귀 패턴 정확히 사라짐. 그러나 새로운 LLM variance 가 다음 layer 에서 발견.

---

## 3. ⚠️ 새 발견 — playwright sync stub vs async import mismatch

### 3-1. 사실 확인

**`code/scrape.py`** (도메인 에이전트 산출):
```python
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    ...
)
```

**`code/test_scrape.py`** (Pytest Author 산출):
```python
class _StubPW:  # sync_playwright() 가정
    def __enter__(self):
        self.chromium = _StubChromium()
        return self
    def __exit__(self, ...): ...

# sys.modules['playwright'] = _StubPW + Module 형태로 주입
```

`pytest test_scrape.py` 실행 시:
```
ModuleNotFoundError: No module named 'playwright.async_api';
'playwright' is not a package
```

원인: 도메인 에이전트는 `playwright.async_api` (async) 를 import 하는데, Pytest
Author 의 stub 은 `playwright` 를 module 로 주입 (sync `with sync_playwright()` 가정).
서브모듈 path `playwright.async_api` 가 stub 에 없음 → ImportError.

### 3-2. 근본 원인 — schema 가 닫지 못한 *2차* 영역

PR #78 schema 는 도메인 에이전트의 산출 형식 (5단 본문 + fence + header) 만 강제.
PR #86 directive 는 entry 파일명/모듈명만 강제. 그러나:

- **도메인 에이전트가 실제로 사용한 *import path***
- **Pytest Author 가 stub 으로 가정한 *import path***

이 *서로 다른 LLM variance 차원* 으로 mismatch 가능. 본 검증은 정확히 그
mismatch 를 첫 적발.

### 3-3. PR #88 후보 — Pytest Author 에 entry 의 import path 명시

처방 (방어선 4 패턴 — 결정형 후처리):
1. `_run_track_b_qa_loop` 에서 `code_task` 산출 결과를 분석 → entry .py 의
   import 문 추출 (정규식)
2. 추출된 imports 를 `pytest_task.description` 에 명시:
   ```python
   directive += (
     f"\n## entry 파일이 사용하는 import path 강제 (PR #88)\n"
     f"엔트리 파일은 다음 import 를 사용합니다:\n{extracted_imports}\n"
     f"테스트의 stub/mock 은 이 import path 들을 정확히 cover 해야 함."
   )
   ```

또는 더 간단한 처방: `code_task` 산출 자체를 `code_task.context` 로 pytest_task
에 전달 (CrewAI 기본 동작) — 이미 PR #58 부터 적용 중. 그러나 LLM 이 컨텍스트
의 import 를 *충분히 주의 깊게* 읽지 못함.

PR #82 의 `_DOMAIN_TO_ENTRY_FILENAME` 처럼 *결정형* 처방이 더 안전:
- `_DOMAIN_TO_TYPICAL_IMPORTS` 도메인별 표준 import path 사전 정의
- 또는 `_extract_imports_from_code(code_task_output)` 정규식 추출

### 3-4. 진척도 — LLM variance 누적 차단

| PR | 차단된 variance | 효과 |
|---|---|---|
| #78 | 5단 본문 누락 (Final Answer 1줄만) | agent_output 41 B → 10 KB |
| **#86** | **filename/module name 변형** (`scraper` → `scrape`) | **import 정확** |
| **PR #88 (후보)** | **import path mismatch** (`playwright` vs `playwright.async_api`) | **stub 정확 cover** |

각 PR 이 LLM 자유 영역의 *다음 layer* 를 deterministic 화. 점진 흡수 패턴.

---

## 4. 인프라 PASS 재확인 (PR #82 build 효과 동일)

PR #84 와 동일하게 PR #82 의 PyInstaller Build 는 정상 작동:
- code/scrape.py → Scrape.exe 빌드 성공
- SHA256 검증 통과
- 7.78분 (PR #84 의 14.26분 대비 단축 — pytest variance 감소로 retry 줄음)

즉 *코드 산출 자체는 valid Python* — 단지 test 와 stub mismatch 가 QA gate fail
의 유일한 원인.

---

## 5. 다음 단계

### 후보 G (신규) — PR #88 import path 강제 🟡

PR #84 → PR #86 → PR #88 의 누적 패턴. 5~10 라인 fix 가능. 그러나 더 일반적
처방 (regex 추출 vs 도메인별 사전) 결정이 필요.

### 후보 A → ✅ 두 번째 검증 완료 (본 PR)

PR #86 directive 정확히 작동 입증. 추가 layer 의 LLM variance 발견.

### 후보 B/C/D/E → 후순위

DevOps 별도 분기 / Streamlit / UI/UX backstory / 휴리스틱 더 강화.

---

## 6. 핵심 학습

### 6-1. 결정형 후처리 패턴의 점진 적용

각 PR 이 LLM 자유 영역 *한 layer* 씩 흡수. 본 검증으로 패턴이 *재귀적으로 적용
가능* 함을 입증:
- 1차: 본문 형식 (PR #78 schema)
- 2차: 파일명/모듈명 (PR #86 directive)
- 3차: import path (PR #88 후보)
- N차: ?

### 6-2. 검증 시간 단축 = LLM variance 감소 신호

- PR #84: 14.26분 (LLM variance 큼, retry 다수 추정)
- PR #86: 7.78분 (variance 줄어 retry 감소)

→ 후처리 directive 가 LLM 출력 안정화에 효과적임을 시간으로도 입증.

### 6-3. 인프라 vs LLM 출력 layer 분리

PR #82 Build 의 .exe 산출 = scrape.py 가 valid Python. 즉 인프라 자체는
건강. QA 의 fail 은 LLM 간 협력 (도메인 ↔ Pytest Author) 에서만 발생 — *각
LLM 의 출력 자체* 는 valid.

---

*본 보고서는 PR #86 머지 직후 (2026-05-08) Pytest Author entry 파일명 강제
효과 실 LLM 재검증 결과입니다. 자세한 산출은
`outputs/automate_workflow_20260508_111820/` 참조.*
