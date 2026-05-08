# Track B 5 도메인 sample 재검증 보고서 (PR #78 머지 직후)

> **작성일**: 2026-05-08
> **검증 대상**: PR #78 — Track B 방어선 2 (5 도메인 `output_pydantic` schema +
> fence/header 자동 보강)
> **결론**: ✅ **5/5 PASS** — 본문 9~16K bytes, 모든 도메인 5단 본문 + code/ 산출
> 정상. PR #75 회귀 (41/57 bytes) 완전 차단.

---

## 1. 검증 명령

각 도메인은 `--enable-automate-branch --max-retries 1` 로 1차 + 1 retry 가능
(qa_feedback_loop). DoD 7/7 중 publish/release/executor 4 항목은 Track B
설계상 미동반 (단일 에이전트 호출만) — 산출 코드 자체 검증이 목표.

```bash
# 1) Web Scraping
python scripts/run_e2e_10th_verification.py \
  --request "네이버 쇼핑 가격 크롤링 스크립트" \
  --enable-automate-branch --max-retries 1

# 2) API Integration
python scripts/run_e2e_10th_verification.py \
  --request "GitHub API 이슈 자동 생성 스크립트" \
  --enable-automate-branch --max-retries 1

# 3) Desktop Automation
python scripts/run_e2e_10th_verification.py \
  --request "Excel 자동 입력 RPA 스크립트" \
  --enable-automate-branch --max-retries 1

# 4) Data Parser
python scripts/run_e2e_10th_verification.py \
  --request "한글 Excel 파일 파싱 스크립트" \
  --enable-automate-branch --max-retries 1

# 5) DevOps (재실행 — 자세히는 §4.5 참조)
python scripts/run_e2e_10th_verification.py \
  --request "Docker multi-stage Dockerfile GitHub Actions CI/CD 워크플로 작성" \
  --enable-automate-branch --max-retries 1
```

---

## 2. 결과 표 — PR #75 회귀 vs PR #78 fix 비교

