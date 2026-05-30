# 🧪 P0+P1+P2 적용 재실행 Verdict 채점 리포트 (2026-05-29)

> **작성일**: 2026-05-30 (런: 2026-05-29 22:57~익일 01:43 KST)
> **작성자**: Claude Opus 4.8 — 멀티 에이전트 워크플로 9 에이전트 (6 증거 + 3 적대 검증)
> **대상 런**: `run_id=b1bd4097e675` (`outputs/alpha_run_20260529_225744/`, 로그 `outputs/events_rerun_P0P1P2_20260529.jsonl`)
> **제약**: READ-ONLY. 패치/빌드/커밋/pytest 실행 **없음**.
> **선행**: P0=#234 · P1=#235 · P2(A+B)=#236 · [P0P1 verdict](phase6e_rerun_P0P1_verdict_20260529.md)

---

## ⭐ TL;DR

> **P0 ✓ · P1 ✓ · P2-A ✓ · P2-B ✓ — 4개 처방 모두 라이브 작동 확정.** 그런데도 BLOCKED — **수렴을 막은 건 P0~P2가 닿지 않는 더 상류의 NEW 병목**: ① **Gap Analyst가 GUI 경로 산출을 아예 못 봄**(engineer_output="" + gui_code_output 미배선) → P2-A가 디스크에 저장한 정답을 *판정기가 못 봐서* 영원히 0 satisfied, ② **GUI Code Generator 크루가 web 컨텍스트를 받고도 PyQt 재선택**(P3), ③ **도메인 드리프트**(iter2 web조차 BIM 아닌 generic 대시보드). **P4(QA 단일토큰)는 이번 BLOCKED의 원인이 아님(적대 검증으로 반증).**

**핵심 진전**: P2-A가 **iter2에서 web 파일 ~15개(react+vite+ts SPA)를 code/에 실제 저장** — 지난 런 0개 → 결정적 수정 확인. 그러나 *판정기가 그 정답을 못 보는* 새 구조 결함이 드러남.

---

## 📊 5차원 채점표

| # | 차원 | 결과 | 신뢰도 |
|---|------|------|:------:|
| 1 | **P2-A 라이브** (web extraction) | ✅ **작동** — iter2 web 파일 ~15개 code/ 저장, 손실 0 | high |
| 2 | **P2-B 라이브** (drift block) | ✅ **작동** — prev=PyQt→차단·경고(iter2/4/5), prev=web→정상 주입(iter3), 4/4 정확 | high |
| 3 | **P0/P1 재확인** | ✅ **작동** — 크래시 0, graceful BLOCKED, PLATFORM_DRIFT 3회 | high |
| 4 | **드리프트 추이 + BIM 본질** | ⚠️ PyQt1→web2(P2-A)→PyQt3→PyQt4→empty5. **정답(web+Three.js+BIM) 0/5** | high |
| 5 | **BLOCKED 1차 원인** | 🆕 **Gap Analyst GUI 입력 배선 결함**(+P3 크루 framing + 도메인 드리프트) | high |

---

## 1~3. P0/P1/P2 — 4개 처방 모두 라이브 작동 ✅

- **P0**: `result`(events:180) BLOCKED(ITERATION_CAP) + `run_end`(:181), judge iter 1~5(폭주 0), `RecursionError/Traceback` **0건**. graceful 종료 확정.
- **P1**: PLATFORM_DRIFT **3회 발동**(iter2/4/5 — prev가 PyQt일 때). P1 제약 헤더 매 iter 상존.
- **P2-A** ✅ **라이브 결정적 성공**: iter2 `code/`에 **web 파일 실제 저장** — index.html(`<div id=root>`+`<script src=/src/main.tsx>`), package.json(react^18.3.1/vite^5.4.1), vite.config.ts, tsconfig.json(jsx:react-jsx), src__App.tsx 외 .tsx ×10, global.css. 지난 P0P1 런 **0개 → 이번 ~15개**. `13b_extraction_warning.txt` 없음(손실 0). 적대 검증 반증 실패(주장 유지).
- **P2-B** ✅ **정확히 분기**: prev=PyQt(iter1/3/4) → "플랫폼 위반·백지 재작성" 경고 + stale PyQt 본문 미주입(iter2/4/5 입력). prev=web(iter2) → 정상 web 코드 주입(iter3 입력, 차단 안 함). 4/4 올바름.

---

## 4. 드리프트 추이 + BIM 본질 — "플랫폼 회복 ≠ 도메인 회복"

