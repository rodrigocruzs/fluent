# Bundled Python Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a self-contained CPython runtime inside Fluent.app so first launch never depends on the user's machine having Python, Homebrew, or a compiler.

**Architecture:** A build-time script assembles a relocatable CPython 3.12 (python-build-standalone) with all engine deps pre-installed and libportaudio vendored; `release.sh` injects it into `Fluent.app/Contents/Resources/engine-runtime` and signs every nested binary before the existing app-signing pass. `AppDelegate.swift` launches the engine with the bundled interpreter, manages the Launch Agent itself, and migrates old venv installs. All first-launch setup machinery (system-Python discovery, venv, pip, progress UI) is deleted.

**Tech Stack:** bash, python-build-standalone, delocate, codesign/notarytool, Swift/AppKit.

**Spec:** `docs/superpowers/specs/2026-07-17-bundled-python-runtime-design.md`

## Global Constraints

- App is **arm64-only**, deployment target **macOS 14.0**. Every Mach-O shipped in the runtime must have `minos` ≤ 14.0 (Homebrew's portaudio bottle is minos 15.0 — that's why portaudio is built from source).
- Pinned inputs (exact values, verified by SHA-256 in the script):
  - CPython: `cpython-3.12.13+20260623-aarch64-apple-darwin-install_only_stripped.tar.gz`, sha256 `41df7d3ae4757e84b97874f76d634268456aaa271740d33f968d826374998fb7`
  - portaudio: `v19.7.0` GitHub tag tarball, sha256 `5af29ba58bbdbb7bbcefaaecc77ec8fc413f0db6f4c4e286c40c3e1b83174fa0`
  - `pyaudio==0.2.14`
- No Mach-O in the runtime may load anything outside `@rpath`/`@loader_path`/`@executable_path`/`/usr/lib`/`/System` (automated gate; this is the clean-machine guarantee).
- The app bundle is read-only and codesigned: every engine spawn sets `PYTHONNOUSERSITE=1` and `PYTHONDONTWRITEBYTECODE=1`.
- Never run `xcodegen generate` (see warnings at top of `fluent/project.yml`); edit `project.pbxproj` surgically.
- Signing order is inside-out: sign runtime binaries first, then the existing `codesign --deep` app pass seals them as resources. Signing runtime binaries *after* the app pass breaks the resource seal.
- Repo conventions: commit messages like `feat(app): …` / `build(release): …`; `build/` is already gitignored (root `.gitignore` has `build/`).

---

### Task 1: Move test-only deps out of shipped requirements

`requirements-common.txt` currently ships `pytest` to every user. Split it into a dev-only file so the bundled runtime doesn't carry test deps.

**Files:**
- Modify: `fluent-engine/requirements-common.txt`
- Create: `fluent-engine/requirements-dev.txt`

**Interfaces:**
- Produces: `requirements-common.txt` + `requirements-mac.txt` = exactly what Task 2 installs into the runtime; `requirements-dev.txt` = extra deps for running the test suite.

- [ ] **Step 1: Edit `fluent-engine/requirements-common.txt`** — remove the `pytest>=8.0` line so the file reads:

```
# Cross-platform engine dependencies (macOS + Windows).
# Installed on every platform alongside the OS-specific requirements file.
# Transcription is cloud-based (Deepgram via the backend) — no local ML.
# Test-only deps live in requirements-dev.txt.
anthropic>=0.28.0
pyaudio>=0.2.14
httpx>=0.27.0
```

- [ ] **Step 2: Create `fluent-engine/requirements-dev.txt`:**

```
# Dev/test-only dependencies — never shipped in the app bundle.
# Install with: pip install -r requirements.txt -r requirements-dev.txt
pytest>=8.0
```

- [ ] **Step 3: Verify the dev venv still runs tests** (the existing `~/.fluent/engine/venv` already has pytest installed; this just confirms nothing else referenced the moved line):

Run: `grep -rn "pytest" fluent-engine/requirements*.txt`
Expected: only `requirements-dev.txt` mentions pytest.

- [ ] **Step 4: Commit**

