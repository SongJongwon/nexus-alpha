# 🧪 P5 적용 재실행 Verdict 채점 리포트 (2026-05-30)

> **작성일**: 2026-05-30 (런: 2026-05-30 14:24~17:20 KST)
> **작성자**: Claude Opus 4.8 — 멀티 에이전트 워크플로 8 에이전트 (5 증거 + 3 적대 검증)
> **대상 런**: `run_id=3f6318b2ba6d` (`outputs/alpha_run_20260530_142405/`, 로그 `outputs/events_rerun_P5_20260529.jsonl`)
> **제약**: READ-ONLY. 패치/빌드/커밋/pytest 실행 **없음**.
> **선행**: P0=#234 · P1=#235 · P2=#236 · P5=#237 · [P0P1P2 verdict](phase6e_rerun_P0P1P2_verdict_20260529.md)

---

## ⭐ TL;DR

> **역대 최대 진전 — P5 ✓✓ + P3 4/5 web 유지 + P6 BIM 본질 회복 → satisfied 0→8(9 중 8, 잔여 1 blocker)로 COMPLETE 직전까지 도달.** BLOCKED의 남은 벽 = **🆕 P7: 빌드/배포 체인이 web을 못 빌드** — 정답 web SPA를 만들어도 빌드 체인이 `vite.config.ts`를 Python entry로 골라 PyInstaller에 먹임(`python vite.config.ts` → SyntaxError → .exe SKIP). web은 `npm run build → dist/`인데 체인은 PyInstaller→.exe만 안다.

**결정적**: 시스템이 **진짜 BIM 3D 뷰어**(IFCLoader+OrbitControls+Raycaster→IFC 속성+다크 관제)를 web/TS로 산출했고, **판정기가 그걸 봐서(P5) 8 satisfied** — 역설은 **.exe를 얻은 유일한 iter가 PyQt 드리프트(iter4)** 였다는 점(배포물을 얻으려면 플랫폼을 위반해야 하는 구조).

---

## 📊 5차원 채점표

| # | 차원 | 결과 | 신뢰도 |
|---|------|------|:------:|
| 1 | **P5 라이브** (satisfied 0→8) | ✅ **작동 확정** — 판정기가 실코드 수신(prompt_length≈코드 바이트), satisfied 8 도달 | high |
| 2 | **P3 드리프트** | ✅ **대폭 개선** — web 4/5 유지, iter4만 PyQt(날조 재현). 잔여 결함 | high |
| 3 | **P6 도메인(BIM)** | ✅ **본질 회복** — 진짜 three.js/IFC 3D 뷰어, 요청 3요소 충족 | high |
| 4 | **🆕 P7 빌드 체인** | ❌ **NEW 병목 확정** — web SPA를 Python으로 오인 → .exe SKIP | high |
| 5 | **BLOCKED 1차 원인** | **P7**(배포물 미산출) + P3 잔여 + QA 단일토큰 | high / blocker정체 medium |

---

## 1. ✅ P5 — 라이브 작동 확정 (satisfied 0→8)

지난 P0P1P2 런은 전 iter "0 satisfied" 고착이었으나, 이번엔 satisfied가 **8까지** 도달. 정량 증거:
- **판정기 입력 = 실코드** (P5 핵심): analyze_gap `prompt_length` ≈ 해당 iter `13_gui_code_output.md` 바이트와 1:1 동반:
  - iter1: prompt 46333 ≈ 코드 46344B → **sat 8**
  - iter5: prompt 67178 ≈ 코드 65667B → **sat 8**
  - iter3: prompt 8375 ≈ 코드 142B(1줄) → sat 1 (얇은 산출 정확 반영)
  - iter4: 코드 6459B(PyQt 드리프트) → sat 0
- 판정기 Thought가 더는 "엔지니어 산출물 부재"를 불평 안 함 (P5 전엔 그게 0-satisfied 원인). iter1 Thought "코드 인용 기반으로 충족 매핑", iter5 "Three.js SPA 베이스라인 복원 — 대량 회복(satisfied 8)".
- run 내 추이 = 8→3→1→0→8 (단조 아님 — iter4 드리프트로 0 회귀 후 iter5 복원). "0→8"은 **런 간 대조**(P0P1P2 전부 0 → P5 8 도달).

> 적대 검증: 반증 실패(high). 8 satisfied 2건 모두 run_id=3f6318b2ba6d, 타 run 혼입 0.

## 2. ✅ P3 — 대폭 개선 (web 4/5), 단 1/5 잔존 드리프트

| iter | framework | 분류 |
|------|-----------|------|
| 1 | Three.js + web-ifc-three (TS SPA) 8파일 | ✅ web+BIM |
| 2 | Three.js + web-ifc-three (TS SPA) 7파일 | ✅ web+BIM |
| 3 | three.js+web-ifc-three (TS SPA) 14파일 | ✅ web (단 142B 얇은 산출) |
| 4 | **pyqt6 3파일** | 🔴 **드리프트** |
| 5 | typescript+threejs+web-ifc-three+vite 13파일 | ✅ web+BIM (복원) |

