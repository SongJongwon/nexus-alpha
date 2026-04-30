# 10차 E2E 검증 — 9차 시도 (PR #61 4 카테고리 시나리오 강제)

> **결과**: ⚠️ **부분 성공** — backstory 강화 효과 입증 (12 시나리오 4 카테고리 분포) BUT ```python``` 마커 누락으로 코드 추출 실패 → active 2/4 → **1/4 회귀**
> **실행 시각**: 2026-04-30 17:24:13 ~ 17:55:02 KST
> **Elapsed**: **1848.88s (30.81분)** — 8차 59.46분 대비 **-48%** (retry 0회)
> **상태**: SUCCESS (DoD 7/7 ALL PASSED, 표면 PASS), fatal 0
> **이전 보고서**: [e2e_10th_verification_post_pr59.md](./e2e_10th_verification_post_pr59.md) (7,8차)

---

## 📊 결과 요약

```
Elapsed: 1848.88s (30.81분)        ← 8차 59.46분 대비 -48% (retry 0)
Status: SUCCESS                    ← fatal 0
[QA] artifact_category=gui
[QA] [QA_LOOP PASS] retry=0/3, failed=0, skipped=3  ← skipped 1 증가!

DoD 7/7 ALL PASSED ✅ (표면)

QA 결과:
  code_qa     : SKIPPED (pytest exit=5, no tests collected) ⚠️ 8차 PASS → 9차 SKIPPED 회귀
  functional  : SKIPPED (GUI 부적합)
  gui         : ✅ PASS (2.45s)
  robustness  : SKIPPED (GUI 부적합)

→ active QA gating: 2/4 → 1/4 (gui만) ⚠️
```

---

## 🔍 결정적 진단

### 1. PR #61 backstory 강화는 *효과적*

`pytest_suite` 본문 (`14_pytest_suite.md`) 의 1단/3단 본문은 정확히 PR #61 의도대로 작성됨:

```
test_calculator.py 12 scenarios

## 테스트 스위트

### 1. 테스트 전략

test_calculator.py는 GUI 윈도우 미표시 정책 하에 calculator 모듈의 산술
평가 진입점을 직접 호출 검증한다. ... 12개 시나리오는 PR #61 최소치
(happy≥3 / edge≥4 / load≥3 / error≥1)를 모두 충족하도록
**happy 4 / edge 4 / load 3 / error 1로 균형 분포**된다. 결정론적
assertion(기댓값을 코드에 직접 박아넣기)을 일관 적용하며, 부동소수 비교만
1e-9 허용오차 내 절대차 검증으로 처리해 functional 정확성과 robustness
(부하·예외 전파)를 동시에 흡수한다.
```

LLM 이 PR #61 의 4 카테고리 분포 + 12 시나리오 + monkeypatch + 결정론적
assertion 모두 정확히 인지. **backstory 강화는 100% 효과적**.

### 2. 그러나 ```python``` fence 마커 누락 ⚠️

`test_code_block` 필드의 코드 본문이 ```python``` 마커 *없이* 직접 들어감:

```
### 2. 실 테스트 코드

# file: test_calculator.py
import sys
import pytest
from pathlib import Path

# 1) entry 모듈 임포트 경로 보장 (pytest standalone)
...
```

`_extract_code_blocks` 의 정규식:
```python
pattern = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
```

→ 마커 없는 raw 코드는 매치 실패 → `code/test_calculator.py` 미생성 →
pytest exit=5 → SKIPPED 회귀.

### 3. 근본 원인

PR #59 의 `PytestSuiteOutput.test_code_block` 필드 — schema description 에
"```python ... ``` 코드 블록" 명시했지만, LLM 이 *코드만* 출력하는 게 더
자연스럽다고 판단. `to_markdown()` 도 마커 자동 감싸기 안 함.

PR #61 에서 backstory + description + schema description 강화했지만,
*마커 자체는 LLM 의 자유* 였음. 9차 LLM 이 마커 없이 출력 → 회귀.

---

## 📈 6,7,8,9차 비교

