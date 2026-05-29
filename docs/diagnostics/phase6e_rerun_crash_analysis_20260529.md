# 🩺 Phase 6.E 재실행 크래시 분석 — GraphRecursionError (2026-05-29)

> **작성일**: 2026-05-29
> **작성자**: Claude Opus 4.8 — 멀티 에이전트 워크플로 9 에이전트 (6 증거 + 3 적대적 검증)
> **대상 런**: `run_id=8998e3042f31` (`outputs/alpha_run_20260529_124613/`, 로그 `outputs/events_rerun_AB_20260529.jsonl`)
> **제약**: READ-ONLY. 패치/빌드/pytest 실행 **없음**.
> **선행**: [phase6e_live_rerun_verdict_20260529.md](phase6e_live_rerun_verdict_20260529.md) (1차 런 INVALID 채점)

---

## ⭐ TL;DR — 판정

> **둘 다이지만 동급이 아니다. 1차(근본) 원인 = Convergence Judge 의 Rule 0(A/PR #231)가 종료 규칙을 구조적으로 override → 무한 IMPROVE. recursion_limit=50 은 그 폭주를 끊은 backstop(증상)일 뿐, "단순 config 부족"은 반증됨.**

사용자 가설 **"A는 반복 IMPROVE 발동, 엔지니어 PyQt 드리프트로 수렴 실패 → 무한 IMPROVE → recursion 초과"가 코드·로그·적대 검증으로 모두 확정**됐다. 반면 "단순 recursion_limit config 부족" 가설은 **반증**됐다 (50은 정상 5-iter엔 충분).

---

## 🔗 크래시 체인 (한눈에)

```
요청: "3D BIM 뷰어: Three.js..." (web/Three.js 도메인)
  └─ expand_requirements (iter0, 1회): domain_checklist = 3D 4항목 생성
       (detect_keywords 전부 JS: WebGLRenderer/THREE./OrbitControls/PerspectiveCamera/Vector3)
  └─ 킥오프 합의: TypeScript + Three.js + IFC.js 웹앱
       └─ ⚠️ 엔지니어가 매 iter PyQt6 Python 산출 (플랫폼 드리프트)
            └─ _validate_domain_checklist: PyQt 텍스트에 JS 키워드 0 매칭 → 4항목 영구 미충족
                 └─ ★ Rule 0 (judge:277-305): 미충족 → IMPROVE_NEEDED 즉시 return
                      └─ Rule 2(STAGNATION:331) · Rule 4(ITERATION_CAP:364) = dead code (도달 불가)
                           └─ _route_after_judge(loop:1618): verdict만 보고 prepare_feedback→run_chain loop back
                                └─ iteration 검사 없음 → max_iterations=5 무력화
                                     └─ iter 5,6,7... 무한 IMPROVE
                                          └─ recursion_limit=50 도달 (iter7 ~51번째 super-step)
                                               └─ 💥 GraphRecursionError (result/verdict 이벤트 없는 크래시)
```

---

## 1. 근본 원인 — Rule 0가 종료 규칙을 구조적으로 가로챔

`convergence_judge.py`의 결정 규칙은 **-1 → 0 → 1 → 2 → 3 → 4 → 5** 순서로 평가되며, **Rule 0가 Rule 2/4보다 먼저 early-return**한다:

| Rule | 위치 | 의미 | 이번 런에서 |
|------|------|------|-------------|
| **0** ★ | `convergence_judge.py:277-305` | domain_checklist 미충족 → **IMPROVE_NEEDED 즉시 return** | **6연속 발동** (영구 미충족) |
| 2 | `:330-345` | STAGNATION → BLOCKED | ☠️ **dead code** (Rule 0 뒤) |
| 4 | `:363-377` | iteration ≥ max → BLOCKED(ITERATION_CAP) | ☠️ **dead code** (Rule 0 뒤) |

> `convergence_judge.py:277` — `# ★ Rule 0: 도메인 체크리스트 미충족 → IMPROVE_NEEDED 강제 (Rule 1 보다 우선)`
> `convergence_judge.py:200-214` (docstring) — `0. ★ ...IMPROVE_NEEDED 강제 / ... / 4. must_fix > 0 AND iteration ≥ max → BLOCKED(ITERATION_CAP)`

**Rule 0가 발동하는 한 STAGNATION·ITERATION_CAP는 문자 그대로 실행되지 않는다.** max_iterations 강제 종료의 **유일한 지점**(Rule 4)이 도달 불가가 되어, `max_iterations=5`가 무력화됐다.

### 라우터도 iteration을 검사하지 않음 (방어선 부재)
`_route_after_judge`(`iterative_loop.py:1618-1629`)는 **verdict만** 보고 분기한다:
> `if decision.verdict == Verdict.IMPROVE_NEEDED: return "prepare_feedback"` → `g.add_edge("prepare_feedback", "run_chain")` (`:1749`)

iteration 비교가 라우터에 **없어서**, judge가 IMPROVE를 계속 주면 그래프 레벨에서 멈출 장치가 전무하다. → **결정적 코드 구조 결함** (LLM variance 아님).

---

## 2. 왜 도메인 체크리스트가 영원히 미충족인가 — 플랫폼 드리프트 × 언어-맹목 매처

- `requirement_expander.py:69-122` — 요청 "3D BIM 건축 모델 뷰어: Three.js"가 `_DOMAIN_PATTERNS["3d_visualization"]`(`3d`/`WebGL`/`Three.js`/`BIM`/`건축 모델`)에 매칭 → **3D 4항목 체크리스트 생성** (Rule 0 wire 활성).
- 4항목의 `detect_keywords`가 **전부 Three.js/JS 토큰** (`WebGLRenderer`, `THREE.`, `OrbitControls`, `PerspectiveCamera`, `Vector3`, `DirectionalLight`).
- `_validate_domain_checklist`(`:153-184`)는 engineer 산출 텍스트에 이 키워드를 부분매칭 → **PyQt6 Python 코드엔 0 매칭** → 매 iter 미충족.

즉 **킥오프는 web/Three.js인데 엔지니어가 매 iter PyQt6로 이탈**(플랫폼 드리프트)하는 한, 체크리스트는 *산출 품질과 무관하게* 절대 충족될 수 없다. 이것이 "수렴 실패"의 정체다. (드리프트 자체는 [1차 런 verdict](phase6e_live_rerun_verdict_20260529.md) 신규발견 (a)와 동일 root cause.)

---

## 3. recursion_limit=50 은 backstop(증상) — "단순 config 부족" 반증

`iterative_loop.py:1930-1933`:
```python
# recursion_limit: iteration 한 번이 7 노드 (Phase 3 에서 sandbox 추가) → max_iter*7 + 안전 여유 10.
recursion_limit = max(50, max_iterations * 7 + 10)   # max_iter=5 → max(50,45) = 50
```

| 시나리오 | super-step 소비 | 50 한도 |
|---------|----------------|---------|
| **정상 5-iter graceful 종료** | prefix 3 + 핵심 6노드×5 + prepare_feedback 4 + 종료꼬리 3~4 ≈ **41** | ✅ 충분 (여유 ~9) |
| **이번 런 (7-iter 폭주)** | prefix 3 + (핵심 7노드)×6=42 + iter7 5노드 = **50** → 51번째(iter7 judge) 초과 | 💥 GraphRecursionError |

- **"50이 max_iter=5에 부족"은 거짓** — 정상 5-iter(~41)는 여유롭게 들어간다.
- 루프가 7회 돈 것은 config 부족이 아니라 **§1의 비종료 결함** 때문.
- **recursion_limit을 올려도** Rule 0가 영원히 IMPROVE를 반환하는 한 *어떤 한도에서든* 동일 크래시(또는 토큰 예산 소진)가 재발한다. → recursion_limit은 근본 원인이 아니라 폭주를 끊은 마지막 안전망.

> ℹ️ 단, 주석의 "7 노드/iter"는 **현재 그래프와 정확히 일치**(run_chain→tech_scout→run_sandbox→runtime_verify→analyze_gap→judge_convergence→prepare_feedback). 다만 floor 50이 ~7 iter를 허용해 `max_iter=5`와 어긋남은 부차적 정합성 이슈.

---

## 4. A / B 시그니처 채점 (재실행)

| 시그니처 | 결과 | 근거 |
|----------|------|------|
| **A (Rule 0)** | ✅ **발동 6회** (iter1~6 전부 IMPROVE 강제) | `judge_convergence done` iter=1~6, `prepare_feedback done` 6회, escalate/finalize 0회. gap "0 satisfied/10 unsatisfied(blocker=6), resolved_since_last=0" 6연속인데도 STAGNATION/BLOCKED 0회 = Rule 0 선점 |
| **B (이전 iter 코드)** | ✅ **발동** (iter2~7 전부) | `00_user_request.txt` 6개(iter2~7)에 PR #232 마커("## 이전 iteration 산출 코드", "--- 이전 iter 코드 발췌 ---", "기존 구조와 식별자...유지") + 직전 PyQt 코드 임베드. prompt_length iter1 5674/3924 → iter2+ 14377~19520 점프 |

→ **1차 런(2026-05-28)과 결정적 차이**: 1차는 A·B 둘 다 **미작동**(머지 前)이었고, 재실행은 둘 다 **작동**했다. 그런데 **B가 작동했음에도 PyQt 드리프트를 못 막았다** — B는 *직전 PyQt 코드*를 첨부하므로, 오히려 엔지니어를 **잘못된 플랫폼(PyQt)에 고착**시켰을 가능성(B가 드리프트를 강화). A는 작동하자마자 종료를 override해 **크래시를 유발**했다.

> ⚠️ B payload 변동: iter5 입력은 834자로 작았는데, 직전 **iter4의 `code/`가 완전히 비어**(빈 산출) 발췌가 요약 텍스트로 폴백된 것. B 발동 자체는 매 iter2+ 유지.

---

## 5. iter별 산출 드리프트 (7회 전부 PyQt, 순수 web 회복 0회)

| iter | 디렉토리 | 산출 분류 | 비고 |
|------|---------|-----------|------|
| 1 | `workflow_20260529_124730` (7파일) | PyQt6 BIM 셸 | model_tree/properties 있으나 3D 캔버스는 **PyQt placeholder** (Three.js 없음) |
| 2 | `_132445` (4파일) | PyQt **일반 대시보드** | "메인 대시보드", BIM 토큰 ~0 |
| 3 | `_135226` (4파일) | PyQt KPI/chart 대시보드 | |
| 4 | `_142213` (**빈**) | **빈 산출** | `code/` 파일 0개 |
| 5 | `_145044` (4파일) | "**Nexus Alpha Control Center**" | 🌀 자기참조 드리프트 (BIM/3D 0) |
| 6 | `_151813` (3파일) | "**Nexus Alpha 에이전트-러너 UI**" | 🌀 최저점, 도메인 완전 상실 |
| 7 | `_154450` (6파일) | PyQt + 내장 Three.js (`block03.py`=viewer.html) | 3D 부분 회복(하이브리드), 순수 web 아님 |

- 킥오프 합의(TypeScript+Three.js+IFC.js 웹앱) 위반 **7/7**.
- **자기참조 드리프트** (iter5/6): 시스템이 BIM 뷰어 대신 *자기 자신(Nexus Alpha)의 대시보드*를 만들기 시작 — 도메인 손실의 극단.
- 구조 축소: 7→4→4→빈→4→3→6 파일.

---

## 6. 적대적 검증 결과 (3 refuter, 전부 high)

| 검증 주장 | 결과 | 결론 |
|-----------|------|------|
| "A가 IMPROVE를 종료조건보다 우선 강제 → 비종료 → recursion 초과" | **반증 실패** | **주장 유지** (3 반증 경로 모두 실패) |
| "단순 recursion_limit config 부족 (비종료 아님)" | **반증됨** | **거짓** — 50은 정상 5-iter에 충분, 비종료가 진짜 원인 |
| "B가 재실행에서 발동" | **확증** | **참** — iter2~7 마커 + prompt 점프 |

---

## 7. 🛠 처방 권고 (우선순위)

### P0 — Rule 0가 종료 규칙(ITERATION_CAP)을 override하지 못하게 (근본)
`convergence_judge.py` 규칙 순서 결함. 두 방법 중 택1(또는 병행):
- **(a) ITERATION_CAP을 Rule 0보다 앞으로** — `iteration >= max_iterations`면 도메인 미충족이라도 BLOCKED(ITERATION_CAP, 사유에 domain_unsatisfied 명기). 가장 직접적.
- **(b) Rule 0가 iteration 인지** — Rule 0 블록 안에서 `iteration >= max`면 IMPROVE 대신 BLOCKED 반환.

### P0 — 라우터/그래프에 hard iteration 가드 (방어선)
`_route_after_judge` 또는 그래프 레벨에서 `iteration >= max_iterations`면 verdict 무관하게 강제 종료. judge 결함 시에도 무한 루프를 막는 defense-in-depth.

### P1 — 플랫폼 드리프트 가드레일 (수렴 실패의 진짜 입력)
[1차 verdict 신규발견 (a)]와 동일. 킥오프 `platform==web`이면 엔지니어 PyQt6/Tkinter 금지·Three.js+Vite 강제. 드리프트를 막아야 도메인 체크리스트가 충족 가능해지고 Rule 0가 정상 수렴한다. (이게 없으면 P0만으론 "BLOCKED로 깔끔히 실패"할 뿐 BIM 본질엔 도달 못 함.)

### P1 — 도메인 체크리스트 매처의 언어-맹목성 완화
`detect_keywords`가 Three.js/JS 전용 → 비-web 산출은 *영구 미충족*. 플랫폼 가드레일과 함께, 매처를 플랫폼-인지형으로 하거나 N회 연속 미충족 시 "충족 불가"로 BLOCKED 처리.

### P2 — B의 드리프트 강화 부작용 검토
B가 *잘못된 플랫폼*의 직전 코드를 첨부하면 드리프트를 고착시킴. 플랫폼 불일치 시 B 발췌에 "이 코드는 플랫폼 위반, 구조 참고만" 경고 주입 또는 platform 정합 시에만 발췌.

### P2 — recursion_limit ↔ max_iter 정합 (부차)
floor 50이 ~7 iter 허용 → max_iter=5와 어긋남. P0 수정 후엔 무해하나, 명시적 정합을 원하면 floor 재검토.

---

## 8. 채점 방법론
- 멀티 에이전트 워크플로 `rerun-crash-analysis` (9 에이전트): 6 증거(A-메커니즘 코드 / max-iter 라우팅 / recursion 수치 / A-발동 로그 / B-발동 로그 / 드리프트 분류) 병렬 + 3 적대적 검증 병렬.
- 모든 판정 파일경로:라인 + 원문 인용. READ-ONLY.
- 인라인 ground-truth(타임라인·iter 진행·prompt_length·recursion 계산)로 선검증 후 위임.

## 9. 관련 문서
- [phase6e_live_rerun_verdict_20260529.md](phase6e_live_rerun_verdict_20260529.md) — 1차 런 INVALID 채점 + 신규발견 3건
- [phase6e_iteration_regression_diagnosis.md](phase6e_iteration_regression_diagnosis.md) — 원 진단
- [phase6e_followups.md](../backlog/phase6e_followups.md) — C/D 보류 처방
- 코드: `src/agents/c_level/convergence_judge.py` (Rule 0/2/4) · `src/workflows/iterative_loop.py` (`_route_after_judge`:1618, recursion:1930) · `src/agents/analysis/requirement_expander.py` (3D 체크리스트)
