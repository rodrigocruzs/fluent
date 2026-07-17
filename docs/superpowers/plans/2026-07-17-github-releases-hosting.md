# GitHub Releases Artifact Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop committing ~42 MB release artifacts (Sparkle update zips, DMG) into git; host them on GitHub Releases while the tiny `appcast.xml` stays on tryfluent.co.

**Architecture:** Each release's zip + DMG become assets on the existing `v<VERSION>` GitHub release (repo is public, so assets are world-downloadable). The appcast enclosure URL and the website download links point at GitHub; `release.sh` writes artifacts to the untracked build dir and uploads via `gh`, committing only `appcast.xml` + `Info.plist`. Existing v1.5 artifacts are backfilled to GitHub first so nothing 404s when the repo copies are removed.

**Tech Stack:** bash, `gh` CLI (authenticated as `rodrigocruzs`), Sparkle appcast.

**Why:** The bundled-Python-runtime work (merged) grew the update zip from ~1.4 MB to ~42 MB. Committing that per release balloons git history permanently and sits near GitHub's 50 MB per-file warning threshold.

## Global Constraints

- Repo: `rodrigocruzs/fluent`, **public** — GitHub release assets are publicly downloadable without auth.
- Stable DMG URL (website): `https://github.com/rodrigocruzs/fluent/releases/latest/download/Fluent.dmg` — works because the DMG asset's basename is always exactly `Fluent.dmg`.
- Per-release zip URL (appcast): `https://github.com/rodrigocruzs/fluent/releases/download/v<VERSION>/Fluent-<VERSION>.zip`.
- `SUFeedURL` (Info.plist) stays `https://www.tryfluent.co/mac/updates/appcast.xml` — the appcast file remains in the repo/Vercel; only enclosure URLs move.
- The Sparkle EdDSA signature signs the zip's bytes — moving hosting does NOT invalidate existing signatures.
- Never rewrite git history; legacy blobs are removed from the tip only.
- Ordering safety: a URL must be live (asset uploaded / site deployed) before anything that references it switches over, and before repo copies are deleted.
- `gh auth status` must succeed before any upload; fail early otherwise.

---

### Task 1: Backfill the current v1.5 release to GitHub

The repo's current artifacts become assets on a `v1.5` GitHub release so all new URLs resolve before anything switches to them.

**Files:** none (publishes existing artifacts; no repo changes)

**Interfaces:**
- Produces: live URLs `releases/download/v1.5/Fluent-1.5.zip` and `releases/latest/download/Fluent.dmg` consumed by Tasks 2–3.

- [ ] **Step 1: Create the release from the existing tag with its annotation as notes, uploading both artifacts:**

```bash
cd /Users/rodrigocruzsouza/fluent
gh auth status
gh release create v1.5 --verify-tag --notes-from-tag \
    website/mac/updates/Fluent-1.5.zip \
    website/Fluent.dmg
```

