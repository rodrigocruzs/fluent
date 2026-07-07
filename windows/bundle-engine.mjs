// Build the pre-built Python engine bundle that ships inside the Windows
// installer, so users never install Python themselves.
//
// Produces  windows/src-tauri/engine-bundle/  containing:
//   - venv/        a full CPython venv with the (torch-free) engine deps
//   - fluent/      the engine package source
//   - main.py      the engine entrypoint
//
// Tauri bundles engine-bundle/ as a resource (see tauri.conf.json
// bundle.resources). At runtime engine.rs resolves the bundled
// venv\Scripts\python.exe + main.py from the resource dir.
//
// Idempotent-ish: the venv is reused if present (pip install is re-run so
// requirement changes are picked up); engine source is always re-copied.
//
// Run automatically before `tauri build` (package.json prebuild). On non-
// Windows dev machines it still builds a venv for local reasoning, but the
// shipped artifact is only meaningful when built on Windows (the C-extension
// wheels — pyaudio, pyaudiowpatch — are platform-specific).

import { execFileSync } from "node:child_process";
import {
  cpSync, mkdirSync, existsSync, rmSync,
} from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { platform } from "node:os";

const here = dirname(fileURLToPath(import.meta.url));
const engineSrc = join(here, "..", "fluent-engine");
const bundle = join(here, "src-tauri", "engine-bundle");
const venv = join(bundle, "venv");

const isWindows = platform() === "win32";
// Windows: python.exe sits at the top of venv/, mirroring a standalone
// CPython install copy (see basePython/venv-creation below) rather than a
// venv's Scripts/ subfolder.
const venvPython = isWindows
  ? join(venv, "python.exe")
  : join(venv, "bin", "python");

function run(cmd, args, opts = {}) {
  console.log(`[bundle-engine] $ ${cmd} ${args.join(" ")}`);
  execFileSync(cmd, args, { stdio: "inherit", ...opts });
}

// Pick a base Python 3.10+ to create the venv from.
//
// FLUENT_BASE_PYTHON pins an exact interpreter and takes precedence. CI must
// set it: on Windows the `py -3` launcher resolves to the NEWEST installed
// Python (e.g. 3.14) regardless of PATH, and pyaudio/pyaudiowpatch have no
// prebuilt wheels there — the venv must be built from a version that does.
function basePython() {
  const pinned = process.env.FLUENT_BASE_PYTHON;
  if (pinned) {
    execFileSync(pinned, ["--version"], { stdio: "ignore" });
    return { cmd: pinned, pre: [] };
  }
  const candidates = isWindows
    ? ["py", "python", "python3"]
    : ["python3", "python"];
  for (const c of candidates) {
    try {
      const args = c === "py" ? ["-3", "--version"] : ["--version"];
      execFileSync(c, args, { stdio: "ignore" });
      return c === "py" ? { cmd: "py", pre: ["-3"] } : { cmd: c, pre: [] };
    } catch { /* try next */ }
  }
  throw new Error(
    "[bundle-engine] No Python 3 found. Install Python 3.10+ and retry."
  );
}

mkdirSync(bundle, { recursive: true });

// 1. Create the venv if missing.
if (!existsSync(venvPython)) {
  const base = basePython();
  if (isWindows) {
    // Windows venvs (3.11+) don't copy a working interpreter: Scripts\
    // python.exe is a small redirecting launcher that reads pyvenv.cfg's
    // `home` key and re-execs the *base* interpreter at that path — it
    // never runs standalone. `home` gets baked in at creation time, which
    // in CI is the ephemeral setup-python hostedtoolcache path (see
    // FLUENT_BASE_PYTHON below); that path doesn't exist on end-user
    // machines, so a shipped venv fails instantly with "No Python at
    // '<path>'" and the engine never starts. Ship a full standalone copy
    // of the base interpreter directory instead — an ordinary CPython
    // install (unlike a venv redirector) is self-contained and safe to
    // relocate to any machine.
    const baseExe = execFileSync(
      base.cmd,
      [...base.pre, "-c", "import sys; print(sys.executable)"],
    ).toString().trim();
    const baseDir = dirname(baseExe);
    console.log(`[bundle-engine] copying base interpreter from ${baseDir}`);
    mkdirSync(venv, { recursive: true });
    cpSync(baseDir, venv, {
      recursive: true,
      // Skip the base install's own Scripts/ (pip.exe etc. from CI's
      // preinstalled set) and site-packages (CI's preinstalled packages) —
      // we install our own deps fresh into this copy below.
      filter: (src) => {
        const rel = relative(baseDir, src);
        return rel !== "Scripts" && rel !== join("Lib", "site-packages");
      },
    });
  } else {
    run(base.cmd, [...base.pre, "-m", "venv", venv]);
  }
}

// 2. Install the torch-free engine deps into the venv.
//    common = anthropic, pyaudio, httpx ; win = pyaudiowpatch, keyring.
//    The copied base install has no site-packages (excluded above, to skip
//    the base's own preinstalled packages), so pip isn't importable yet —
//    ensurepip bootstraps it from CPython's bundled wheels (stdlib-only, no
//    network needed). A real venv (non-Windows path) already has pip from
//    `python -m venv`'s own bootstrap; ensurepip here is a harmless no-op.
run(venvPython, ["-m", "ensurepip", "--upgrade"]);
run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
run(venvPython, [
  "-m", "pip", "install",
  "-r", join(engineSrc, "requirements-common.txt"),
  ...(isWindows ? ["-r", join(engineSrc, "requirements-win.txt")] : []),
]);

// 3. Stage the engine source into the bundle (always refresh).
//    Filter out non-engine cruft that lives alongside the package on disk
//    (stray Xcode project, caches, OS metadata) so it never ships.
const EXCLUDE = new Set([
  "__pycache__", ".DS_Store", "Fluent", "Fluent.xcodeproj",
  "project.yml", ".pytest_cache",
]);
const keep = (src) => {
  const base = src.split(/[\\/]/).pop();
  if (EXCLUDE.has(base)) return false;
  if (base.endsWith(".pyc")) return false;
  return true;
};
for (const item of ["fluent", "main.py"]) {
  const dest = join(bundle, item);
  if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
  cpSync(join(engineSrc, item), dest, { recursive: true, filter: keep });
}

console.log(`[bundle-engine] engine bundle ready at ${bundle}`);
if (!isWindows) {
  console.warn(
    "[bundle-engine] WARNING: built on a non-Windows host. The C-extension " +
    "wheels (pyaudio, pyaudiowpatch) are platform-specific — build the " +
    "shippable bundle on Windows."
  );
}
