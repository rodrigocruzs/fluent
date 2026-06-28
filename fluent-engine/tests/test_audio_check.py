import struct
import wave
from pathlib import Path

from fluent.audio_check import system_audio_captured


def _write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_missing_file_is_not_captured(tmp_path):
    assert system_audio_captured(tmp_path / "nope.wav") is False


def test_silent_file_is_not_captured(tmp_path):
    p = tmp_path / "silent.wav"
    _write_wav(p, [0] * 16000)  # 1s of pure silence
    assert system_audio_captured(p) is False


def test_loud_file_is_captured(tmp_path):
    p = tmp_path / "loud.wav"
    _write_wav(p, [8000, -8000] * 8000)  # 1s of loud tone
    assert system_audio_captured(p) is True
