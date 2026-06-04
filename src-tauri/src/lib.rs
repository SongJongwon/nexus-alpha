//! Nexus Alpha Tauri shell — Agent Office Visualizer.
//!
//! Sprint 5 + Claude Code CLI 인증 통합. 본 file 의 commands:
//!   * claude_auth_status — `claude auth status --json` 호출 + JSON parse
//!   * claude_auth_login  — `claude auth login` (브라우저 OAuth 인터랙티브)
//!   * claude_auth_logout — `claude auth logout`
//!   * start_run          — Python sidecar spawn (P18: 빌드 타깃 web/desktop/none +
//!                          max-iterations + tech-scout/auto-iterate 플래그 매핑,
//!                          build_run_args 참조; claude.exe PATH 주입)
//!
//! ## Windows PATH 결함 처방 (2026-05-26)
//! Windows 의 `where claude` 가 3 후보 반환 — `claude.exe` (native),
//! 확장자 없는 npm script, `claude.cmd` (npm Windows wrapper). Rust 의
//! `Command::new("claude")` 가 PATHEXT 처리 차이로 잘못된 후보 spawn 하거나
//! GUI subsystem 에서 못 찾을 수 있음. 본 file 의 `find_claude_executable()`
//! 가 PATH 를 직접 순회하여 *`.exe` 우선* 절대 경로 결정 → spawn.

use std::{
    fs::OpenOptions,
    io::{BufRead, BufReader, Seek, SeekFrom},
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::Duration,
};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

/// Smoke test command — 살아있음 응답 (PR-A 부터 유지).
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {name}! Nexus Alpha Tauri shell is alive.")
}

// ---------------------------------------------------------------------------
// Claude CLI executable resolution
// ---------------------------------------------------------------------------

/// PATH 환경변수를 순회하여 claude CLI 의 *절대 경로* 결정.
/// Windows 에서는 `.exe` → `.cmd` → `.bat` → 확장자 없음 순서 우선.
/// Unix 에서는 `claude` 만 검색.
///
/// PM PC 진단 결과 (`where.exe claude`):
///   C:\Users\woker\.local\bin\claude.exe        ← 본 함수가 첫 매치로 잡음
///   C:\Users\woker\AppData\Roaming\npm\claude   ← 확장자 없음 (Windows native 못 spawn)
///   C:\Users\woker\AppData\Roaming\npm\claude.cmd
fn find_claude_executable() -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    let candidates: &[&str] = if cfg!(windows) {
        &["claude.exe", "claude.cmd", "claude.bat", "claude"]
    } else {
        &["claude"]
    };
    for dir in std::env::split_paths(&path_var) {
        for candidate in candidates {
            let candidate_path = dir.join(candidate);
            if candidate_path.is_file() {
                return Some(candidate_path);
            }
        }
    }
    None
}

/// `claude` subcommand 를 실행하기 위한 `Command` 빌더.
/// CLI 미발견 시 사용자에게 보여줄 명확한 에러 반환.
fn build_claude_command() -> Result<Command, String> {
    let path = find_claude_executable().ok_or_else(|| {
        "claude CLI 미발견 — PATH 에 claude.exe 가 없습니다. \
         https://claude.com 에서 Claude Code 설치 후 재시도해주세요."
            .to_string()
    })?;
    Ok(Command::new(path))
}

// ---------------------------------------------------------------------------
// Claude Code CLI 인증
// ---------------------------------------------------------------------------

/// `claude auth status --json` 의 응답 schema. `loggedIn` / `email` /
/// `subscriptionType` 핵심 + 디버깅용 보조 필드.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AuthStatus {
    #[serde(rename = "loggedIn", default)]
    pub logged_in: bool,
    #[serde(default)]
    pub email: Option<String>,
    #[serde(rename = "subscriptionType", default)]
    pub subscription_type: Option<String>,
    #[serde(rename = "authMethod", default)]
    pub auth_method: Option<String>,
    #[serde(rename = "orgName", default)]
    pub org_name: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

/// Claude Code CLI 인증 상태 조회.
#[tauri::command]
async fn claude_auth_status() -> Result<AuthStatus, String> {
    let mut cmd = match build_claude_command() {
        Ok(c) => c,
        Err(e) => {
            return Ok(AuthStatus {
                logged_in: false,
                error: Some(e),
                ..Default::default()
            });
        }
    };
    cmd.arg("auth").arg("status").arg("--json");

    let output = match cmd.output() {
        Ok(o) => o,
        Err(e) => {
            return Ok(AuthStatus {
                logged_in: false,
                error: Some(format!("claude CLI 실행 실패: {e}")),
                ..Default::default()
            });
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    if let Ok(parsed) = serde_json::from_str::<AuthStatus>(stdout.trim()) {
        return Ok(parsed);
    }

    Ok(AuthStatus {
        logged_in: false,
        error: Some(format!(
            "auth status JSON parse 실패. stdout={} stderr={}",
            stdout.trim(),
            stderr.trim()
        )),
        ..Default::default()
    })
}

/// `claude auth login` 실행 후 status 재조회 (인터랙티브 브라우저 OAuth).
#[tauri::command]
async fn claude_auth_login() -> Result<AuthStatus, String> {
    let mut cmd = build_claude_command()?;
    cmd.arg("auth").arg("login");

    let status = cmd
        .status()
        .map_err(|e| format!("claude auth login 실행 실패: {e}"))?;

    if !status.success() {
        return Err(format!(
            "claude auth login 종료 코드 {:?} — OAuth 흐름 미완료 또는 사용자 취소",
            status.code()
        ));
    }
    claude_auth_status().await
}

/// vite preview 기본 포트 (P19) — vite 기본값이자 사용자 검증 포트. 점유 시 동적 포트로 대체.
const DEFAULT_PREVIEW_PORT: u16 = 4173;

/// preview 서버에 쓸 포트 선택 (P19). 4173(vite 기본·사용자 검증)이 비어있으면 그대로,
/// 점유 시 OS 가 빈 포트를 배정(:0 bind). 선택 포트를 vite `--port <p> --strictPort` 로 고정 +
/// 동일 포트를 브라우저 URL 로 사용 → 4173 하드코딩의 silent fallback(점유 시 vite 는 4174 로
/// 가는데 브라우저는 stale 4173 을 열던 회귀) 제거. 재실행/더블클릭도 각자 올바른 포트로 동작.
fn pick_preview_port() -> u16 {
    if TcpListener::bind(("127.0.0.1", DEFAULT_PREVIEW_PORT)).is_ok() {
        return DEFAULT_PREVIEW_PORT;
    }
    TcpListener::bind("127.0.0.1:0")
        .ok()
        .and_then(|l| l.local_addr().ok())
        .map(|a| a.port())
        .unwrap_or(DEFAULT_PREVIEW_PORT)
}

/// 산출물이 web(.html) 인지 — desktop(.exe) 와 분기 (P19).
/// run.py 의 `_is_web_vision_target`(P17) 와 동일 신호(.html/.htm suffix)를 Rust 측에서 재현.
fn is_web_artifact(path: &Path) -> bool {
    matches!(
        path.extension()
            .and_then(|e| e.to_str())
            .map(|s| s.to_ascii_lowercase())
            .as_deref(),
        Some("html") | Some("htm")
    )
}

// v13 P22 — 런 중 개입 체크포인트의 GUI 분기·'빌드 열어보기' 계약을 Rust 순수 함수로 박제.
// 프론트(App.tsx)에 JS 단위 테스트 하네스가 없어, 분기/활성 조건을 여기서 정의·cargo 로 검증한다.
// 실제 빌드 열기는 기존 `open_exe`(web→open_web_preview / desktop→.exe spawn) 를 *재사용*한다.

/// 체크포인트 패널 분기: iteration>=2 면 '직전 빌드 검토' 패널, 아니면 P20 '계획' 패널.
#[allow(dead_code)]
fn checkpoint_is_build_review(iteration: i64) -> bool {
    iteration >= 2
}

/// '빌드 열어보기' 버튼 활성 여부 — 직전 빌드 경로가 있고 공백이 아닐 때만(없으면 비활성+안내).
#[allow(dead_code)]
fn open_build_enabled(prev_build_path: Option<&str>) -> bool {
    matches!(prev_build_path, Some(p) if !p.trim().is_empty())
}

/// dist/index.html → web 프로젝트 루트(code_dir = package.json/node_modules/vite.config 위치).
/// `_run_web_build`(P17) 가 code_dir/dist/index.html 을 exe_path 로 surface 하므로
/// index_html 의 조부모 디렉터리가 프로젝트 루트.
fn web_project_dir(index_html: &Path) -> Option<PathBuf> {
    index_html
        .parent() // .../dist
        .and_then(|dist| dist.parent()) // .../code (project root)
        .map(|d| d.to_path_buf())
}

/// 로컬 vite 바이너리 경로 (node_modules/.bin/vite[.cmd]) — 빌드 시 npm install 로 생성.
/// npm script(package.json 의 preview) 의존을 피하고 vite 를 직접 호출 (LLM 산출 변동 무관).
fn local_vite_bin(project_dir: &Path) -> PathBuf {
    let bin = project_dir.join("node_modules").join(".bin");
    if cfg!(windows) {
        bin.join("vite.cmd")
    } else {
        bin.join("vite")
    }
}

/// vite preview spawn 인자 — (program, args). Windows 는 `cmd /C` 로 .cmd shim 해소.
/// `--strictPort` 로 주어진 포트 점유 시 *폴백 대신 즉시 실패* → 브라우저가 여는 포트와
/// vite 가 바인딩한 포트가 항상 일치(stale 4173 silent 오작동 차단). 순수 함수라 단위 테스트.
fn vite_preview_invocation(vite_bin: &Path, port: u16) -> (String, Vec<String>) {
    let bin = vite_bin.to_string_lossy().into_owned();
    let p = port.to_string();
    if cfg!(windows) {
        (
            "cmd".into(),
            vec![
                "/C".into(),
                bin,
                "preview".into(),
                "--port".into(),
                p,
                "--strictPort".into(),
            ],
        )
    } else {
        (bin, vec!["preview".into(), "--port".into(), p, "--strictPort".into()])
    }
}

/// 기본 브라우저로 URL 열기 (detached). Windows `cmd /C start`, 기타 `xdg-open`.
fn open_in_browser(url: &str) -> Result<(), String> {
    let mut cmd = if cfg!(windows) {
        let mut c = Command::new("cmd");
        // start 의 첫 인자 "" 는 창 제목 placeholder (URL 이 제목으로 먹히지 않도록).
        c.args(["/C", "start", "", url]);
        c
    } else {
        let mut c = Command::new("xdg-open");
        c.arg(url);
        c
    };
    cmd.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null());
    cmd.spawn()
        .map_err(|e| format!("브라우저 열기 실패: {e}"))?;
    Ok(())
}

/// web 산출물(dist/index.html) 을 vite preview 로 서빙 + 기본 브라우저로 열기 (P19).
/// vite preview 는 SPA fallback(history 라우팅) 기본 지원. 서버 바인딩 대기 후 브라우저 오픈.
fn open_web_preview(index_html: &Path) -> Result<(), String> {
    let project_dir = web_project_dir(index_html)
        .ok_or_else(|| "web 프로젝트 루트 결정 실패 (dist/index.html 구조 아님)".to_string())?;
    let vite_bin = local_vite_bin(&project_dir);
    if !vite_bin.exists() {
        return Err(format!(
            "vite 미설치 ({}) — web 빌드(npm install)가 선행돼야 preview 가능합니다.",
            vite_bin.display()
        ));
    }
    // 빈 포트 선택(4173 우선) → vite 와 브라우저가 동일 포트 사용 보장.
    let port = pick_preview_port();
    let (program, args) = vite_preview_invocation(&vite_bin, port);
    let mut cmd = Command::new(&program);
    cmd.args(&args)
        .current_dir(&project_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .stdin(Stdio::null());
    cmd.spawn()
        .map_err(|e| format!("vite preview 실행 실패: {e}"))?;

    // vite preview 가 포트 바인딩할 시간(~1.5s) 후 *선택한 포트* 로 브라우저 오픈 — 명령은 즉시 반환.
    let url = format!("http://localhost:{port}");
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(1500));
        let _ = open_in_browser(&url);
    });
    Ok(())
}

