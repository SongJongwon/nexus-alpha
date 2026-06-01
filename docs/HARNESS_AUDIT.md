# 하네스 엔지니어링 감사 — 오케스트레이션/스캐폴딩 계층

> **범위**: LLM 에이전트를 감싸는 오케스트레이션 계층 — `scripts/run.py` → `iterative_loop`(LangGraph) → workflows(recall→kickoff→chain→sandbox→gap→judge→retro→curate) + 복구 메커니즘(retry/converter_rescue/degenerate/salvage/verdict 판정).
> **방식**: 8개 차원(구조·복구 일관성·실패 처리·설정/임계값·테스트·관측성·기술부채 + ★단축출력 포렌식)을 8 에이전트가 READ-ONLY로 file:line + 위험도 인용. 본 문서는 그 종합.
> **결과물**: 정직한 평가(강점 + 문제) + 우선순위 권장. **코드 변경 없음 — 감사/문서 전용.** 기준일 2026-06-01.
> ⚠️ 인용 라인 번호는 감사 시점 스냅샷 기준 — 함수/근방 식별용(미세 오프셋 가능).

---

## 0. 경영진/리드 요약

**한 줄 평결: "규율 잡힌 솔기(seam), 누적된 몸통(body)".** P0~P15 패치는 *개별적으로는* 모범적입니다(전부 default-OFF/web-scoped + "회귀 0" 보장 + PR 출처 + 전용 회귀 테스트). 그러나 오케스트레이션 *코어*는 복잡도 임계를 넘어서, **최종 verdict가 4~5곳에서 작성**되고(단일 우선순위표 부재), **복구가 비결정적 에이전트를 원천에서 제약하지 않고 하류에서 보상**하며, 판별자(predicate)·설정·관측성 표면이 파편화됐습니다. *썩은 누더기는 아니지만*, 지금이 **통합(consolidation)의 변곡점**입니다.

