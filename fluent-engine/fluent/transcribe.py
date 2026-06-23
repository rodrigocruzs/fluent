"""
Transcription via the Fluent backend, which proxies Deepgram.
The engine uploads the recorded WAV; no local speech model is used.
"""

import os
from pathlib import Path

import httpx

from fluent.config import BACKEND_URL
from fluent.coach import get_token


def transcribe(wav_path: Path, _api_key: str = "") -> str:
    token = get_token()
    if not token:
        raise RuntimeError("Not logged in. Please sign in to Fluent.")

    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    audio = Path(wav_path).read_bytes()
    r = httpx.post(
        f"{url}/transcribe",
        content=audio,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "audio/wav",
        },
        timeout=180,
    )
    if r.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    r.raise_for_status()
    return r.json().get("transcript", "")