/// 빌드 산출물을 실행/열기 (frontend 의 "▶ 실행" 버튼) — P19: 타깃 인지형.
///
/// 2026-05-26 추가 — Sprint 6 의 *자동 빌드* 흐름의 마지막 layer. ResultEvent.exe_path
/// 가 채워진 run 종료 후, frontend 가 본 command 를 invoke 해 산출물을 즉시 연다.
///
/// P19 — web 산출물(dist/index.html)을 *무조건 .exe 로 spawn* 하던 결함(os error 193) 수정.
///   * web(.html) → vite preview 로 dist 서빙 + 기본 브라우저로 열기.
///   * desktop(.exe) → 기존 detached spawn 그대로 (불변).
///
/// Detached spawn — Tauri shell 의 stdin/stdout 을 inherit 하지 *않음*. spawn 후
/// child handle drop — 부모가 종료해도 child 는 계속 실행.
#[tauri::command]
async fn open_exe(path: String) -> Result<(), String> {
    let artifact = std::path::PathBuf::from(&path);
    if !artifact.exists() {
        return Err(format!("산출물 미발견: {path}"));
    }

    // P19 — web 타깃은 vite preview + 브라우저. (.exe Win32 spawn 금지 — os error 193 차단.)
    if is_web_artifact(&artifact) {
        return open_web_preview(&artifact);
    }

    // desktop(.exe) — 기존 경로 불변.
    if !artifact.is_file() {
        return Err(format!("파일 아님 (디렉터리?): {path}"));
    }
    let mut cmd = Command::new(&artifact);
    if let Some(parent) = artifact.parent() {
        cmd.current_dir(parent);
    }
    cmd.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null());
    cmd.spawn()
        .map_err(|e| format!(".exe 실행 실패 ({path}): {e}"))?;
    Ok(())
}

/// v13 P20 — intervention_in.json payload(JSON) 구성 (순수 함수, 단위 테스트 대상).
fn intervention_payload_json(feedback: &str, action: &str) -> String {
    serde_json::json!({ "feedback": feedback, "action": action }).to_string()
}

/// v13 P20 — 개입 피드백을 intervention_in.json 에 *원자적* 기록 (frontend 개입 패널 → 하네스 폴링).
///
/// frontend(웹뷰)는 파일을 직접 쓸 수 없으므로 본 command 경유. 같은 디렉터리 temp 파일에
/// 쓴 뒤 rename → 하네스(`_intervention._poll_intervention_file`)가 *부분 JSON* 을 읽는 레이스
/// 방지. `action`: "inject"(feedback 반영) | "continue"(그냥 계속). checkpoint 이벤트의
/// `intervention_file` 절대경로를 그대로 path 로 받는다.
#[tauri::command]
async fn write_intervention_file(
    path: String,
    feedback: String,
    action: String,
) -> Result<(), String> {
    let target = std::path::PathBuf::from(&path);
    let json = intervention_payload_json(&feedback, &action);
    // 같은 디렉터리 temp(.tmp) → rename (원자적, 동일 파일시스템).
    let tmp = target.with_extension("tmp");
    std::fs::write(&tmp, json.as_bytes())
        .map_err(|e| format!("intervention temp 기록 실패 ({}): {e}", tmp.display()))?;
    std::fs::rename(&tmp, &target)
        .map_err(|e| format!("intervention rename 실패 ({}): {e}", target.display()))?;
    Ok(())
}

