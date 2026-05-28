# Phase 6 — Tech Scout 라이브 검증 가이드

> **목적**: Phase 6.1 (PyPI 인프라) + 6.2 (도메인 체크리스트) + 6.3 (workflow 통합) 의 *통합 동작* 을 1 cycle 실 라이브 실행으로 검증.
>
> **실행 위치**: PM 본인 PC.
> **예상 소요**: 20~35분 (max_iterations 3 × ~7-10분/iter, 가짜 패키지 시뮬레이션 시 IMPROVE 라운드 1~2회).
> **예상 비용**: ~$3-10 (Opus 4.7, Tech Scout 자체는 비용 0).
>
> **참조**: [phase6_proposal.md](architecture/phase6_proposal.md) (PM 확정 7건 의사결정).

---

## 0. 사전 체크리스트

| 항목 | 확인 명령 |
|------|----------|
| `requests>=2.31.0` 설치 | `.venv\Scripts\python.exe -c "import requests; print(requests.__version__)"` |
| Tech Scout 모듈 import | `.venv\Scripts\python.exe -c "from src.agents.research import scout_and_validate"` |
| Claude Code CLI 인증 | `claude auth status` (loggedIn=true) |
| Tech Scout 직접 호출 검증 | `.venv\Scripts\python.exe -c "from src.agents.research import scout_and_validate; r = scout_and_validate('3D 시각화 Python'); print(f'valid={r.valid_count}/{len(r.candidates)}')"` |

기대 출력 (마지막):
```
valid=5/5
```

---

## 1. 추천 `--request` 문구

### 옵션 A (추천) — BIM 환각 패키지 시나리오

```
3D BIM 건축 모델 뷰어: Three.js + BIM 라이브러리 사용. 캐드 모델 import, 카메라 Orbit 회전, 줌/팬 인터랙티브 컨트롤. PyInstaller .exe.
```

**왜 BIM 환각 가능성 높은가**:
- *3D 도메인* — Phase 6.2 Rule 0 활성 (4 항목 체크리스트)
- *BIM 키워드* — Engineer LLM 이 `bim_repository` 같은 *환각 패키지* 산출 가능성 ↑
- *Tech Scout 발동 조건 충족* — Engineer 가 requirements.txt 산출 시 PyPI 검증

### 옵션 B — 단순 3D 시각화 (정상 라이브러리만 산출 시나리오)

```
3D 데이터 시각화 GUI: numpy 데이터를 3D scatter plot 으로 렌더. 카메라 Orbit 회전 + 줌. matplotlib + mplot3d 사용.
```

→ Engineer 가 matplotlib 사용 시 *가짜 없음* → Tech Scout 통과 → Phase 6.2 체크리스트만 검증.

---

## 2. 실행 명령어

### PowerShell

```powershell
.venv\Scripts\python.exe scripts\run.py `
  --request "3D BIM 건축 모델 뷰어: Three.js + BIM 라이브러리 사용. 캐드 모델 import, 카메라 Orbit 회전, 줌/팬 인터랙티브 컨트롤. PyInstaller .exe." `
  --track A --build `
  --enable-tech-scout `
  --auto-iterate --max-iterations 3 `
  --emit-events outputs\events.jsonl `
  --non-interactive
```

### Bash

```bash
.venv/Scripts/python.exe scripts/run.py \
  --request "3D BIM 건축 모델 뷰어: ..." \
  --track A --build \
  --enable-tech-scout \
  --auto-iterate --max-iterations 3 \
  --emit-events outputs/events.jsonl \
  --non-interactive
```

### 핵심 flag

| Flag | 효과 |
|------|------|
| `--enable-tech-scout` ⭐ | **본 PR #230 NEW** — Tech Scout 노드 진입 + Rule -1 활성 |
| `--auto-iterate` | iterative_loop production 모드 |
| `--max-iterations 3` | 1 cycle = 3 iter — 1차 IMPROVE → 2차 IMPROVE or 통과 → 3차 |
| `--build` | PyInstaller .exe 산출 (Engineer 의 requirements.txt 검증 대상) |
| `--emit-events` | telemetry 파일 출력 (`tech_scout` 이벤트 포함) |

### Phase 5.4 + 6.3 결합 (풀체인)

```powershell
.venv\Scripts\python.exe scripts\run.py `
  --request "3D BIM 건축 모델 뷰어: ..." `
  --track A --build `
  --enable-rv --enable-strategist --enable-boardroom --enable-tikitaka `
  --enable-tech-scout `
  --auto-iterate --max-iterations 5 `
  --emit-events outputs\events.jsonl `
  --non-interactive
```

→ 자율 진화 루프 (Phase 1~5.4) + Tech Scout 가짜 가드 동시 활성.

---

## 3. 실행 후 확인 — 산출 파일 + grep 명령어

### 3.1 ⭐ Tech Scout 텔레메트리 (라운드별 검증 evidence)

```powershell
Get-Content outputs\events.jsonl |
  Select-String "tech_scout" |
  Select-Object -First 20
