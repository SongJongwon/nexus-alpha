# 🧪 P0+P1 적용 재실행 Verdict 채점 리포트 (2026-05-29)

> **작성일**: 2026-05-29
> **작성자**: Claude Opus 4.8 — 멀티 에이전트 워크플로 9 에이전트 (6 증거 + 3 적대 검증)
> **대상 런**: `run_id=20e515d7de93` (`outputs/alpha_run_20260529_183019/`, 로그 `outputs/events_rerun_P0P1_20260529.jsonl`)
> **제약**: READ-ONLY. 패치/빌드/커밋/pytest 실행 **없음**.
> **선행**: [크래시 분석](phase6e_rerun_crash_analysis_20260529.md) (P0/P1 처방 출처) · P0=PR #234 · P1=PR #235

---

## ⭐ TL;DR

> **P0 완전 성공 ✓ · P1(예방+탐지) 작동 확정 ✓ — 그러나 web 산출이 디스크에 materialize 못 함 → 분기 (b), 단 근본은 "프롬프트가 약해서"가 아니라 P1이 못 막는 *하류 3중 결함*(코드 extraction 손실 · 옵션 B↔P1 충돌 · QA 단일토큰).**

**결정적 반전**: iter2에서 시스템이 **완전한 Three.js+Vite+TypeScript+web-ifc-three SPA(10파일)를 실제로 산출**했다 → "web을 할 수 있다"는 증명. 그러나 그 정답이 code/에 한 파일도 저장되지 못했고(추출 파이프라인 결함), iter3~5는 옵션 B가 stale PyQt를 재주입해 데스크탑으로 되돌아갔다.

---

## 📊 6차원 채점표

| # | 차원 | 결과 | 신뢰도 |
|---|------|------|:------:|
| 1 | **P0 graceful 종료** | ✅ **작동 확정** — BLOCKED(ITERATION_CAP), 크래시 0, iter 5 종료(7폭주 해소) | high |
| 2 | **P1 예방** (web 제약 주입) | ✅ **작동** — platform_intent=web 감지, iter1~5 전 프롬프트 최상단 주입 | high |
| 3 | **P1 탐지** (PLATFORM_DRIFT) | ✅ **4회 발동** (iter1→2~4→5 전이 매번), 데스크탑 마커 정상 검출 | high |
| 4 | **드리프트 추이** | ⚠️ PyQt1 → **web2(전략층 정답)** → PyQt3 → PyQt4 → 빈산출5 (**진동, persist된 web 0**) | high |
| 5 | **A/B 시그니처** | A: PLATFORM_DRIFT 4 / Rule0 domain 0. B: 발동, **4중 3건 PyQt 재첨부=부작용 실증** | high |
| 6 | **BLOCKED 원인** | (가) 플랫폼 드리프트 미해결 — 단 하류 3중 결함이 진짜 원인 | high |

---

## 1. ✅ P0 — graceful 종료 확정 (완전 성공)

크래시 런과 명확히 대조되며 P0가 설계대로 작동했다:
- `result` 이벤트 존재 (events:182) — `verdict=BLOCKED, blocked_cause=ITERATION_CAP, iterations_run=5/5, exe_path=""` + `run_end`(events:183) 정상 종결.
- `judge_convergence` iter=1..5 **5회만** (events:40/41…173/174) — 크래시 런의 7회 폭주 해소.
- `GraphRecursionError`/`Traceback`/`agent_error` **0건** (telemetry는 노드 예외 시 agent_error re-raise → 부재가 무예외 입증).
- 종료 경로 = `convergence_judge` post-가드(1차 방어선), 최종 cause는 JudgmentDecision에서 옴 (iterative_loop.py:2008). `analyze_gap`이 "stagnation 4회 연속 확정 → BLOCKED 강력 권고"(events:171) 후 BLOCKED 종결 체인 정상 통과.

> **P0는 더 이상 web 도메인 요청에서 크래시하지 않는다 — 목표 달성.**

## 2. ✅ P1 예방 — web 감지 + 제약 주입 확정

iter1~5 **모든** `00_user_request.txt` 최상단(라인 3~6)에 동일 제약:
> `## 🚫 플랫폼 제약 (P1, 최우선 — Track 기본값 무시) / 타겟 = web/브라우저 ... PyQt/PySide/Tkinter 등 데스크탑 GUI 프레임워크는 절대 금지`

kickoff에서도 web SPA 합의 (`shared_kickoff_decisions.yaml`: CTO="TypeScript+Vite+Three.js+web-ifc-three SPA 확정", GUI Code Generator="브라우저 File API only"). → platform_intent=web 감지가 kickoff부터 일관.

## 3. ✅ P1 탐지 — PLATFORM_DRIFT 4회 발동 확정