/// `claude auth logout` 실행. 성공 시 token 삭제.
#[tauri::command]
async fn claude_auth_logout() -> Result<(), String> {
    let mut cmd = build_claude_command()?;
    cmd.arg("auth").arg("logout");

    let status = cmd
        .status()
        .map_err(|e| format!("claude auth logout 실행 실패: {e}"))?;

    if !status.success() {
        return Err(format!("claude auth logout 종료 코드 {:?}", status.code()));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Python sidecar spawn + jsonl tail
// ---------------------------------------------------------------------------

/// scripts/run.py 호출 인자 벡터 구성 (P18 — UI 컨트롤 → run.py 플래그 매핑).
///
/// **순수 함수** — 부수효과 없이 인자만 산출하므로 단위 테스트로 매핑을 검증한다.
/// 하네스(Python) 로직은 일절 건드리지 않고 *기존 run.py 플래그* 만 조합한다.
///
/// 매핑 (PowerShell `run.py` 와 동등):
///   * `build_target`:
///       - `"web"`     → `--build` + **`--force-cli` 미부착** (Track A GUI/web 분기
///                       활성 → web SPA 요청이 vite 빌드 → dist/index.html). ★앱이
///                       못 하던 web 빌드 갭 해소.
///       - `"desktop"` → `--build` + `--force-cli` (기존 PyInstaller 경로 *그대로* — 회귀 0).
///       - 그 외(`"none"`) → 빌드 없음 + `--force-cli` (기존 비-빌드 동작 보존).
///   * `--max-iterations N` (auto-iterate 시 최대 iteration).
///   * `--enable-tech-scout` (toggle ON 일 때만).
///   * `--auto-iterate` / `--no-auto-iterate` (toggle).
///   * 공통: `--request` / `--track` / `--emit-events` / `--non-interactive`.
fn build_run_args(
    run_script: &Path,
    request: &str,
    track: &str,
    build_target: &str,
    max_iterations: u32,
    enable_tech_scout: bool,
    auto_iterate: bool,
    intervene: bool,
    events_path: &Path,
) -> Vec<String> {
    let mut args: Vec<String> = vec![
        run_script.to_string_lossy().into_owned(),
        "--request".into(),
        request.to_string(),
        "--track".into(),
        track.to_string(),
        "--emit-events".into(),
        events_path.to_string_lossy().into_owned(),
        "--max-iterations".into(),
        max_iterations.to_string(),
        "--non-interactive".into(),
    ];
    // web 만 GUI/web 분기 활성 (force-cli 제거). desktop/none 은 기존대로 --force-cli.
    if build_target != "web" {
        args.push("--force-cli".into());
    }
    // web/desktop → --build (run.py/_is_web_project 가 web vs PyInstaller 결정). none → 빌드 없음.
    if build_target == "web" || build_target == "desktop" {
        args.push("--build".into());
    }
    if enable_tech_scout {
        args.push("--enable-tech-scout".into());
    }
    if auto_iterate {
        args.push("--auto-iterate".into());
    } else {
        args.push("--no-auto-iterate".into());
    }
    // v13 P20 — 런 중 사람 개입 체크포인트 (opt-in). 앱은 --emit-events 도 보내므로 하네스가
    // 파일(intervention_in.json) 모드로 codegen 직전 1회 멈춘다. OFF 면 미부착(기존 런 동일).
    if intervene {
        args.push("--intervene".into());
    }
    args
}

/// Python sidecar (`scripts/run.py`) spawn + events.jsonl tail thread.
///
/// 본 PR (2026-05-26) 부터 spawn 시점에 *claude.exe 의 디렉터리* 를 자식
/// process 의 PATH 에 prepend + `CLAUDE_CLI_PATH` env var 전달. 향후 백엔드가
/// claude CLI 를 자식 process 로 호출할 때 *Rust 에서 결정한 절대 경로* 를
/// 그대로 사용 가능 (현재 scripts/run.py 는 미사용이지만 일관성).
///
/// P18 — `build` (bool) → `build_target` ("web"/"desktop"/"none") 로 교체 + run 옵션
/// (`enable_tech_scout` / `auto_iterate`) 노출. 플래그 매핑은 `build_run_args` 참조.
/// P20 — `intervene` (런 중 사람 개입 체크포인트 토글) 추가 → `--intervene` 매핑.
#[tauri::command]
async fn start_run(
    app: AppHandle,
    request: String,
    track: String,
    build_target: String,
    max_iterations: u32,
    enable_tech_scout: bool,
    auto_iterate: bool,
    intervene: bool,
) -> Result<String, String> {
    let project_root = resolve_project_root()?;
    let events_path = project_root.join("outputs").join("events.jsonl");

    if let Some(parent) = events_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("outputs 디렉터리 생성 실패: {e}"))?;
    }
    let _ = std::fs::File::create(&events_path)
        .map_err(|e| format!("events.jsonl 초기화 실패: {e}"))?;

    // v13 P20 — 매 런 시작 시 이전 런의 고아 intervention 파일 정리 (housekeeping).
    // 막판 제출/타임아웃 직후 도착으로 남은 intervention_in.json(+.tmp)을 best-effort 삭제 →
    // 새 런을 클린 상태로. (정확성엔 영향 없음 — 하네스도 체크포인트 진입 시 stale 제거.)
    if let Some(out_dir) = events_path.parent() {
        let _ = std::fs::remove_file(out_dir.join("intervention_in.json"));
        let _ = std::fs::remove_file(out_dir.join("intervention_in.tmp"));
    }

    let python = project_root
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    let run_script = project_root.join("scripts").join("run.py");

    if !python.exists() {
        return Err(format!(
            "Python interpreter 미발견: {} — .venv 가 root 에 있는지 확인",
            python.display()
        ));
    }
    if !run_script.exists() {
        return Err(format!(
            "scripts/run.py 미발견: {} — project root 결정 실패 가능",
            run_script.display()
        ));
    }

    // P18 — UI 컨트롤(빌드 타깃 / max-iterations / tech-scout / auto-iterate)을
    // run.py 플래그로 매핑. 순수 함수라 단위 테스트(build_run_args_*)로 검증됨.
    let run_args = build_run_args(
        &run_script,
        &request,
        &track,
        &build_target,
        max_iterations,
        enable_tech_scout,
        auto_iterate,
        intervene,
        &events_path,
    );

    let mut cmd = Command::new(&python);
    cmd.args(&run_args)
        .current_dir(&project_root)
        // 2026-05-26 fix — Stdio::piped() 인데 부모가 read 안 하면 child 의
        // OS write buffer full → Python sidecar 가 BrokenPipeError 로 즉시 사망 →
        // events.jsonl 0 byte. inherit() 로 변경하면 dev 모드는 Tauri shell 의
        // console 로 stream (debugging 가능), release 의 GUI subsystem 은 NULL
        // handle inherit (조용히 무시) — 양쪽 모두 broken pipe 회피.
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    // claude.exe 디렉터리를 자식 process 의 PATH 에 prepend + 절대 경로 env var.
    // PM 요청 2: "run.py 호출 시에도 동일하게 claude.exe 전체 경로를 사용".
    if let Some(claude_path) = find_claude_executable() {
        if let Some(claude_dir) = claude_path.parent() {
            let new_path = if let Ok(existing) = std::env::var("PATH") {
                format!("{};{}", claude_dir.display(), existing)
            } else {
                claude_dir.display().to_string()
            };
            cmd.env("PATH", new_path);
            cmd.env("CLAUDE_CLI_PATH", &claude_path);
        }
    }

    cmd.spawn()
        .map_err(|e| format!("Python sidecar spawn 실패: {e}"))?;

    let app_clone = app.clone();
    let events_path_clone = events_path.clone();
    thread::spawn(move || tail_loop(app_clone, events_path_clone));

    Ok(events_path.to_string_lossy().into_owned())
}

fn resolve_project_root() -> Result<PathBuf, String> {
    let cwd = std::env::current_dir().map_err(|e| e.to_string())?;
    if cwd.ends_with("src-tauri") {
        Ok(cwd
            .parent()
            .ok_or_else(|| "project root 결정 실패".to_string())?
            .to_path_buf())
    } else {
        Ok(cwd)
    }
}

fn tail_loop(app: AppHandle, path: PathBuf) {
    // 2026-05-26 — 시작 즉시 *meta event* emit. frontend 가 본 event 를 받으면
    // listen 권한 + tail thread 모두 정상 evidence (PR #200 capability fix 적용 확인).
    emit_tail_meta(
        &app,
        "tail_started",
        &path,
        &format!("watching path (poll 500ms)"),
    );

    let mut offset: u64 = 0;
    let mut announced_ready = false;
    let mut announced_missing = false;
    let mut missing_round_count: u32 = 0;
    loop {
        thread::sleep(Duration::from_millis(500));
        if !path.exists() {
            missing_round_count = missing_round_count.saturating_add(1);
            // 첫 1초 (2 round) 이후 file 미존재 시 1회만 알림.
            if !announced_missing && missing_round_count >= 2 {
                emit_tail_meta(
                    &app,
                    "tail_file_missing",
                    &path,
                    "events.jsonl 미존재 — Python sidecar 가 실행되지 않았거나 즉시 종료된 가능성",
                );
                announced_missing = true;
            }
            continue;
        }
        if !announced_ready {
            emit_tail_meta(&app, "tail_file_ready", &path, "events.jsonl 발견 — tail 시작");
            announced_ready = true;
        }
        match read_new_lines(&path, offset) {
            Ok((lines, new_offset)) => {
                offset = new_offset;
                for line in lines {
                    let trimmed = line.trim_end();
                    if trimmed.is_empty() {
                        continue;
                    }
                    if let Err(err) = app.emit("nexus://telemetry", trimmed.to_string()) {
                        eprintln!("[Tauri] telemetry emit 실패: {err}");
                    }
                }
            }
            Err(err) => {
                eprintln!("[Tauri] events.jsonl read 실패: {err}");
            }
        }
    }
}

/// `nexus://telemetry` channel 에 진단용 *meta* JSON 한 줄 emit. frontend 는
/// `type=tail_meta` 로 인식. ad-hoc 진단 정보를 *기존 event stream* 으로 흘려보내
/// 별도 channel 추가 없이 stream panel 에 즉시 표시되도록 한다.
fn emit_tail_meta(app: &AppHandle, kind: &str, path: &Path, detail: &str) {
    let payload = serde_json::json!({
        "type": "tail_meta",
        "kind": kind,
        "path": path.to_string_lossy(),
        "detail": detail,
    });
    if let Ok(line) = serde_json::to_string(&payload) {
        let _ = app.emit("nexus://telemetry", line);
    }
}

fn read_new_lines(path: &Path, last_offset: u64) -> std::io::Result<(Vec<String>, u64)> {
    let file = OpenOptions::new().read(true).open(path)?;
    let size = file.metadata()?.len();
    if size <= last_offset {
        return Ok((Vec::new(), last_offset));
    }
    let mut reader = BufReader::new(file);
    reader.seek(SeekFrom::Start(last_offset))?;
    let mut lines = Vec::new();
    let mut buf = String::new();
    loop {
        buf.clear();
        let read = reader.read_line(&mut buf)?;
        if read == 0 {
            break;
        }
        lines.push(buf.clone());
    }
    Ok((lines, size))
}

// ---------------------------------------------------------------------------
// v13 Phase 5.1 (PR #223) — Boardroom panel commands
//
// 의결 로그 YAML (PR #222, Phase 4 산출): outputs/board_decisions/<ts>_<session_id>/decision.yaml
// 회의록 markdown (PR #221, Phase 3 산출): outputs/_boardroom_sessions/<ts>_<session_id>.md
// 두 산출물 양쪽 모두 listing + read 가능해야 frontend Boardroom panel 이 cross-reference.
// ---------------------------------------------------------------------------

/// 회의 세션 / 의결 로그 1건의 list 항목 — frontend list 사이드바 표시용.
#[derive(Debug, Clone, Serialize)]
pub struct BoardroomListItem {
    /// 디렉터리 또는 파일 이름 (예: "20260528_120000_a1b2c3d4e5f6").
    pub name: String,
    /// timestamp ISO8601 (파일/디렉터리 이름의 앞부분 파싱).
    pub timestamp: String,
    /// session_id 12자 hex (이름 뒷부분 파싱).
    pub session_id: String,
    /// 절대 경로 (decision.yaml 또는 .md).
    pub path: String,
}

