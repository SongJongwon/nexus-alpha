# 🧪 Phase 6.E BIM 라이브 재실행 — Verdict 채점 리포트

> ※ **본 리포트는 2026-05-28 1차 런(A+B 머지 前, INVALID) 채점이다. 2026-05-29 재실행 verdict는 별도 문서로 작성된다.**

> **작성일**: 2026-05-29
> **작성자**: Claude Opus 4.8 (채점 세션) — 멀티 에이전트 워크플로 9 에이전트 (6 증거 + 3 적대적 검증)
> **프로토콜**: [next_session_context.md](../next_session_context.md) §PENDING 1순위 — A+B 결합 효과 5점 채점 + 베타/C/D 분기
> **대상 런**: `run_id=53adfbf5da76` (`outputs/alpha_run_20260528_155507/`)
> **제약**: READ-ONLY 채점. 패치/커밋/빌드/pytest 실행 **없음**.

---

## ⭐ TL;DR — 한 줄 결론

> **❌ 이 런은 A+B 검증으로 무효(INVALID)다.** 런이 PR #231/#232 머지 **이전**에 실행됐고, 산출물에 A/B 행동 시그니처가 **0건**이다. 즉 이 런은 A+B의 *효과를 검증한 런이 아니라*, **A+B를 만들게 한 BEFORE(baseline) 사고 그 자체**다. → **1순위(A+B 결합 효과 검증)는 아직 미충족 → 베타 보류 → 재실행 필수.**

**부수 확정**: A+B가 막으려던 바로 그 퇴행(iter1 BIM 본질 → iter2 일반 GUI)이 이 런에서 **재현**됐다. 이는 A+B의 *필요성*을 강화하지만, A+B가 *작동하는지*는 여전히 미검증.

---

## 🚨 채점을 뒤집은 결정적 사실 — 타임라인

| 사건 | 시각 (KST) | 근거 |
|------|-----------|------|
| BIM 라이브 런 실행 | **2026-05-28 15:55 ~ 17:15** | events.jsonl:161 (run_start 06:55:19Z) / :248 (run_end 08:14:55Z) |
| PR #231 (A: Rule 0 wire) main 머지 | **2026-05-29 09:22:05** | git committer date, commit `8c4c1f4` |
| PR #232 (B: iter간 코드 첨부) main 머지 | **2026-05-29 09:35:03** | git committer date, commit `79e634a` |

→ **런이 A+B 머지보다 약 16–17시간 빠르다.** PM 로컬 브랜치에서 머지 전 코드로 실행했을 가능성은 타임스탬프만으로 배제 불가하므로, **행동 시그니처**(아래 조건 2·3)가 결정적 증거다 — 그리고 둘 다 **부재**다.

> ⚠️ **사용자 전제 정정**: 채점 지시는 "루트 `events.jsonl` = 이번 라이브 런 산출물"이라 했으나, 루트 `events.jsonl`은 mtime **2026-05-27 17:28**의 "계산기" 런 잔여물이다. 실제 BIM 런 데이터는 **`outputs/events.jsonl`** (mtime 2026-05-28 17:14)에 있다. 본 리포트는 후자를 채점했다.

> ⚠️ **추가 편차**: 핸드오프 검증 명령은 `--max-iterations 5`였으나, 실제 런은 **max_iterations=3** (events.jsonl:161). 2 iter 만에 BLOCKED 종료.

---

## 📊 5점 채점표

| # | 조건 | 점수 | 신뢰도 | 핵심 근거 |
|---|------|:----:|:------:|----------|
| 1 | iter 1이 BIM 본질 산출 (viewport.py + WebGL + Three.js + OrbitControls + PerspectiveCamera) | ✅ **PASS** | high | 6 키워드 전부 `viewport.py`에 verbatim 존재 |
| 2 | iter 2+ Engineer prompt에 이전 iter 코드 발췌 (옵션 B) | ❌ **FAIL** | high | B 마커 0건, prompt 13716자 < iter1 18868자, B는 런 18h 후 머지 |
| 3 | iter 1이 미충족 시 Rule 0 강제 IMPROVE (옵션 A) | ❌ **FAIL** | high | `domain_checklist`/"도메인 체크리스트" 0건, IMPROVE는 순수 GAP 기반(STAGNATION) |
| 4 | A+B 결합이 PR #226 단독보다 BIM 본질 보존률 ↑ | ❌ **FAIL / N/A** | high | A+B 미작동 → 비교 불가, 오히려 퇴행 재현 |
| 5 | .exe가 진짜 3D 모델 표시 (자율 런 기준) | ❌ **FAIL** | high | 자율 exe = 일반 GUI, 3D는 매뉴얼 빌드에만, Vision QA SKIPPED |

