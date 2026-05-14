# 🔐 BFG 절차 — git history 의 leaked secret 정리

> **PR #137 와 별도 단계**. 본 문서는 *절차만* 명시하며, 실 BFG 실행 + force-push
> 는 사용자 명시 컨펌 후 별도 세션에서 진행.

## 🎯 대상 leak (2026-05-14 종합 점검 식별)

| 노출 값 | 분류 | 위험 등급 |
|--------|------|---------|
| `pk-lf-09fedad5-dcbf-4b8e-8f5d-f741922da92b` | LangFuse public key (read-only 식별자) | LOW |
| `jwsong@ymx.co.kr` | maintainer 이메일 | LOW (이미 PR 메시지 등에서 공개) |
| `머지봇_송종원` | git user.name | LOW (의도된 공개) |

**잔존 commit**: `354ccfb` / `2287c63` / `1b6ef19` / `b89719a`
**노출 파일**: `docs/context/next_session_context.md` (단 1 파일, history 한정)
**main 현재 상태**: PR #103 (`e02a43f`, 2026-05-11) 에서 placeholder 로 정리됨

→ **즉시 revoke 까지는 불필요** (public key 라 write 권한 X). 정책 정합성 + 재발 방지를 위한 사전 조치.

## ⚠️ 사전 영향 평가

| 영향 대상 | 영향 | 조치 |
|---------|------|------|
| Maintainer (본인 PC) | history 갱신 필요 | `git fetch + git reset --hard origin/main` 한 줄 |
| 베타 테스터 (친구 PC) | install.ps1 의 `git fetch + reset --hard` (PR #107) 가 *자동* 처리 | 친구가 다음 install.ps1 실행만 하면 OK — 별도 알림 불필요 |
| 활성 PR | 현재 0 (PR #134-A / #135 모두 머지됨) | rebase 필요 0 |
| Archive 브랜치 | 50+ 개 (feat/ / fix/ / phase*/) | history-only, 재push X — 영향 0 |
| 외부 fork | `gh api repos/SongJongwon/nexus-alpha/forks` 결과 0 가정 (확인 필요) | force-push 전 확인 — fork 0 이면 충돌 0 |

## 📋 절차 (실 실행 시)

### Step 0 — 사전 (사용자, ~2분)

1. **LangFuse 콘솔** (https://cloud.langfuse.com) 접속
2. 해당 프로젝트의 **Settings → API Keys** 진입
3. 옛 public key (`pk-lf-09fedad5-...`) **rotate** 버튼 클릭 → 새 key 발급
4. 본인 PC `.env` 의 `LANGFUSE_PUBLIC_KEY` 새 값으로 업데이트
5. 옛 key revoke (선택 — read-only 라 둬도 무방하나 정합성)

### Step 1 — BFG 다운로드 (Claude / 사용자, ~30초)

```powershell
# Java 11+ 필요 — winget 으로 OpenJDK 설치 (이미 설치됐으면 skip)
winget install --id Microsoft.OpenJDK.21 --silent

# BFG jar 다운로드 (~16 MB)
$BfgVersion = '1.14.0'
$BfgJar = "$env:TEMP\bfg-$BfgVersion.jar"
Invoke-WebRequest `
    -Uri "https://repo1.maven.org/maven2/com/madgag/bfg/$BfgVersion/bfg-$BfgVersion.jar" `
    -OutFile $BfgJar
```

### Step 2 — Mirror clone (Claude, ~10초)

```powershell
$WorkDir = "$env:TEMP\nexus-alpha-bfg"
Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue
git clone --mirror https://github.com/SongJongwon/nexus-alpha.git $WorkDir
Set-Location $WorkDir
```

### Step 3 — replace-text 파일 작성 (Claude, ~5초)

```powershell
$ReplaceFile = "$env:TEMP\bfg-replacements.txt"
@'
pk-lf-09fedad5-dcbf-4b8e-8f5d-f741922da92b==>***REMOVED***
'@ | Set-Content -Path $ReplaceFile -Encoding UTF8
```

> **이메일 / 이름은 의도된 공개**라 BFG 대상 X. 정말 정리하려면 `==>` 패턴 추가.

### Step 4 — BFG 실행 (Claude, ~30초)

```powershell
java -jar $BfgJar --replace-text $ReplaceFile $WorkDir

# 후속 GC + reflog 정리 (BFG 가 안내)
Set-Location $WorkDir
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### Step 5 — Force-push (사용자 명시 컨펌 후, ~10초)

```powershell
# ⚠️ DESTRUCTIVE — 사용자 명시 컨펌 후만 실행
# main 외에 force-push 하면 안 되는 브랜치 확인 후
git push --force --mirror origin
```

> **위험 신호**: force-push 후 GitHub UI 의 commit hash 가 변경됨. 외부 fork / 미머지 PR 이 broken 상태가 될 수 있음 — Step 0 에서 확인 필수.

### Step 6 — Maintainer PC 동기화 (사용자, ~30초)

```powershell
Set-Location C:\projects\nexus-alpha
git fetch origin
git reset --hard origin/main

# 다른 active 브랜치가 있다면:
# git checkout <other-branch>
# git rebase origin/main  # 또는 reset --hard 후 재push
```

### Step 7 — 검증 (Claude, ~1분)

```powershell
# 옛 key 가 진짜 history 에서 사라졌는지 확인 — 결과는 *empty* 여야 함
git log --all -S "pk-lf-09fedad5"

# gitleaks workflow 가 main push 후 통과하는지 GitHub Actions 에서 확인
gh run list --workflow=gitleaks.yml --limit 3

# 친구 PC: install.ps1 다음 실행 시 자동 동기화 (PR #107 destructive sync)
```

## 🛡️ 사후 — 재발 방지 (PR #137 자동화로 보장)

- **gitleaks workflow** (push / PR / weekly cron) 가 새 leak 즉시 차단
- **CodeQL workflow** 가 hardcoded credentials 정적 검출
- **dependabot** 가 vulnerable dep 자동 PR

## 📊 BFG 실행 권장 시점

| 시점 옵션 | 장단점 |
|---------|------|
| **Sprint 1 끝** (이번 주) | 자동화 + history 동시 정리. 깔끔. |
| **친구 베타 1주일 후** | 친구가 install.ps1 한 번 더 돌려도 안전 — 부담 0 |
| **PR #134-B 진행 시** | 환경 분기 처방 PR 와 묶음 — 한 번에 |
| **무기한 보류** | LOW risk 라 history 그대로 둬도 큰 위험 없음. gitleaks 가 새 leak 만 차단 |

→ PM 결정 권장 사항.
