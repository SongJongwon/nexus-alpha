# Nexus Alpha v4 — 완전 자율 빌드 설계

- **문서 버전**: v4 (2026-04-17)
- **상태**: 설계안 — Phase 3까지 완료 후 착수 예정
- **선행 조건**: v3 자율 반복 루프(Phase 2.5) + Phase 3 실행 엔진 통합

---

## 1. 비전

**한 문장 비전**:

> 사용자가 *"계산기를 만들어줘"* 라고 말하면, Nexus Alpha가 알아서 GUI를 디자인하고, 코드를 작성하고, `.exe`로 빌드하고, 설치 관리자로 패키징하고, 다운로드 가능한 형태로 배포 가능한 상태까지 가져온다.

이 비전은 **2026-04-17 세션의 핵심 발견**에서 나왔다. 사용자가 "계산기 만들어줘" 같은 단순 요청을 던졌을 때 Nexus Alpha v1/v2가 실제로 산출한 결과는 다음 셋 중 하나였다:

| 산출 | 사용자 기대 | 간극 |
|---|---|---|
| 데이터 분석 파이프라인 (`calc_report/`) | 계산기 앱 | **완전 빗나감** — 워크플로우가 분석 템플릿에 결합됨 |
| 단일 `calculator.py` REPL (콘솔) | 더블클릭 실행 가능한 GUI 앱 | **형태(form factor)가 다름** |
| GUI 코드(Tkinter) — 가끔 | `.exe` 더블클릭 실행 | **빌드/패키징 단계 부재** |

**근본 원인 분석**:
- v1~v2의 산출물은 항상 "**사람이 추가 작업을 해야 쓸 수 있는** 코드 스니펫"이다.
- 일반 사용자가 기대하는 "완성품"은 *코드가 아니라 실행 파일*이다.
- 코드 → 실행 파일 변환에는 디자인·빌드·패키징·배포 4단계가 필요한데, v1~v2에는 이 단계의 에이전트가 없다.

**v4의 정의**: 위 4단계를 채워 **CLI 코드가 아니라 .exe (또는 macOS의 .app, Linux의 AppImage)** 를 산출하는 시스템.

---

## 2. 간극 분석 — CLI에서 .exe까지

### 2-1. 현재 (Phase 1~2.5 누적)

```
사용자 요청
  ↓
[기획·분석·설계]  ← v3까지 완료 시 반복 보장됨
  ↓
[코드 생성]       ← Engineer (Phase 1)
  ↓
[코드 품질 검증]  ← QA (Phase 2)
  ↓
산출: outputs/workflow_<ts>/code/*.py    ← 여기서 멈춤
```

### 2-2. v4 목표 상태

```
사용자 요청
  ↓
[기획·분석·설계]
  ↓
[GUI 디자인]      ← 🆕 Phase 4
  ↓
[코드 생성 (GUI 포함)]
  ↓
[코드 품질 검증]
  ↓
[빌드 & 패키징]   ← 🆕 Phase 4.5
  ↓
[배포 & 업데이트] ← 🆕 Phase 5
  ↓
산출: dist/<product>-<version>-setup.exe (다운로드 링크 또는 release URL)
```

### 2-3. 간극 메우는 13명의 신규 에이전트

| Phase | 본부 | 신규 에이전트 | 인원 |
|---|---|---|---|
| 4 | 기획 및 설계 | UI/UX Analyst | 1 |
| 4 | **🆕 디자인 (신설)** | GUI Designer · GUI Code Generator · Theme Designer | 3 |
| 4.5 | **🆕 빌드 & 배포 (신설)** | Build Engineer · Dependency Analyzer · Asset Manager · Installer Creator · Platform Tester | 5 |
| 5 | 빌드 & 배포 | Release Manager · Changelog Generator · Update Checker · Distribution Agent | 4 |
| | | **합계** | **13** |

조직도 자세한 위치·책임은 [nexus_alpha_org_v4.md](./nexus_alpha_org_v4.md) 참조.

---

## 3. Phase 4 — GUI 자동 생성

### 3-1. 목표
사용자가 별도 지정하지 않아도 **요청의 형태(form factor)를 추론**해 적절한 GUI를 자동 생성한다. 단순 요청은 단순 UI, 복잡 요청은 멀티 패널 UI.

### 3-2. 단계별 흐름

