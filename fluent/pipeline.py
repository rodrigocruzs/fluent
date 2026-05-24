"""
Orchestrates: transcribe → diarise → extract user segments → coach → report.
"""

from pathlib import Path
from fluent.config import Config
from fluent.transcribe import transcribe
from fluent.diarise import diarise, filter_user_segments, LABEL_USER
from fluent.coach import coach
from fluent.report import generate_report
from fluent.audio import RecordingPaths


def _extract_user_transcript(full_transcript: str, user_segments: list[dict]) -> str:
    total_user_time = sum(s["duration"] for s in user_segments)
    return f"[User spoke for {total_user_time:.1f}s in this session]\n\n{full_transcript}"


def run_pipeline(
    paths: RecordingPaths,
    duration: float,
    config: Config,
) -> Path | None:
    """
    Returns the report Path on success.
    """
    print(f"[pipeline] transcribing {paths.mixed} ...")
    transcript = transcribe(paths.mixed)
    print(f"[pipeline] transcript length: {len(transcript)} chars")

    print("[pipeline] diarising ...")
    segments = diarise(paths.mixed, mic_path=paths.mic, sys_path=paths.sys)
    user_segments = filter_user_segments(segments, LABEL_USER)
    total_speaking = sum(s["duration"] for s in user_segments)
    print(f"[pipeline] user speaking time: {total_speaking:.1f}s")

    user_transcript = _extract_user_transcript(transcript, user_segments)

    print("[pipeline] sending to backend for coaching ...")
    coaching_data = coach(user_transcript, config)

    print("[pipeline] generating report ...")
    report_path = generate_report(coaching_data, duration, transcript=transcript)
    print(f"[pipeline] report saved: {report_path}")
    return report_path
