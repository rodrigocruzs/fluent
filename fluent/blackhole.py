"""
BlackHole installation and Multi-Output Device setup.
Everything runs silently — no user-visible audio driver terminology.

Flow:
  1. is_blackhole_installed()  — check HAL driver on disk
  2. install_blackhole(pkg)    — sudo installer via osascript privilege dialog
  3. ensure_multi_output()     — create Multi-Output Device (BlackHole + speakers)
                                 and set it as system default output
"""

import ctypes
import ctypes.util
import struct
import subprocess
import time
from pathlib import Path

BLACKHOLE_DRIVER_PATH = "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"
BLACKHOLE_NAME = "BlackHole 2ch"
MULTI_OUTPUT_NAME = "Fluent Audio"
MULTI_OUTPUT_UID = "com.fluent.multioutput.v1"

# ---------------------------------------------------------------------------
# CoreAudio / CoreFoundation ctypes — device IDs are little-endian uint32,
# four-char-code selectors are big-endian uint32.
# ---------------------------------------------------------------------------

_ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
_cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))

_cf.CFStringGetCStringPtr.restype = ctypes.c_char_p
_cf.CFStringGetLength.restype = ctypes.c_long
_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFRelease.restype = None

kAudioObjectSystemObject = 1
_SEL_DEVICES    = struct.unpack(">I", b"dev#")[0]
_SEL_DEF_OUT    = struct.unpack(">I", b"dOut")[0]
_SEL_SYS_OUT    = struct.unpack(">I", b"sOut")[0]
_SEL_SCOPE_GLOB = struct.unpack(">I", b"glob")[0]
_SEL_LNAME      = struct.unpack(">I", b"lnam")[0]
_SEL_UID        = struct.unpack(">I", b"uid ")[0]
_kCFStringEncodingUTF8 = 0x08000100


class _Addr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32),
                ("mScope",    ctypes.c_uint32),
                ("mElement",  ctypes.c_uint32)]


def _get_raw(obj: int, selector: int, size: int | None = None) -> bytes:
    a = _Addr(selector, _SEL_SCOPE_GLOB, 0)
    if size is None:
        sz = ctypes.c_uint32(0)
        _ca.AudioObjectGetPropertyDataSize(
            ctypes.c_uint32(obj), ctypes.byref(a), 0, None, ctypes.byref(sz))
        size = sz.value
    if not size:
        return b""
    sz = ctypes.c_uint32(size)
    buf = ctypes.create_string_buffer(size)
    err = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj), ctypes.byref(a), 0, None, ctypes.byref(sz), buf)
    return buf.raw[:sz.value] if err == 0 else b""


def _cfstr_to_py(ref: int) -> str:
    if not ref:
        return ""
    ptr = _cf.CFStringGetCStringPtr(ctypes.c_void_p(ref), _kCFStringEncodingUTF8)
    if ptr:
        return ptr.decode("utf-8", errors="replace")
    length = _cf.CFStringGetLength(ctypes.c_void_p(ref))
    if length <= 0:
        return ""
    buf = ctypes.create_string_buffer(length * 4 + 1)
    _cf.CFStringGetCString(ctypes.c_void_p(ref), buf, len(buf), _kCFStringEncodingUTF8)
    return buf.value.decode("utf-8", errors="replace")


def _read_cfstr_prop(dev_id: int, selector: int) -> str:
    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    raw = _get_raw(dev_id, selector, ptr_size)
    if len(raw) < ptr_size:
        return ""
    fmt = "<Q" if ptr_size == 8 else "<I"
    ref = struct.unpack(fmt, raw[:ptr_size])[0]
    result = _cfstr_to_py(ref)
    if ref:
        _cf.CFRelease(ctypes.c_void_p(ref))
    return result


def _all_device_ids() -> list[int]:
    raw = _get_raw(kAudioObjectSystemObject, _SEL_DEVICES)
    if not raw:
        return []
    return list(struct.unpack(f"<{len(raw) // 4}I", raw))


def _device_name(dev_id: int) -> str:
    return _read_cfstr_prop(dev_id, _SEL_LNAME)


