"""Detect whether the system-audio stream actually captured anything.

On macOS the system stream comes from BlackHole. If the user wore headphones,
declined the driver install, or routed output away from the Fluent aggregate
device, the sys.wav will be silent. We detect that so the report can say so
instead of silently presenting a mic-only transcript as the whole meeting.
"""

import struct
import wave
from pathlib import Path

# int16 scale (0-32767). Matches the silence floor used in diarise.py.
SILENCE_RMS = 200


def _wav_rms(path: Path) -> float:
    if not path.exists() or path.stat().st_size < 44:
        return 0.0
    try:
        total_sq = 0
        total_n = 0
        with wave.open(str(path), "rb") as wf:
            while True:
                data = wf.readframes(16000)
                if not data:
                    break
                samples = struct.unpack(f"<{len(data) // 2}h", data)
                total_sq += sum(s * s for s in samples)
                total_n += len(samples)
        if total_n == 0:
            return 0.0
        return (total_sq / total_n) ** 0.5
    except (wave.Error, struct.error, OSError, EOFError):
        return 0.0


def system_audio_captured(sys_path: Path) -> bool:
    """True if sys.wav contains non-silent audio (other participants heard)."""
    return _wav_rms(Path(sys_path)) >= SILENCE_RMS
