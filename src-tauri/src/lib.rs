//! Nexus Alpha Tauri shell — Agent Office Visualizer (Sprint 5 PR-A).
//!
//! 본 crate 는 docs/insights/desktop_app_vision.md 의 Tauri 데스크탑 앱 비전을
//! 실제 코드로 진입시키는 *최초 골격*. PR-A 시점에서는 hello-world 수준의 `greet`
//! command 한 개만 제공한다.
//!
//! 이어지는 Sprint 5 의 다음 PR:
//!   * PR-B — React + Tailwind frontend scaffold + 부서 그리드 (🔵 기획 / 🟣 개발
//!     / 🟢 학습) placeholder 3 카드 마운트.
//!   * PR-C — Python sidecar spawn (`scripts/run.py --emit-events events.jsonl`)
//!     Tauri command + JSON Lines tail + 4 event type 콘솔 log 검증.
//!
//! 백엔드 Python 코드 수정은 0 — PR #188 (Sprint 4) 의 Telemetry hook 이
//! 모든 event 를 jsonl 로 emit 하므로 Rust shell 은 tail 만 한다.

/// Smoke test command — frontend (또는 외부 tool) 가 invoke 했을 때 Tauri shell
/// 이 살아있음을 확인하는 1 줄 응답.
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {name}! Nexus Alpha Tauri shell is alive.")
}

/// Tauri application entry — `main.rs` 와 (향후) mobile entry point 가 공유.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![greet])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
