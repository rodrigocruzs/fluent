#!/usr/bin/env bash
# Build Fluent.app via xcodebuild and package it as a DMG for distribution.
#
# Prerequisites:
#   brew install create-dmg   (optional — falls back to hdiutil)
#
# Usage: ./build_dmg.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
XCODE_PROJECT="$REPO_ROOT/fluent/Fluent.xcodeproj"
SCHEME="Fluent"
CONFIGURATION="Release"
BUILD_DIR="$REPO_ROOT/fluent/build/Release/Release"
APP_PATH="$BUILD_DIR/Fluent.app"
DMG_NAME="Fluent"
WEBSITE_DIR="$REPO_ROOT/website"
DMG_PATH="$WEBSITE_DIR/Fluent.dmg"

echo "==> Building $SCHEME ($CONFIGURATION)..."
xcodebuild \
    -project "$XCODE_PROJECT" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath "$REPO_ROOT/fluent/build/DerivedData" \
    SYMROOT="$REPO_ROOT/fluent/build/Release" \
    build 2>&1 | tail -5

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: $APP_PATH not found — check xcodebuild output above."
    exit 1
fi

echo "==> Built: $APP_PATH"

# ── Package as DMG ────────────────────────────────────────────────────────────

mkdir -p "$WEBSITE_DIR"

# Stage only the .app into a clean temp folder
STAGING=$(mktemp -d)
ditto "$APP_PATH" "$STAGING/Fluent.app"

if command -v create-dmg &>/dev/null; then
    echo "==> Creating styled DMG with create-dmg..."
    rm -f "$DMG_PATH"
    create-dmg \
        --volname "$DMG_NAME" \
        --window-size 540 380 \
        --icon-size 128 \
        --icon "Fluent.app" 130 190 \
        --hide-extension "Fluent.app" \
        --app-drop-link 410 190 \
        "$DMG_PATH" \
        "$STAGING/"
else
    echo "==> create-dmg not found — using hdiutil (no styling)..."
    ln -sf /Applications "$STAGING/Applications"
    hdiutil create \
        -volname "$DMG_NAME" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "$DMG_PATH"
fi

rm -rf "$STAGING"

echo ""
echo "==> Done: $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Deploy to Vercel to publish the download."