```bash
git add fluent-engine/requirements-common.txt fluent-engine/requirements-dev.txt
git commit -m "build(engine): move pytest to requirements-dev.txt so it isn't shipped"
```

---

### Task 2: Runtime assembly script

**Files:**
- Create: `scripts/build_engine_runtime.sh`

**Interfaces:**
- Produces: `build/engine-runtime/` — a relocatable CPython whose `bin/python3` can run `fluent-engine/main.py` with zero external deps. Contains `MANIFEST.txt` (versions) and `.stamp` (cache key). Task 3's `bundle_engine_runtime_into_app.sh` copies this directory verbatim.
- Env flags: `FORCE=1` rebuilds despite cache; `SKIP_ENGINE_TESTS=1` skips the pytest gate.

- [ ] **Step 1: Write `scripts/build_engine_runtime.sh`** with this exact content, then `chmod +x` it:

```bash
#!/usr/bin/env bash
# Assembles the self-contained Python runtime that release.sh bundles into
# Fluent.app (Contents/Resources/engine-runtime).
# See docs/superpowers/specs/2026-07-17-bundled-python-runtime-design.md.
#
# Output:  build/engine-runtime/   (relocatable CPython + engine deps)
# Re-runs are no-ops unless this script or the requirements change.
#   FORCE=1             rebuild even when cached
#   SKIP_ENGINE_TESTS=1 skip the pytest gate (debug escape hatch)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_SRC="$REPO_ROOT/fluent-engine"
OUT="$REPO_ROOT/build/engine-runtime"
CACHE="$REPO_ROOT/build/engine-runtime-cache"
STAMP="$OUT/.stamp"

# ── Pinned inputs ─────────────────────────────────────────────────────────────
PBS_TAG="20260623"
PBS_PY="3.12.13"
PBS_NAME="cpython-${PBS_PY}+${PBS_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_NAME}"
PBS_SHA256="41df7d3ae4757e84b97874f76d634268456aaa271740d33f968d826374998fb7"

PA_VERSION="19.7.0"
PA_NAME="portaudio-${PA_VERSION}.tar.gz"
PA_URL="https://github.com/PortAudio/portaudio/archive/refs/tags/v${PA_VERSION}.tar.gz"
PA_SHA256="5af29ba58bbdbb7bbcefaaecc77ec8fc413f0db6f4c4e286c40c3e1b83174fa0"

PYAUDIO_VERSION="0.2.14"

# Must match the app's MACOSX_DEPLOYMENT_TARGET (fluent/project.yml).
# The min-OS gate below enforces it on every shipped Mach-O.
export MACOSX_DEPLOYMENT_TARGET="14.0"

stamp_value() {
    shasum -a 256 "$0" \
        "$ENGINE_SRC/requirements-common.txt" \
        "$ENGINE_SRC/requirements-mac.txt" | shasum -a 256 | cut -d' ' -f1
}

if [ "${FORCE:-0}" != "1" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$(stamp_value)" ]; then
    echo "[runtime] up to date ($OUT) — FORCE=1 to rebuild"
    exit 0
fi

rm -rf "$OUT"
mkdir -p "$OUT" "$CACHE"

fetch() { # <url> <sha256> <dest>
    local url="$1" sha="$2" dest="$3"
    if [ ! -f "$dest" ] || ! echo "$sha  $dest" | shasum -a 256 -c - >/dev/null 2>&1; then
        echo "[runtime] downloading $(basename "$dest") ..."
        curl -fL --retry 3 -o "$dest" "$url"
    fi
    echo "$sha  $dest" | shasum -a 256 -c - >/dev/null \
        || { echo "[runtime] ERROR: checksum mismatch for $dest" >&2; exit 1; }
}

# ── 1. Relocatable CPython ────────────────────────────────────────────────────
fetch "$PBS_URL" "$PBS_SHA256" "$CACHE/$PBS_NAME"
tar -xzf "$CACHE/$PBS_NAME" -C "$OUT" --strip-components=1   # tarball root: python/
PY="$OUT/bin/python3"
echo "[runtime] $("$PY" -V)"
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade

# ── 2. portaudio from source ──────────────────────────────────────────────────
# Homebrew's bottle has minos 15.0 (> app target 14.0), so build our own.
fetch "$PA_URL" "$PA_SHA256" "$CACHE/$PA_NAME"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PA_PREFIX="$WORK/portaudio-prefix"
tar -xzf "$CACHE/$PA_NAME" -C "$WORK"
echo "[runtime] building portaudio $PA_VERSION ..."
(
    cd "$WORK/portaudio-$PA_VERSION"
    ./configure --prefix="$PA_PREFIX" --disable-static \
        CFLAGS="-arch arm64 -mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
        LDFLAGS="-arch arm64" >/dev/null
    make -j"$(sysctl -n hw.ncpu)" >/dev/null
    make install >/dev/null
)

# ── 3. PyAudio wheel, repaired so libportaudio is vendored ───────────────────
# Tooling (delocate, pytest) goes into a throwaway --target dir, NOT the
# runtime's site-packages — pip can't cleanly uninstall transitive deps, and
# some (typing-extensions) are shared with real runtime deps.
TOOLS="$WORK/tools"
"$PY" -m pip install --quiet --target "$TOOLS" delocate pytest
WHEELS="$WORK/wheels"
echo "[runtime] building PyAudio wheel ..."
CFLAGS="-I$PA_PREFIX/include" LDFLAGS="-L$PA_PREFIX/lib" ARCHFLAGS="-arch arm64" \
    "$PY" -m pip wheel --quiet "pyaudio==$PYAUDIO_VERSION" \
    --no-deps --no-binary :all: -w "$WHEELS"
PYTHONPATH="$TOOLS" "$TOOLS/bin/delocate-wheel" -w "$WHEELS/repaired" "$WHEELS"/[Pp]y[Aa]udio*.whl
"$PY" -m pip install --quiet "$WHEELS/repaired"/[Pp]y[Aa]udio*.whl

# ── 4. Engine dependencies ────────────────────────────────────────────────────
echo "[runtime] installing engine deps ..."
"$PY" -m pip install --quiet \
    -r "$ENGINE_SRC/requirements-common.txt" \
    -r "$ENGINE_SRC/requirements-mac.txt"

# ── 5. Engine test suite under the assembled runtime ─────────────────────────
if [ "${SKIP_ENGINE_TESTS:-0}" != "1" ]; then
    echo "[runtime] running engine tests under the assembled runtime ..."
    (cd "$ENGINE_SRC" && PYTHONPATH="$TOOLS" "$PY" -m pytest tests -q)
fi

# ── 6. Manifest (before pip is pruned) ───────────────────────────────────────
{
    echo "python: $("$PY" -V 2>&1) (python-build-standalone $PBS_TAG)"
    echo "portaudio: $PA_VERSION (source build, min macOS $MACOSX_DEPLOYMENT_TARGET)"
    "$PY" -m pip freeze
} > "$OUT/MANIFEST.txt"

# ── 7. Prune ──────────────────────────────────────────────────────────────────
"$PY" -m pip uninstall --quiet -y pip setuptools wheel 2>/dev/null || true
rm -f "$OUT"/bin/pip* "$OUT"/bin/wheel* "$OUT"/bin/idle* "$OUT"/bin/pydoc*
find "$OUT/lib" -type d \( -name tests -o -name test -o -name __pycache__ \) \
    -prune -exec rm -rf {} +

# ── 8. Precompile (the bundle is read-only at runtime) ───────────────────────
"$PY" -m compileall -q "$OUT/lib"

# ── 9. Portability + min-OS gate ─────────────────────────────────────────────
echo "[runtime] scanning Mach-O files ..."
BAD=0
while IFS= read -r -d '' f; do
    file -b "$f" | grep -q "Mach-O" || continue
    while IFS= read -r dep; do
        case "$dep" in
            @rpath/*|@loader_path/*|@executable_path/*|/usr/lib/*|/System/*) ;;
            *) echo "[runtime] BAD LINK: $f -> $dep"; BAD=1 ;;
        esac
    done < <(otool -l "$f" \
        | awk '/cmd LC_(LOAD_DYLIB|LOAD_WEAK_DYLIB|REEXPORT_DYLIB)/{grab=1}
               grab && $1=="name"{print $2; grab=0}')
    minos=$(otool -l "$f" | awk '/minos/{print $2; exit}')
    if [ -n "${minos:-}" ] && \
       [ "$(printf '%s\n' "$minos" "$MACOSX_DEPLOYMENT_TARGET" | sort -V | tail -1)" \
         != "$MACOSX_DEPLOYMENT_TARGET" ]; then
        echo "[runtime] BAD MIN-OS ($minos > $MACOSX_DEPLOYMENT_TARGET): $f"; BAD=1
    fi
done < <(find "$OUT" -type f \( -perm -111 -o -name '*.so' -o -name '*.dylib' \) -print0)
[ "$BAD" = "0" ] || { echo "[runtime] ERROR: portability gate failed" >&2; exit 1; }

# ── 10. Import check with a stripped environment ─────────────────────────────
echo "[runtime] import check (clean env) ..."
(cd / && env -i HOME=/tmp PATH=/usr/bin:/bin "$PY" - <<'PYCHECK'
import sys
mods = ["anthropic", "pyaudio", "httpx", "AVFoundation", "CoreAudio", "Cocoa"]
missing = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        missing.append(f"{m}: {e}")
if missing:
    sys.stderr.write("Import check failed:\n" + "\n".join(missing) + "\n")
    sys.exit(1)
PYCHECK
)

stamp_value > "$STAMP"
echo "[runtime] done: $OUT ($(du -sh "$OUT" | cut -f1))"
```

