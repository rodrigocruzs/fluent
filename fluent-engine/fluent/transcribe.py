"""
Transcription via the Fluent backend, which proxies Deepgram.
The engine compresses the recorded WAV to AAC/m4a (huge size reduction) and
uploads that; no local speech model is used.

Why compress: the backend runs on Vercel, whose serverless functions reject
request bodies larger than ~4.5MB (HTTP 413 FUNCTION_PAYLOAD_TOO_LARGE) before
they ever reach our handler. A 16kHz mono int16 WAV is ~1.9MB/min, so anything
over ~2.3 min would fail. AAC mono @ 32kbps is ~0.23MB/min, giving ~20 min of
headroom under that limit. Deepgram accepts m4a/AAC natively.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from fluent.config import BACKEND_URL
from fluent.coach import get_token

# Comfortable margin below Vercel's ~4.5MB serverless body limit.
MAX_UPLOAD_BYTES = 4_000_000


def _compress_to_m4a(wav_path: Path) -> tuple[bytes, str]:
    """
    Encode the WAV to AAC in an m4a container using macOS's built-in afconvert
    (no extra dependency). Returns (bytes, content_type). Falls back to the raw
    WAV if afconvert is unavailable or fails — the caller still enforces the
    size limit, so a fallback that's too big surfaces a clear error.
    """
    afconvert = "/usr/bin/afconvert"
    if not os.path.exists(afconvert):
        return Path(wav_path).read_bytes(), "audio/wav"

    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        # AAC, mono, 32 kbps — ample for 16kHz speech, ~8x smaller than WAV.
        subprocess.run(
            [afconvert, "-f", "m4af", "-d", "aac", "-b", "32000",
             str(wav_path), str(out)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out.read_bytes(), "audio/mp4"
    except (subprocess.CalledProcessError, OSError):
        return Path(wav_path).read_bytes(), "audio/wav"
    finally:
        out.unlink(missing_ok=True)


def transcribe(wav_path: Path, _api_key: str = "") -> str:
    token = get_token()
    if not token:
        raise RuntimeError("Not logged in. Please sign in to Fluent.")

    audio, content_type = _compress_to_m4a(Path(wav_path))
    if len(audio) > MAX_UPLOAD_BYTES:
        minutes = len(audio) / MAX_UPLOAD_BYTES * 20  # ~20 min fits in the limit
        raise RuntimeError(
            f"Recording is too long to transcribe (~{minutes:.0f} min). "
            "Please keep sessions under about 20 minutes for now."
        )

    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    r = httpx.post(
        f"{url}/transcribe",
        content=audio,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
        timeout=180,
    )
    if r.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    r.raise_for_status()
    return r.json().get("transcript", "")
