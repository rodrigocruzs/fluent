# Mac Auto-Update via Sparkle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship silent, self-applying auto-updates for the Mac app using Sparkle, matching the Windows app's update UX, with releases still cut locally via `release.sh`.

**Architecture:** Sparkle (added via Swift Package Manager) runs inside the Mac app, polling a signed `appcast.xml` hosted on the existing website. `release.sh` gains steps to stamp the version, zip the already-notarized `.app`, sign it with Sparkle's `sign_update` CLI (key stored in Keychain), regenerate the appcast via a new Node script, and publish both to `website/mac/updates/`. Updates download and verify silently and install on the app's next natural quit — no CI changes, no prompts.

**Tech Stack:** Swift / Cocoa, Sparkle 2.x (SPM), Xcode project file edits, Node.js (appcast generator script, mirroring `windows/scripts/generate-latest-json.mjs`), bash (`release.sh`).

## Global Constraints

- Releases stay local — no GitHub Actions changes, no Developer ID cert or notarytool credentials exported to CI.
- Updates are fully silent: no update-availability dialog, no release-notes viewer UI.
- Updates install on the app's next natural quit, never a forced/immediate relaunch.
- Sparkle's EdDSA private key lives in the macOS login Keychain (via `generate_keys`), never in a file or the repo.
- `SUPublicEDKey` (public key) is committed to `Info.plist` — it is public by design.
- Appcast and signed update zip are hosted at `website/mac/updates/` (appcast at `https://www.tryfluent.co/mac/updates/appcast.xml`).
- Update artifact format is a signed `.zip` of the notarized `.app`; the existing `.dmg` remains the fresh-install artifact and is unchanged.
- Check cadence: on launch + every 24h (`SUScheduledCheckInterval = 86400`).
- Version source of truth becomes an explicit argument to `release.sh`, cross-checked against an annotated git tag `vX.Y.Z` — no more silent manual `Info.plist` edits.

---

## Task 1: One-time Sparkle signing keypair

**Files:**
- None created/modified by this task — this is a local one-time machine setup step, documented so it's reproducible if this Mac is ever replaced.
- Create: `docs/mac-sparkle-keysetup.md` (short, reproducible setup notes — analogous to the existing `fluent-notary` keychain profile comment in `release.sh`)

**Interfaces:**
- Produces: a Keychain item named `Private key for signing Sparkle updates` (read by `sign_update` in Task 5), and a printed EdDSA public key string (consumed by Task 3, embedded as `SUPublicEDKey`).

- [ ] **Step 1: Download the Sparkle release tools**

```bash
cd /tmp
curl -LO https://github.com/sparkle-project/Sparkle/releases/download/2.9.4/Sparkle-2.9.4.tar.xz
tar -xf Sparkle-2.9.4.tar.xz -C /tmp/sparkle-2.9.4
ls /tmp/sparkle-2.9.4/bin
```

Expected: a `bin/` directory containing `generate_keys`, `sign_update`, `generate_appcast`, and a few other tools.

- [ ] **Step 2: Generate the keypair**

```bash
/tmp/sparkle-2.9.4/bin/generate_keys
```

Expected output includes a line like:
```
Public key (SUPublicEDKey): <base64 string>
```
The private key is stored in the login Keychain automatically (item: "Private key for signing Sparkle updates"). Copy the printed public key string — it's needed in Task 3.

- [ ] **Step 3: Verify the key is retrievable**

```bash
/tmp/sparkle-2.9.4/bin/generate_keys -p
```

Expected: prints the same public key as Step 2, confirming `sign_update` will be able to find the private key later.

- [ ] **Step 4: Write setup notes**

Create `docs/mac-sparkle-keysetup.md`:

```markdown
# Mac Sparkle signing key setup (one-time, per-machine)

Fluent's Mac auto-updates are signed with a Sparkle EdDSA keypair, generated
once and stored in this machine's login Keychain. `release.sh` reads it via
Sparkle's `sign_update` CLI at publish time — no password to manage
separately.

## If this Mac is ever replaced

1. Download the Sparkle CLI tools (`generate_keys`, `sign_update`,
   `generate_appcast`) from
   https://github.com/sparkle-project/Sparkle/releases — grab the
   `Sparkle-X.Y.Z.tar.xz` asset (not the SPM zip), and extract `bin/`.
2. Run `generate_keys` once. It stores the private key in the login
   Keychain automatically.
3. Update `SUPublicEDKey` in `fluent/Fluent/Info.plist` with the newly
   printed public key.

**Do not generate a new keypair if the old Keychain/Mac is still
available** — every app already in the wild trusts the original public key
baked into its `Info.plist`. A new keypair breaks auto-updates for everyone
already installed; they'd need to manually reinstall once more.
```

- [ ] **Step 5: Commit**

```bash
git add docs/mac-sparkle-keysetup.md
git commit -m "docs: document Mac Sparkle signing key setup"
```

---

## Task 2: Add Sparkle as a Swift Package Manager dependency

**Files:**
- Modify: `fluent/Fluent.xcodeproj/project.pbxproj` (via Xcode UI, not hand-edited)

**Interfaces:**
- Produces: the `Sparkle` Swift module, importable as `import Sparkle` in `AppDelegate.swift` (Task 4).

- [ ] **Step 1: Add the package dependency in Xcode**

Open `fluent/Fluent.xcodeproj` in Xcode. File > Add Package Dependencies…
Enter the URL: `https://github.com/sparkle-project/Sparkle`
Choose "Up to Next Major Version" starting from `2.7.0` (current stable line as of this plan). Add the `Sparkle` library product to the `Fluent` target.

- [ ] **Step 2: Verify it resolves and builds**

```bash
cd /Users/rodrigocruzsouza/fluent/fluent
xcodebuild -project Fluent.xcodeproj -scheme Fluent -configuration Debug build 2>&1 | tail -20
```

Expected: `** BUILD SUCCEEDED **`, and a new `Package.resolved` file appears next to `project.pbxproj`.

- [ ] **Step 3: Commit**

```bash
git add fluent/Fluent.xcodeproj
git commit -m "build(mac): add Sparkle as an SPM dependency"
```

---

## Task 3: Add Sparkle Info.plist keys

**Files:**
- Modify: `fluent/Fluent/Info.plist`

**Interfaces:**
- Consumes: the public key string printed in Task 1, Step 2.
- Produces: the `SUFeedURL`, `SUPublicEDKey`, `SUEnableAutomaticChecks`, `SUScheduledCheckInterval`, and `SUAutomaticallyUpdate` keys that `SPUStandardUpdaterController` (Task 4) reads at runtime.

- [ ] **Step 1: Add the Sparkle keys**