| 지표 | 6차 (PR #55) | 7차 (PR #58) | 8차 (PR #59) | **9차 (PR #61)** |
|---|---|---|---|---|
| Elapsed | 26.90분 | 28.60분 | 59.46분 | **30.81분** |
| DoD 7/7 | ✅ | ✅ | ✅ | ✅ |
| Calculator.exe | ✅ 11.18MB | ✅ | ✅ | ✅ |
| `pytest_suite` 분량 | (없음) | 30 bytes | 6,102 bytes | **4,534 bytes** |
| 시나리오 수 | — | (Final Answer만) | 15 | **12** (4 카테고리 분포 ⭐) |
| ```python``` 마커 | — | ❌ | ✅ | ❌ ⚠️ |
| `test_*.py` 추출 | ❌ | ❌ | ✅ | ❌ |
| `code_qa` | SKIPPED | SKIPPED | **PASS (15 tests)** | **SKIPPED 회귀** ⚠️ |
| active QA | 1/4 | 1/4 | **2/4** | **1/4 회귀** |
| `retry_count` | 0 | 0 | 1 (자동 보정) | 0 |

---

## 🎓 학습

### 1. backstory 강화 효과 vs 마커 누락의 분리

PR #61 의도 (4 카테고리 분포 + 12 시나리오 + 분량 1200자+ 코드 60줄+) 는
*완벽 달성*. 그러나 `_extract_code_blocks` 에 *필요한* 마커 (```python```)
는 LLM 의 자유 영역으로 남아있어 회귀 가능.

→ schema description 의 *지시* 만으로는 fence 마커 보장 불가능. 필요한 것:
- (a) `to_markdown()` 에서 자동 감싸기 (마커 없을 때만)
- (b) backstory + description 에 마커 *예시 코드* 명시 (LLM 모방 유도)
- (c) 후처리: `_extract_code_blocks` 가 fence 없는 코드도 인식 (휴리스틱)

### 2. 빠른 시간 (30.81분, 8차 -48%) = 회귀의 신호

9차가 빠른 이유:
- LLM 이 schema 강제로 한 번에 정확한 4 필드 출력 (rescue/retry 0)
- `code_qa` 가 SKIPPED 됐으므로 qa_feedback_loop 가 retry 발동 안 함
- → *PASS 인 척* 하지만 실은 *active 검증 회피*

**시간 줄어듦 ≠ 더 좋아짐**. 8차 59.46분의 retry=1 자동 보정이 *진짜 검증*
의 비용. 9차 30.81분은 vacuous PASS 의 가벼움.

### 3. PR #61 강화의 절반 성공 — 본문은 OK, 추출은 실패

전형적 *부분 회귀* 패턴:
- ✅ 의도된 부분 성공 (4 카테고리 분포 명시)
- ❌ 의도하지 않은 회귀 (마커 누락 → 추출 실패)

→ 다음 PR (#63) 의 fix 는 작은 변경 (5~15분):
- 옵션 X: `to_markdown()` 마커 자동 감싸기
- 옵션 Y: schema description 마커 강제
- 옵션 Z: X + Y 동시

---

## 🚦 다음 액션 — 내일 1순위

**PR #63 옵션 Z (X + Y 동시)** ⭐:

1. `src/workflows/_schemas.py` — `PytestSuiteOutput.to_markdown()` 에서
   `test_code_block` 이 ```python``` 으로 시작 안 하면 자동 감싸기
2. `src/workflows/_schemas.py` — `test_code_block` 필드 description 에
   "**필드 본문에 ```python\\n...\\n``` fence 마커 *반드시* 포함**" 추가
3. `src/agents/qa/pytest_author.py` — backstory 의 "출력 규약" 섹션에
   ```python``` fence 강제 + 예시 코드 갱신
4. `src/workflows/analyze_and_implement.py` — `_build_pytest_author_task`
   description 에 동일 강화
5. 테스트 추가:
   - `to_markdown()` 자동 감싸기 (마커 없는 입력 → 마커 포함 출력)
   - schema description "fence" 키워드 검증
   - backstory ```python``` 예시 검증
6. 10차 E2E 10차 재실행 → active 2/4 회복 + 의미적 4/4 (12 시나리오 4
   카테고리) 동시 달성 검증

---

## 📁 산출 디렉터리

| 디렉터리 / 파일 | 내용 |
|---|---|
| `outputs/e2e_10th_verification_20260430_172413/summary.json` | 9차 풀 metadata |
| `outputs/_e2e_10th_9th_pr61_log.txt` | 9차 콘솔 로그 (3,371줄) |
| `outputs/workflow_20260430_172421/14_pytest_suite.md` | 9차 산출 (4,534 bytes, 마커 누락) |
| `outputs/workflow_20260430_172421/code/calculator.py` | entry 만 (test_*.py 미생성) |

---

*"9차: backstory 강화 100% 효과 (4 카테고리 12 시나리오 분포 정확) BUT*
*```python``` fence 마커 누락으로 추출 실패 → active 2/4 → 1/4 회귀.*
*내일 PR #63 옵션 Z (자동 감싸기 + description 강제) 로 회복 + 의미적 4/4 도달."*