- [ ] **Step 2: Make it executable and run it**

Run: `chmod +x scripts/build_engine_runtime.sh && bash scripts/build_engine_runtime.sh`
Expected: downloads both tarballs, builds portaudio and the PyAudio wheel, engine tests pass, both gates pass, ends with `[runtime] done: .../build/engine-runtime (~110M)`. If the pytest gate fails for a reason unrelated to this work (pre-existing test breakage), verify the same failure exists under the dev venv before deciding anything — do not silently `SKIP_ENGINE_TESTS=1`.

- [ ] **Step 3: Verify the cache short-circuit**

Run: `bash scripts/build_engine_runtime.sh`
Expected: single line `[runtime] up to date (...) — FORCE=1 to rebuild`, exits 0 instantly.

- [ ] **Step 4: Spot-check the vendored portaudio**

Run: `otool -L build/engine-runtime/lib/python3.12/site-packages/pyaudio/_portaudio*.so`
Expected: a `@loader_path/…/.dylibs/libportaudio…` reference (delocate vendors libs into a `.dylibs` dir inside the package); **no** `/opt/homebrew` or absolute build paths.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_engine_runtime.sh
git commit -m "build(engine): script to assemble the self-contained Python runtime"
```

---

### Task 3: Inject + sign the runtime in the release pipeline

**Files:**
- Create: `scripts/bundle_engine_runtime_into_app.sh`
- Modify: `release.sh` (insert after the build step, currently after line 92 `echo "==> Built: $APP_PATH"`)

**Interfaces:**
- Consumes: `build/engine-runtime/` from Task 2.
- Produces: `Fluent.app/Contents/Resources/engine-runtime/bin/python3` — the path Task 4's `enginePython()` resolves; a pruned `Contents/Resources/fluent-engine`.

- [ ] **Step 1: Write `scripts/bundle_engine_runtime_into_app.sh`**, then `chmod +x`:

```bash
#!/usr/bin/env bash
# Injects build/engine-runtime into a built Fluent.app and signs its binaries.
# Called by release.sh between xcodebuild and the app signing pass — the
# nested binaries must be signed BEFORE the app's codesign --deep pass seals
# Resources, or the seal breaks.
#
# Usage: bundle_engine_runtime_into_app.sh <path/to/Fluent.app> [sign-identity]
# Without an identity, binaries are ad-hoc signed — for local testing only.
set -euo pipefail

