# Bundled Python Runtime — Design

**Date:** 2026-07-17
**Status:** Approved (approach); spec pending review

## Problem

First launch on a non-developer Mac fails. `setup_engine.sh` searches the user's
machine for a system Python 3.10+ and exits with `EXIT_NO_PYTHON` when none
exists, which is the normal state of a consumer Mac — the app then shows the
"Python is required" dialog and sends the user to python.org.

The failure is deeper than the dialog:

1. **No Python 3.10+** on a stock Mac → dialog on first launch.
2. **PyAudio has no prebuilt macOS wheel.** Even after installing Python from
   python.org, `pip install pyaudio` compiles from source, which requires the
   Xcode Command Line Tools *and* Homebrew's portaudio. On the dev machine the
   compiled `_portaudio.so` links `/opt/homebrew/opt/portaudio/lib/libportaudio.2.dylib`.
   A normal user hits `EXIT_PIP_FAILED` ("Couldn't finish setup") instead.
3. Even when setup succeeds, first run needs a network connection and several
   minutes of pip downloads.

Net: onboarding currently only works on developer machines with Homebrew.

## Decision

Ship a self-contained CPython runtime **inside Fluent.app** and run the engine
from the bundle. First launch becomes instant, offline, and dialog-free. The
system-Python discovery, venv, pip install, sentinel, and setup-progress UI are
all removed.

Alternatives considered and rejected:

- **PyInstaller-frozen engine** — same payoff, higher risk (pyobjc under
  PyInstaller is fragile; field debugging harder). Fallback if runtime signing
  proves unworkable (it shouldn't — Blender et al. ship embedded Python).
- **Download runtime at first launch** — preserves the network-dependent
  first-run failure class this design eliminates.
- **Swift port of the engine** — best long-term end state on Mac (pairs with
  the ScreenCaptureKit capture migration) but a multi-week rewrite, and the
  planned Windows port shares the Python core. Not the onboarding fix.

## Architecture

### Current

```
Fluent.app/Contents/Resources/fluent-engine/   ← engine source (folder ref in pbxproj)
~/.fluent/engine/venv/                          ← per-user venv built by setup_engine.sh
~/.fluent/engine/                               ← rsync'd copy of engine source (for Launch Agent)
~/.fluent/engine/.engine-ready                  ← sentinel gating startEngine()
```

- App-spawned engine: `~/.fluent/engine/venv/bin/python3 <bundle>/fluent-engine/main.py`,
  cwd = bundle engine dir (`AppDelegate.startEngine()`).
- Launch Agent (`com.fluent.engine`, best-effort fallback): venv python running
  `~/.fluent/engine/main.py`.

### Target

```
Fluent.app/Contents/Resources/engine-runtime/   ← relocatable CPython 3.12 + all deps (new)
Fluent.app/Contents/Resources/fluent-engine/    ← engine source (unchanged, pruned of junk)
~/.fluent/                                      ← config.json, reports/, recordings/ (unchanged)
```

- App-spawned engine: `<bundle>/engine-runtime/bin/python3 <bundle>/fluent-engine/main.py`,
  cwd = bundle engine dir. Env: `PYTHONNOUSERSITE=1` (no leakage from the
  user's `~/.local` site-packages), `PYTHONDONTWRITEBYTECODE=1` (the bundle is
  read-only and codesigned; nothing may write into it).
- Launch Agent: same interpreter/paths, resolved from `Bundle.main` at runtime
  so non-`/Applications` installs still work. Written by Swift (see below).
- `~/.fluent/engine/` (venv + copied source + sentinel) is deleted by a
  one-time migration; user data in `~/.fluent` is untouched.

Engine source continues to run from the bundle, so engine code can never drift
from the app version — the same now becomes true of the interpreter and deps.

## Components

### 1. Runtime assembly — `scripts/build_engine_runtime.sh` (new)

Build-time script, run by `release.sh` (cached output under `build/engine-runtime/`):

1. Download a **pinned** python-build-standalone release
   (`cpython-3.12.x-aarch64-apple-darwin-install_only_stripped.tar.gz` — the app
   is arm64-only) and verify its SHA-256. Cache the tarball.
2. Install deps directly into the runtime's `site-packages` (no venv — the
   runtime is private): `requirements-common.txt` + `requirements-mac.txt`.
3. **PyAudio:** `pip wheel pyaudio` on the build machine (Homebrew portaudio
   present), then repair with `delocate-wheel` so `libportaudio.2.dylib` is
   vendored into the wheel and the extension links it via `@loader_path`.
   Install the repaired wheel. Fail the build if the vendored dylib's minimum
   OS version exceeds the app's deployment target (14.0); if that ever happens,
   compile portaudio from source with `MACOSX_DEPLOYMENT_TARGET=14.0`.
4. Prune: strip `pip`/`setuptools`/`wheel`, `tests`/`test` dirs, `__pycache__`;
   then `python -m compileall` the tree once (read-only bundle can't write
   `.pyc` later).
