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

# This script ends by pushing straight to origin/main (no PR, no review) —
# correct for a real release cut from main, but if run from any other branch
# it publishes that branch's entire unreviewed history as a side effect.
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "ERROR: release.sh must be run from 'main' (currently on '$CURRENT_BRANCH')." >&2
  echo "  Merge/review this branch into main first, then re-run from main." >&2
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

# ── 1. Build ──────────────────────────────────────────────────────────────────
echo "==> Checking AppIcon safe-area padding (full-bleed artwork renders oversized in the Dock)..."
python3 "$REPO_ROOT/scripts/check-appicon-padding.py"

echo "==> Building $SCHEME ($CONFIGURATION)..."
rm -rf "$APP_PATH"
xcodebuild \
    -project "$XCODE_PROJECT" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath "$REPO_ROOT/fluent/build/DerivedData" \
    SYMROOT="$BUILD_ROOT" \
    build 2>&1 | tail -3
[ -d "$APP_PATH" ] || { echo "ERROR: $APP_PATH not found"; exit 1; }
echo "==> Built: $APP_PATH"

# ── 2. Sign the app ─────────────────────────────────────────────────────────--
echo "==> Signing app (Developer ID, hardened runtime)..."
codesign --deep --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$SIGN_IDENTITY" \
    "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

# ── 3. Notarize the app ─────────────────────────────────────────────────────--
echo "==> Notarizing app (a few minutes)..."
APPZIP=$(mktemp /tmp/Fluent_app_XXXXXX.zip)
ditto -c -k --keepParent "$APP_PATH" "$APPZIP"
xcrun notarytool submit "$APPZIP" \
    --keychain-profile "$NOTARY_PROFILE" --wait
rm -f "$APPZIP"
echo "==> Stapling app..."
xcrun stapler staple "$APP_PATH"
spctl --assess --type execute --verbose "$APP_PATH"

# ── 4. Package DMG ─────────────────────────────────────────────────────────--
echo "==> Building DMG..."
mkdir -p "$WEBSITE_DIR"
rm -f "$DMG_PATH"
STAGING=$(mktemp -d)
ditto "$APP_PATH" "$STAGING/Fluent.app"
create-dmg \
    --volname "Fluent" \
    --window-size 540 380 \
    --icon-size 128 \
    --icon "Fluent.app" 130 190 \
    --hide-extension "Fluent.app" \
    --app-drop-link 410 190 \
    "$DMG_PATH" \
    "$STAGING/"
rm -rf "$STAGING"

# ── 5. Sign + notarize + staple the DMG ─────────────────────────────────────--
echo "==> Signing DMG..."
codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
echo "==> Notarizing DMG (a few minutes)..."
xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$NOTARY_PROFILE" --wait
echo "==> Stapling DMG..."
xcrun stapler staple "$DMG_PATH"
spctl --assess --type open --context context:primary-signature --verbose "$DMG_PATH" || true

# ── 6. Install to /Applications ────────────────────────────────────────────--
echo "==> Installing to /Applications..."
pkill -x Fluent 2>/dev/null || true
sleep 0.5
rm -rf /Applications/Fluent.app
ditto "$APP_PATH" /Applications/Fluent.app

echo "==> Refreshing icon caches (avoids stale/oversized Dock icon)..."
touch /Applications/Fluent.app
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f /Applications/Fluent.app
killall Dock 2>/dev/null || true

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
node "$REPO_ROOT/scripts/generate-appcast.mjs" \
  "$VERSION" "$NEW_BUILD" "$NOTES_FILE" "$UPDATE_SIGNATURE" "$ZIP_LENGTH" "$DOWNLOAD_URL" "$APPCAST_PATH"
rm -f "$NOTES_FILE"

# ── 10. Publish to the website ───────────────────────────────────────────────
echo "==> Publishing update artifacts..."
cd "$REPO_ROOT"
git add "$UPDATE_ZIP_PATH" "$APPCAST_PATH" "$INFO_PLIST"
git commit -m "release(mac): publish v$VERSION"
git push origin HEAD:main

echo ""
echo "==> Done."
echo "    App:      /Applications/Fluent.app"
echo "    DMG:      $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Update:   $UPDATE_ZIP_PATH ($(du -sh "$UPDATE_ZIP_PATH" | cut -f1))"
echo "    Appcast:  $APPCAST_PATH"
echo "    Published to main — Vercel will deploy the update feed shortly."