Edit `fluent/Fluent/Info.plist`, adding these entries inside the top-level `<dict>` (alphabetical placement doesn't matter to Xcode, but keep them grouped together with a comment for readability):

```xml
	<key>SUFeedURL</key>
	<string>https://www.tryfluent.co/mac/updates/appcast.xml</string>
	<key>SUPublicEDKey</key>
	<string>PASTE_PUBLIC_KEY_FROM_TASK_1_HERE</string>
	<key>SUEnableAutomaticChecks</key>
	<true/>
	<key>SUScheduledCheckInterval</key>
	<integer>86400</integer>
	<key>SUAutomaticallyUpdate</key>
	<true/>
```

Replace `PASTE_PUBLIC_KEY_FROM_TASK_1_HERE` with the actual public key string generated in Task 1.

- [ ] **Step 2: Verify the plist is well-formed**

```bash
plutil -lint /Users/rodrigocruzsouza/fluent/fluent/Fluent/Info.plist
```

Expected: `Info.plist: OK`

- [ ] **Step 3: Commit**

```bash
git add fluent/Fluent/Info.plist
git commit -m "build(mac): add Sparkle Info.plist configuration"
```

---

## Task 4: Wire SPUStandardUpdaterController into AppDelegate

**Files:**
- Modify: `fluent/Fluent/AppDelegate.swift:1-48` (imports and `applicationDidFinishLaunching`)

**Interfaces:**
- Consumes: `Sparkle` module (Task 2), Info.plist keys (Task 3).
- Produces: `AppDelegate.updaterController` (a stored `SPUStandardUpdaterController`), kept alive for the app's lifetime so Sparkle's background checks keep running.

- [ ] **Step 1: Add the import and stored property**

In `fluent/Fluent/AppDelegate.swift`, add the import at the top:

```swift
import Cocoa
import UserNotifications
import AVFoundation
import Sparkle
```

Add a new stored property near the other controllers (after line 10, `private var setupWindowController: EngineSetupWindowController?`):

```swift
    private var updaterController: SPUStandardUpdaterController!
```

- [ ] **Step 2: Start the updater in applicationDidFinishLaunching**

In `applicationDidFinishLaunching` (currently lines 34-48), add the updater start. Insert it right after `setupMenu()`:

```swift
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupMenu()

        updaterController = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )

        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        DarwinNotificationBridge.shared.startListening(name: "com.fluent.reportReady") { [weak self] in
            DispatchQueue.main.async { self?.showLatestReport() }
        }

        requestMicrophonePermission()
        setupEngineIfNeeded()
        showReport()
    }
```

`startingUpdater: true` makes Sparkle begin its automatic check/download cycle immediately using the Info.plist configuration from Task 3 — no further calls needed for fully-silent behavior.

- [ ] **Step 3: Build and verify no crash on launch**

```bash
cd /Users/rodrigocruzsouza/fluent/fluent
xcodebuild -project Fluent.xcodeproj -scheme Fluent -configuration Debug build 2>&1 | tail -20
open build/Debug/Fluent.app 2>/dev/null || open /Users/rodrigocruzsouza/fluent/fluent/Fluent/build/Debug/Debug/Fluent.app
```

Expected: build succeeds, app launches normally (menu bar appears, report window shows). Since `SUFeedURL` points at a URL that doesn't exist yet (Task 7 publishes it for the first time), Sparkle's background check will fail silently — this is expected and fine at this stage; it should not crash or show any dialog.

- [ ] **Step 4: Commit**

```bash
git add fluent/Fluent/AppDelegate.swift
git commit -m "feat(mac): start Sparkle updater on launch"
```

---

## Task 5: Appcast generator script

**Files:**
- Create: `fluent/scripts/generate-appcast.mjs`
- Test: `fluent/scripts/generate-appcast.test.mjs`

**Interfaces:**
- Consumes: version string, release notes text, Sparkle `sign_update` output (signature + file length), download URL.
- Produces: `generateAppcast({ version, notes, pubDate, signature, length, downloadUrl })` returning an XML string; a CLI entry point writing that string to a file. Consumed by `release.sh` in Task 6.

This mirrors `windows/scripts/generate-latest-json.mjs`'s structure (library function + CLI wrapper + a sibling `.test.mjs`), adapted to Sparkle's appcast XML schema instead of Tauri's `latest.json` schema.

- [ ] **Step 1: Write the failing test**

Create `fluent/scripts/generate-appcast.test.mjs`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateAppcast } from "./generate-appcast.mjs";