APP_PATH="${1:?usage: bundle_engine_runtime_into_app.sh <Fluent.app> [identity]}"
IDENTITY="${2:--}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_SRC="$REPO_ROOT/build/engine-runtime"
RUNTIME_DST="$APP_PATH/Contents/Resources/engine-runtime"
ENGINE_DST="$APP_PATH/Contents/Resources/fluent-engine"

[ -x "$RUNTIME_SRC/bin/python3" ] \
    || { echo "ERROR: run scripts/build_engine_runtime.sh first" >&2; exit 1; }
[ -d "$ENGINE_DST" ] \
    || { echo "ERROR: $ENGINE_DST missing — not a built Fluent.app?" >&2; exit 1; }

echo "==> Copying engine runtime into app..."
rm -rf "$RUNTIME_DST"
ditto "$RUNTIME_SRC" "$RUNTIME_DST"
rm -f "$RUNTIME_DST/.stamp"

echo "==> Pruning bundled engine source..."
# The pbxproj folder reference copies fluent-engine/ wholesale, including
# dev-only and stray content that must not ship.
rm -rf "$ENGINE_DST/tests" \
       "$ENGINE_DST/__pycache__" \
       "$ENGINE_DST/fluent/Fluent" \
       "$ENGINE_DST/fluent/Fluent.xcodeproj" \
       "$ENGINE_DST/fluent/project.yml"