fn parse_boardroom_name(name: &str) -> Option<(String, String)> {
    // 예: "20260528_120000_a1b2c3d4e5f6"
    // 또는 "20260528_120000_a1b2c3d4e5f6.md"
    let stem = name.strip_suffix(".md").unwrap_or(name);
    let parts: Vec<&str> = stem.splitn(3, '_').collect();
    if parts.len() < 3 {
        return None;
    }
    let date = parts[0];
    let time = parts[1];
    let session_id = parts[2];
    if date.len() != 8 || time.len() != 6 {
        return None;
    }
    let iso = format!(
        "{}-{}-{}T{}:{}:{}Z",
        &date[0..4],
        &date[4..6],
        &date[6..8],
        &time[0..2],
        &time[2..4],
        &time[4..6],
    );
    Some((iso, session_id.to_string()))
}

/// `outputs/board_decisions/*/decision.yaml` list.
///
/// 최근 (timestamp desc) 순으로 최대 50건. PR #222 Phase 4 산출 viewer 용.
#[tauri::command]
async fn list_board_decisions() -> Result<Vec<BoardroomListItem>, String> {
    let project_root = resolve_project_root()?;
    let dir = project_root.join("outputs").join("board_decisions");
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut items = Vec::new();
    let entries = std::fs::read_dir(&dir).map_err(|e| e.to_string())?;
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let yaml_path = path.join("decision.yaml");
        if !yaml_path.is_file() {
            continue;
        }
        let name = match path.file_name().and_then(|s| s.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        if let Some((timestamp, session_id)) = parse_boardroom_name(&name) {
            items.push(BoardroomListItem {
                name,
                timestamp,
                session_id,
                path: yaml_path.to_string_lossy().into_owned(),
            });
        }
    }
    items.sort_by(|a, b| b.timestamp.cmp(&a.timestamp));
    items.truncate(50);
    Ok(items)
}

/// `outputs/board_decisions/<name>/decision.yaml` 의 내용을 *JSON value* 로 변환.
///
/// frontend 가 JSON 으로 받아 즉시 렌더링. serde_yaml → serde_json::Value 변환.
#[tauri::command]
async fn read_board_decision(name: String) -> Result<serde_json::Value, String> {
    let project_root = resolve_project_root()?;
    let yaml_path = project_root
        .join("outputs")
        .join("board_decisions")
        .join(&name)
        .join("decision.yaml");
    if !yaml_path.exists() {
        return Err(format!("decision.yaml 미발견: {}", yaml_path.display()));
    }
    let text = std::fs::read_to_string(&yaml_path)
        .map_err(|e| format!("decision.yaml read 실패: {e}"))?;
    let yaml_value: serde_yaml::Value =
        serde_yaml::from_str(&text).map_err(|e| format!("YAML parse 실패: {e}"))?;
    let json_text = serde_json::to_string(&yaml_value)
        .map_err(|e| format!("YAML→JSON 변환 실패: {e}"))?;
    let json_value: serde_json::Value = serde_json::from_str(&json_text)
        .map_err(|e| format!("JSON parse 실패 (내부): {e}"))?;
    Ok(json_value)
}

/// `outputs/_boardroom_sessions/*.md` list (timestamp desc, 최대 50건).
///
/// PR #221 Phase 3 회의록 — decision.yaml 과 session_id 로 cross-reference.
#[tauri::command]
async fn list_boardroom_sessions() -> Result<Vec<BoardroomListItem>, String> {
    let project_root = resolve_project_root()?;
    let dir = project_root.join("outputs").join("_boardroom_sessions");
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut items = Vec::new();
    let entries = std::fs::read_dir(&dir).map_err(|e| e.to_string())?;
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let name = match path.file_name().and_then(|s| s.to_str()) {
            Some(n) if n.ends_with(".md") => n.to_string(),
            _ => continue,
        };
        if let Some((timestamp, session_id)) = parse_boardroom_name(&name) {
            items.push(BoardroomListItem {
                name,
                timestamp,
                session_id,
                path: path.to_string_lossy().into_owned(),
            });
        }
    }
    items.sort_by(|a, b| b.timestamp.cmp(&a.timestamp));
    items.truncate(50);
    Ok(items)
}

/// `outputs/_boardroom_sessions/<name>.md` 의 raw markdown 텍스트.
#[tauri::command]
async fn read_boardroom_session(name: String) -> Result<String, String> {
    let project_root = resolve_project_root()?;
    let md_path = project_root
        .join("outputs")
        .join("_boardroom_sessions")
        .join(&name);
    if !md_path.exists() {
        return Err(format!("회의록 미발견: {}", md_path.display()));
    }
    std::fs::read_to_string(&md_path).map_err(|e| format!("회의록 read 실패: {e}"))
}

// ===========================================================================
// P21 — 런 리포트 (읽기 전용): 런 목록 / 본부별 단계 트리 / 파일 읽기 / 내보내기.
//   * 모든 read 는 outputs/ 하위로 *경로 제한*(safe_outputs_path) — 탈출 차단.
//   * 런 산출물(alpha_run_*/workflow_*) 은 *수정·삭제 없음*. 내보내기는 별도
//     outputs/_run_reports/<run_id>/ 에만 쓴다 (산출물 dir 불변 = 읽기 전용 보존).
//   * LLM 호출 0 — 전부 파일 파싱. PDF/HTML 은 record 와 동일한 python 렌더 파이프라인 재사용.
// ===========================================================================

const RUN_FILE_READ_LIMIT: usize = 5 * 1024 * 1024; // 미리보기 read 상한 5MB

/// 산출 디렉터리 outputs/ — 모든 P21 read/export 의 sandbox 루트.
fn outputs_root() -> Result<PathBuf, String> {
    Ok(resolve_project_root()?.join("outputs"))
}

/// 단일 경로 요소가 안전한지 (빈/`.`/`..`/separator/null/`:`(드라이브-상대) 금지).
/// `:` 차단으로 Windows 드라이브-상대 경로("D:", "C:Users") 탈출까지 방어.
fn is_safe_segment(s: &str) -> bool {
    !(s.is_empty()
        || s == "."
        || s == ".."
        || s.contains('/')
        || s.contains('\\')
        || s.contains('\0')
        || s.contains(':'))
}

/// run_id + 상대경로 → outputs/ 하위로 제한된 안전 절대경로. 경로 탈출(`..`·절대·separator)을
/// 차단: 각 component 검증 + 정규화 후 outputs 루트 포함 검사 (심볼릭 우회까지 방어).
fn safe_outputs_path(run_id: &str, rel: &str) -> Result<PathBuf, String> {
    if !is_safe_segment(run_id) {
        return Err(format!("잘못된 run_id: {run_id:?}"));
    }
    let root = outputs_root()?;
    let mut p = root.join(run_id);
    for part in rel.split(['/', '\\']) {
        if part.is_empty() || part == "." {
            continue;
        }
        if !is_safe_segment(part) {
            return Err(format!("경로 탈출 차단: {rel:?}"));
        }
        p.push(part);
    }
    // 존재하면 canonicalize 로 실경로 포함 검사, 미존재(export 대상)면 component 검증으로 충분.
    match p.canonicalize() {
        Ok(real) => {
            let root_c = root.canonicalize().map_err(|e| e.to_string())?;
            if !real.starts_with(&root_c) {
                return Err(format!("outputs 밖 접근 차단: {}", real.display()));
            }
            Ok(real)
        }
        Err(_) => {
            if !p.starts_with(&root) {
                return Err("outputs 밖 접근 차단".to_string());
            }
            Ok(p)
        }
    }
}

/// alpha_run_<YYYYMMDD_HHMMSS> 디렉터리명 → ISO8601 (실패 시 None).
fn parse_run_timestamp(name: &str) -> Option<String> {
    let ts = name.strip_prefix("alpha_run_").unwrap_or(name);
    let parts: Vec<&str> = ts.splitn(2, '_').collect();
    if parts.len() != 2 || parts[0].len() != 8 || parts[1].len() != 6 {
        return None;
    }
    let (d, t) = (parts[0], parts[1]);
    if !d.chars().all(|c| c.is_ascii_digit()) || !t.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(format!(
        "{}-{}-{}T{}:{}:{}Z",
        &d[0..4], &d[4..6], &d[6..8], &t[0..2], &t[2..4], &t[4..6]
    ))
}

/// 단계 파일명 → (본부 키, 본부 라벨, 정렬 순서). 파일명 NN_ 접두 기반 *결정론* 매핑
/// (하네스 스테이지 정의: analyze_and_implement/build_workflow/release_workflow + App.tsx 본부).
fn stage_hq(filename: &str) -> (&'static str, &'static str, u32) {
    let lower = filename.to_ascii_lowercase();
    if lower.starts_with("retrospective") {
        return ("hq-10", "Coordination · 회고", 90);
    }
    if lower.starts_with("knowledge_entry") {
        return ("hq-5", "지식 관리", 91);
    }
    let nn: Option<u32> = filename.get(0..2).and_then(|s| s.parse().ok());
    match nn {
        Some(0) => ("input", "입력 · 사용자 요청", 0),
        Some(1) => ("hq-0", "C-Level · 기술 전략", 1),
        Some(2) => ("hq-1", "업무 분석", 2),
        Some(3) => ("hq-3", "개발 · Engineer", 3),
        Some(4) | Some(5) => ("hq-4", "품질 검증 · QA/Pytest", 4),
        Some(10) => ("hq-2", "기획·설계 · UI/UX", 10),
        Some(11) | Some(12) | Some(13) => ("hq-7", "디자인 · GUI/Theme/CodeGen", 11),
        Some(14) => ("hq-4", "품질 검증 · QA/Pytest", 14),
        Some(20..=25) | Some(30..=34) => ("hq-8", "빌드 · 배포", 20),
        Some(26) => ("hq-9", "런타임 검증 · RV", 26),
        _ => ("other", "기타", 99),
    }
}