```
1) UI/UX Analyst    : 요청 분석 → "이 앱은 어떤 UI 패턴이 적절한가" 판정
                       (예: 입력+출력 1:1 → 단일 윈도우 / 워크플로우형 → 탭 또는 위저드)
                       산출: ui_spec.yaml (윈도우 수, 위젯 트리, 레이아웃 그리드)

2) GUI Designer     : ui_spec → 고/저 충실도 와이어프레임 (텍스트 기반 ASCII 또는
                       SVG mock). 색상·타이포·간격은 후속 Theme Designer에 위임.
                       산출: wireframe.md / mock.svg

3) Theme Designer   : 디자인 시스템 토큰(palette, typography, spacing) 결정.
                       기존 OS 룩&필 따를지(native) 커스텀 갈지 판단.
                       산출: design_tokens.json

4) GUI Code Generator: ui_spec + wireframe + design_tokens → 실제 UI 코드 생성
                       (Tkinter / PyQt6 / Flet / customtkinter 중 선택).
                       기존 Python Engineer는 비즈니스 로직 담당, 이 에이전트는 UI 레이어 전담.
                       산출: src/<pkg>/gui/*.py
```

### 3-3. UI 프레임워크 선택 정책 (기본값)

| 요청 복잡도 | 기본 프레임워크 | 이유 |
|---|---|---|
| 단순 (위젯 5개 이하, 단일 윈도우) | **Tkinter + customtkinter** | 표준 라이브러리, 빌드 시 의존성 최소, .exe 크기 작음 |
| 중간 (멀티 윈도우, 차트, 테이블) | **Flet** (Flutter 기반) | 단일 코드베이스로 데스크톱·웹·모바일 동시 대응 |
| 복잡 (미디어, 고급 인터랙션) | **PyQt6** | 성숙도, 위젯 풍부함, but 라이선스·.exe 크기 주의 |

**원칙**: UI/UX Analyst가 먼저 "요청 복잡도"를 판정하고, GUI Code Generator는 그 판정에 따라 프레임워크를 선택한다. 사용자가 명시한 경우는 그 선택을 우선.

### 3-4. UI/UX Analyst가 답해야 할 5가지 질문

1. **단일 윈도우인가, 다중 윈도우/탭인가?**
2. **데이터 입출력은 어떤 단위인가?** (한 번에 한 값 / 표 / 시계열 / 미디어)
3. **상태(state)는 휘발성인가, 영속인가?** (영속이면 로컬 DB가 추가 필요)
4. **사용자 학습곡선은 몇 분인가?** (1분 < 단순, 10분+ → 위저드/온보딩 필요)
5. **접근성 요구가 있는가?** (키보드 단축키, 스크린리더, 다크모드 등)

이 5가지 답이 ui_spec.yaml의 필수 필드.

---

## 4. Phase 4.5 — 빌드 & 패키징

### 4-1. 목표
Python 코드를 **사용자 PC에 Python이 설치되어 있지 않아도 동작하는 단일 실행 파일**로 변환한다. Windows는 `.exe`, macOS는 `.app`/`.dmg`, Linux는 AppImage가 표준 산출.

### 4-2. 단계별 흐름

```
1) Dependency Analyzer : import 그래프 정적 분석 → 외부 의존성 목록 + 라이선스 점검
                          숨겨진 의존성(__import__, importlib) 탐지
                          산출: dependencies.lock + license_report.md

2) Asset Manager       : 아이콘, 폰트, 이미지, 데이터 파일 수집 및 빌드 시 포함 경로 결정
                          PyInstaller `--add-data` 인자 / Nuitka 옵션 자동 생성
                          산출: build_assets.spec

3) Build Engineer      : 빌드 도구 선택(PyInstaller / Nuitka / cx_Freeze) 후 실행
                          빌드 실패 시 오류 패턴 인식 → 수정안 제시
                          산출: dist/<product>.exe (또는 .app, AppImage)

4) Platform Tester     : 빌드 산출물을 깨끗한 가상환경(또는 Windows Sandbox / Docker)에서
                          기본 동작 시나리오 자동 실행. 실행 실패는 빌드 회귀로 간주
                          산출: smoke_test_report.md

5) Installer Creator   : 단일 .exe + 종속 자원을 설치 관리자로 패키징
                          (Windows: Inno Setup / WiX, macOS: pkgbuild, Linux: AppImage 자체)
                          산출: dist/<product>-<version>-setup.exe
```