iter2~5 `00_user_request.txt`의 "## 이전 iteration 보정 지시" 섹션에 judge의 PLATFORM_DRIFT next_action이 verbatim:
> `Convergence Judge 권고: ... 타겟=web/브라우저 — Three.js로 재작성하고 PyQt/PySide/Tkinter 제거. 감지된 데스크탑 마커: from pyqt, qapplication, qmainwindow ...`

- **4회 발동** (발동 가능한 4개 전이 전부). detect_desktop_markers가 직전 iter의 PyQt 마커를 정상 검출 → "excerpt 공란" 우려 **기각**.
- events에 "PLATFORM_DRIFT" verbatim 0건은 **preview 잘림**일 뿐(feedback은 프롬프트 끝) — 미발동 아님.

## 4. ⚠️ 드리프트 추이 — 진동 + 결정적 반전

| iter | code/ 디렉토리 (persist) | GUI 트랙 (13_gui_code_output.md) | 분류 |
|------|--------------------------|----------------------------------|------|
| 1 | app.py(PyQt6)+viewport_3d.py(QOpenGLWidget) | PyQt6 | 🔴 PyQt 드리프트 |
| 2 | **test_spa_project.py (tkinter stub만)** | **★ vite+typescript+three.js+web-ifc-three 10파일 완성** | 🟡 **전략층 web 정답 — 그러나 persist 실패** |
| 3 | app.py(PyQt6)+viewport_3d(QPainter placeholder) | framework=PyQt6, 6파일 | 🔴 PyQt 재드리프트 |
| 4 | app.py(PyQt6)+widgets.py | framework=pyqt6, 4파일 (3D/BIM 제거된 generic 대시보드 — 도메인 퇴행) | 🔴 PyQt + 도메인 퇴행 |
| 5 | **(빈 디렉토리)** | web 의도 6줄 잘린 꼬리만 | ⚫ 빈 산출 |

> **🎯 핵심 반전**: iter2의 GUI 트랙은 **진짜 완전한 Three.js SPA**(`IFCLoader`, `IFCViewer.ts`, `SceneSetup`, `OrbitControls`, `entry=npm run dev`)였다. 시스템은 web을 *할 수 있었다*. 그런데:
> - 그 web .ts/.html이 **code/에 한 파일도 저장 안 됨** → 대신 무관한 **tkinter "스파(마사지샵) 예약앱" test stub**만 남음.
> - 원인: **"SPA(single-page-app)"를 "스파(마사지샵)"로 오해** + test-stub-only persist. executor가 정확히 진단: `no valid entry — only test files in code_files. LLM may have misunderstood the request`.
> - **전체 run의 어느 code/에도 web 파일(.html/.js/.ts/package.json) 0개** — web은 markdown prose로만 존재, 빌드 가능 소스로 한 번도 materialize 안 됨.

## 5. A/B 시그니처

- **A**: PLATFORM_DRIFT IMPROVE **4회** / Rule 0(domain_checklist) IMPROVE **0회** — web 의도라 PLATFORM_DRIFT가 매 재진입을 선점(Rule 0보다 우선 배치). 도메인 체크리스트(카메라 회전·클릭 속성·다크모드)는 iter2 web SPA에서 충족 → 미수렴 원인 아님.
- **B**: iter2~5 "이전 iter 코드 발췌" 첨부 발동. **4건 중 3건(iter2/4/5)이 PyQt 코드 재첨부** (iter3만 web TS) → **B 부작용 실증**. 결정적으로 옵션 B의 *"기존 구조/식별자 유지, 백지 재작성=퇴행"* 지시가 P1의 *"PyQt 절대 금지"* 와 **정면 충돌** → GUI framework selector를 PyQt로 되돌림 (iter3 CTO 전략엔 web 제약 언급조차 소실).

## 6. BLOCKED 원인 — (가) 플랫폼 드리프트 미해결, 단 하류 3중 결함

미수렴은 "엔지니어가 web을 몰라서"가 **아니다**(전략층은 정답을 냈다). 진짜 원인은 P1이 못 막는 하류 3중 결함:

1. **🥇 GUI 코드 extraction 파이프라인 단절** — iter2의 정답 web .ts가 code/에 저장 안 되고 "SPA→스파" 오해로 tkinter stub만 persist. *정답을 냈는데 손실.* (가장 치명적)
2. **🥈 옵션 B(#232) ↔ P1(#235) 충돌** — iter3~5에 stale PyQt 코드 재주입 + "구조 유지" 지시가 P1 "PyQt 금지"를 무력화 → 재드리프트. (P2 백로그 항목이 여기서 실증 — **최우선 격상**)
3. **🥉 QA 단일토큰 입력 결함** — Code Reviewer가 실제 코드 대신 `"NEEDS_REVISION"` 단일 토큰만 받아 매 iter blocker 해소 불가 (PR #28/#30/#32 systematic failure 재현) → gap 5회 연속 0 satisfied / resolved_since_last=0 → stagnation.

→ **max-iterations 증액으로는 수렴 불가** (매 iter PyQt 재anchor + QA 입력공백 루프 재생산). 동일 패턴 N회 실패 규칙 부합.

---

## 🛡 적대 검증 (3 refuter, 전부 high)

| 주장 | 결과 | 결론 |
|------|------|------|
| "P0 graceful 종료" | 반증 실패 | **유지** — 5종 반증 전부 음성, 크래시 0 확정 |
| "엔지니어 PyQt 고집 (분기 b)" | 반증 실패 | **유지** — persist 기준 web 회복 0 (iter2 raw web 코드는 분기 a 부분 정황이나 persist 미달) |
| "iteration 부족 (분기 a)" | **반증됨** | **거짓** — 후반 iter 진전 0, web 파일 0개, gap 정체 → max-iter 늘려도 동일 |

---

## 🧭 분기 판정 — **(b) + 중대 보강**

| 분기 | 판정 | 근거 |
|------|:----:|------|
| (a) iteration 부족 → max-iter 증액 | ❌ **기각** | 후반 진전 0, gap 정체, web 파일 0개 |
| (b) 엔지니어 PyQt 고집 → 크루/framing 손봐야 | ✅ **채택(보강)** | persist 산출 web 회복 0, 매 iter 데스크탑 마커 재검출 |
| (c) P1 미발동 | ❌ **기각** | P1 예방+탐지 모두 4회 작동 확정 |

> **정밀 판정**: 분기 (b)가 맞되, 표면적 해석("프롬프트가 약해서 크루 정체성을 못 이김")은 **불완전**하다. P0+P1은 **설계대로 100% 작동**했고, 시스템은 iter2에서 **완전한 Three.js SPA를 실제로 산출**했다. 진짜 병목은 **P1이 닿지 않는 하류 레이어**(코드 extraction · 옵션 B 충돌 · QA 입력)다. 즉 "엔지니어 framing"보다 **파이프라인/충돌 결함**이 1차.

---

## 🔧 처방 권고 (우선순위)

### P2-A (최우선) — GUI 코드 extraction 파이프라인 수정
iter2처럼 `13_gui_code_output.md`에 진짜 web SPA(.ts/.html)가 있는데 code/에 저장 안 되는 버그. "SPA(single-page-app)"→"스파(마사지샵)" 오해 + test-stub-only persist 차단. web 산출(.ts/.html/index.html/package.json)을 code/에 정상 추출·저장. **정답을 냈는데 손실하는 게 가장 치명적.**

### P2-B (최우선) — 옵션 B(#232) ↔ P1(#235) 충돌 해소
web 의도일 때 stale **PyQt 코드 발췌를 첨부하지 말 것** (또는 "이 코드는 플랫폼 위반 — 구조 참고 금지, 백지 web 재작성 필요" 경고로 대체). 현 "구조 유지=퇴행 방지" 지시가 P1과 충돌해 iter3~5 재드리프트의 직접 원인. (크래시 분석 §7 P2의 "B 부작용"이 실증됨 — 격상.)

### P3 — GUI Code Generator 크루 framing
프롬프트뿐 아니라 **크루 도구/정체성 레벨**에서 web 의도 시 Vite/TS 스캐폴드 강제 (분기 b 본래 처방). P2-A/B 후에도 재드리프트 잔존 시.

### P4 — QA 단일토큰 입력 결함 (오래된 systematic failure)
Code Reviewer가 `"NEEDS_REVISION"` 단일 토큰만 받는 결함 (PR #28/#30/#32 재현) — gap stagnation의 한 축. 별도 추적.

---

## 결론 한 줄
**P0+P1 처방은 목표대로 작동(크래시 0 + web 의도 감지/제약/드리프트 탐지 4회)했고, 시스템이 iter2에서 완전한 Three.js SPA를 산출함을 증명했다. 그러나 web 산출이 디스크에 materialize 못 한 것은 P1이 닿지 않는 하류 3중 결함(extraction 손실 · 옵션 B↔P1 충돌 · QA 입력) 탓 → 다음 = P2-A(extraction) + P2-B(B 충돌) 최우선.**

---

## 방법론 + 관련 문서
- 워크플로 `p0p1-rerun-verdict` (9 에이전트): 6 증거(P0/P1예방/P1탐지/드리프트/AB/BLOCKED원인) + 3 적대 검증. 모든 판정 파일경로:라인+원문 인용. READ-ONLY.
- [phase6e_rerun_crash_analysis_20260529.md](phase6e_rerun_crash_analysis_20260529.md) · [phase6e_live_rerun_verdict_20260529.md](phase6e_live_rerun_verdict_20260529.md) · [phase6e_followups.md](../backlog/phase6e_followups.md)