**종합: 1 PASS / 4 FAIL → A+B 검증으로 ❌ INVALID.**

---

## 🔬 조건별 상세 + 인용 근거

### ✅ 조건 1 — iter 1 BIM 본질: **PASS** (high)

iter 1은 3D BIM 뷰어의 본질(3D 렌더 + 카메라 회전 + 클릭 속성 + 다크 관제 스타일)을 코드로 **완전히** 담았다. `viewport.py`가 `QWebEngineView` 안에 Three.js HTML을 임베드하고, `WebGLRenderer`/`PerspectiveCamera`/`OrbitControls`로 3D·카메라를, `Raycaster`로 클릭 picking을 구현. Python 브릿지(`on_object_picked`)→`property_panel.show_properties`로 IFC 속성 표 연결.

> ⚠️ 단, iter1 산출 스택은 **PyQt6 데스크톱**인데, 킥오프 합의는 **TypeScript + web-ifc-three SPA**였다 → 플랫폼 드리프트(조건 5·아래 추가결함 참조). 그래도 "3D BIM 본질" 키워드 채점 기준으로는 PASS.

**인용**:
- `00_user_request.txt:1` — "3D BIM 건축 모델 뷰어: Three.js + BIM 라이브러리 사용. 카메라 회전, 클릭 시 속성 표시, 다크 모드 관제 센터 스타일"
- `workflow_20260528_155627/code/viewport.py:53` — `import * as THREE from 'three';`
- `viewport.py:54` — `import { OrbitControls } from 'three/addons/controls/OrbitControls.js';`
- `viewport.py:61` — `const camera = new THREE.PerspectiveCamera(`
- `viewport.py:65` — `const renderer = new THREE.WebGLRenderer({ antialias: true });`
- `viewport.py:70` — `const controls = new OrbitControls(camera, renderer.domElement);`
- `viewport.py:131` — `const ray = new THREE.Raycaster();`
- `viewport.py:196` — `self.webview = QWebEngineView()`
- `property_panel.py:32` — `"Door_004": {"Name": "Door_004", "Type": "IfcDoor", "Material": "목재"}`
- `theme.py:10` — `# Palette — Dark Mode (관제 센터 기본)`

### ❌ 조건 2 — 옵션 B (iter간 코드 발췌): **FAIL** (high)

B가 주입하는 고정 마커("## 이전 iteration 산출 코드", "기존 구조와 식별자... 최대한 유지", "백지에서 다시 작성하는 것은 퇴행", "--- 이전 iter 코드 발췌 ---")가 run 53adfbf5da76 이벤트 전 구간 **0건**. iter2 엔지니어 prompt에는 오직 GAP 텍스트("must-fix 잔여: 5 blocker(s) + 4 major(s)")만 존재 → 과제가 정의한 FAIL 기준에 정확히 부합. **prompt_length 역증거**: iter2 코드생성 prompt = **13,716자** < iter1 = **18,868자**. B가 발동해 ~15k 코드를 첨부했다면 iter2가 더 길어야 하나 오히려 짧다.

**인용**:
- events.jsonl:204 — `## 이전 iteration 보정 지시\n- must-fix 잔여: 5 blocker(s) + 4 major(s) (총 9건)` ← GAP만, 코드 발췌 없음
- events.jsonl:211 — iter2 GUI 코드생성 `prompt_length: 13716`, preview는 "## 📌 킥오프 회의 합의 사항"으로 시작 (이전 코드 블록 부재)
- events.jsonl:176 — iter1 동일 단계 `prompt_length: 18868`
- `git show 79e634a` — PR #232 머지 `2026-05-29 09:35:03 +0900` (런보다 18h 후), 커밋 메시지가 *이 런의 iter2 퇴행*을 B 도입 root cause로 인용

### ❌ 조건 3 — 옵션 A (Rule 0 강제 IMPROVE): **FAIL** (high)

run 53adfbf5da76 전체에서 `domain_checklist`/`engineer_output_excerpt`/"도메인 체크리스트"/"Rule 0"/"Rule -1" **0건**. `judge_convergence` 이벤트(iter1/iter2)는 working/done 상태만 기록, 페이로드 전무. IMPROVE 강제는 오직 `analyze_gap`의 GAP 기반("0 satisfied, 10 unsatisfied, blocker=5")으로 발생했고, 종료 사유는 **STAGNATION**(2 iter 연속 gap 무변화)이지 도메인 체크리스트 미충족이 아니다.

