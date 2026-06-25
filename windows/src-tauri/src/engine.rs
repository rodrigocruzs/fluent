//! Python engine lifecycle — port of AppDelegate's engine management.
//!
//! Kills any stale listener on port 2788, then spawns and supervises the
//! engine (max restarts with linear backoff, give up if it dies immediately).

use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

const MAX_RESTARTS: u32 = 5;
const MIN_HEALTHY_SECS: u64 = 30;

/// Locate the engine directory and its venv Python.
///
/// Production (installed): the pre-built bundle ships as a Tauri resource at
/// `<resource_dir>/engine-bundle/` (see bundle-engine.mjs + tauri.conf
/// bundle.resources), with venv\Scripts\python.exe + main.py inside.
/// Dev: the M2 venv at repo/fluent-engine/venv, resolved relative to the crate
/// or the current dir.
fn engine_paths(app: &tauri::AppHandle) -> Option<(PathBuf, PathBuf)> {
    use tauri::Manager;

    let mut candidates: Vec<PathBuf> = Vec::new();

    // Production: the bundled engine resource. resource_dir() points at the
    // installed resources root; bundle-engine.mjs stages everything under
    // engine-bundle/.
    if let Ok(res) = app.path().resource_dir() {
        candidates.push(res.join("engine-bundle"));
    }

    // Dev fallbacks: the repo's fluent-engine with its M2 venv.
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fluent-engine"));
    candidates.push(std::env::current_dir().unwrap_or_default().join("fluent-engine"));
    candidates.push(std::env::current_dir().unwrap_or_default().join("../fluent-engine"));

    for engine_dir in candidates {
        let py = engine_dir.join("venv").join("Scripts").join("python.exe");
        let main = engine_dir.join("main.py");
        if py.exists() && main.exists() {
            return Some((py, engine_dir));
        }
    }
    None
}

/// Kill any process currently listening on the engine port (Windows).
/// Equivalent to AppDelegate.killProcessOnPort via lsof on macOS.
fn kill_stale_listener(port: u16) {
    // `netstat -ano` lists "...:port ... LISTENING <pid>"; pull the PIDs and
    // taskkill them. Best-effort: ignore all errors.
    let out = Command::new("netstat").args(["-ano"]).output();
    if let Ok(out) = out {
        let text = String::from_utf8_lossy(&out.stdout);
        let needle = format!(":{port}");
        for line in text.lines() {
            if line.contains(&needle) && line.to_uppercase().contains("LISTENING") {
                if let Some(pid) = line.split_whitespace().last() {
                    if pid.chars().all(|c| c.is_ascii_digit()) && pid != "0" {
                        let _ = Command::new("taskkill").args(["/PID", pid, "/F"]).output();
                    }
                }
            }
        }
    }
}

/// Spawn the engine and keep it alive on a background thread.
pub fn spawn_and_supervise(app: tauri::AppHandle) {
    thread::spawn(move || {
        let (py, engine_dir) = match engine_paths(&app) {
            Some(p) => p,
            None => {
                eprintln!("[engine] could not locate python + main.py; engine not started");
                return;
            }
        };
        let log_path = std::env::temp_dir().join("fluent-engine.log");

        let mut restarts = 0u32;
        loop {
            kill_stale_listener(crate::engine_port());

            let log = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)
                .ok();

            let started = Instant::now();
            println!("[engine] starting {} (attempt {})", py.display(), restarts + 1);

            let mut cmd = Command::new(&py);
            cmd.arg(engine_dir.join("main.py"))
                .current_dir(&engine_dir);
            if let Some(log) = log {
                let err = log.try_clone().ok();
                cmd.stdout(log);
                if let Some(err) = err {
                    cmd.stderr(err);
                }
            }

            match cmd.spawn() {
                Ok(mut child) => {
                    let _ = child.wait();
                }
                Err(e) => {
                    eprintln!("[engine] failed to spawn: {e}");
                }
            }

            // Supervision policy (ported from AppDelegate.handleEngineExit):
            // give up if it keeps dying, and cap restarts when it dies fast.
            let alive = started.elapsed().as_secs();
            if alive >= MIN_HEALTHY_SECS {
                restarts = 0; // it ran healthily; reset the counter
            } else {
                restarts += 1;
                if restarts > MAX_RESTARTS {
                    eprintln!("[engine] exceeded {MAX_RESTARTS} fast restarts; giving up");
                    return;
                }
            }
            let backoff = Duration::from_secs(2 * restarts as u64).max(Duration::from_secs(2));
            thread::sleep(backoff);
        }
    });
}
