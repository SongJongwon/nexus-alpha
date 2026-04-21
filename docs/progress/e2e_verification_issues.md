# E2E 재검증 결과 — PR #23 사후 (2026-04-21)

**검증 대상**: PR #23 (`🔧 E2E 검증 이슈 3종 수정`) 가 main 에 병합된 후, 이전에
보고된 3개 이슈가 실제로 해소됐는지 실 LLM (Claude MAX / agent_sdk) 으로 재검증.

**실행 명령**: `python scripts/run_e2e_verification.py`
**실행 시간**: 13분 27초 (808.39초)
**산출 디렉터리**: `outputs/workflow_20260421_101234/`
**LLM 호출 추정**: 14건 (UI/UX + CTO + Analyst + Designer + Theme + GUI Code Gen +
Reviewer + Build 5 + Release 4)

---

## 종합 판정

| # | 이전 이슈 | 검증 결과 | 비고 |
|---|---|---|---|
| 1 | GUI 분기 미실행 | ✅ **해결** | `chosen_path=gui`, 11/12/13 파일 모두 생성 |
| 2 | "계산기" → 데이터 분석 도구 | ✅ **해결** | CTO 가 "계산기 구현 전략 문서" 작성 (Tkinter, Decimal, 사칙연산) |
| 3 | 상대 import 단독 실행 불가 | ⚠️ **검증 불가** | 새 이슈 4 로 인해 코드 자체가 추출되지 않음 |

| # | 신규 이슈 | 심각도 | 상태 |
|---|---|---|---|
| 4 | GUI 에이전트 산출 본문 누락 (Final Answer summary 만 캡처) | 🔴 **블로킹** | 별도 PR 필요 |

---

## 이슈 1 — GUI 분기 미실행 — ✅ 해결 확인

### 검증 데이터

```
chosen_path: gui
산출 파일:
  10_ui_ux_spec.md     ✓ 존재
  11_gui_design.md     ✓ 존재
  12_design_tokens.md  ✓ 존재
  13_gui_code_output.md ✓ 존재
```

`enable_gui_branch=True` + UI/UX Analyst 가 정확히 `need_gui: yes` 를 emit 하여
파서가 GUI 경로 분기. PR #23 의 두 가지 보정 모두 작동:
- 파서 (`_parse_ui_ux_path`): `need_gui` 와 `form_factor` 양쪽 시그널 인식
- UI/UX Analyst 프롬프트: "계산기" 를 GUI 키워드로 명시화 → LLM 이 `need_gui: yes`
  를 안정적으로 출력

### UI/UX Analyst 실제 출력

```
Final Answer:
form_factor=single_window, complexity=simple, need_gui=yes
```

(*주의*: 본 출력의 본문 마크다운은 누락 — 이슈 4 참조. 그러나 Final Answer 의
시그널만으로도 분기 결정에는 충분했음.)

---

## 이슈 2 — "계산기" 프롬프트 해석 — ✅ 해결 확인

### 검증 데이터 (CTO 출력 발췌)

```markdown
# 계산기 구현 전략 문서

**전제 조건 (UI/UX Analyst 산출물 기반)**
- form_factor: single_window (단일 창 데스크톱 애플리케이션)
- complexity: simple (사칙연산 중심의 표준 계산기)
- need_gui: yes (GUI 필수, CLI 아님)

## 1. 기술 스택

| 레이어 | 선택 | 근거 |
|---|---|---|
| 언어 | Python 3.11+ | 학습 곡선 낮고, 표준 라이브러리만으로 GUI 완결 가능 |
| GUI 프레임워크 | Tkinter (ttk) | Python 내장, 추가 의존성 0, 단일 창·simple 요건에 최적 |
| 수식 평가 | decimal.Decimal 기반 자체 파서 | eval() 금지(보안), 부동소수점 오차 방지 |
| 테스트 | pytest + unittest.mock | 계산 엔진 단위 테스트에 충분 |
| 패키징 | PyInstaller (단일 exe) | Windows 기준 설치 없이 배포 가능 |
```