test("generateAppcast produces a valid Sparkle appcast item", () => {
  const xml = generateAppcast({
    version: "1.3",
    notes: "Fixed a bug with session history.",
    pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
    signature: "abc123base64==",
    length: 45678,
    downloadUrl: "https://www.tryfluent.co/mac/updates/Fluent-1.3.zip",
  });

  assert.match(xml, /<rss xmlns:sparkle="http:\/\/www\.andymatuschak\.org\/xml-namespaces\/sparkle" version="2\.0">/);
  assert.match(xml, /<sparkle:version>1\.3<\/sparkle:version>/);
  assert.match(xml, /<sparkle:shortVersionString>1\.3<\/sparkle:shortVersionString>/);
  assert.match(xml, /url="https:\/\/www\.tryfluent\.co\/mac\/updates\/Fluent-1\.3\.zip"/);
  assert.match(xml, /length="45678"/);
  assert.match(xml, /sparkle:edSignature="abc123base64=="/);
  assert.match(xml, /<pubDate>Tue, 07 Jul 2026 12:00:00 \+0000<\/pubDate>/);
  assert.match(xml, /Fixed a bug with session history\./);
});

test("generateAppcast rejects a version with a leading v", () => {
  assert.throws(
    () =>
      generateAppcast({
        version: "v1.3",
        notes: "x",
        pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
        signature: "sig",
        length: 1,
        downloadUrl: "https://example.com/x.zip",
      }),
    /must not include a leading "v"/
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/rodrigocruzsouza/fluent/fluent/scripts
node --test generate-appcast.test.mjs
```

Expected: FAIL — `generate-appcast.mjs` does not exist yet (`Cannot find module`).

- [ ] **Step 3: Write the implementation**

Create `fluent/scripts/generate-appcast.mjs`:

```javascript
// Generates website/mac/updates/appcast.xml, the feed Sparkle's
// SPUStandardUpdaterController polls (see SUFeedURL in
// fluent/Fluent/Info.plist). Schema:
// https://sparkle-project.org/documentation/publishing/
//
// Used both as a library (generateAppcast, for tests) and as a CLI:
//   node generate-appcast.mjs <version> <notesFile> <signature> <length> <downloadUrl> <outFile>

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { pathToFileURL } from "node:url";

function escapeXml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function generateAppcast({ version, notes, pubDate, signature, length, downloadUrl }) {
  if (version.startsWith("v")) {
    throw new Error('version must not include a leading "v" (strip the tag prefix first)');
  }

  return `<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>Fluent Changelog</title>
    <link>${downloadUrl.replace(/\/[^/]*$/, "/appcast.xml")}</link>
    <description>Most recent changes for Fluent on macOS.</description>
    <language>en</language>
    <item>
      <title>Version ${escapeXml(version)}</title>
      <description><![CDATA[${notes}]]></description>
      <pubDate>${pubDate}</pubDate>
      <sparkle:version>${escapeXml(version)}</sparkle:version>
      <sparkle:shortVersionString>${escapeXml(version)}</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      <enclosure
        url="${escapeXml(downloadUrl)}"
        length="${length}"
        type="application/octet-stream"
        sparkle:edSignature="${escapeXml(signature)}"
      />
    </item>
  </channel>
</rss>
`;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const [, , version, notesFile, signature, length, downloadUrl, outFile] = process.argv;
  if (!version || !notesFile || !signature || !length || !downloadUrl || !outFile) {
    console.error(
      "usage: generate-appcast.mjs <version> <notesFile> <signature> <length> <downloadUrl> <outFile>"
    );
    process.exit(1);
  }

  const notes = readFileSync(notesFile, "utf8").trim();
  const pubDate = new Date().toUTCString();

  const xml = generateAppcast({ version, notes, pubDate, signature, length: Number(length), downloadUrl });

  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, xml);
  console.log(`[generate-appcast] wrote ${outFile} (version ${version})`);
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/rodrigocruzsouza/fluent/fluent/scripts
node --test generate-appcast.test.mjs
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fluent/scripts/generate-appcast.mjs fluent/scripts/generate-appcast.test.mjs
git commit -m "feat(mac): add appcast.xml generator script"
```

---

## Task 6: Extend release.sh — version stamping, zip, sign, publish

**Files:**
- Modify: `release.sh` (full rewrite of the tail end, after the existing DMG stapling step)

**Interfaces:**
- Consumes: `generateAppcast` CLI (Task 5), Sparkle `sign_update`/sizes (from the Task 1 download, expected at a fixed local path — see Step 1), a version argument.
- Produces: `website/mac/updates/appcast.xml`, `website/mac/updates/Fluent-<version>.zip`, an updated `fluent/Fluent/Info.plist` with the new `CFBundleShortVersionString`/`CFBundleVersion`.

- [ ] **Step 1: Install the Sparkle CLI tools at a stable local path**

These tools are needed every release, so move them out of `/tmp` (used only for the one-time Task 1 exploration) into a permanent location:

```bash
mkdir -p ~/.local/sparkle-cli
curl -L https://github.com/sparkle-project/Sparkle/releases/download/2.9.4/Sparkle-2.9.4.tar.xz -o /tmp/Sparkle-2.9.4.tar.xz
tar -xf /tmp/Sparkle-2.9.4.tar.xz -C ~/.local/sparkle-cli
ls ~/.local/sparkle-cli/bin/sign_update
```

Expected: `~/.local/sparkle-cli/bin/sign_update` exists and is executable.

- [ ] **Step 2: Add version argument handling and tag check to release.sh**

Edit `release.sh`. Replace the header (lines 1-24) with a version that requires and validates a version argument:

```bash
#!/usr/bin/env bash
# Full release: build → sign → notarize app → DMG → notarize+staple DMG → install
#              → zip+sign for Sparkle → generate appcast → publish.
#
# Builds via xcodebuild (uses committed source, including frontend/ + fluent-engine/),
# Developer ID signs with hardened runtime, notarizes both the app and the DMG so
# Gatekeeper trusts the downloaded disk image, then installs to /Applications.
# Finally produces a signed update zip + appcast.xml for Sparkle auto-updates.
#
# Usage: bash release.sh <version>   e.g. bash release.sh 1.3
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "usage: bash release.sh <version>   e.g. bash release.sh 1.3" >&2
  exit 1
fi
if [[ "$VERSION" == v* ]]; then
  echo "ERROR: pass the version without a leading 'v' (e.g. 1.3, not v1.3)" >&2
  exit 1
fi

TAG="v$VERSION"
TAG_MSG="$(git tag -l --format='%(contents)' "$TAG" 2>/dev/null || true)"
if [ -z "$TAG_MSG" ]; then
  echo "ERROR: annotated tag '$TAG' not found. Create it first:" >&2
  echo "  git tag -a $TAG -m \"<release notes>\"" >&2
  exit 1
fi

SPARKLE_CLI="$HOME/.local/sparkle-cli/bin"
if [ ! -x "$SPARKLE_CLI/sign_update" ]; then
  echo "ERROR: Sparkle CLI tools not found at $SPARKLE_CLI" >&2
  echo "  See docs/mac-sparkle-keysetup.md to install them." >&2
  exit 1
fi
if ! "$SPARKLE_CLI/sign_update" --help >/dev/null 2>&1; then
  echo "ERROR: sign_update failed to run — check the Sparkle signing key is in Keychain (docs/mac-sparkle-keysetup.md)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
XCODE_PROJECT="$REPO_ROOT/fluent/Fluent.xcodeproj"
SCHEME="Fluent"
CONFIGURATION="Release"
BUILD_ROOT="$REPO_ROOT/fluent/build/Release"
APP_PATH="$BUILD_ROOT/Release/Fluent.app"
ENTITLEMENTS="$REPO_ROOT/fluent/Fluent/Fluent.entitlements"
WEBSITE_DIR="$REPO_ROOT/website"
DMG_PATH="$WEBSITE_DIR/Fluent.dmg"
UPDATES_DIR="$WEBSITE_DIR/mac/updates"
UPDATE_ZIP_PATH="$UPDATES_DIR/Fluent-$VERSION.zip"
APPCAST_PATH="$UPDATES_DIR/appcast.xml"
INFO_PLIST="$REPO_ROOT/fluent/Fluent/Info.plist"

SIGN_IDENTITY="Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)"
# Notarization uses a keychain profile created once with:
#   xcrun notarytool store-credentials "fluent-notary" \
#     --apple-id <apple-id> --team-id H28RYPBSMQ --password <app-specific-password>
# This keeps the app-specific password out of the repo.
NOTARY_PROFILE="fluent-notary"

# ── 0. Stamp the version into Info.plist ────────────────────────────────────
echo "==> Stamping version $VERSION into Info.plist..."
CURRENT_BUILD=$(plutil -extract CFBundleVersion raw "$INFO_PLIST")
NEW_BUILD=$((CURRENT_BUILD + 1))
plutil -replace CFBundleShortVersionString -string "$VERSION" "$INFO_PLIST"
plutil -replace CFBundleVersion -string "$NEW_BUILD" "$INFO_PLIST"
echo "==> CFBundleShortVersionString=$VERSION CFBundleVersion=$NEW_BUILD"
```

- [ ] **Step 3: Verify the existing build/sign/notarize/DMG steps are untouched**

Read `release.sh` after your edit and confirm sections "1. Build" through "5. Sign + notarize + staple the DMG" (the existing xcodebuild, codesign, notarytool, create-dmg logic) are unchanged and still numbered sequentially after the new "0." step. No code changes needed there — just confirm nothing was accidentally deleted.

- [ ] **Step 4: Add the zip + sign + appcast + publish steps**

Append after the existing "## 6. Install to /Applications" section (the `ditto "$APP_PATH" /Applications/Fluent.app` block) and before the final "Done" echo block:

```bash
# ── 7. Zip the notarized app for Sparkle ────────────────────────────────────
echo "==> Zipping notarized app for Sparkle update feed..."
mkdir -p "$UPDATES_DIR"
rm -f "$UPDATE_ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$UPDATE_ZIP_PATH"
ZIP_LENGTH=$(stat -f%z "$UPDATE_ZIP_PATH")
echo "==> Zip: $UPDATE_ZIP_PATH ($ZIP_LENGTH bytes)"

# ── 8. Sign the update zip with Sparkle's EdDSA key ─────────────────────────
echo "==> Signing update zip (Sparkle EdDSA)..."
SIGN_OUTPUT=$("$SPARKLE_CLI/sign_update" "$UPDATE_ZIP_PATH")
# sign_update prints: sparkle:edSignature="..." length="..."
UPDATE_SIGNATURE=$(echo "$SIGN_OUTPUT" | grep -o 'sparkle:edSignature="[^"]*"' | sed 's/sparkle:edSignature="//;s/"$//')
if [ -z "$UPDATE_SIGNATURE" ]; then
  echo "ERROR: failed to parse signature from sign_update output:" >&2
  echo "$SIGN_OUTPUT" >&2
  exit 1
fi
echo "==> Signature: $UPDATE_SIGNATURE"

# ── 9. Generate the appcast ──────────────────────────────────────────────────
echo "==> Generating appcast.xml..."
NOTES_FILE=$(mktemp /tmp/fluent_release_notes_XXXXXX.txt)
printf '%s' "$TAG_MSG" > "$NOTES_FILE"
DOWNLOAD_URL="https://www.tryfluent.co/mac/updates/Fluent-$VERSION.zip"
node "$REPO_ROOT/fluent/scripts/generate-appcast.mjs" \
  "$VERSION" "$NOTES_FILE" "$UPDATE_SIGNATURE" "$ZIP_LENGTH" "$DOWNLOAD_URL" "$APPCAST_PATH"
rm -f "$NOTES_FILE"

# ── 10. Publish to the website ───────────────────────────────────────────────
echo "==> Publishing update artifacts..."
cd "$REPO_ROOT"
git add "$UPDATE_ZIP_PATH" "$APPCAST_PATH" "$INFO_PLIST"
git commit -m "release(mac): publish v$VERSION"
git push origin HEAD:main
```

- [ ] **Step 5: Update the final "Done" summary to mention the update feed**

Find the existing final echo block:

```bash
echo ""
echo "==> Done."
echo "    App:  /Applications/Fluent.app"
echo "    DMG:  $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
```

Replace with:

```bash
echo ""
echo "==> Done."
echo "    App:      /Applications/Fluent.app"
echo "    DMG:      $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Update:   $UPDATE_ZIP_PATH ($(du -sh "$UPDATE_ZIP_PATH" | cut -f1))"
echo "    Appcast:  $APPCAST_PATH"
echo "    Published to main — Vercel will deploy the update feed shortly."
```

- [ ] **Step 6: Commit**

```bash
git add release.sh
git commit -m "feat(mac): extend release.sh to publish signed Sparkle updates"
```

---

## Task 7: First real release — Release A (establish the pipeline)

**Files:** None (operational task — running the release pipeline for real).

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: the first live `website/mac/updates/appcast.xml` and `Fluent-<version>.zip` on the deployed site; confirms the whole publish pipeline works without a pre-existing appcast to compare against.

- [ ] **Step 1: Decide and tag the version**

Check the current version and bump it:

```bash
cd /Users/rodrigocruzsouza/fluent
plutil -extract CFBundleShortVersionString raw fluent/Fluent/Info.plist
```

Pick the next version (e.g. if current is `1.2`, use `1.3`). Create the annotated tag with real release notes:

```bash
git tag -a v1.3 -m "Add Sparkle-based auto-updates for Mac."
```

- [ ] **Step 2: Run the release**

```bash
cd /Users/rodrigocruzsouza/fluent
bash release.sh 1.3
```

Watch the output closely. Expected: all existing build/notarize/DMG steps succeed as before, followed by the new zip/sign/appcast/publish steps, ending in the updated "Done" summary showing the update zip and appcast paths, and a successful `git push`.

- [ ] **Step 3: Verify the published feed is live**

Wait for Vercel to deploy (check the Vercel dashboard or just poll), then:

```bash
curl -s https://www.tryfluent.co/mac/updates/appcast.xml
curl -sI https://www.tryfluent.co/mac/updates/Fluent-1.3.zip | head -5
```

Expected: the appcast XML is returned with `<sparkle:version>1.3</sparkle:version>`, and the zip URL returns `HTTP/2 200`.

- [ ] **Step 4: Verify the installed app runs cleanly against the live feed**

The app installed to `/Applications/Fluent.app` by `release.sh` in Task 7 Step 2 is already version 1.3 (there's nothing newer to find yet). Launch it and confirm no crash, no error dialog, and check Console.app (filter process "Fluent") for Sparkle log lines indicating a successful check that found no update:

```bash
open /Applications/Fluent.app
log show --predicate 'process == "Fluent"' --last 2m | grep -i sparkle
```

Expected: log lines showing a completed update check with no newer version available — no errors.

This step doesn't require a code change or commit; it's a live verification checkpoint before Task 8's real update test.

---

## Task 8: Second real release — Release B (prove the update path end-to-end)

**Files:** None (operational task).

**Interfaces:**
- Consumes: Release A already installed and running (Task 7).
- Produces: verified proof that an installed Release A app self-updates to Release B silently, on next quit, with no user interaction.

- [ ] **Step 1: Make a trivial, visible change and tag Release B**

Make a tiny, easy-to-verify change — e.g. bump a version-visible string in the Settings UI, or just rely on `CFBundleShortVersionString` itself as the visible marker. Tag it:

```bash
cd /Users/rodrigocruzsouza/fluent
git tag -a v1.4 -m "Test release: verify Sparkle end-to-end update path."
```

- [ ] **Step 2: Temporarily shorten the check interval for a fast test**

Editing a live installed app's Info.plist directly (not the repo) makes Release A check sooner, without needing to wait 24h:

```bash
sudo plutil -replace SUScheduledCheckInterval -integer 60 /Applications/Fluent.app/Contents/Info.plist
```

Note: this modifies the already-installed, already-signed app bundle in place, which invalidates its code signature for anything that checks it strictly — that's fine here since this copy is being retired anyway once the update test completes. Do not do this to a build you intend to keep signed/notarized.

- [ ] **Step 3: Ensure Release A is running**

```bash
open /Applications/Fluent.app
```

Confirm it's running and leave it running for the remainder of this task.

- [ ] **Step 4: Cut Release B while Release A keeps running**

In a separate terminal (don't touch the running `/Applications/Fluent.app` copy — `release.sh` will overwrite it, which is fine, since Sparkle's update mechanism is independent of what's on disk after launch):

```bash
cd /Users/rodrigocruzsouza/fluent
bash release.sh 1.4
```

Expected: same success path as Task 7 Step 2, publishing `Fluent-1.4.zip` and an updated `appcast.xml` with `<sparkle:version>1.4</sparkle:version>`.

- [ ] **Step 5: Watch Release A detect and apply the update**

Wait up to ~60-90 seconds (the shortened check interval from Step 2), then watch Console.app or tail logs:

```bash
log stream --predicate 'process == "Fluent"' | grep -i sparkle
```

Expected: log lines showing Release A found version 1.4, downloaded it, and verified its signature successfully. No dialog should appear (fully silent per the design).

- [ ] **Step 6: Quit Release A and confirm the update applied**

```bash
osascript -e 'quit app "Fluent"'
sleep 3
plutil -extract CFBundleShortVersionString raw /Applications/Fluent.app/Contents/Info.plist
```

Expected: prints `1.4` — confirming Sparkle swapped the app bundle on quit, per the "install on quit" design decision.

- [ ] **Step 7: Relaunch and confirm the updated app runs normally**

```bash
open /Applications/Fluent.app
```

Expected: app launches normally, menu bar appears, report window shows, no crash. This is the full proof: an installed app silently discovered, downloaded, verified, and applied an update with zero manual steps beyond a normal quit.

- [ ] **Step 8: Record the result**

No code changes in this task, but note the outcome (pass/fail, and any issues hit) back to the user — this is the gate the spec calls out as required before considering the work done. If any step failed, treat it as a bug to fix (in Tasks 1-6) and re-run Task 7 and Task 8 from scratch with a new version bump, rather than patching around it live.

---

## Self-Review Notes

- **Spec coverage:** SPM integration ✓ (Task 2), Info.plist keys ✓ (Task 3), silent check/download/install with no prompts ✓ (Task 3 `SUAutomaticallyUpdate`/Task 4 `startingUpdater: true`), install-on-quit behavior ✓ (relies on Sparkle's default — verified live in Task 8), Keychain-stored signing key ✓ (Task 1), zip update artifact alongside unchanged DMG ✓ (Task 6 Step 4), appcast generator mirroring the Windows script pattern ✓ (Task 5), version stamping + tag cross-check ✓ (Task 6 Step 2), local-only release (no CI) ✓ (all release tasks run `bash release.sh` locally), two-real-release validation plan ✓ (Tasks 7-8).
- **Placeholder scan:** no TBD/TODO markers; the one bracketed placeholder (`PASTE_PUBLIC_KEY_FROM_TASK_1_HERE` in Task 3) is intentional — the actual key is only known after Task 1 runs on this machine, and the step explicitly instructs replacing it.
- **Type/name consistency:** `generateAppcast` (Task 5) is called identically in its test and its CLI wrapper; `release.sh`'s Task 6 invocation of `generate-appcast.mjs` passes arguments in the same order as the CLI usage string. `SPUStandardUpdaterController` and `updaterController` naming is consistent between Task 2's produced interface and Task 4's consumption.
