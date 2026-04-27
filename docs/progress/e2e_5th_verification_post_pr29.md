# 5차 E2E 검증 결과 — PR #29 사후 (2026-04-27)

**검증 대상**: PR #29 (`🔧 이슈 6 수정 — LLM 본문 누락 자동 재시도 (방어선 1)`) 가
main 에 병합된 후, post-hoc 자동 재시도가 16 에이전트의 본문 캡처율을 *얼마나*
끌어올리는지 정량 측정.

**실행 명령**: `python scripts/run_e2e_verification.py`
**실행 시간**: 21분 38초 (1298.13초)
**산출 디렉터리**: `outputs/workflow_20260427_141936/`
**LLM 호출**: 14건 (+ 짧은 출력 감지 시 자동 재시도)

---

## 종합 판정

| 지표 | PR #28 (4차, 재시도 없음) | PR #30 (5차, 재시도 있음) | 변동 |
|---|---|---|---|
| 본문 캡처 (16 에이전트 중) | 12 / 16 (75%) | **12 / 16 (75%)** | ±0 |
| 짧은 출력 잔존 | 4 (UIUX/Build/Release/Distribution) | **4 (QA/Theme/Build/Release)** | 위치 변동 |
| 실행 시간 | 22:09 | 21:38 | -31초 (오차 범위) |

**핵심 결론**: 방어선 1 (auto-retry) 의 코드는 정상 작동하나 **캡처율 개선 효과는
미미**. 동일 LLM + 동일 prompt 재실행이라 짧은 출력 확률이 그대로 유지됨.

| # | 이슈 | 결과 |
|---|---|---|
| 1, 2, 3 | GUI 분기 / "계산기" / 단독 실행 | ✅ 유지 |
| 4 | GUI 4 에이전트 본문 | 🟡 부분 (4 중 1 짧음 — ThemeDesigner) |
| 5 | 비-GUI 10 에이전트 본문 | 🟡 부분 (10 중 3 짧음 — QA/Build/Release) |
| 6 | LLM 비결정적 컴플라이언스 | 🟡 **방어선 1 효과 미미** — 방어선 2 필요 |

---

## 상세 비교 (PR #28 → PR #30)

| 파일 | PR #28 | PR #30 | 판정 |
|---|---|---|---|
| `01_cto_strategy.md` | 9,390 | 9,539 | ✓ |
| `02_analyst_brief.md` | 10,645 | 12,197 | ✓ |
| `04_qa_review.md` | 8,536 | **14** | 🔴 NEW REGRESSION |
| `10_ui_ux_spec.md` | 58 | **2,826** | ✅ HEALED |
| `11_gui_design.md` | 6,734 | 8,846 | ✓ |
| `12_design_tokens.md` | 4,808 | **82** | 🔴 NEW REGRESSION |
| `13_gui_code_output.md` | 25,043 | 22,102 | ✓ |
| `20_dependency_report.md` | 4,769 | 4,546 | ✓ |
| `21_build_spec.md` | 67 | **67** | 🔴 STILL SHORT |
| `22_asset_manifest.md` | 8,946 | 5,868 | ✓ |
| `23_installer_spec.md` | 10,227 | 9,215 | ✓ |
| `24_platform_test_report.md` | 5,003 | 5,202 | ✓ |
| `30_release_decision.md` | 37 | **37** | 🔴 STILL SHORT |
| `31_changelog_entry.md` | 1,506 | 2,439 | ✓ |
| `32_update_module_spec.md` | 16,702 | 21,025 | ✓ |
| `33_distribution_spec.md` | 132 | **9,486** | ✅ HEALED |

`code/calculator.py`: 19,213 자, py_compile 통과 ✅

---

## 🔬 진단 — 재시도 메커니즘은 작동했으나 효과 미미

### 1. 재시도 기능은 정상 작동 (코드 검증)

증거:
- pytest 154 passed (12 신규 테스트 포함) — 단위 테스트 모두 통과
- E2E 종료 코드 0 — 재시도 중 예외 발생 없음
- `21_build_spec.md` 가 PR #28 (`hidden_imports=1개`) 와 PR #30 (`hidden_imports=2개`) 사이에서 *내용* 은 다르지만 *길이* 는 동일 → 두 번째 LLM 호출이 발생했음을 시사 (재시도가 다른 시뮬레이션 데이터로 호출돼도 결과가 같은 67자).

### 2. 그러나 캡처율은 개선 안 됨 (75% → 75%)

**짧은 출력 분포 변화**:

| 런 | 짧은 에이전트 |
|---|---|
| PR #28 (4차) | UIUXAnalyst, BuildEngineer, ReleaseManager, DistributionAgent |
| PR #30 (5차) | CodeReviewer, ThemeDesigner, BuildEngineer, ReleaseManager |

**관찰**:
- `BuildEngineer`, `ReleaseManager` — 양 런에서 동일하게 짧음 → **체계적으로
  짧은 출력 산출**. 재시도해도 동일 패턴 (`tool=pyinstaller, mode=onefile, ...`,
  `version=X.Y.Z, bump=patch, tag=vX.Y.Z`). LLM 이 이 요약 형식을
  *완결된 답변* 으로 취급.
- `UIUXAnalyst`, `DistributionAgent` — PR #28 에선 짧음 → PR #30 에서 회복.
  (재시도 효과인지 LLM 무작위 샘플링 효과인지 구분 어려움)
- `CodeReviewer`, `ThemeDesigner` — PR #28 에선 정상 → PR #30 에서 짧음.
  새로운 무작위 실패 — 동일 prompt 라도 LLM 출력 분산 큼.

### 3. 근본 원인 (이슈 6 재진단)

