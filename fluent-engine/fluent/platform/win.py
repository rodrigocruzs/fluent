"""Windows implementations of the platform seams."""

import os
import tempfile
from pathlib import Path

# Same service/account naming as macOS so the two stores are conceptually
# identical; on Windows these become a Credential Manager generic credential.
CRED_SERVICE = "fluent"
CRED_JWT_KEY = "jwt_token"


def _keyring():
    # Imported lazily so the engine can import this module on a box where
    # keyring isn't installed yet (e.g. before the bundled env is staged).
    import keyring
    return keyring


def get_token() -> str | None:
    token = _keyring().get_password(CRED_SERVICE, CRED_JWT_KEY)
    return token if token else None


def save_token(token: str) -> None:
    _keyring().set_password(CRED_SERVICE, CRED_JWT_KEY, token)


def delete_token() -> None:
    try:
        _keyring().delete_password(CRED_SERVICE, CRED_JWT_KEY)
    except Exception:
        # delete_password raises if no credential exists; deleting a
        # nonexistent token is a no-op, matching the macOS behavior.
        pass


def notify_report_ready() -> None:
    """No-op on Windows.

    The Tauri host learns a report is ready by polling the engine's GET
    /status endpoint (the `analysing` flag going true->false) and then
    reloading ~/.fluent/reports/latest.json. No OS notification needed.
    """
    return


def log_path() -> Path:
    return Path(os.environ.get("TEMP", tempfile.gettempdir())) / "fluent-engine.log"
