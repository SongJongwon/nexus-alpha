# 🏢 Nexus Alpha 실제 구축 구성안 v6 (PR #36 반영)

**━ AI 소프트웨어 자동 생성 공장 (Software Generation Factory) ━**

> **작성일**: 2026-04-28 (v6 — PR #36 머지 후 첫 진짜 `.exe` 산출 시점)
> **선행 문서**:
> - **v1** ([최종_상세_구성안.md](.) — 2026-04-17): RPA 원안
> - **v3** ([nexus_alpha_v3.md](./nexus_alpha_v3.md) — 2026-04-17): 자율 반복 루프 설계
> - **v4** ([nexus_alpha_v4.md](./nexus_alpha_v4.md) — 2026-04-17): 자연어 → .exe 풀 비전 설계
> - **v4 조직도** ([nexus_alpha_org_v4.md](./nexus_alpha_org_v4.md)): 9개 본부 24명 매핑
> - **v5 (built)** ([nexus_alpha_v5_built.md](./nexus_alpha_v5_built.md) — 2026-04-21): Phase 5 통합 시점 구축 상태
>
> **본 문서 (v6) 의 역할**: v5 이후 단일 세션 8시간(2026-04-27~28)동안 12 PR 머지로
> 이슈 4/5/6 모두 close + **첫 진짜 `.exe` 산출** 달성. v5 의 "사양 산출만"
> 한계를 PR #36 이 외부 도구 첫 호출로 해소.
>
> **현재 상태**: Phase 0~5 완료 + 이슈 4/5/6 close + PR #36 PyInstaller 통합
> **테스트 커버리지**: pytest **199 passed** (v5 138 → +61)
> **누적 PR**: **36개 머지** (v5 24 → +12, 단일 세션)
> **첫 `.exe` 산출**: ✅ Calculator.exe 10.7MB, SHA256 검증 완료 (PR #36)
> **8차 E2E**: 진행 중 (PR #38 — 자연어 → `.exe` 풀체인 검증)

---

## 📑 v5 → v6 핵심 변경

### 🎯 단일 세션 8시간 누적 성과 (2026-04-27~28)

| 지표 | v5 (2026-04-21) | **v6 (2026-04-28)** | 변동 |
|---|---|---|---|
| 누적 PR | 24개 | **36개** | +12 |
| pytest | 138 passed | **199 passed** | +61 (회귀 0) |
| 본문 캡처율 | 38% (PR #24 측정) | **94%** (PR #34 측정) | +56% |
| Close된 이슈 | — | **이슈 4 / 5 / 6** | +3 |
| 외부 도구 통합 | 0 (사양만) | **PyInstaller 실제 호출** | 첫 통합 |
| 첫 `.exe` 산출 | 미달성 | ✅ **Calculator.exe 10.7MB** | M4.5 신규 달성 |

### 🔄 비전 진화

v5 까지: **"AI 소프트웨어 자동 생성 공장"** — 사양 수준
v6 부터: **"AI 소프트웨어 자동 생성 공장 + 첫 진짜 `.exe`"** — 실제 산출

---

## 🎯 v6 의 포지셔닝

> **Nexus Alpha v6 는 자연어 요청 한 줄에서 다중 AI 에이전트가 협업하여
> 분석 → 설계 → 코드 → 빌드 → 배포 전 과정을 자동 수행하고
> **실제 실행 가능한 `.exe` 산출까지 완료**하는 소프트웨어 자동 생성 공장입니다.**

### 골든 패스 (v6 부터 — 첫 `.exe` 도달)

```
"계산기 만들어줘"
        ↓
[UI/UX Analyst] → form_factor=single_window, need_gui=yes
        ↓
[CTO] → Tkinter 전략, MVC 분리
        ↓
[GUI Designer] → 와이어프레임 + 위젯 트리
        ↓
[Theme Designer] → WCAG AA 컬러 토큰
        ↓
[GUI Code Generator] → calculator.py (단독 실행 가능, 21,332자)
        ↓
[Code Reviewer] → APPROVED / NEEDS_REVISION
        ↓
[Dep Analyzer → Build Engineer → Asset Manager → Installer Creator → Platform Tester]
        ↓ (Phase 4.5 빌드 사양)
[Release Manager → Changelog Generator → Update Checker → Distribution Agent]
        ↓ (Phase 5 릴리스 사양)
[build_executor] — ⭐ PR #36 신규
        ↓
🎉 outputs/workflow_<ts>/build_output/dist/Calculator.exe (10.7 MB, PE32+ Windows GUI)
```

---

## 🏗️ 실제 조직도 (9개 본부, 23명 + 1도구)

### 0. C-Level (2명) ⚠️ 부분 구축 (변경 없음)

| 직책 | 파일 | 역할 | 상태 |
|---|---|---|---|
| **CTO** | [c_level/cto.py](../../src/agents/c_level/cto.py) | 기술 전략 / 구현 접근 / 리스크 / 권장 작업 4치원 산출 | ✅ |
| **Convergence Judge** | [c_level/convergence_judge.py](../../src/agents/c_level/convergence_judge.py) | v3 반복 루프의 종결 판정 | ✅ |
| ~~CEO~~ | — | 전체 워크플로우 총괄 | ❌ 미구축 |
| ~~CFO~~ | — | 토큰/API 비용 모니터링 | ❌ 미구축 (LangFuse 자동 추적으로 대체) |

---

### 1~6. 분석 / 기획 / 디자인 / 엔지니어링 / QA / 지식 / 운영 본부 (변경 없음)

총 14명 (변경 없음 — 기존 v5 와 동일).

상세는 [Nexus_Alpha_조직도_v6.md](./Nexus_Alpha_조직도_v6.md) 참조.

---

### 7. 빌드 & 배포 본부 (9명 + 1도구) — **PR #36 외부 도구 통합 첫 시작**

#### Phase 4.5 — 빌드 5명 (변경 없음, 모두 ✅ 구축)

| 직책 | 파일 | 역할 |
|---|---|---|
| **Dependency Analyzer** | [build_release/dependency_analyzer.py](../../src/agents/build_release/dependency_analyzer.py) | 코드에서 의존성 추출 + YAML 보고서 |
| **Build Engineer** | [build_release/build_engineer.py](../../src/agents/build_release/build_engineer.py) | PyInstaller / cx_Freeze / Nuitka 중 선택 + spec 파일 |
| **Asset Manager** | [build_release/asset_manager.py](../../src/agents/build_release/asset_manager.py) | 아이콘 / 리소스 매니페스트 |
| **Installer Creator** | [build_release/installer_creator.py](../../src/agents/build_release/installer_creator.py) | NSIS / Inno Setup 인스톨러 스크립트 |
| **Platform Tester** | [build_release/platform_tester.py](../../src/agents/build_release/platform_tester.py) | Sandbox 실행 + narration 보고서 |

#### Phase 5 — 릴리스 4명 (변경 없음, 모두 ✅ 구축)

| 직책 | 파일 | 역할 |
|---|---|---|
| **Release Manager** | [build_release/release_manager.py](../../src/agents/build_release/release_manager.py) | SemVer 결정 + RELEASE.md 초안 |
| **Changelog Generator** | [build_release/changelog_generator.py](../../src/agents/build_release/changelog_generator.py) | Keep a Changelog 형식 |
| **Update Checker** | [build_release/update_checker.py](../../src/agents/build_release/update_checker.py) | 자동 업데이트 모듈 사양 (HTTPS / TLS / SHA256 / 채널 allowlist) |
| **Distribution Agent** | [build_release/distribution_agent.py](../../src/agents/build_release/distribution_agent.py) | GitHub Release / 채널별 배포 사양 |

#### 🆕 PR #36 신규 — build_executor (도구, LLM 아님)

| 컴포넌트 | 파일 | 역할 | 상태 |
|---|---|---|---|
| **build_executor** | [build_release/build_executor.py](../../src/agents/build_release/build_executor.py) | BuildSpec 사양 → 실제 `pyinstaller` subprocess 호출 → `.exe` 산출 → SHA256 | ✅ PR #36 |

**v5 → v6 차이**:
- v5: 빌드 본부 9명 모두 *사양 산출만* (LLM 9건)
- v6: 빌드 본부 9명 + **build_executor 도구** → 실제 외부 도구 호출 → `.exe` 산출

**build_executor 설계 원칙**:
- subprocess 호출만 담당 (BuildSpec markdown 파싱 X — 입력은 구조화된 인자)
- timeout 강제 (5분 기본). PyInstaller 무한 hang 방지
- graceful failure (예외 propagate 안 함, ExecuteResult.success=False 반환)
- 결정적 산출 디렉터리 (`output_dir/dist/<App>.exe`)

**ExecuteResult 데이터 모델**:
```python
@dataclass
class ExecuteResult:
    success: bool
    exit_code: int  # -1=timeout, -2=pyinstaller 미설치, -3=entry 부재
    elapsed_sec: float
    exe_path: Optional[Path]
    exe_size_bytes: Optional[int]
    sha256: Optional[str]
    stdout: str  # tail 100KB
    stderr: str  # tail 100KB
    error_message: Optional[str]
```

---

## 🔄 실제 워크플로우 (PR #36 부터 변경)

### 메인 워크플로우 — `analyze_and_implement` (PR #38 진행 중)

[src/workflows/analyze_and_implement.py](../../src/workflows/analyze_and_implement.py)

```python
run_analyze_and_implement(
    user_request="계산기 만들어줘",
    enable_gui_branch=True,      # Phase 4 GUI 분기
    enable_build_branch=True,    # Phase 4.5 빌드 사슬
    enable_release_branch=True,  # Phase 5 릴리스 사슬
    previous_version="0.1.0",
    repo_url="https://github.com/...",
    enable_executor=True,        # ⭐ PR #36/#37 신규 — 실제 PyInstaller 호출
    executor_timeout_sec=600,
)
```

### Phase 4.5 빌드 사슬 (PR #36 후 — executor 추가)

```
... 메인 체인 종료 ...
↓
Dep Analyzer → Build Engineer → Asset Manager → Installer Creator → Platform Tester
↓
[build_executor] — ⭐ enable_executor=True 시 활성
↓
실 PyInstaller subprocess 호출
↓
calculator.exe (10.7 MB) + SHA256 산출
↓
25_executor_result.md 자동 저장
```

---

## 🛠️ 실제 기술 스택 (사용 중)

| 카테고리 | v5 | v6 (변경) |
|---|---|---|
| 오케스트레이션 | CrewAI 1.14.1 + LangGraph | (변경 없음) |
| LLM 어댑터 | NexusAlphaLLM + Anthropic SDK | **NexusAlphaLLM + supports_function_calling=False** (PR #32) |
| 모니터링 | LangFuse | (변경 없음) |
| 테스트 | pytest + FakeProvider | **pytest (199개)** + FakeProvider |
| CI | GitHub Actions (ubuntu, py3.13) | (변경 없음, PR #25-36 모두 통과) |
| 로컬 환경 | Windows 11 + Python 3.13 | (변경 없음) |
| **빌드 도구** | (없음 — 사양만) | **PyInstaller 6.20.0** (PR #36 신규) |
| **출력 강제** | (자유 텍스트) | **Pydantic output_pydantic** (PR #31, #33) |

### 신규 인프라 (PR #29, #31, #33)

```
src/workflows/_common.py           ← 🆕 PR #29 (공유 헬퍼)
src/workflows/_schemas.py          ← 🆕 PR #31 + #33 (14 Pydantic 스키마 + sanitize)
src/agents/build_release/build_executor.py  ← 🆕 PR #36 (외부 도구 호출)
```

---

## 🛡️ 실제 보안 장치 (변경 없음)

v5 의 모든 보안 장치 + 다음 신규:

| 장치 | v5 | v6 (변경) |
|---|---|---|
| Audit Log | LangFuse trace | (변경 없음) |
| Max Iteration Limit | v3 ITER_CAP | (변경 없음) |
| Token Budget Gate | v3 BUDGET 결정 | (변경 없음) |
| **Output Schema 강제** | (없음) | **Pydantic output_pydantic 14 에이전트** (PR #31/#33) |
| **자동 재시도** | (없음) | **`retry_short_tasks_in_chain` 헬퍼** (PR #29) |
| **빌드 graceful failure** | (없음) | **build_executor 의 ExecuteResult** (PR #36) |
| **SHA256 자동 산출** | (사양만) | **build_executor 가 실제 계산** (PR #36) |

---

## 📂 실제 프로젝트 구조 (변경)

```
nexus-alpha/
├── src/
│   ├── agents/                  # 9개 본부, 23명 + 1도구
│   │   ├── c_level/             #   CTO, ConvergenceJudge
│   │   ├── analysis/            #   DataAnalyst, GapAnalyst, RequirementExpander
│   │   ├── planning/            #   UIUXAnalyst
│   │   ├── design/              #   GUIDesigner, ThemeDesigner, GUICodeGenerator
│   │   ├── engineering/         #   PythonEngineer
│   │   ├── qa/                  #   CodeReviewer
│   │   ├── knowledge/           #   Curator, RAGSearcher
│   │   ├── operations/          #   SandboxRunner
│   │   └── build_release/       #   Build 5 + Release 4 = 9명 + 🆕 build_executor (도구)
│   │
│   ├── workflows/               # 메인 + 보조 5개
│   │   ├── analyze_and_implement.py   # 메인 (4-agent + GUI/Build/Release/Executor 분기)
│   │   ├── iterative_loop.py          # v3 LangGraph 반복 개선
│   │   ├── build_workflow.py          # Phase 4.5 단독 + executor 통합 (PR #36)
│   │   ├── release_workflow.py        # Phase 5 단독
│   │   ├── router.py                  # Intent 라우팅
│   │   ├── _common.py                 # 🆕 PR #29 공유 헬퍼
│   │   └── _schemas.py                # 🆕 PR #31/#33 14 Pydantic 스키마
│   │
│   ├── llm/                     # NexusAlphaLLM + CrewAI 어댑터 (PR #32 호환 fix)
│   ├── monitoring/              # LangFuse 클라이언트
│   └── tests/                   # 35+ 파일, 199 passed
│
├── docs/
│   ├── architecture/
│   │   ├── nexus_alpha_v3.md         # v3 (반복 루프) 설계
│   │   ├── nexus_alpha_v4.md         # v4 (풀 비전) 설계
│   │   ├── nexus_alpha_org_v4.md     # 조직도 v4
│   │   ├── nexus_alpha_v5_built.md   # v5 (Phase 5 통합 시점) 구축
│   │   ├── nexus_alpha_v6_built.md   # 본 문서 (v6 = PR #36 시점)
│   │   ├── Nexus_Alpha_구성안_v4.4.md # v4.4 로드맵
│   │   ├── Nexus_Alpha_구성안_v5.md   # 🆕 v5 로드맵 (PR #36 반영)
│   │   ├── Nexus_Alpha_조직도_v5.1.md  # 조직도 v5.1
│   │   └── Nexus_Alpha_조직도_v6.md   # 🆕 조직도 v6 (PR #36 반영)
│   ├── progress/                # E2E 7회 + 세션 로그 + 이슈 close 기록
│   └── context/                 # CrewAI 호환성 노트
│
├── scripts/
│   └── run_e2e_verification.py  # 실 LLM E2E (PR #38 부터 enable_executor=True)
│
├── outputs/                     # 워크플로우 산출 + 🆕 build_output/dist/*.exe (PR #36)
├── .github/workflows/ci.yml     # ubuntu py3.13, pytest -v --tb=short
├── requirements.txt             # crewai==1.14.1 + 🆕 pyinstaller>=6.20.0 (PR #36)
└── .env                         # ANTHROPIC_API_KEY, LANGFUSE_*
```

---

## 🗺️ Phase 진행 실적 (v5 → v6)

| Phase | 상태 | PR 번호 | 비고 |
|---|---|---|---|
| Phase 0~5 | ✅ 완료 | PR #1~21 | v5 시점 |
| Phase 5 후속 | ✅ 완료 | PR #22~24 | v5 마무리 |
| **PR #25** | ✅ 완료 | 이슈 4 fix | GUI 4 에이전트 본문 누락 |
| **PR #26** | ✅ 완료 | E2E 재재검증 | 이슈 5 발견 |
| **PR #27** | ✅ 완료 | 이슈 5 fix | 비-GUI 16 에이전트 |
| **PR #28** | ✅ 완료 | 4차 E2E | 이슈 6 발견 |
| **PR #29** | ✅ 완료 | 방어선 1 | auto-retry 헬퍼 |
| **PR #30** | ✅ 완료 | 5차 E2E | 방어선 1 효과 미미 |
| **PR #31** | ✅ 완료 | 방어선 2 시범 | output_pydantic 2 에이전트 |
| **PR #32** | ✅ 완료 | 어댑터 fix + 6차 E2E | NexusAlphaLLM 호환성 + 시범 100% |
| **PR #33** | ✅ 완료 | 방어선 2 전체 확장 | 14 에이전트 + sanitize |
| **PR #34** | ✅ 완료 | 7차 E2E | 94% 도달, **이슈 6 close** |
| **PR #35** | ✅ 완료 | 세션 로그 정리 | 2026-04-27 단일 세션 종합 |
| **PR #36** | ✅ 완료 | **PyInstaller 통합** | **첫 진짜 `.exe` 산출** ⭐ |
| **PR #37** | 본 PR | architecture 문서 최신화 (v6) | (문서 정리) |
| 🔄 PR #38 (예정) | 진행 중 | 8차 E2E | 자연어 → `.exe` 풀체인 |

**총 PR**: 36개 / **누적 기간**: 11일 (2026-04-17 ~ 2026-04-28) / **테스트**: 199 passed

---

## 🧹 이슈 close 누적 (v5 → v6)

### 이슈 4 — GUI 에이전트 산출 본문 누락 ✅ **PR #25 close**

**증상**: GUI 4 에이전트 (UI/UX, Designer, Theme, Code Gen) 의 `task.output.raw` 가 Final Answer summary 한 줄만 캡처. 본문 마크다운 + 코드 블록 모두 손실.

**근본 원인**: 4 backstory 의 `"마지막 줄에 반드시 Final Answer: <summary>로 시작..."` 지시가 LLM 으로 하여금 본문을 Final Answer **앞**에 적게 함 → CrewAI 가 **이후 텍스트만** 캡처.

**해결**: 4 backstory 의 출력 규약을 `Final Answer: 라인 + 그 다음 줄부터 본문` 패턴으로 교체 + 회귀 방지 정적 grep 테스트 3건 추가.

### 이슈 5 — 비-GUI 16 에이전트 동일 패턴 ✅ **PR #27 close**

**증상**: PR #25 가 GUI 4 만 수정 → 동일 `마지막 줄 Final Answer:` 패턴이 비-GUI 16 에이전트 (QA + Build 5 + Release 4 + iterative_loop 6) 에 잔존.

**해결**: 16 backstory 패턴 일괄 치환 + 회귀 테스트 16 에이전트 정적 grep 추가.

### 이슈 6 — LLM 비결정적 컴플라이언스 ✅ **PR #29/#31/#33 close**

**증상**: prompt 자체는 정확하나 LLM 의 통계적 행동으로 가끔 본문 생략. 4차 E2E 에서 16 중 4 (25%) 짧음.

**방어선 1 (PR #29)**: auto-retry 헬퍼. 짧은 출력 감지 시 동일 task 재실행.
- 5차 E2E 결과: 캡처율 75% → 75% (정체) — systematic failure 에는 무력

**방어선 2 (PR #31, #32, #33)**: CrewAI `output_pydantic` 으로 schema 강제.
- PR #31 시범: BuildEngineer + ReleaseManager 100% 본문 캡처
- PR #32: NexusAlphaLLM 어댑터 `supports_function_calling=False` 호환성 fix
- PR #33: 12 추가 에이전트로 확장 (총 14) + cosmetic sanitize 헬퍼

**검증 (PR #34)**: 7차 E2E 캡처율 **94%** (15/16) — 이슈 6 사실상 close.

---

## 🎉 PR #36 — 첫 진짜 `.exe` 산출

### Smoke test 결과 (실 PyInstaller 호출)

이전 E2E (PR #34) 의 `calculator.py` 로 검증:

```
[BUILD SUCCESS] Calculator.exe (10.7 MB, sha256=7b66044e353edb10..., elapsed=18.4s)
```

| 항목 | 값 |
|---|---|
| 산출 경로 | `outputs/_smoke_test_pr36/dist/Calculator.exe` |
| 형식 | **PE32+ executable (GUI) x86-64, for MS Windows** |
| 크기 | 11,194,725 bytes (10.7 MB) |
| SHA256 | `7b66044e353edb10...` (전체 64자) |
| 빌드 시간 | **18.4초** (예상 1~3분 대비 매우 빠름) |

### 구현 요약

```python
# src/agents/build_release/build_executor.py
def execute_pyinstaller(
    entry_path: Path,
    output_dir: Path,
    app_name: str = "App",
    windowed: bool = True,
    onefile: bool = True,
    hidden_imports: Optional[list[str]] = None,
    icon_path: Optional[Path] = None,
    timeout_sec: int = 300,
    additional_args: Optional[list[str]] = None,
) -> ExecuteResult:
    """PyInstaller subprocess 호출 + 타임아웃 + graceful failure."""
```

15개 단위 테스트 (모킹된 subprocess 검증 + sanity 경로 검증).

### v5 → v6 차이

| 항목 | v5 | v6 |
|---|---|---|
| Build Engineer 산출 | LLM 사양 (markdown) | LLM 사양 (markdown) |
| `.exe` 산출 | ❌ 미달성 (외부 도구 미통합) | ✅ **달성** (build_executor 가 실 호출) |
| SHA256 | (사양만) | **실제 계산** (build_executor) |
| 풀체인 E2E | 사양 수준 | **실 `.exe` 까지 도달** (PR #38 진행 중) |

---

## 📊 v3 + v4 통합 그림 — v6 시점

```
                      [사용자]
                         │
                         ▼
         ┌───────────────────────────────┐
         │ Iteration Controller (v3)     │  → src/workflows/iterative_loop.py
         │ ┌───────────────────────────┐ │
         │ │ Requirement Expander (v3) │ │  ✅
         │ └───────────────┬───────────┘ │
         │                 ▼             │
         │ ┌───────────────────────────┐ │
         │ │ CTO ✅                     │ │  ✅ Phase 1
         │ │ Data Analyst ✅            │ │
         │ │ + UI/UX Analyst ✅         │ │  Phase 4
         │ │ + GUI Designer ✅          │ │  ✅ Phase 4 + PR #25/#33 (output_pydantic)
         │ │ + Theme Designer ✅        │ │  ✅ + 본문 캡처 안정화
         │ │ + GUI Code Generator ✅    │ │
         │ │ + Engineer ✅              │ │
         │ │ + Code Reviewer ✅         │ │  ✅ + PR #33 (output_pydantic)
         │ │ + Dep Analyzer ✅          │ │  ✅ Phase 4.5 + PR #33
         │ │ + Build Engineer ✅        │ │  ✅ + PR #31 (output_pydantic 시범)
         │ │ + Asset Manager ✅         │ │  ✅ + PR #33
         │ │ + Installer Creator ✅     │ │  ✅ + PR #33
         │ │ + Platform Tester ✅       │ │  ✅ + PR #33
         │ │ + Release Manager ✅       │ │  ✅ Phase 5 + PR #31
         │ │ + Changelog Generator ✅   │ │  ✅ + PR #33
         │ │ + Update Checker ✅        │ │  ✅ + PR #33
         │ │ + Distribution Agent ✅    │ │  ✅ + PR #33
         │ └───────────────┬───────────┘ │
         │                 ▼             │
         │ ┌───────────────────────────┐ │
         │ │ build_executor ⭐         │ │  ⭐ PR #36 신규 (도구)
         │ │ → pyinstaller subprocess  │ │
         │ │ → calculator.exe (10.7MB) │ │
         │ │ → SHA256 산출             │ │
         │ └───────────────┬───────────┘ │
         │                 ▼             │
         │ ┌───────────────────────────┐ │
         │ │ Gap Analyst ✅             │ │  Phase 2.5 (iterative_loop)
         │ │ Convergence Judge ✅      │ │
         │ └───────────────────────────┘ │
         └─────────────────┬─────────────┘
                           ▼
              ┌─────────────────────────────────┐
              │ outputs/workflow_<ts>/          │
              │   ├── 00~04, 10~13, 20~24, 30~33│
              │   ├── 25_executor_result.md ⭐  │  PR #36 신규
              │   ├── code/calculator.py        │  21,332자, py_compile 통과
              │   └── build_output/dist/        │  ⭐ PR #36 신규
              │       └── Calculator.exe (10MB)  │  ⭐ 첫 진짜 .exe
              └─────────────────────────────────┘

🔄 미달성 (외부 자동화 잔여):
   GitHub Releases 자동 업로드 → PR #38+ 예정
```

---

## 📚 v5 → v6 핵심 학습

### 1. 이슈는 *체계적* 일 수도, *통계적* 일 수도

- 이슈 4·5: 4·16 에이전트의 prompt 패턴 — backstory 수정으로 *결정적* 해결
- 이슈 6: LLM 의 *통계적* 행동 — prompt 만으론 100% 보장 불가, 외부 메커니즘 (output_pydantic schema 강제) 필요

### 2. 방어선 1 vs 방어선 2 — 측정으로 결정

- 방어선 1 (auto-retry): 직관적·간단·저비용. 그러나 systematic failure 에는 무력
- 방어선 2 (structured output): schema 강제로 출력 형태 자체를 LLM 이 위반 못 하게 함
- 5차 → 6차 → 7차 E2E 의 캡처율 데이터 (75% → 81% → 94%) 가 결정의 객관적 근거

### 3. 어댑터 호환성 부채는 production 에서 노출

NexusAlphaLLM 의 `supports_function_calling` 미구현이 PR #31 의 output_pydantic 시범에서 1차 E2E ConverterError 로 표면화. PR #32 의 1줄 fix (False 반환) 로 부분 호환성 확보.

### 4. cosmetic 이슈도 측정해야 발견됨

PR #32 6차 E2E 에서 `### 1. 도구 선택` 헤더 중복 (LLM 이 필드 안에 자체 헤더 포함) 발견. 시범 단계 효과 측정 안 했으면 14 에이전트 확장 후 발견됐을 것 → PR #33 sanitize 도입.

### 5. 도구 컴포넌트 vs LLM 에이전트 — 명확히 구분

build_executor 는 결정론적 코드 (subprocess + SHA256). LLM 아님. 본부 정원에 포함하지 않음. 향후 다른 외부 도구 통합 (gh release create 등) 도 동일 분리 원칙 적용.

### 6. graceful degradation 설계의 가치

- output_pydantic 파싱 실패 → task.output.pydantic = None → raw 사용
- to_markdown 예외 → raw fallback
- pytest 환경 → 모든 production 메커니즘 skip (FakeProvider 호환)
- build_executor 실패 → ExecuteResult.success=False, 예외 propagate 안 함

---

## 🔮 다음 단계 (Phase 6 이전 후보)

### 즉시 (PR #38~40)

- [ ] **PR #38 — 8차 E2E** (자연어 → calculator.exe 풀체인 검증) — 🔄 진행 중
- [ ] **PR #39 — GitHub Release 자동 업로드** (gh release create 실 호출)
- [ ] **PR #40 — Update Checker 산출 코드 통합** (산출 calculator.py 에 updater.py 임포트)

### 단기 (1~2주)

- [ ] **CLI 경로 E2E 검증** — 데이터 분석 시나리오로 CLI 분기도 정상 작동 확인
- [ ] **Streamlit UI 추가** (v1 계획 항목)
- [ ] **Vector DB 통합** (Qdrant) — Knowledge 본부 강화

### 중기 (1~2개월)

- [ ] **Phase 6 착수** (Track B 시작) — 5명 추가 (Web Scraping / Desktop Auto / API / Data Parser / DevOps)
- [ ] **Credential Vault** — 키 암호화 저장
- [ ] **RPA 분기 추가** (선택) — Web Scraping / Desktop Automation 에이전트 (v1 비전 부분 회귀)

### 장기 (3개월+)

- [ ] **CEO/CFO 에이전트 추가** (선택) — multi-project 동시 진행 시 의미 있을 수 있음
- [ ] **Helicone 통합** — 비용 세분 추적
- [ ] **Slack Bot** — 협업 환경 통합

---

## 📜 핵심 원칙 (v1 → v6 유지)

1. ✅ **작게 시작해서 점진적으로 확장** — Phase 0~5 + PR #25~36 단계별 진행 유지
2. ✅ **한 사이클이 완전히 작동한 후 다음 단계 진행** — 각 Phase 별 PR 분리
3. ✅ **모니터링 없이 개발 금지** — LangFuse 처음부터 연결
4. ✅ **파일럿으로 반드시 검증** — E2E 검증 7회 누적 (PR #21~34)
5. ✅ **외부 도구 통합은 graceful failure** — PR #36 부터 적용
6. ⚠️ **보안은 처음부터 제대로 설계** — 부분 적용 (FakeProvider 격리만, Credential Vault 미구축)

---

## 📜 변경 이력

| 버전 | 날짜 | 변경 |
|---|---|---|
| v1 | 2026-04-17 | RPA 원안 |
| v3 | 2026-04-17 | 자율 반복 루프 설계 |
| v4 | 2026-04-17 | 자연어 → .exe 풀 비전 설계 |
| v5 | 2026-04-21 | Phase 5 통합 시점 구축 상태 |
| **v6** | **2026-04-28** | **PR #25-36 반영: 이슈 4/5/6 close + 외부 도구 통합 첫 시작 + 첫 진짜 `.exe` 산출** |

---

*본 v6 구성안은 2026-04-28 기준 PR #36 머지 시점의 실제 구축 상태를 반영합니다.*
*PR #38 (8차 E2E) 완료 후 v6.1 로 업데이트 예정 — 자연어 → `.exe` 풀체인 검증 결과 추가.*

*v1 (2026-04-17 RPA 비전 원안) → v6 (2026-04-28 첫 진짜 `.exe` 산출) 의 비전 진화는
구현 과정에서 자연 발생한 점진적 진화이며, RPA 비전은 향후 Phase 6+ 의 선택적 분기로
재등장 가능합니다.*
