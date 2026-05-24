"""
First-launch helpers shared between first_launch and setup_window.
"""

import sys
import subprocess
from pathlib import Path

SETUP_DONE_FLAG = Path.home() / ".fluent" / ".setup_done"
BLACKHOLE_PKG_NAME = "BlackHole2ch-0.6.1.pkg"


def _bundled_pkg() -> Path | None:
    exe = Path(sys.executable).resolve()
    # py2app layout: .app/Contents/MacOS/Fluent → Resources/
    resources = exe.parent.parent / "Resources"
    pkg = resources / BLACKHOLE_PKG_NAME
    if pkg.exists():
        return pkg
    # Dev layout: project root / resources /
    dev_pkg = Path(__file__).parent.parent / "resources" / BLACKHOLE_PKG_NAME
    if dev_pkg.exists():
        return dev_pkg
    return None


def _request_mic_permission():
    script = """
import threading
try:
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    done = threading.Event()
    AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda g: done.set())
    done.wait(timeout=30)
except Exception:
    pass
"""
    try:
        subprocess.run([sys.executable, "-c", script], timeout=35)
    except Exception:
        pass


def run_if_needed():
    """
    Show the setup progress window if first-launch setup hasn't been done.
    This replaces the old silent background approach with a visible UI.
    """
    if SETUP_DONE_FLAG.exists():
        return

    from fluent.setup_window import run_setup_window
    run_setup_window()
