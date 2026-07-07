# Mac auto-update via Sparkle

## Problem

The Mac app (native Swift menu-bar + WebView app) has no update mechanism at
all. `release.sh` builds, Developer-ID-signs, notarizes, packages a DMG,
notarizes/staples the DMG, and copies it to `website/Fluent.dmg` — but that's
where it stops. There's no Sparkle framework, no `SUFeedURL`, no "check for
updates" code anywhere in the Swift source, and no CI for Mac releases at all
(unlike Windows, which now builds/signs/publishes from a GitHub Actions
workflow on tag push). Every Mac user must notice a new DMG exists and
manually re-download and reinstall it.

Version numbering is also currently decorative: `CFBundleShortVersionString`
(currently `1.2`) is hand-edited in Info.plist, and git tags like `v0.1.1`
exist but `release.sh` never reads them or cross-checks them against anything.

## Goal

Ship Sparkle-based silent auto-updates for the Mac app, matching the
Windows app's update UX (check automatically, download, verify, and install
in the background with no user prompt) while respecting two real differences
from Windows: releases stay a **local, manual** process (not CI — see
"Non-goals"), and the update install is deferred to the app's next natural
quit rather than forced immediately, since an update download can complete
while a coaching session or the engine subprocess is active.

### Non-goals

- **No move to GitHub Actions / CI for Mac releases.** `release.sh` continues
  to run locally, using the Developer ID cert and notarytool keychain
  profile already on this machine. Exporting those credentials to CI is a
  separate, larger decision not made here — and avoids reproducing the
  CI-secrets class of failure (a permissions gap surfacing at the last step)
  that hit the Windows release.
- **No update-prompt UI.** Updates are fully silent, matching Windows. No
  "a new version is available" dialog, no release-notes viewer.
- **No Mac App Store distribution change.** Distribution stays direct
  (Developer ID + notarization), unrelated to this effort.

## Design

### Client integration (Sparkle)

- Add Sparkle as a Swift Package Manager dependency in `Fluent.xcodeproj`
  (File > Add Package Dependencies → `sparkle-project/Sparkle`). No binaries
  committed to the repo; Xcode pins the version via `Package.resolved`.
- `AppDelegate` owns an `SPUStandardUpdaterController`, started in
  `applicationDidFinishLaunching` alongside the existing menu setup and
  engine bring-up. No delegate customization needed for silent behavior —
  it's driven entirely by Info.plist keys (below).
- New `Info.plist` keys:
  - `SUFeedURL` = `https://www.tryfluent.co/mac/updates/appcast.xml`
  - `SUPublicEDKey` = the Sparkle EdDSA public key (from one-time key
    generation, below)
  - `SUEnableAutomaticChecks` = `true`
  - `SUScheduledCheckInterval` = `86400` (24h) — combined with Sparkle's
    default check-on-launch, this covers the fact that Fluent is a
    long-lived menu-bar app that may not be relaunched often.
  - `SUAutomaticallyUpdate` = `true` and Sparkle's automatic-download
    behavior configured so no permission dialog appears at any stage
    (check, download, or verify) — fully silent end to end, matching
    Windows.
- **Relaunch timing:** Sparkle's standard "install on quit" behavior is
  used as-is (no custom installer invocation). Once a downloaded update is
  verified, Sparkle stages it and swaps the app bundle the next time the
  user quits Fluent normally — never force-terminating mid-session. This
  requires no new coordination with the engine subprocess:
  `applicationWillTerminate` already terminates `engineProcess` on quit.

### One-time signing key setup

- Run Sparkle's `generate_keys` CLI tool once, locally. It generates an
  EdDSA keypair and stores the private key in the login Keychain (item
  `Private key for signing Sparkle updates`) — same trust model as the
  existing `fluent-notary` notarytool keychain profile, no separate
  password to manage or lose.
