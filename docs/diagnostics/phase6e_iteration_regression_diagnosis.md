# Phase 6.E 라이브 검증 — iteration 퇴행 버그 진단 리포트

> **작성**: 2026-05-28 (PM 본인 PC 의 BIM 라이브 검증 직후)
> **상태**: 진단 only — 수정은 PM 승인 후 별도 PR
> **참조 산출**: `outputs/alpha_run_20260528_155507/`

---

## 0. 사건 요약

PM 가 [PHASE_6_LIVE_VERIFICATION_GUIDE.md](../PHASE_6_LIVE_VERIFICATION_GUIDE.md) 의 BIM 시나리오로 라이브 실행. 결과:

| iter | 산출 디렉터리 | 코드 본질 | .exe 빌드 |
|------|---------------|----------|-----------|
| 1 | `workflow_20260528_155627/code/` | ✅ **진짜 BIM** — viewport.py + Three.js + WebGLRenderer + OrbitControls + QWebEngineView | ❌ pre-PyInstaller validation 실패 |
| 2 | `workflow_20260528_163248/code/` | ❌ **퇴행** — viewport.py 사라짐, 일반 PyQt 위젯 (`widgets.py` / `styles.py`) | ✅ `App.exe` 산출 — **잘못된 결과** |

→ 사용자는 *iter 2 의 잘못된 .exe* 를 최종 결과로 받음. iter 1 의 *진짜 BIM 코드는 폐기*.

---

## 1. iter 1 의 *진짜* 실패 원인 (.exe 미빌드)

`workflow_20260528_155627/25_executor_result.md` 발췌:
```
pre-PyInstaller validation: pre-build validation: 코드 자체 결함 감지 (ModuleNotFoundError).
PyInstaller 호출해도 .exe 가 런타임 실패할 것이므로 build 중단.

stderr:
  File "viewport.py", line 15, in <module>
    from PyQt6.QtWebEngineWidgets import QWebEngineView
ModuleNotFoundError: No module named 'PyQt6.QtWebEngineWidgets'

PyInstaller 실행 결과: 🔴 FAILED (Exit Code: -5)
```

**결정적 발견**:
- 코드 자체는 *완벽* — viewport.py 가 정확히 `from PyQt6.QtWebEngineWidgets import QWebEngineView` 호출
- 실패 원인 = **`.venv` 에 `PyQt6-WebEngine` 별도 패키지 미설치**
- `PyQt6` 만 있고 `PyQt6-WebEngine` 은 *transitive dep* 으로 자동 안 깔림
- → **PyInstaller pre-validation 이 "코드 결함" 으로 오판 + build 중단**

### 1.1 dependency_analyzer 의 한계

[src/agents/build_release/dependency_analyzer.py](../../src/agents/build_release/dependency_analyzer.py) 의 6 축 분석은 *Python import* 만 검출:
- `from PyQt6.QtWebEngineWidgets import QWebEngineView` → `PyQt6` 만 추출
- `PyQt6-WebEngine` 이라는 *별도 pip 패키지명* 은 import 와 불일치 → 누락
- → pip install 시 `PyQt6-WebEngine` 미설치 → ModuleNotFoundError

### 1.2 처방 (수정은 PM 승인 후)

3 옵션:
- **A** — dependency_analyzer 에 *Qt sub-module → pip package* 매핑 사전 (`QtWebEngineWidgets → PyQt6-WebEngine`, `QtMultimedia → PyQt6-Multimedia` 등)
- **B** — pre-PyInstaller validation 의 ModuleNotFoundError 시 *fallback retry* (해당 import 의 *유추 pip 이름* 으로 1회 자동 install)
- **C** — requirements.txt 에 *PyQt6-WebEngine* 같은 *알려진 sub-package* 사전 등록 (대규모 의존성 사전 표 — 유지 부담)

→ **A + B 결합 추천** — A 의 매핑이 다수 케이스 cover, B 는 매핑 미존재 케이스 자동 복구.

### 1.3 임시 우회 (사용자 측 검증 가능)

```powershell
.venv\Scripts\pip.exe install PyQt6-WebEngine
.venv\Scripts\pyinstaller.exe --onedir --windowed --name BIM-Viewer `
    --collect-all PyQt6 --noconfirm `
    outputs\alpha_run_20260528_155507\workflow_20260528_155627\code\app.py
```

→ **본 리포트 작성 시점 위 명령으로 빌드 검증 완료** — `outputs/bim_viewer_manual_build/dist/BIM-Viewer/BIM-Viewer.exe` 2.4MB + `_internal/` 579MB (QtWebEngine + Three.js 임베딩 HTML 포함). 5초 spawn alive 확정.

---

## 2. iter 2 의 *진짜* 퇴행 원인 (BIM 본질 폐기)

### 2.1 iter 2 의 user_request (boundary feedback)