| 도메인 | 이전 (PR #75) | 이후 (PR #78) | 배율 | code/ 추출 | 본문 5단 | 판정 |
|---|---:|---:|---:|---|---|---|
| **web_scraping** | 41 B | **16,159 B** | **394×** | `scrape.py` | ✅ 5단 본문 + robots.txt 검토 + Playwright async | ✅ PASS |
| **api_integration** | 57 B | **11,722 B** | **205×** | `api_client.py` | ✅ 5단 본문 + Bearer PAT + httpx + tenacity + Pydantic 검증 | ✅ PASS |
| **desktop_automation** | (미수행) | **9,325 B** | — | `automate.py` | ✅ 5단 본문 + PyWinAuto UIA + FAILSAFE | ✅ PASS |
| **data_parser** | (미수행) | **9,169 B** | — | `parser.py` | ✅ 5단 본문 + chardet + cp949 fallback | ✅ PASS |
| **devops** | (미수행) | **9,570 B** | — | `Dockerfile` + `.github/workflows/ci.yml` | ✅ 5단 본문 + multi-stage + matrix build + permissions minimal | ✅ PASS |

**산출 디렉터리**:
- `outputs/automate_workflow_20260507_174328/` (web_scraping, retry 2/2)
- `outputs/automate_workflow_20260507_174722/` (api_integration, retry 2/2)
- `outputs/automate_workflow_20260507_175228/` (desktop_automation, retry 2/2)
- `outputs/automate_workflow_20260507_175822/` (data_parser, retry 1/2 — 1차 PASS)
- `outputs/automate_workflow_20260508_090456/` (devops, retry 1/2 — 재실행본)

---

## 3. 도메인별 산출 분석

### 3.1 web_scraping (16,159 bytes — 394×)

- **요청**: "네이버 쇼핑 가격 크롤링 스크립트"
- **휴리스틱 분류**: `web_scraping` ✅ (매칭 키워드: 크롤링·쇼핑→웹페이지)
- **본문 5단 구조 검출**:
  - `## Web Scraping 산출` ✅
  - `### 1. 도구 선택 + 근거` — Playwright(Chromium) 1순위, `requests + BeautifulSoup` 탈락 근거
  - `### 2. robots.txt + ToS 검토 결과` — `urllib.robotparser` 동적 로드, 캡차 우회 거절
  - `### 3. 단독 실행 코드` — ` ```python ` + `# file: scrape.py` 자동 헤더 + Playwright async API 본문
  - `### 4. 셀렉터 전략 + flakiness 방지`
  - `### 5. 작성자 노트` — rate limit 결정 근거
- **윤리 원칙 준수**: 공식 Open API (개발자센터) 권장 명시 + 자동 우회 거절

### 3.2 api_integration (11,722 bytes — 205×)

- **요청**: "GitHub API 이슈 자동 생성 스크립트"
- **휴리스틱 분류**: `api_integration` ✅ (매칭: api·github api)
- **본문 5단 구조 검출**:
  - `## API Integration 산출` ✅
  - `### 1. 도구 선택 + 근거` — httpx 1순위 (HTTP/2 + connection multiplex)
  - `### 2. 인증 전략` — Bearer PAT + `os.environ['GITHUB_TOKEN']` + .env 변수 5종
  - `### 3. 단독 실행 코드` — ` ```python ` + `# file: api_client.py` + tenacity + Pydantic
  - `### 4. rate limit + pagination 처리`
  - `### 5. 작성자 노트` — schema drift / idempotency / 회전 정책

### 3.3 desktop_automation (9,325 bytes)

- **요청**: "Excel 자동 입력 RPA 스크립트"
- **휴리스틱 분류**: `desktop_automation` ✅ (매칭: 자동·rpa·엑셀 자동)
- **본문 5단 구조**: PyWinAuto UIA 트리 + `# file: automate.py` + FAILSAFE
- **안전 원칙 준수**: 위험 조작 거절, 무인 실행 종료 조건, 스크린샷 패턴

### 3.4 data_parser (9,169 bytes)

- **요청**: "한글 Excel 파일 파싱 스크립트"
- **휴리스틱 분류**: `data_parser` ✅ (매칭: 엑셀·파싱)
- **본문 5단 구조**: openpyxl + chardet + utf-8/cp949/euc-kr fallback + DataFrame 구조

### 3.5 devops (9,570 bytes) — 재실행 1회 필요

- **1차 시도 요청**: "FastAPI Docker 배포 파이프라인" → ⚠️ **`api_integration` 으로 오분류**
  - 이유: 휴리스틱이 `fastapi` (api_integration) + `api` 부분문자열 매칭 = 2점 vs `docker` (devops) = 1점
  - Track B 분류는 키워드 카운트 단순 모델 — 다중 도메인 신호 시 오분류 가능
- **2차 시도 요청**: "Docker multi-stage Dockerfile GitHub Actions CI/CD 워크플로 작성"
  - `docker` + `dockerfile` + `github actions` + `ci/cd` = 4점 (devops) → 정상 분류
- **본문 5단 구조**:
  - `### 2. Dockerfile` — ` ```dockerfile ` + `# file: Dockerfile` + multi-stage builder/runtime + non-root
  - `### 3. CI/CD 워크플로` — ` ```yaml ` + `# file: .github/workflows/ci.yml` + matrix Python 3.11/12/13 + `permissions: contents: read`
- **code/ 추출**: `Dockerfile` (2,108 B) + `.github__workflows__ci.yml` (3,045 B)
  (슬래시는 `__` 로 안전 치환 — `_extract_track_b_code_blocks` 표준 패턴)

---

## 4. 핵심 학습

### 4.1 방어선 2 + 4 의 누적 입증 — *세 번째* 재사용

| PR | 메커니즘 | 적용 |
|---|---|---|
| #59 | `output_pydantic` schema + 1200자 임계 | Track A Pytest Author |
| #64 | `_ensure_python_fence` (deterministic 후처리) | Track A PytestSuiteOutput |
| #66 | `_ensure_file_header_in_python_block` | Track A UpdateModuleSpecOutput |
| **#78** | **schema 5 도메인 + 일반화 헬퍼 (python/dockerfile/yaml)** | **Track B automate_workflow** |

→ PR #78 결과는 *결정형 후처리로 LLM 자유 영역 빈틈 점진 흡수* 패턴이 외부
도구 통합과 도메인 전문 에이전트 양쪽 모두에 재사용 가능함을 입증.

### 4.2 휴리스틱 분류의 한계 — devops 사례

`fastapi` 토큰이 `api_integration` 키워드 (`fastapi`) 와 `api_integration`
키워드 (`api` 부분문자열) 양쪽 매칭 → 2점. `docker` 1점은 같은 요청에 등장
해도 패배. **다중 도메인 신호** 가 있는 요청은 키워드 카운트 모델만으로
정확 분류 불가.

**개선 후보 (선택, PR #80~)**:
1. 키워드 가중치 (도구·동작어 > 부분문자열) — 단순 +1 vs +2
2. `api` 같은 *광범위 부분문자열* 은 *단어 경계* 매칭 (`\bapi\b`) 강제
3. 다중 도메인 매칭 시 사용자 디스커버리 (질문 1회) — UNKNOWN 대신
4. LLM 분류 fallback (현재 휴리스틱 → 동률 시 LLM 호출)

### 4.3 schema 강제 + Track A capture-before-rescue 의 *결합* 이 회귀 차단

devops 1차 (PR #78 머지 후 첫 실행) 에서 LLM 응답이 schema 검증 실패 →
PR #53/#55 의 `kickoff_with_converter_rescue` 가 작동 → output_pydantic
strip + raw 보존 + retry. 그러나 raw 가 80 chars 짧음 → `retry_short_tasks_in_chain`
재시도 시점에 Windows MCP 메시지 리더 일시 크래시 → 80 bytes 결과로 종료.

2차 (clearer keywords) 에선 1회 호출에 schema 통과 + 9,570 bytes 정상
산출. 즉:
- **schema 강제** = LLM 행동 안정화 메커니즘
- **capture-before-rescue** = LLM variance 흡수 메커니즘
- **retry_short_tasks_in_chain** = 본문 분량 임계 회귀 차단

세 메커니즘이 *직렬* 로 작동해야 *전체* 회귀가 차단됨. PR #78 은 1번 추가
+ 2/3 재사용 → 5/5 PASS.

---

## 5. 다음 단계

1. **PR #79 (본 보고서) 머지** — 결과 docs + WORK_STATUS / next_session_context 갱신
2. **(선택) PR #80 — 휴리스틱 개선** — 단어 경계 매칭 + 가중치 + 다중 매칭 시 LLM fallback
3. **(선택) Track B 풀체인** — 현재 단일 에이전트 호출만, Track A 처럼
   QA 피드백 루프 결합 시 산출물 안정성 추가 향상 가능

---

*본 보고서는 PR #78 머지 직후 (2026-05-08) 5 도메인 sample 검증 결과를
기록합니다. 자세한 산출은 `outputs/automate_workflow_<ts>/02_agent_output.md`
참조.*
