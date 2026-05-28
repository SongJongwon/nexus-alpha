# Phase 6 제안서 — Tech Scout 능력 (웹 리서치 기반 자기 진화)

> **상태**: PM 검토 완료 + 7건 의사결정 확정 (2026-05-28)
> **목적**: Phase 5.4 의 *양방향 토론* 위에 *외부 지식 탐색 + 가짜 패키지 가드* 격상
> **출처**: 코드베이스 정찰 보고 + PM 의 BIM 빌드 사례 분석 (얕은 요구 분석 + 성급한 수렴 + 환각 패키지)

---

## 0. 배경 — BIM 빌드 사례에서 식별된 시스템 결함

PM 분석 결과 시스템의 두 약점 + 한 환각:

| # | 결함 | 영향 |
|---|------|------|
| 1 | `expand_requirements` 가 *얕음* | "진짜 3D vs 가짜 2D" 구분 못 함 — BIM 안건이 isometric 2D 로 나옴 |
| 2 | `judge_convergence` 가 *성급함* | 요구 본질 미충족인데 1회 만에 COMPLETE |
| 3 | 에이전트가 *우물 안 개구리* | Three.js 등 신기술 발견 못 함 + `bim_repository` 같은 *환각 패키지* 산출 |

---

## 1. Feasibility Study — 웹 검색 실현 가능성 (PM 의사결정 #1 ✅)

### 1.1 옵션 검토 결과

| 옵션 | 비용 | 신뢰성 | 채택 |
|------|------|--------|------|
| A — Anthropic API server-side `web_search` tool | $10/1k searches | 높음 | ❌ 향후 별도 sprint |
| **B — PyPI / npm / GitHub JSON API 타겟 스크래핑** | **$0** | **결정적** | ✅ **채택** |
| C — 하이브리드 (A+B) | $$ | 가장 높음 | ❌ 복잡도 ↑ |

### 1.2 PM 확정 (옵션 B 만)

**근거**: 비용 0원 + *가짜 패키지 검증* 이라는 *현재 가장 큰 결함* 정조준. open-ended *발견* (옵션 A) 은 향후 별도 sprint.

**채택 인프라**:
- **PyPI JSON API**: `https://pypi.org/pypi/<pkg>/json` (무인증, 4xx → 가짜 확정)
- **npm Registry** (옵션): `https://registry.npmjs.org/<pkg>`
- **GitHub API** (옵션): repo 활성도 검증 (60 req/hr 무인증)
- **라이브러리**: `requests>=2.31` 만 추가 (httpx/bs4 불요)

---

## 2. Phased PR Plan (PM 의사결정 #3 ✅ — 6.2 우선)

### 2.1 PM 확정 PR 순서

**PR #226 (Phase 6.2) 먼저** → PR #227 (Phase 6.1) → PR #228 (Phase 6.3)

**근거**: 웹 검색 인프라와 무관하게 *"얕은 분석 + 조기 종료" 버그* 를 백엔드 코어에서 먼저 격파. BIM 같은 케이스가 *체크리스트 기반 강제 IMPROVE* 만으로도 cover 가능.

### 2.2 PR 별 Scope

| PR | Phase | 변경 | 의존 |
|----|-------|------|------|
| **#227** | **6.2 (★우선)** | Requirement Expander 3D 도메인 매처 + Convergence Judge Rule 0 + ChecklistItem dataclass | 없음 — 독립 머지 |
| #226 | 6.1 | Tech Scout 인프라 (`requests`, PyPI JSON, 캐시) + `NexusAlphaLLM` 어댑터 tool_use 활성 (옵션 B 만이므로 후자는 불필요할 수 있음) | 없음 |
| #228 | 6.3 | `--enable-tech-scout` CLI + workflow wire + BIM 벤치마크 + 라이브 가이드 | #226 + #227 머지 후 |

### 2.3 의존성 그래프 (PM 확정 순서)

```
PR #226 (Phase 6.2) ─★ 즉시 진입
  └─ Convergence Judge Rule 0 + Domain Checklist
        ↓ (회귀 0 확정 후)
PR #227 (Phase 6.1)
  └─ Tech Scout 인프라 (PyPI JSON + 캐시)
        ↓ (회귀 0 확정 후)
PR #228 (Phase 6.3)
  └─ 통합 + BIM 벤치마크
```

---

