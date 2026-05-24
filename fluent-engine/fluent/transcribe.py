"""
Local transcription via faster-whisper (tiny.en model).
Model is downloaded once to ~/.fluent/models/faster-whisper-tiny.en/
by the setup window on first launch.
"""

from pathlib import Path
from faster_whisper import WhisperModel

MODELS_DIR  = Path.home() / ".fluent" / "models"
MODEL_DIR   = MODELS_DIR / "faster-whisper-tiny.en"
MODEL_SIZE  = "tiny.en"


def _load_model() -> WhisperModel:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    # Use local directory if the setup window already downloaded it;
    # otherwise fall back to automatic HuggingFace download.
    if (MODEL_DIR / "model.bin").exists():
        return WhisperModel(str(MODEL_DIR), device="cpu")
    return WhisperModel(MODEL_SIZE, device="cpu", download_root=str(MODELS_DIR))


def transcribe(wav_path: Path, _api_key: str = "") -> str:
    model = _load_model()
    segments, _ = model.transcribe(str(wav_path), language="en", beam_size=1)
    return " ".join(seg.text.strip() for seg in segments)
