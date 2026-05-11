# 🏛️ Nexus Alpha 공식 조직도 v9 (PR #97~#101 — DoD 양 Track 7/7 + 안정성 empirical 사이클 + 최종 배포 비전 확정)

**개정일**: 2026-05-11
**최신 구조**: 경영진 + 8개 본부, 총 46명 에이전트
**현재 상태**: **39/46명 구현 (85%)** + **3개 본부 100%** + **본부 3 (개발) 67%** + **Track A·B 모두 DoD 7/7 ALL PASSED** + **5-iter 안정성 80%**

---

## 🚀 v8 → v9 핵심 변경사항

| 항목 | v8 (2026-05-07 PR #49~#76) | **v9 (2026-05-11 PR #77~#101)** |
|---|---|---|
| 누적 PR | 76 | **101** (+25) |
| pytest | 572 | **750** (+178, 회귀 0) |
| Track B 풀체인 | sample 검증 단계 | **DoD 7/7 ALL PASSED (PR #97)** ⭐⭐⭐ |
| **Track B DoD** | 미확립 | **7/7 (PR #97) + active 4/4 (PR #91)** ⭐⭐⭐ |
| 방어선 패턴 재사용 | 4 차 | **13 차 누적** (PR #59~#101) |
| **안정성 검증 도구** | 없음 | ✅ **`scripts/run_dod_stability.py` (PR #99)** ⭐ |
| **N-iter 안정성** | 1/1 single-shot | **5-iter PR #99=60% → PR #100=80% → PR #101 직접 차단** |
| **LLM blind spot 식별 layer** | import path (#88) | **+ stub symbol (#100) + 예외 단정 (#101)** |
| 최종 배포 비전 | 자연어 → .exe (백엔드만) | **Electron/Tauri 데스크탑 + 웹 dual-channel 확정** ⭐⭐⭐ |
| 전체 구현률 | 39/46 (85%) | **39/46 (85%) 유지** (조직 인원 증감 없음) |

---

## 📊 전체 조직 구성 (v8 동일)

### 조직 단위 총 9개
- **경영진 (C-Level)** — 1개 (1/3 구현, 33%)
- **실무 본부** — 8개 (38/43 구현, 88%)

### 에이전트 구현 현황 (2026-05-11 v9)

| 구분 | 인수 | 비율 |
|---|---|---|
| 구현 완료 | **39명** | **85%** |
| 미구현 | 7명 | 15% |
| **총계** | **46명** | **100%** |

### 100% 완성 본부 🎉 (v8 동일)
- ✅ **본부 7: 디자인** (3명, v5 부터)
- ✅ **본부 8: 빌드 & 배포** (9명 + 도구 2종, v6 부터)
- ✅ **본부 4: 품질 검증** (9명 + Convergence Judge + 도구 5종, v7 부터)

### 67% 도달 본부 (v8 동일)
- ✅ **본부 3: 개발** (6/9 = 67%, Phase 6 Track B 5명)

---

## 🆕 v9 의 핵심 — *조직 변경 없는 시스템 강화*

v9 는 *에이전트 수* 가 아닌 **워크플로 안정성 + 사용자 인터페이스 layer** 에 집중.

### 1) Track B 풀체인 DoD 7/7 도달 (PR #97)

PR #95~#96 으로 `external_dependent` 카테고리 + priority fix → **DoD 7/7 ALL PASSED, 13.06분, 18 tests, Draft Release 발행**. Nexus Alpha v4 비전 양 Track 완전 입증.

### 2) 안정성 empirical 사이클 (PR #99~#101)

| 후보 | PR | 결과 | 발견/처방 |
|---|---|---|---|
| N | #99 | 5-iter 3/5 = 60% | `expect` ImportError N-failure 식별 (stub symbol gap) |
| O | #100 | 1-iter PASS, directive 12 차 | stub 심볼 enum + `__getattr__` fallback 도입 |
| P | #100 검증 | 5-iter **4/5 = 80%** (+20%p) | `expect` 0회 재발, ITER 3 새 fail (`urlparse(None)` 잘못된 예외 가정) |
| Q | #101 | 1-iter code_qa PASS | `test_error_*` 예외 단정 보수적 규칙 directive 13 차 |

방어선 패턴 *13 차* 누적:
PR #59 (Track A schema) → #64 (fence) → #66 (header) → #78 (Track B schema) →
#83 (Track B updater) → #86 (filename) → #88 (import path) → #93 (retry directive) →
#95 (dep gating) → #96 (priority) → **#100 (stub symbol) → #101 (예외 단정)**

### 3) LLM systematic blind spot layer 점진 식별

각 PR 가 *finite list of LLM blind spots* 의 한 layer 를 차단:

| Layer | 차단 PR | 패턴 |
|---|---|---|
| filename 변형 (`scraper`/`scrape`) | #86 | entry 파일명 강제 |
| import path 추출 | #88 | `sys.modules` 서브모듈 등록 |
| infinite-short retry | #93 | retry directive 강화 |
| **stub symbol enumeration** | **#100** | `from X import a, b, c` → `{X: [a,b,c]}` + `__getattr__` fallback |
| **예외 단정 (stdlib None/empty)** | **#101** | `urlparse(None)` 등 raise 안 함 사실 목록 |
| (예측 후보) 데이터 타입 가정 | TBD | 자료형 변환 raise 가정 보강 |
| (예측 후보) 환경 변수 가정 | TBD | `os.environ` empty 입력 처리 |

→ 가설: *finite* 한 LLM blind spot 만 존재. 점진적 차단으로 점근적 100% stability.

---

## 🏛️ 본부별 상세 (v8 의 구조 동일 — 강화만 발생)

### 본부 3: 개발 (6/9 = 67%) (v8 동일)

서브그룹 A (핵심 3명) + 서브그룹 B (Phase 6 Track B 5명) + 서브그룹 C (미구현 3명).

### 본부 4: 품질 검증 (9명+1) — *v9 강화*

PR #100 + #101 로 **Pytest Author + qa_feedback_loop directive layer 12·13 차 재사용**:
- Pytest Author 의 backstory 직접 변경 X (안정 유지)
- `_run_track_b_pytest_and_qa` 의 directive chain 만 확장 (방어선 패턴 - workflow level)

### 본부 8: 빌드 & 배포 (9명) — *v9 강화*

PR #99 의 `scripts/run_dod_stability.py` 신설 — *반복 검증 인프라*. N-iter sweep 으로 stability metric empirical 측정. CI/CD-like 안정성 회귀 가드.

---

## 🌐 v9 신규 — 최종 배포 layer (Electron/Tauri)

v9 시점 confirm: **Nexus Alpha 의 최종 진입점은 데스크탑 앱 (Electron 또는 Tauri) + 웹 브라우저 dual channel** (Discord 방식).

| 단계 | 도구 | 사용자 |
|---|---|---|
| Alpha | `install.ps1` | 내부 / 얼리 어답터 |
| Beta | **Streamlit** 웹 UI | 베타 테스터 / 외부 데모 |
| Release | **Electron 또는 Tauri** | 일반 사용자 |

**현재 백엔드 풀체인은 production-ready** — 외부 인터페이스 layer 만 남음. 자세한 로드맵: `docs/context/next_session_context.md` §10.

이는 *조직도 layer 외* 의 결정이지만, 향후 본부 7 (디자인) 의 GUI Designer + GUI Code Generator 가 Streamlit/Electron/Tauri 산출 시나리오를 다룰 가능성.

---

## 🗓️ 다음 단계 — v10 후보

| 시점 | 작업 | 인원 변화 | 비고 |
|---|---|---|---|
| 즉시 | 후보 R (PR #101 5-iter sweep) | 0 | 안정성 +N%p empirical |
| 단기 | 후보 S/T (Post-processing / Sticky category) | 0 | 80% → 95%+ 목표 |
| 중기 | **후보 U (Streamlit Beta)** ⭐ | 0 | UI layer 첫 진입 |
| ⬜ Phase 8 | 2명 (CEO/CFO) | 41명 | C-Level 완성 |
| ⬜ Phase 9 | 5명 (분석/계획/지식/운영/본부 3 나머지 3명) | **46명** | 전체 완성 |

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
| v8 | 2026-05-07 | PR #49-#76: Phase 6 Track B 5명 + Update Checker 풀체인 통합 + active 4/4 도달 |
| **v9** | **2026-05-11** | **PR #97-#101: Track B DoD 7/7 + 안정성 empirical 사이클 (후보 N→O→P→Q, directive 13 차 누적) + 최종 배포 비전 Electron/Tauri 확정** ⭐⭐⭐ |

---

*본 조직도는 PR #101 시점 (2026-05-11) 기준. 39/46 (85%) 구현률 유지.*
*v10 후보: 후보 R/S/T (안정성 95%+ 도달) → 후보 U (Streamlit Beta) → Phase 8/9.*