## 3. expand_requirements + Convergence Judge 결정론 명세 (PM 의사결정 #4 ✅)

### 3.1 도메인 범위 — 3D 우선 (PM 확정)

**3D 도메인만 우선 적용**. BIM 케이스로 완벽 검증 후 data_viz / ml / distributed 등 확장.

### 3.2 expand_requirements 강화 명세

#### ChecklistItem dataclass

```python
@dataclass
class ChecklistItem:
    id: str               # "3d-camera-orbit" (kebab-case 도메인 ID)
    domain: str           # "3d_visualization"
    description: str      # "카메라 Orbit 회전 (마우스 드래그)"
    must_satisfy: bool    # True → Rule 0 강제 검증
    detect_keywords: list[str]  # 결정론 매칭 키워드
```

#### 3D 도메인 결정론 매처

```python
_DOMAIN_PATTERNS: dict[str, list[str]] = {
    "3d_visualization": [
        "3d", "3차원", "WebGL", "Three.js", "BIM", "CAD",
        "Bloch sphere", "Mesh", "Camera", "Orbit",
    ],
}

def _detect_domain(user_request: str) -> list[str]:
    lower = user_request.lower()
    return [
        domain for domain, kws in _DOMAIN_PATTERNS.items()
        if any(kw.lower() in lower for kw in kws)
    ]
```

#### 3D 도메인 템플릿 체크리스트 (4 항목)

```yaml
domain_checklist:
  - id: 3d-camera-orbit
    domain: 3d_visualization
    description: 카메라 Orbit 회전 (마우스 드래그로 카메라 위치 조정)
    must_satisfy: true
    detect_keywords: [OrbitControls, mouseDown, rotate, camera.position]

  - id: 3d-webgl-vs-canvas
    domain: 3d_visualization
    description: WebGL (Three.js) vs Canvas 2D 아키텍처 선택 명시
    must_satisfy: true
    detect_keywords: [WebGLRenderer, three.js, Canvas2DContext, getContext("2d")]

  - id: 3d-interactive-controls
    domain: 3d_visualization
    description: 줌/팬/리셋 인터랙티브 컨트롤
    must_satisfy: true
    detect_keywords: [zoom, pan, reset, wheel, controls.update]

  - id: 3d-real-3d-not-isometric
    domain: 3d_visualization
    description: 진짜 3D (Z-축 회전) vs 가짜 2D isometric 구분 ★ BIM 본질
    must_satisfy: true
    detect_keywords: [rotateY, rotation.z, Vector3, depthBuffer]
```

### 3.3 Convergence Judge — Rule 0 (pre-validation) 명세

#### 시그니처 확장 (backward-compatible)

```python
def judge_convergence(
    gap: GapReport,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    budget_tokens_remaining: int = NO_BUDGET_GATE,
    domain_checklist: Optional[list[ChecklistItem]] = None,  # ★ Phase 6.2 NEW
    engineer_output_excerpt: str = "",  # ★ NEW
    qa_result_excerpt: str = "",        # ★ NEW
) -> JudgmentDecision:
```

#### Rule 0 동작

```
Rule 0 (★ NEW, Rule 1 보다 우선):
  - domain_checklist 가 None or [] → skip (회귀 0)
  - domain_checklist 모두 must_satisfy=false → skip
  - 미충족 항목 (detect_keywords 가 engineer_output/qa_result 에 없음) 발견 시
      → verdict = IMPROVE_NEEDED 강제
      → blocked_cause = NONE
      → reason = "도메인 체크리스트 N/M 미충족: [id1] desc..., [id2] desc..."
      → JudgmentDecision.domain_unsatisfied = [id1, id2, ...]

Rule 1~5 (기존 그대로):
  Rule 1 must_fix == 0 → COMPLETE
  Rule 2 must_fix > 0 + stagnation → BLOCKED(STAGNATION)
  Rule 3 must_fix > 0 + budget → BLOCKED(BUDGET_EXHAUSTED)
  Rule 4 must_fix > 0 + iter cap → BLOCKED(ITERATION_CAP)
  Rule 5 else → IMPROVE_NEEDED
```

#### `_validate_domain_checklist()` 결정론 매처

```python
def _validate_domain_checklist(
    checklist: list[ChecklistItem],
    engineer_output: str,
    qa_result: str,
) -> list[ChecklistItem]:
    haystack = (engineer_output + " " + qa_result).lower()
    return [
        item for item in checklist
        if item.must_satisfy
        and not any(kw.lower() in haystack for kw in item.detect_keywords)
    ]
```