**근본 원인(코드 차원)**: Rule 0 로직은 PR #226에 존재했으나, 그것을 호출하는 wire(`iterative_loop.py`에 `domain_checklist=` 주입)는 **PR #231에서야 추가**됐고 이는 런 이후다. iter1 QA BLOCKER는 "NEEDS_REVISION 단일 토큰" systematic failure(PR #28/#30/#32 패턴)이지 Rule 0가 아니다. precondition(iter1 = isometric 2D)도 미발생(iter1은 진짜 3D였음).

**인용**:
- events.jsonl:197 — `gap report — 0개 satisfied, 10개 unsatisfied (blocker=5) ... 언어·플랫폼 드리프트`
- events.jsonl:236 — `... stagnation=true ... resolved_since_last=0`
- events.jsonl:247 — `verdict=BLOCKED(STAGNATION) iterations=2/3 — 진행 정체`
- `src/agents/c_level/convergence_judge.py:124` — "호출자가 `domain_checklist=` 주입 안 하면 항상 []"
- `git blame iterative_loop.py:1578` — `8c4c1f44 (2026-05-29 09:22:05)` ← A wire 추가 시점 = 런 이후
- `git show 8c4c1f4` (PR #231) — "Rule 0 가 침묵한 원인: PR #226 머지 시 코드만 머지, workflow wire 0건"

### ❌ 조건 4 — A+B > PR #226: **FAIL / N/A** (high)

A·B 둘 다 이 런에서 미작동(조건 2·3)이므로 "A+B 결합 효과"를 PR #226 단독과 **비교할 표본 자체가 없다.** 정성 판단: A+B가 적용되지 않은 이 baseline에서 BIM 본질 퇴행(iter1 viewport.py → iter2 일반 GUI)이 그대로 발생했다 → A+B의 *필요성*은 입증되나 *효과*는 미입증. 따라서 "보존률 ↑" 주장은 이 런으로 뒷받침 불가.

### ❌ 조건 5 — .exe 진짜 3D 표시 (자율 런 기준): **FAIL** (high)

**반드시 두 빌드를 구분**:

| | 자율 런 빌드 | 매뉴얼 빌드 |
|---|---|---|
| 경로 | `workflow_20260528_163248/build_output/dist/App.exe` | `outputs/bim_viewer_manual_build/dist/BIM-Viewer/BIM-Viewer.exe` |
| 소스 | iter2 code (app/main_window/**styles/widgets**) | PM 손수정 viewport.py + Three.js vendor 번들 |
| 3D? | ❌ 일반 PyQt6 GUI (입력창·로그·설정 폼) | ✅ 진짜 3D (PM 스크린샷 확인) |
| 의존성 | PyQt6 단독, **QtWebEngine 훅 없음** | PyQt6-WebEngine 수동 보충 |

자율 exe는 Three.js/WebGL/QWebEngineView/viewport/camera/gltf/ifc가 **0줄**인 범용 셸이다. Vision QA는 `ANTHROPIC_API_KEY` 미설정으로 **SKIPPED** → 화면이 요구사항 대비 평가된 적이 없다. 진짜 3D는 **매뉴얼 빌드에서만** 존재하며, 이는 자율 루프 산출이 아니라 PM의 git-ignored 복구 트랙이다.

**인용**:
- `workflow_20260528_163248/code/widgets.py:21` — `title = QLabel("자연어 → 실행 파일 변환")` (BIM 무관 일반 GUI)
- `13_gui_code_output.md:1` — `framework=PyQt6, files=4개, entry=python app.py`
- `25_executor_result.md:5` — `direct_dependencies: 1개 (PyQt6)` / QtWebEngine 훅 없음
- `25_executor_result.md:37` — `[EXE_SMOKE_TEST] PASS — 3.10s alive` (3D 검증 아님, mainloop 생존만)
- `vision_qa/summary.txt:1` — `[GUI_TEST SKIPPED] Vision API 미평가 — ANTHROPIC_API_KEY 미설정`
- `app.py:9` — `app.setApplicationName("Nexus Alpha GUI")` ← test_app.py가 기대한 "BIM Viewer"와 미스매치
- `WORK_STATUS.md:63` — "모델 로드 + 카메라 작동 ✓ (PM 스크린샷 — BIM 건축 모델 정상 표시)" ← **매뉴얼 빌드** 기준

---

## 🛡️ 적대적 검증 결과 (3 refuter, 전부 high)

| 검증 대상 주장 | 반증됐나 | 결론 |
|----------------|:--------:|------|
| "B는 이 런에서 미작동" | ❌ 반증 실패 | **주장 유지** — B 마커 0, prompt 길이 역증거, 머지 18h 후 |
| "A는 이 런에서 미작동" | ❌ 반증 실패 | **주장 유지** — domain_checklist 0, STAGNATION만, wire 런 후 머지 |
| "자율 exe가 진짜 3D 표시" | ❌ 반증 실패 | **주장 거짓** — exe는 일반 GUI, 3D는 매뉴얼 빌드만 |

→ 세 핵심 결론(A 미작동 / B 미작동 / exe ≠ 3D)이 적대적 검증을 모두 통과(반증 시도 실패).

---

## 🧭 분기 권고

프로토콜 분기(✅PASS→베타 / ⚠️부분→C·D / ❌FAIL→재시도) 중 **❌에 해당하되, "fix가 실패"가 아니라 "fix가 테스트되지 않음"**이라는 점이 핵심이다.

### 1순위 (필수) — 🔁 A+B 재실행 (베타 보류)
1순위(A+B 결합 효과 검증)는 **미충족**. 베타 cohort 배포는 **보류**. 재실행 조건:
- **머지된 main**에서 실행 (A+B 코드 존재 확인 — `git log`로 #231/#232 포함 확인)
- `--max-iterations 5` (이번엔 3이었음), `--enable-tech-scout`
- **`ANTHROPIC_API_KEY` 설정** — 안 하면 조건 5(Vision QA)는 영구히 검증 불가
- **검증 게이트(이번엔 0건이었던 시그니처가 이번엔 나와야 함)**:
  - events.jsonl에 `domain_checklist` 페이로드 + "도메인 체크리스트 N/M 미충족" (A 발동)
  - iter2 prompt에 "## 이전 iteration 산출 코드" + viewport.py 본문 + prompt_length **증가** (B 발동)

### 2순위 (재실행과 무관하게 부상) — 🆕 플랫폼 드리프트 가드레일
이 런이 드러낸 **A+B가 직접 못 막는 새 root cause**: 킥오프는 web/Three.js/IFC.js SPA를 합의했으나 엔지니어가 PyQt6 데스크톱으로 이탈. 런의 retrospective 자체가 처방을 제안한다:
> `retrospective.md:14` — "GUI 코드 생성 에이전트 프롬프트에 'kickoff.platform == web 이면 PyQt6/Tkinter 금지, Three.js + Vite 스캐폴드 강제' 가드레일 추가"

이 가드레일(S 비용)은 **D 처방(Product Manager, L 비용)보다 싸고 타깃이 정확**하다. D는 비전 일관성 추가 안전망으로 여전히 후순위 유효.

### 보류 유지 — C 처방 (dependency_analyzer Qt sub-package)
C의 진입 트리거(PyQt6-WebEngine 누락 → BUILD_FAILED)는 **이번 런에서 재발하지 않았다.** iter1 BIM 코드는 빌드 단계 이전에 QA가 BLOCK했고, 실제 빌드된 iter2는 평범한 PyQt6라 webengine 의존이 없었다. → **C는 backlog 유지** (다음 *진짜 A+B 런*에서 iter1 BIM 코드가 빌드까지 가면 그때 트리거 가능).

---

## 📌 부수 발견 (운영 갭)

1. **Vision QA가 SKIPPED** (`ANTHROPIC_API_KEY` 미설정) → 자율 루프가 "화면이 요구사항을 충족하는지"를 자가 검증 못 함. 재실행 시 필수 설정.
2. **루트 `events.jsonl` gitignore 갭** — `outputs/events.jsonl`만 ignore되고 루트 동명 파일은 추적됨. 혼동(이번 채점 전제 오류) 유발. 정리 권고.
3. **`app.py` 앱 이름 미스매치** — iter2 코드가 `"Nexus Alpha GUI"`로 설정, test_app.py는 `"BIM Viewer"` 기대 → 엔지니어/테스터 cross-agent 불일치도 잔존.

---

## 9. 채점 방법론 (재현 가능성)

- 멀티 에이전트 워크플로 `bim-live-rerun-verdict` (9 에이전트): 6 증거 추출(조건1·B·A·구조diff·조건5·메타활성화) 병렬 + 3 적대적 검증 병렬.
- 모든 점수는 파일경로:라인 + 원문 인용으로 뒷받침. READ-ONLY (수정/빌드/실행 없음).
- 1차 채점 세션 인라인 스카우팅(타임라인·verdict·시그니처)으로 ground-truth 후 위임.

## 10. 관련 문서
- [next_session_context.md](../next_session_context.md) — 1순위 프로토콜
- [phase6e_iteration_regression_diagnosis.md](phase6e_iteration_regression_diagnosis.md) — 원 진단 (4 root cause)
- [phase6e_followups.md](../backlog/phase6e_followups.md) — C/D 보류 처방
- [WORK_STATUS.md](../WORK_STATUS.md) — 매뉴얼 빌드 트랙 기록
