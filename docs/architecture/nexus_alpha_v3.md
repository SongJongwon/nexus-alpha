# Nexus Alpha v3 — 자율 반복 루프 설계 (자기 진화 엔진)

- **문서 버전**: v3 (2026-04-17)
- **상태**: 설계안 — Phase 2 완료 이후 착수 예정
- **선행 조건**: Phase 1 MVP + Phase 2-P1(pytest 하네스) + Phase 2-P2(QA 에이전트)

---

## 1. 배경 — 왜 v3가 필요한가

Phase 1 MVP의 워크플로우는 **단일 패스(single-pass)** 구조다:

```
사용자 요청 → CTO → Analyst → Engineer → 결과
```

이 구조는 **첫 응답의 품질에 전적으로 의존**한다. 실제로 `outputs/workflow_20260417_164414/`의 사례에서 관찰한 이슈:

1. **요구 사항 확장의 일방향성** — CTO가 자의로 설정한 가정(예: "웹 공학용 계산기 MVP")을 후속 에이전트가 무비판적으로 이어받아 사용자 원래 요청("계산기를 만들어줘")과 멀어진 산출이 나왔다.
2. **모호성 수렴 불가** — 요구가 불명확할 때 CTO가 "선행 질문 6가지"를 던지는 패턴이 나타나지만, **그 질문이 누구에게도 답변되지 않은 채** 다음 단계로 넘어간다.
3. **품질 게이트 부재** — Engineer 산출 코드의 실제 실행 가능성·타입 정합성을 아무도 확인하지 않는다.
4. **반복 없음** — 결과가 부족해도 "한 번 더 돌려 보정"할 메커니즘이 없다. 사용자가 프롬프트를 바꿔 전체 체인을 재기동해야 한다.

**v3의 목표**: 워크플로우에 **자기 관찰(self-observation)과 반복(iteration)** 을 도입해, 체인이 스스로 "충분히 좋은 결과에 도달했는가"를 판정하고 필요하면 다시 돌 수 있도록 한다.

---

## 2. 위상 — Phase 2.5 "자기 진화 엔진"

로드맵상 위치:

```
Phase 1 : MVP 단일 패스 (CTO → Analyst → Engineer)                        [완료]
Phase 2 : QA / Knowledge / Operations / 요청 라우팅                         [진행 중]
──────────────────────────────────────────────────────────────────────────
Phase 2.5: 자율 반복 루프 (v3)                                              [본 문서]
──────────────────────────────────────────────────────────────────────────
Phase 3 : 실행 엔진 통합 (샌드박스 빌드·실행)
Phase 4 : GUI 자동 생성 (v4)
Phase 4.5: 빌드 & 패키징 (v4)
Phase 5 : 배포 자동화 (v4)
```

**Phase 2.5로 번호를 매긴 이유**: Phase 3 이후 단계는 모두 "실행 가능한 결과물"을 전제로 한다. 그런데 결과물 품질을 **단일 패스로는 보장하지 못하므로**, 실행/빌드/배포를 도입하기 전에 먼저 **수렴 보장 메커니즘**을 깔아야 한다.

---

## 3. 루프 아키텍처 개요

```
                     ┌──────────────────────────────────────┐
                     │ ┌──────────────────────────────────┐ │
                     │ │      Iteration Controller        │ │  ← 상태 관리
                     │ └──────────────────────────────────┘ │
                     │              │                        │
  사용자 요청  ────→  │   ┌──────────┴──────────┐             │
                     │   │ Requirement Expander │             │
                     │   └──────────┬──────────┘             │
                     │              ▼                        │
                     │   ┌───────────────────┐              │
                     │   │  CTO → Analyst →  │              │
                     │   │  Engineer → QA    │   (기존 체인) │
                     │   └─────────┬─────────┘              │
                     │             ▼                         │
                     │   ┌───────────────────┐              │
                     │   │  Gap Analyst      │  ← 산출물과  │
                     │   └─────────┬─────────┘     요구     │
                     │             ▼               비교     │
                     │   ┌───────────────────┐              │
                     │   │ Convergence Judge │  ← 판정     │
                     │   └─────────┬─────────┘              │
                     │             │                         │
                     └─────────────┼─────────────────────────┘
                                   │
                     ┌─────────────┼─────────────┐
                     ▼             ▼             ▼
                COMPLETE     IMPROVE_NEEDED    BLOCKED
                (출력)         (루프 재진입)    (사용자에게 질문)
```

### 3-1. 각 구성요소의 책임

