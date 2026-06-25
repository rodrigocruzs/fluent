//! Fluent for Windows — Tauri host.
//!
//! Ports the responsibilities of the macOS Swift app (AppDelegate +
//! WebViewController) to a Rust + WebView2 host:
//!   - spawn & supervise the Python engine on port 2788  (engine module)
//!   - the `apiRequest` bridge to tryfluent.co/api        (api_request command)
//!   - session injection + report-ready polling            (host_loop)
//!   - system tray menu                                     (tray)
//!
//! The shared web UI (../../frontend) runs unchanged; tauri-bridge.js
//! synthesizes the WebKit messageHandlers interface report.js expects.

use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{Emitter, Manager};

const BACKEND_URL: &str = "https://www.tryfluent.co/api";
const ENGINE_URL: &str = "http://127.0.0.1:2788";
const ENGINE_PORT: u16 = 2788;
const KEYRING_SERVICE: &str = "fluent";
const KEYRING_ACCOUNT: &str = "jwt_token";

// ── Token store ──────────────────────────────────────────────────────────────
// Same Credential Manager entry the engine's platform/win.py uses, so the host
// and the engine share one token.

fn get_token() -> Option<String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).ok()?;
    entry.get_password().ok().filter(|t| !t.is_empty())
}

fn save_token(token: &str) {
    if let Ok(entry) = keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT) {
        let _ = entry.set_password(token);
    }
}

fn clear_token() {
    if let Ok(entry) = keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT) {
        let _ = entry.delete_password();
    }
}

// ── apiRequest bridge (M3c) ────────────────────────────────────────────────────
// Mirrors WebViewController.handleApiRequest: attach the JWT, call the backend,
// return { ok, status, body } where body is the raw response text.

#[derive(Serialize)]
struct ApiResponse {
    ok: bool,
    status: u16,
    body: String,
}

#[tauri::command]
async fn api_request(path: String, method: String, body: Option<String>) -> Result<ApiResponse, String> {
    let url = format!("{BACKEND_URL}{path}");
    let client = reqwest::Client::new();
    let m = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
    let mut req = client.request(m, &url);

    if let Some(token) = get_token() {
        req = req.header("Authorization", format!("Bearer {token}"));
    }
    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }

    match req.send().await {
        Ok(resp) => {
            let status = resp.status().as_u16();
            let ok = resp.status().is_success();
            let text = resp.text().await.unwrap_or_default();
            Ok(ApiResponse { ok, status, body: text })
        }
        Err(e) => Ok(ApiResponse { ok: false, status: 0, body: format!("{{\"error\":\"{e}\"}}") }),
    }
}

#[tauri::command]
fn sign_out() {
    clear_token();
    // Best-effort: also tell the engine to drop its cached token.
    let _ = reqwest::blocking::Client::new()
        .post(format!("{ENGINE_URL}/signout"))
        .timeout(Duration::from_secs(3))
        .send();
}

// ── Engine supervision (M3d) ────────────────────────────────────────────────────

mod engine;

// ── Host background loop (M3e): sessions injection + report-ready polling ───────

mod host_loop;

// ── Tray (M3e) ──────────────────────────────────────────────────────────────────

mod tray;

// ── Auth: fluent:// deep-link handler (M5) ──────────────────────────────────────

mod auth;

// ── Auto-update (M6) ────────────────────────────────────────────────────────────

mod update;

/// Shared host state.
pub struct AppState {
    /// Last seen `analysing` flag from the engine /status, to detect the
    /// true->false edge that means a fresh report is ready.
    pub was_analysing: Mutex<bool>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // single-instance MUST be the first plugin: it captures a fluent://
        // launch and forwards the URLs (argv) to the already-running app.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            let urls: Vec<String> = argv
                .into_iter()
                .filter(|a| a.starts_with("fluent://"))
                .collect();
            if !urls.is_empty() {
                auth::handle_urls(app, urls);
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(AppState { was_analysing: Mutex::new(false) })
        .invoke_handler(tauri::generate_handler![api_request, sign_out])
        .setup(|app| {
            // 0. Register the runtime deep-link handler (covers the case where
            //    the app is already running when fluent:// fires).
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                let handle = app.handle().clone();
                app.deep_link().on_open_url(move |event| {
                    let urls: Vec<String> = event.urls().iter().map(|u| u.to_string()).collect();
                    auth::handle_urls(&handle, urls);
                });
                // On dev/Windows, ensure the scheme is registered for the
                // current executable so callbacks route back to us.
                let _ = app.deep_link().register("fluent");
            }

            // 1. Start & supervise the Python engine.
            engine::spawn_and_supervise(app.handle().clone());

            // 2. Build the system tray.
            tray::build(app.handle())?;

            // 3. Once the webview is ready: inject sessions, then poll for
            //    report-ready and re-inject as needed.
            host_loop::start(app.handle().clone());

            // 4. Check for updates in the background (non-blocking). If an
            //    update is found it is downloaded and installed, then the app
            //    relaunches. Silently ignores failures (e.g. offline).
            {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    update::check_and_install(handle).await;
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Fluent");
}

// Helpers shared across modules.

pub(crate) fn backend_url() -> &'static str { BACKEND_URL }
pub(crate) fn engine_url() -> &'static str { ENGINE_URL }
pub(crate) fn engine_port() -> u16 { ENGINE_PORT }
pub(crate) fn token() -> Option<String> { get_token() }

/// Re-fetch and re-inject the sessions list (after sign-in). Runs the blocking
/// HTTP on a background thread so it never blocks the deep-link callback.
pub(crate) fn reinject_sessions(app: tauri::AppHandle) {
    std::thread::spawn(move || host_loop::inject_sessions(&app));
}

/// Inject a JS call into the main webview (e.g. window.loadSessions(...)).
pub(crate) fn eval_in_webview(app: &tauri::AppHandle, js: &str) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.eval(js);
    }
}

/// Emit a Tauri event (used by the tray to drive UI actions).
pub(crate) fn emit(app: &tauri::AppHandle, event: &str, payload: impl Serialize + Clone) {
    let _ = app.emit(event, payload);
}