| iter | 플랫폼 | BIM 본질 | 비고 |
|------|--------|----------|------|
| 1 | 🔴 PyQt6 | ✅ **BIM 충실** | viewport_3d(GLViewWidget 3D), model_tree(IfcType), "BIM Control Center", IFC 로드 |
| 2 | ✅ **web (P2-A 저장)** | ❌ **도메인 드리프트** | react+vite+ts SPA지만 three.js/web-ifc/IFCLoader **0개**, 내용=generic 에이전트 대시보드(Planner/Coder/Reviewer/Releaser). 다크모드만 ✓ |
| 3 | 🔴 PyQt6 | ❌ | generic task 앱, 라이트모드 |
| 4 | 🔴 pyqt6 | ❌ | KPI/차트 generic 대시보드 |
| 5 | 🔴 pyqt6/empty | ❌ | code/ 비어있음 (result saved_dir) |

> **🎯 역설**: BIM 도메인을 가장 충실히 구현한 건 *플랫폼이 틀린* iter1(PyQt). 플랫폼을 회복한 iter2(web)는 도메인을 generic 대시보드로 갈아끼움. **정답 조합(web + Three.js + BIM 3D) = 0/5 iters.**

---

## 5a. iter3 재드리프트 원인 = **P3 GUI Code Generator 크루 framing**

iter3는 **3중 정상 입력**을 받았다: P1 제약("타겟=web, PyQt 금지") + prev=iter2 web 코드(P2-B 정상 주입) + CTO 전략이 **전면 web**(`01_cto_strategy.md`: "Web 단일 타겟, 데스크탑 범위 외", three.js^0.160.0/WebGLRenderer/OrbitControls 채택). **그런데도 GUI Code Generator가 PyQt6 재선택** — 근거가 날조됨:
> `13_gui_code_output.md:6` — "PyQt6 선택. 근거: **(1) 사용자가 명시적으로 PyQt6 지정**" ← 사용자는 PyQt를 지정한 적 없음(요청은 Three.js/web).

→ 드리프트는 CTO **하류**의 Code Generator 단계에서 주입. P1/P2-B가 닿지 않는 **크루 framing 병목**(P3).

---

## 5b. ★ NEW — BLOCKED 1차 원인 = Gap Analyst가 GUI 산출을 못 봄 (구조적 배선 결함)

**가장 중요한 새 발견.** P2-A가 정답 web 코드를 디스크에 저장했어도, **판정기(Gap Analyst)가 그것을 입력으로 받지 못한다**:

1. GUI 경로 `WorkflowResult.engineer_output=""` 고정 (`analyze_and_implement.py:1430`). 실 코드는 `gui_code_output` 필드 + `code/` 에만 존재. `03_engineer_output.md`는 5 iter 전부 66바이트 스텁("GUI 경로 — Python Engineer 미실행").
2. Gap Analyst 입력 직렬화 `_format_gap_analyst_input`(`iterative_loop.py:335`)는 `[ENGINEER_OUTPUT]` 블록에 `chain_result.engineer_output`만 주입 — **`gui_code_output`은 어느 블록에도 안 들어감** → GUI 경로 [ENGINEER_OUTPUT]은 **항상 공란**.
3. **결정적 반증**: iter2는 P2-A가 web 14파일 저장 + 드리프트 0이었는데도 Gap Analyst가 **"0개 satisfied"**. iter2 gap Thought가 자백: *"Engineer 산출물이 비어있고 ... 실제 산출 0"*(events:79). → 정답을 디스크에 저장해도 판정기는 못 봄 → 0 satisfied 고정 → resolved_since_last=0 → stagnation → BLOCKED.

→ **이 배선 결함이 있는 한, GUI/web 경로는 *완벽한 산출을 내도* 절대 COMPLETE 될 수 없다.** P2-A(코드→디스크)는 고쳤으나, 병렬 채널 `gui_code_output → Gap Analyst 입력`은 여전히 끊겨 있음.

---

## 🛡 적대 검증 (3 refuter)

| 주장 | 결과 | 결론 |
|------|------|------|
| "P2-A 라이브 작동(web 저장됨)" | 반증 실패 (high) | **유지** — code/ web 15파일, PyQt 마커 0, 손실 0 |
| "남은 1차 병목=GUI 크루 PyQt 재선택(P3, 라)" | 반증 실패 (high) | **유지** — iter3가 3중 web 입력에도 PyQt6, 날조 근거. P2-A/B 결함 아님 |
| "QA 단일토큰(P4)이 이번 BLOCKED 원인" | **반증됨 (high)** | **거짓** — PyQt iter의 BLOCKED 경로는 PLATFORM_DRIFT→IMPROVE→P0 cap이라 QA-feed stagnation 규칙을 **우회**. P4는 실재(iter4/5 단일토큰)하나 *이번 BLOCKED엔 인과 0* |

