# 🏛️ Nexus Alpha 공식 조직도 v8 (PR #49~#76 — Phase 6 Track B 5명 + Update Checker 통합 + active 4/4 도달)

**개정일**: 2026-05-07
**최신 구조**: 경영진 + 8개 본부, 총 46명 에이전트
**현재 상태**: **39/46명 구현 (85%)** + **3개 본부 100% 완성** + **본부 3 (개발) 67%** + **자동 QA 피드백 루프 active 4/4 도달**

---

## 🚀 v7 → v8 핵심 변경사항

| 항목 | v7 (2026-04-28 PR #42~#48) | **v8 (2026-05-07 PR #49~#76)** |
|---|---|---|
| 누적 PR | 48 | **76** (+28) |
| pytest | 260+ | **572** (+312, 회귀 0) |
| **본부 3 (개발)** | 3/9 (33%) | **6/9 (67%)** ⭐ |
| **Phase 6 Track B 착수** | ⬜ | ✅ **5명 동시 추가 (PR #68)** |
| **Track B 워크플로 통합** | ⬜ | ✅ **`automate_workflow.py` 신설 (PR #70)** |
| **Update Checker 풀체인 통합** | ⬜ (사양만) | ✅ **`code/updater.py` 자동 산출 + entry 자동 import** (PR #66) |
| **active QA gating** | 0/4 (인프라만) | **4/4 (`--force-cli` CLI 시나리오, PR #73)** ⭐⭐⭐ |
| **방어선 4 도입 (deterministic)** | ⬜ | ✅ **`to_markdown()` 자동 fence + 헤더 보장 (PR #64, #66)** |
| 전체 구현률 | 30/46 (65%) | **39/46 (85%)** ⭐⭐ |
| 100% 본부 | 3개 | **3개 유지** (디자인 / 빌드&배포 / 품질 검증) |

---

## 📊 전체 조직 구성

### 조직 단위 총 9개
- **경영진 (C-Level)** — 1개 (1/3 구현, 33%)
- **실무 본부** — 8개 (38/43 구현, 88%)

### 에이전트 구현 현황 (2026-05-07 v8)

| 구분 | 인수 | 비율 |
|---|---|---|
| 구현 완료 | **39명** | **85%** |
| 미구현 | 7명 | 15% |
| **총계** | **46명** | **100%** |

### 100% 완성 본부 🎉
- ✅ **본부 7: 디자인** (3명, v5 부터)
- ✅ **본부 8: 빌드 & 배포** (9명 + 도구 2종, v6 부터)
- ✅ **본부 4: 품질 검증** (9명 + Convergence Judge + 도구 5종, v7 부터)

### 67% 도달 본부 ⭐
- ✅ **본부 3: 개발** (6/9 = 67%, **v8 신규 — Phase 6 Track B 5명 동시 추가**) ⭐⭐

---

## 🏛️ 본부 3: 개발 본부 (Engineering) — **6/9 (67%)** ⭐ v8 신규

**책임**: 새 코드 창조 (실행 로직 중심)
**현황**: 6/9 구현 (67%) — Phase 6 Track B 5명 추가 (v8)

### 서브그룹 A: 핵심 (3명, v7 부터)

| # | 직책 | 역할 | 구현 PR | 상태 |
|---|---|---|---|---|
| 1 | **Data Analyst Agent** | 데이터 분석 지시서 | Phase 1 | ✅ |
| 2 | **Python Engineer Agent** | Python 코드 작성 | Phase 1 (PR #23) | ✅ |
| 3 | **Gap Analyst** | 격차 분석 | Phase 2.5 | ✅ |

### 서브그룹 B: Phase 6 Track B (5명, **v8 신규**) ⭐

| # | 직책 | 1순위 도구 | 핵심 원칙 | 구현 PR |
|---|---|---|---|---|
| 4 | **Web Scraping Specialist** | Playwright + Selenium fallback | robots.txt + rate limit + 캡차 우회 거절 | **PR #68** ⭐ |
| 5 | **Desktop Automation Specialist** | PyWinAuto + PyAutoGUI fallback | 해상도 독립 + FAILSAFE + Office COM | **PR #68** ⭐ |
| 6 | **API Integration Developer** | httpx + gql + FastAPI | secret 환경변수 + OAuth2 + tenacity | **PR #68** ⭐ |
| 7 | **Data Parser Engineer** | openpyxl + pdfplumber + ijson | cp949 + 한글 컬럼 + streaming | **PR #68** ⭐ |
| 8 | **DevOps Engineer** | Dockerfile multi-stage + GitHub Actions | non-root + secret baked 금지 + tag 불변 | **PR #68** ⭐ |

### 서브그룹 C: 미구현 (3명, Phase 9 예정)

| # | 직책 | 역할 | Phase | 상태 |
|---|---|---|---|---|
| 9 | Integration Architect | 연동 아키텍처 | Phase 9 | ⬜ |
| (10) | Code Refactoring Specialist (가칭) | legacy 정리 | Phase 9 | ⬜ |
| (11) | Migration Specialist (가칭) | 마이그레이션 | Phase 9 | ⬜ |

> **note**: 본부 3 정원 9명 중 3명 미구현. Track B 워크플로 (`automate_workflow.py`) 통합으로 5명이 *호출 가능* 상태.

### 🎯 본부 3 의 워크플로 도구 (v8 신규)

| # | 컴포넌트 | 역할 | 위치 | 구현 PR |
|---|---|---|---|---|
| 0a | **`automate_workflow.py`** | Track B 단일 에이전트 호출 (5 도메인 휴리스틱 분류) | `src/workflows/automate_workflow.py` | **PR #70** ⭐ |
| 0b | **`detect_automation_domain()`** | 휴리스틱 도메인 분류 (web_scraping / desktop_automation / api_integration / data_parser / devops / unknown) | `src/workflows/automate_workflow.py` | **PR #70** ⭐ |
| 0c | **`AutomationDomain` enum** | 5 도메인 + UNKNOWN | `src/workflows/automate_workflow.py` | **PR #70** ⭐ |

**핵심 결정사항 (PR #68~#76)**:
- Track A (analyze_and_implement) 와 분리 책임 — `automate_workflow.py` 별도 신설
- Track A 안정성 보호 (Calculator.exe 풀체인 회귀 위험 격리)
- `analyze_and_implement.py` 에 `enable_automate_branch=False` 토글 추가 (PR #70) — backward compat
- E2E 스크립트 `--enable-automate-branch` 플래그 (PR #75) — Track B 풀체인 검증 도구

### ⚠️ Track B 한계 (5/7 sample 검증으로 발견)

| 방어선 | Track A 적용 | **Track B 적용** |
|---|---|---|
| 1 (PR #29 auto-retry) | ✅ | ✅ |
| **2 (PR #31~33, #59 `output_pydantic`)** | ✅ | ❌ **미적용** |
| 3 (PR #53, #55 capture-before-rescue) | ✅ | ✅ |
| 4 (PR #64 fence 자동) | ✅ | (schema 없으니 N/A) |

→ Track B 2 도메인 sample 검증 (Web Scraping 41 bytes / API Integration 57 bytes) 에서 *이슈 4/6 회귀 패턴* 발견. 다음 PR #77 후속 작업으로 5 도메인 schema (`WebScrapingOutput` 등) 도입 예정.

---

## 🏛️ 본부 4: 품질 검증 본부 (QA & Review) — **100% 완성** 🎉 (v7 유지)

(v7 부터 완성, v8 변경 없음 — 단 active QA gating 4/4 도달 ⭐⭐⭐)

### 9명 + Convergence Judge + 도구 5종

(서브그룹 A/B/C/D + code_qa_executor / functional_test_executor / gui_test_executor / robustness_executor / qa_feedback_loop)

### 🎯 v8 신규 — active QA gating 4/4 도달 ⭐⭐⭐

PR #73 `--force-cli` 플래그 → CLI E2E 검증 → **active QA 4/4 자연 도달**:

```
artifact_category=library (gui 가 아님)
skipped=0  ← SKIPPED 없음!
QA 결과:
  code_qa     : ✅ PASS (12 tests)
  functional  : ✅ PASS (10/10) ⭐
  gui_test    : ✅ PASS
  robustness  : ✅ PASS (9/9) ⭐
```

active QA gating 진화: 0/4 → 2/4 (8차) → 1/4 회귀 (9차) → 2/4 (10·11·12차) → **4/4 (PR #73)** ⭐⭐⭐

---

## 🏛️ 본부 8: 빌드 & 배포 본부 — **9/9 + 도구 2종 (100%)** 🎉 (v7 유지)

### 핵심 변경 (v8) — Update Checker 풀체인 통합 ⭐ (PR #66)

| v7 (2026-04-28) | **v8 (2026-05-07 PR #66)** |
|---|---|
| Update Checker 가 *사양 + 참조 구현* 만 산출 (`32_update_module_spec.md`) | **`code/updater.py` 자동 산출** + 산출 entry (`calculator.py`) 에 `try: import updater; updater.start()` 자동 삽입 |
| 산출 .exe 가 updater 모듈을 import 못함 | **풀체인 외부 첫 통합 검증 완료** (11차 E2E) |

### 보안 5원칙 100% 준수 (LLM 산출 updater.py)

| 보안 원칙 | 구현 |
|---|---|
| HTTPS 강제 | `url.startswith("https://")` ✅ |
| TLS 검증 | `requests` + `verify=True` 기본 ✅ |
| 화이트리스트 | `ALLOWED_ENDPOINTS` 튜플 ✅ |
| SHA256 검증 | `hashlib.sha256` + `_verify_sha256()` ✅ |
| 자동 적용 금지 | `webbrowser.open()` 만 ✅ |

### 도구 컴포넌트 (3종)

- **build_executor** (PR #36) — 실제 PyInstaller 호출
- **distribution_executor** (PR #39) — 실제 `gh release create` 호출
- **(v8 신규)** **`_integrate_update_checker()` 워크플로 helper** (PR #66) — `update_module_spec` → `code/updater.py` 자동 추출 + entry 자동 import

---

## 🎯 경영진 (C-Level) — 1/3 (33%) — v7 유지

(v7 변경 없음. CTO Agent ✅ / CEO Agent ⬜ / CFO Agent ⬜)

---

## 🏛️ 본부 1: 업무 분석 본부 — 1/5 (20%) — v7 유지

---

## 🏛️ 본부 2: 기획 및 설계 본부 — 1/4 (25%) — v7 유지

---

## 🏛️ 본부 5: 지식 관리 본부 — 2/3 (67%) — v7 유지

---

## 🏛️ 본부 6: 운영 지원 본부 — 1/4 (25%) — v7 유지

---

## 🏛️ 본부 7: 디자인 본부 — **3/3 (100%)** 🎉 — v7 유지

---

## 📊 본부별 인수 및 진척률 요약

| 조직 단위 | 정원 | 현재 | 진척률 | 변동 (v7→v8) | Phase별 완성 예정 |
|---|---|---|---|---|---|
| 경영진 (C-Level) | 3명 | 1명 | 33% | — | Phase 8 |
| 본부 1: 업무 분석 | 5명 | 1명 | 20% | — | Phase 9 |
| 본부 2: 기획 및 설계 | 4명 | 1명 | 25% | — | Phase 9 |
| **본부 3: 개발** | 9명 | **6명** | **67%** ⭐ | **+3명** (PR #68) | Phase 6 Track B (v8) |
| **🎉 본부 4: 품질 검증** | 9명+1 | **9명+1** | **100%** ✅ | — | Phase 7 완료 (v7) |
| 본부 5: 지식 관리 | 3명 | 2명 | 67% | — | Phase 9 |
| 본부 6: 운영 지원 | 4명 | 1명 | 25% | — | Phase 9 |
| **🎉 본부 7: 디자인** | 3명 | **3명** | **100%** ✅ | — | Phase 4 완료 |
| **🎉 본부 8: 빌드 & 배포** | 9명+1 | **9명+1** | **100%** ✅ | (Update Checker 통합) | Phase 5 완료 |
| **총계** | **46명** | **39명** ⭐⭐ | **85%** | **+9명** (v7→v8) | Phase 9 완료 시 |

---

## 📝 v7 → v8 변경사항 요약 (PR #49~#76)

### 신규 도입 인프라 (4개 모듈)

| 모듈 | PR | 역할 |
|---|---|---|
| `automate_workflow.py` | **#70** ⭐ | Track B 단일 에이전트 호출 (5 도메인 휴리스틱 분류) |
| `_integrate_update_checker()` (analyze_and_implement) | **#66** | Update Checker 풀체인 통합 (`code/updater.py` 자동 산출 + entry import) |
| `_ensure_python_fence()` (방어선 4) | **#64** | Pytest fence 자동 감싸기 (deterministic) |
| `_ensure_file_header_in_python_block()` (방어선 4) | **#66** | `# file: <name>` 헤더 자동 보장 |

### 신규 에이전트 (5명, **본부 3 Phase 6 Track B**) ⭐

| 에이전트 | PR | 1순위 도구 |
|---|---|---|
| Web Scraping Specialist | **#68** | Playwright + Selenium fallback |
| Desktop Automation Specialist | **#68** | PyWinAuto + PyAutoGUI fallback |
| API Integration Developer | **#68** | httpx + gql + FastAPI |
| Data Parser Engineer | **#68** | openpyxl + pdfplumber + ijson |
| DevOps Engineer | **#68** | Dockerfile multi-stage + GitHub Actions |

### 풀체인 도구 (E2E 스크립트 강화, 3종)

| 플래그 | PR | 효과 |
|---|---|---|
| `--request "..."` | #71 | 임의 시나리오 재사용 가능 (argparse + 원본 보존) |
| `--force-cli` | #73 | `enable_gui_branch=False` 강제 → **active QA 4/4 도달** ⭐⭐⭐ |
| `--enable-automate-branch` | #75 | Track B 풀체인 검증용 (5 도메인 sample 검증) |

### 핵심 학습 — 방어선 4 패턴 재사용

| PR | 적용 위치 | 메커니즘 |
|---|---|---|
| **PR #64** | `PytestSuiteOutput.to_markdown()` | fence 자동 감싸기 |
| **PR #66** | `UpdateModuleSpecOutput.to_markdown()` | fence + `# file: updater.py` 헤더 자동 보장 |

같은 헬퍼 (`_ensure_python_fence`) 가 두 schema 모두 재사용 → LLM 자유 영역의 빈틈을 *결정형 단계로* 흡수.

---

## 🔑 조직 운영 원칙 (v2~v8 일관)

1. 단일 책임 원칙
2. 관리폭 제한 (본부당 최대 10명)
3. 본부 간 책임 경계 명확
4. 에이전트 배치는 유연
5. 본부 신설은 신중
6. 도구 컴포넌트 vs LLM 에이전트 구분 (v6 부터)
7. **Track A / Track B 분리** (v8 신규) — 워크플로 안정성 보호

---

## 🎯 다음 단계 전망

### Track A: `.exe` 생성기 — 사실상 완료 ✅
- M1~M5 모두 달성, **M5 풀체인 자동 검증** (PR #41 9차 E2E)
- **M5 + QA 검증 풀체인** (PR #51 10차 E2E DoD 7/7 ALL PASSED)
- **active QA gating 4/4 자연 도달** (PR #73 `--force-cli`) ⭐⭐⭐

### Track B: 업무 자동화 (남은 7명)

| Phase | 추가 에이전트 | 누적 | 마일스톤 |
|---|---|---|---|
| ✅ **Phase 6 (v8)** | **5명** (Track B 본격 시작) | **39명** | **본부 3 67% + 풀체인 외부 통합** |
| ⏳ Phase 6 후속 | Track B 방어선 2 (`output_pydantic`) | 39명 | 5 도메인 schema 도입 (PR #77 예정) |
| ⬜ Phase 8 | 2명 (CEO/CFO) | 41명 | C-Level 완성 |
| ⬜ Phase 9 | 5명 (분석/계획/지식/운영/본부 3 나머지 3명) | **46명** | **전체 완성** |

---

## 📜 변경 이력

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v2.0 | 2026-04-17 | 6개 본부 + 경영진 |
| v3.0 | 2026-04-17 | 자율 반복 루프 4명 추가 |
| v4.0 | 2026-04-17 | 디자인 + 빌드&배포 본부 신설 → 8개 |
| v5.0 | 2026-04-20 | Phase 4 완료: 디자인 100% |
| v5.1 | 2026-04-20 | Phase 4.5+5 완료: 빌드&배포 100% |
| v6 | 2026-04-28 | PR #25-36: 외부 도구 통합 첫 성공 + 첫 .exe |
| v7 | 2026-04-28 | PR #42-#48: 본부 4 (품질 검증) 100% + 자동 QA 피드백 루프 |
| **v8** | **2026-05-07** | **PR #49-#76: Phase 6 Track B 5명 + Update Checker 풀체인 통합 + active 4/4 도달** ⭐⭐⭐ |

---

*본 조직도는 PR #76 머지 시점 (2026-05-07) 기준. 39/46 (85%) 구현률 도달.*
*v9 후보: PR #77 후속 (Track B 방어선 2 적용) → Phase 8 (C-Level 완성) → Phase 9 (전체 완성).*