**판정**: CTO 는 "계산기" 를 *계산기* 로 정확히 해석. 이전 이슈 (데이터 분석 도구
프레이밍) 흔적 없음. PR #23 의 UI/UX 키워드 명시화 + Engineer backstory 일반화 +
Engineer task 의 도메인 중립화 모두 효과 있음.

(*주의*: GUI 경로에서는 Python Engineer 가 호출되지 않아 [python_engineer.py](../../src/agents/engineering/python_engineer.py)
의 backstory 변경 효과는 본 시나리오로 직접 검증 불가. CLI 경로 시나리오로 추가
검증 권장.)

---

## 이슈 3 — 단독 실행 가능성 — ⚠️ 검증 불가

### 검증 시도

```
$ ls outputs/workflow_20260421_101234/code/
(empty)

$ wc -l outputs/workflow_20260421_101234/13_gui_code_output.md
0
```

`13_gui_code_output.md` 파일에는 본문이 없고 Final Answer summary 한 줄만 존재:

```
framework=tkinter+customtkinter, files=1개, entry=python app.py
```

→ `_extract_code_blocks` 가 추출할 ```python 블록이 없어 `code/` 디렉터리 비어 있음.
→ `python <entry>.py` 단독 실행 자체가 불가능 — **검증 데이터 부재**.

### 원인

이슈 4 (다음 섹션) 가 직접 원인. PR #23 의 "상대 import 금지" 프롬프트 변경이
실제로 효과 있는지는 GUI Code Generator 가 본문 코드를 출력해야 검증 가능. 본
시나리오에서는 본문 코드 자체가 출력되지 않아 검증 불능.

---

## 신규 이슈 4 — GUI 에이전트 산출 본문 누락 (BLOCKING) — 🔴

### 증상

GUI 분기의 4개 에이전트 (UI/UX Analyst, GUI Designer, Theme Designer, GUI Code
Generator) 의 `task.output.raw` 가 **Final Answer summary 한 줄만** 담고, 본문
마크다운 + 코드 블록은 모두 누락.

| 파일 | 줄 수 | 실제 내용 |
|---|---|---|
| `10_ui_ux_spec.md` | 0 | `form_factor=single_window, complexity=simple, need_gui=yes` |
| `11_gui_design.md` | 0 | `GUI design — 1개 윈도우, 24개 위젯` |
| `12_design_tokens.md` | 0 | `theme_strategy=native, modes=1개, palette=#0B5FFF/...` |
| `13_gui_code_output.md` | 0 | `framework=tkinter+customtkinter, files=1개, entry=python app.py` |

대조: CTO `01_cto_strategy.md` 는 127 줄의 완전한 마크다운 캡처됨.

### 근본 원인 (코드 위치 식별)

GUI 4개 에이전트의 backstory 마지막에 다음 패턴이 공통으로 존재:

```python
# 예: src/agents/design/gui_code_generator.py:118-120
"마지막 줄은 반드시 `Final Answer:` 로 시작 — `Final Answer: framework=<X>, "
"files=<N>개, entry=python <entry>.py` 형태로 ..."
```

이 지시는 LLM 에게 **"마지막 줄에 한 줄짜리 summary 를 둬라"** 로 해석되어:
- LLM 출력 = `<본문 마크다운>\n... \nFinal Answer: <summary>`
- CrewAI 의 `Final Answer:` 파서는 **이후 텍스트만** `output.raw` 로 캡처
- 결과: 본문은 영구 손실, summary 만 보존

대조 — CTO 프롬프트는 "Final Answer: <summary>" 형식 강제 없음 → LLM 이
`Thought: ...\nFinal Answer:\n<full markdown>` 형식으로 출력 → CrewAI 가 본문 전체
캡처.

### 영향 범위

- **GUI 경로 (enable_gui_branch=True + chosen_path=gui)**: 코드 생성 결과 사실상
  전무. `code/` 비어 있음 → 빌드/실행/배포 사슬 모두 의미 없음.
- **CLI 경로 (chosen_path=cli)**: Engineer 는 영향 없음 (해당 프롬프트 패턴 없음).
  단, UI/UX Analyst 가 Final Answer summary 만 emit 해도 이후 단계에 충분한
  시그널은 전달됨 (form_factor / complexity).

### 권장 수정 (별도 PR)

**대상 파일** (4개):
1. `src/agents/planning/ui_ux_analyst.py`
2. `src/agents/design/gui_designer.py`
3. `src/agents/design/theme_designer.py`
4. `src/agents/design/gui_code_generator.py`

**수정 방향**: 각 backstory 의 "마지막 줄 Final Answer: <summary>" 지시를 다음과
같이 교체:

```
산출 시작에 `Final Answer:` 한 줄을 두고, 그 다음부터 산출 본문 (마크다운 +
yaml/json 블록 + Python 코드 블록) 을 모두 작성하세요. 본문 안 어딘가에
`framework=...` 같은 1줄 요약을 포함시키되, **summary-only 출력 금지** —
CrewAI 가 본문을 잃습니다.
```

또는 더 안전하게, `_task_output_text` 헬퍼에서 `output.raw` 가 너무 짧으면
`str(out)` (Thought + Final Answer 전체) 를 fallback 으로 쓰도록 보강.

**검증**: 본 PR 과 동일한 E2E 시나리오 재실행 → `13_gui_code_output.md` 가 본문 +
```python 블록을 포함 → `code/` 에 추출된 .py 파일 존재 → `python app.py` 실행 시
계산기 GUI 표시.

---

## 부록 — 산출 파일 인벤토리

```
outputs/workflow_20260421_101234/
├── 00_user_request.txt        (1 line — "계산기 만들어줘")
├── 01_cto_strategy.md         (127 lines — full strategy)
├── 02_analyst_brief.md        (full Data Analyst brief)
├── 03_engineer_output.md      (placeholder — "GUI 경로, Engineer 미실행")
├── 04_qa_review.md            (Code Reviewer 5단 리뷰)
├── 10_ui_ux_spec.md           (1 line — Final Answer summary only) ← 이슈 4
├── 11_gui_design.md           (1 line — Final Answer summary only) ← 이슈 4
├── 12_design_tokens.md        (1 line — Final Answer summary only) ← 이슈 4
├── 13_gui_code_output.md      (1 line — Final Answer summary only) ← 이슈 4
├── 20_dependency_report.md    (Dep Analyzer)
├── 21_build_spec.md           (Build Engineer)
├── 22_asset_manifest.md       (Asset Manager)
├── 23_installer_spec.md       (Installer Creator)
├── 24_platform_test_report.md (Platform Tester)
├── 30_release_decision.md     (1 line — Release Manager summary, 같은 패턴?)
├── 31_changelog_entry.md      (Changelog Generator)
├── 32_update_module_spec.md   (Update Checker)
├── 33_distribution_spec.md    (Distribution Agent)
└── code/                      (BIN 비어있음 — 이슈 4 영향)
```

(`30_release_decision.md` 도 같은 1줄 패턴으로 보이나 본 검증 범위 외 — Phase 5
재검증 시 동일 origin 의 이슈로 추정.)

---

## 다음 액션 (권장)

1. **즉시**: 본 문서 main 에 병합
2. **다음 PR**: 이슈 4 수정 (4개 backstory 일괄 + 가능하면 `_task_output_text`
   safety net)
3. **그 다음 PR**: 이슈 4 수정 후 동일 E2E 재실행 → `code/` 디렉터리에 실제 .py
   추출 → `python <entry>.py` 단독 실행 → 계산기 GUI 표시까지 검증 완료