```

**기대 출력**: `agent_status` 이벤트 (`working` + `done`) 가 iter 마다 emit. dept="learning".

### 3.2 ⭐ 가짜 패키지 감지 시 IMPROVE 루프 evidence

```powershell
Get-Content outputs\events.jsonl |
  Select-String 'fake|FAKE_PACKAGE|IMPROVE_NEEDED' |
  Select-Object -First 20
```

**기대 출력**: 가짜 패키지 발견 시 *judge_convergence* 의 reason 에 `Fake packages detected (1st occurrence)` 또는 `2 consecutive`.

### 3.3 PyPI 캐시 디렉터리

```powershell
Get-ChildItem outputs\_pypi_cache\*.json |
  Select-Object Name, Length, LastWriteTime |
  Format-Table
```

**기대 출력**: 검증된 각 패키지의 JSON 캐시 파일. 7d 이내면 다음 run 에서 network skip.

### 3.4 Engineer requirements.txt (검증 대상)

```powershell
Get-ChildItem outputs\alpha_run_*\workflow\requirements.txt |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  Get-Content
```

### 3.5 최종 verdict + 가짜 패키지 정보

```powershell
Get-Content outputs\events.jsonl |
  Select-String '"type":"result"' |
  Select-Object -Last 1
```

**기대 schema**:
- `verdict`: `COMPLETE` (가짜 없음) / `IMPROVE_NEEDED` (1차 가짜) / `BLOCKED` (2차 가짜)
- `blocked_cause`: `FAKE_PACKAGE` (2차 발동 시)

---

## 4. 실패 시나리오 + 디버깅 가이드

| 시나리오 | 증상 | 진단 / 처방 |
|----------|------|------------|
| Tech Scout 노드 미진입 | `events.jsonl` 에 `tech_scout` 이벤트 0 | `--enable-tech-scout` flag 누락 |
| requirements.txt 미생성 | Engineer 가 `--build` 없이 종료 | `--build` flag 추가 |
| 모든 패키지 5xx (skipped_count > 0) | PyPI 일시 장애 | stale cache 사용됨 — `outputs/_pypi_cache/` 확인 |
| 1차 IMPROVE 후 Engineer 가 같은 가짜 반복 | LLM 의 환각 강도 ↑ | 2iter 후 BLOCKED(FAKE_PACKAGE) — 정상 동작 |
| `bim_repository` 같은 가짜가 *real* 감지됨 | PyPI 에 *우연히* 동명 패키지 존재 | `outputs/_pypi_cache/bim_repository.json` 의 latest_version 확인 — squat 패키지일 수도 |
| 캐시 폭증 | `outputs/_pypi_cache/` 가 MB 단위 | 정상 — 7d TTL 자동 invalidate. 수동 clean: `Remove-Item outputs/_pypi_cache/*.json` |

---

## 5. 성공 판정 — Phase 6.E Definition of Done

✅ **Tech Scout 1 cycle 완주** 시 다음 5 통과:

1. `outputs/events.jsonl` 에 `tech_scout` 이벤트 ≥ 1건 (working + done)
2. `outputs/_pypi_cache/*.json` ≥ 1 파일 생성 (PyPI 검증 evidence)
3. Engineer 의 `requirements.txt` 파일이 *모든 실존 패키지* 로 산출 (`exists=True` 만)
4. `result` 이벤트의 `verdict` ∈ {COMPLETE, IMPROVE_NEEDED, BLOCKED}
5. BLOCKED 시 `blocked_cause=FAKE_PACKAGE` (절충안 2차 발동 evidence)

→ 5/5 통과 시 **v13 Phase 6 전체 완성** (6.1 + 6.2 + 6.3 통합 evidence) → 베타 cohort 5명 배포 준비.

---

## 6. PM 본인 PC 검증 후 다음 sprint

| 결과 | 다음 작업 |
|------|----------|
| 5/5 PASS + 가짜 감지 evidence | Phase 6 전체 완료 → 베타 cohort 5명 배포 → 실 사용자 BIM 사례 수집 |
| 5/5 PASS + 가짜 미감지 | 정상 동작. 가짜 시뮬레이션을 위해 의도적 환각 유발 prompt 작성 후 재시도 |
| 부분 FAIL | 디버깅 sprint — Tech Scout 노드 진입 확인 + requirements.txt 파일 위치 확인 |
| Tech Scout 활성 시 cycle 시간 ↑↑ | PyPI 호출 시간 분석 — 캐시 hit rate 검증 + `MAX_SEARCHES_PER_QUERY` 조정 |

---

**관련 PR**: #226 (Phase 6.2 Judge Rule 0) · #229 (Phase 6.1 PyPI 인프라) · **#230 (Phase 6.3 workflow 통합 + 본 가이드)**

**최종 검증 시점**: 2026-05-28 (PM 본인 PC 실행 예정).
