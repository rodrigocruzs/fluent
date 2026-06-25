"""
Transcription via the Fluent backend, which proxies Deepgram.
The engine compresses the recorded WAV to AAC/m4a (huge size reduction) and
uploads that; no local speech model is used.

Two upload paths, chosen by size:

- Small clips (≤ ~4MB compressed) go straight in the request body to
  POST /transcribe. The backend runs on Vercel, whose serverless functions
  reject request bodies larger than ~4.5MB (HTTP 413), so this is the fast path
  only for short sessions.

- Long sessions exceed that limit, so the engine uploads the compressed audio
  directly to R2 with a presigned PUT (bypassing Vercel), then calls
  POST /transcribe/start. Deepgram fetches the object itself and the backend
  deletes it immediately. AAC mono @ 32kbps is ~0.23MB/min, so an hour is
  ~14MB — fine for the R2 path, far over the direct-body limit.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from fluent.config import BACKEND_URL
from fluent.coach import get_token

# Comfortable margin below Vercel's ~4.5MB serverless body limit. Anything at or
# under this goes in the request body; anything larger uses the R2 upload path.
DIRECT_UPLOAD_LIMIT = 4_000_000


def _compress_to_m4a(wav_path: Path) -> tuple[bytes, str]:
    """
    Encode the WAV to AAC in an m4a container using macOS's built-in afconvert
    (no extra dependency). Returns (bytes, content_type). Falls back to the raw
    WAV if afconvert is unavailable or fails.
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


def _backend_url() -> str:
    return os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)


def _transcribe_direct(audio: bytes, content_type: str, token: str) -> str:
    """Short clip: upload the bytes directly in the request body."""
    r = httpx.post(
        f"{_backend_url()}/transcribe",
        content=audio,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": content_type},
        timeout=180,
    )
    if r.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    r.raise_for_status()
    return r.json().get("transcript", "")


def _transcribe_via_r2(audio: bytes, content_type: str, token: str) -> str:
    """Long session: presigned PUT to R2, then ask the backend to transcribe."""
    url = _backend_url()
    auth = {"Authorization": f"Bearer {token}"}

    init = httpx.post(f"{url}/transcribe/init", headers=auth,
                      json={"content_type": content_type}, timeout=30)
    if init.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    if init.status_code == 503:
        raise RuntimeError(
            "This session is too long to transcribe right now. "
            "Please try a shorter recording."
        )
    init.raise_for_status()
    data = init.json()
    key, put_url = data["key"], data["put_url"]

    # Upload straight to R2 (bypasses Vercel entirely).
    put = httpx.put(put_url, content=audio,
                    headers={"Content-Type": content_type}, timeout=300)
    put.raise_for_status()

    start = httpx.post(f"{url}/transcribe/start", headers=auth,
                       json={"key": key}, timeout=300)
    if start.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    start.raise_for_status()
    return start.json().get("transcript", "")


def transcribe(wav_path: Path, _api_key: str = "") -> str:
    token = get_token()
    if not token:
        raise RuntimeError("Not logged in. Please sign in to Fluent.")

    audio, content_type = _compress_to_m4a(Path(wav_path))
    if len(audio) <= DIRECT_UPLOAD_LIMIT:
        return _transcribe_direct(audio, content_type, token)
    return _transcribe_via_r2(audio, content_type, token)
