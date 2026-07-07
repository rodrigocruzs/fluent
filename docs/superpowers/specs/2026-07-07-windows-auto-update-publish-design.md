# Windows auto-update publish pipeline

## Problem

The Windows app (Tauri shell) already ships with the `tauri-plugin-updater`
wired in: on every launch, `windows/src-tauri/src/update.rs` checks
`https://www.tryfluent.co/windows/updates/latest.json` for a newer signed
release, and downloads/installs/relaunches if one is found
(`windows/src-tauri/src/lib.rs`). The endpoint is configured in
`windows/src-tauri/tauri.conf.json` under `plugins.updater`, with a minisign
`pubkey` already set.

That endpoint currently returns **404** — nothing ever generates or publishes
`latest.json`. `windows/README.md` even documents the gap directly: "Publish
the installer + a `latest.json` manifest ... at the configured endpoint" is
left as a manual instruction that has never been carried out. Today, shipping
a new Windows build means downloading the signed installer from the GitHub
Actions run and manually `git commit`-ing it into `website/Fluent-Setup.exe` —
the updater never sees it, so installed apps never update themselves.

## Goal

Automate the missing publish step so that pushing a version tag is the entire
release process: CI builds, signs, generates `latest.json`, and publishes both
it and the installer to the website. Installed Fluent Windows apps then
discover and self-update on their next launch.

Out of scope: the Mac app has no update mechanism at all (no Sparkle); adding
one is a separate, larger effort and not addressed here.

## Design

### Trigger and versioning

- `windows/src-tauri/tauri.conf.json`'s `"version"` field remains the source
  of the app's version, bumped by hand before a release.
- A release is cut by committing that bump, then
  `git tag -a vX.Y.Z -m "<release notes>"` and `git push --tags`.
- `windows-build.yml` keeps both its existing triggers
  (`workflow_dispatch` and `push: tags: v*`), but the new publish step only
  runs when the ref is a tag (`startsWith(github.ref, 'refs/tags/v')`).
  `workflow_dispatch` runs still build, sign, and upload the installer as a
  build artifact (useful for test builds) but do not publish to the website.
- On a tag-triggered run, CI parses the version out of the tag name and
  compares it against `tauri.conf.json`'s `version`. A mismatch fails the job
  immediately with a clear error, before any publish happens — tag and
  installer version can never drift.

### Release notes

- CI reads the annotated tag's message (`git tag -l --format='%(contents)' vX.Y.Z`)
  and uses it verbatim as `latest.json`'s `"notes"` field.
- If the tag has no message (lightweight tag), fall back to the subject line
  of the commit the tag points at.
- These notes are not currently surfaced in any UI (`update.rs` runs the
  updater silently), but are cheap to populate now for when an update-visible
  UI is added later.

### Publish step (new)

Added to `.github/workflows/windows-build.yml`, after the existing
build/sign steps, gated on the tag-push condition above:

1. Confirm the tag version matches `tauri.conf.json` (fail-fast check above).
2. Locate the build outputs already produced by `tauri build`:
   `windows/src-tauri/target/release/bundle/nsis/*-setup.exe` and its
   `.sig` sibling (already generated today — the updater signing key,
   `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, is
   already present as a CI secret and already used in the "Build Windows
   installer" step).
3. Read the `.sig` file's contents (a base64 minisign signature — this is
   Tauri's standard updater artifact, consumed as-is).
4. Generate `website/windows/updates/latest.json` matching the schema the
   `tauri-plugin-updater` client expects:

   ```json
   {
     "version": "0.1.1",
     "notes": "<tag message or fallback commit subject>",
     "pub_date": "<UTC ISO8601 timestamp, e.g. 2026-07-07T12:00:00Z>",
     "platforms": {
       "windows-x86_64": {
         "signature": "<contents of the .sig file>",
         "url": "https://www.tryfluent.co/Fluent-Setup.exe"
       }
     }
   }
   ```

5. Copy the signed installer to `website/Fluent-Setup.exe`, overwriting the
   existing file at that path (this is the same path the site's download
   button already links to — no change needed to `website/index.html`).
6. Commit both changed files
   (`website/windows/updates/latest.json`, `website/Fluent-Setup.exe`) to
   `main` with message `release(windows): publish vX.Y.Z`, and push.
7. Vercel's existing deploy-on-push picks up the change; no Vercel config
   changes needed.

### Client behavior (unchanged)

`update.rs` and `lib.rs` are already correct and need no changes. Once
`latest.json` resolves with a real, higher version and a valid signature, the
existing background check on app launch will download, verify, install, and
relaunch — silently, per its current "best-effort" design.

### Failure handling

If the publish step fails (e.g. a push conflict or branch protection), the
build/sign/artifact-upload steps have already succeeded and the signed
installer + `.sig` remain available as a GitHub Actions artifact for manual
recovery — a publish failure does not lose the signed binary, only requires
retrying the publish.

### Testing plan

- Verify the version-mismatch guard fails the job when the tag doesn't match
  `tauri.conf.json`.
- Verify a `workflow_dispatch` run builds/signs/uploads the artifact but does
  not touch `website/`.
- Verify a tagged run produces a `latest.json` that validates against the
  Tauri updater schema (correct field names, valid base64 signature, working
  URL) and that an old installed build picks it up and updates successfully
  end-to-end on a real Windows machine/VM.
