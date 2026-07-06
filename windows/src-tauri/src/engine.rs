//! Python engine lifecycle — port of AppDelegate's engine management.
//!
//! Kills any stale listener on port 2788, then spawns and supervises the
//! engine (max restarts with linear backoff, give up if it dies immediately).

use std::ffi::c_void;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt as _;
use std::path::PathBuf;
use std::process::Command;
use std::sync::OnceLock;
use std::thread;
use std::time::{Duration, Instant};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const MAX_RESTARTS: u32 = 5;
const MIN_HEALTHY_SECS: u64 = 30;

// ── Windows Job Object: ensure Python engine dies when the parent exits ───────
//
// Assigning the child to a job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE means
// the OS kills it automatically when fluent-windows.exe exits for any reason —
// including a forced kill by the NSIS installer — preventing locked DLLs during
// reinstall/update.

extern "system" {
    fn CreateJobObjectW(attrs: *mut c_void, name: *const u16) -> *mut c_void;
    fn SetInformationJobObject(job: *mut c_void, class: i32, info: *mut c_void, len: u32) -> i32;
    fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
}

// HANDLE (*mut c_void) is not Send/Sync by default; the job handle is
// process-scoped and never mutated after creation, so this is safe.
struct JobHandle(*mut c_void);
unsafe impl Send for JobHandle {}
unsafe impl Sync for JobHandle {}

const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;
const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;

#[repr(C)]
struct BasicLimitInfo {
    per_process_user_time_limit: i64,
    per_job_user_time_limit: i64,
    limit_flags: u32,
    minimum_working_set_size: usize,
    maximum_working_set_size: usize,
    active_process_limit: u32,
    affinity: usize,
    priority_class: u32,
    scheduling_class: u32,
}

#[repr(C)]
struct IoCounters {
    read_operation_count: u64,
    write_operation_count: u64,
    other_operation_count: u64,
    read_transfer_count: u64,
    write_transfer_count: u64,
    other_transfer_count: u64,
}

#[repr(C)]
struct ExtendedLimitInfo {
    basic: BasicLimitInfo,
    io_info: IoCounters,
    process_memory_limit: usize,
    job_memory_limit: usize,
    peak_process_memory_used: usize,
    peak_job_memory_used: usize,
}

static ENGINE_JOB: OnceLock<JobHandle> = OnceLock::new();

fn engine_job() -> *mut c_void {
    ENGINE_JOB
        .get_or_init(|| unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            let mut info = ExtendedLimitInfo {
                basic: BasicLimitInfo {
                    per_process_user_time_limit: 0,
                    per_job_user_time_limit: 0,
                    limit_flags: JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                    minimum_working_set_size: 0,
                    maximum_working_set_size: 0,
                    active_process_limit: 0,
                    affinity: 0,
                    priority_class: 0,
                    scheduling_class: 0,
                },
                io_info: IoCounters {
                    read_operation_count: 0,
                    write_operation_count: 0,
                    other_operation_count: 0,
                    read_transfer_count: 0,
                    write_transfer_count: 0,
                    other_transfer_count: 0,
                },
                process_memory_limit: 0,
                job_memory_limit: 0,
                peak_process_memory_used: 0,
                peak_job_memory_used: 0,
            };
            SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                &mut info as *mut _ as *mut c_void,
                std::mem::size_of::<ExtendedLimitInfo>() as u32,
            );
            JobHandle(job)
        })
        .0
}

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
    let out = Command::new("netstat").args(["-ano"]).creation_flags(CREATE_NO_WINDOW).output();
    if let Ok(out) = out {
        let text = String::from_utf8_lossy(&out.stdout);
        let needle = format!(":{port}");
        for line in text.lines() {
            if line.contains(&needle) && line.to_uppercase().contains("LISTENING") {
                if let Some(pid) = line.split_whitespace().last() {
                    if pid.chars().all(|c| c.is_ascii_digit()) && pid != "0" {
                        let _ = Command::new("taskkill").args(["/PID", pid, "/F"]).creation_flags(CREATE_NO_WINDOW).output();
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
                .current_dir(&engine_dir)
                .creation_flags(CREATE_NO_WINDOW);
            if let Some(log) = log {
                let err = log.try_clone().ok();
                cmd.stdout(log);
                if let Some(err) = err {
                    cmd.stderr(err);
                }
            }

            match cmd.spawn() {
                Ok(mut child) => {
                    unsafe { AssignProcessToJobObject(engine_job(), child.as_raw_handle()); }
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
