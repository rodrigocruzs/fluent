"""
fluent-engine — headless background process.
No UI. Runs as a Launch Agent, started automatically at login.
Exposes a local HTTP API on port 2788 for the Swift app to control.
Writes ~/.fluent/reports/latest.json and fires a Darwin notification
so Fluent.app renders the new report.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fluent.config import Config
from fluent.audio import AudioRecorder, RecordingPaths
from fluent.pipeline import run_pipeline

PORT = 2788


class Engine:
    MIN_DURATION_SECS = 5.0

    def __init__(self):
        self.config = Config.load()
        self.recorder = AudioRecorder()
        self._recording = False
        self._analysing = False
        self._lock = threading.Lock()

    def start(self) -> dict:
        with self._lock:
            if self._recording:
                return {"ok": False, "error": "already recording"}
            try:
                self.recorder.start()
                self._recording = True
                return {"ok": True, "recording": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def stop(self, session_name: str | None = None,
             meeting_type: str | None = None) -> dict:
        with self._lock:
            if not self._recording:
                return {"ok": False, "error": "not recording"}
            self._recording = False

        paths, duration = self.recorder.stop()
        self._analysing = True
        threading.Thread(
            target=self._run_pipeline,
            args=(paths, duration, session_name, meeting_type),
            daemon=True,
        ).start()
        return {"ok": True, "recording": False}

    def status(self) -> dict:
        return {"recording": self._recording, "analysing": self._analysing}

    def _run_pipeline(self, paths: RecordingPaths, duration: float,
                      session_name: str | None = None,
                      meeting_type: str | None = None):
        if duration < self.MIN_DURATION_SECS:
            print(f"[engine] session too short ({duration:.1f}s < {self.MIN_DURATION_SECS}s), skipping pipeline", file=sys.stderr)
            self._analysing = False
            return
        try:
            run_pipeline(paths=paths, duration=duration, config=self.config,
                         session_name=session_name, meeting_type=meeting_type)
        except Exception as e:
            print(f"[engine] pipeline error: {e}", file=sys.stderr)
        finally:
            self._analysing = False


def make_handler(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_OPTIONS(self):
            self.send_response(200)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path == "/status":
                self._json(engine.status())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/start":
                self._json(engine.start())
            elif self.path == "/stop":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                self._json(engine.stop(session_name=body.get("session_name"),
                                       meeting_type=body.get("meeting_type")))
            elif self.path == "/signin":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                token = body.get("token", "")
                if token:
                    from fluent.coach import save_token
                    save_token(token)
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "no token"})
            elif self.path == "/signout":
                from fluent.coach import delete_token
                delete_token()
                self._json({"ok": True})
            else:
                self.send_response(404)
                self.end_headers()

        def _json(self, data: dict):
            body = json.dumps(data).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    return Handler


def main():
    cfg_dir = Path.home() / ".fluent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "reports").mkdir(exist_ok=True)

    engine = Engine()

    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", PORT), make_handler(engine))
    print(f"[engine] listening on port {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
