# Fluent for Windows (Tauri shell)

The Windows native shell for Fluent — a Tauri (Rust + WebView2) host that
replaces the macOS Swift app (`../fluent/`). It:

- loads the shared web UI from `../frontend/` (unchanged across platforms),
- spawns and supervises the Python engine (`../fluent-engine/`) on port 2788,
- bridges authenticated API calls to `tryfluent.co/api` (the `apiRequest`
  bridge, ported from `WebViewController.swift`),
- runs as a system-tray app.

See the full plan at `~/.claude/plans/federated-roaming-lollipop.md` and the
project memory `fluent-windows-port-scoping`.

## Layout

- `src-tauri/` — the Rust host (Cargo crate + `tauri.conf.json`).
- `src/` — the thin web entry: a bridge shim that emulates the WebKit
  `window.webkit.messageHandlers.*` interface on top of Tauri `invoke`, then
  loads the shared `../../frontend/` assets. This keeps ONE frontend for both
  OSes — `report.js` runs unchanged.

## Dev prerequisites (Windows laptop)

1. Rust: https://rustup.rs  (`rustup` installer)
2. Node.js LTS: https://nodejs.org  (or `winget install OpenJS.NodeJS.LTS`)
3. WebView2 runtime: preinstalled on Windows 11; on Windows 10 the Tauri
   bundler ships a bootstrapper.
4. The engine venv already set up at `..\fluent-engine\venv` (M2).

## Run (dev)

```powershell
cd windows
npm install
npm run icons      # one-time: generate src-tauri/icons/* from icon-source.png
npm run dev        # runs sync-frontend then `tauri dev`
```

`npm run dev` first runs `sync-frontend.mjs` (copies `../frontend/*` into
`src/` and writes `index.html` with the bridge shim), then `tauri dev`.

The host launches the engine from `..\fluent-engine\venv\Scripts\python.exe`
running `..\fluent-engine\main.py` (the venv from M2). It kills any stale
listener on port 2788 first, then supervises the engine with restart/backoff.

## Notes

- `src/` is a generated artifact (from `sync-frontend.mjs`) — do not hand-edit;
  edit `../frontend/` instead. `tauri-bridge.js` is the one Windows-only web
  file and lives in `src/` directly.
- The JWT is read from Windows Credential Manager (service `fluent`, account
  `jwt_token`) — the same entry the engine writes via `platform/win.py`.