Expected: release URL printed. (`--verify-tag` refuses to create a new tag if `v1.5` didn't exist.)

- [ ] **Step 2: Verify both public URLs serve the exact bytes:**

```bash
curl -sL -o /tmp/gh-check.zip https://github.com/rodrigocruzs/fluent/releases/download/v1.5/Fluent-1.5.zip
shasum -a 256 /tmp/gh-check.zip website/mac/updates/Fluent-1.5.zip
curl -sIL https://github.com/rodrigocruzs/fluent/releases/latest/download/Fluent.dmg | grep -i "^HTTP\|content-length" | tail -3
```

Expected: identical checksums; DMG URL answers 200 with the right size. No commit for this task.

---

### Task 2: Point the website's download buttons at GitHub

**Files:**
- Modify: `website/index.html` (3 anchors, lines ~107, ~428, ~460)

**Interfaces:**
- Consumes: the stable DMG URL from Task 1.

- [ ] **Step 1:** In `website/index.html`, replace the `href` in all three download anchors:

```
href="Fluent.dmg"  →  href="https://github.com/rodrigocruzs/fluent/releases/latest/download/Fluent.dmg"
```

Keep the `download="Fluent.dmg"` attribute and the PostHog `onclick` untouched. (The `download` attribute is ignored cross-origin, but GitHub serves the asset with an attachment disposition, so the browser still downloads rather than navigates.)

- [ ] **Step 2: Verify:** `grep -c 'releases/latest/download/Fluent.dmg' website/index.html` → `3`, and `grep -c 'href="Fluent.dmg"' website/index.html` → `0`.

- [ ] **Step 3: Commit**

```bash
git add website/index.html
git commit -m "feat(website): serve the Mac download from GitHub Releases"
```

---

### Task 3: Repoint the appcast and remove legacy artifacts from the repo tip

One atomic commit so the Vercel deploy never has a window where the appcast points at a file the same deploy removed.

**Files:**
- Modify: `website/mac/updates/appcast.xml` (single `<item>`, enclosure url attribute)
- Delete: `website/Fluent.dmg`, `website/mac/updates/Fluent-1.3.zip`, `website/mac/updates/Fluent-1.4.zip`, `website/mac/updates/Fluent-1.5.zip`

**Interfaces:**
- Consumes: the live zip URL verified in Task 1. Existing v1.3/v1.4 users' Sparkle checks fetch this appcast and will download 1.5 from GitHub.

- [ ] **Step 1:** Rewrite the enclosure URL:

```bash
sed -i '' 's|https://www.tryfluent.co/mac/updates/Fluent-1.5.zip|https://github.com/rodrigocruzs/fluent/releases/download/v1.5/Fluent-1.5.zip|' website/mac/updates/appcast.xml
grep -o 'url="[^"]*"' website/mac/updates/appcast.xml
```

Expected: exactly one `url="https://github.com/..."`.

- [ ] **Step 2:** Remove the repo copies (blobs stay in history; that's accepted — no history rewrite):

```bash
git rm website/Fluent.dmg website/mac/updates/Fluent-1.3.zip website/mac/updates/Fluent-1.4.zip website/mac/updates/Fluent-1.5.zip
```

- [ ] **Step 3:** Sanity-check the appcast is still valid XML: `xmllint --noout website/mac/updates/appcast.xml` (or `plutil` is wrong for XML feeds — use xmllint; if unavailable, `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse('website/mac/updates/appcast.xml')"`).

- [ ] **Step 4: Commit**

```bash
git add website/mac/updates/appcast.xml
git commit -m "feat(release): move update artifacts to GitHub Releases hosting"
```

- [ ] **Step 5:** After this lands on origin/main and Vercel deploys (Tasks 2–3 push together with everything pending on main), verify live: `curl -s https://www.tryfluent.co/mac/updates/appcast.xml | grep -o 'url="[^"]*"'` shows the GitHub URL, and `curl -sIL` on that URL returns 200. Note: pushing main also publishes the merged bundled-runtime commits — intended.

---

### Task 4: Teach release.sh the new flow

**Files:**
- Modify: `release.sh`

**Interfaces:**
- Consumes: `gh` CLI; existing variables `TAG`, `VERSION`, `BUILD_ROOT`, `NOTES_FILE` flow.
- Produces: future releases upload assets to GitHub and commit only `appcast.xml` + `Info.plist`.

- [ ] **Step 1:** Add a preflight near the Sparkle CLI checks (after line ~50):

```bash
if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh CLI not authenticated (run: gh auth login) — needed to upload release assets" >&2
  exit 1
fi
```

- [ ] **Step 2:** Move artifact paths out of the repo (they must never be tracked again):

```bash
# was: DMG_PATH="$WEBSITE_DIR/Fluent.dmg"
DMG_PATH="$BUILD_ROOT/Fluent.dmg"
# was: UPDATE_ZIP_PATH="$UPDATES_DIR/Fluent-$VERSION.zip"
UPDATE_ZIP_PATH="$BUILD_ROOT/Fluent-$VERSION.zip"
```

`UPDATES_DIR`/`APPCAST_PATH` stay as-is (appcast remains in the repo).

- [ ] **Step 3:** Change `DOWNLOAD_URL` in step 9:

```bash
DOWNLOAD_URL="https://github.com/rodrigocruzs/fluent/releases/download/$TAG/Fluent-$VERSION.zip"
```

- [ ] **Step 4:** Insert a new step between appcast generation (step 9) and the publish commit (step 10) — assets must be live before the appcast referencing them is pushed. Reuse `NOTES_FILE` (move its `rm -f` to after this step):

```bash
# ── 9b. Upload artifacts to the GitHub release ──────────────────────────────
echo "==> Creating GitHub release $TAG with artifacts..."
gh release create "$TAG" --verify-tag --notes-file "$NOTES_FILE" \
    "$UPDATE_ZIP_PATH" "$DMG_PATH"
```

(`gh release create` fails if the release already exists — correct for a fresh release; a re-run after partial failure should use `gh release upload --clobber`, note this in a comment.)

- [ ] **Step 5:** Update the publish step (10): `git add "$APPCAST_PATH" "$INFO_PLIST"` (drop `$UPDATE_ZIP_PATH`). Update the final `echo` summary paths accordingly.

- [ ] **Step 6: Verify:** `bash -n release.sh`, then `grep -n "WEBSITE_DIR/Fluent.dmg\|UPDATES_DIR/Fluent-" release.sh` → no matches, and review `git diff release.sh` against this task.

- [ ] **Step 7: Commit**

```bash
git add release.sh
git commit -m "feat(release): upload artifacts to GitHub Releases instead of committing them"
```

The real gate is the next `release.sh` run (which also carries the first notarization of the bundled runtime — watch `notarytool log`).

---

## Out of scope / future

- **Sparkle delta updates:** `generate_appcast`/`BinaryDelta` exist in `~/.local/sparkle-cli`. Constraint discovered: `generate_appcast` assumes one `--download-url-prefix` for all archives, which conflicts with per-tag GitHub URLs — doing deltas later means either a single rolling "updates" release on GitHub or hand-built `BinaryDelta` patches with manual appcast entries. Revisit if the 42 MB per-update download bothers users.
- **Purging old blobs from git history** (BFG/filter-repo): not worth the history rewrite; the ~4 MB of legacy zips in history is harmless. The point was stopping the 42 MB-per-release growth going forward.