rm -f  "$ENGINE_DST/setup_engine.sh" "$ENGINE_DST/install_agent.py" \
       "$ENGINE_DST/requirements-dev.txt" "$ENGINE_DST/requirements-win.txt"
find "$ENGINE_DST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$ENGINE_DST" -name '*.pyc' -delete

echo "==> Signing runtime binaries ($IDENTITY)..."
SIGN_ARGS=(--force --options runtime --sign "$IDENTITY")
[ "$IDENTITY" != "-" ] && SIGN_ARGS+=(--timestamp)
while IFS= read -r -d '' f; do
    file -b "$f" | grep -q "Mach-O" || continue
    codesign "${SIGN_ARGS[@]}" "$f"
done < <(find "$RUNTIME_DST" -type f \
    \( -perm -111 -o -name '*.so' -o -name '*.dylib' \) -print0)
echo "==> Engine runtime bundled ($(du -sh "$RUNTIME_DST" | cut -f1))."
```

- [ ] **Step 2: Wire it into `release.sh`** — insert between the build step and `# ── 2. Sign the app`:

```bash
# ── 1b. Bundle the Python engine runtime ─────────────────────────────────────
# Nested binaries are signed here, BEFORE the --deep app pass below seals
# Resources; reversing the order breaks the app's resource seal.
echo "==> Bundling engine runtime..."
bash "$REPO_ROOT/scripts/build_engine_runtime.sh"
bash "$REPO_ROOT/scripts/bundle_engine_runtime_into_app.sh" "$APP_PATH" "$SIGN_IDENTITY"
```

- [ ] **Step 3: Test against a real build without releasing.** Build Release locally, inject with the real Developer ID (signing locally is free; no notarization here):

```bash
xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Release \
    -derivedDataPath fluent/build/DerivedData SYMROOT=fluent/build/Release build 2>&1 | tail -3
APP=fluent/build/Release/Release/Fluent.app
bash scripts/bundle_engine_runtime_into_app.sh "$APP" \
    "Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)"
codesign --deep --force --options runtime --timestamp \
    --entitlements fluent/Fluent/Fluent.entitlements \
    --sign "Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
```

Expected: `bundle_engine_runtime_into_app.sh` prints the pruning and signing lines; the final verify prints `valid on disk` / `satisfies its Designated Requirement`. If the verify fails with a resource-seal error, the signing order is wrong — nested signing must precede the app pass.

- [ ] **Step 4: Spot-check one runtime binary's signature**

Run: `codesign -dv "$APP/Contents/Resources/engine-runtime/bin/python3" 2>&1 | grep -E "Authority|flags"`
Expected: `Authority=Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)` and `flags=0x10000(runtime)`.

- [ ] **Step 5: Commit**

```bash
git add scripts/bundle_engine_runtime_into_app.sh release.sh
git commit -m "build(release): bundle and sign the engine runtime inside Fluent.app"
```

---

