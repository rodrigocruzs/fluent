#!/usr/bin/env bash
# Injects build/engine-runtime into a built Fluent.app and signs its binaries.
# Called by release.sh between xcodebuild and the app signing pass — the
# nested binaries must be signed BEFORE the app's codesign --deep pass seals
# Resources, or the seal breaks.
#
# Usage: bundle_engine_runtime_into_app.sh <path/to/Fluent.app> [sign-identity]
# Without an identity, binaries are ad-hoc signed — for local testing only.
set -euo pipefail

APP_PATH="${1:?usage: bundle_engine_runtime_into_app.sh <Fluent.app> [identity]}"
IDENTITY="${2:--}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_SRC="$REPO_ROOT/build/engine-runtime"
RUNTIME_DST="$APP_PATH/Contents/Resources/engine-runtime"
ENGINE_DST="$APP_PATH/Contents/Resources/fluent-engine"

[ -x "$RUNTIME_SRC/bin/python3" ] \
    || { echo "ERROR: run scripts/build_engine_runtime.sh first" >&2; exit 1; }
[ -d "$ENGINE_DST" ] \
    || { echo "ERROR: $ENGINE_DST missing — not a built Fluent.app?" >&2; exit 1; }

echo "==> Copying engine runtime into app..."
rm -rf "$RUNTIME_DST"
ditto "$RUNTIME_SRC" "$RUNTIME_DST"
rm -f "$RUNTIME_DST/.stamp"

echo "==> Pruning bundled engine source..."
# The pbxproj folder reference copies fluent-engine/ wholesale, including
# dev-only and stray content that must not ship.
rm -rf "$ENGINE_DST/tests" \
       "$ENGINE_DST/__pycache__" \
       "$ENGINE_DST/fluent/Fluent" \
       "$ENGINE_DST/fluent/Fluent.xcodeproj" \
       "$ENGINE_DST/fluent/project.yml"
rm -f  "$ENGINE_DST/setup_engine.sh" "$ENGINE_DST/install_agent.py" \
       "$ENGINE_DST/requirements-dev.txt" "$ENGINE_DST/requirements-win.txt"
find "$ENGINE_DST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$ENGINE_DST" -name '*.pyc' -delete

echo "==> Signing runtime binaries ($IDENTITY)..."
SIGN_ARGS=(--force --options runtime --sign "$IDENTITY")
[ "$IDENTITY" != "-" ] && SIGN_ARGS+=(--timestamp)
while IFS= read -r -d '' f; do
    file -b "$f" | grep -q "Mach-O" || continue
    codesign "${SIGN_ARGS[@]}" "$f"
done < <(find "$RUNTIME_DST" -type f \
    \( -perm -111 -o -name '*.so' -o -name '*.dylib' \) -print0)
echo "==> Engine runtime bundled ($(du -sh "$RUNTIME_DST" | cut -f1))."