방어선 1 (auto-retry) 의 **수학적 한계**:
- 단일 호출 짧은 출력 확률을 p=0.25 로 가정 (PR #28 데이터)
- max_retries=1 → 두 번 모두 짧을 확률 = p² = 6.25%
- 16 에이전트 × 6.25% = 평균 1 짧음 예상 (이론)
- **실제 PR #30 결과**: 4 짧음 → 이론보다 4배 큼

→ p가 에이전트마다 다르며, **일부 에이전트(BuildEngineer/ReleaseManager)는
p ≈ 1.0** (체계적 실패). 평균값으로 본 모델링이 부적합.

### 4. BuildEngineer / ReleaseManager 가 왜 *체계적* 인가

backstory 의 요약 형식이 LLM 에게 *자기-종결* 신호:

| 에이전트 | 요약 형식 | 자기-종결성 |
|---|---|---|
| BuildEngineer | `tool=pyinstaller, mode=onefile, hidden_imports=N개, est_size=~XMB` | **High** (구체적 사양 결정) |
| ReleaseManager | `version=X.Y.Z, bump=patch, tag=vX.Y.Z` | **High** (버전 결정) |
| DistributionAgent | `channel=github_releases, url_template=..., signed=no` | Medium |
| UIUXAnalyst | `form_factor=single_window, complexity=simple, need_gui=yes` | Medium |
| DepAnalyzer | `deps=N개, hidden=M개, license_warnings=L개, os_blockers=B개` | Low (카운트 — "상세 보여줘" 유도) |
| AssetManager | `assets — icons=N, fonts=M, ...` | Low |

**가설**: 결정형 요약 (`X=Y` 형식, 단일 결정) 의 자기-종결성이 카운트형 요약
(`N개, M개`) 보다 높음 → LLM 이 본문을 생략할 가능성 증가.

---

## 권장 — 방어선 2 (structured output API)

방어선 1 은 적은 비용으로 *일부* 회복을 제공하지만 systematic failure 에는 무력.
**근본 해결**:

### 옵션 A — Anthropic SDK `tools` 강제 호출

```python
client.messages.create(
    model="claude-...",
    tools=[{
        "name": "build_spec_output",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "한 줄 요약"},
                "tool_section": {"type": "string", "description": "도구 선택 본문"},
                "command_section": {"type": "string", "description": "빌드 명령"},
                "spec_section": {"type": "string", "description": "PyInstaller spec"},
                "checklist": {"type": "array", "items": {"type": "string"}},
                "engineer_notes": {"type": "string"},
            },
            "required": ["summary", "tool_section", "command_section", "spec_section",
                         "checklist", "engineer_notes"],
        },
    }],
    tool_choice={"type": "tool", "name": "build_spec_output"},
)
```

→ Anthropic API 가 스키마 검증 → 누락된 섹션이 있으면 LLM 재호출 (Anthropic 측에서
처리). 본 워크플로우 코드는 결과 dict 받아 markdown 렌더만.

### 옵션 B — CrewAI 1.14.1 호환성 검토

CrewAI 가 `output_pydantic` 또는 `output_json` 파라미터 지원. Pydantic 모델로
출력 형식 강제 가능:

```python
from pydantic import BaseModel

class BuildSpec(BaseModel):
    summary: str
    tool_section: str
    command_section: str
    spec_section: str
    checklist: list[str]
    engineer_notes: str

build_task = Task(
    description=...,
    expected_output=...,
    agent=build_engineer,
    output_pydantic=BuildSpec,  # 스키마 강제
)
```

→ CrewAI 가 LLM 응답을 BuildSpec 으로 파싱 시도. 실패 시 자동 재시도 (CrewAI 내부).

### 결정 기준

- **CrewAI 1.14.1 가 output_pydantic 안정적이면**: 옵션 B (코드 변경 최소).
- **그렇지 않으면**: 옵션 A (Anthropic SDK 직접 호출, CrewAI 우회).

검토 PR (PR #31) 에서 CrewAI 호환성 + 16 에이전트 출력 스키마 정의 + 1~2 에이전트
시범 적용 → 5차 E2E 의 1/3 수준 시간으로 효과 측정.

---

## 핵심 결론

1. **방어선 1 코드 정상 작동.** pytest 154 passed, 단위 테스트 모두 통과,
   production 에서도 예외 없이 실행.
2. **그러나 LLM 비결정적 컴플라이언스 문제는 systematic failure 비중이 커**
   단순 재시도로 해결 불가. 캡처율 75% 그대로 (4차 → 5차).
3. **방어선 2 (structured output API) 필수.** PR #31 에서 도입 검토 필요.
4. **GUI 풀체인 안정성 유지.** `code/calculator.py` 19,213 자 추출, py_compile
   통과 — 이슈 4/5/6 와 무관하게 사용자 가시 사슬은 작동.

---

## 다음 액션

1. **PR #30** (이 문서 + WORK_STATUS) → 5차 E2E 결과 영구 기록
2. **PR #31 (예정)**: 방어선 2 도입 검토 — CrewAI `output_pydantic` 호환성 + 1~2
   에이전트 시범 + 효과 측정
3. **WORK_STATUS §4 (PyInstaller 통합)** 평행 시작 가능 — 외부 도구 통합은 본 이슈
   와 독립적 진행 가능 (현재 사슬은 사양 수준에서 안정).

---

*방어선 1 의 한계가 명확해진 만큼, 방어선 2 의 ROI 가 분명. 다만 75% 캡처율
자체로도 사용자 가시 산출물 (calculator.py) 은 정상이므로 외부 도구 통합 작업과
병행 가능.*
