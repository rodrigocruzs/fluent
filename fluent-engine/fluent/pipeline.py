"""
Orchestrates: transcribe → diarise → coach.
Writes ~/.fluent/reports/latest.json and fires a Darwin notification
to wake the Swift frontend. No HTML generation — the frontend renders.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from fluent.config import Config
from fluent.transcribe import transcribe
from fluent.diarise import diarise, filter_user_segments, LABEL_USER
from fluent.coach import coach, save_session_remote
from fluent.audio import RecordingPaths

REPORTS_DIR = Path.home() / ".fluent" / "reports"
LATEST_JSON = REPORTS_DIR / "latest.json"
DARWIN_NOTIFICATION = "com.fluent.reportReady"


def _notify_swift():
    """Fire a Darwin notification to wake the Swift app."""
    # Try notifyutil first (available on macOS without extra deps)
    try:
        subprocess.run(
            ["notifyutil", "-p", DARWIN_NOTIFICATION],
            capture_output=True, timeout=3,
        )
        return
    except FileNotFoundError:
        pass

    # Fallback: post via CoreFoundation directly
    try:
        import ctypes, ctypes.util
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf.CFNotificationCenterPostNotification.restype = None
        center = cf.CFNotificationCenterGetDarwinNotifyCenter()
        name_ref = cf.CFStringCreateWithCString(
            None, DARWIN_NOTIFICATION.encode(), 0x08000100)
        cf.CFNotificationCenterPostNotification(center, name_ref, None, None, True)
        cf.CFRelease(name_ref)
    except Exception as e:
        print(f"[pipeline] Darwin notification error: {e}")


def _session_name(now: datetime) -> str:
    h = now.hour
    if h < 12:  return "Morning session"
    if h < 17:  return "Afternoon session"
    return "Evening session"


def run_pipeline(
    paths: RecordingPaths,
    duration: float,
    config: Config,
) -> Path | None:
    """
    Runs the full pipeline, writes latest.json, wakes Swift frontend.
    Returns path to latest.json on success.
    """
    print(f"[pipeline] transcribing {paths.mixed} ...")
    transcript = transcribe(paths.mixed)
    print(f"[pipeline] {len(transcript)} chars")

    print("[pipeline] diarising ...")
    segments = diarise(paths.mixed, mic_path=paths.mic, sys_path=paths.sys)
    user_segments = filter_user_segments(segments, LABEL_USER)
    total_speaking = sum(s["duration"] for s in user_segments)
    print(f"[pipeline] user speaking: {total_speaking:.1f}s")

    user_transcript = (
        f"[User spoke for {total_speaking:.1f}s]\n\n{transcript}"
    )

    print("[pipeline] coaching ...")
    issues = coach(user_transcript, config)
    print(f"[pipeline] {len(issues)} issue(s)")

    now = datetime.now()
    payload = {
        "date": now.strftime("%B %d, %Y"),
        "name": _session_name(now),
        "duration": duration,
        "transcript": transcript,
        "issues": issues,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Timestamped archive copy
    slug = now.strftime("%Y-%m-%d_%H-%M")
    (REPORTS_DIR / f"{slug}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"[pipeline] wrote {LATEST_JSON}")

    save_session_remote(
        slug=slug,
        name=payload["name"],
        date=payload["date"],
        duration=duration,
        transcript=transcript,
        issues=issues,
    )

    _notify_swift()
    return LATEST_JSON
