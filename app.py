"""
Fluent — Mac menu bar app.
Run with: python app.py
"""

import threading
import os
import sys
from pathlib import Path

import rumps

from fluent.config import Config
from fluent.audio import AudioRecorder, RecordingPaths
from fluent.pipeline import run_pipeline


class FluentApp(rumps.App):
    def __init__(self):
        super().__init__("Fluent", title="🎙")
        self.config = Config.load()
        self.recorder = AudioRecorder()
        self._recording = False
        self._paths: RecordingPaths | None = None
        self._duration = 0.0

        self.menu = [
            rumps.MenuItem("Start session", callback=self.start_session),
            rumps.MenuItem("Stop session", callback=self.stop_session),
            None,
            rumps.MenuItem("Open config...", callback=self.open_config),
            rumps.MenuItem("List audio devices", callback=self.list_devices),
        ]
        self.menu["Stop session"].set_callback(None)

    def start_session(self, _):
        if self._recording:
            return

        self._recording = True
        self.title = "🔴"
        self.menu["Start session"].set_callback(None)
        self.menu["Stop session"].set_callback(self.stop_session)

        try:
            self._paths = self.recorder.start()
            rumps.notification("Fluent", "Session started", "Recording mic + system audio...")
        except Exception as e:
            self._recording = False
            self.title = "🎙"
            self.menu["Start session"].set_callback(self.start_session)
            self.menu["Stop session"].set_callback(None)
            rumps.alert("Failed to start recording", str(e))

    def stop_session(self, _):
        if not self._recording:
            return

        self.title = "⏳"
        self.menu["Stop session"].set_callback(None)

        paths, duration = self.recorder.stop()
        self._recording = False
        self._paths = paths
        self._duration = duration

        rumps.notification("Fluent", "Session stopped", f"Processing {int(duration)}s of audio...")

        threading.Thread(
            target=self._run_pipeline_async,
            args=(paths, duration),
            daemon=True,
        ).start()

    def open_config(self, _):
        config_path = Path.home() / ".fluent" / "config.json"
        if not config_path.exists():
            self.config.save()
        os.system(f'open -e "{config_path}"')

    def list_devices(self, _):
        from fluent.audio import list_input_devices
        devices = list_input_devices()
        lines = "\n".join(f"[{d['index']}] {d['name']}" for d in devices)
        rumps.alert("Available input devices", lines)

    def _run_pipeline_async(self, paths: RecordingPaths, duration: float):
        try:
            result = run_pipeline(paths=paths, duration=duration, config=self.config)
            if result:
                rumps.notification("Fluent", "Report ready", "Opening in your browser...")
        except Exception as e:
            rumps.notification("Fluent", "Pipeline error", str(e))
            print(f"[pipeline error] {e}", file=sys.stderr)
        finally:
            self.title = "🎙"
            self.menu["Start session"].set_callback(self.start_session)


def main():
    cfg_dir = Path.home() / ".fluent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "reports").mkdir(exist_ok=True)

    # Onboarding: show auth + setup screens if no JWT saved
    from fluent.onboarding import needs_onboarding, run_onboarding
    if needs_onboarding():
        completed = run_onboarding()
        if not completed:
            return  # user closed the window — don't start the app

    # First-launch hardware setup: BlackHole + mic permission
    from fluent.first_launch import run_if_needed
    run_if_needed()

    FluentApp().run()


if __name__ == "__main__":
    main()
