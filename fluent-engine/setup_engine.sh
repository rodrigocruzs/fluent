#!/usr/bin/env bash
# Sets up the Fluent engine on a user's machine.
# Called by Fluent.app on first launch.
# - Creates a venv at ~/.fluent/engine/venv
# - Installs dependencies
# - Copies engine source into ~/.fluent/engine/
# - Registers a Launch Agent so the engine starts at login
#
# Usage: setup_engine.sh <engine_resources_dir>
#   engine_resources_dir — path to the engine/ folder inside Fluent.app/Contents/Resources/

set -euo pipefail

ENGINE_SRC="${1:-$(dirname "$0")}"
FLUENT_DIR="$HOME/.fluent"
ENGINE_DIR="$FLUENT_DIR/engine"
VENV="$ENGINE_DIR/venv"
PYTHON="$VENV/bin/python3"
AGENT_LABEL="com.fluent.engine"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
LOG_FILE="$FLUENT_DIR/engine-setup.log"

mkdir -p "$FLUENT_DIR" "$ENGINE_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[setup] Starting Fluent engine setup — $(date)"
echo "[setup] Engine source: $ENGINE_SRC"

# ── 1. Find a suitable Python 3.10+ ──────────────────────────────────────────

# Echoes the path of a Python interpreter that is version 3.10 or newer.
is_py_310_plus() {
    # Exit status 0 only when the interpreter reports major==3 and minor>=10.
    "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
    # Prefer well-known absolute paths first — when Fluent.app launches this
    # script the inherited PATH may only contain /usr/bin (system Python 3.9),
    # so relying on PATH lookups alone can wrongly pick an old interpreter.
    local path
    for path in \
        /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
        /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
        /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.10/bin/python3; do
        if [ -x "$path" ] && is_py_310_plus "$path"; then
            echo "$path"; return 0
        fi
    done
    # Fall back to PATH lookups, verifying the version each time.
    for py in python3.13 python3.12 python3.11 python3.10 python3; do
        path=$(command -v "$py" 2>/dev/null || true)
        [ -z "$path" ] && continue
        if is_py_310_plus "$path"; then
            echo "$path"; return 0
        fi
    done
    return 1
}

SYS_PYTHON=$(find_python) || {
    echo "[setup] ERROR: Python 3.10+ not found. Please install Python from python.org."
    exit 1
}
echo "[setup] Using Python: $SYS_PYTHON ($($SYS_PYTHON --version))"

# ── 2. Create venv ────────────────────────────────────────────────────────────

if [ ! -x "$PYTHON" ]; then
    echo "[setup] Creating venv at $VENV ..."
    "$SYS_PYTHON" -m venv "$VENV"
fi

# ── 3. Copy engine source ─────────────────────────────────────────────────────

echo "[setup] Copying engine source to $ENGINE_DIR ..."
rsync -a --delete \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude "venv" \
    --exclude "*.egg-info" \
    "$ENGINE_SRC/" "$ENGINE_DIR/"

# ── 4. Install dependencies ───────────────────────────────────────────────────

echo "[setup] Installing dependencies (this may take a few minutes) ..."
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$ENGINE_DIR/requirements.txt" --quiet

echo "[setup] Dependencies installed."

# ── 5. Register Launch Agent ──────────────────────────────────────────────────

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${ENGINE_DIR}/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/fluent-engine.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/fluent-engine.log</string>
    <key>WorkingDirectory</key>
    <string>${ENGINE_DIR}</string>
</dict>
</plist>
PLIST

echo "[setup] Wrote Launch Agent plist: $PLIST_PATH"

# Re-register the agent. The Swift app also launches the engine itself, so the
# agent is a best-effort fallback (e.g. engine running without the app open).
# Use the modern bootstrap API and ignore failures — a non-zero status here must
# not abort setup (set -e), since the app-managed engine still works regardless.
GUI_DOMAIN="gui/$(id -u)"
launchctl bootout "$GUI_DOMAIN/$AGENT_LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$PLIST_PATH" 2>/dev/null \
    || launchctl load "$PLIST_PATH" 2>/dev/null \
    || echo "[setup] note: launch agent not loaded (engine still managed by Fluent.app)"

echo "[setup] Engine registered."
echo "[setup] Done — $(date)"