- iter4 드리프트 = 동일 **"사용자가 명시적으로 framework=pyqt6 지정" 날조**(13_gui_code_output.md:7) — 실제 요청은 "PyQt 절대 금지", CTO 전략도 web, judge 권고도 web (3중 web 신호 역행).
- P5/P1 가드가 iter5에서 web 복원(단일 iter 일탈로 격리) — *사후 교정*은 되나 *진입 차단*은 못 함(iter 1개 낭비, max=5에서 치명적).
- 지난 P0P1P2 런(generic web 1회뿐) 대비 명확한 개선.

## 3. ✅ P6 — BIM 본질 회복 (진짜 3D 뷰어)

iter1/iter5 산출은 generic 앱이 아닌 **진짜 BIM 3D 뷰어** (요청 3요소 충족):
- **IFC 로드**: `import { IFCLoader } from 'web-ifc-three/IFCLoader.js'` + `loadAsync(url)` + `setWasmPath('./')`(CDN 금지)
- **카메라 회전 ①**: `OrbitControls`(enableDamping) + top/front/side/iso 뷰 + fitView
- **클릭 속성 ②**: `Raycaster.setFromCamera→intersectObject` → IFC `expressID` → `getItemProperties`+`getPropertySets`(Pset Volume/Area/Material) → 속성 패널 + EdgesGeometry 하이라이트
- **다크 관제 ③**: `BG_BASE:'#0B0F14'` + 시안 액센트, "prefers-color-scheme 의도적 무시 — 관제센터 컨벤션 우선"
- WebGLRenderer + WebGL2 강제.

→ 지난 런(generic 에이전트 대시보드, three.js 0)과 천양지차. **P6 사실상 해소** (web 유지 시).

## 4. 🆕 P7 — 빌드 체인 web 미지원 (NEW 병목, 적대 검증 확정)

**.exe SKIP(exit=-5)은 코드 결함이 아니라 web↔Python 빌드 체인 미스매치다.** 3단계 메커니즘:
1. **entry 오선택**: `_select_entry_point`/`_detect_entry_hint`(build_workflow.py)는 확장자 개념 없음(.py만 가정). `_has_main_block`이 `ast.parse()`(Python 파서)로 .ts를 읽어 SyntaxError→False → 모든 web 파일 탈락 → `vite.config.ts`가 entry로 선택.
2. **Python 문법검사를 TS에 적용** (exit=-5 직접 원인): `_pre_pyinstaller_validation`이 `subprocess.run([sys.executable, entry])` = **"python vite.config.ts"** → line4 주석의 em-dash(`—`, U+2014)에서 `SyntaxError: invalid character` → 'SyntaxError' 패턴 매칭 → build 중단. (stderr의 mojibake가 Python이 JS를 읽은 직접 증거.)
3. **web 빌드 경로 부재**: `build_workflow.py` 전체에 `npm|vite build|node_modules|webpack` grep = **0건**. Executor는 PyInstaller→.exe만 안다.

**Build Spec→Executor 핸드오프 단절**: `21_build_spec.md`는 **이미 정답** — "PyInstaller는 적용 대상 아님", tool=Vite, "entry는 index.html→src/main.ts로 정정". 그런데 Executor가 이 결정을 **무시**하고 PyInstaller 강행.

**매 iter 동일 근본원인, 다른 표면증상**: iter1 entry=package.json→`pip install main` 실패(exit -4) / iter2 `python package.json` SyntaxError(-5) / iter3 valid entry 없음(-7) / **iter4 PyQt 드리프트만 .exe SUCCESS(35MB, exit 0)** / iter5 `python vite.config.ts`(-5). → **web 의도 런에서 .exe가 절대 안 나오는 구조**, .exe를 얻은 유일 iter는 플랫폼 위반(iter4).

> 적대 검증: 반증 실패(high). (a) .ts는 정상(em-dash는 합법 주석) (b) npm build 경로 부재 — 둘 다 확정.

## 5. BLOCKED 1차 원인 — P7 (+ P3 잔여 + QA 단일토큰)

8 satisfied / **1 blocker**로 cap 종료. 잔여 1 blocker는 **"동작하는 배포물/실행 검증"**이 가장 정합:
- iter5 retrospective "실행 verdict unknown — 빌드/런타임 검증 파이프라인이 결과 미확정(npm run build/정적 호스팅 smoke 누락 추정)"
- iter1/5 `24_platform_test_report.md` = FAIL(exit=-1), `25_executor_result.md` = PyInstaller FAILED
- result `blocked_cause=ITERATION_CAP`(BUILD_FAILED 아님), `exe_path=""` — 배포물 미확정 상태로 cap

> ⚠️ **신뢰도 medium (blocker 정체)**: gap report unsatisfied 원문(severity/id/reason)이 events output_preview 240자 절단 + standalone gap 파일 미보존으로 **literal 직접 인용 불가**. 판정은 Thought+retrospective+platform/executor 보고서의 수렴적 정황 근거 (기능 미구현이라는 반대 증거는 0).