### 4-3. 빌드 도구 선택 정책 (기본값)

| 우선 순위 | 도구 | 적용 조건 |
|---|---|---|
| 1 | **PyInstaller** | 일반적인 Python 앱. 가장 검증되고 문서가 풍부함. |
| 2 | **Nuitka** | 성능이 중요한 앱(C 컴파일), 또는 PyInstaller로 빌드 실패한 경우 |
| 3 | **cx_Freeze** | 위 둘 모두 실패 시 fallback |

Build Engineer는 1→2→3 순으로 시도하며, 모두 실패 시 v3 루프의 BLOCKED 경로로 에스컬레이션.

### 4-4. Dependency Analyzer가 잡아야 하는 함정

- **Hidden imports** — `numpy`, `pandas`, `matplotlib` 등은 PyInstaller가 자동 감지하지 못하는 lazy import가 많음. 사전 화이트리스트로 강제 포함.
- **Native binaries** — `cv2`, `tensorflow` 등의 .dll/.so 파일이 빠지면 런타임 오류.
- **License conflicts** — GPL 라이선스 의존성이 들어가면 산출물도 GPL이 강제됨. 사용자에게 사전 고지.
- **OS-specific deps** — `win32api` 같은 Windows 전용 의존성이 macOS 빌드에 들어가면 즉시 실패.

### 4-5. Platform Tester가 검증하는 것

| 검증 항목 | 기준 | 실패 시 |
|---|---|---|
| 빌드 산출물이 실제로 실행되는가 | exit code 0 | 빌드 회귀 — Build Engineer로 피드백 |
| 메인 윈도우가 표시되는가 | UI Automation으로 확인 | GUI Code Generator로 피드백 |
| 핵심 기능 1개 시나리오 (예: "1 + 1 = 2") | 자동 입력 → 출력 검증 | 비즈니스 로직 회귀 — Engineer로 피드백 |
| 시작 시간 | < 5초 (조정 가능) | 경고만, 차단 아님 |
| 산출물 크기 | < 200MB (조정 가능) | 경고만, 차단 아님 |

---

## 5. Phase 5 — 배포 자동화

### 5-1. 목표
"Nexus Alpha가 만든 산출물을 사용자가 한 번의 다운로드로 설치할 수 있는 상태"까지.

### 5-2. 4명의 에이전트

```
1) Release Manager     : 버전 번호 결정(SemVer), 릴리스 노트 초안 생성, Git 태그 부착
                          정책: 사용자 요청 변화량에 따라 major/minor/patch 자동 판정
                          산출: tag v1.2.3 + RELEASE.md

2) Changelog Generator : 이번 릴리스에 포함된 변경 사항을 사용자 친화적 한국어로 요약
                          (Iteration Controller의 history를 입력으로 사용)
                          산출: CHANGELOG.md (Keep a Changelog 규약)

3) Update Checker      : 산출물에 "자동 업데이트 체크" 모듈 삽입
                          (예: 앱 시작 시 GitHub Releases API 호출 → 신버전 알림)
                          산출: <pkg>/updater.py + 옵션 토글

4) Distribution Agent  : 산출물을 어디에 어떻게 올릴지 결정·실행
                          (GitHub Releases / S3 / 단순 파일 서버)
                          체크섬 생성, 다운로드 URL 생성, 사용자에게 전달
                          산출: download URL + SHA256 hash
```

### 5-3. Distribution Agent의 채널 우선순위

| 우선 순위 | 채널 | 적용 조건 |
|---|---|---|
| 1 | **GitHub Releases** | public 또는 private repo가 있을 때. 무료, 검증됨. |
| 2 | **사내 파일 서버 / 회사 클라우드** | 기업용 산출물(외부 노출 금지) |
| 3 | **S3 + presigned URL** | 일회성 공유, 만료 시간 설정 가능 |
| 4 | **로컬 파일만** | 모든 채널 거부 시 fallback. 사용자에게 경로만 안내. |

### 5-4. 보안 고려