---

## 🧭 분기 판정 — **(라) 새 병목** (복합), (가)는 부분·(나)(다) 기각·P4 인과 반증

| 분기 | 판정 | 근거 |
|------|:----:|------|
| (가) P2 작동+드리프트0인데 QA정체→P4 | ⚠️ **부분** | P2 작동·web 저장은 맞으나, 정체 원인이 **P4가 아니라** 상류 Gap Analyst 배선(P4는 인과 반증됨) |
| (나) P2-A web 저장 실패 | ❌ **기각** | iter2 web 15파일 저장 확정 |
| (다) P2-B 드리프트 여전 | ❌ **기각** | P2-B 4/4 정상 분기 (stale 재주입만 막음, 신규 드리프트는 책임 밖) |
| **(라) 새 병목** | ✅ **채택(복합)** | ①Gap Analyst GUI 입력 배선 결함(최우선) ②P3 크루 framing ③도메인 드리프트 |

---

## 🔧 처방 권고 (우선순위)

### P5 (최우선·NEW) — Gap Analyst GUI-경로 입력 배선 수정
**근거**: 이게 없으면 GUI/web 경로는 *완벽한 산출을 내도* COMPLETE 불가 — 수렴의 절대 블로커.
- `_format_gap_analyst_input`(`iterative_loop.py:335`)가 GUI 경로에서 `gui_code_output`(또는 `code/`의 web 파일)을 `[ENGINEER_OUTPUT]` 블록에 주입하도록 환원. `engineer_output==""` 면 `gui_code_output` 폴백.
- (P2-A가 코드→디스크를 고쳤듯, 이건 코드→판정기 채널 수정.)

### P3 — GUI Code Generator 크루 framing
**근거**: iter3가 3중 web 입력+web CTO 전략에도 PyQt6 재선택("사용자가 PyQt 지정" 날조).
- 프롬프트뿐 아니라 **크루 도구/정체성 레벨**에서 `platform_intent==web`이면 Vite/TS 스캐폴드 강제 + framework 자기선택 차단. CTO 전략(web)을 Code Generator가 무시 못 하게 결합.

### P6 (NEW) — 도메인 본질(BIM/Three.js) 강제
**근거**: iter2 web조차 three.js/IFC 0개(generic 대시보드). 플랫폼 회복 ≠ 도메인 회복.
- 도메인 체크리스트(3D-webgl-vs-canvas 등)가 web 경로에서도 실제 적용되도록 + GUI 생성기가 요청 도메인(BIM 3D 뷰어)을 generic 대시보드로 치환 못 하게.

### P4 — QA 단일토큰 입력 결함 (실재하나 이번 BLOCKED엔 비인과)
Code Reviewer가 `"NEEDS_REVISION"` 단일 토큰만 받는 systematic failure(iter4/5, PR #28/#30/#32 재현). 별도 추적 — 우선순위 하향(이번 미수렴 원인 아님).

---

## 결론 한 줄
**P0+P1+P2 4개 처방 모두 라이브 작동 확정(크래시 0 + web 저장 + 드리프트 보정). 그러나 BLOCKED — P2-A가 정답 web을 디스크에 저장해도 *Gap Analyst가 GUI 산출을 못 보는* 새 구조 결함(P5)이 수렴을 막고, P3 크루 framing이 PyQt 재드리프트를, 도메인 드리프트가 BIM 본질 상실을 일으킴. 다음 = P5(판정기 배선) 최우선 → P3(크루 framing) → P6(도메인).**

---

## 방법론 + 관련 문서
- 워크플로 `p0p1p2-rerun-verdict` (9 에이전트): 6 증거(P0/P1·P2-A·P2-B·드리프트+BIM·iter3원인·BLOCKED원인) + 3 적대 검증. 파일경로:라인+원문 인용. READ-ONLY.
- [phase6e_rerun_P0P1_verdict_20260529.md](phase6e_rerun_P0P1_verdict_20260529.md) · [phase6e_rerun_crash_analysis_20260529.md](phase6e_rerun_crash_analysis_20260529.md) · [phase6e_followups.md](../backlog/phase6e_followups.md)
