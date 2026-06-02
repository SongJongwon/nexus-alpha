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

/// 빌드된 .exe 를 detached spawn 으로 실행 (frontend 의 "실행" 버튼).
///
/// 2026-05-26 추가 — Sprint 6 의 *GUI 앱 자동 .exe 빌드* 흐름의 마지막 layer.
/// ResultEvent.exe_path 가 채워진 run 종료 후, frontend 가 본 command 를 invoke
/// 해서 사용자가 즉시 빌드된 앱을 실행할 수 있도록.
///
/// Detached spawn — Tauri shell 의 stdin/stdout 을 inherit 하지 *않음*. release
/// 모드의 GUI subsystem 에서는 console 없으니 NULL handle, dev 모드에서는
/// inherit 가 안전. spawn 후 child handle drop — 부모가 종료해도 child 는 계속
/// 실행.
#[tauri::command]
async fn open_exe(path: String) -> Result<(), String> {
    let exe_path = std::path::PathBuf::from(&path);
    if !exe_path.exists() {
        return Err(format!("실행 파일 미발견: {path}"));
    }
    if !exe_path.is_file() {
        return Err(format!("파일 아님 (디렉터리?): {path}"));
    }
    let mut cmd = Command::new(&exe_path);
    if let Some(parent) = exe_path.parent() {
        cmd.current_dir(parent);
    }
    cmd.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null());
    cmd.spawn()
        .map_err(|e| format!(".exe 실행 실패 ({path}): {e}"))?;
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
#[tauri::command]
async fn start_run(
    app: AppHandle,
    request: String,
    track: String,
    build_target: String,
    max_iterations: u32,
    enable_tech_scout: bool,
    auto_iterate: bool,
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
            list_board_decisions,
            read_board_decision,
            list_boardroom_sessions,
            read_boardroom_session,
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
}
