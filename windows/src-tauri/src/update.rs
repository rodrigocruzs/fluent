//! Auto-update (M6).
//!
//! On startup the host asks the updater plugin to check the configured update
//! endpoints (see tauri.conf.json plugins.updater). If a newer signed release
//! is available it is downloaded and installed, then the app relaunches.
//!
//! Best-effort: any failure (offline, no update, bad manifest) is logged and
//! ignored so it never blocks normal startup.

use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

/// Check for an update and, if found, install it and relaunch.
pub async fn check_and_install(app: AppHandle) {
    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            eprintln!("[update] updater unavailable: {e}");
            return;
        }
    };

    match updater.check().await {
        Ok(Some(update)) => {
            println!(
                "[update] update available: {} -> {}",
                update.current_version, update.version
            );
            // download_and_install streams the artifact; we don't surface
            // progress UI for now (silent background update).
            if let Err(e) = update
                .download_and_install(|_chunk, _total| {}, || {})
                .await
            {
                eprintln!("[update] download/install failed: {e}");
                return;
            }
            println!("[update] installed; relaunching");
            app.restart();
        }
        Ok(None) => {
            println!("[update] up to date");
        }
        Err(e) => {
            eprintln!("[update] check failed: {e}");
        }
    }
}
