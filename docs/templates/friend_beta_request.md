# 📩 친구 베타 요청 메시지 템플릿

> **사용법**: 아래 메시지를 그대로 카톡/Slack/이메일로 친구에게 복붙. 1주일 여유, 부담 없는 톤.
>
> **발송 상태**: ⏳ **(다음 세션 시작 시 사용자에게 발송 여부 확인 필요)**
>
> **첫 번째 친구 (1차 검증, 2026-05-14)**: ✅ Message_App.exe 9.86 MB / 33.11 min 빌드 성공

---

## 친구에게 보낼 메시지 (그대로 복붙)

> Nexus Alpha 1차 검증 도와줘서 고마웠어! Message_App.exe 빌드 성공한 게 첫 외부 PC 입증이었어 🎉
>
> 1주일 정도 여유 있을 때 **다른 종류 GUI 라이브러리** 도 한두 개 시도해줄 수 있을까? 부담 없이 1개만 해도 OK.
>
> ## ⚠️ 시작 전 1단계 — PowerShell 선택모드 끄기 (중요!)
>
> 1차 시도 때 빌드가 멈춘 줄 알고 마우스로 PowerShell 텍스트 선택했지? 그게 사실은 **PowerShell 의 Quick Edit Mode** 라는 기능 때문에 *실제로 프로세스가 일시정지* 되는 거야. 33분 빌드 중에 잘못 클릭하면 멈춰버려.
>
> **사전 조치 (1번만 해두면 됨)**:
> 1. PowerShell 창 열기
> 2. 좌측 상단 **창 제목 바 우클릭 → 속성**
> 3. **옵션** 탭 → **편집 옵션** 섹션 → **빠른 편집 모드** 체크 *해제*
> 4. **확인** → 다시 PowerShell 새로 열기
>
> 이렇게 하면 33분 빌드 중에 마우스로 화면 클릭해도 안 멈춰.
>
> ## 시도 추천 (편한 거 1-2개 골라줘)
>
> 같은 명령으로 시작 (이미 설치됐으면 Step 2 부터):
>
> **Step 1 — 업데이트 (이미 설치된 경우 자동으로 main 동기화)**:
> ```powershell
> irm https://raw.githubusercontent.com/SongJongwon/nexus-alpha/main/install.ps1 | iex
> ```
>
> **Step 2 — 실행**:
> ```powershell
> cd $HOME\nexus-alpha
> .\.venv\Scripts\python.exe scripts\run.py
> ```
>
> **Step 3 — `요청:` 프롬프트에 아래 중 1개 입력**:
>
> | # | 추천 요청 | 사용될 GUI 라이브러리 | 예상 시간 |
> |---|----------|------------------|---------|
> | 1 | `customtkinter 로 다크모드 메모장 만들어줘` | customtkinter (heavy modern UI) | ~30분 |
> | 2 | `Flet 으로 할일 관리 앱 만들어줘` | Flet (Flutter 기반) | ~35분 |
> | 3 | `PyQt 로 이미지 뷰어 만들어줘 - 폴더 열기 + 이전/다음` | PyQt5 / PySide6 | ~40분 |
> | 4 | `dearpygui 로 그래프 그리는 앱 만들어줘` | dearpygui (게임엔진 스타일) | ~30분 |
>
> **Step 4 — Track 선택**: Enter (자동 라우팅)
> **Step 5 — 빌드 [y/N]**: `y`
> **Step 6 — 약 30-40분 대기** (빌드 중 PowerShell 화면 클릭 X — Quick Edit 끄긴 했지만 안전)
>
> ## 결과 보고 양식
>
> ### ✅ 성공한 경우
> 1. PowerShell 마지막 화면 캡처 (`결과 — Track A` 박스 보이게)
> 2. `.exe` 더블클릭 → GUI 창 캡처
> 3. 한 줄 정보:
>    - OS: Windows 10 또는 11
>    - 회사 PC / 개인 PC
>    - 빌드 시간: XX 분
>    - .exe 이름 + 크기
>
> ### ❌ 실패한 경우 (PR #134-A 진단 자동 발동)
>
> 화면에 이런 박스가 뜨면 그 박스 **통째로** 캡처해줘:
> ```
> ═══ tkinter 진단 dump (PR #134-A) ═══
> [1] tkinter import 시도 결과: ...
> ...
> [12] 자동 분류 에러 ID: TKINTER-XXX
> [13] JSON 구조화 dump
> ═══════════════════════════════════════
> ```
> 13 섹션 통째로 캡처가 핵심 — 이게 다른 PC 환경에서 어떤 결함 패턴이 나오는지 학습하는 데이터야.
>
> ### ⚠️ 이상한 경우 (빌드는 됐는데 실행 시 문제)
> - GUI 창 깜빡이고 사라짐 → PowerShell 마지막 50줄 + 캡처
> - GUI 떴는데 입력 안 먹음 / 표시 이상 → 화면 + 한 줄 설명
>
> ## 보너스 (가능하면)
>
> 주변에 회사 PC 또는 개인 PC 있는 사람 1-2명 더 모집해줄 수 있어? 환경 다양할수록 좋음:
> - Windows 10 vs 11
> - 회사 PC (도메인 가입) vs 개인 PC
> - 한국 백신 (V3, AhnLab) vs Windows Defender 만
>
> 1주일 안에 편할 때 알려줘. 급하지 않아!

---

## 사용자 (PM) 메모 — 다음 세션 시 확인할 것

### 친구가 보내줄 데이터별 다음 행동

| 친구 결과 | PM 다음 행동 |
|---------|-----------|
| ✅ 4 라이브러리 모두 성공 | PR #141 (Vision QA + delegation) 즉시 시작 — paradigm-shift 진행 가능 |
| ✅ 일부 성공 + 일부 실패 (TKINTER-XXX 분류) | PR #134-B 환경 분기 처방 시작 (분류된 ID 처방) + PR #141 병렬 |
| ⚠️ Vision QA 가 정말 필요한 이상 케이스 (예: 환율 사례 같은 cross-agent inconsistency) | PR #141 즉시 시작 + 그 케이스를 PR #141 회귀 테스트로 |
| ❌ 모두 실패 + 진단 dump 풍부 | PR #134-B 환경 분기 처방 우선 |
| ❌ 친구 무응답 / 1대 PC 만 결과 | 추가 베타 모집 시도 + Sprint 2 (PR #141) 진행 |

### 친구가 데이터 못 보낼 경우 (1주일 내내 무응답)

- 다음 세션 시작 시 [docs/insights/agent_collaboration_paradigm_shift.md](../insights/agent_collaboration_paradigm_shift.md) 통찰만으로도 PR #141 진행 가능
- 환율 사례가 이미 명확한 증거 → cross-agent inconsistency 검출 시나리오 충분
