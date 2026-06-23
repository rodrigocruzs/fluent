//! System tray — port of the macOS NSStatusItem menu.
//!
//! Start/Stop drive the engine directly (POST /start, /stop); Settings and
//! Sign out emit events the frontend listens for; Quit exits the app.

use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri::Manager;

pub fn build(app: &tauri::AppHandle) -> tauri::Result<()> {
    let start = MenuItem::with_id(app, "start", "Start recording", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "Stop recording", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let sign_out = MenuItem::with_id(app, "sign_out", "Sign out", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Fluent", true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&start, &stop, &settings, &sign_out, &quit])?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .tooltip("Fluent")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "start" => engine_post("/start"),
            "stop" => engine_post("/stop"),
            "settings" => crate::emit(app, "show-settings", ()),
            "sign_out" => {
                crate::sign_out();
                crate::emit(app, "signed-out", ());
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click the tray icon -> bring the main window forward.
            if let TrayIconEvent::Click { .. } = event {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

/// Show the main window when the user clicks the tray icon (in case it was hidden).
fn show_main(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
    }
}

fn engine_post(path: &str) {
    let url = format!("{}{}", crate::engine_url(), path);
    // Fire-and-forget; the frontend reflects state via its own polling.
    std::thread::spawn(move || {
        let _ = reqwest::blocking::Client::new()
            .post(&url)
            .timeout(Duration::from_secs(5))
            .send();
    });
}
