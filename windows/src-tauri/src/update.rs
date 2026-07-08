//! Auto-update (M6).
//!
//! On startup the host asks the updater plugin to check the configured update
//! endpoints (see tauri.conf.json plugins.updater). If a newer signed release
//! is available it is downloaded in the background and held in
//! `PendingUpdate` until the user quits — installing it then (rather than
//! immediately, via `app.restart()`) avoids yanking the app out from under
//! someone mid-session and prevents an unexplained installer window popping
//! up unprompted, which reads as malware to a non-technical user.
//!
//! Best-effort: any failure (offline, no update, bad manifest) is logged and
//! ignored so it never blocks normal startup or shutdown.

use std::sync::Mutex;

use tauri::{AppHandle, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

/// Holds a downloaded-but-not-yet-installed update, if any.
#[derive(Default)]
pub struct PendingUpdate(pub Mutex<Option<(Update, Vec<u8>)>>);

/// Check for an update and, if found, download it (but don't install yet).
/// The bytes are stashed in `PendingUpdate` for `install_pending_on_exit` to
/// apply once the app is already closing.
pub async fn check_and_download(app: AppHandle) {
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
            match update.download(|_chunk, _total| {}, || {}).await {
                Ok(bytes) => {
                    println!("[update] downloaded; will install on quit");
                    if let Some(state) = app.try_state::<PendingUpdate>() {
                        *state.0.lock().unwrap() = Some((update, bytes));
                    }
                }
                Err(e) => eprintln!("[update] download failed: {e}"),
            }
        }
        Ok(None) => {
            println!("[update] up to date");
        }
        Err(e) => {
            eprintln!("[update] check failed: {e}");
        }
    }
}

/// Install a previously-downloaded update, if any. Called when the app is
/// already exiting, so the installer (configured for silent `quiet` mode —
/// see tauri.conf.json plugins.updater.windows.installMode) runs during the
/// close the user themselves initiated, with no visible window and no
/// surprise mid-session quit.
pub fn install_pending_on_exit(app: &AppHandle) {
    let Some(state) = app.try_state::<PendingUpdate>() else { return };
    let Some((update, bytes)) = state.0.lock().unwrap().take() else { return };
    println!("[update] installing pending update before exit");
    if let Err(e) = update.install(bytes) {
        eprintln!("[update] install failed: {e}");
    }
}