- The printed public key is pasted into `Info.plist` as `SUPublicEDKey`
  (committed to the repo — it's public by design).
- `release.sh` calls Sparkle's `sign_update` CLI at publish time, which
  reads the private key from Keychain automatically. If the key isn't
  present, `sign_update` fails immediately — `release.sh` checks for this
  up front (before the slow notarization steps) and aborts with a clear
  error rather than producing a broken appcast entry later.

### Release pipeline (`release.sh`, extended)

`release.sh` remains a local script. After the existing DMG
notarize/staple steps, it gains:

1. **Version stamping.** `release.sh` now takes the release version
   explicitly (e.g. `bash release.sh 1.3`) and stamps it into
   `CFBundleShortVersionString` before building, bumping `CFBundleVersion`
   (the build number) alongside it. This replaces today's silent manual
   Info.plist edits and gives Sparkle the real, monotonically increasing
   version signal it needs to detect updates. The script also checks that
   an annotated tag `vX.Y.Z` matching this version exists (or offers to
   create it), reusing the same tag-based release-notes convention
   Windows uses (`git tag -l --format='%(contents)'`, falling back to the
   commit subject).
2. **Zip the notarized app.** The same `.app` already signed and notarized
   for the DMG is `ditto`-zipped (Sparkle's expected update-artifact
   format — simpler for Sparkle to unpack/swap than a DMG, and what its
   `generate_appcast` tooling expects).
3. **Sign the zip.** Run Sparkle's `sign_update` on the zip; capture the
   returned signature and file length.
4. **Generate the appcast.** Regenerate
   `website/mac/updates/appcast.xml` with the new version, signature,
   length, download URL, pubDate, and release notes (from the tag
   message). Either Sparkle's own `generate_appcast` tool (pointed at a
   local folder containing just the new zip) or a small hand-rolled
   generator can produce this — decide during implementation planning,
   mirroring the structure of `windows/scripts/generate-latest-json.mjs`.
5. **Publish.** Copy the signed zip into `website/mac/updates/`, commit
   both the zip and `appcast.xml` (message
   `release(mac): publish vX.Y.Z`), and push to `main`. Vercel's existing
   deploy-on-push picks it up — no Vercel config changes.
6. The existing DMG output (`website/Fluent.dmg`) is unchanged and remains
   the artifact for fresh, non-updating downloads from the website.

### Error handling

- Missing Sparkle Keychain key at publish time → `release.sh` aborts
  early with a clear message, before notarization.
- Appcast fetch failure (offline, DNS, site down) at runtime → Sparkle
  silently retries on its next scheduled check; no user-facing error,
  consistent with fully-silent behavior.
- Signature verification failure on a downloaded update → Sparkle
  discards it and does not retry that same version; this is Sparkle's
  built-in behavior, protecting against a corrupted or tampered artifact.
- Tag/version mismatch (annotated tag doesn't match the version passed to
  `release.sh`) → abort before any build step, same fail-fast principle
  used in the Windows pipeline.

### Testing / validation plan

Given releases stay local (no CI to dry-run against), the proof is two
real, sequential releases rather than a simulation — directly addressing
the three failure classes that hit the Windows release on its first real
run (a lost/mismatched signing key password, a script bug that only
manifested on the target OS's path format, and a permissions gap that
only surfaced at the last step):

1. **Release A** — cut the current in-flight version through the
   Sparkle-enabled `release.sh`. This version has no predecessor to
   update *from* (it's the last version anyone has to manually download),
   but it proves the full publish pipeline end-to-end: key lookup
   succeeds, the zip signs, the appcast generates and validates, files
   land correctly on the website, and the app launches normally with
   Sparkle wired in (finding nothing newer than itself).
2. **Release B** — bump the version again and cut a second real release
   through `release.sh`. With the user watching, confirm a running
   *installed* copy of Release A actually detects Release B (on its next
   launch or 24h check — temporarily lowering `SUScheduledCheckInterval`
   for the test is acceptable), downloads it, verifies the signature, and
   silently applies it on next quit, ending up on Release B.

This two-release run is a required step before considering this work
done — code review and a clean build are not sufficient on their own,
per what actually broke on the Windows release.
