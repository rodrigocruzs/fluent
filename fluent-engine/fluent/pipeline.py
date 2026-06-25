"""
Orchestrates: transcribe → diarise → coach.
Writes ~/.fluent/reports/latest.json and fires a Darwin notification
to wake the Swift frontend. No HTML generation — the frontend renders.
"""

import json
from datetime import datetime
from pathlib import Path

from fluent import platform
from fluent.config import Config
from fluent.transcribe import transcribe
from fluent.diarise import diarise, filter_user_segments, LABEL_USER
from fluent.coach import coach, save_session_remote
from fluent.audio import RecordingPaths

REPORTS_DIR = Path.home() / ".fluent" / "reports"
LATEST_JSON = REPORTS_DIR / "latest.json"


def _session_name(now: datetime) -> str:
    h = now.hour
    if h < 12:  return "Morning session"
    if h < 17:  return "Afternoon session"
    return "Evening session"


def run_pipeline(
    paths: RecordingPaths,
    duration: float,
    config: Config,
    session_name: str | None = None,
) -> Path | None:
    """
    Runs the full pipeline, writes latest.json, wakes Swift frontend.
    Returns path to latest.json on success.
    """
    # Transcription must never silently lose a recording. If it fails (network,
    # backend, audio too long), save the session anyway with a clear marker so
    # the user sees what happened instead of being dropped back to an empty
    # Sessions list. Coaching is skipped automatically when the transcript is
    # empty (see below).
    print(f"[pipeline] transcribing {paths.mixed} ...")
    transcript = ""
    transcribe_error = ""
    try:
        transcript = transcribe(paths.mixed)
        print(f"[pipeline] {len(transcript)} chars")
    except Exception as e:
        transcribe_error = str(e)
        print(f"[pipeline] transcription failed, saving session anyway: {e}")

    print("[pipeline] diarising ...")
    segments = diarise(paths.mixed, mic_path=paths.mic, sys_path=paths.sys)
    user_segments = filter_user_segments(segments, LABEL_USER)
    total_speaking = sum(s["duration"] for s in user_segments)
    print(f"[pipeline] user speaking: {total_speaking:.1f}s")

    user_transcript = (
        f"[User spoke for {total_speaking:.1f}s]\n\n{transcript}"
    )

    # Coaching must never lose the session. Skip it entirely when there's no
    # speech to coach, and treat any coach failure as "no issues" so the report
    # is still written and the session still saved to history.
    issues = []
    if transcript.strip():
        print("[pipeline] coaching ...")
        try:
            issues = coach(user_transcript, config)
        except Exception as e:
            print(f"[pipeline] coaching failed, saving session without issues: {e}")
            issues = []
    else:
        print("[pipeline] empty transcript — skipping coaching")
    print(f"[pipeline] {len(issues)} issue(s)")

    now = datetime.now()
    name = (session_name or "").strip() or _session_name(now)
    # If transcription failed, store a readable note as the transcript so the
    # saved session explains itself instead of appearing empty.
    saved_transcript = transcript
    if transcribe_error and not transcript.strip():
        saved_transcript = f"⚠️ Transcription failed: {transcribe_error}"
    payload = {
        "date": now.strftime("%B %d, %Y"),
        "name": name,
        "duration": duration,
        "transcript": saved_transcript,
        "issues": issues,
        "transcribe_error": transcribe_error,
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
        transcript=saved_transcript,
        issues=issues,
    )

    platform.notify_report_ready()
    return LATEST_JSON
