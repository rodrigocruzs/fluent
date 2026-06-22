"""
Platform abstraction for the OS-specific seams of the engine.

The rest of the engine (transcribe / diarise / pipeline / the coaching call /
report / config) is plain cross-platform Python. Only three things genuinely
differ per OS, and they live behind this module:

  - token storage      (macOS Keychain   vs Windows Credential Manager)
  - "report ready"     (Darwin notification vs no-op; the Windows host polls
                        the engine's /status endpoint instead)
  - log path           (/tmp on macOS    vs %TEMP% on Windows)

`get_token` / `save_token` / `delete_token`, `notify_report_ready`, and
`log_path` are re-exported from the matching backend so callers do
`from fluent import platform` and never branch on sys.platform themselves.
"""

import sys

if sys.platform == "win32":
    from fluent.platform import win as _impl
else:
    from fluent.platform import mac as _impl

get_token = _impl.get_token
save_token = _impl.save_token
delete_token = _impl.delete_token
notify_report_ready = _impl.notify_report_ready
log_path = _impl.log_path
open_system_capture = _impl.open_system_capture

__all__ = [
    "get_token",
    "save_token",
    "delete_token",
    "notify_report_ready",
    "log_path",
    "open_system_capture",
]