/// Track B(automate_workflow_*) 는 NN 번호 의미가 Track A 와 다르다(02 코드생성·03 QA·04 빌드).
/// Track A 본부 매핑을 그대로 쓰면 한 칸씩 밀린 오분류가 되므로, 회고/지식 외에는 *평면*
/// 'Track B · 자동화 단계' 그룹으로 폴백(번호 순서 보존) — 잘못된 본부 라벨 방지.
fn track_b_stage(filename: &str) -> (&'static str, &'static str, u32) {
    let lower = filename.to_ascii_lowercase();
    if lower.starts_with("retrospective") {
        return ("hq-10", "Coordination · 회고", 90);
    }
    if lower.starts_with("knowledge_entry") {
        return ("hq-5", "지식 관리", 91);
    }
    let order: u32 = filename.get(0..2).and_then(|s| s.parse().ok()).unwrap_or(99);
    ("track-b", "Track B · 자동화 단계", order)
}

/// 단계 파일 → 본부 매핑 (Track A/B 분기).
fn stage_hq_for(filename: &str, is_track_b: bool) -> (&'static str, &'static str, u32) {
    if is_track_b {
        track_b_stage(filename)
    } else {
        stage_hq(filename)
    }
}

/// 확장자 → frontend 렌더 분기용 kind.
fn file_kind(name: &str) -> &'static str {
    let l = name.to_ascii_lowercase();
    if l.ends_with(".md") {
        "md"
    } else if l.ends_with(".yaml") || l.ends_with(".yml") {
        "yaml"
    } else if l.ends_with(".json") {
        "json"
    } else if l.ends_with(".txt") {
        "txt"
    } else {
        "other"
    }
}

/// 파일 첫 헤딩/제목 줄 1줄 라벨 추출 (markdown `#` 우선, 없으면 첫 비공백 줄). LLM 0.
fn extract_label(content: &str) -> String {
    for line in content.lines().take(40) {
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        let h = t.trim_start_matches('#').trim();
        if !h.is_empty() {
            return h.chars().take(120).collect();
        }
    }
    String::new()
}

