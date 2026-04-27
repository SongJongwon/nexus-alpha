# 📌 Nexus Alpha — Work Status Dashboard

> **마지막 업데이트**: 2026-04-27
> **현재 브랜치**: `phase5/e2e-rereverification-issue4`
> **테스트**: pytest **141 passed** (138 + 신규 3)
> **마지막 세션 로그**: [progress/session_log_20260421-22.md](./progress/session_log_20260421-22.md)
> **최신 통합 설계**: [architecture/nexus_alpha_v5_built.md](./architecture/nexus_alpha_v5_built.md)

---

## 🚦 현재 상태 한눈에

| 영역 | 상태 |
|---|---|
| Phase 0~5 구축 | ✅ 완료 (25개 PR) |
| 메인 워크플로우 (`analyze_and_implement`) | ✅ 작동 |
| GUI 분기 라우팅 | ✅ 작동 (PR #23 fix 검증 완료 — PR #24) |
| GUI 코드 생성 본문 캡처 | ✅ **PR #25 머지 완료** (이슈 4 해결, 2026-04-27) |
| GUI 풀체인 ('계산기' → 단독 실행 가능 calculator.py) | ✅ **첫 성공** (E2E 재재검증, 2026-04-27) |
| 비-GUI 10 에이전트 본문 캡처 (QA + Build 5 + Release 4) | 🔴 **이슈 5 신규 발견** (이슈 4 와 동일 패턴) |
| 풀체인 E2E ('계산기' → setup.exe) | ❌ 미달성 (외부 도구 미통합 + 이슈 5) |

---

## 🔴 즉시 처리 필요 (Blocker)

### 1. E2E 재재검증 결과 PR #26 (작성 중)

- **브랜치**: `phase5/e2e-rereverification-issue4`
- **결과 문서**: [progress/e2e_rereverification_post_pr25.md](./progress/e2e_rereverification_post_pr25.md)
- **검증 결과 요약**:
  - ✅ 이슈 4 (GUI 4 에이전트 본문 누락) — 완전 해결 (`13_gui_code_output.md` 50자 → 18,547자)
  - ✅ 이슈 1, 2, 3 — 유지/해결 (`code/calculator.py` 473 줄, py_compile 통과, 절대 import)
  - 🔴 **신규 이슈 5 발견** — 비-GUI 10 에이전트 동일 패턴

### 2. 이슈 5 수정 PR #27 (예정)

- **대상**: QA Reviewer + Build 5 (Dep Analyzer / Build Engineer / Asset Manager / Installer Creator / Platform Tester) + Release 4 (Release Manager / Changelog / Update Checker / Distribution)
- **수정 내용**: 10개 backstory 의 `마지막 줄 Final Answer:` 패턴 → `Final Answer: 한 줄 + 이후 본문 전체` (PR #25 와 동일 방식)
- **회귀 테스트 확장**: `test_non_gui_agent_backstories_do_not_use_truncating_final_answer_pattern` 추가
- **선결 조건**: PR #26 머지 후 진행

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
| **E2E 재재검증 결과** (2026-04-27, 이슈 5 발견) | [progress/e2e_rereverification_post_pr25.md](./progress/e2e_rereverification_post_pr25.md) |
| Phase 1 완료 보고서 | [progress/phase1_complete.md](./progress/phase1_complete.md) |
| Phase 2 P1 완료 보고서 | [progress/phase2_priority1_complete.md](./progress/phase2_priority1_complete.md) |
| Phase 2 P2 완료 보고서 | [progress/phase2_priority2_complete.md](./progress/phase2_priority2_complete.md) |
| E2E 재검증 결과 (이슈 4 발견) | [progress/e2e_verification_issues.md](./progress/e2e_verification_issues.md) |

---

## 🎯 추천 다음 액션 순서

1. ~~**이슈 4 PR 생성** → 리뷰 → main 머지~~ ✅ 완료 (PR #25, 2026-04-27)
2. ~~**E2E 재재검증** (스크립트 1회 실행 ~18분)~~ ✅ 완료 (`outputs/workflow_20260427_094102/`)
3. **PR #26**: E2E 재재검증 결과 + 이슈 5 발견 보고 ← **현재**
4. **PR #27**: 이슈 5 수정 — 비-GUI 10 에이전트 backstory 패턴 치환 + 회귀 테스트 확장
5. **PR #27 사후 4차 E2E** — 14 에이전트 모두 본문 캡처 확인
6. 이후 → 작업 #3 (CLI 경로 E2E) 또는 #4 (PyInstaller 통합) 중 선택

---

*본 문서는 살아있는 대시보드 — 작업 상태가 바뀌면 직접 업데이트하거나 다음 세션 시작 시 Claude 에게 갱신 요청 가능. v5 통합 구성안과 짝을 이루어 "현재 어디에 있고 다음에 무엇을 할 것인가" 를 한 페이지로 보여줌.*
