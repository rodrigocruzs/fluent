# Fluent

macOS app that passively records your meetings and generates a post-meeting English coaching report for non-native speakers.

## Architecture

Fluent is three cooperating layers:

1. **Native macOS app** — `fluent/Fluent.xcodeproj` (Swift). Menu-bar app with a
   WKWebView UI (`frontend/`). Spawns and supervises the local engine, and
   renders reports.
2. **Local engine** — `fluent-engine/` (Python, headless). Runs as a Launch
   Agent and exposes a local HTTP API on `127.0.0.1:2788` for the app to
   start/stop recording. Captures mic + BlackHole system audio, transcribes
   locally with `faster-whisper`, diarises by audio energy, writes
   `~/.fluent/reports/latest.json`, and fires a Darwin notification
   (`com.fluent.reportReady`) so the app shows the new report.
3. **Backend** — `backend/` (FastAPI), deployed on Vercel at `tryfluent.co/api`.
   Handles auth (JWT), session storage (Neon Postgres), Stripe billing, Google
   OAuth + Calendar, and the Claude coaching call.

## Prerequisites

- macOS 14+
- [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) for system-audio
  capture. The app installs and configures a Multi-Output Device on first launch;
  to do it manually: `brew install blackhole-2ch`, then in **Audio MIDI Setup**
  create a Multi-Output Device combining `BlackHole 2ch` + your speakers and set
  it as system output.
- For local development of the engine/backend: Python 3.11+.

## Build & run the app

The app is built with Xcode (project generated from `fluent/project.yml` via
[XcodeGen](https://github.com/yonaskolb/XcodeGen)).

```bash
# Debug build + install to /Applications
xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Debug build

# Full signed + notarized release DMG (Developer ID), then install
bash release.sh
```

> Note: the app loads a **bundled copy** of `frontend/`. After editing
> `frontend/*`, rebuild and reinstall for changes to take effect, and bump the
> `report.js?v=NN` cache-buster in `frontend/report.html`.

## Engine (local development)

```bash
cd fluent-engine
pip install -r requirements.txt
python main.py          # serves the control API on 127.0.0.1:2788
```

The first run downloads the `faster-whisper` tiny.en model into
`~/.fluent/models/`. Config lives in `~/.fluent/config.json`.

## Backend (local development)

```bash
cd backend
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... uvicorn backend.main:app --reload --port 8000
```

Environment variables (DB URL, Stripe keys, Google OAuth, Anthropic key) are
read from the environment / `.env.local` — never commit credentials.

## Reports

Reports are written to `~/.fluent/reports/` and rendered inside the app.

## Project layout

```
fluent/            — Xcode project (Swift app) + project.yml (XcodeGen spec)
  Fluent/          — Swift sources (AppDelegate, WebViewController, …)
frontend/          — WebView UI: report.html, report.js, report.css
fluent-engine/     — local Python engine (main.py + fluent/ package)
  fluent/          — audio, transcribe, diarise, pipeline, coach, report, config
backend/           — FastAPI backend (main.py, auth.py, database.py)
api/index.py       — Vercel entrypoint (imports backend.main:app)
website/           — landing page, privacy policy, reset-password, DMG
release.sh         — build → sign → notarize → DMG → install
```