#[derive(Debug, Clone, Serialize)]
pub struct RunSummary {
    pub run_id: String,
    pub timestamp: String,
    pub request: String,
    pub stage_count: u32,
    pub verdict: String,
    pub iterations: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct StageFile {
    pub filename: String,
    pub rel_path: String, // run_id 디렉터리 기준 상대경로 (예: workflow_xx/01_cto_strategy.md)
    pub hq_key: String,
    pub hq_label: String,
    pub order: u32,
    pub label: String,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CodeEntry {
    pub rel_path: String,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RunReport {
    pub run_id: String,
    pub timestamp: String,
    pub request: String,
    pub verdict: String,
    pub iterations: String,
    pub workflow_dir: String,
    pub stages: Vec<StageFile>,
    pub code_files: Vec<CodeEntry>,
}

/// alpha_run_* 안의 *산출 본체* 서브디렉터리(workflow_* 또는 automate_workflow_*) 이름.
fn find_inner_workflow_dir(run_dir: &Path) -> Option<String> {
    let mut best: Option<String> = None;
    if let Ok(entries) = std::fs::read_dir(run_dir) {
        for e in entries.flatten() {
            if !e.path().is_dir() {
                continue;
            }
            if let Some(n) = e.file_name().to_str() {
                if n.starts_with("workflow_") || n.starts_with("automate_workflow_") {
                    // 가장 최근(이름 desc) 선택
                    if best.as_deref().map(|b| n > b).unwrap_or(true) {
                        best = Some(n.to_string());
                    }
                }
            }
        }
    }
    best
}

/// events.jsonl(outputs/events.jsonl) 에서 이 run 의 verdict/iterations best-effort 파싱.
/// 텔레메트리 OFF/연결 불가면 ("미상","미상") — *날조하지 않음*.
fn run_verdict_best_effort(run_id: &str, workflow_dir: &str) -> (String, String) {
    let path = match outputs_root() {
        Ok(r) => r.join("events.jsonl"),
        Err(_) => return ("미상".into(), "미상".into()),
    };
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return ("미상".into(), "미상".into()),
    };
    for line in text.lines().rev() {
        let v: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if v.get("type").and_then(|t| t.as_str()) != Some("result") {
            continue;
        }
        let saved = v.get("saved_dir").and_then(|s| s.as_str()).unwrap_or("");
        // saved_dir 이 이 run 의 workflow_* 를 가리키는지(부모=run_id, 자신=workflow_dir).
        let sp = Path::new(saved);
        let self_match = sp.file_name().and_then(|s| s.to_str()) == Some(workflow_dir);
        let parent_match = sp
            .parent()
            .and_then(|p| p.file_name())
            .and_then(|s| s.to_str())
            == Some(run_id);
        if self_match || parent_match {
            let verdict = v
                .get("verdict")
                .and_then(|s| s.as_str())
                .unwrap_or("미상")
                .to_string();
            let iters = v
                .get("iterations_run")
                .map(|i| i.to_string())
                .unwrap_or_else(|| "미상".into());
            return (verdict, iters);
        }
    }
    ("미상".into(), "미상".into())
}

/// 런 목록 — outputs/alpha_run_* 최신순(최대 100). 메타는 전부 파일 파싱(LLM 0).
#[tauri::command]
async fn list_runs() -> Result<Vec<RunSummary>, String> {
    let root = outputs_root()?;
    if !root.exists() {
        return Ok(Vec::new());
    }
    let mut items = Vec::new();
    for e in std::fs::read_dir(&root).map_err(|e| e.to_string())?.flatten() {
        let path = e.path();
        if !path.is_dir() {
            continue;
        }
        let name = match path.file_name().and_then(|s| s.to_str()) {
            Some(n) if n.starts_with("alpha_run_") => n.to_string(),
            _ => continue,
        };
        let timestamp = parse_run_timestamp(&name).unwrap_or_default();
        let inner = find_inner_workflow_dir(&path);
        let (mut request, mut stage_count) = (String::new(), 0u32);
        if let Some(wf) = &inner {
            let wf_dir = path.join(wf);
            if let Ok(req) = std::fs::read_to_string(wf_dir.join("00_user_request.txt")) {
                request = req.trim().chars().take(300).collect();
            }
            // get_run_report 와 동일 기준(파일 + .tmp 제외) — 사이드바 단계 수 일치.
            if let Ok(files) = std::fs::read_dir(&wf_dir) {
                for f in files.flatten() {
                    if f.path().is_file() {
                        if let Some(fname) = f.file_name().to_str() {
                            if !fname.ends_with(".tmp") {
                                stage_count += 1;
                            }
                        }
                    }
                }
            }
        }
        let (verdict, iterations) = match &inner {
            Some(wf) => run_verdict_best_effort(&name, wf),
            None => ("미상".into(), "미상".into()),
        };
        items.push(RunSummary { run_id: name, timestamp, request, stage_count, verdict, iterations });
    }
    items.sort_by(|a, b| b.run_id.cmp(&a.run_id)); // 디렉터리명(타임스탬프) desc = 최신순
    items.truncate(100);
    Ok(items)
}

/// 선택 런의 본부별 단계 트리 + code/ 파일 목록 + 메타. (읽기 전용, LLM 0)
#[tauri::command]
async fn get_run_report(run_id: String) -> Result<RunReport, String> {
    let run_dir = safe_outputs_path(&run_id, "")?;
    if !run_dir.is_dir() {
        return Err(format!("런 디렉터리 미발견: {run_id}"));
    }
    let workflow_dir = find_inner_workflow_dir(&run_dir)
        .ok_or_else(|| format!("workflow_* 산출 디렉터리 없음: {run_id}"))?;
    let wf_path = run_dir.join(&workflow_dir);
    let is_track_b = workflow_dir.starts_with("automate_workflow_");

    let mut stages: Vec<StageFile> = Vec::new();
    for e in std::fs::read_dir(&wf_path).map_err(|e| e.to_string())?.flatten() {
        let p = e.path();
        if !p.is_file() {
            continue;
        }
        let filename = match p.file_name().and_then(|s| s.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        if filename.ends_with(".tmp") {
            continue;
        }
        let (hq_key, hq_label, order) = stage_hq_for(&filename, is_track_b);
        // 첫 ~4KB 만 읽어 라벨 추출 (거대 파일 보호).
        let head = read_head(&p, 4096);
        stages.push(StageFile {
            label: extract_label(&head),
            kind: file_kind(&filename).to_string(),
            rel_path: format!("{workflow_dir}/{filename}"),
            filename,
            hq_key: hq_key.to_string(),
            hq_label: hq_label.to_string(),
            order,
        });
    }
    stages.sort_by(|a, b| a.order.cmp(&b.order).then_with(|| a.filename.cmp(&b.filename)));

    // code/ 트리 (렌더 대신 목록만)
    let mut code_files: Vec<CodeEntry> = Vec::new();
    let code_root = wf_path.join("code");
    if code_root.is_dir() {
        collect_code_tree(&code_root, &code_root, &mut code_files);
        code_files.sort_by(|a, b| a.rel_path.cmp(&b.rel_path));
        code_files.truncate(500);
    }

    let request = std::fs::read_to_string(wf_path.join("00_user_request.txt"))
        .map(|s| s.trim().chars().take(2000).collect::<String>())
        .unwrap_or_default();
    let (verdict, iterations) = run_verdict_best_effort(&run_id, &workflow_dir);

    Ok(RunReport {
        run_id,
        timestamp: String::new(),
        request,
        verdict,
        iterations,
        workflow_dir,
        stages,
        code_files,
    })
}

fn read_head(path: &Path, max: usize) -> String {
    use std::io::Read;
    let mut buf = Vec::new();
    if let Ok(f) = std::fs::File::open(path) {
        // take().read_to_end — 단일 read() 의 부분읽기(EOF 아닌데 적게 반환)를 피해
        // max 바이트(또는 EOF)까지 결정적으로 채운다.
        let _ = f.take(max as u64).read_to_end(&mut buf);
    }
    String::from_utf8_lossy(&buf).into_owned()
}

fn collect_code_tree(root: &Path, dir: &Path, out: &mut Vec<CodeEntry>) {
    if out.len() >= 500 {
        return;
    }
    if let Ok(entries) = std::fs::read_dir(dir) {
        for e in entries.flatten() {
            let p = e.path();
            if p.is_dir() {
                collect_code_tree(root, &p, out);
            } else if let Ok(rel) = p.strip_prefix(root) {
                let rel_s = rel.to_string_lossy().replace('\\', "/");
                out.push(CodeEntry {
                    kind: file_kind(&rel_s).to_string(),
                    rel_path: rel_s,
                });
            }
        }
    }
}

/// 단계/코드 파일 1개 읽기 — outputs/ 경로 제한. {content, kind} 반환.
#[tauri::command]
async fn read_run_file(run_id: String, rel_path: String) -> Result<serde_json::Value, String> {
    let path = safe_outputs_path(&run_id, &rel_path)?;
    if !path.is_file() {
        return Err(format!("파일 미발견: {rel_path}"));
    }
    let meta = std::fs::metadata(&path).map_err(|e| e.to_string())?;
    if meta.len() as usize > RUN_FILE_READ_LIMIT {
        // truncation 안내는 frontend 배지로 일원화 (본문에 덧붙이지 않음).
        return Ok(serde_json::json!({
            "kind": file_kind(&rel_path),
            "truncated": true,
            "content": read_head(&path, RUN_FILE_READ_LIMIT)
        }));
    }
    let content = std::fs::read_to_string(&path)
        .unwrap_or_else(|_| String::from("(텍스트가 아닌 파일 — 미리보기 불가)"));
    Ok(serde_json::json!({ "kind": file_kind(&rel_path), "truncated": false, "content": content }))
}

/// render_report.py spawn 인자 빌더 (순수 함수 — 단위 테스트 대상).
fn render_command_args(script: &str, mode: &str, input: &str, out: &str, title: &str) -> Vec<String> {
    vec![
        script.into(),
        "--mode".into(),
        mode.into(),
        "--in".into(),
        input.into(),
        "--out".into(),
        out.into(),
        "--title".into(),
        title.into(),
    ]
}

/// 본부 순서대로 결합 마크다운 조립 (export 공통). 각 단계 파일 내용을 종류별로 감싼다.
fn build_combined_markdown(report: &RunReport, run_dir: &Path) -> String {
    let mut s = String::new();
    s.push_str(&format!("# 런 리포트 — {}\n\n", report.run_id));
    s.push_str(&format!(
        "- **요청**: {}\n- **verdict**: {}\n- **iterations**: {}\n- **workflow**: {}\n- **단계 수**: {}\n\n---\n\n",
        report.request.replace('\n', " "),
        report.verdict,
        report.iterations,
        report.workflow_dir,
        report.stages.len()
    ));
    // 본부별로 묶어 각 본부를 1회만 출력 (frontend 트리와 일치 — 비연속 order(04·14 둘 다 QA)
    // 로 인한 ## 헤더 중복 방지). 첫 등장 순서 = 파이프라인 순서(stages 는 order 정렬됨).
    let mut order_seen: Vec<String> = Vec::new();
    let mut by_hq: std::collections::HashMap<String, Vec<&StageFile>> =
        std::collections::HashMap::new();
    for st in &report.stages {
        if !by_hq.contains_key(&st.hq_label) {
            order_seen.push(st.hq_label.clone());
        }
        by_hq.entry(st.hq_label.clone()).or_default().push(st);
    }
    for hq in &order_seen {
        s.push_str(&format!("\n## {hq}\n\n"));
        for st in &by_hq[hq] {
            s.push_str(&format!("### {} — {}\n\n", st.filename, st.label));
            let content =
                std::fs::read_to_string(run_dir.join(&st.rel_path)).unwrap_or_default();
            match st.kind.as_str() {
                "md" => {
                    s.push_str(&content);
                    s.push_str("\n\n");
                }
                "yaml" => s.push_str(&format!("```yaml\n{content}\n```\n\n")),
                "json" => s.push_str(&format!("```json\n{content}\n```\n\n")),
                _ => s.push_str(&format!("```\n{content}\n```\n\n")),
            }
        }
    }
    s
}

/// 런 리포트 내보내기 — format: "zip" | "html" | "pdf".
/// 산출은 outputs/_run_reports/<run_id>/run_report.<ext> (런 산출물 dir 불변). 저장 경로 반환.
#[tauri::command]
async fn export_run_report(run_id: String, format: String) -> Result<String, String> {
    let run_dir = safe_outputs_path(&run_id, "")?;
    if !run_dir.is_dir() {
        return Err(format!("런 디렉터리 미발견: {run_id}"));
    }
    let report = get_run_report(run_id.clone()).await?;

    let export_dir = outputs_root()?.join("_run_reports").join(&run_id);
    std::fs::create_dir_all(&export_dir).map_err(|e| format!("export 디렉터리 생성 실패: {e}"))?;

    match format.as_str() {
        "zip" => {
            let out = export_dir.join("run_report.zip");
            zip_run_files(&report, &run_dir, &out)?;
            Ok(out.to_string_lossy().into_owned())
        }
        "html" | "pdf" => {
            let combined = build_combined_markdown(&report, &run_dir);
            let tmp_md = export_dir.join("_combined.md");
            std::fs::write(&tmp_md, combined.as_bytes())
                .map_err(|e| format!("결합 마크다운 기록 실패: {e}"))?;
            let ext = if format == "pdf" { "pdf" } else { "html" };
            let out = export_dir.join(format!("run_report.{ext}"));
            run_render_python(&tmp_md, &out, &format, &run_id)?;
            Ok(out.to_string_lossy().into_owned())
        }
        other => Err(format!("지원하지 않는 format: {other}")),
    }
}

fn zip_run_files(report: &RunReport, run_dir: &Path, out: &Path) -> Result<(), String> {
    let file = std::fs::File::create(out).map_err(|e| format!("zip 생성 실패: {e}"))?;
    let mut zw = zip::ZipWriter::new(file);
    let opts: zip::write::FileOptions<()> =
        zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    use std::io::Write;
    let mut added = 0u32;
    for st in &report.stages {
        let p = run_dir.join(&st.rel_path);
        if let Ok(bytes) = std::fs::read(&p) {
            zw.start_file(st.filename.clone(), opts)
                .map_err(|e| format!("zip entry 실패: {e}"))?;
            zw.write_all(&bytes).map_err(|e| format!("zip write 실패: {e}"))?;
            added += 1;
        }
    }
    zw.finish().map_err(|e| format!("zip finish 실패: {e}"))?;
    if added == 0 {
        let _ = std::fs::remove_file(out); // 빈 0-entry zip 정리
        return Err("zip 에 포함할 단계 파일이 없습니다 (빈 산출 방지).".to_string());
    }
    Ok(())
}

fn run_render_python(in_md: &Path, out: &Path, mode: &str, title: &str) -> Result<(), String> {
    let project_root = resolve_project_root()?;
    let python = project_root.join(".venv").join("Scripts").join("python.exe");
    let script = project_root.join("scripts").join("render_report.py");
    if !python.exists() {
        return Err(format!("python 미발견: {}", python.display()));
    }
    if !script.exists() {
        return Err(format!("render_report.py 미발견: {}", script.display()));
    }
    let args = render_command_args(
        &script.to_string_lossy(),
        mode,
        &in_md.to_string_lossy(),
        &out.to_string_lossy(),
        title,
    );
    // .output() 으로 동기 대기 + stderr 캡처 — 실패 시 python traceback 을 사용자에게 surface.
    let output = Command::new(&python)
        .args(&args)
        .current_dir(&project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("render_report 실행 실패: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let lines: Vec<&str> = stderr.lines().collect();
        let tail = lines[lines.len().saturating_sub(8)..].join(" / ");
        // html/pdf 둘 다 python 파이프라인 — 실패 시 *zip(원본 묶음)* 이 무의존 대체 경로.
        return Err(format!(
            "{mode} 생성 실패 (종료코드 {:?}) — ZIP(원본 단계 파일 묶음)으로 대체 가능. {tail}",
            output.status.code()
        ));
    }
    Ok(())
}

/// 내보낸 리포트 폴더를 탐색기로 열기 — outputs/_run_reports/<run_id>/ 로 경로 제한.
#[tauri::command]
async fn open_report_folder(run_id: String) -> Result<(), String> {
    if !is_safe_segment(&run_id) {
        return Err(format!("잘못된 run_id: {run_id:?}"));
    }
    let base = outputs_root()?.join("_run_reports");
    let dir = base.join(&run_id);
    if !dir.is_dir() {
        return Err("내보낸 리포트 폴더 없음 — 먼저 내보내기 하세요.".to_string());
    }
    // 경로 탈출 차단(다른 4개 command 과 동일 불변식) — canonicalize 후 _run_reports 하위 검사.
    let real = dir.canonicalize().map_err(|e| e.to_string())?;
    let base_c = base.canonicalize().map_err(|e| e.to_string())?;
    if !real.starts_with(&base_c) {
        return Err("outputs/_run_reports 밖 접근 차단".to_string());
    }
    let mut cmd = if cfg!(windows) {
        let mut c = Command::new("explorer");
        c.arg(&dir);
        c
    } else {
        let mut c = Command::new("xdg-open");
        c.arg(&dir);
        c
    };
    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    cmd.spawn().map_err(|e| format!("폴더 열기 실패: {e}"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            greet,
            start_run,
            claude_auth_status,
            claude_auth_login,
            claude_auth_logout,
            open_exe,
            write_intervention_file,
            list_board_decisions,
            read_board_decision,
            list_boardroom_sessions,
            read_boardroom_session,
            list_runs,
            get_run_report,
            read_run_file,
            export_run_report,
            open_report_folder,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_boardroom_name_extracts_timestamp_and_session_id() {
        let parsed = parse_boardroom_name("20260528_120000_a1b2c3d4e5f6");
        assert_eq!(
            parsed,
            Some(("2026-05-28T12:00:00Z".to_string(), "a1b2c3d4e5f6".to_string()))
        );
    }

    #[test]
    fn parse_boardroom_name_handles_md_suffix() {
        let parsed = parse_boardroom_name("20260528_120000_abcdef123456.md");
        assert_eq!(
            parsed,
            Some(("2026-05-28T12:00:00Z".to_string(), "abcdef123456".to_string()))
        );
    }

    #[test]
    fn parse_boardroom_name_rejects_malformed() {
        assert!(parse_boardroom_name("not-a-valid-name").is_none());
        assert!(parse_boardroom_name("20260528_12_short").is_none());
        assert!(parse_boardroom_name("2026_120000_sessionid").is_none());
    }

    #[test]
    fn read_board_decision_parses_phase4_schema_v1() {
        // Phase 4 PR #222 schema v1 의 round-trip 검증 — serde_yaml → serde_json.
        let yaml = r#"
schema_version: "v1"
session:
  session_id: "a1b2c3d4e5f6"
  agenda: "GUI sandbox 강화"
  attendees:
    - CTO
    - GoalAlignmentAgent
    - TokenBudgetOptimizer
alignment:
  status: "approved"
  reason: "mission 부합"
  references:
    - "mission.md"
budget:
  status: "approved"
  estimated_cost_usd: 2.0
  budget_limit_usd: 15.0
  cumulative_cost_usd: 3.17
final_decision:
  outcome: "approved"
  reason: "둘 다 통과"
  blocked_by: []
"#;
        let parsed: serde_yaml::Value = serde_yaml::from_str(yaml).expect("YAML parse 실패");
        let json_text = serde_json::to_string(&parsed).expect("JSON 변환 실패");
        let json: serde_json::Value =
            serde_json::from_str(&json_text).expect("JSON parse 실패");
        assert_eq!(json["schema_version"], "v1");
        assert_eq!(json["alignment"]["status"], "approved");
        assert_eq!(json["budget"]["estimated_cost_usd"], 2.0);
        assert_eq!(json["final_decision"]["outcome"], "approved");
        assert_eq!(json["final_decision"]["blocked_by"].as_array().unwrap().len(), 0);
    }

    // -----------------------------------------------------------------------
    // P18 — build_run_args 플래그 매핑 (UI 컨트롤 → run.py 플래그)
    // -----------------------------------------------------------------------
    fn args_for(
        build_target: &str,
        max_iterations: u32,
        enable_tech_scout: bool,
        auto_iterate: bool,
    ) -> Vec<String> {
        build_run_args(
            Path::new("scripts/run.py"),
            "칸반 보드 웹앱",
            "A",
            build_target,
            max_iterations,
            enable_tech_scout,
            auto_iterate,
            false, // intervene — 기존 테스트는 OFF (P20 토글은 별도 테스트)
            Path::new("outputs/events.jsonl"),
        )
    }

    #[test]
    fn build_args_common_flags_always_present() {
        let a = args_for("web", 3, true, true);
        assert_eq!(a[0], "scripts/run.py");
        for pair in [
            ("--request", "칸반 보드 웹앱"),
            ("--track", "A"),
            ("--emit-events", "outputs/events.jsonl"),
            ("--max-iterations", "3"),
        ] {
            let idx = a.iter().position(|x| x == pair.0).expect("flag 누락");
            assert_eq!(a[idx + 1], pair.1, "{} 값 불일치", pair.0);
        }
        assert!(a.contains(&"--non-interactive".to_string()));
    }

    #[test]
    fn build_args_web_target_drops_force_cli_and_builds() {
        // web — GUI/web 분기 활성(force-cli 제거) + --build. ★앱 web 빌드 갭 해소.
        let a = args_for("web", 3, true, true);
        assert!(!a.contains(&"--force-cli".to_string()), "web 은 --force-cli 미부착");
        assert!(a.contains(&"--build".to_string()), "web 은 --build");
    }

    #[test]
    fn build_args_desktop_target_keeps_force_cli_and_builds() {
        // desktop — 기존 PyInstaller 경로 *그대로* (force-cli + build). 회귀 0.
        let a = args_for("desktop", 3, false, true);
        assert!(a.contains(&"--force-cli".to_string()), "desktop 은 --force-cli 유지");
        assert!(a.contains(&"--build".to_string()), "desktop 은 --build");
    }

    #[test]
    fn build_args_none_target_no_build_keeps_force_cli() {
        let a = args_for("none", 3, false, true);
        assert!(!a.contains(&"--build".to_string()), "none 은 --build 없음");
        assert!(a.contains(&"--force-cli".to_string()), "none 은 기존대로 --force-cli");
    }

    #[test]
    fn build_args_tech_scout_toggle() {
        assert!(args_for("web", 3, true, true).contains(&"--enable-tech-scout".to_string()));
        assert!(!args_for("web", 3, false, true).contains(&"--enable-tech-scout".to_string()));
    }

    #[test]
    fn build_args_auto_iterate_toggle() {
        let on = args_for("web", 5, true, true);
        assert!(on.contains(&"--auto-iterate".to_string()));
        assert!(!on.contains(&"--no-auto-iterate".to_string()));
        let off = args_for("web", 5, true, false);
        assert!(off.contains(&"--no-auto-iterate".to_string()));
        assert!(!off.contains(&"--auto-iterate".to_string()));
    }

    #[test]
    fn build_args_max_iterations_passthrough() {
        let a = args_for("web", 7, true, true);
        let idx = a.iter().position(|x| x == "--max-iterations").unwrap();
        assert_eq!(a[idx + 1], "7");
    }

    // -----------------------------------------------------------------------
    // P20 — 런 중 개입 토글 → --intervene 매핑 + intervention payload
    // -----------------------------------------------------------------------
    fn args_with_intervene(intervene: bool) -> Vec<String> {
        build_run_args(
            Path::new("scripts/run.py"),
            "칸반 보드 웹앱",
            "A",
            "web",
            3,
            true,
            true,
            intervene,
            Path::new("outputs/events.jsonl"),
        )
    }

    #[test]
    fn build_args_intervene_toggle() {
        // ON → --intervene 부착, OFF → 미부착 (기본 OFF = 기존 런 동일).
        assert!(args_with_intervene(true).contains(&"--intervene".to_string()));
        assert!(!args_with_intervene(false).contains(&"--intervene".to_string()));
    }

    #[test]
    fn build_args_off_target_has_no_intervene() {
        // args_for 헬퍼(기존 테스트)는 intervene=false → 어떤 타깃도 --intervene 없음.
        for t in ["web", "desktop", "none"] {
            assert!(!args_for(t, 3, true, true).contains(&"--intervene".to_string()));
        }
    }

    #[test]
    fn intervention_payload_json_has_feedback_and_action() {
        let json = intervention_payload_json("배경을 다크 테마로", "inject");
        let v: serde_json::Value = serde_json::from_str(&json).expect("valid JSON");
        assert_eq!(v["feedback"], "배경을 다크 테마로");
        assert_eq!(v["action"], "inject");
        // continue 액션도 직렬화 — feedback 비어도 유효 JSON.
        let cont: serde_json::Value =
            serde_json::from_str(&intervention_payload_json("", "continue")).unwrap();
        assert_eq!(cont["action"], "continue");
    }

    // -----------------------------------------------------------------------
    // P19 — ▶실행 타깃 인지 (web vite preview vs desktop .exe spawn)
    // -----------------------------------------------------------------------
    #[test]
    fn is_web_artifact_detects_html() {
        assert!(is_web_artifact(Path::new("outputs/code/dist/index.html")));
        assert!(is_web_artifact(Path::new("page.HTM"))); // 대소문자 무관
    }

    #[test]
    fn is_web_artifact_rejects_desktop_and_others() {
        assert!(!is_web_artifact(Path::new("dist/App.exe")));
        assert!(!is_web_artifact(Path::new("main.py")));
        assert!(!is_web_artifact(Path::new("noext")));
    }

    #[test]
    fn web_project_dir_is_grandparent_of_index_html() {
        // code_dir/dist/index.html → code_dir
        let dir = web_project_dir(Path::new("outputs/run/code/dist/index.html"));
        assert_eq!(dir, Some(PathBuf::from("outputs/run/code")));
    }

    #[test]
    fn local_vite_bin_points_into_node_modules() {
        let bin = local_vite_bin(Path::new("proj"));
        let s = bin.to_string_lossy();
        assert!(s.contains("node_modules"));
        assert!(s.contains(".bin"));
        // vite 또는 vite.cmd (플랫폼별)
        assert!(s.ends_with("vite") || s.ends_with("vite.cmd"));
    }

    #[test]
    fn vite_preview_invocation_has_preview_port_strictport_args() {
        let (program, args) =
            vite_preview_invocation(Path::new("proj/node_modules/.bin/vite.cmd"), 4173);
        assert!(args.iter().any(|a| a == "preview"));
        let pidx = args.iter().position(|a| a == "--port").expect("--port 누락");
        assert_eq!(args[pidx + 1], "4173");
        // strictPort 로 포트 점유 시 fallback 대신 실패 → 브라우저 URL 과 vite 포트 일치 보장.
        assert!(args.iter().any(|a| a == "--strictPort"), "--strictPort 누락");
        if cfg!(windows) {
            assert_eq!(program, "cmd");
            assert_eq!(args[0], "/C");
        } else {
            assert!(program.ends_with("vite"));
        }
    }

    #[test]
    fn vite_preview_invocation_uses_given_port() {
        let (_p, args) = vite_preview_invocation(Path::new("proj/node_modules/.bin/vite"), 51234);
        let pidx = args.iter().position(|a| a == "--port").unwrap();
        assert_eq!(args[pidx + 1], "51234"); // 동적 포트가 인자에 반영
    }

    #[test]
    fn pick_preview_port_returns_bindable_port() {
        // 선택된 포트는 실제로 바인딩 가능해야 함(4173 또는 OS 동적 포트). 0 이 아님.
        let port = pick_preview_port();
        assert!(port > 0);
        // 선택 직후엔 바인딩 가능(점유 전) — 재바인드로 유효성 확인.
        assert!(TcpListener::bind(("127.0.0.1", port)).is_ok());
    }

    // -----------------------------------------------------------------------
    // P21 — 런 리포트: 단계→본부 매핑 / 경로 제한 / 메타 파싱 / render 인자 / kind
    // -----------------------------------------------------------------------
    #[test]
    fn stage_hq_maps_pipeline_stages_to_headquarters() {
        assert_eq!(stage_hq("00_user_request.txt").0, "input");
        assert_eq!(stage_hq("01_cto_strategy.md").0, "hq-0");
        assert_eq!(stage_hq("02_analyst_brief.md").0, "hq-1");
        assert_eq!(stage_hq("03_engineer_output.md").0, "hq-3");
        assert_eq!(stage_hq("04_qa_review.md").0, "hq-4");
        assert_eq!(stage_hq("05_pytest_suite.md").0, "hq-4");
        assert_eq!(stage_hq("10_ui_ux_spec.md").0, "hq-2");
        assert_eq!(stage_hq("11_gui_design.md").0, "hq-7");
        assert_eq!(stage_hq("13_gui_code_output.md").0, "hq-7");
        assert_eq!(stage_hq("13d_generation_failed.txt").0, "hq-7"); // 조건부 진단도 디자인
        assert_eq!(stage_hq("14_pytest_suite.md").0, "hq-4");
        assert_eq!(stage_hq("20_dependency_report.md").0, "hq-8");
        assert_eq!(stage_hq("25_executor_result.md").0, "hq-8");
        assert_eq!(stage_hq("26_runtime_verify_pass.md").0, "hq-9");
        assert_eq!(stage_hq("33_distribution_spec.md").0, "hq-8");
        assert_eq!(stage_hq("retrospective.md").0, "hq-10");
        assert_eq!(stage_hq("retrospective_llm_raw.json").0, "hq-10");
        assert_eq!(stage_hq("knowledge_entry.yaml").0, "hq-5");
        assert_eq!(stage_hq("weird_unmapped.txt").0, "other");
    }

    #[test]
    fn stage_hq_order_follows_pipeline() {
        assert!(stage_hq("01_cto_strategy.md").2 < stage_hq("10_ui_ux_spec.md").2);
        assert!(stage_hq("10_ui_ux_spec.md").2 < stage_hq("20_dependency_report.md").2);
        assert!(stage_hq("20_dependency_report.md").2 < stage_hq("retrospective.md").2);
    }

    #[test]
    fn safe_outputs_path_blocks_traversal() {
        assert!(safe_outputs_path("../etc", "x").is_err());
        assert!(safe_outputs_path("run", "../../secret").is_err());
        assert!(safe_outputs_path("run", "..\\..\\secret").is_err());
        assert!(safe_outputs_path("a/b", "x").is_err()); // run_id 에 separator
        assert!(safe_outputs_path("..", "").is_err());
        // 드라이브-상대 탈출 차단 (":" 거부) — open_report_folder 우회 회귀 방지.
        assert!(safe_outputs_path("D:", "").is_err());
        assert!(safe_outputs_path("C:Users", "").is_err());
        assert!(!is_safe_segment("D:"));
        assert!(!is_safe_segment("C:Users"));
    }

    #[test]
    fn track_b_stage_uses_flat_group_not_track_a_hq() {
        // Track B 02/03/04 는 Track A 의미와 달라 평면 'Track B' 그룹으로 폴백 (오분류 방지).
        assert_eq!(track_b_stage("02_agent_output.md").0, "track-b");
        assert_eq!(track_b_stage("03_pytest_suite.md").0, "track-b");
        assert_eq!(track_b_stage("04_executor_result.md").0, "track-b");
        // 회고/지식 은 Track 무관 동일 본부.
        assert_eq!(track_b_stage("retrospective.md").0, "hq-10");
        assert_eq!(track_b_stage("knowledge_entry.yaml").0, "hq-5");
        // 분기 함수: is_track_b=false 면 Track A 매핑.
        assert_eq!(stage_hq_for("02_analyst_brief.md", false).0, "hq-1");
        assert_eq!(stage_hq_for("02_agent_output.md", true).0, "track-b");
    }

    #[test]
    fn safe_outputs_path_allows_normal_under_outputs() {
        let p = safe_outputs_path("alpha_run_20260603_013051", "workflow_x/01_cto_strategy.md")
            .expect("정상 경로는 허용");
        let s = p.to_string_lossy().replace('\\', "/");
        assert!(s.contains("/outputs/alpha_run_20260603_013051/workflow_x/01_cto_strategy.md"));
    }

    #[test]
    fn parse_run_timestamp_parses_alpha_run_dir() {
        assert_eq!(
            parse_run_timestamp("alpha_run_20260603_013051"),
            Some("2026-06-03T01:30:51Z".to_string())
        );
        assert_eq!(parse_run_timestamp("not_a_run"), None);
    }

    #[test]
    fn file_kind_branches_by_extension() {
        assert_eq!(file_kind("a.md"), "md");
        assert_eq!(file_kind("a.YAML"), "yaml");
        assert_eq!(file_kind("a.json"), "json");
        assert_eq!(file_kind("a.txt"), "txt");
        assert_eq!(file_kind("a.png"), "other");
    }

    #[test]
    fn extract_label_takes_first_heading() {
        assert_eq!(extract_label("# CTO 전략\n본문..."), "CTO 전략");
        assert_eq!(extract_label("\n\n## 분석 브리프\nx"), "분석 브리프");
        assert_eq!(extract_label("그냥 텍스트 첫 줄\n둘째"), "그냥 텍스트 첫 줄");
        assert_eq!(extract_label(""), "");
    }

    #[test]
    fn render_command_args_has_mode_in_out_title() {
        let a = render_command_args("scripts/render_report.py", "pdf", "c.md", "out.pdf", "런 X");
        assert_eq!(a[0], "scripts/render_report.py");
        for (flag, val) in [("--mode", "pdf"), ("--in", "c.md"), ("--out", "out.pdf"), ("--title", "런 X")] {
            let i = a.iter().position(|x| x == flag).expect("flag 존재");
            assert_eq!(a[i + 1], val);
        }
    }

    // ----- P22 (iter 간 개입: 패널 분기 + '빌드 열어보기' 매핑/활성) -----

    #[test]
    fn p22_panel_branch_on_iteration() {
        // iter 1 → P20 계획 패널, iter 2+ → 직전 빌드 검토 패널.
        assert!(!checkpoint_is_build_review(0));
        assert!(!checkpoint_is_build_review(1));
        assert!(checkpoint_is_build_review(2));
        assert!(checkpoint_is_build_review(5));
    }

    #[test]
    fn p22_open_build_enabled_only_with_path() {
        assert!(open_build_enabled(Some("C:/out/code/dist/index.html")));
        assert!(open_build_enabled(Some("C:/out/build_output/dist/App.exe")));
        // 빌드 null/빈/공백 → 비활성(안내).
        assert!(!open_build_enabled(None));
        assert!(!open_build_enabled(Some("")));
        assert!(!open_build_enabled(Some("   ")));
    }

    #[test]
    fn p22_open_build_routes_web_vs_desktop() {
        // '빌드 열어보기' 는 기존 open_exe 와 동일하게 is_web_artifact 로 web/desktop 라우팅.
        assert!(is_web_artifact(Path::new("C:/out/code/dist/index.html"))); // web → vite preview
        assert!(is_web_artifact(Path::new("C:/out/code/dist/index.HTM")));
        assert!(!is_web_artifact(Path::new("C:/out/build_output/dist/App.exe"))); // desktop → spawn
    }
}
