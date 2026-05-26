//! Nexus Alpha Tauri shell — Agent Office Visualizer.
//!
//! Sprint 5 이후 PR — Claude Code CLI 인증 통합 + sticky toolbar 백엔드.
//!   * claude_auth_status — `claude auth status --json` 호출 + JSON parse
//!   * claude_auth_login  — `claude auth login` (브라우저 OAuth 인터랙티브) 실행
//!   * claude_auth_logout — `claude auth logout` 실행
//!   * start_run          — Python sidecar spawn (--force-cli 기본 추가)
//!
//! 백엔드 Python 코드 수정은 0 — `scripts/run.py` 의 기존 `--force-cli` (Track A
//! 의 GUI 분기 비활성) + `--emit-events` (PR #188 telemetry) flag 를 그대로 활용.

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
// Claude Code CLI 인증
// ---------------------------------------------------------------------------

/// `claude auth status --json` 의 응답 schema. PM 요청은 `claude whoami` 였으나
/// 해당 명령은 *LLM 호출* (메모리 기반 출력) 이라 deterministic parsing 부적합 —
/// `auth status --json` 으로 대체. 사용자 의도 (인증 상태 + 이메일 + plan) 모두
/// 커버 + JSON 으로 직접 parse 가능.
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
    /// 에러 메시지 (parse 실패 / CLI 미설치 등) — 비어있으면 정상.
    #[serde(default)]
    pub error: Option<String>,
}

/// Claude Code CLI 인증 상태 조회. CLI 가 없으면 logged_in=false + error 반환.
#[tauri::command]
async fn claude_auth_status() -> Result<AuthStatus, String> {
    let output = match Command::new("claude")
        .arg("auth")
        .arg("status")
        .arg("--json")
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            return Ok(AuthStatus {
                logged_in: false,
                error: Some(format!("claude CLI 실행 실패 (PATH 확인): {e}")),
                ..Default::default()
            });
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    // exit 0 가 아니어도 stdout 에 JSON 이 있으면 parse 시도.
    // (logout 직후 등 일부 케이스에서 exit code 가 비0)
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

/// `claude auth login` 실행 후 status 재조회.
///
/// 본 명령은 *인터랙티브* — Claude CLI 가 시스템 기본 브라우저를 열어 OAuth 진행.
/// stdin/stdout 은 부모 (Tauri shell) 의 것을 inherit. dev 모드에서 콘솔 prompt
/// 가 보일 수 있음. 사용자 가 브라우저 콜백 완료 시 CLI 종료 → 재조회 결과 반환.
#[tauri::command]
async fn claude_auth_login() -> Result<AuthStatus, String> {
    let status = Command::new("claude")
        .arg("auth")
        .arg("login")
        .status()
        .map_err(|e| format!("claude auth login 실행 실패 (PATH 확인): {e}"))?;

    if !status.success() {
        return Err(format!(
            "claude auth login 종료 코드 {:?} — OAuth 흐름 미완료 또는 사용자 취소",
            status.code()
        ));
    }

    claude_auth_status().await
}

/// `claude auth logout` 실행. 성공 시 token 삭제됨 → 후속 auth_status 가 not logged in.
#[tauri::command]
async fn claude_auth_logout() -> Result<(), String> {
    let status = Command::new("claude")
        .arg("auth")
        .arg("logout")
        .status()
        .map_err(|e| format!("claude auth logout 실행 실패 (PATH 확인): {e}"))?;

    if !status.success() {
        return Err(format!(
            "claude auth logout 종료 코드 {:?}",
            status.code()
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Python sidecar spawn + jsonl tail
// ---------------------------------------------------------------------------

/// Python sidecar (`scripts/run.py`) spawn + events.jsonl tail thread 시작.
///
/// 본 PR 부터 `--force-cli` flag 가 기본 추가 — Track A 의 GUI 분기 비활성화 + Claude
/// Code CLI 구독 흐름 강제. (사용자 요청 4: "Claude Code 구독 방식으로 실행, API 키 불필요")
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
        .arg("--force-cli") // PM 요청: Track A 의 GUI 분기 비활성 + CLI 구독 흐름 강제
        .arg("--emit-events")
        .arg(&events_path)
        .arg("--max-iterations")
        .arg(max_iterations.to_string())
        .arg("--non-interactive")
        .current_dir(&project_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if build {
        cmd.arg("--build");
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
    let mut offset: u64 = 0;
    loop {
        thread::sleep(Duration::from_millis(500));
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
            Err(_) => {}
        }
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