`workflow_20260528_163248/00_user_request.txt` 발췌:
```
3D BIM 건축 모델 뷰어: Three.js + BIM 라이브러리 사용. 카메라 회전,
클릭 시 속성 표시, 다크 모드 관제 센터 스타일

## 이전 iteration 보정 지시
- must-fix 잔여: 5 blocker(s) + 4 major(s) (총 9건)
- 모호 항목 3건 — 이번 iteration 에서 명확화 우선.
- Convergence Judge 권고: Re-enter loop. Inject must-fix items as boundary
  feedback for CTO/Engineer.

**이번 iteration 은 위 must-fix 항목 해소를 최우선으로 잡고,
기존에 충족된 요구는 회귀시키지 마세요.**
```

**결정적 발견**:
- "기존에 충족된 요구는 회귀시키지 마세요" 안내 *있음* — 그러나 Engineer 가 **무시**
- **`iter 1` 의 실제 코드 파일 (viewport.py 등) 은 prompt 에 *포함 X***
- Engineer 가 *blank slate* 로 iter 2 시작 → must-fix 9건 압박 + LLM variance → *완전히 다른 방향* 산출
- iter 2 산출: `app.py`, `main_window.py`, **`styles.py`**, **`widgets.py`** — *viewport.py 사라짐* + Three.js 흔적 0

### 2.2 근본 원인 — iter 간 *코드 컨텍스트 손실*