def _device_uid(dev_id: int) -> str:
    return _read_cfstr_prop(dev_id, _SEL_UID)


def _find_device(fragment: str) -> tuple[int, str] | tuple[None, None]:
    """Return (device_id, uid) for the first device whose name contains fragment."""
    for dev_id in _all_device_ids():
        name = _device_name(dev_id)
        if fragment.lower() in name.lower():
            return dev_id, _device_uid(dev_id)
    return None, None


def _set_default_output(dev_id: int):
    a_out = _Addr(_SEL_DEF_OUT, _SEL_SCOPE_GLOB, 0)
    a_sys = _Addr(_SEL_SYS_OUT, _SEL_SCOPE_GLOB, 0)
    v = ctypes.c_uint32(dev_id)
    _ca.AudioObjectSetPropertyData(
        ctypes.c_uint32(kAudioObjectSystemObject), ctypes.byref(a_out),
        0, None, ctypes.c_uint32(4), ctypes.byref(v))
    _ca.AudioObjectSetPropertyData(
        ctypes.c_uint32(kAudioObjectSystemObject), ctypes.byref(a_sys),
        0, None, ctypes.c_uint32(4), ctypes.byref(v))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_blackhole_installed() -> bool:
    return Path(BLACKHOLE_DRIVER_PATH).exists()


def install_blackhole(pkg_path: str | Path) -> bool:
    """
    Install BlackHole using the standard macOS password dialog.
    Returns True on success.
    """
    pkg = str(Path(pkg_path).resolve())
    script = f'do shell script "installer -pkg {pkg!r} -target /" with administrator privileges'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    return result.returncode == 0


def ensure_multi_output() -> bool:
    """
    Create a Multi-Output Device combining built-in speakers + BlackHole,
    then set it as the system default output.
    Returns True if the device is ready.
    """
    # Already exists?
    mo_id, _ = _find_device(MULTI_OUTPUT_NAME)
    if mo_id is not None:
        _set_default_output(mo_id)
        return True

    bh_id, bh_uid = _find_device("BlackHole 2ch")
    if not bh_uid:
        return False

    _, speaker_uid = _find_device("MacBook Pro Speakers")
    if not speaker_uid:
        _, speaker_uid = _find_device("Built-in Output")

    success = _create_aggregate(bh_uid, speaker_uid)
    if not success:
        return False

    # Wait up to 6 s for CoreAudio to surface the new device
    for _ in range(20):
        time.sleep(0.3)
        mo_id, _ = _find_device(MULTI_OUTPUT_NAME)
        if mo_id is not None:
            _set_default_output(mo_id)
            return True
    return False


def _create_aggregate(bh_uid: str, speaker_uid: str | None) -> bool:
    """Create the aggregate multi-output device via Foundation + CoreAudio."""
    sub_uids = []
    if speaker_uid:
        sub_uids.append(speaker_uid)
    sub_uids.append(bh_uid)
    sub_list_repr = repr(sub_uids)

    script = f"""
import sys, ctypes, ctypes.util, objc
from Foundation import NSDictionary, NSArray

_ca = ctypes.CDLL(ctypes.util.find_library('CoreAudio'))
_ca.AudioHardwareCreateAggregateDevice.restype = ctypes.c_int32
_ca.AudioHardwareCreateAggregateDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]

sub_devices = NSArray.arrayWithArray_(
    [NSDictionary.dictionaryWithDictionary_({{'uid': uid}}) for uid in {sub_list_repr}]
)
desc = NSDictionary.dictionaryWithDictionary_({{
    'name':       '{MULTI_OUTPUT_NAME}',
    'uid':        '{MULTI_OUTPUT_UID}',
    'stacked':    1,
    'subdevices': sub_devices,
}})

out_id = ctypes.c_uint32(0)
err = _ca.AudioHardwareCreateAggregateDevice(ctypes.c_void_p(objc.pyobjc_id(desc)), ctypes.byref(out_id))
sys.exit(0 if err == 0 else 1)
"""
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0
