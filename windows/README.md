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

## Packaging (M6) — building the installer

`npm run build` produces the NSIS installer. Its `prebuild` step runs both
`sync-frontend.mjs` and `bundle-engine.mjs`:

- **`bundle-engine.mjs`** builds `src-tauri/engine-bundle/` — a full CPython
  venv with the (torch-free) engine deps plus the staged engine source. Tauri
  ships this folder as a resource (`bundle.resources`), so the installed app
  runs the engine without the user installing Python. **Build on Windows** —
  the C-extension wheels (`pyaudio`, `pyaudiowpatch`) are platform-specific.
- At runtime `engine.rs` resolves the bundled `engine-bundle/venv/Scripts/
  python.exe` + `main.py` from the Tauri resource dir (falling back to the dev
  M2 venv when running from the repo).

The installer also configures:

- **WebView2**: `downloadBootstrapper` — installs the runtime if missing
  (preinstalled on Windows 11; fetched on Windows 10).
- **NSIS**: `currentUser` install — no admin elevation.

```powershell
cd windows
npm install
npm run icons          # one-time
npm run build          # -> src-tauri/target/release/bundle/nsis/Fluent_x.y.z_x64-setup.exe
```

### Auto-update — one-time key generation (required before first build)

The updater needs a signing keypair. Generate it once:

```powershell
npm run tauri signer generate -- -w %USERPROFILE%\.tauri\fluent-updater.key
```

This prints (and writes) a **private key** (keep secret — never commit; store
in a password manager / CI secret) and a **public key**. Put the public key in
`src-tauri/tauri.conf.json` → `plugins.updater.pubkey`, replacing
`REPLACE_WITH_UPDATER_PUBLIC_KEY`. Until this is done, `npm run build` will
fail (by design — it prevents shipping an unverifiable updater).

To sign update artifacts at build time, set the private key in the environment:

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $env:USERPROFILE\.tauri\fluent-updater.key -Raw
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "<the password you set>"
npm run build
```

The build emits a `.sig` next to the installer. Publishing is automated:
pushing a `vX.Y.Z` tag (matching `src-tauri/tauri.conf.json`'s `version`)
triggers `.github/workflows/windows-build.yml`, which generates
`website/windows/updates/latest.json` and commits it plus the signed
installer to the website — see `windows/scripts/generate-latest-json.mjs`.
Installed apps discover the update via `plugins.updater.endpoints` and
self-update on next launch (`windows/src-tauri/src/update.rs`).

> **First release footgun:** the updater only installs when the manifest
> version is strictly greater than what's installed. If users already have
> `0.1.0`, tagging `v0.1.0` will pass CI's tag/version-match guard but publish
> a no-op update — bump `tauri.conf.json`'s `version` above whatever is
> already in users' hands before cutting the first automated release tag.

### Authenticode signing (Azure Trusted Signing)

Signing is configured via `bundle.windows.signCommand` in `tauri.conf.json`:

```
trusted-signing-cli -e https://neu.codesigning.azure.net/ -a fluent -c fluent-public %1
```

This signs the built installer with **Azure Trusted Signing** (a.k.a. Artifact
Signing), Public Trust profile, issued to **NEW HARBOR CAPITAL LTD**. Signed
builds are SmartScreen-clean (no "unknown publisher" warning). The identity is:

- Endpoint: `https://neu.codesigning.azure.net/` (North Europe)
- Account: `fluent` · Certificate profile: `fluent-public`

**One-time setup on the build machine (Windows):**

1. Install the signing CLI (needs the Rust toolchain):
   ```powershell
   cargo install trusted-signing-cli
   ```
2. Authenticate to Azure. `trusted-signing-cli` uses the standard Azure
   credential chain, so either:
   - `az login` (Azure CLI) as a user holding the **"Trusted Signing
     Certificate Profile Signer"** role on the `fluent` account, OR
   - a service principal via env vars: `AZURE_TENANT_ID`,
     `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (recommended for CI).

**Build a signed installer:**

```powershell
cd windows
# updater key (as above)
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $env:USERPROFILE\.tauri\fluent-updater.key -Raw
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "<updater key password>"
# Azure auth: either `az login` beforehand, or set AZURE_* env vars here
npm run build
```

Tauri runs the `signCommand` on the produced `.exe`. **Verify** the result:

```powershell
signtool verify /pa /v src-tauri\target\release\bundle\nsis\Fluent_*-setup.exe
```

Expect "Successfully verified" with NEW HARBOR CAPITAL LTD as the signer. If
`signtool` isn't on PATH it ships with the Windows SDK (under
`...\Windows Kits\10\bin\<ver>\x64\signtool.exe`).

> If `signCommand` is present but Azure auth is missing, the build fails at the
> sign step. To produce an unsigned test build, temporarily remove the
> `signCommand` line.
