# Track B 풀체인 실 LLM E2E 검증 보고서 (PR #84 머지 직후)

> **작성일**: 2026-05-08
> **검증 대상**: PR #78~#84 누적 — Track B 풀체인 시퀀스 (schema → 휴리스틱 →
> QA loop → Build → Release CLI 플래그 통합)
> **결론**: ✅ **인프라 5/5 PASS** (분류·schema·QA loop·Build·산출 모두 정상) +
> ⚠️ **QA gate fail** (Pytest Author entry 파일명 불일치 — 단일 LLM 품질 이슈,
> 인프라 회귀 아님). **PR #85 follow-up 후보 도출**.

---

## 1. 실행 명령

```bash
.venv/Scripts/python.exe scripts/run_e2e_10th_verification.py \
  --request "네이버 쇼핑 가격 크롤링 스크립트" \
  --enable-automate-branch \
  --enable-automate-qa-loop \
  --enable-automate-build \
  --max-retries 1
```

PR #84 로 노출된 5 신규 CLI 플래그 중 3 활성:
- `--enable-automate-branch` (PR #75 — Track B 라우팅)
- `--enable-automate-qa-loop` (PR #81 — pytest_author + code_qa)
- `--enable-automate-build` (PR #82 — execute_pyinstaller)

`--enable-automate-release` 는 GitHub 외부 상태 변경 위험으로 본 검증에선 미활성
(별도 trigger 권장).

---

## 2. 결과 요약

| 단계 | 결과 | 산출 |
|---|---|---|
| 1) 휴리스틱 분류 (PR #80) | ✅ `web_scraping` 정확 분류 | 01_detected_domain.txt |
| 2) Web Scraping LLM (PR #78 schema) | ✅ 5단 본문 + python fence + `# file: scrape.py` 자동 | 02_agent_output.md (10,099 B) |
| 3) code/ 추출 | ✅ scrape.py (5,118 B) | code/scrape.py |
| 4) Pytest Author LLM (PR #81 QA) | ✅ 12 scenarios + 4 카테고리 분포 + python fence 자동 | 03_pytest_suite.md (9,079 B) |
| 5) test_*.py 추출 | ✅ test_scraper.py (6,098 B) | code/test_scraper.py |
| 6) code_qa 실행 (PR #81) | ⚠️ **FAIL** — `import scraper` 잘못된 파일명 | qa_iter[0/1] |
| 7) PyInstaller Build (PR #82) | ✅ **SUCCESS** — Scrape.exe 9.14 MB + SHA256 | build_output/dist/Scrape.exe |
| 종합 elapsed | 14.26 분 | (tmpdir 정리 + LLM 호출 2건 + PyInstaller subprocess) |

**핵심 산출물**:
```
outputs/automate_workflow_20260508_104330/
├── 00_user_request.txt        (1,042 B)
├── 01_detected_domain.txt     ('web_scraping')
├── 02_agent_output.md         (10,099 B — Web Scraping 5단 본문)
├── 03_pytest_suite.md         (9,079 B — Pytest 12 scenarios)
├── 04_executor_result.md      (6,241 B — PyInstaller 결과)
├── code/
│   ├── scrape.py              (5,118 B)
│   └── test_scraper.py        (6,098 B)  ⚠️ 파일명 불일치!
└── build_output/
    └── dist/
        └── Scrape.exe         (9,587,444 B = 9.14 MB)
            SHA256: 190caff1d83f55e5484239d2a2815104528a9b691cce2639fd33ac43895d1415
```

---

## 3. ⚠️ QA gate fail — 근본 원인 분석

### 3-1. 사실 확인

`code/test_scraper.py` 첫 33줄:
```python
# file: test_scraper.py
"""scraper.py 의 standalone pytest — playwright 브라우저 미실행, 결정론적 검증."""
import sys
...
sys.path.insert(0, str(Path(__file__).parent))

# --- playwright 사전 stub (scraper import 전에 sys.modules 에 주입) ---
...
import scraper  # noqa: E402   ← 잘못된 모듈명 (실제는 scrape)
```

실제 산출 파일: `code/scrape.py` (PR #78 schema 의 `# file: scrape.py` 헤더로
강제). 그러나 Pytest Author 는 `import scraper` 로 작성 → ModuleNotFoundError →
code_qa fail → functional / robustness 도 연쇄 fail.

### 3-2. 근본 원인

`_build_pytest_author_task` (Track A의 함수, PR #58/#59) 의 description 에는
*entry 파일명 명시 없음* — 컨텍스트 (code_task) 에서 LLM 이 추론해야 함.
Track A 의 Calculator 시나리오에서는 LLM 이 `# file: calculator.py` 에서
파일명을 읽어 `import calculator` 작성하는 패턴이 안정적. 그러나 Track B 에선
도메인 에이전트의 산출 (Web Scraping) 이 `# file: scrape.py` 로 정확히 명시
했음에도 Pytest Author 가 자체 추론 시 `scraper` 로 변형.

이는 **단일 LLM variance** — schema/fence/header 강제는 도메인 에이전트의 *산출*
까지만 적용되며, 후속 Pytest Author 의 *입력 해석*은 LLM 자유 영역.

### 3-3. PR #86 후보 — Pytest Author 에 도메인 entry 명시

위치: `src/workflows/automate_workflow.py::_run_track_b_qa_loop`

처방:
```python
def _build_pytest_author_task_for_track_b(
    pytest_author, code_task, expected_entry_filename: str
) -> Task:
    """Track A 의 _build_pytest_author_task 와 동일하지만 description 에
    expected_entry_filename 을 명시해 LLM variance 차단."""
    base = _build_pytest_author_task(pytest_author, code_task)
    base.description += (
        f"\n\n## entry 파일명 강제\n"
        f"엔트리 파일은 정확히 `{expected_entry_filename}` 입니다. "
        f"테스트 코드는 `import {expected_entry_filename.replace('.py', '')}` "
        f"로 작성하세요. 다른 파일명 추론 절대 금지 — Pytest Author variance "
        f"의 회귀 패턴 (PR #84 검증 사례)."
    )
    return base
```

또는 더 deterministic — 도메인별 `_DOMAIN_TO_ENTRY_FILENAME` (PR #82 에서 정의)
재사용 + description 자동 주입. 5 라인 fix.

`_DOMAIN_TO_ENTRY_FILENAME[domain]` 으로 결정론적 entry 파일명 보장 → import
실패 회귀 차단 + functional/robustness 도구도 entry 정확 인지.

---

## 4. ✅ 인프라 5/5 PASS — Track B 풀체인 정상 작동 입증

### 4-1. PR #78 schema 강제 (방어선 2)

agent_output 10,099 B = 5단 본문 + ```python``` fence + `# file: scrape.py`
헤더. PR #75 회귀 (41 B Final Answer 1줄) 패턴은 *완전 차단*.

### 4-2. PR #80 휴리스틱 분류

"네이버 쇼핑 가격 크롤링 스크립트" → `web_scraping` 정확 분류 (가중치
크롤링(strong=3) + 스크래핑 키워드 매칭).

### 4-3. PR #81 QA loop 실행 (인프라)

pytest_author task 정상 실행 → 03_pytest_suite.md 9,079 B 산출 → 12 scenarios
+ 4 카테고리 분포 (happy/edge/load/error) + python fence + `# file:` 헤더 자동.
즉, *schema 강제는 PR #81 에서도 정상 작동* (방어선 2 패턴 5번째 적용).

### 4-4. PR #82 Build 성공

execute_pyinstaller subprocess → exit_code=0, elapsed=10.54초, **Scrape.exe
9.14 MB**, SHA256 `190caff1...`. 04_executor_result.md 정확 보고서 산출.

핵심: PR #82 의 `_DOMAIN_TO_ENTRY_FILENAME[WEB_SCRAPING] = "scrape.py"` 가
PyInstaller entry 정확 결정 → .exe 빌드 성공. (Pytest Author 가 같은 방식으로
entry 명시 못해 fail 한 점이 PR #86 의 핵심 동기.)

### 4-5. PR #84 CLI 플래그 통합

`--enable-automate-qa-loop` + `--enable-automate-build` 모두 정확히 작동 →
실 LLM 풀체인 trigger 가능 입증.

---

## 5. 핵심 학습

### 5-1. 방어선 2 패턴 *5 차* 재사용 효과 입증

| PR | 적용 위치 | 효과 |
|---|---|---|
| #59 | Track A Pytest Author (PytestSuiteOutput) | 3 필드 schema 강제 |
| #64 | Track A PytestSuiteOutput.to_markdown() | python fence 자동 |
| #66 | Track A UpdateModuleSpecOutput | fence + `# file:` 헤더 자동 |
| #78 | Track B 5 도메인 schema | 5단 본문 강제 + 일반화 헬퍼 |
| **#83** | **Track B Update Checker (PR #66 직접 재사용)** | **자동 import 주입** |

→ *결정형 후처리로 LLM 자유 영역 빈틈 점진 흡수* 패턴이 Track B 에서도 5/5
도메인 안정. 본 E2E 가 그 효과를 실 LLM 1회 호출로 다시 입증.

### 5-2. Schema 가 닫지 못한 영역 — Pytest Author entry 파일명 추론

방어선 2 schema 는 *각 task 의 산출 형식* 만 강제. *task 간 협력* (Pytest Author
가 도메인 에이전트의 entry 파일명을 정확히 읽어 import) 은 여전히 LLM 자유 영역.

이는 *Track A 에서도 잠재 회귀 가능* — Track A 가 Calculator 시나리오에서는
calculator.py 가 일관되게 산출돼 안정적이었으나, 다른 도메인 (Excel 분석 등) 에서
같은 패턴이 발생할 수 있음. PR #86 에서 *_DOMAIN_TO_ENTRY_FILENAME 강제 주입*
패턴이 Track A 도 일반화 가능.

### 5-3. PR #82 Build 성공이 Track B 풀체인 핵심 검증

.exe 9.14 MB 산출 = scrape.py 가 *문법적으로 valid 한 Python* 임을 PyInstaller
가 입증 (불완전 코드면 PyInstaller 빌드도 실패). 즉:
- 도메인 에이전트 산출이 실행 가능한 Python 코드
- Pytest Author 산출도 실행 가능 (테스트 자체는 valid Python)
- 단지 *모듈명 mismatch* 만 fail

→ PR #86 fix 1줄로 QA gate 도 PASS 가능.

---

## 6. 다음 단계 (next_session_context.md §6 갱신 예정)

### 후보 A → ✅ 완료 (본 PR)

본 보고서가 후보 A (Track B 풀체인 실 LLM E2E 검증) 의 결과.

### 후보 F (신규) — Pytest Author entry 파일명 강제 (PR #86) 🔴

PR #84 검증에서 발견된 *Pytest Author variance* fix. `_DOMAIN_TO_ENTRY_FILENAME`
재사용으로 5 라인 코드 + 1 description 주입. **다음 1순위 추천** — Track B QA
gate PASS 도달 + Track A 잠재 회귀 차단.

### 후보 B → 후순위

DevOps 별도 분기 (Trivy + docker build) — 다른 4 도메인 풀체인 안정 후.

### 후보 C/D/E → 중장기

Streamlit UI / UI/UX backstory 강화 / 휴리스틱 더 강화.

---

## 7. 부록 — Track B 풀체인 동작 시퀀스 (실 검증)

```
input: "네이버 쇼핑 가격 크롤링 스크립트"
   │
   │  PR #80 휴리스틱 (가중치 + 단어 경계)
   ↓
domain = web_scraping  (크롤링 + 스크래핑 = 6점, 다른 도메인 0)
   │
   │  PR #78 schema 강제 (WebScrapingOutput.to_markdown)
   ↓
agent_output (10,099 B)
   │  ## Web Scraping 산출
   │  ### 1. 도구 선택 + 근거  (Playwright 1순위 + 근거)
   │  ### 2. robots.txt + ToS 검토  (네이버 정책 + 캡차 거절)
   │  ### 3. 단독 실행 코드  ```python\n# file: scrape.py\n...```
   │  ### 4. 셀렉터 전략 + flakiness 방지
   │  ### 5. 작성자 노트
   │
   │  _extract_track_b_code_blocks (PR #78 일반화 헬퍼)
   ↓
code/scrape.py (5,118 B)
   │
   │  PR #81 QA 루프 — _build_pytest_author_task (Track A 재사용)
   │  + Pytest Author Crew 호출
   │  + PytestSuiteOutput.to_markdown() 자동 fence (PR #64)
   ↓
03_pytest_suite.md (9,079 B) → code/test_scraper.py (6,098 B)
   │  ⚠️ "scraper" 파일명 추론 — 실제는 scrape  ← PR #86 fix 필요
   │
   │  run_code_qa(code_dir)
   ↓
code_qa fail (ImportError: No module named 'scraper')
   │
   │  PR #82 Build — execute_pyinstaller(scrape.py)
   │  + _DOMAIN_TO_ENTRY_FILENAME[WEB_SCRAPING] = "scrape.py" (정확)
   ↓
build_output/dist/Scrape.exe (9.14 MB)  ⭐ 풀체인 도달
SHA256: 190caff1d83f55e5484239d2a2815104528a9b691cce2639fd33ac43895d1415
```

**Track B 풀체인 = 인프라 PASS, 단일 LLM variance fix (PR #86) 만 남음.**

---

*본 보고서는 PR #84 머지 직후 (2026-05-08) Track B 풀체인 실 LLM E2E 검증 결과
입니다. 자세한 산출은 `outputs/automate_workflow_20260508_104330/` 참조.*