| 컴포넌트 | 책임 | 기존 체인과의 관계 |
|---|---|---|
| **Iteration Controller** | 루프 전체 상태(iteration count, budget, history) 관리. 종료 조건 집행. | 최상위 오케스트레이터. LangGraph `StateGraph` 노드로 구현. |
| **Requirement Expander** | 사용자 원 요청을 구조화된 요구 스펙으로 확장. 모호한 부분은 "명시적 가정"으로 기록해 추후 추적 가능. | 기존 CTO의 "선행 질문" 역할을 사전 단계로 분리. |
| **Gap Analyst** | Engineer + QA 산출물과 Requirement Expander 스펙을 비교해 **미달 항목 / 잉여 항목 / 모호 해소 실패**를 목록화. | QA는 "코드 품질", Gap Analyst는 "요구 충족도" — 관심사 분리. |
| **Convergence Judge** | Gap Analyst 보고서를 입력받아 `COMPLETE` / `IMPROVE_NEEDED` / `BLOCKED` 중 하나를 판정. | 판정 결과가 Controller의 분기 조건. |

---

## 4. 신규 에이전트 4종 상세 설계

### 4-1. Requirement Expander

- **파일 경로**: `src/agents/planning/requirement_expander.py`
- **소속 본부**: 기획 및 설계 본부 (조직도 참조)
- **역할**: 사용자의 자연어 요청을 **요구 스펙 YAML**으로 전개

**출력 스키마**:
```yaml
goal: "계산기 만들어줘"
deliverables:
  - type: executable
    platform: "Windows desktop"     # 추론 (가정)
    form_factor: "GUI"              # 추론 (가정)
functional:
  - id: F-001
    desc: "사칙연산 (+, -, *, /)"
    priority: must
  - id: F-002
    desc: "사용자 입력을 키보드/마우스로 수용"
    priority: must
nonfunctional:
  - id: N-001
    desc: "윈도우에서 더블클릭으로 바로 실행"
    priority: must
assumptions:                        # 확장 과정에서 만든 가정 ← 명시적 기록
  - "별도 설치 절차 없이 단일 파일로 배포"
  - "네트워크 연결 불필요"
open_questions:                     # 답이 없어도 진행은 하되 BLOCKED 판정 근거
  - "과학 함수(sin/cos 등) 필요 여부"
```

**핵심 원칙**: *가정(assumption)과 미해결 질문(open_question)은 절대 숨기지 않는다.* 이후 Gap Analyst가 "가정이 실제 산출에서 지켜졌는가"를 검사한다.

### 4-2. Gap Analyst

- **파일 경로**: `src/agents/analysis/gap_analyst.py`
- **소속 본부**: 업무 분석 본부
- **입력**: Requirement Expander 스펙 + Engineer 산출 코드 + QA 리뷰
- **출력**: 간극 보고서

**출력 스키마**:
```yaml
satisfied: [F-001, F-002]
unsatisfied:
  - id: N-001
    reason: "산출물은 .py 단일 파일. 더블클릭 실행 불가."
    severity: blocker
ambiguous:
  - id: open_questions[0]
    reason: "과학 함수 미구현 — 가정 없이 생략됨"
    severity: minor
stagnation:                         # 이전 iteration과의 차이
  changed_files_since_last: 3
  resolved_gaps_since_last: 1       # 0이면 stagnation=true
  stagnation: false
```

**stagnation 필드가 핵심**. 두 iteration 연속으로 `resolved_gaps_since_last == 0` 이면 Controller가 루프를 강제 종료한다.

### 4-3. Convergence Judge

- **파일 경로**: `src/agents/c_level/convergence_judge.py`
- **소속 본부**: C-Level (경영 의사결정)
- **입력**: Gap Analyst 보고서 + 현재 iteration count + budget 잔여
- **출력**: 판정 결과 + 근거

**판정 규칙** (결정표):

| unsatisfied | stagnation | budget | iter count | 판정 | 다음 행동 |
|---|---|---|---|---|---|
| 없음 | - | - | - | `COMPLETE` | 사용자에게 결과 전달 |
| blocker 있음 | false | >0 | < max | `IMPROVE_NEEDED` | 루프 재진입 (gap을 CTO에게 feedback으로 주입) |
| blocker 있음 | **true** | - | - | `BLOCKED` | 사용자에게 "해소 안 되는 쟁점" 질문 |
| blocker 있음 | - | ≤ 0 | - | `BLOCKED` | 예산 소진 안내 |
| blocker 있음 | - | - | ≥ max | `BLOCKED` | 반복 한도 도달 안내 |
| minor만 | - | - | - | `COMPLETE` | 미결 항목을 caveat으로 표기해 전달 |

**설계 원칙**: 판정자는 **자유 형식 추론**이 아니라 **결정표**를 따른다. LLM 호출은 근거 문장을 생성할 때만 사용. 이는 루프 안정성의 핵심.

### 4-4. Iteration Controller