5. **Gate:** scan every Mach-O in the runtime with `otool -L` and fail if any
   references `/opt/homebrew`, `/usr/local`, or any absolute path outside the
   runtime and system libraries. This is the automated stand-in for a
   clean-machine test.
6. Import-check the critical modules (`anthropic`, `pyaudio`, `httpx`, the
   pyobjc frameworks) using the assembled runtime itself, with `PATH` and
   `PYTHONPATH` stripped.
7. Write a manifest (Python version, PBS release, package versions) into the
   runtime dir.

Requirements cleanup: move `pytest` from `requirements-common.txt` into a new
`requirements-dev.txt` so test-only deps aren't shipped.

### 2. Release pipeline — `release.sh`

After `xcodebuild`, before app signing:

1. Run `scripts/build_engine_runtime.sh` (no-op when cached and requirements
   unchanged), `ditto` output into `$APP_PATH/Contents/Resources/engine-runtime`.
2. Prune the bundled `Resources/fluent-engine` of non-runtime junk the folder
   reference drags in (`__pycache__`, `tests/`, stray Xcode/build artifacts).
3. **Sign nested binaries first:** find every `.so`, `.dylib`, and executable
   in `engine-runtime` and codesign each with `--force --options runtime
   --timestamp` and the same Developer ID identity. No extra entitlements —
   extensions are signed with the same Team ID, so hardened-runtime library
   validation passes.
4. Existing app signing, notarization, DMG, and Sparkle steps run on top.
   One check during implementation: the current `codesign --deep --force` app
   pass must not clobber the nested signatures incorrectly — if it does,
   switch to the canonical inside-out order (sign nested binaries, then the
   app bundle without `--deep`).

No pbxproj change (it's hand-edited and fragile per `project.yml`'s warnings);
the runtime is injected post-build by `release.sh`.

### 3. App — `AppDelegate.swift`

- `startEngine()` resolves the interpreter:
  1. `Bundle.main.resourceURL/engine-runtime/bin/python3` (release builds);
  2. legacy `~/.fluent/engine/venv/bin/python3` as a dev-only fallback
     (Xcode Debug builds don't carry the runtime), with a log line;
  3. neither → log error, no dialog.
- Delete: `findSystemPython()`, `isPython310Plus()`, `showPythonMissing()`,
  `runEngineSetup()`, `showSetupFailed()`, the sentinel check, and
  `EngineSetupWindowController` (setup is now instant; there is no progress to
  show). `setup_engine.sh` is deleted.
- **Launch Agent management moves into Swift.** On every launch, compute the
  desired plist (bundle-resolved interpreter + `main.py` paths, same
  `com.fluent.engine` label, `RunAtLoad`/`KeepAlive` as today); if it differs
  from the installed one, rewrite it and `bootout`/`bootstrap` the agent. This
  self-heals across app moves and Sparkle updates.
- **One-time migration:** only when the bundled runtime is present (i.e.
  release builds — Debug builds must keep the legacy venv their fallback uses):
  if `~/.fluent/engine/` exists (venv, rsync'd source, sentinel), bootout the
  old agent, delete that directory (~85 MB of
  app-managed cache — never touches `config.json`, `reports/`, `recordings/`),
  and let the normal flow install the new plist.

## Error handling

- Runtime missing from a release bundle would be a packaging bug; `release.sh`
  fails the build if the import-check gate didn't run. At app level it logs
  and falls back as above rather than showing a dialog.
- Engine crash/restart behavior (back-off, port-2788 cleanup) is unchanged.
- The Launch-Agent-spawned engine's TCC/microphone attribution is unchanged
  from today (pre-existing caveat, out of scope; the app-spawned engine
  inherits the app's mic permission as before).

## Size

Estimates to be confirmed during implementation: stripped CPython ≈ 30 MB +
deps ≈ 80 MB unpacked (pyobjc dominates); roughly +35–45 MB compressed in the
DMG and Sparkle zip. Acceptable for a desktop app on a daily update cadence.

## Testing

- Assembly gates (steps 5–6 above) run on every release build.
- `codesign --verify --deep --strict` + notarization already in `release.sh`.
- Manual: fresh-user-account run with `PATH` stripped; ideally one true
  clean-machine (VM or friend's Mac) validation of the first release.
- Engine pytest suite runs under the assembled runtime
  (`build/engine-runtime/python/bin/python3 -m pytest`) to prove dep parity.

## Out of scope / future

- **Windows:** same idea via the CPython embeddable distribution +
  `pyaudiowpatch` wheels (which do ship prebuilt); noted for the Windows port.
- **Swift engine port / ScreenCaptureKit capture:** unchanged long-term
  direction; this design shrinks with it (the runtime disappears when the
  engine does).
- Trimming pyobjc further or lazy-downloading optional deps — YAGNI until size
  is a demonstrated problem.
