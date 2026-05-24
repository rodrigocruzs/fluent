"""
py2app build script.

Usage:
    pip install py2app
    python setup_app.py py2app
"""

from setuptools import setup

APP = ["app.py"]

DATA_FILES = [
    # Bundle the BlackHole installer into Resources
    ("", ["resources/BlackHole2ch-0.6.1.pkg"]),
]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": None,          # add app.icns here if you have one
    "plist": {
        "CFBundleName": "Fluent",
        "CFBundleDisplayName": "Fluent",
        "CFBundleIdentifier": "com.fluent.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,       # menu bar only — no Dock icon
        "NSMicrophoneUsageDescription": "Fluent needs access to your microphone to coach your English.",
        "NSAppleEventsUsageDescription": "Fluent uses AppleScript to install an audio component.",
    },
    "packages": [
        "fluent",
        "rumps",
        "pyaudio",
        "openai",
        "anthropic",
        "pyannote",
        "torch",
        "torchaudio",
        "pydub",
        "Foundation",
        "CoreAudio",
        "AVFoundation",
        "objc",
    ],
    "includes": [
        "fluent.config",
        "fluent.audio",
        "fluent.blackhole",
        "fluent.first_launch",
        "fluent.pipeline",
        "fluent.transcribe",
        "fluent.diarise",
        "fluent.coach",
        "fluent.report",
    ],
    "excludes": ["tkinter", "PyQt5", "wx"],
    "semi_standalone": False,
    "site_packages": True,
}

setup(
    name="Fluent",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
