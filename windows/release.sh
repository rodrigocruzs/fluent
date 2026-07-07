#!/usr/bin/env bash
# Cut a Windows release: bump the version, commit, tag, push.
#
# CI (.github/workflows/windows-build.yml) does the rest — building, signing,
# generating latest.json, and publishing to the website — triggered by the
# tag push this script performs. See:
#   docs/superpowers/specs/2026-07-07-windows-auto-update-publish-design.md
#   docs/superpowers/specs/2026-07-07-windows-release-script-design.md
#
# Usage: bash windows/release.sh <patch|minor|major>
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_PATH="$REPO_ROOT/windows/src-tauri/tauri.conf.json"

BUMP="${1:-}"
if [[ "$BUMP" != "patch" && "$BUMP" != "minor" && "$BUMP" != "major" ]]; then
  echo "Usage: bash windows/release.sh <patch|minor|major>" >&2
  exit 1
fi

cd "$REPO_ROOT"

# ── 1. Safety checks ────────────────────────────────────────────────────────
echo "==> Checking working tree..."
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty. Commit or stash your changes first." >&2
  exit 1
fi

echo "==> Checking branch..."
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "ERROR: must be on main (currently on '$CURRENT_BRANCH'). Checkout main first." >&2
  exit 1
fi

echo "==> Checking main is up to date with origin..."
git fetch origin main
BEHIND_COUNT="$(git rev-list HEAD..origin/main --count)"
if [[ "$BEHIND_COUNT" != "0" ]]; then
  echo "ERROR: main is behind origin/main by $BEHIND_COUNT commit(s). git pull first." >&2
  exit 1
fi

# ── 2. Local verification ───────────────────────────────────────────────────
echo "==> Running generate-latest-json tests..."
node --test windows/scripts/generate-latest-json.test.mjs

echo "==> Validating tauri.conf.json..."
python3 -c "import json; json.load(open('windows/src-tauri/tauri.conf.json'))"

echo "==> Validating windows-build.yml..."
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/windows-build.yml'))"

# ── 3. Compute the new version ──────────────────────────────────────────────
CURRENT_VERSION="$(node -p "require('./windows/src-tauri/tauri.conf.json').version")"
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP" in
  patch)
    PATCH=$((PATCH + 1))
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
echo "==> Version: $CURRENT_VERSION -> $NEW_VERSION"

# ── 4. Prompt for release notes ─────────────────────────────────────────────
read -r -p "Release notes for v$NEW_VERSION: " NOTES

# ── 5. Update, commit, tag, push ────────────────────────────────────────────
echo "==> Updating tauri.conf.json..."
node -e "
  const fs = require('fs');
  const path = 'windows/src-tauri/tauri.conf.json';
  const raw = fs.readFileSync(path, 'utf8');
  const updated = raw.replace(
    /\"version\":\s*\"[^\"]+\"/,
    '\"version\": \"$NEW_VERSION\"'
  );
  fs.writeFileSync(path, updated);
"

echo "==> Committing..."
git add "$CONF_PATH"
git commit -m "release(windows): bump version to $NEW_VERSION"

echo "==> Tagging v$NEW_VERSION..."
git tag -a "v$NEW_VERSION" -m "$NOTES"

echo "==> Pushing main..."
git push origin main

echo "==> Pushing tag v$NEW_VERSION..."
git push origin "v$NEW_VERSION"

echo ""
echo "==> Done. CI will build, sign, and publish shortly:"
echo "    https://github.com/rodrigocruzs/fluent/actions"
