#!/usr/bin/env bash
# Full release: build → sign → notarize app → DMG → notarize+staple DMG → install.
#
# Builds via xcodebuild (uses committed source, including frontend/ + fluent-engine/),
# Developer ID signs with hardened runtime, notarizes both the app and the DMG so
# Gatekeeper trusts the downloaded disk image, then installs to /Applications.
#
# Usage: bash release.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
XCODE_PROJECT="$REPO_ROOT/fluent/Fluent.xcodeproj"
SCHEME="Fluent"
CONFIGURATION="Release"
BUILD_ROOT="$REPO_ROOT/fluent/build/Release"
APP_PATH="$BUILD_ROOT/Release/Fluent.app"
ENTITLEMENTS="$REPO_ROOT/fluent/Fluent/Fluent.entitlements"
WEBSITE_DIR="$REPO_ROOT/website"
DMG_PATH="$WEBSITE_DIR/Fluent.dmg"

SIGN_IDENTITY="Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)"
# Notarization uses a keychain profile created once with:
#   xcrun notarytool store-credentials "fluent-notary" \
#     --apple-id <apple-id> --team-id H28RYPBSMQ --password <app-specific-password>
# This keeps the app-specific password out of the repo.
NOTARY_PROFILE="fluent-notary"

# ── 1. Build ──────────────────────────────────────────────────────────────────
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

echo ""
echo "==> Done."
echo "    App:  /Applications/Fluent.app"
echo "    DMG:  $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