- **파일 경로**: `src/workflows/iterative_loop.py` (워크플로우 계층)
- **구현 도구**: LangGraph `StateGraph`
- **역할**:
  - 전역 상태(`LoopState`) 관리
  - Convergence Judge 판정에 따른 엣지 라우팅
  - 예산(budget) 집행 — LLM 토큰 사용량/시간/반복 횟수
  - Gap → 다음 iteration feedback 변환

**이 에이전트는 LLM을 호출하지 않는다** — 결정론적 오케스트레이션 레이어. 테스트·디버깅이 용이해야 하는 지점에 랜덤성을 두지 않는다.

---

## 5. LangGraph StateGraph 스켈레톤

```python
# src/workflows/iterative_loop.py (스케치)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
from langgraph.graph import StateGraph, END


Verdict = Literal["COMPLETE", "IMPROVE_NEEDED", "BLOCKED"]


@dataclass
class LoopState:
    user_request: str
    spec: dict = field(default_factory=dict)          # Requirement Expander 산출
    chain_output: dict = field(default_factory=dict)  # CTO/Analyst/Engineer/QA 산출
    gap_report: dict = field(default_factory=dict)    # Gap Analyst 산출
    verdict: Verdict | None = None
    feedback: str = ""                                # 다음 iteration에 주입할 보정
    iteration: int = 0
    budget_tokens_remaining: int = 200_000
    history: list[dict] = field(default_factory=list) # 과거 iteration 스냅샷


def build_graph() -> StateGraph:
    g = StateGraph(LoopState)

    g.add_node("expand_requirements", run_requirement_expander)
    g.add_node("run_chain",           run_cto_analyst_engineer_qa)  # 기존 체인 재사용
    g.add_node("analyze_gap",         run_gap_analyst)
    g.add_node("judge_convergence",   run_convergence_judge)
    g.add_node("prepare_feedback",    prepare_next_iteration_feedback)
    g.add_node("finalize",            finalize_for_user)
    g.add_node("escalate",            escalate_to_human)

    g.set_entry_point("expand_requirements")
    g.add_edge("expand_requirements", "run_chain")
    g.add_edge("run_chain",           "analyze_gap")
    g.add_edge("analyze_gap",         "judge_convergence")

    g.add_conditional_edges(
        "judge_convergence",
        lambda s: s.verdict,
        {
            "COMPLETE":        "finalize",
            "IMPROVE_NEEDED":  "prepare_feedback",
            "BLOCKED":         "escalate",
        },
    )
    g.add_edge("prepare_feedback", "run_chain")   # 루프 재진입
    g.add_edge("finalize", END)
    g.add_edge("escalate", END)

    return g
```

**주의점**:
- `run_chain` 재진입 시 `feedback` 필드가 CTO의 컨텍스트에 `prior_iteration_feedback` 형태로 주입된다.
- `prepare_feedback` 은 Gap 보고서의 `unsatisfied` 항목을 **CTO가 이해할 수 있는 보정 지시**로 변환 — 단순 append가 아니라 "이전 iteration은 N-001을 충족하지 못했다. 이번엔 더블클릭 실행 가능한 형태로 스펙을 잡아라" 같은 구체 지침.

---

## 6. 종료 조건 (정확한 정의)

| 종료 유형 | 조건 | 결과 |
|---|---|---|
| `COMPLETE` | Gap 보고서에 `unsatisfied.severity == blocker` 가 0건 | 사용자에게 최종 산출 전달. minor 미결 항목은 caveat으로 병기. |
| `IMPROVE_NEEDED` | blocker 존재 AND stagnation=false AND budget > 0 AND iteration < max_iterations | feedback 생성 후 루프 재진입 |
| `BLOCKED (stagnation)` | 2회 연속 `resolved_gaps_since_last == 0` | 사용자에게 "해소 안 되는 쟁점 목록" 에스컬레이션 |
| `BLOCKED (budget)` | LLM 토큰·시간·API 호출 예산 소진 | 사용자에게 "예산 소진, 현재 상태로 중단" 안내 |
| `BLOCKED (iteration cap)` | iteration == max_iterations (기본 5) | 사용자에게 "반복 한도 도달" 안내 + 중간 산출 제공 |

---

## 7. 안전장치

### 7-1. max_iterations = 5 (하드 코딩 기본값)
- 단순 초과 방지용. 대부분 실험에서 5회 내 수렴하지 않으면 구조적 문제임.
- `.env` 또는 워크플로우 인자로 조정 가능하지만 **기본값을 올리지 않는다**. 5회 초과 필요 시에는 요구 정의를 먼저 의심.