- **코드 서명(Code Signing)** — Windows에선 서명 안 된 .exe가 SmartScreen 경고를 띄움. 인증서 보유 시 자동 서명, 없으면 사용자에게 우회 안내.
- **체크섬 표기** — 모든 다운로드 URL과 함께 SHA256 해시를 동봉.
- **업데이트 채널 검증** — Update Checker는 HTTPS만 허용, TLS 인증서 검증 필수.

---

## 6. 신규 에이전트 13종 카탈로그

| # | 에이전트 | 본부 | 파일 경로 | Phase |
|---|---|---|---|---|
| 1 | UI/UX Analyst | 기획 및 설계 | `src/agents/planning/ui_ux_analyst.py` | 4 |
| 2 | GUI Designer | 디자인 | `src/agents/design/gui_designer.py` | 4 |
| 3 | GUI Code Generator | 디자인 | `src/agents/design/gui_code_generator.py` | 4 |
| 4 | Theme Designer | 디자인 | `src/agents/design/theme_designer.py` | 4 |
| 5 | Build Engineer | 빌드 & 배포 | `src/agents/build_release/build_engineer.py` | 4.5 |
| 6 | Dependency Analyzer | 빌드 & 배포 | `src/agents/build_release/dependency_analyzer.py` | 4.5 |
| 7 | Asset Manager | 빌드 & 배포 | `src/agents/build_release/asset_manager.py` | 4.5 |
| 8 | Installer Creator | 빌드 & 배포 | `src/agents/build_release/installer_creator.py` | 4.5 |
| 9 | Platform Tester | 빌드 & 배포 | `src/agents/build_release/platform_tester.py` | 4.5 |
| 10 | Release Manager | 빌드 & 배포 | `src/agents/build_release/release_manager.py` | 5 |
| 11 | Changelog Generator | 빌드 & 배포 | `src/agents/build_release/changelog_generator.py` | 5 |
| 12 | Update Checker | 빌드 & 배포 | `src/agents/build_release/update_checker.py` | 5 |
| 13 | Distribution Agent | 빌드 & 배포 | `src/agents/build_release/distribution_agent.py` | 5 |

> 디자인 본부는 3명, Phase 4 신설 인원 4명 중 **UI/UX Analyst는 기획 및 설계 본부 소속**으로 분류한다. 이유는 [nexus_alpha_org_v4.md §3-2](./nexus_alpha_org_v4.md) 참조.

---

## 7. 기술 선택 — 디자인·빌드·배포 도구 매트릭스

| 단계 | 1순위 | 2순위 | fallback |
|---|---|---|---|
| GUI 프레임워크 (단순) | Tkinter + customtkinter | Flet | PyQt6 |
| GUI 프레임워크 (복잡) | Flet | PyQt6 | (Electron 등 비-Python 검토) |
| 빌드 도구 | PyInstaller | Nuitka | cx_Freeze |
| 인스톨러 (Win) | Inno Setup | WiX | NSIS |
| 인스톨러 (mac) | pkgbuild + productbuild | DMG (create-dmg) | (zip만) |
| 인스톨러 (Linux) | AppImage | Flatpak | (tar.gz만) |
| 코드 서명 (Win) | signtool + EV cert | self-signed (개발용만) | 없음 + SmartScreen 안내 |
| 배포 채널 | GitHub Releases | S3 presigned | 로컬 파일만 |

---

## 8. 로드맵 & 의존성

```
v3 (Phase 2.5) — 자율 반복 루프         ← 선행 필수 (품질 보장)
   │
   ▼
Phase 3 — 실행 엔진 통합                ← 선행 필수 (Platform Tester가 사용)
   │
   ▼
Phase 4 — GUI 자동 생성 (4 agents)      ← v4 본격 시작
   │
   ▼
Phase 4.5 — 빌드 & 패키징 (5 agents)    ← Phase 4 산출 코드를 입력으로
   │
   ▼
Phase 5 — 배포 자동화 (4 agents)        ← Phase 4.5 산출 .exe를 입력으로
```

### 단계별 수용 기준 (Definition of Done)

#### Phase 4 (GUI)
- [ ] "계산기 만들어줘" 요청에 대해 Tkinter 기반 GUI 코드가 자동 생성됨
- [ ] 생성된 GUI가 PyInstaller 없이도 `python` 으로 실행 가능
- [ ] UI/UX Analyst가 단순/중간/복잡 요청 3종에 대해 서로 다른 ui_spec을 산출

