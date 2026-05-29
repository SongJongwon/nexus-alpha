# Phase 6.E 후속 backlog (PM 보류 처방)

> **출처**: [phase6e_iteration_regression_diagnosis.md](../diagnostics/phase6e_iteration_regression_diagnosis.md) §5.2
> **상태**: PM 확정 진행 우선순위 = **A → B**. C/D 는 본 문서에 *보류 기록*.

---

## 즉시 진행 (PR 진입 확정)

| 옵션 | PR | 상태 |
|------|----|----|
| **A — Rule 0 workflow wire** | 본 sprint | 🚧 진행 중 |
| **B — iter 간 코드 prompt 첨부** | A 머지 + PM 검토 후 | ⏳ 대기 |

---

## 보류 (Backlog)

### C — dependency_analyzer 의 sub-package 매핑

**진단**: iter 1 의 *진짜 BIM 코드* 가 `from PyQt6.QtWebEngineWidgets import QWebEngineView` 산출. dependency_analyzer 가 `PyQt6` 만 추출 → `PyQt6-WebEngine` 별도 pip 패키지 누락 → `ModuleNotFoundError` → BUILD_FAILED (환경 결함 → 코드 결함 오판).

**처방 옵션**:
- **C1**: *Qt sub-module → pip 패키지* 매핑 사전 (`QtWebEngineWidgets → PyQt6-WebEngine`, `QtMultimedia → PyQt6-Multimedia`, `QtCharts → PyQt6-Charts` 등)
- **C2**: pre-PyInstaller validation 의 `ModuleNotFoundError` 시 *fallback retry* (실패한 import 의 *유추 pip 이름* 으로 1회 자동 install)
- **C3**: 두 옵션 결합 — C1 매핑이 다수 케이스 cover, C2 가 매핑 미존재 케이스 자동 복구

**예상 비용**: M (~200줄) — 알려진 Qt sub-module 매핑 (~15건) + AST 확장 + 단위 테스트.

**진입 조건**: PM 승인. 또는 *같은 BUILD_FAILED 오판* 이 1회 더 재발하면 우선순위 ↑.

**파일 영향 후보**:
- `src/agents/build_release/dependency_analyzer.py` — 매핑 dict + 추출 로직
- `src/agents/build_release/build_executor.py` — pre-validation fallback (C2)
- `src/tests/test_dependency_analyzer_agent.py` 또는 `src/tests/test_build_executor_agent.py` — 회귀

---

### D — Product Manager 에이전트 구현 (Phase 5.2 후보)

**진단**: 본부 2 (기획·설계) 의 Product Manager 가 *미구현*. PM 의 가설:
> "Product Manager 가 *제품 비전 / 방향성 유지* 책임을 가지면 iter 간 코드 손실 자체가 일어나지 않을 것"

**진단 분석 결과** (재확인): Product Manager 부재는 **root cause 아님**. 옵션 A (Rule 0 wire) + 옵션 B (iter 간 코드 첨부) 모두 해결되면 *없어도 작동 가능*. 다만 *추가 안전망* 차원의 가치는 분명함.

**처방 옵션**:
- **D1**: Product Manager 에이전트 신설 — 본부 2/2 완성 (현재 1/2)
- 책임:
  - 매 iter 시작 시 *제품 비전* 한 줄 출력 → state 의 *영구 기록*
  - Engineer 산출이 *비전 위배* 시 *경고 신호* (judge 에 보조 입력)
  - User-facing 제품 가치 chain (CTO 의 기술 전략 보다 *상위* layer)

**예상 비용**: L (~500줄) — CrewAI Agent factory + LLM 호출 + workflow wire + 단위 테스트.

**진입 조건**: A + B 머지 후 *그래도* BIM 같은 사고가 또 일어나면 우선순위 ↑. 그렇지 않으면 Phase 5.2 백엔드 3명 묶음에서 함께 진행.

**파일 영향 후보**:
- `src/agents/planning/product_manager.py` (신규)
- `src/agents/planning/__init__.py` — export 추가
- `src/workflows/iterative_loop.py` — wire (옵션)
- 본부 2 정원: 1/2 → 2/2 (조직도 v13)

---

## 추가 인사이트 (사전 보존)

### iter 1 의 BUILD_FAILED 실제 원인 (C 와 관련)

PR #226 머지 후 PM 의 첫 라이브 검증에서:
1. iter 1 = *완벽한 BIM 코드* (Three.js + WebEngine + OrbitControls)
2. dependency_analyzer 가 `PyQt6` 만 검출 → `pip install PyQt6` 성공
3. pre-PyInstaller validation 이 `from PyQt6.QtWebEngineWidgets import QWebEngineView` 실행 → `ModuleNotFoundError` (PyQt6-WebEngine 미설치) → **build 중단**
4. iter 2 가 *blank slate* 로 재시작 (Rule 0 침묵 + 코드 컨텍스트 손실) → 다른 방향 산출

**우리가 manual 빌드 검증 시점에** `.venv\Scripts\pip.exe install PyQt6-WebEngine` 수동 실행 → 정상 빌드 + 5초 alive 검증 완료. 이게 C 처방의 *실제 증명 사례*.

### A + B 머지 후 BIM 재현 가능성

A + B 머지 후 같은 BIM 안건으로 라이브 재실행 시:
- Rule 0 가 iter 1 의 *완벽한 viewport.py* 통과 → Gap Analyst 가 COMPLETE 부여 시 *그대로 COMPLETE*
- 만약 iter 1 이 BUILD_FAILED 면 — iter 2 가 *이전 iter 코드 발췌 prompt* 받음 → BIM 본질 유지하며 fix 시도

→ **A + B 만으로도 BIM 본질 손실 차단 가능성 큼**. C/D 는 *예방 안전망* 차원으로 보존.

---

**작성**: 2026-05-28 PM 의사결정 시점
**참조**: phase6e_iteration_regression_diagnosis.md §5.2 (4 옵션 매트릭스)