[src/workflows/iterative_loop.py:731-744](../../src/workflows/iterative_loop.py#L731-L744):

```python
def _node_run_chain(state: _LoopState) -> dict[str, Any]:
    next_iter = state["iteration"] + 1
    feedback = state.get("feedback", "")
    if feedback:
        request_with_feedback = (
            f"{state['user_request']}\n\n{feedback}"
        )
    else:
        request_with_feedback = state["user_request"]
    ...
    chain_result = run_analyze_and_implement(
        request_with_feedback,
        ...
    )
```

**핵심**: Engineer 에게 전달되는 입력 = `user_request + feedback (must-fix 텍스트)`. **이전 iter 의 실제 코드 (`*.py` 파일) 는 미포함**.

→ Engineer 는 *매 iter 마다* prompt 만 보고 *처음부터* 코드 산출. iter 1 의 "viewport.py + Three.js" 같은 *구조적 결정* 은 *증발*.

### 2.3 처방 (수정은 PM 승인 후)

3 옵션:
- **A** — `_node_run_chain` 의 prompt 에 *이전 iter 의 코드 파일 발췌* (최근 산출 디렉터리 의 주요 `*.py` 첫 N줄) 자동 첨부
- **B** — Gap Analyst 가 *이전 코드 구조 인용* 의무 (예: "이전 iter 의 viewport.py 의 OrbitControls 사용을 유지하면서...")
- **C** — `IMPROVE_NEEDED` 시 Engineer 산출 디렉터리를 *다음 iter 의 시작점* 으로 *재사용* (incremental edit 모드)

→ **A 가 가장 단순 + 즉시 가치**. C 는 *진정한 self-improvement* 지만 큰 구조 변경.

---

## 3. Rule 0 (3D 체크리스트) 가 *왜 못 막았는지*

### 3.1 결정적 발견 — **Rule 0 는 프로덕션에서 *침묵***

[src/workflows/iterative_loop.py:1409-1444](../../src/workflows/iterative_loop.py#L1409) 의 `_node_judge_convergence`:

```python
decision = judge_convergence(
    gap,
    max_iterations=state.get("max_iterations", DEFAULT_MAX_ITERATIONS),
    budget_tokens_remaining=budget,
    # Phase 6.3 (PR #230) — Tech Scout fake_packages 전달
    fake_packages=state.get("fake_packages"),
    consecutive_fake_iterations=state.get("consecutive_fake_iterations", 0),
)
```

**`domain_checklist` 인자 미전달 → Rule 0 가 default None → skip → 침묵**.

`grep "domain_checklist" iterative_loop.py` 결과: **0건**. `grep "build_domain_checklist"` 결과: **0건**. `grep "engineer_output_excerpt"` 결과: **0건**.

→ **Phase 6.2 PR #226 머지는 *코드만 머지*. workflow wire 0**.

### 3.2 PR #226 시점의 *scope 분리* 결정

PR #226 commit message:
> "workflow 통합은 PR #228 (BIM 벤치마크) 에서"

→ PR #230 (Phase 6.3) 작업 시 `fake_packages` 만 wire, `domain_checklist` 는 *여전히 wire 안 함*. **알려진 갭이 누락된 채 PR #230 머지**.

### 3.3 영향

- iter 1 산출: viewport.py 에 `OrbitControls` / `WebGLRenderer` / `PerspectiveCamera` / `Vector3` 모두 존재 → Rule 0 *발동 시* "도메인 체크리스트 통과 → Rule 1 진입" 정상 동작 *했을 것*
- iter 2 산출: 위 키워드 *모두 사라짐* → Rule 0 *발동 시* "4 항목 모두 미충족 → IMPROVE_NEEDED 강제 → iter 3 진입 + Engineer 에게 ID 명시 안내" 정상 동작 *했을 것*
- 그러나 **Rule 0 침묵** → judge 가 iter 2 산출에 *통과 verdict* 부여 → 최종 결과 = iter 2 의 잘못된 .exe

### 3.4 처방 (PM 승인 후)

**즉시 fix 가능** — 작은 PR:
1. `_node_run_chain` 에 *user_request 첫 진입 시* `build_domain_checklist(user_request)` 호출 + state 보존
2. `_node_judge_convergence` 에서 state.domain_checklist + chain_result.code_excerpt 를 judge 에 전달

예상 PR 크기 ~50줄 + 단위 테스트.

---

## 4. Product Manager 미구현이 *진짜 원인인지?*

### 4.1 PM 지적 — *기획 통제 부재*

조직도 v13 본부 2 (기획·설계) 의 Product Manager 가 *미구현*. PM 의 가설:
> "Product Manager 가 *제품 비전 / 방향성 유지* 책임을 가지면 iter 간 코드 손실 자체가 일어나지 않을 것"

### 4.2 분석 결과 — Product Manager 부재는 *추가 안전망 부재*, *root cause 아님*

**root cause 우선순위** (severity 순):
1. ★★★ **iter 간 코드 컨텍스트 손실** (§2.2) — 이건 *구조적 결함*. Engineer 가 prompt 만 보고 *blank slate* 로 매번 시작.
2. ★★★ **Rule 0 workflow wire 미됨** (§3.1) — 알려진 안전망이 *프로덕션에서 침묵*.
3. ★★ **dependency_analyzer 의 sub-package 누락** (§1.2) — iter 1 의 BUILD_FAILED 가 *환경 결함* 인데 *코드 결함* 으로 오판.
4. ★ **Product Manager 미구현** — *추가 안전망* 차원. 1+2+3 모두 해결되면 *없어도 작동 가능*.

### 4.3 처방 우선순위

- **단기 (Phase 7 후보)**: 1 + 2 + 3 fix → iter 간 코드 보존 + Rule 0 활성 + 의존성 사전 매핑
- **중기 (Phase 5.2)**: Product Manager 구현 — 제품 비전 *명시 유지* 추가 안전망

---

## 5. 진단 종합 + PM 승인 요청 사항

### 5.1 본 라이브 검증의 *진짜 결론*

| 차원 | 상태 |
|------|------|
| iter 1 BIM 코드 자체 | ✅ **완벽** (Three.js / WebGL / OrbitControls / WebEngine) |
| iter 1 BIM 빌드 가능성 | ✅ **검증 완료** (수동 빌드 — 2.4MB exe + 579MB internal, 5초 alive) |
| iter 1 BUILD_FAILED 원인 | 🔴 dependency_analyzer 의 sub-package 누락 (환경 결함) |
| iter 2 퇴행 원인 | 🔴 **iter 간 코드 컨텍스트 손실** (구조적 결함) |
| Rule 0 가 못 막은 원인 | 🔴 **workflow wire 미됨** (알려진 갭이 PR #226/#230 둘 다에서 누락) |
| Product Manager 부재 영향 | 🟡 추가 안전망 부재 (root cause 아님) |

### 5.2 PM 검토 요청 — 처방 우선순위

다음 4 옵션 중 PM 결정 필요:

| 옵션 | 작업 | 비용 | 효과 |
|------|------|------|------|
| **A** | Rule 0 workflow wire (즉시 fix) | S (~50줄) | Rule 0 가 *드디어* 프로덕션 동작 — iter 2 같은 퇴행 자동 차단 |
| **B** | iter 간 코드 prompt 첨부 (§2.3 A) | M (~150줄) | Engineer 가 *이전 산출 인지* — 본질적 퇴행 해결 |
| **C** | dependency_analyzer sub-package 매핑 (§1.2 A) | M (~200줄) | iter 1 같은 BUILD_FAILED *환경 오판* 차단 |
| **D** | Product Manager 구현 (Phase 5.2) | L (~500줄) | 추가 안전망 — *비전 유지* 책임자 등장 |

**추천 순서**: **A → B → C → D**. A 가 가장 작고 즉시 효과 (Rule 0 가 *드디어* 동작). B 가 본질적 fix (root cause). C/D 는 후속.

### 5.3 임시 가용 산출

- **iter 1 의 진짜 BIM .exe**: [outputs/bim_viewer_manual_build/dist/BIM-Viewer/BIM-Viewer.exe](../../outputs/bim_viewer_manual_build/dist/BIM-Viewer/BIM-Viewer.exe) (2.4MB launcher + 579MB internal)
- 본 진단 리포트 자체

---

**작성**: Claude Opus 4.7 (1M context)
**검증 방식**: 코드 evidence 직접 인용 + Grep / file Read / 실 빌드 PASS
**상태**: PM 승인 대기 — 처방 옵션 A/B/C/D 결정 후 진입
