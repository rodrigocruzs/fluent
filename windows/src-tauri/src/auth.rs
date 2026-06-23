//! fluent:// deep-link auth handler — port of AppDelegate's URL-scheme handler
//! and WebViewController.handleGoogleAuthCallback.
//!
//! Google OAuth (opened in the system browser via the openURL bridge) ends with
//! the backend redirecting to:
//!     fluent://auth?token=<jwt>&name=<n>&email=<e>      (success)
//!     fluent://auth?error=<reason>                       (failure)
//! Windows routes that URL to the running app (single-instance + deep-link).
//! We then mirror the macOS handler: persist the token, tell the engine, and
//! drive the frontend's authComplete path.

use tauri::Manager;
use url::Url;

/// Handle one or more deep-link URLs delivered to the app.
pub fn handle_urls(app: &tauri::AppHandle, urls: Vec<String>) {
    for raw in urls {
        let Ok(url) = Url::parse(&raw) else { continue };
        if url.scheme() != "fluent" {
            continue;
        }
        // Accept fluent://auth?... regardless of how the host part parses.
        let mut token = None;
        let mut error = None;
        for (k, v) in url.query_pairs() {
            match k.as_ref() {
                "token" => token = Some(v.into_owned()),
                "error" => error = Some(v.into_owned()),
                _ => {}
            }
        }

        if let Some(token) = token {
            on_auth_success(app, &token);
        } else if let Some(error) = error {
            on_auth_error(app, &error);
        }
    }
}

fn on_auth_success(app: &tauri::AppHandle, token: &str) {
    // 1. Persist to Credential Manager (the engine reads the same entry).
    crate::save_token(token);

    // 2. Best-effort: tell the running engine to cache it too.
    let t = token.to_string();
    std::thread::spawn(move || {
        let _ = reqwest::blocking::Client::new()
            .post(format!("{}/signin", crate::engine_url()))
            .json(&serde_json::json!({ "token": t }))
            .timeout(std::time::Duration::from_secs(3))
            .send();
    });

    // 3. Drive the frontend exactly like WebViewController did: set the token in
    //    localStorage and fire authComplete, then re-inject sessions.
    let tok_js = serde_json::to_string(token).unwrap_or_else(|_| "\"\"".into());
    let js = format!(
        "try {{ localStorage.setItem('fluent_token', {tok}); }} catch(e) {{}}\n\
         window._fluentToken = {tok};\n\
         if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.authComplete) {{\n\
           window.webkit.messageHandlers.authComplete.postMessage({tok});\n\
         }}",
        tok = tok_js
    );
    crate::eval_in_webview(app, &js);

    // Bring the window forward so the user sees they're signed in.
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
    }

    // Re-inject sessions now that we're authenticated.
    crate::reinject_sessions(app.clone());
}

fn on_auth_error(app: &tauri::AppHandle, message: &str) {
    let msg_js = serde_json::to_string(message).unwrap_or_else(|_| "\"sign-in failed\"".into());
    let js = format!(
        "window.showOnboarding && window.showOnboarding();\n\
         var el = document.getElementById('auth-error');\n\
         if (el) el.textContent = 'Google sign-in failed: ' + {msg};",
        msg = msg_js
    );
    crate::eval_in_webview(app, &js);
}