**★ "왜 55자 단축 출력이 여러 P를 거쳐도 iteration을 계속 깨뜨리나"** — 근본원인 확정(아래 §4):
> **단축 가드가 잘못된 양을 측정합니다.** `retry_task_if_short`는 `GUICodeOutput.to_markdown()`의 *전체 직렬화 길이*를 잽니다([_common.py:124-126](src/workflows/_common.py#L124)). 그런데 P-시대에 `output_pydantic` 스키마가 LLM에게 *산문 필드*(summary/framework_choice/integration_guide)를 채우도록 강제하면서, 실패 양상이 "Final Answer 한 줄(진짜 짧음)"에서 **"산문 필드는 길지만 `code_blocks`는 비어 있음"**으로 *이동*했습니다. → `to_markdown()`은 120자를 훌쩍 넘김 → 가드는 "충분히 김, OK" → **재시도 안 함** → 추출 코드 0개 → degenerate. P14는 이를 *탐지*만 하고(`13d_generation_failed.txt` 파일만 씀, 재생성 안 함), P15는 *완화*만 합니다(과거의 더 나은 iteration 채택, 코드를 만들어내진 못함). **플랫폼 드리프트엔 원천 재생성 루프(`_regenerate_until_clean`)가 있는데, degenerate엔 그 짝이 없습니다.** 그래서 탐지+우회는 되지만 *원천 예방*은 전무합니다.

---

## 1. 차원별 점수표

| # | 차원 | 평결 | 최고 위험 |
|---|------|------|-----------|
| 1 | 구조 / 응집도 | 🟡 mixed (ad-hoc 경향) | 빌드 *실행*이 "결정론" judge 노드 안에서 일어남; iterative_loop 2,493줄 god-module |
| 2 | 복구 메커니즘 일관성 | 🟡 mixed | 4종 web/GUI 판별자 불일치; judge 솔기에 4스테이지 verdict 재작성; 예방 지점은 2곳뿐 |
| 3 | 실패 처리 | 🟡 mixed | **코어 `compiled.invoke`에 except 없음** — 유일하게 크래시가 새는 곳 |
| 4 | 설정 / 임계값 | 🟡 mixed | 동일 개념 2값(max-iter 3↔5, web build 300↔600); 중앙 config 없음; budget gate 死 |
| 5 | 테스트 커버리지 | 🟢 well-disciplined (통합 갭 1) | 다중-iteration loop-back E2E 부재; `_resolve_best_output` 배선 통합 미검증 |
| 6 | 관측성 | 🟡 mixed | 복구 *결정*(override/salvage/best-iteration/degenerate)이 이벤트로 안 보임; ResultEvent가 오도(`iterations_run`=마지막, 채택 iter 아님) |
| 7 | 기술 부채 | 🟡 mixed (솔기 OK, 몸통 누적) | verdict 5스테이지 재작성; 3종 GUI 마커셋 불일치; dead budget gate |
| ★ | 단축출력 포렌식 | 🔴 ad-hoc-accretion | 원천 예방 0 — detect(P14)+mitigate(P15)뿐; 가드가 추출 코드가 아닌 총길이 측정 |

---

## 2. 차원별 정직한 평가

### 1) 구조 / 응집도 — 🟡 mixed

**잘 된 것**
- `run.py` → `run_iterative_loop` 위임이 깔끔. `_run_track_a`는 얇은 드라이버, 재구현 아님([run.py:608-633](scripts/run.py#L608)).
- Convergence Judge의 결정표/내레이션 분리가 명시적 SRP — `judge_convergence`(LLM 무관 결정표) vs `create_convergence_judge_agent`(verdict 절대 안 뒤집음)([convergence_judge.py:5,16-18](src/agents/c_level/convergence_judge.py#L5)). natural/guarded 분리(`_judge_convergence_natural` vs 공개 `judge_convergence`)는 교과서적.
- 텔레메트리가 노드에 박히지 않고 래퍼로 분리([iterative_loop.py:2108-2117](src/workflows/iterative_loop.py#L2108) `_telemetry_wrap`).
- 빌드 *실행*은 `build_workflow.py`에 적절히 위치([build_workflow.py:474](src/workflows/build_workflow.py#L474) `_run_web_build`).

**문제**
- 🔴 **빌드 실행이 judge 결정 경로 안에 있음.** `_maybe_salvage_web_build`가 `_node_judge_convergence`에서 호출되어([iterative_loop.py:2032](src/workflows/iterative_loop.py#L2032)) 실제 npm 서브프로세스를 수 분간 돌림([iterative_loop.py:1719-1722](src/workflows/iterative_loop.py#L1719)). "결정표 호출(LLM 무관)" 노드 원칙 위반. → salvage를 judge↔finalize 사이 *전용 그래프 노드*로 분리.
- 🔴 **god-module**: `iterative_loop.py` 2,493줄. web 빌드 에러 파싱/분류(`_parse_web_build_errors`/`_ts_fix_hint`/`_is_type_only_failure`/`_is_web_build_result`, [:1459-1563](src/workflows/iterative_loop.py#L1459))가 *빌드 도메인*인데 iteration 컨트롤러에 거주, `build_workflow.py`와 중복 도메인. → `web_build_recovery.py` 추출.
- 🟡 **verdict 4곳에서 작성** — judge → `_apply_build_failure_override`(COMPLETE→IMPROVE/BLOCKED) → `_maybe_salvage_web_build`(BLOCKED→COMPLETE) → `_resolve_best_output`(또 COMPLETE 합성, [:1842-1852](src/workflows/iterative_loop.py#L1842)).
- 🟡 `_node_runtime_verify`가 RV+아티팩트+Strategist+Boardroom 4책임([:1145-1238](src/workflows/iterative_loop.py#L1145)). `run_analyze_and_implement` 340줄 분기 monolith.
- 🟢(낮음) dead code 잔존: `_pick_entry_file`이 "더 이상 호출 안 됨" 주석과 함께 보존([:383-388](src/workflows/iterative_loop.py#L383)).

### 2) 복구 메커니즘 일관성 — 🟡 mixed

**메커니즘 분류** (각 복구가 무엇을 하는가):
| 메커니즘 | 유형 | 위치 |
|---|---|---|
| `retry_task_if_short`/`retry_short_tasks_in_chain` | RETRY-in-place | _common.py:100/161 |
| `task_output_text` 단축 경고 | DETECT-only | _common.py:81 |
| `kickoff_with_converter_rescue` | SALVAGE | _common.py:201 |
| `_maybe_regenerate_on_platform_drift`/`_regenerate_until_clean` | **RETRY-in-place(원천)** | analyze_and_implement.py:1070/1030 |
| `_build_web_platform_directive`(첫 생성 주입) | **PREVENT** | :1183 |
| `_is_degenerate_codegen` | DETECT-only | :393 |
| `_ensure_web_manifests` | SALVAGE→synthesize | :471 |
| `_apply_build_failure_override` | LOOP-back(web)/MITIGATE(desktop) | iterative_loop.py:1575 |
| `_maybe_salvage_web_build` | SALVAGE(vite-only) | :1680 |
| `_resolve_best_output` | MITIGATE | :1811 |
| 판정 cap 가드(judge post + router) | **PREVENT** | convergence_judge.py:502 + iterative_loop.py:2097 |

**핵심 통찰**: *진짜 PREVENT 지점은 2곳뿐*(첫 생성 web 제약 + iteration cap). 나머지는 전부 두 솔기(코드젠 후 / judge 후)에 붙은 하류 DETECT/RETRY/SALVAGE/MITIGATE. **비결정적 코드젠 에이전트를 원천에서 제약하지 않고 사후 보상**하는 아키텍처.

**잘 된 것**: 단축 패밀리의 DETECT(`task_output_text` 경고)/RETRY(`retry_task_if_short`) 분리가 명시적([_common.py:54](src/workflows/_common.py#L54)); 재생성이 *intra-iteration*이라 카운터 불변 명문화([iterative_loop.py:1048](src/workflows/iterative_loop.py#L1048)); `detect_desktop_markers` 3곳 재사용("새 ad-hoc substring 금지", [:1020](src/workflows/iterative_loop.py#L1020)) — predicate sprawl에 *저항*한 좋은 반례.

**문제**
- 🟡 **web/GUI/desktop 판별자 4종이 입력·멤버십이 달라 서로 불일치 가능**: (1) `_DESKTOP_GUI_MARKERS` 서브스트링(judge/P3/P2-B), (2) `_GUI_TOP_LEVEL_MODULES` AST셋+서브스트링 폴백(sandbox-skip; pygame/kivy/wx 포함), (3) `_is_web_project` 파일/확장자([build_workflow.py:358](src/workflows/build_workflow.py#L358)), (4) `_is_degenerate_codegen`. **kivy import 앱은 sandbox엔 "GUI"지만 judge 드리프트 검사엔 안 보임.** → 단일 `platform.py`로 통합.
- 🟡 **"출력이 깨졌나"를 3가지 임계로 3번 계산**: `SUSPICIOUS_OUTPUT_THRESHOLD=120`(char), `_MIN_GUI_CODE_BYTES=200`(byte), `_detect_extraction_loss`(헤더수). 공유 정의 없음.
- 🟡 web-build 결과 판정이 **매직 exit code 결합**: `exit_code == -8`([iterative_loop.py:1526](src/workflows/iterative_loop.py#L1526) ↔ 생산자 [build_workflow.py](src/workflows/build_workflow.py)). → `ExecuteResult.kind` 필드로.
- 🟢(낮음) pytest-skip 관례 3가지 혼재(`"pytest" in sys.modules` early-return vs 경고만 억제 vs 주입 의존). P2-B↔P1 near-conflict를 `if platform_intent=="web"` 분기로 *특수처리* 해소([:814](src/workflows/iterative_loop.py#L814)).

### 3) 실패 처리 — 🟡 mixed

**잘 된 것**: sandbox 서브프로세스 timeout 처리 교과서적(`TimeoutExpired`→구조화 결과+`finally` force-kill, [sandbox_runner.py:169-191](src/agents/operations/sandbox_runner.py#L169)); YAML parse 실패 → `ValueError` → 호출부 빈 `GapReport` 폴백([iterative_loop.py:1439-1442](src/workflows/iterative_loop.py#L1439)); 텔레메트리는 절대 메인 차단 안 함(fail-quiet, [telemetry.py:299-311](src/monitoring/telemetry.py#L299)); `_telemetry_wrap`은 에러 emit *후 재-raise*(삼키지 않음); **과거 fail-silent 버그를 fail-loud sentinel로 교정**(`CodeQASkipped(skip_reason=...)`, [automate_workflow.py:979-996](src/workflows/automate_workflow.py#L979)) — 규율의 강한 증거.

**문제**
- 🔴 **코어에 실패 경로 없음**: `_node_run_chain`→`run_analyze_and_implement` 무방비([iterative_loop.py:935](src/workflows/iterative_loop.py#L935)), `compiled.invoke`도 `finally`만 있고 `except` 없음([:2408,2476](src/workflows/iterative_loop.py#L2408)). 깊은 실패(provider 에러, OSError, GraphRecursionError)는 raw traceback으로 빠져나가 **LoopOutcome도, escalate 아티팩트도, curated 지식도 없음**. 유일 backstop은 run.py:1292의 `except`. → `compiled.invoke`를 try/except로 감싸 `BLOCKED(INTERNAL_ERROR)` LoopOutcome 합성(다른 실패 모드와 일관되게).
- 🟡 `_pre_pyinstaller_validation`이 **fail-open**: timeout/일반 except가 `return True`([build_workflow.py:1524-1528](src/workflows/build_workflow.py#L1524)) — "검증 못 함"을 "검증 통과"로 보고.
- 🟡 RV/strategist/boardroom 경로가 `except Exception: pass` 스택([iterative_loop.py:1227-1230](src/workflows/iterative_loop.py#L1227)) — 기능이 매 iter 실패해도 집계 신호 없음. → `except` 팔에서 `agent_error` 이벤트 emit.
- 🟢(낮음) `task_output_text`/`retry_task_if_short`가 렌더/kickoff 실패를 무로깅 삼킴; ~90개 `except Exception # noqa: BLE001` 중 상당수가 변수·메시지 없이 `""`/`continue` — *스타일*은 균일하나 *보존 정보*는 불균일(누적의 징후).

### 4) 설정 / 임계값 — 🟡 mixed

**잘 된 것**: 핵심 안전 한도는 rationale 달린 명명 상수(`DEFAULT_MAX_ITERATIONS=5`+design-doc 근거, `NO_BUDGET_GATE`, [convergence_judge.py:143-150](src/agents/c_level/convergence_judge.py#L143)); `SUSPICIOUS_OUTPUT_THRESHOLD`는 단일 출처+테스트 박제; `recursion_limit`은 매직넘버 아닌 `max(50, max_iter*7+10)` 유도식([iterative_loop.py:2405-2408](src/workflows/iterative_loop.py#L2405)).

**문제**
- 🟡 **동일 개념 2값(드리프트 위험)**: CLI `--max-iterations` default=**3**([run.py:1178-1185](scripts/run.py#L1178)) vs 라이브러리 `DEFAULT_MAX_ITERATIONS`=**5** — judge docstring은 "5회" 근거인데 제품은 3 cap. / 같은 npm 빌드가 메인 경로 timeout **300** vs salvage 경로 default **600**([build_workflow.py:474-480](src/workflows/build_workflow.py#L474)). / engineer-excerpt cap 15k vs 30k.
- 🟡 `executor_timeout_sec=300`/`publish_timeout_sec=120`이 3+ 시그니처에 인라인 반복, **CLI 노출 0** — 큰 앱 PyInstaller 빌드 5분 초과 시 소스 편집 외 방법 없음.
- 🟡 RV startup timeout이 인라인 `3.0`([iterative_loop.py:1181](src/workflows/iterative_loop.py#L1181)) — 3초 초과 초기화 .exe 오분류.
- 🟡 **중앙 config/settings 모듈 없음**; telemetry 경로 외 env 설정 0. P16+ 패치마다 "코드 옆 새 상수" 패턴이 표면을 계속 파편화.
- 🟢(낮음) **budget gate 死코드**: 완전히 plumbing됐으나(Rule 3 `BUDGET_EXHAUSTED` + 5000/iter 감산) CLI가 `budget_tokens_remaining`를 안 넘김 → 항상 `NO_BUDGET_GATE`, 감산 미발동. BlockedCause 힌트는 존재하지 않는 `--budget-tokens` 플래그를 안내.

### 5) 테스트 커버리지 — 🟢 well-disciplined (통합 갭 1개)

**잘 된 것**: 거의 모든 P-솔기에 전용 명명 테스트 — override/salvage/type-only/parse 함수가 `salvage_fn` 주입 가능 단위테스트([test_p13](src/tests/test_p13_web_build_fix_and_salvage.py)); best-iteration 8케이스([test_p15](src/tests/test_p15_best_iteration.py)); router 5출력 직접 테스트([test_iterative_loop_termination](src/tests/test_iterative_loop_termination.py)); RV/tech_scout는 **실 LangGraph `compiled.invoke()` E2E + events.jsonl 검증**([test_iterative_loop_rv](src/tests/workflows/test_iterative_loop_rv.py)); 그래프 엣지 튜플 검증; Track A/B 어댑터 테스트.

**문제**
- 🔴 **다중-iteration loop-back E2E 부재**: 모든 `run_iterative_loop()` E2E가 정확히 1 iteration에 COMPLETE(FakeProvider 빈 GapReport). IMPROVE→prepare_feedback→run_chain 재진입·feedback 누적·`recursion_limit`이 *실행*되지 않음 — 단위/엣지 레벨만. **2026-05-29 GraphRecursionError 크래시가 바로 이 loop-back 상호작용이었고 당시 단위테스트가 못 잡음** — 격리 단위테스트로 불충분하다는 역사적 증거.
- 🔴 `_resolve_best_output`(P15)의 `run_iterative_loop` **배선** 통합 미검증 — 격리 단위테스트만; E2E가 1 iter라 best-vs-last 분기가 end-to-end로 안 돌아감.
- 🟡 `_maybe_convene_boardroom`(RV 노드 내 분기) 미테스트; BLOCKED 종단 full-graph 런 부재(escalate측 retrospective_blocked/curate_blocked try/except 미실행).
- 🟢(낮음) 주 루프 테스트의 노드 단언이 stale(`issubset`이라 신규 노드 누락 회귀 못 잡음).

### 6) 관측성 — 🟡 mixed

**잘 된 것**: 단일 emitter+fail-silent+0-overhead-when-off([telemetry.py:352](src/monitoring/telemetry.py#L352)); 노드 라이프사이클 균일 계측(working→done→error); `ResultEvent`가 *채택된* iteration 기준 계산([iterative_loop.py:2448](src/workflows/iterative_loop.py#L2448) `chain = sel_chain`); LLM 호출 grain 관측(provider `finally`의 `AgentMessageEvent`); 복구 아티팩트는 side-file로 영속(13b/13c/13d).

**문제**
- 🔴 **복구 *결정*이 이벤트로 안 보임**: override(COMPLETE→BLOCKED), salvage(WEB_BUILD_SALVAGED), best-iteration(BEST_ITERATION_ADOPTED)이 전부 `decision.reason` 문자열에만 존재([:1626,1731,1842](src/workflows/iterative_loop.py#L1626)). 운영자는 `events.jsonl`에서 verdict가 *결정론 override로 뒤집힌 건지* Gap Analyst 산출인지 구분 불가.
- 🔴 **`ResultEvent`가 오도**: `iterations_run`=*마지막* iter([:2425](src/workflows/iterative_loop.py#L2425))인데 P15가 *이전* iter를 ship할 수 있음 — `adopted_iteration` 필드 없음 → 이벤트 스트림이 "마지막 iter를 배포"한 것처럼 보이게 함.
- 🔴 코드젠 sub-chain의 drift-regen/degenerate가 `run_chain` 노드 *아래*에서 일어나 전부 불투명(하나의 `run_chain working→done`). drift 재생성 N회·degenerate가 무이벤트(13d 파일만).
- 🟡 `iteration_begin`/`iteration_end` + `set_iteration`이 **死** — 모든 `AgentStatusEvent.iteration`=0, 진짜 iter 번호는 `detail="iter=N"` 자유텍스트로만. "진행 바 1/3→2/3" 불가능.
- 🟢(낮음) LangFuse trace와 telemetry가 `run_id` 미공유 → 상관에 수동 타임스탬프 매칭 필요.

### 7) 기술 부채 (P0~P15) — 🟡 mixed (솔기 OK, 몸통 누적)

**잘 된 것**: 공유 `detect_desktop_markers` 재사용(테스트가 규율 단언, [test_p3:259](src/tests/test_p3_gui_drift_reject.py#L259)); 가드 적용 순서가 *명시 문서화*; cap 가드 1차(judge)/2차(router) 방어가 *같은 불변식* 강제라 모순 불가; 신규 플래그 default-OFF short-circuit으로 회귀 0 보장.

**문제**: §1·§2와 중복되는 verdict 5스테이지 재작성·3종 GUI 마커셋 불일치·2종 is-web 판별자 외에:
- 🟢(낮음) **dead budget gate**(§4); `_format_blocked_partial_hint`가 `FAKE_PACKAGE` arm 누락([:177-185](src/workflows/iterative_loop.py#L177)) → 해당 BLOCKED는 힌트 공란; path-flatten `replace("/","__")` 3 생산 지점+P10b `_safe_rel_path` 4번째 스킴(공유 헬퍼 없음).
- 🟡 `_NON_TYPE_FAIL_MARKERS`/`_DESKTOP_GUI_MARKERS`가 영문+한국어 자유텍스트 매처(`"npm 미설치"`, `"is not recognized"`) — 툴체인 문구 변경 시 `_is_type_only_failure` 조용히 뒤집힘. → 구조적 신호(exit code, `TS\d+` regex) 우선.

---

## 3. ★ 단축출력 포렌식 (버닝 질문) — 🔴 ad-hoc-accretion

**왜 55자 단축 출력이 P0~P15를 거쳐도 iteration을 계속 깨뜨리나** — 각 복구 계층이 *왜* 놓치는지 확정:

1. **단축-재시도**([_common.py:124-126](src/workflows/_common.py#L124)) — `to_markdown()` *전체 길이* 측정. 빈 `code_blocks`여도 산문 필드로 >120자 → 재시도 미발동.
2. **converter-rescue**([_common.py:276-291](src/workflows/_common.py#L276)) — `ConverterError`/`ValidationError`에만 발동. *유효한* `GUICodeOutput`(빈 문자열 code_blocks)은 둘 다 안 던짐 → 미발동.
3. **degenerate-탐지 / P14**([analyze_and_implement.py:1929-1935](src/workflows/analyze_and_implement.py#L1929)) — **정확히 탐지하나 `13d_generation_failed.txt` 파일만 씀**. 재생성 강제 안 함, 빌드 차단 안 함, degenerate `code_paths`를 그대로 반환. *순수 종이 흔적*.
4. **drift-재생성 / P3**([analyze_and_implement.py:1070](src/workflows/analyze_and_implement.py#L1070)) — `platform_intent=="web"` AND `detect_desktop_markers(...)` 게이트. *빈* 출력엔 데스크탑 마커 0 → `_should_regenerate_for_drift`=False → 재생성 안 함. *잘못된 플랫폼* 코드는 고치나 *없는* 코드는 못 고침.
5. **best-iteration / P15**([iterative_loop.py:1828](src/workflows/iterative_loop.py#L1828)) — 유효 iter가 *있으면* degenerate 종단 거부. 그러나 **모든 iter가 degenerate면 마지막 degenerate를 surface**. 영향 완화일 뿐 코드 생성 불가.

**확정된 근본원인**: 단축 방어가 *문자열 길이* 프록시(`SUSPICIOUS_OUTPUT_THRESHOLD`)로 설계됐던 시점엔 실패가 "Final Answer 한 줄(진짜 ~30-57바이트)"이었음. `output_pydantic` 스키마(방어 2단계)가 LLM에게 *산문* 필드를 채우게 강제하자, 실패가 **"산문은 김, code_blocks 비었음"**으로 이동 → `to_markdown()`은 바이트론 길지만 *추출 가능 코드 0*. **어떤 계층도 원천 task에서 추출 가능 코드를 측정하지 않음.** 유일한 코드-수 인지 검사(`_is_degenerate_codegen`, P14)는 추출 *하류*에 탐지기로 붙었고 재생성 엣지가 없으며, 기존 intra-iteration 재생성 머신(`_regenerate_until_clean`, P3)은 플랫폼 드리프트에만 좁게 스코프됨. → **"코드가 나쁘다" 탐지기가 둘(drift, degenerate)인데 재생성 액추에이터에 배선된 건 하나뿐** = ad-hoc 통합.

**확정된 핵심 메커니즘**(CONFIRMED): `task_output_text`가 pydantic 렌더 선호([_common.py:67-72](src/workflows/_common.py#L67)) → `GUICodeOutput.to_markdown()`이 4필드 무조건 연결([_schemas.py:501-508](src/workflows/_schemas.py#L501)) → 빈 code_blocks여도 헤더+산문으로 >120자 → 가드 통과.

---

## 4. 교차 테마 (반복 패턴)

1. **탐지하되 예방 안 함**: 진짜 PREVENT는 2곳(첫 생성 web 제약 + cap)뿐. 단축·degenerate·manifest는 전부 detect/salvage/mitigate. 비결정 에이전트를 *원천 제약* 대신 *하류 보상*.
2. **판별자 난립**: web/GUI/desktop 4종, "깨졌나" 3종 — 멤버십 달라 불일치(kivy 사각지대). `exit_code==-8` 매직 결합.
3. **verdict 4~5곳 작성**: judge→override→salvage→best-iteration. 단일 우선순위표 부재 → "최종 verdict 어디서 정해지나" 불투명.
4. **주변부는 fail-safe, 코어는 무방비**: 모든 *주변* 서브시스템은 fail-silent 정책 일관 적용인데, *중앙* `compiled.invoke`만 except 없음 — 안전망이 코어에서 바깥으로가 아니라 솔기마다 둘러 짜였다는 방증.
5. **관측성이 Sprint-4에 동결**: 노드 라이프사이클은 보이나 P12~P15 복구 *결정*은 안 보임. 이벤트 스트림이 채택 iter를 오도.
6. **설정 분산**: 동일 개념 2값 다수, 중앙 config 0, dead gate.

---

## 5. 우선순위 개선 권장 (무엇 · 왜 · 위험도)

### P1 — 높음 (지금)

1. **단축 가드를 코드-추출 인지로 + degenerate→재생성 루프 추가** *(버닝 질문의 진짜 수정)*
   - *무엇*: `retry_task_if_short`를 스키마 인지로 — `GUICodeOutput`/`PytestSuiteOutput`/Track-B는 *코드 필드가 ≥1 추출 블록*인지 검증(총길이 무관). + `_regenerate_until_clean`을 미러링한 `_regenerate_until_nondegenerate` 바운드 루프를 코드젠 직후에 배선(같은 coder-Crew `regen_fn` 재사용).
   - *왜*: 현재 N개 낭비 iteration → 1회 재시도로 전환. 탐지(P14)+완화(P15)는 *예방*이 아님 — 단일-iter/max-iter=1/전부-degenerate 경로에서 사용자가 55자 stub을 받음. **이게 "왜 안 막히나"의 직접 해소.**
   - *위험*: 미수정 시 — degenerate 산출이 사용자에 도달 + 매 iteration LLM 예산 낭비.

2. **코어 `compiled.invoke`를 try/except로 감싸 구조화 실패 verdict 합성**
   - *무엇*: invoke 실패 시 `BLOCKED(INTERNAL_ERROR)` LoopOutcome 합성(다른 실패 모드와 일관).
   - *왜*: 유일하게 크래시가 새는 경로 — provider 에러/OSError가 LoopOutcome·아티팩트·지식 없이 raw traceback으로 종료.
   - *위험*: 미수정 시 — 깊은 실패가 관측·복구 불가, 자율 루프의 "항상 terminal 도달" 보증 깨짐.

3. **다중-iteration loop-back + `_resolve_best_output` 배선 통합 테스트 추가**
   - *무엇*: 노드를 패치해 iter 1..N-1=IMPROVE, N=COMPLETE(또는 유효 early + degenerate last)로 만들어 `iterations_run`·feedback 누적·`recursion_limit`·best 채택을 *실행* 검증.
   - *왜*: 격리 단위테스트가 못 잡는 state-merge/재진입 버그 영역 — 2026-05-29 GraphRecursionError 크래시가 정확히 이 부류였음(역사적 증거).
   - *위험*: 미수정 시 — loop-back/best-iteration 회귀가 라이브에서만 드러남.

### P2 — 중간 (다음 사이클)

4. **verdict 작성 통합** — override/salvage/best-iteration을 단일 `resolve_final_verdict(decision, chain, gap, records)`로, 명시적 우선순위표와 함께. *왜*: 4~5 mutator 2파일 분산 → "최종 verdict 어디서?" 불투명(증명된 버그는 아니나 실제 비용).
5. **salvage(실 서브프로세스)를 judge 노드 밖으로** — judge↔finalize 사이 전용 그래프 노드로. *왜*: "결정론/LLM-무관" 노드 안에서 수 분 빌드 = 모듈 자체 원칙 위반.
6. **판별자/매직코드 통합** — 단일 `platform.py`(`is_web`/`desktop_markers`/`gui_imports`) + `ExecuteResult.kind`(`exit_code==-8` 대체). *왜*: kivy/pygame 사각지대 + 두 is-web이 실패-경로에서 disagree 가능.
7. **복구 결정을 이벤트로 + `ResultEvent.adopted_iteration`** — override flip/salvage/best-iteration/degenerate/drift-regen emit + `iteration_begin/end`(또는 `set_iteration`) 구동. *왜*: 라이브 Tauri 패널(텔레메트리의 존재 이유)이 verdict 뒤집힘·채택 iter를 못 봄 → 스트림이 오도.
8. **설정 중앙화** — 단일 `_config.py`(iteration/budget/timeout/threshold), max-iter 3↔5 / web build 300↔600 / excerpt 15k↔30k 정합 + timeout CLI 노출. *왜*: P16+ 패치마다 표면 파편화 + 동일-개념-2값 드리프트 재발.

### P3 — 낮음 (정리)

9. **死코드/누락 arm 정리**: budget gate 배선 또는 삭제; `_format_blocked_partial_hint`에 `FAKE_PACKAGE` arm(+ 전수 커버 assertion); `_pick_entry_file` 제거; path-flatten 단일 헬퍼화.
10. **실패 처리 계약**: 복구 경로의 broad `except`는 re-raise / warn-once / 예외 repr 담은 typed sentinel 중 하나로(현재 ~90곳 정보 보존 불균일).

---

## 6. 정직한 균형 (steelman)

이 하네스를 "누더기"로만 보는 건 부당합니다. 반대 증거:
- **모든 P-패치가 default-OFF 또는 `platform_intent != "web"` early-return**으로 *수학적으로* 이전 동작 바이트-동일 보장 + 전용 회귀 테스트 + 사고를 인용한 docstring. 이는 부주의 패치의 *반대*입니다.
- **cap 가드 1차/2차 방어**는 중복이 아니라 실제 GraphRecursionError 크래시에 대한 belt-and-suspenders.
- **과거 fail-silent를 fail-loud로 교정**(`CodeQASkipped`)한 사례는 적극적 규율의 증거.
- **테스트는 P-솔기마다 박제** — 거의 모든 결정론 헬퍼가 단위 커버.
- predicate sprawl/config 분산은 *연구용 단일 메인테이너 하네스*에선 "코드 옆 rationale 상수"가 먼 중앙 config보다 가독성 높다는 방어도 성립.

**그러나** 이 방어가 무너지는 두 하드팩트: (1) "결정론" judge 노드 안에서 *서브프로세스 빌드*가 돌고, (2) *원천 예방* 대신 *하류 보상*에 의존해 55자 degenerate가 N iteration을 낭비시킨다 — 이는 스타일이 아닌 **응집/아키텍처 결함**. 그래서 종합 평결은 **"규율 잡힌 솔기, 누적된 몸통 — 통합의 변곡점"**입니다.

---

*본 감사는 실제 소스(run.py, iterative_loop, analyze_and_implement, _common, _schemas, build_workflow, convergence_judge, telemetry, tests)를 8 에이전트가 READ-ONLY로 file:line 인용 + 위험도 평가한 것을 종합. ★단축출력 포렌식의 핵심 메커니즘(가드가 추출 코드 아닌 to_markdown 총길이 측정)은 소스로 CONFIRMED. 코드 변경 없음.*
