# Windows release script (`windows/release.sh`)

## Problem

The Windows auto-update publish pipeline (see
`docs/superpowers/specs/2026-07-07-windows-auto-update-publish-design.md`,
implemented and merged to `main`) automated the build/sign/`latest.json`
publish step: pushing a `vX.Y.Z` git tag now triggers CI to do everything
from there. What's left is manual and still requires two hand-run steps
every release:

1. Bump `"version"` in `windows/src-tauri/tauri.conf.json`, commit.
2. `git tag -a vX.Y.Z -m "<notes>"`, `git push --tags`.

These are normal, deliberate release gestures (not something to fully
automate away — auto-releasing on every merge to `main` would ship every
commit immediately with no chance to decide something is release-worthy).
But the two steps are easy to get wrong by hand: forgetting to bump the
version before tagging (CI's version-match guard then fails the build),
tagging from a stale/non-`main` branch, or tagging with uncommitted changes
nearby. A small script collapses this into one deliberate, safety-checked
command.

## Goal

`windows/release.sh <patch|minor|major>` performs the entire "cut a release"
step locally: validates preconditions, bumps the version, commits, tags,
and pushes. CI (already built) takes it from there.

Out of scope: this script does **not** build, sign, or publish anything
itself — all of that is already CI's job. It also does not touch the Mac
release process (`release.sh` at the repo root, which is a different kind
of script since it performs the actual local build/notarize/install).

## Design

### Usage

```
bash windows/release.sh patch   # 0.1.0 -> 0.1.1
bash windows/release.sh minor   # 0.1.5 -> 0.2.0
bash windows/release.sh major   # 0.2.3 -> 1.0.0
```

Any other argument (missing, misspelled, extra) prints usage and exits
non-zero without touching anything.

### Flow

1. **Safety checks** (run first, before any file is touched):
   - Working tree is clean: `git status --porcelain` is empty. Uncommitted
     changes anywhere in the repo abort the script — prevents bundling
     unrelated in-progress work into the version-bump commit.
   - Current branch is `main`: `git branch --show-current` must equal
     `main`.
   - `main` is not behind `origin/main`: `git fetch origin main`, then
     compare `git rev-list HEAD..origin/main --count` is `0`.
   - Any failure here aborts immediately with a clear message naming which
     check failed and how to fix it (e.g. "commit or stash your changes
     first", "checkout main first", "git pull first").

2. **Local verification** (abort on any failure, before bumping anything):
   - `node --test windows/scripts/generate-latest-json.test.mjs`
   - `python3 -c "import json; json.load(open('windows/src-tauri/tauri.conf.json'))"`
   - `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/windows-build.yml'))"`

   These are cheap, fast, and catch a broken script/config before a tag
   push commits CI to a build that can't publish.

3. **Compute the new version:**
   - Read the current `"version"` string from
     `windows/src-tauri/tauri.conf.json` (parse with `node -p` or `python3
     -c`, matching the style already used in `windows-build.yml`'s
     version-match guard).
   - Split on `.`, bump the requested segment, per standard semver/`npm
     version` semantics: `patch` increments the third segment; `minor`
     increments the second segment and resets the third to `0`; `major`
     increments the first segment and resets the second and third to `0`.

4. **Prompt for release notes:**
   - `read -p "Release notes for vX.Y.Z: " notes` (interactive; the script
     is meant to be run by a human at a terminal, not from CI).
   - No default/fallback — an empty response is allowed (an empty tag
     message is a valid, if uninformative, release note; the existing CI
     workflow already falls back to the commit subject if the tag message
     is empty, so this degrades gracefully).

5. **Update, commit, tag, push:**
   - Write the new version into `windows/src-tauri/tauri.conf.json`
     (in-place edit of just the `"version"` field, preserving the rest of
     the file's formatting).
   - `git add windows/src-tauri/tauri.conf.json`
   - `git commit -m "release(windows): bump version to X.Y.Z"`
   - `git tag -a vX.Y.Z -m "<notes>"`
   - `git push origin main`
   - `git push origin vX.Y.Z`
   - Each of these five steps runs under `set -euo pipefail`, so any
     failure aborts the whole script immediately. The commit and tag are
     created locally before any push, so a failure in `git push origin
     main` leaves nothing on `origin` — the local commit/tag can be
     inspected, fixed, or discarded by hand without any remote state to
     reconcile.

6. **Print next steps:**
   - A closing message pointing at the GitHub Actions run the tag push
     just triggered (the repo's Actions URL,
     `https://github.com/rodrigocruzs/fluent/actions`), so the operator
     knows where to watch the build/sign/publish happen.

### Error handling

- `set -euo pipefail` at the top, matching the existing `release.sh`
  convention.
- Safety-check failures print a specific, actionable message (not a bare
  git error) and exit before any mutation.
- A failure in steps 5 or 6 (after the commit/tag exist locally but before
  or during push) is recoverable by hand: `git tag -d vX.Y.Z` and `git
  reset --soft HEAD~1` undo the local state if the operator wants to start
  over, or the operator can simply re-run the two push commands once the
  underlying problem (e.g. network, permissions) is fixed.

### Testing plan

- Dry-run the safety checks against a dirty working tree, a non-`main`
  branch, and a `main` behind `origin/main` — confirm each aborts with the
  right message and no side effects.
- Run the version-bump math against a few inputs (`0.1.0`/patch →
  `0.1.1`, `0.1.9`/minor → `0.2.0`, `0.9.9`/major → `1.0.0`) to confirm
  standard semver reset behavior.
- Full dry run on a throwaway branch/tag (not `v*`-patterned, to avoid
  triggering the real CI workflow) to confirm the script's file edit,
  commit, and tag steps work end-to-end before trusting it for a real
  release.
