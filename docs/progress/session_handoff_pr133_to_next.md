# 🤝 세션 인계 문서 — PR #133 완료 → 다음 세션

**작성일**: 2026-05-14 (PR #133 머지 직후 새벽)
**작성자**: Claude Opus 4.7 (이전 세션)
**대상**: 다음 세션의 Claude (또는 사용자 본인 참조용)
**핵심 메시지**: PR #133 완전 마감. 베타 배포 단계 진입. 친구 1-2명 테스트 결과 받은 후 후속 PR 우선순위 결정.

---

## 📌 30초 요약

1. **Nexus Alpha** = 자연어 한 줄 → 동작하는 .exe + Draft Release URL 풀체인 자동화 (CrewAI + LangGraph)
2. **PR #133 머지 완료** (2026-05-14 새벽, squash commit `0060bd9`)
   - 16개 fixup 누적 (#133 본체 + fixup #1~#15)
   - pytest 937/937 통과 (이전 784 → +153, 회귀 0)
   - 라이브 5회 검증 완료 (4 빌드 성공 + 1 정확 차단)
   - main 브랜치 smoke test 통과 (환율 변환기 .exe 정상 동작)
3. **현재 상태**: 친구 1-2명 베타 배포 대기. 데이터 수집 후 PR #134~#136 우선순위 결정.
4. **사용자 (송종원)**: Korean ML 엔지니어 / PM, 한국어 대화 선호, PR 단위 머지 패턴, 회귀 검증 + false positive 위험 0 우선

---

## 🎯 PR #133 의 핵심 가치 (사용자 명시)

> **"이 도구를 다른 사람에게 배포해서 테스트시킬 예정. LLM 의 가끔 잘못된 API 호출 (flet.colors, padding.symmetric 등) 이 일반 사용자에게 노출되면 안 됨. 사전 차단 필수."**

이 한 문장이 PR #133 의 fixup 시퀀스 전체를 관통하는 *철학*. 특히 **fixup #14 (정적 attribute 검증)** 가 이 목표 달성의 핵심.

---

## 📜 16 Fixup 시퀀스 — 사용자 라이브 검증 주도 점진적 개선

| Fixup | 트리거 | 핵심 변경 |
|-------|--------|----------|
| **PR #133 본체** | calculator.py 의 `ModuleNotFoundError: customtkinter` | embeddable Python 경로 제거 + workflow 의 자동 pip install (B안) + AST primary |
| #1 | MSI uninstall 1603 (Burn cache 손상) | orphan MSI registry + Package Cache + Add/Remove Programs 강제 정리 |
| #2 | "지정된 파일을 찾을 수 없습니다" (retry 직전 installer 삭제) | finally 의 `Remove-Item` 제거 → installer 를 retry 까지 유지 |
| #3 | retry 시점에 또 installer 사라짐 (AntiVirus 등) | retry 직전 *조건 없이* 재다운로드 |
| **#4** | MSI 로그 분석 — sub-MSI 가 "Present" 로 detect | **Windows Installer per-user MSI 등록** (`HKCU\Software\Microsoft\Installer\Products`) 직접 삭제 |
| #5 | py -3.13 이 embeddable Python (tkinter 없음) 가리킴 | 모든 Python 검출 경로에 tkinter import 검증 추가 |
| **#6** | calculator.exe runtime `ModuleNotFoundError: flet` (LLM 변동성) | LLM 보고서 + entry AST 스캔 **UNION**, pip name 정규화, --collect-all, halt on fail |
| #7 | `theme`/`views`/`storage` 가 외부 패키지로 오인 | code_files 의 sibling .py / 패키지 디렉토리 → local_modules set, 필터 추가 |
| **#8** | PySide6 + PyQt6 동시 보고 → PyInstaller abort | **AST primary** (LLM direct_deps 버림), mutex groups (Qt/OpenCV/tensorflow), --collect-all 화이트리스트 |
| **#9** | theme.py 가 entry 로 잘못 선택 (no-op .exe) | `_select_entry_point`: `__main__` block **PRIORITY 1**, entry_hint 강등 |
| #10 | Flet 의 `flet_desktop` transitive runtime dep 누락 | multi-package runtime extras 매핑 (flet → flet-desktop) |
| **#11** | `flet.controls.padding.symmetric` 런타임 AttributeError | pre-PyInstaller subprocess validation (5s timeout + 에러 패턴 검출) + LLM hidden_imports 필터 |
| **#12** | `test_calculator.py` 가 entry 로 잘못 선택 | `_is_test_file` 패턴 (test_/*/conftest) → test 파일 entry 후보에서 배제 |
| **#13** | sandbox_runner.py line 504 decode-on-str 버그 → 빌드 전체 crash | subprocess.run → Popen + 명시적 cleanup + ignore_cleanup_errors + graceful catch |
| **#14** | Flet popup: "module 'flet' has no attribute 'colors'" | **정적 module attribute 검증** (AST chain + importlib.getattr 실제 검증) — 사용자 명시 요구의 핵심 |
| **#15** | Test_Clock_Widget.exe 빌드 성공 but useless (LLM 이 test 파일만 생성) | FALLBACK 제거 → test 파일만 있을 때 None 반환 + 명시적 build fail |

(굵게 표시된 fixup 이 *결정적 변화* — 나머지는 보조 패치)

---

## ✅ 라이브 5회 검증 결과 (사용자 요구 우선순위 반영)

| 회차 | 결과 | .exe / 크기 | GUI 라이브러리 (추정) | 의미 |
|------|------|-------------|----------------------|------|
| **1차** | ✅ 정상 | Calculator.exe / 35.23 MB | customtkinter / PySide6 (heavy) | 회귀 확인 — 정상 빌드 |
| **2차** | ✅ 정상 | Todo_App.exe / 10.70 MB | Tkinter (light) | 회귀 확인 — 다른 lib 동작 |
| **3차** 🔥 | **정확 차단** | (.exe 없음) | Flet | **fixup #14 정상 작동** (`flet.colors`, `padding.symmetric`, `alignment.center`, `alignment.center_right` 4개 거짓 API 사전 검출) |
| **4차** | ✅ 정상 | Notepad.exe / 10.70 MB | Tkinter | GUI 라이브러리 다양성 충족 |
| **5차** | ⚠️ useless | Test_Clock_Widget.exe / 32.74 MB | (LLM 이 test 파일만 생성) | → **fixup #15 추가** 후 향후 차단 |

### main 브랜치 smoke test (PR #133 머지 후, 2026-05-14 새벽)

| 항목 | 결과 |
|------|------|
| 빌드 시간 | 23.05 분 |
| `.exe` | Currency_Converter.exe / 10.70 MB |
| GUI 동작 | ✅ **실시간 환율 표시** (1 USD = 1,365.5 KRW), 변환 정상 작동 |
| LLM 의도 매칭 | ✅ "환율 변환기" 정확 생성 |

**결론**: 베타 배포 진행 가능.

---

## 🔍 PR #133 의 핵심 파일 (다음 세션 참조용)

### 코드
- [src/workflows/build_workflow.py](../../src/workflows/build_workflow.py) — Track A 의 PyInstaller 호출 파이프라인. 모든 fixup 의 핵심 변경 위치.
  - `_select_entry_point` (fixup #9/#12/#15) — entry 선택 4단 우선순위
  - `_resolve_build_deps` (fixup #6/#7/#8/#10/#11) — BuildDepsResolution dataclass 반환
  - `_pre_pyinstaller_validation` (fixup #11) — subprocess 5s timeout
  - `_validate_module_attributes` (fixup #14) — AST + importlib.getattr 정적 검증
- [src/workflows/automate_workflow.py](../../src/workflows/automate_workflow.py) — Track B 도 동일 패턴 적용
- [src/agents/build_release/build_executor.py](../../src/agents/build_release/build_executor.py) — execute_pyinstaller (fixup #6/#8 — `collect_all` + `exclude_modules` 인자 추가)
- [src/agents/operations/sandbox_runner.py](../../src/agents/operations/sandbox_runner.py) — fixup #13 의 Popen 전환 + cleanup
- [install.ps1](../../install.ps1) — PR #133 본체 + fixup #1~#5 의 install 견고성 강화

### 테스트
- [src/tests/test_pr133_deps_autoinstall.py](../../src/tests/test_pr133_deps_autoinstall.py) — fixup #6~#10/#12/#15 의 핵심 테스트
- [src/tests/test_pr133_fixup13_sandbox_robustness.py](../../src/tests/test_pr133_fixup13_sandbox_robustness.py) — sandbox 견고성
- [src/tests/test_pr133_fixup14_static_attribute_validation.py](../../src/tests/test_pr133_fixup14_static_attribute_validation.py) — 정적 attribute 검증 (21 테스트)
- [src/tests/test_alpha_run_entry.py](../../src/tests/test_alpha_run_entry.py) — install.ps1 정적 검증 (79 테스트)

### 문서
- [docs/progress/pr133_alpha_deployment_summary.md](./pr133_alpha_deployment_summary.md) — PR #133 작업 정리 (8 섹션, 사용자 매뉴얼 포함)
- [docs/WORK_STATUS.md](../WORK_STATUS.md) — 프로젝트 전체 진행 상황 대시보드 (PR #133 머지 후 갱신됨)

---

## 🚀 베타 배포 매뉴얼 (친구 1-2명에게 전달용)

### 친구에게 보내는 메시지 (복붙용)

> Nexus Alpha 베타 테스터 부탁합니다.
>
> 자연어 한 줄로 GUI 앱 .exe 를 자동 생성하는 도구입니다.
>
> **필요 환경:**
> - Windows 10 / 11
> - 인터넷 연결 (~1GB 다운로드)
> - 빈 디스크 공간 ~3GB
>
> **1단계 — 설치 (~5분)**
>
> PowerShell 열고:
> ```powershell
> irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex
> ```
> "🎉 Nexus Alpha 가 준비됐습니다." 메시지 뜨면 성공.
>
> **2단계 — 실행**
>
> 새 PowerShell 창에서:
> ```powershell
> cd $HOME\nexus-alpha
> .\.venv\Scripts\python.exe scripts\run.py
> ```
>
> **3단계 — 요청 입력**
>
> - `요청:` 에 만들고 싶은 앱 자연어로 입력 (예: "메모장 만들어줘 - 다크모드")
> - `선택`: **Enter** (자동 라우팅)
> - `빌드`: `y`
>
> **4단계 — 약 20~25분 대기**
>
> 마지막에 `.exe` 경로 표시 → 더블클릭으로 실행.
>
> **결과 알려주세요:**
> - OS (Windows 10 / 11)
> - install.ps1 완료 여부
> - 어떤 요청 입력했는지
> - 빌드 시간
> - .exe 이름 / 크기 / 동작 여부
> - 에러 발생 시 PowerShell 화면 캡처

---

## 🔮 식별된 후속 PR (베타 데이터 받은 후 우선순위 결정)

### PR #134 — LLM intent 매칭 강화
- **트리거**: 친구 PC 에서 또 useless .exe 발생 시
- **내용**:
  - `src/agents/design/gui_code_generator.py` 의 system prompt 보강
  - "엔트리 파일은 반드시 app.py 또는 main.py 로 명명"
  - "test_*.py 파일에 `__main__` 블록 두지 말 것 (테스트는 pytest 가 발견)"
  - "사용하는 라이브러리의 모든 attribute 와 method 는 해당 버전에서 실제로 존재해야 함"
  - "다른 GUI 프레임워크의 import 는 절대 추천하지 말 것 (flet 앱에 PySide6 X)"
- **추정 시간**: ~1-2 시간

### PR #135 — 좀비 프로세스 cleanup + 부가 결함
- **트리거**: 친구가 거슬려하거나 베타 보고서에 자주 등장
- **내용**:
  1. Flet 의 Flutter daemon 등 Windows subprocess 잔존 — `psutil.Process.children(recursive=True)` 강제 kill
  2. LangFuse traces 401 graceful fallback (API 키 미설정 시 자동 disable)
  3. langgraph `cache.base.__init__` 의 `allowed_objects` deprecation warning 명시 처리
- **추정 시간**: ~2-3 시간

### PR #136 — README + 베타 배포 가이드 공식화
- **트리거**: 베타 1-2 거치고 안정화되면
- **내용**:
  - README 에 알려진 한계 명시 (LLM 변동성, 빌드 시간, 호환 OS 등)
  - 베타 배포 공식 가이드 추가 (위 매뉴얼 정리)
  - 트러블슈팅 섹션
- **추정 시간**: ~1 시간

---

## 🛡️ 다음 세션이 주의할 점

### 1. 사용자 (송종원) 의 작업 스타일
- **PR 단위 머지 패턴** — 작은 PR 자주, 누적 안 함
- **회귀 검증 1순위** — 기존 통과 시나리오 깨지지 않게 (fixup #14 시 명시적 요구)
- **False positive 위험 0 우선** — 모르겠으면 통과 (특히 정적 분석)
- **사용자 PC 노출 0** — LLM 결함 → 빈 .exe 양산 절대 회피
- **한국어 대화** — 모든 답변 한국어

### 2. PR #133 의 정책 결정사항 (변경 시 신중)
- **AST primary** — LLM의 dependency_report 의 `direct_dependencies` 는 *버림* (fixup #8). LLM 변동성 차단의 핵심.
- **`__main__` block PRIORITY 1** — entry_hint 보다 우선 (fixup #9). 호출 측의 잘못된 hint 무력화.
- **Test 파일 entry 배제** — FALLBACK 없이 None 반환 (fixup #15). useless .exe 양산 금지.
- **2 단계 pre-validation** — subprocess timeout (fixup #11) + 정적 attribute (fixup #14). 둘 다 필수.

### 3. 메모리에 이미 기록된 내용 (재읽기 권장)
- [project_pr133_alpha_distribution_ready.md](C:\Users\woker\.claude\projects\c--projects-nexus-alpha\memory\project_pr133_alpha_distribution_ready.md) — PR #133 완료 요약
- [project_install_ps1_encoding_gap.md](C:\Users\woker\.claude\projects\c--projects-nexus-alpha\memory\project_install_ps1_encoding_gap.md) — install.ps1 의 한국어 Windows CP949 디코딩 gap (irm|iex 안전, 로컬 file 실행은 미해결)
- [feedback_n_failure_diagnosis.md](C:\Users\woker\.claude\projects\c--projects-nexus-alpha\memory\feedback_n_failure_diagnosis.md) — 동일 패턴 N회 실패 = 결정적 결함

### 4. 다음 세션 시작 시 추천 첫 행동
1. **친구 베타 결과 확인 질문** — "친구 PC 에서 시도해보셨나요? 결과는?"
2. 결과에 따라:
   - 정상 동작 → PR #134~#136 우선순위 사용자와 협의
   - 문제 발생 → PowerShell 출력 / 25_executor_result.md 확인 → 진단

---

## 📊 통계 (PR #133 완료 시점)

| 지표 | 값 |
|------|-----|
| 머지된 PR | **133** (직전 132 → +1) |
| pytest 통과 | **937** (직전 ~784 → +153) |
| 회귀 발생 | **0** (모든 fixup 후) |
| 라이브 검증 회차 | **5 + main smoke test 1 = 6** |
| 빌드 풀체인 성공률 | **5/6 (83%)** + 1/6 정확 차단 |
| GUI 라이브러리 다양성 검증 | customtkinter (heavy) / Tkinter (light) / Flet (블록됨) = **3종** |
| 식별된 후속 PR | #134 / #135 / #136 |
| 베타 배포 준비도 | ✅ **준비 완료** |

---

## 💬 새 세션 시작 시 사용자가 줄 만한 메시지 예시

### 시나리오 A — 베타 정상 동작
> "친구 PC 에서 잘 됐어. [친구 PC OS] 에서 [요청] 했는데 [N]분 만에 [앱] .exe 정상 동작 확인. 이제 다음 단계는?"

→ 답변: PR #134~#136 중 어떤 것 먼저 진행할지 협의. 친구 결과 데이터 (앱 종류 / 라이브러리 / 시간) 누적 → 어떤 PR 이 가장 시급한지 판단.

### 시나리오 B — 친구 PC 에서 문제 발생
> "친구 PC 에서 안 됐어. [에러 화면 / 메시지]"

→ 답변:
1. 친구 PC 의 PowerShell 출력 + 25_executor_result.md 요청
2. 진단 (어느 fixup 단계에서 실패?)
3. 필요 시 즉시 PR (예: #134 의 부분 구현) 또는 새 fixup

### 시나리오 C — 사용자가 직접 다른 작업 요청
> "PR #134 시작해줘" / "메모리 확인해줘" / "다른 작업 [X]"

→ 답변: 본 문서 + 메모리 + WORK_STATUS 참조 후 진행.

---

## 🔗 참조 링크

- **GitHub Repo**: https://github.com/SongJongwon/nexus-alpha
- **PR #133**: https://github.com/SongJongwon/nexus-alpha/pull/133 (머지됨)
- **main 브랜치 install URL**: `https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1`
- **사용자 PC 의 nexus-alpha**: `C:\Users\woker\nexus-alpha\` (이미 main 으로 동기화됨)

---

**이 문서를 새 세션 시작 시 가장 먼저 읽어주세요. 그 다음 메모리 (`MEMORY.md`) → WORK_STATUS.md 순으로 컨텍스트 복원.**

**작성 완료**: 2026-05-14 새벽 (PR #133 머지 직후)
**다음 마일스톤**: 친구 1-2명 베타 결과 → PR #134~#136 우선순위 결정
