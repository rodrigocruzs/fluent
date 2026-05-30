"""
Sends the user's transcript to the Fluent backend for coaching.
The backend holds the Anthropic API key; the client only needs a JWT.
"""

import os
import httpx
import keyring
from fluent.config import Config, BACKEND_URL

KEYCHAIN_SERVICE = "fluent"
KEYCHAIN_JWT_KEY = "jwt_token"


def get_token() -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_JWT_KEY)


def save_token(token: str):
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_JWT_KEY, token)


def delete_token():
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_JWT_KEY)
    except keyring.errors.PasswordDeleteError:
        pass


def register(email: str, password: str) -> str:
    """Register a new account. Returns JWT token."""
    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    r = httpx.post(f"{url}/auth/register", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def login(email: str, password: str) -> str:
    """Log in to an existing account. Returns JWT token."""
    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    r = httpx.post(f"{url}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def save_session_remote(slug: str, name: str, date: str,
                        duration: float, transcript: str, issues: list) -> None:
    """POST the completed session to the backend for persistent storage."""
    token = get_token()
    if not token:
        return
    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    try:
        r = httpx.post(
            f"{url}/sessions",
            json={
                "slug": slug,
                "name": name,
                "date": date,
                "duration": duration,
                "transcript": transcript,
                "issues": issues,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        print(f"[coach] session saved remotely (id={r.json().get('id')})")
    except Exception as e:
        print(f"[coach] failed to save session remotely: {e}")


def coach(transcript: str, config: Config) -> list:
    """
    Send transcript to backend /coach endpoint.
    Returns list of issue dicts from Claude.
    """
    token = get_token()
    if not token:
        raise RuntimeError("Not logged in. Please sign in to Fluent.")

    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    r = httpx.post(
        f"{url}/coach",
        json={
            "transcript": transcript,
            "native_language": config.native_language,
            "job_context": config.job_context,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if r.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    r.raise_for_status()
    return r.json()
