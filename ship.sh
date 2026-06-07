#!/bin/bash
set -e

# Usage: bash ship.sh
# Build first in Xcode with Release configuration (Product > Scheme > Edit Scheme > Run > Release),
# then run this script to sign, notarize, and install to /Applications.

DERIVED_DATA="/Users/rodrigocruzsouza/Library/Developer/Xcode/DerivedData/Fluent-dhztpitnzsulzehgusvjicnjkfef"
APP_NAME="Fluent.app"
ENTITLEMENTS="/Users/rodrigocruzsouza/fluent/fluent/Fluent/Fluent.entitlements"
SIGN_IDENTITY="Developer ID Application: Rodrigo Cruz de Souza (H28RYPBSMQ)"
APPLE_ID="rodrigocruuz@gmail.com"
TEAM_ID="H28RYPBSMQ"
APP_PASSWORD="***REMOVED***"

APP_PATH="$DERIVED_DATA/Build/Products/Release/$APP_NAME"

if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: Build output not found at $APP_PATH"
  echo "Please build in Xcode first with Release configuration:"
  echo "  Product > Scheme > Edit Scheme > Run > Build Configuration: Release"
  echo "  Then Cmd+B to build."
  exit 1
fi

echo "==> Using build: $APP_PATH ($(date -r "$APP_PATH" '+%Y-%m-%d %H:%M:%S'))"

echo "==> Signing..."
codesign --deep --force --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$SIGN_IDENTITY" \
  "$APP_PATH"

echo "==> Zipping for notarization..."
TMPZIP=$(mktemp /tmp/Fluent_XXXXXX.zip)
ditto -c -k --keepParent "$APP_PATH" "$TMPZIP"

echo "==> Submitting for notarization (this takes a few minutes)..."
xcrun notarytool submit "$TMPZIP" \
  --apple-id "$APPLE_ID" \
  --team-id "$TEAM_ID" \
  --password "$APP_PASSWORD" \
  --wait

rm -f "$TMPZIP"

echo "==> Stapling..."
xcrun stapler staple "$APP_PATH"

echo "==> Verifying..."
spctl --assess --type execute --verbose "$APP_PATH"

echo "==> Installing to /Applications..."
pkill -x Fluent 2>/dev/null || true
sleep 0.5
rm -rf /Applications/Fluent.app
ditto "$APP_PATH" /Applications/Fluent.app

echo ""
echo "Done! Fluent is ready in /Applications."
