//! Host background loop — session injection + report-ready polling.
//!
//! Ports WebViewController.fetchAndInjectSessions (initial sessions/up-next
//! load) and the Darwin-notification handler. On Windows there is no Darwin
//! notification: per the M1 design, the engine's notify_report_ready is a
//! no-op and the host learns a report is ready by polling GET /status and
//! watching the `analysing` flag fall from true to false.

use std::thread;
use std::time::Duration;

use serde_json::Value;
use tauri::Manager;

pub fn start(app: tauri::AppHandle) {
    thread::spawn(move || {
        // 1. Give the webview + engine a moment, then decide the landing screen.
        //    IMPORTANT: window.loadSessions() unconditionally shows the sessions
        //    page and hides onboarding, so we must NOT call it when signed out —
        //    otherwise the user is stranded on an empty sessions page with no way
        //    to sign in. With a token: inject it + load sessions. Without one:
        //    show onboarding (the Google sign-in screen).
        thread::sleep(Duration::from_secs(2));
        if crate::token().is_some() {
            inject_token(&app);
            inject_sessions(&app);
        } else {
            crate::eval_in_webview(&app, "window.showOnboarding && window.showOnboarding();");
        }

        // 2. Poll the engine /status for the analysing true->false edge.
        let client = reqwest::blocking::Client::new();
        loop {
            thread::sleep(Duration::from_millis(1500));
            let status = client
                .get(format!("{}/status", crate::engine_url()))
                .timeout(Duration::from_secs(3))
                .send()
                .ok()
                .and_then(|r| r.json::<Value>().ok());

            let analysing = status
                .as_ref()
                .and_then(|s| s.get("analysing"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false);

            let state = app.state::<crate::AppState>();
            let report_ready = {
                let mut was = state.was_analysing.lock().unwrap();
                let edge = *was && !analysing; // true -> false means done
                *was = analysing;
                edge
            };
            if report_ready {
                // analysing finished -> a fresh report.json was written.
                load_latest_report(&app);
            }
        }
    });
}

fn inject_token(app: &tauri::AppHandle) {
    if let Some(token) = crate::token() {
        let js = format!(
            "window._fluentToken = {tok}; try {{ localStorage.setItem('fluent_token', {tok}); }} catch(e) {{}}",
            tok = serde_json::to_string(&token).unwrap_or_else(|_| "\"\"".into())
        );
        crate::eval_in_webview(app, &js);
    }
}

pub fn inject_sessions(app: &tauri::AppHandle) {
    let sessions = backend_get_json(app, "/sessions").unwrap_or(Value::Array(vec![]));
    let up_next = backend_get_json(app, "/calendar/upcoming").unwrap_or(Value::Array(vec![]));
    let js = format!(
        "if (window.loadSessions) window.loadSessions({}, {});",
        sessions, up_next
    );
    crate::eval_in_webview(app, &js);
}

fn load_latest_report(app: &tauri::AppHandle) {
    // ~/.fluent/reports/latest.json
    if let Some(home) = dirs_home() {
        let path = home.join(".fluent").join("reports").join("latest.json");
        if let Ok(text) = std::fs::read_to_string(&path) {
            if serde_json::from_str::<Value>(&text).is_ok() {
                let js = format!("if (window.loadReport) window.loadReport({});", text);
                crate::eval_in_webview(app, &js);
            }
        }
    }
}

/// Authenticated GET to the backend, returning parsed JSON.
fn backend_get_json(_app: &tauri::AppHandle, path: &str) -> Option<Value> {
    let client = reqwest::blocking::Client::new();
    let mut req = client
        .get(format!("{}{}", crate::backend_url(), path))
        .timeout(Duration::from_secs(15));
    if let Some(token) = crate::token() {
        req = req.header("Authorization", format!("Bearer {token}"));
    }
    req.send().ok()?.json::<Value>().ok()
}

fn dirs_home() -> Option<std::path::PathBuf> {
    std::env::var_os("USERPROFILE")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(std::path::PathBuf::from))
}
