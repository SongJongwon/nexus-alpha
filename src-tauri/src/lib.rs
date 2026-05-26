//! Nexus Alpha Tauri shell — Agent Office Visualizer (Sprint 5 PR-C).
//!
//! 본 crate 는 docs/insights/desktop_app_vision.md 의 데스크탑 앱 비전을
//! 실제 코드로 진입시키는 골격. PR-A 는 hello-world Rust shell, PR-B 는 React
//! + Tailwind 부서 그리드 placeholder, **본 PR-C** 는 Python sidecar spawn +
//! JSON Lines tail + 4 event type frontend emit 의 *최초 동작 layer* 추가.
//!
//! 백엔드 Python 코드 수정은 0 — PR #188 (Sprint 4) 의 Telemetry hook 이
//! 모든 event 를 events.jsonl 로 emit 하므로 Rust shell 은 *tail 만* 한다.

use std::{
    fs::OpenOptions,
    io::{BufRead, BufReader, Seek, SeekFrom},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::Duration,
};

use tauri::{AppHandle, Emitter};

/// Smoke test command — frontend (또는 외부 tool) 가 invoke 했을 때 Tauri shell
/// 이 살아있음을 확인하는 1 줄 응답. (PR-A 부터 유지)
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {name}! Nexus Alpha Tauri shell is alive.")
}

/// Python sidecar (`scripts/run.py`) 를 spawn 하고 `outputs/events.jsonl` tail
/// 을 별도 thread 에서 시작한다. tail 은 `nexus://telemetry` event 로 frontend
/// 에 그대로 forward (한 line = 한 JSON event).
///
/// 본 PR-C 시점의 단순화:
///   * tail thread shutdown 없음 (앱 라이프타임 = thread 라이프타임).
///   * sidecar PID 추적 없음 (재실행 시 이전 sidecar 가 계속 돌아갈 수 있음 —
///     Sprint 5 후속 작업).
///   * Python interpreter 는 `.venv\Scripts\python.exe` 하드코드 (Sprint 6
///     설치 환경 대응 시 동봉 sidecar 또는 시스템 python 자동 탐지로 확장).
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
    // 이전 run 의 jsonl 잔류 방지 — truncate.
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

/// Tauri dev 환경에서 cwd 가 `src-tauri/` 일 수 있다. 한 단계 위로 올려 project
/// root 를 결정. 그 외에는 cwd 가 곧 project root.
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

/// events.jsonl 의 새 line 을 polling (500ms) 하여 `nexus://telemetry` event 로
/// frontend 에 forward. 각 line 은 원본 JSON 문자열 그대로 (frontend 가 parse).
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
            Err(_) => {
                // jsonl 미존재 또는 read 실패는 정상 (sidecar 가 첫 줄 쓰기 전).
                // polling 계속.
            }
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

/// Tauri application entry — `main.rs` 와 (향후) mobile entry point 가 공유.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![greet, start_run])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
