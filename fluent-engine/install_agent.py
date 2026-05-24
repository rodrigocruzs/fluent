"""
Installs fluent-engine as a macOS Launch Agent so it starts at login automatically.
Run once: python3 install_agent.py
"""
import os
import sys
import subprocess
from pathlib import Path

AGENT_LABEL = "com.fluent.engine"
PYTHON = sys.executable
MAIN_PY = str(Path(__file__).parent / "main.py")
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{AGENT_LABEL}.plist"

PLIST = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{MAIN_PY}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/fluent-engine.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/fluent-engine.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Library/Frameworks/Python.framework/Versions/3.11/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""

def install():
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(PLIST)
    print(f"Wrote {PLIST_PATH}")

    # Unload if already loaded
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)

    # Load it
    result = subprocess.run(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Launch agent loaded — engine will start now and at every login.")
    else:
        print(f"launchctl load failed: {result.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    install()