### Task 4: AppDelegate — bundled interpreter, Launch Agent management, migration

Replace the entire first-launch setup flow in `fluent/Fluent/AppDelegate.swift`.

**Files:**
- Modify: `fluent/Fluent/AppDelegate.swift`

**Interfaces:**
- Consumes: `Contents/Resources/engine-runtime/bin/python3` (Task 3), `Contents/Resources/fluent-engine/main.py` (existing).
- Produces: `enginePython() -> String?`, `migrateLegacyEngineIfNeeded()`, `installEngineLaunchAgentIfNeeded()`. Engine spawns carry `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`. Optional env override `FLUENT_ENGINE_PYTHON` for dev.

- [ ] **Step 1: Delete the setup machinery.** Remove from `AppDelegate.swift`:
  - Properties `engineSetupProcess` and `setupWindowController` (lines 9, 11).
  - The `engineReadySentinel` computed property (lines 20–26) and its doc comment.
  - The `EngineSetupError` enum (lines 28–34) and its comment.
  - Functions: `setupEngineIfNeeded()`, `runEngineSetup()`, `findSystemPython()`, `isPython310Plus(_:)`, `showSetupProgress()`, `dismissSetupWindow()`, `showPythonMissing()`, `showSetupFailed(_:)` (lines 73–222 region — everything between `// MARK: - Engine setup & launch` and `private func startEngine()` except what Step 2 adds back).

- [ ] **Step 2: Add the new engine-lifecycle code** in place of the deleted block:

```swift
    // MARK: - Engine runtime

    private static let engineAgentLabel = "com.fluent.engine"

    private var engineAgentPlistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(Self.engineAgentLabel).plist")
    }

    private var bundledEnginePython: String? {
        guard let path = Bundle.main.resourceURL?
            .appendingPathComponent("engine-runtime/bin/python3").path,
            FileManager.default.isExecutableFile(atPath: path) else { return nil }
        return path
    }

    /// Interpreter resolution: dev override → bundled runtime (release builds)
    /// → legacy venv (Debug builds on dev machines, where the bundled runtime
    /// isn't in the Xcode-built bundle).
    private func enginePython() -> String? {
        if let override = ProcessInfo.processInfo.environment["FLUENT_ENGINE_PYTHON"],
           FileManager.default.isExecutableFile(atPath: override) {
            print("[Fluent] using FLUENT_ENGINE_PYTHON override: \(override)")
            return override
        }
        if let bundled = bundledEnginePython { return bundled }
        let legacy = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine/venv/bin/python3").path
        if FileManager.default.isExecutableFile(atPath: legacy) {
            print("[Fluent] bundled runtime missing — using legacy venv python (dev build)")
            return legacy
        }
        return nil
    }

    /// One-time cleanup of the pre-bundled-runtime install (venv + rsync'd
    /// engine + sentinel). Only runs when this build actually carries the
    /// bundled runtime — Debug builds still rely on the venv.
    /// Never touches user data (~/.fluent/config.json, reports/, recordings/).
    private func migrateLegacyEngineIfNeeded() {
        guard bundledEnginePython != nil else { return }
        let legacyDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/engine")
        guard FileManager.default.fileExists(atPath: legacyDir.path) else { return }
        runLaunchctl(["bootout", "gui/\(getuid())/\(Self.engineAgentLabel)"])
        try? FileManager.default.removeItem(at: legacyDir)
        print("[Fluent] migrated: removed legacy engine install at ~/.fluent/engine")
    }

    /// The agent runs the bundled runtime against the bundled engine source —
    /// release builds only (Debug builds return nil and leave any agent as-is).
    private func desiredEngineAgentPlistData() -> Data? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let python = resources.appendingPathComponent("engine-runtime/bin/python3")
        let mainPy = resources.appendingPathComponent("fluent-engine/main.py")
        guard FileManager.default.isExecutableFile(atPath: python.path),
              FileManager.default.fileExists(atPath: mainPy.path) else { return nil }
        let plist: [String: Any] = [
            "Label": Self.engineAgentLabel,
            "ProgramArguments": [python.path, mainPy.path],
            "RunAtLoad": true,
            "KeepAlive": true,
            "StandardOutPath": "/tmp/fluent-engine.log",
            "StandardErrorPath": "/tmp/fluent-engine.log",
            "WorkingDirectory": mainPy.deletingLastPathComponent().path,
            "EnvironmentVariables": [
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            ],
        ]
        return try? PropertyListSerialization.data(
            fromPropertyList: plist, format: .xml, options: 0)
    }

    /// Installs/refreshes the Launch Agent so it always points at the current
    /// bundle location (self-heals across app moves and Sparkle updates).
    private func installEngineLaunchAgentIfNeeded() {
        guard let desired = desiredEngineAgentPlistData() else { return }
        if let existing = try? Data(contentsOf: engineAgentPlistURL), existing == desired {
            return
        }
        let dir = engineAgentPlistURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        do {
            try desired.write(to: engineAgentPlistURL)
        } catch {
            print("[Fluent] failed to write launch agent plist: \(error)")
            return
        }
        runLaunchctl(["bootout", "gui/\(getuid())/\(Self.engineAgentLabel)"])
        runLaunchctl(["bootstrap", "gui/\(getuid())", engineAgentPlistURL.path])
        print("[Fluent] launch agent installed: \(engineAgentPlistURL.path)")
    }

    @discardableResult
    private func runLaunchctl(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }
```