#### Phase 4.5 (빌드)
- [ ] 위 GUI 코드를 PyInstaller로 .exe 빌드 성공
- [ ] Windows Sandbox / 깨끗한 VM에서 .exe 실행 → "1+1=2" 시나리오 자동 검증 통과
- [ ] Inno Setup으로 setup.exe 생성, 설치 → 시작 메뉴 등록 → 실행 시나리오 통과

#### Phase 5 (배포)
- [ ] GitHub Releases에 setup.exe 자동 업로드
- [ ] CHANGELOG.md 자동 생성, RELEASE.md 한국어 요약 포함
- [ ] 다운로드 URL + SHA256 hash가 워크플로우 결과로 사용자에게 반환
- [ ] **최종 검증**: "계산기 만들어줘" 한 마디 → 다운로드 가능한 setup.exe URL 까지 자동 도달

---

## 9. v3 / v4 / Phase 1~2 의 합성 그림

```
                      [사용자]
                         │
                         ▼
         ┌───────────────────────────────┐
         │ Iteration Controller (v3)     │
         │ ┌───────────────────────────┐ │
         │ │ Requirement Expander (v3) │ │
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ CTO → Analyst → ...       │ │  ← Phase 1 (3명)
         │ │ + UI/UX Analyst (v4)      │ │  ← Phase 4
         │ │ + GUI Designer (v4)       │ │  ← Phase 4
         │ │ + Theme Designer (v4)     │ │  ← Phase 4
         │ │ + Engineer + GUI Coder    │ │  ← Phase 1 + Phase 4
         │ │ + QA (Phase 2)            │ │  ← Phase 2
         │ │ + Build Engineer (v4)     │ │  ← Phase 4.5
         │ │ + Dep Analyzer (v4)       │ │  ← Phase 4.5
         │ │ + Asset Manager (v4)      │ │  ← Phase 4.5
         │ │ + Installer Creator (v4)  │ │  ← Phase 4.5
         │ │ + Platform Tester (v4)    │ │  ← Phase 4.5
         │ │ + Release Manager (v4)    │ │  ← Phase 5
         │ │ + Changelog Gen (v4)      │ │  ← Phase 5
         │ │ + Update Checker (v4)     │ │  ← Phase 5
         │ │ + Distribution (v4)       │ │  ← Phase 5
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ Gap Analyst (v3)          │ │
         │ └─────────────┬─────────────┘ │
         │               ▼               │
         │ ┌───────────────────────────┐ │
         │ │ Convergence Judge (v3)    │ │
         │ └─────────────┬─────────────┘ │
         └───────────────┼───────────────┘
                         ▼
              dist/<product>-<version>-setup.exe
              + GitHub Releases URL
              + SHA256 + 한국어 CHANGELOG
```

---

## 10. 열린 설계 질문

1. **Cross-platform 우선순위**: Windows-only로 시작 vs macOS/Linux 동시 지원? — 본 문서는 Windows-first 가정. 사용자의 첫 사용 환경이 Windows.
2. **UI 추론의 한계**: "계산기 만들어줘"에서 GUI를 추론하는 건 합리적이지만, "REST API 만들어줘"에선 GUI가 없어야 한다. UI/UX Analyst의 1차 분기는 `gui? yes/no` 가 되어야 하며, no면 Phase 4를 통째로 건너뛴다.
3. **빌드 시간 예산**: Nuitka 빌드는 5~30분 소요. v3의 budget gate에 빌드 시간도 포함해야 함.
4. **인증서 비용**: EV 코드 서명 인증서는 연 $300~$500. 사용자 환경에서 이 비용을 누가 감당할지 사전 합의 필요. 없으면 SmartScreen 경고를 사용자에게 안내.
5. **자동 업데이트의 보안 모델**: Update Checker가 임의 URL에서 코드를 받아 실행하면 공급망 공격 표면이 됨. 서명 검증 + 업데이트 채널 화이트리스트 필수.
6. **`.exe`의 신뢰 문제**: AI가 자동 생성한 .exe를 사용자가 신뢰할 수 있는가? 산출물에 "이 파일은 Nexus Alpha가 자동 생성했습니다 + 코드 GitHub 링크 + 빌드 로그 hash" 라는 출처(provenance) 정보를 항상 동봉.

이 6가지 질문은 v4 Phase 4 착수 시점에 별도 세션에서 사용자와 합의한다.
