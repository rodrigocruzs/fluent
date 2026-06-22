"""macOS implementations of the platform seams."""

import subprocess
from pathlib import Path

# System audio on macOS is captured from the BlackHole virtual device, which
# already presents itself as a 16 kHz mono int16 input (configured by the
# Multi-Output device setup), so no resampling is needed here.
BLACKHOLE_DEVICE_NAME = "BlackHole 2ch"

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


def open_system_capture(pa, on_chunk, rate, chunk, fmt):
    """Open the system-audio capture stream (BlackHole) on macOS.

    Calls `on_chunk(pcm_bytes)` with 16 kHz mono int16 frames — the same
    format the mic stream produces — so the recorder's mixer is unchanged.
    Returns the open stream, or None if BlackHole isn't installed (the
    recorder then falls back to mic-only).
    """
    idx = None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if (BLACKHOLE_DEVICE_NAME.lower() in info["name"].lower()
                and info["maxInputChannels"] > 0):
            idx = i
            break

    if idx is None:
        print(f"WARNING: '{BLACKHOLE_DEVICE_NAME}' not found. Recording mic only.")
        return None

    def _callback(in_data, frame_count, time_info, status):
        on_chunk(in_data)
        return (None, 0)  # paContinue

    return pa.open(
        format=fmt, channels=1, rate=rate,
        input=True, input_device_index=idx,
        frames_per_buffer=chunk, stream_callback=_callback,
    )
