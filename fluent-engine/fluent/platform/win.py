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


def _resample_to_16k_mono_int16(raw: bytes, src_rate: int, src_channels: int) -> bytes:
    """Convert a WASAPI loopback chunk to 16 kHz mono int16.

    Loopback typically delivers 48 kHz stereo float32. We downmix to mono,
    linearly resample to 16 kHz, and pack as int16 so the output matches the
    mic stream and the recorder's mixer needs no Windows-specific handling.
    Pure stdlib (array/audioop) — no numpy dependency.
    """
    import array
    import audioop

    # float32 [-1, 1] -> int16. (WASAPI loopback shared-mode is float32.)
    floats = array.array("f")
    floats.frombytes(raw)
    if not floats:
        return b""
    ints = array.array("h", (
        int(max(-1.0, min(1.0, s)) * 32767.0) for s in floats
    ))
    pcm = ints.tobytes()

    # Downmix to mono (audioop wants the sample width = 2 for int16).
    if src_channels > 1:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5) if src_channels == 2 else \
            _downmix_n(pcm, src_channels)

    # Resample src_rate -> 16000.
    if src_rate != 16000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, src_rate, 16000, None)

    return pcm


def _downmix_n(pcm: bytes, channels: int) -> bytes:
    """Average N interleaved int16 channels down to mono (rare >2ch case)."""
    import array
    samples = array.array("h")
    samples.frombytes(pcm)
    out = array.array("h", (
        int(sum(samples[i:i + channels]) / channels)
        for i in range(0, len(samples) - channels + 1, channels)
    ))
    return out.tobytes()


def make_pyaudio():
    """Create the loopback-aware PyAudio instance.

    pyaudiowpatch is a superset build of PyAudio that adds the WASAPI
    loopback APIs (get_loopback_device_info_generator, etc.). The standard
    `pyaudio.PyAudio` does NOT have them, so we must instantiate from
    pyaudiowpatch here.
    """
    import pyaudiowpatch
    return pyaudiowpatch.PyAudio()


def _find_loopback_device(pa):
    """Return the WASAPI loopback device matching the default speakers.

    Uses pyaudiowpatch's helper which returns the loopback endpoint paired
    with the current default output device directly, falling back to scanning
    all loopback devices.
    """
    # Preferred: the patched helper hands back the default speakers' loopback.
    try:
        return pa.get_default_wasapi_loopback()
    except Exception:
        pass

    try:
        default_out = pa.get_device_info_by_index(
            pa.get_default_output_device_info()["index"]
        )
        first = None
        for info in pa.get_loopback_device_info_generator():
            if first is None:
                first = info
            if default_out["name"] in info["name"]:
                return info
        return first  # fall back to the first loopback device, or None
    except Exception as e:
        print(f"WARNING: could not enumerate loopback devices ({e}); mic only.")
        return None


def open_system_capture(pa, on_chunk, rate, chunk, fmt):
    """Open the WASAPI loopback capture stream on Windows.

    Driverless: captures the default render (speaker) endpoint's output via
    WASAPI loopback — no BlackHole, no virtual device. Normalizes each chunk
    to 16 kHz mono int16 (via `_resample_to_16k_mono_int16`) before calling
    `on_chunk`, so the recorder's mixer is identical across platforms.
    Returns the open stream, or None if no loopback endpoint is found.
    `pa` must be a pyaudiowpatch PyAudio instance (see make_pyaudio).
    """
    loopback = _find_loopback_device(pa)
    if loopback is None:
        print("WARNING: no WASAPI loopback endpoint found; recording mic only.")
        return None

    src_rate = int(loopback["defaultSampleRate"])
    src_channels = int(loopback["maxInputChannels"])
    print(f"[platform.win] loopback: {loopback['name']} "
          f"({src_rate}Hz {src_channels}ch) -> 16kHz mono int16")

    def _callback(in_data, frame_count, time_info, status):
        on_chunk(_resample_to_16k_mono_int16(in_data, src_rate, src_channels))
        return (None, 0)  # paContinue

    # Open at the device's NATIVE format (float32, native rate/channels);
    # conversion to 16 kHz mono int16 happens in the callback.
    import pyaudiowpatch
    return pa.open(
        format=pyaudiowpatch.paFloat32,
        channels=src_channels,
        rate=src_rate,
        frames_per_buffer=chunk,
        input=True,
        input_device_index=loopback["index"],
        stream_callback=_callback,
    )