- [ ] **Step 3: Rewrite `startEngine()`'s interpreter guard and environment.** Replace the venv-guard block (the comment starting `// Only the venv python has the installed deps` through the `guard … else { … runEngineSetup(); return }`) with:

```swift
        guard let python = enginePython() else {
            print("[Fluent] no engine interpreter available — engine not started")
            return
        }
```

  and in the same function replace `process.executableURL = URL(fileURLWithPath: venvPython)` with `process.executableURL = URL(fileURLWithPath: python)`, then add the environment just after `process.currentDirectoryURL` is set:

```swift
        var env = ProcessInfo.processInfo.environment
        env["PYTHONNOUSERSITE"] = "1"        // don't leak ~/.local site-packages
        env["PYTHONDONTWRITEBYTECODE"] = "1" // bundle is read-only + codesigned
        process.environment = env
```

- [ ] **Step 4: Update `applicationDidFinishLaunching`.** Replace the `setupEngineIfNeeded()` call with:

```swift
        migrateLegacyEngineIfNeeded()
        installEngineLaunchAgentIfNeeded()
        startEngine()
```

- [ ] **Step 5: Build**

Run: `xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Debug build 2>&1 | tail -3`
Expected: `BUILD SUCCEEDED`. Also `grep -c "runEngineSetup\|findSystemPython\|EngineSetupError\|engineReadySentinel" fluent/Fluent/AppDelegate.swift` → `0`.

- [ ] **Step 6: Commit**

```bash
git add fluent/Fluent/AppDelegate.swift
git commit -m "feat(app): run the engine from the bundled Python runtime

Removes the system-Python discovery, venv setup flow, and both failure
dialogs; the app now manages the Launch Agent itself and migrates old
venv-based installs."
```

---

### Task 5: Delete the setup-era files

**Files:**
- Delete: `fluent/Fluent/EngineSetupWindowController.swift`, `fluent-engine/setup_engine.sh`, `fluent-engine/install_agent.py`
- Modify: `fluent/Fluent.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes: Task 4 (nothing references `EngineSetupWindowController` after it).

- [ ] **Step 1: Confirm nothing still references the deleted files**

Run: `grep -rn "EngineSetupWindowController\|setup_engine\|install_agent" fluent/Fluent/*.swift fluent-engine --include="*.py" --include="*.sh"`
Expected: only self-references from the files being deleted (and `EngineSetupWindowController.swift`'s own class definition). If anything else shows up, fix it first.

- [ ] **Step 2: Delete the files**

```bash
git rm fluent/Fluent/EngineSetupWindowController.swift \
       fluent-engine/setup_engine.sh \
       fluent-engine/install_agent.py
```

- [ ] **Step 3: Remove the four pbxproj references.** In `fluent/Fluent.xcodeproj/project.pbxproj`, delete these exact lines (do NOT run `xcodegen generate`):

```
		E5A1B2C3D4E5F60718293A4B /* EngineSetupWindowController.swift in Sources */ = {isa = PBXBuildFile; fileRef = F6B2C3D4E5F6071829304A5C /* EngineSetupWindowController.swift */; };
		F6B2C3D4E5F6071829304A5C /* EngineSetupWindowController.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = EngineSetupWindowController.swift; sourceTree = "<group>"; };
				F6B2C3D4E5F6071829304A5C /* EngineSetupWindowController.swift */,
				E5A1B2C3D4E5F60718293A4B /* EngineSetupWindowController.swift in Sources */,
