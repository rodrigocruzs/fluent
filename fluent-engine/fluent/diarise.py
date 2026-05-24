"""
Energy-based speaker diarisation using the two separate audio channels
(mic and system audio) that AudioRecorder now saves separately.

Strategy:
- Split both streams into 1-second windows.
- Compute RMS energy per window for each channel.
- A window is "user speaking" if mic RMS > threshold AND mic RMS > sys RMS * dominance_ratio.
- A window is "other speaking" if sys RMS > threshold AND sys RMS > mic RMS * dominance_ratio.
- Windows below the silence threshold are labelled SILENCE.

Returns the same segment dict format as the old pyannote diarise() so the
rest of the pipeline is unchanged.
"""

import struct
import wave
from pathlib import Path

SAMPLE_RATE = 16000
WINDOW_SECS = 1.0
SILENCE_RMS = 200       # below this = silence (int16 scale 0-32767)
DOMINANCE_RATIO = 1.5   # one channel must be this much louder to "own" the window

LABEL_USER  = "SPEAKER_USER"
LABEL_OTHER = "SPEAKER_OTHER"


def _rms(frames: bytes) -> float:
    if not frames:
        return 0.0
    samples = struct.unpack(f"<{len(frames)//2}h", frames)
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _read_wav_chunks(path: Path, window_frames: int) -> list[bytes]:
    """Read a WAV file and return a list of fixed-size raw PCM chunks."""
    chunks = []
    if not path.exists() or path.stat().st_size < 44:
        return chunks
    with wave.open(str(path), "rb") as wf:
        while True:
            data = wf.readframes(window_frames)
            if not data:
                break
            chunks.append(data)
    return chunks


def diarise(wav_path: Path, mic_path: Path | None = None, sys_path: Path | None = None) -> list[dict]:
    """
    Diarise using separate mic and system audio files.

    wav_path  — mixed file (used to infer duration if channel files absent)
    mic_path  — mic-only WAV (session_*_mic.wav)
    sys_path  — system-audio WAV (session_*_sys.wav)
    """
    window_frames = int(SAMPLE_RATE * WINDOW_SECS)

    mic_chunks = _read_wav_chunks(mic_path, window_frames) if mic_path else []
    sys_chunks = _read_wav_chunks(sys_path, window_frames) if sys_path else []

    # Pad the shorter list so zip covers all windows
    n = max(len(mic_chunks), len(sys_chunks))
    mic_chunks += [b""] * (n - len(mic_chunks))
    sys_chunks  += [b""] * (n - len(sys_chunks))

    segments: list[dict] = []
    current_label: str | None = None
    seg_start: float = 0.0

    def _flush(label, start, end):
        if label and label != "SILENCE" and end > start:
            segments.append({
                "speaker": label,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
            })

    for i, (mic_data, sys_data) in enumerate(zip(mic_chunks, sys_chunks)):
        t_start = i * WINDOW_SECS
        t_end   = t_start + WINDOW_SECS

        mic_rms = _rms(mic_data)
        sys_rms = _rms(sys_data)

        if mic_rms < SILENCE_RMS and sys_rms < SILENCE_RMS:
            label = "SILENCE"
        elif mic_rms >= sys_rms * DOMINANCE_RATIO:
            label = LABEL_USER
        elif sys_rms >= mic_rms * DOMINANCE_RATIO:
            label = LABEL_OTHER
        else:
            # Both active, roughly equal — attribute to user (conservative)
            label = LABEL_USER

        if label != current_label:
            _flush(current_label, seg_start, t_start)
            current_label = label
            seg_start = t_start

    _flush(current_label, seg_start, n * WINDOW_SECS)
    return segments


def get_speaker_labels(segments: list[dict]) -> list[str]:
    seen = set()
    labels = []
    for s in segments:
        if s["speaker"] not in seen:
            seen.add(s["speaker"])
            labels.append(s["speaker"])
    return labels


def filter_user_segments(segments: list[dict], user_label: str) -> list[dict]:
    return [s for s in segments if s["speaker"] == user_label]