**2·3순위 가중 요인**:
- **P3 잔여**: iter4 드리프트가 satisfied를 0으로 리셋 → stagnation 기여 + iter 1개 낭비(max=5).
- **QA 단일토큰**: 5 iter 전부 Code Reviewer가 `"NEEDS_REVISION"` 1단어만 받아 **영구 [BLOCKER]** 생성(PR #28/#30/#32 재현) → QA verdict NEEDS_REVISION 고착 → **APPROVED 불가 → COMPLETE 경로 차단**. (이전 verdict는 P4를 *cap-cause* 비인과로 하향했으나, *COMPLETE 도달 게이트*로서는 다시 유효.)
- 부수: retrospective에 kickoff 합의 미주입(`(킥오프 합의 없음)`)인데 실제 `shared_kickoff_decisions.yaml`은 풍부 — 컨텍스트 전달 누락.

---

## 🛡 적대 검증 (3 refuter)

| 주장 | 결과 | 결론 |
|------|------|------|
| "P5 작동, satisfied 0→8" | 반증 실패 (high) | **유지** — 8 satisfied×2 모두 이 run |
| "NEW P7 = 빌드 체인 web 오인" | 반증 실패 (high) | **유지** — .ts 정상+npm 경로 0, Python으로 .ts 실행한 미스매치 |
| "잔여 blocker = 배포물(P7 원인)" | 반증 실패 (medium) | **지지** — literal 미확보(절단)이나 정황 수렴, 반대증거 0 |

---

## 🧭 판정

> **P5 작동 + satisfied 0→8 확정. P3(4/5)·P6(BIM 본질) 대폭 회복.** 남은 확정 병목 = **🆕 P7(빌드/배포 체인 web 미지원, 1순위·COMPLETE의 진짜 벽) + P3 잔여 드리프트(1/5) + QA 단일토큰(COMPLETE 게이트)**. P5 추가 작업 불요.

태스크 분기 기준 — **"P5 작동 + satisfied 0→증가 확정 → 남은 확정 병목"** 에 해당하되, 남은 병목은 P3+P6이 아니라(P6는 이번에 회복) **P7(신규)+P3 잔여+QA**.

---

## 🔧 처방 권고 (우선순위)

### P7 (최우선·NEW) — 빌드/Executor 체인 web-awareness (COMPLETE의 진짜 벽)
- `_select_entry_point`/`_detect_entry_hint`/`_pre_pyinstaller_validation`/`execute_pyinstaller`가 `code_files` 확장자·프로젝트 종류(package.json/vite.config/.ts 존재) 감지 → **web이면 PyInstaller 분기 스킵**, `npm ci && npm run build → dist/`(또는 정적 호스팅 산출)을 "동작 배포물"로 인정.
- **Build Spec→Executor 핸드오프 배선**: `21_build_spec.md`의 `tool=vite`/entry 정정 결정을 Executor가 신뢰하도록 (이미 정답을 내는데 무시당함).
- 부수: 엔지니어가 package.json 미산출하는 갭(20_dependency_report "package.json 미제공") 보강.

### P3 잔여 — GUI Code Generator 드리프트 진입 차단
gui_code 생성 직후 web 마커 위반(pyqt/qapplication) 시 **iter 소모 없이 즉시 reject+재생성**. "사용자가 명시 PyQt" 류 날조 근거 거부.

### QA 단일토큰 — Code Reviewer 입력에 실제 코드/diff 첨부
1단어 verdict만 넘기는 어댑터 수정 → 영구 [BLOCKER] 제거 → APPROVED 경로 개방. (COMPLETE 도달 필수 게이트.)

### 부수 — retrospective에 kickoff 합의 주입

---

## 결론 한 줄
**P0→P5로 종료·드리프트·extraction·판정기 가시성을 차례로 고친 결과, 시스템이 이제 *판정기가 보는*(P5, 8 satisfied) *진짜 web BIM 3D 뷰어*(P6 회복)를 *대부분 web 유지*(P3 4/5)하며 산출한다. COMPLETE 직전의 마지막 벽은 🆕 P7 — 빌드/배포 체인이 web을 못 빌드해(PyInstaller에 .ts를 먹임) 동작 배포물이 안 나오는 것. 다음 = P7(빌드 체인 web 라우팅) 최우선 → P3 잔여 → QA 단일토큰.**

---

## 방법론 + 관련 문서
- 워크플로 `p5-rerun-verdict` (8 에이전트): 5 증거(P5-satisfied/P3-drift/P6-domain/P7-build/BLOCKED) + 3 적대 검증. 파일경로:라인+원문 인용. READ-ONLY.
- [phase6e_rerun_P0P1P2_verdict_20260529.md](phase6e_rerun_P0P1P2_verdict_20260529.md) · [phase6e_rerun_P0P1_verdict_20260529.md](phase6e_rerun_P0P1_verdict_20260529.md) · [phase6e_rerun_crash_analysis_20260529.md](phase6e_rerun_crash_analysis_20260529.md)
