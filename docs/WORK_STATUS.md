# 📌 Nexus Alpha — Work Status Dashboard

> **마지막 업데이트**: 2026-04-27 (PR #25~31 머지 + PR #32 작성 중)
> **현재 브랜치**: `phase5/e2e-6th-verification-structured-output`
> **테스트**: pytest **163 passed** (138 + PR #25 신규 3 + PR #27 신규 1 + PR #29 신규 12 + PR #31 신규 9)
> **마지막 세션 로그**: [progress/session_log_20260421-22.md](./progress/session_log_20260421-22.md)
> **최신 통합 설계**: [architecture/nexus_alpha_v5_built.md](./architecture/nexus_alpha_v5_built.md)

---

## 🚦 현재 상태 한눈에

| 영역 | 상태 |
|---|---|
| Phase 0~5 구축 | ✅ 완료 (31개 PR) |
| 메인 워크플로우 (`analyze_and_implement`) | ✅ 작동 |
| GUI 분기 라우팅 | ✅ 작동 (PR #23 fix 검증 완료 — PR #24) |
| GUI 코드 생성 본문 캡처 | ✅ **PR #25 머지** (이슈 4 해결, 2026-04-27) |
| GUI 풀체인 (`calculator.py` 19~25k 자, py_compile 통과) | ✅ **안정화 (6차 연속)** (PR #28~32 양호) |
| 비-GUI 16 에이전트 본문 캡처 | 🟡 **81% 도달** (PR #32 — 13/16, 시범 2 에이전트 100%) |
| LLM 비결정적 컴플라이언스 | ✅ **방어선 2 입증** (PR #31 시범 100%, PR #33 확장 시 95%+ 예상) |
| 풀체인 E2E ('계산기' → setup.exe) | ❌ 미달성 (외부 도구 미통합) |

---

## 🔴 즉시 처리 필요 (Blocker)

### 1. PR #32 6차 E2E 결과 (작성 중) — 방어선 2 시범 100% 성공

- **브랜치**: `phase5/e2e-6th-verification-structured-output`
- **결과 문서**: [progress/e2e_6th_verification_post_pr31.md](./progress/e2e_6th_verification_post_pr31.md)
- **결과 요약**:
  - ⚠️ **1차 시도 실패**: NexusAlphaLLM 어댑터에 `supports_function_calling` 미구현 → AttributeError → ConverterError. PR #32 의 1줄 fix (False 반환) 로 production E2E 정상화.
  - 🎯 **시범 2 에이전트 100%**: BuildEngineer 67→9,669 자 (×144), ReleaseManager 37→2,156 자 (×58). systematic failure 가 완전 해결.
  - 📈 **캡처율 75% → 81%** (13/16). 비-시범 14 에이전트는 여전히 ~25% 무작위 실패.

### 2. PR #33 (예정) — 14 에이전트 확장 + cosmetic 정리

- **우선순위**: CodeReviewer (양 런 short — systematic 의심), ThemeDesigner (양 런 short)
- **부수 작업**: 21_build_spec.md 의 `### 1.` 헤더 중복 정리 (description 강화 또는 sanitize)
- **목표**: PR #33 사후 7차 E2E 에서 16/16 (≥95%) 도달

### 3. WORK_STATUS §4 (PyInstaller 통합) 평행 시작 가능

- 현재 GUI 사슬은 사양 수준 안정 (`calculator.py` 6차 연속 정상) → 외부 도구 통합은 본 이슈와 독립적 진행 가능

---

## 🟡 단기 작업 (1~2주)

### 3. CLI 경로 E2E 검증

- 데이터 분석 도구 시나리오 (`'매장별 월간 매출 Excel 분석 PDF 보고서'`) 로 CLI 분기도 정상 작동 확인
- Python Engineer backstory 의 도메인 중립화 (PR #23) 효과 직접 검증
- 이슈 4 와 동일한 본문 손실 패턴이 CTO/Analyst/Engineer/Reviewer 에는 없는지 재확인

### 4. PyInstaller 실제 호출 통합 (Phase 4.5 강화)

- 현재: Build Engineer 가 *spec 파일 사양만* 산출
- 목표: 사양 → 실제 `pyinstaller` 호출 → `.exe` 생성 → SHA256 산출
- 위치: [src/agents/build_release/build_engineer.py](../src/agents/build_release/build_engineer.py) 옆에 `build_executor.py` 추가
- v5 doc DoD Phase 4.5 체크리스트 항목 완료 가능

### 5. GitHub Release 자동 업로드 (Phase 5 강화)

- 현재: Distribution Agent 가 *URL 사양만* 산출
- 목표: 사양 → 실제 `gh release create` + 파일 업로드 + 다운로드 URL 반환
- v5 doc DoD Phase 5 체크리스트 완료 가능
- **선결**: PyInstaller 통합 (작업 #4)

---

## 🟢 중기 작업 (1~2개월)

### 6. Streamlit UI 추가 (v1 계획 항목)

- 현재: CLI + 산출 파일 트리만
- 목표: `streamlit run app.py` → 사용자가 자연어 입력 → 진행 상황 실시간 표시 → 산출 다운로드
- 위치: 새 `src/ui/streamlit_app.py`
- 의존성: streamlit + websocket
- v5 doc 의 "UI 20% 구축률" 항목 개선

### 7. Vector DB 통합 (Knowledge 본부 강화)

- 현재: Curator + RAGSearcher 가 메모리 기반 단순 검색
- 목표: Qdrant 또는 ChromaDB 통합 → 과거 워크플로우 산출을 임베딩 → 유사 패턴 검색
- 위치: [src/agents/knowledge/](../src/agents/knowledge/) + 새 `vector_store.py`
- v5 doc 의 "지식 베이스 40% 구축률" 항목 개선

### 8. Credential Vault (보안 강화)

- 현재: `.env` + dotenv 만 (암호화 미적용)
- 목표: `cryptography` 라이브러리로 키 암호화 저장 + 키 회전 지원
- 위치: 새 `src/security/credential_vault.py`
- v5 doc 의 "보안 장치 10% 구축률" 항목 개선
- **계기**: 2026-04-21 git credential 토큰 노출 사고 — 향후 동일 재발 방지

### 9. 빌드 시간 예산 추가 (v3 BUDGET 게이트 확장)

- 현재: v3 의 BUDGET 결정은 LLM 토큰 비용만 추적
- 목표: Build Engineer 사양에 `estimated_build_time_min` 필드 추가 → Convergence Judge 의 BUDGET 합산
- 위치: [src/agents/c_level/convergence_judge.py](../src/agents/c_level/convergence_judge.py) + Build Engineer
- v5 doc "6가지 어려운 질문 #3" 답변

### 10. .exe Provenance 자동 첨부

- 현재: SHA256 만 산출
- 목표: `release_summary.json` 에 `provenance` 필드 (생성 timestamp / agent 체인 경로 / GitHub commit SHA / 빌드 로그 hash)
- 위치: [src/agents/build_release/distribution_agent.py](../src/agents/build_release/distribution_agent.py)
- v5 doc "6가지 어려운 질문 #6 — .exe 신뢰" 답변

---

## 🔵 장기 작업 (3개월+)

### 11. RPA 분기 추가 (v1 비전 부분 회귀)

v5 doc 의 "비전 피벗으로 RPA 특화 에이전트 미구축" 결정을 *선택적으로* 회귀:
- Web Scraping Specialist (Playwright 기반)
- Desktop Automation Specialist (PyAutoGUI 기반)
- API Integration Developer (REST/GraphQL)
- 새 워크플로우: `automate_workflow.py` (analyze_and_implement 와 병렬)

### 12. CEO/CFO 에이전트 추가 (선택)

- multi-project 동시 진행 시 의미 있을 수 있음
- LangGraph 의 deterministic 결정과 조화 필요

### 13. Helicone 통합 (v1 계획 항목)

- 현재: LangFuse 만 (trace + cost)
- 목표: Helicone 추가로 비용 세분 추적 + alert

### 14. Slack Bot (협업 환경)

- v1 계획 항목
- 위치: 새 `src/ui/slack_bot.py`

---

## ⚠️ 알려진 위험 / 기술 부채

### A. 본문 손실 회귀 위험 (이슈 4 패턴)

- 새 GUI 에이전트 추가 시 backstory 에 `"마지막 줄 Final Answer: <summary>"` 패턴 *재도입* 가능
- **방어**: PR #25 의 회귀 테스트 `test_gui_agent_backstories_do_not_use_truncating_final_answer_pattern` 가 정적 grep 으로 차단
- 새 GUI 에이전트 추가 시 해당 테스트의 `backstories` dict 에 등록 필수
- **확장 필요**: PR #27 (이슈 5 fix) 에서 비-GUI 10 에이전트도 동일 grep 보호 대상으로 포함

### B. 외부 도구 미통합 의존

- 현재 Phase 4.5/5 는 *사양 산출만* — 실제 PyInstaller / gh / signtool 호출 부재
- 풀체인 E2E ('계산기' → 다운로드 가능 setup.exe URL) 는 작업 #4~5 완료 전에는 불가능
- v5 doc DoD 의 미완 항목 모두 이 의존에 묶임

### C. 토큰 노출 사고 (2026-04-21)

- `git credential fill` 로 PAT 가 conversation context 에 노출됨
- 사용자가 즉시 PAT 회전 — **위험 해소됨**
- **재발 방지**: 2026-04-27 `gh` CLI 2.91.0 설치 + `gh auth login --web` (브라우저 OAuth) 완료 → PAT 직접 노출 경로 제거

### D. CrewAI 1.14.1 핀 고정

- 현재 `crewai==1.14.1` 핀
- CrewAI 메이저 업그레이드 시 `Final Answer:` 파서 동작 변경 가능 (이슈 4 의 근원)
- requirements.txt 핀 변경 전에 conftest.py + 4 GUI 에이전트 backstory 호환성 재검증 필수

---

## 🗂️ 핵심 문서 빠른 참조

| 목적 | 문서 |
|---|---|
| **현재 작업 상태** (이 문서) | [WORK_STATUS.md](./WORK_STATUS.md) |
| 통합 설계 + 실제 구축 비교 | [architecture/nexus_alpha_v5_built.md](./architecture/nexus_alpha_v5_built.md) |
| v3 자율 반복 루프 설계 | [architecture/nexus_alpha_v3.md](./architecture/nexus_alpha_v3.md) |
| v4 풀 비전 설계 (자연어 → .exe) | [architecture/nexus_alpha_v4.md](./architecture/nexus_alpha_v4.md) |
| v4 조직도 (9 본부 24명) | [architecture/nexus_alpha_org_v4.md](./architecture/nexus_alpha_org_v4.md) |
| 최근 세션 로그 (2026-04-21~22) | [progress/session_log_20260421-22.md](./progress/session_log_20260421-22.md) |
| E2E 재재검증 (2026-04-27, 이슈 5 발견) | [progress/e2e_rereverification_post_pr25.md](./progress/e2e_rereverification_post_pr25.md) |
| E2E 4차 검증 (2026-04-27, 이슈 6 발견) | [progress/e2e_4th_verification_post_pr27.md](./progress/e2e_4th_verification_post_pr27.md) |
| E2E 5차 검증 (2026-04-27, 방어선 1 효과 미미) | [progress/e2e_5th_verification_post_pr29.md](./progress/e2e_5th_verification_post_pr29.md) |
| **E2E 6차 검증** (2026-04-27, 방어선 2 시범 100%) | [progress/e2e_6th_verification_post_pr31.md](./progress/e2e_6th_verification_post_pr31.md) |
| Phase 1 완료 보고서 | [progress/phase1_complete.md](./progress/phase1_complete.md) |
| Phase 2 P1 완료 보고서 | [progress/phase2_priority1_complete.md](./progress/phase2_priority1_complete.md) |
| Phase 2 P2 완료 보고서 | [progress/phase2_priority2_complete.md](./progress/phase2_priority2_complete.md) |
| E2E 재검증 결과 (이슈 4 발견) | [progress/e2e_verification_issues.md](./progress/e2e_verification_issues.md) |

---

## 🎯 추천 다음 액션 순서

1. ~~**이슈 4 PR 생성**~~ ✅ PR #25 머지
2. ~~**E2E 재재검증**~~ ✅ PR #26 — 이슈 5 발견
3. ~~**이슈 5 수정**~~ ✅ PR #27 머지
4. ~~**4차 E2E**~~ ✅ PR #28 — 75% + 이슈 6 발견
5. ~~**이슈 6 방어선 1 (auto-retry)**~~ ✅ PR #29 머지
6. ~~**5차 E2E**~~ ✅ PR #30 — 방어선 1 효과 미미 (75% 정체)
7. ~~**방어선 2 시범** (output_pydantic for Build/Release)~~ ✅ PR #31 머지
8. ~~**6차 E2E**~~ ✅ PR #32 — 어댑터 fix + 시범 100% 성공 (75% → 81%) ← **현재**
9. **PR #33 (예정)**: 14 에이전트 확장 (CodeReviewer + Theme 우선) + cosmetic 정리
10. **PR #33 사후 7차 E2E** — 16/16 (≥95%) 캡처 확인
11. **WORK_STATUS §4 (PyInstaller 통합)** — 본 이슈와 독립 진행 가능 (병렬 OK)

---

*본 문서는 살아있는 대시보드 — 작업 상태가 바뀌면 직접 업데이트하거나 다음 세션 시작 시 Claude 에게 갱신 요청 가능. v5 통합 구성안과 짝을 이루어 "현재 어디에 있고 다음에 무엇을 할 것인가" 를 한 페이지로 보여줌.*
