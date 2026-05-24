#!/usr/bin/env bash
# Build Fluent.app and package it as a distributable DMG.
#
# Prerequisites:
#   pip install py2app
#   brew install create-dmg   (optional, for a styled DMG)
#
# Usage: ./build_dmg.sh

set -euo pipefail

APP_NAME="Fluent"
DMG_NAME="Fluent-1.0"
BUILD_DIR="dist"
APP_PATH="$BUILD_DIR/$APP_NAME.app"
DMG_PATH="$BUILD_DIR/$DMG_NAME.dmg"

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Building $APP_NAME.app with py2app..."
python setup_app.py py2app 2>&1

if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: $APP_PATH not found after build." >&2
  exit 1
fi

echo "==> Built: $APP_PATH"

# ── Package as DMG ─────────────────────────────────────────────────────────

if command -v create-dmg &>/dev/null; then
  echo "==> Creating styled DMG with create-dmg..."
  create-dmg \
    --volname "$APP_NAME" \
    --window-size 540 380 \
    --icon-size 128 \
    --icon "$APP_NAME.app" 130 190 \
    --hide-extension "$APP_NAME.app" \
    --app-drop-link 410 190 \
    "$DMG_PATH" \
    "$BUILD_DIR/"
else
  echo "==> create-dmg not found — using hdiutil (no styling)..."
  STAGING="$BUILD_DIR/dmg_staging"
  mkdir -p "$STAGING"
  cp -r "$APP_PATH" "$STAGING/"
  # Symlink to /Applications for drag-install UX
  ln -sf /Applications "$STAGING/Applications"
  hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$DMG_PATH"
  rm -rf "$STAGING"
fi

echo ""
echo "==> Done: $DMG_PATH"
echo "    Drag $APP_NAME to Applications to install."

# Copy DMG to website/ so the download button always serves the latest build
cp "$DMG_PATH" "website/Fluent.dmg"
echo "==> Copied to website/Fluent.dmg"
