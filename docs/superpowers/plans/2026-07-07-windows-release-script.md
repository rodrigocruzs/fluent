# Windows Release Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `windows/release.sh`, a single safety-checked command (`bash windows/release.sh <patch|minor|major>`) that bumps the app version, commits, tags, and pushes — the two remaining manual steps of an otherwise fully CI-automated Windows release pipeline.

**Architecture:** One self-contained bash script following the existing `release.sh` (repo root, Mac) conventions: `set -euo pipefail`, a `REPO_ROOT` resolved from the script's own location, staged `echo "==> ..."` progress messages. Version read/write uses plain Node one-liners (matching the `node -p "require(...)."version` pattern already used in `.github/workflows/windows-build.yml`) rather than introducing `jq` or any new dependency.

**Tech Stack:** bash, Node (already a required dev dependency for this project — no new tooling).

## Global Constraints

- Script path: `windows/release.sh`, invoked as `bash windows/release.sh <patch|minor|major>` from the repo root (matches how `release.sh` and `build_dmg.sh` are already invoked).
- Must abort before any mutation if: the working tree is dirty, the current branch isn't `main`, or local `main` is behind `origin/main`.
- Must run `node --test windows/scripts/generate-latest-json.test.mjs` plus JSON/YAML validation of `windows/src-tauri/tauri.conf.json` and `.github/workflows/windows-build.yml` before bumping anything, aborting on any failure.
- Version bump follows semver: `patch` increments the 3rd segment; `minor` increments the 2nd segment and zeroes the 3rd; `major` increments the 1st segment and zeroes the 2nd and 3rd.
- Release notes come from an interactive prompt (`read -p`), not a script argument; an empty response is allowed.
- Commit message: `release(windows): bump version to X.Y.Z`. Tag: `vX.Y.Z`, annotated with the prompted notes.
- Push order: `git push origin main` then `git push origin vX.Y.Z` — both required; each runs under `set -euo pipefail` so a failure at any step aborts immediately, and nothing partial should already be on `origin` if an earlier step failed (commit/tag are created locally first).
- Closing output must print the repo's Actions URL: `https://github.com/rodrigocruzs/fluent/actions`.

---

### Task 1: `windows/release.sh`

**Files:**
- Create: `windows/release.sh`

**Interfaces:**
- Consumes: `windows/scripts/generate-latest-json.test.mjs` (run as a precondition check, not imported); `windows/src-tauri/tauri.conf.json`'s `"version"` field (read and rewritten); `.github/workflows/windows-build.yml` (read-only, for YAML validation).
- Produces: nothing consumed by other tasks — this is the only task in the plan. The script's own behavior (exit codes, output format) is validated directly in this task's steps.

This is the only task in the plan (a single ~90-line bash script). There's no framework for unit-testing bash in this repo, so verification is done via structured dry runs against real repo state on a disposable branch, mirroring the spec's own testing plan.

- [ ] **Step 1: Write the script**

Create `windows/release.sh`:

```bash
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
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x windows/release.sh
```

- [ ] **Step 3: Verify the usage-error path**

```bash
bash windows/release.sh
echo "exit code: $?"
bash windows/release.sh bogus
echo "exit code: $?"
```

Expected: both print `Usage: bash windows/release.sh <patch|minor|major>` to
stderr and exit with a non-zero code (`1`). Neither should touch git or the
filesystem — confirm with `git status --porcelain` (expect no output).

- [ ] **Step 4: Verify the dirty-tree safety check**

```bash
echo "// scratch" >> windows/src-tauri/tauri.conf.json
bash windows/release.sh patch; echo "exit code: $?"
git checkout windows/src-tauri/tauri.conf.json
```

Expected: prints `ERROR: working tree is dirty...` to stderr, exits `1`,
before any of the "Checking branch..." output appears. The `git checkout`
cleans up the scratch line afterward.

- [ ] **Step 5: Verify the branch safety check**

```bash
git checkout -b release-script-scratch-test
bash windows/release.sh patch; echo "exit code: $?"
git checkout main
git branch -D release-script-scratch-test
```

Expected: prints `ERROR: must be on main (currently on
'release-script-scratch-test')...`, exits `1`, before any commit/tag is
created. Confirm no new tag was created: `git tag -l "v*"` should be
unchanged from before this step.

- [ ] **Step 6: Verify version-bump arithmetic in isolation**

Run each of these as standalone shell snippets (they mirror Step 3 of the
script's logic exactly) to confirm the math before trusting the full script:

```bash
IFS='.' read -r MAJOR MINOR PATCH <<< "0.1.0"; PATCH=$((PATCH + 1)); echo "$MAJOR.$MINOR.$PATCH"
```
Expected: `0.1.1`

```bash
IFS='.' read -r MAJOR MINOR PATCH <<< "0.1.9"; MINOR=$((MINOR + 1)); PATCH=0; echo "$MAJOR.$MINOR.$PATCH"
```
Expected: `0.2.0`

```bash
IFS='.' read -r MAJOR MINOR PATCH <<< "0.9.9"; MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0; echo "$MAJOR.$MINOR.$PATCH"
```
Expected: `1.0.0`

- [ ] **Step 7: Full dry run on a disposable branch, without pushing**

This exercises the entire happy path (safety checks pass, local tests run,
version bumps, file is rewritten, commit is created, tag is created)
without pushing to `origin` — a real push would create a live `v0.1.1` tag
and trigger production CI. Make a temporary local edit that redirects the
script's two push lines to a harmless no-op, run it, verify the result,
then revert the edit:

```bash
git checkout -b release-script-dry-run
sed -i.bak \
  -e 's/^git push origin main$/echo "(dry run) would: git push origin main"/' \
  -e 's/^git push origin "v\$NEW_VERSION"$/echo "(dry run) would: git push origin v$NEW_VERSION"/' \
  windows/release.sh

bash windows/release.sh patch
# When prompted, type: dry run test
```

Expected: script prints `Version: 0.1.0 -> 0.1.1`, prompts for notes,
creates the commit and tag locally, then prints the two `(dry run) would:`
lines instead of actually pushing. Verify:

```bash
git log -1 --oneline
git tag -l "v0.1.1"
git show v0.1.1 --format="%B" -s
grep '"version"' windows/src-tauri/tauri.conf.json
git log origin/main..main --oneline
```

Expected: commit subject `release(windows): bump version to 0.1.1`; tag
`v0.1.1` exists locally; tag message is `dry run test`;
`tauri.conf.json` shows `"version": "0.1.1"`; the last command shows the
dry-run commit sitting locally ahead of `origin/main`, confirming nothing
was actually pushed.

Restore the real script before committing anything:

```bash
mv windows/release.sh.bak windows/release.sh
```

- [ ] **Step 8: Clean up the dry run**

```bash
git tag -d v0.1.1
git checkout main
git branch -D release-script-dry-run
git status --porcelain
```

Expected: tag deleted, back on `main` with a clean working tree, dry-run
branch deleted. `git status --porcelain` prints nothing.

- [ ] **Step 9: Commit**

```bash
git add windows/release.sh
git commit -m "feat(windows): add release.sh to automate version bump + tag + push"
```
