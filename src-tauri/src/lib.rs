//! Nexus Alpha Tauri shell — Agent Office Visualizer.
//!
//! Sprint 5 + Claude Code CLI 인증 통합. 본 file 의 commands:
//!   * claude_auth_status — `claude auth status --json` 호출 + JSON parse
//!   * claude_auth_login  — `claude auth login` (브라우저 OAuth 인터랙티브)
//!   * claude_auth_logout — `claude auth logout`
//!   * start_run          — Python sidecar spawn (--force-cli + claude.exe PATH 주입)
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

/// Python sidecar (`scripts/run.py`) spawn + events.jsonl tail thread.
///
/// 본 PR (2026-05-26) 부터 spawn 시점에 *claude.exe 의 디렉터리* 를 자식
/// process 의 PATH 에 prepend + `CLAUDE_CLI_PATH` env var 전달. 향후 백엔드가
/// claude CLI 를 자식 process 로 호출할 때 *Rust 에서 결정한 절대 경로* 를
/// 그대로 사용 가능 (현재 scripts/run.py 는 미사용이지만 일관성).
#[tauri::command]
async fn start_run(
    app: AppHandle,
    request: String,
    track: String,
    build: bool,
    max_iterations: u32,
) -> Result<String, String> {
    let project_root = resolve_project_root()?;
    let events_path = project_root.join("outputs").join("events.jsonl");

    if let Some(parent) = events_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("outputs 디렉터리 생성 실패: {e}"))?;
    }
    let _ = std::fs::File::create(&events_path)
        .map_err(|e| format!("events.jsonl 초기화 실패: {e}"))?;

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

    let mut cmd = Command::new(&python);
    cmd.arg(&run_script)
        .arg("--request")
        .arg(&request)
        .arg("--track")
        .arg(&track)
        .arg("--force-cli") // Claude Code CLI 구독 흐름 강제 (Track A 의 GUI 분기 비활성)
        .arg("--emit-events")
        .arg(&events_path)
        .arg("--max-iterations")
        .arg(max_iterations.to_string())
        .arg("--non-interactive")
        .current_dir(&project_root)
        // 2026-05-26 fix — Stdio::piped() 인데 부모가 read 안 하면 child 의
        // OS write buffer full → Python sidecar 가 BrokenPipeError 로 즉시 사망 →
        // events.jsonl 0 byte. inherit() 로 변경하면 dev 모드는 Tauri shell 의
        // console 로 stream (debugging 가능), release 의 GUI subsystem 은 NULL
        // handle inherit (조용히 무시) — 양쪽 모두 broken pipe 회피.
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    if build {
        cmd.arg("--build");
    }

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            greet,
            start_run,
            claude_auth_status,
            claude_auth_login,
            claude_auth_logout,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
