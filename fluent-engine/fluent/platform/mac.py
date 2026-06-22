"""macOS implementations of the platform seams."""

import subprocess
from pathlib import Path

KEYCHAIN_SERVICE = "fluent"
KEYCHAIN_JWT_KEY = "jwt_token"

DARWIN_NOTIFICATION = "com.fluent.reportReady"


def get_token() -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_JWT_KEY, "-w"],
        capture_output=True, text=True,
    )
    token = result.stdout.strip()
    return token if token else None


def save_token(token: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_JWT_KEY],
        capture_output=True,
    )
    subprocess.run(
        ["security", "add-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_JWT_KEY, "-w", token],
        capture_output=True,
    )


def delete_token() -> None:
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_JWT_KEY],
        capture_output=True,
    )


def notify_report_ready() -> None:
    """Fire a Darwin notification so Fluent.app renders the new report."""
    # notifyutil ships with macOS and needs no extra deps.
    try:
        subprocess.run(
            ["notifyutil", "-p", DARWIN_NOTIFICATION],
            capture_output=True, timeout=3,
        )
        return
    except FileNotFoundError:
        pass

    # Fallback: post via CoreFoundation directly.
    try:
        import ctypes
        import ctypes.util
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf.CFNotificationCenterPostNotification.restype = None
        center = cf.CFNotificationCenterGetDarwinNotifyCenter()
        name_ref = cf.CFStringCreateWithCString(
            None, DARWIN_NOTIFICATION.encode(), 0x08000100)
        cf.CFNotificationCenterPostNotification(center, name_ref, None, None, True)
        cf.CFRelease(name_ref)
    except Exception as e:
        print(f"[platform.mac] Darwin notification error: {e}")


def log_path() -> Path:
    return Path("/tmp/fluent-engine.log")