```

- [ ] **Step 4: Build**

Run: `xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Debug build 2>&1 | tail -3`
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 5: Commit**

```bash
git add fluent/Fluent.xcodeproj/project.pbxproj
git commit -m "chore(app): delete first-launch Python setup machinery"
```

---

### Task 6: End-to-end verification on a simulated clean machine

No new code — proves the whole chain before the next real release.

**Files:** none (verification only)

- [ ] **Step 1: Full local assembly of a release-style app** (repeat of Task 3 Step 3 against the code as of Task 5, including the Task 4/5 app changes):

```bash
bash scripts/build_engine_runtime.sh
xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Release \
    -derivedDataPath fluent/build/DerivedData SYMROOT=fluent/build/Release build 2>&1 | tail -3
APP=fluent/build/Release/Release/Fluent.app
bash scripts/bundle_engine_runtime_into_app.sh "$APP" \
    "Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)"
codesign --deep --force --options runtime --timestamp \
    --entitlements fluent/Fluent/Fluent.entitlements \
    --sign "Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
```

- [ ] **Step 2: Boot the engine exactly as a fresh consumer Mac would** — stripped env, empty HOME, no Homebrew paths. Stop anything holding port 2788 first:

```bash
launchctl bootout "gui/$(id -u)/com.fluent.engine" 2>/dev/null || true
lsof -ti tcp:2788 | xargs kill 2>/dev/null || true
TMPHOME=$(mktemp -d)
cd "$APP/Contents/Resources/fluent-engine"
env -i HOME="$TMPHOME" PATH=/usr/bin:/bin \
    PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    ../engine-runtime/bin/python3 main.py &
sleep 3
curl -s http://127.0.0.1:2788/status
kill %1
```

Expected: `curl` returns the engine's `/status` JSON (any well-formed JSON body means the runtime, deps, and HTTP server all work with zero machine dependencies). If Python fails to start or imports fail, the runtime is not actually self-contained — go back to the Task 2 gates.

- [ ] **Step 3: Launch the real app once** (`open "$APP"` — or rebuild into /Applications via ship.sh) and check:
  - No "Python is required" or setup dialog appears.
  - `/tmp/fluent-engine.log` shows the engine starting under `…/Resources/engine-runtime/bin/python3`.
  - `~/Library/LaunchAgents/com.fluent.engine.plist` now points at the bundle paths.
  - `~/.fluent/engine/` is gone (migration ran), while `~/.fluent/config.json`, `reports/`, `recordings/` are intact.

- [ ] **Step 4: Record sizes** for the release notes: `du -sh "$APP"` and `ditto -c -k --keepParent "$APP" /tmp/fluent-size-test.zip && ls -lh /tmp/fluent-size-test.zip` (this approximates the Sparkle update zip). Note the numbers in the final report; expected roughly 110 MB unpacked / 35–45 MB zipped.

- [ ] **Step 5: Commit the plan checkboxes and report.** The first real `release.sh` run (with notarization) after merging is the final gate — notarization now covers ~2,000 extra signed Mach-O files. If notarytool rejects, inspect `xcrun notarytool log <id>`; the expected failure mode would be an unsigned binary the find-loop missed (fix the loop's predicate), not the signing order.

---

## Rollback

Each task is an independent commit; `git revert` in reverse order restores the venv-based setup. Users who already migrated would re-run first-launch setup on next start (the venv rebuild path still exists in any reverted build).