### 3.4 자동 재수행 백엔드 제어

`IMPROVE_NEEDED` 의 `next_action` 에 *미충족 항목 명시* — 다음 iter Engineer prompt 에 자동 주입 (기존 Gap Analyst feedback loop 패턴 재사용). 추가 wiring 은 PR #228 (통합).

---

## 4. PM 확정 7건 의사결정 (요약)

| # | 결정 | 확정 값 |
|---|------|---------|
| **1** | 웹 검색 범위 | (b) **옵션 B 만 — PyPI Registry JSON API** |
| **2** | 공급자 정책 | 해당 없음 — agent_sdk 유지 |
| **3** | PR 순서 | (b) **Phase 6.2 (PR #226) 우선** |
| **4** | 도메인 범위 | (b) **3D 도메인만 우선** (BIM 검증 후 확장) |
| **5** | 가짜 패키지 판정 (★절충안) | **1차 IMPROVE_NEEDED + partial 힌트**, **2차 연속 시 BLOCKED** |
| **6** | 캐시 정책 | (a) **7일 (7d TTL) 로컬 디스크 캐싱** |
| **7** | 비용 / 검색 상한 | (b) **MAX_SEARCHES = 5** |

### 추가 PM 가드라인

- **회귀 0 절대 준수** — 기존 1,636 PASS 유지
- `domain_checklist=None` **방어 코드 철저**
- `--enable-tech-scout` (default OFF) 신설 예정 (PR #228)
- 활성화는 Phase 1~5.4 기존 flag 와 **독립 동작**
- **미래 리스크 가드** — Phase 6.1 진입 전 *"노드별 `LLM_PROVIDER` 분리"* 아키텍처 호환성 선제 검증 리포트 제출

---

## 5. 회귀 보호 plan

| Phase | 회귀 안전 메커니즘 |
|-------|------------------|
| **6.2 (PR #226)** | `domain_checklist=None` default → Rule 0 skip → 기존 1,636 PASS 영향 0. `GapReport` 새 필드는 `default_factory=list`. `JudgmentDecision` 새 필드 동일. |
| 6.1 (PR #227) | workflow 미진입 — 모든 신규 코드는 *수동 호출* 만. 1,636 PASS 영향 0. |
| 6.3 (PR #228) | `--enable-tech-scout` OFF default → workflow path 기존 그대로. |

---

## 6. Phase 6.2 (PR #226) 즉시 착수 — 작업 분해

| 단계 | 파일 | 변경 |
|------|------|------|
| 1 | `src/agents/analysis/requirement_expander.py` | `ChecklistItem` dataclass + `_DOMAIN_PATTERNS` (3D) + `_detect_domain()` + `build_domain_checklist()` |
| 2 | `src/agents/c_level/convergence_judge.py` | `Rule 0` + `_validate_domain_checklist()` + `GapReport.domain_unsatisfied` 필드 + `JudgmentDecision.domain_unsatisfied` + `BlockedCause.FAKE_PACKAGE` enum (PR #228 대비) |
| 3 | `src/tests/agents/test_requirement_expander_v6.py` (신규) | `_detect_domain` 매칭 / `build_domain_checklist` 3D 템플릿 / 빈 도메인 |
| 4 | `src/tests/test_convergence_judge_rule0.py` (신규) | Rule 0 skip / IMPROVE 강제 / `must_satisfy=false` 무시 / Rule 1~5 회귀 0 |
| 5 | `docs/WORK_STATUS.md` | PR #226 추가 + Phase 6.2 완료 |
| 6 | `docs/architecture/phase6_proposal.md` (본 파일) | 저장 완료 |

---

## 7. 향후 PR

- **PR #227 (Phase 6.1)** — Tech Scout 인프라 (`requests` + PyPI JSON + 캐시) → **선행 LLM_PROVIDER 호환성 리포트 제출 후 진입**
- **PR #228 (Phase 6.3)** — `--enable-tech-scout` CLI + workflow wire + BIM E2E + 라이브 가이드

---

**최종 검토**: PM 의사결정 7건 확정 (2026-05-28)
**작성**: Claude Opus 4.7 (1M context)
**참조**: 정찰 보고 (코드 evidence 기반, 추측 0건)