### 7-2. Budget Gate
- 매 iteration 시작 전 `budget_tokens_remaining`을 체크.
- LangFuse의 `Usage` 정보를 주기적으로 합산 (또는 Provider 응답에서 직접 집계).
- 초과 시 즉시 BLOCKED. **부분 결과라도 반환** — 완전 실패 금지.

### 7-3. Stagnation Detection
- Gap Analyst가 iteration n과 n-1의 Gap 보고서를 비교해 `resolved_gaps_since_last` 계산.
- 2회 연속 0이면 판정자가 BLOCKED로 내린다.
- "같은 실수를 반복하는 루프"를 조기에 끊는 것이 목적.

### 7-4. Feedback 순환 방지
- `prepare_feedback`은 "이전 iteration의 실패 이유 + 개선 방향" **2가지만** 주입한다.
- 이전 iteration 코드 전체를 CTO에게 다시 주입하면 컨텍스트 팽창으로 토큰 낭비 + LLM이 기존 결과에 과도하게 앵커링.

### 7-5. LangFuse 관측
- 각 iteration을 **단일 trace 아래 5개 generation**(Expander, Chain-of-4, Gap, Judge, Feedback)으로 기록.
- 반복 간 diff를 대시보드에서 바로 추적 가능.

---

## 8. 기존 아키텍처와의 관계

### 8-1. 단일 패스 워크플로우는 그대로 둔다
- `src/workflows/analyze_and_implement.py`는 삭제·수정하지 않는다.
- v3 루프는 `src/workflows/iterative_loop.py`로 **나란히** 존재.
- "빠른 결과가 필요할 때는 단일 패스, 품질 보장이 필요할 때는 반복 루프" — 호출 측이 선택.

### 8-2. 에이전트 팩토리 계약 재사용
- Requirement Expander / Gap Analyst / Convergence Judge 모두 기존 `create_X_agent()` 팩토리 패턴 따름.
- `NexusAlphaLLM` 어댑터, LangFuse 자동 로깅, FakeProvider 테스트 전략 모두 그대로 적용.

### 8-3. pytest 하네스 (Phase 2-P1) 확장 경로
- `conftest.py`의 FakeProvider 패턴이 v3 에이전트에도 그대로 적용 가능.
- 다만 Convergence Judge는 결정표 기반이라 **LLM 없이 순수 단위 테스트**로 대부분 커버할 수 있음 — FakeProvider가 아예 필요 없는 첫 에이전트.

---

## 9. 구현 로드맵

| 단계 | 산출물 | 선행 조건 |
|---|---|---|
| 2.5-A | Requirement Expander + 스펙 스키마 + pytest | Phase 2-P2 (QA 에이전트) 완료 |
| 2.5-B | Gap Analyst + diff 유틸 + pytest | 2.5-A |
| 2.5-C | Convergence Judge (결정표 기반) + pytest | 2.5-B |
| 2.5-D | Iteration Controller (LangGraph) + 루프 E2E 테스트 | 2.5-A~C |
| 2.5-E | Budget Gate 통합 + LangFuse usage 집계 | 2.5-D |
| 2.5-F | v2.5 완료 보고서 + next_session_context 갱신 | 전 단계 |

### 수용 기준 (Definition of Done)

- [ ] `run_iterative_loop(user_request)` 가 모호한 입력에서도 3~5회 내 `COMPLETE` 또는 `BLOCKED` 중 하나로 **반드시 종료**.
- [ ] pytest FakeProvider로 네트워크 없이 전체 루프 실행 검증 (각 판정 분기 테스트 3건 이상).
- [ ] LangFuse 대시보드에서 한 trace 내 iteration 수와 각 단계별 latency/token 확인 가능.
- [ ] stagnation, budget, iteration cap 각각에 대응하는 BLOCKED 경로를 인위적으로 트리거하는 테스트 3건 통과.

---

## 10. 열린 설계 질문

v3 구현 착수 전에 결정이 필요한 항목들:

1. **Feedback 형식**: 자연어 지시 vs 구조화된 diff. 초기엔 자연어로 시작하되, 3회 이상 순환 시 구조화된 diff로 강제 전환?
2. **Gap Analyst의 QA 의존도**: QA 리뷰가 없으면 Gap 판정이 어렵다. Phase 2-P2(QA) 없이 v3 착수 가능한가? → 아니오, 선행 필수.
3. **LangGraph vs 자체 상태 머신**: LangGraph의 체크포인팅/persistence가 필요한가? 초기엔 in-memory로 충분, 필요 시 SQLite 백엔드 추가.
4. **사용자 개입 시점**: `BLOCKED` 이외에도 중간에 사용자가 "그만 돌려"라고 개입할 수 있어야 한다 — `--max-iterations=1` 같은 CLI 인자로 우선 대응.

이 4가지 질문은 v3 착수 시점에 별도 세션에서 사용자와 합의한다.
