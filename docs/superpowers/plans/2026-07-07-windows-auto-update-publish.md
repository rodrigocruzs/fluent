# Windows Auto-Update Publish Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `git push --tags` the entire Windows release process — CI builds, signs, generates `latest.json`, and publishes both it and the installer to the website, so the already-running Tauri updater (`windows/src-tauri/src/update.rs`) actually finds and installs updates instead of hitting a 404.

**Architecture:** A new Node script (`windows/scripts/generate-latest-json.mjs`) takes the tag name, the built installer path, and its `.sig` sibling, and writes a `latest.json` manifest matching the Tauri updater schema — this is pure, testable logic with no GitHub Actions dependency. A new step in `.github/workflows/windows-build.yml`, gated to tag-triggered runs only, calls that script, copies the installer into `website/`, and commits+pushes both files.

**Tech Stack:** Node (ESM, no new dependencies — matches `sync-frontend.mjs`/`bundle-engine.mjs` conventions), GitHub Actions (`windows-latest` runner, existing `windows-build.yml`), git.

## Global Constraints

- `latest.json` must validate against the Tauri updater v2 schema: top-level `version`, `notes`, `pub_date` (UTC ISO8601), and `platforms.windows-x86_64.{signature,url}` — exact field names, or the already-deployed updater client silently fails to parse it.
- The tag version and `windows/src-tauri/tauri.conf.json`'s `"version"` field must match exactly, or the workflow must fail before publishing (per spec).
- The publish step (commit+push to `website/`) must run only when `github.ref` is a tag matching `v*`; `workflow_dispatch` runs must still build/sign/upload-artifact but skip publish.
- The installer's public download URL must remain `https://www.tryfluent.co/Fluent-Setup.exe` (unchanged — the site's existing download button already points here).
- No changes to `windows/src-tauri/src/update.rs`, `lib.rs`, or the updater `pubkey`/endpoint in `tauri.conf.json` — the client side is already correct.

---

### Task 1: `generate-latest-json.mjs` script + unit-style tests

**Files:**
- Create: `windows/scripts/generate-latest-json.mjs`
- Create: `windows/scripts/generate-latest-json.test.mjs`

**Interfaces:**
- Produces: `generateLatestJson({ version, notes, pubDate, signature, downloadUrl })` — a pure function returning the manifest object (exported for the test file to import). The CLI entry point (`if (import.meta.url === ...)`) reads `process.argv` and writes the file, calling this function internally.
- Consumes: nothing from other tasks (this is the foundational, standalone piece).

This task builds the manifest-generation logic in isolation, testable on any
machine (no Windows/CI/Tauri build required), before wiring it into the
workflow in Task 2.

- [ ] **Step 1: Write the failing test**

Create `windows/scripts/generate-latest-json.test.mjs`:

```js
// Run with: node --test windows/scripts/generate-latest-json.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateLatestJson } from "./generate-latest-json.mjs";

test("produces a manifest matching the Tauri updater v2 schema", () => {
  const manifest = generateLatestJson({
    version: "0.1.1",
    notes: "Merge consecutive same-speaker utterances",
    pubDate: "2026-07-07T12:00:00Z",
    signature: "dW50cnVzdGVkIGNvbW1lbnQ6c2lnbmF0dXJl",
    downloadUrl: "https://www.tryfluent.co/Fluent-Setup.exe",
  });

  assert.equal(manifest.version, "0.1.1");
  assert.equal(manifest.notes, "Merge consecutive same-speaker utterances");
  assert.equal(manifest.pub_date, "2026-07-07T12:00:00Z");
  assert.deepEqual(Object.keys(manifest.platforms), ["windows-x86_64"]);
  assert.equal(
    manifest.platforms["windows-x86_64"].signature,
    "dW50cnVzdGVkIGNvbW1lbnQ6c2lnbmF0dXJl"
  );
  assert.equal(
    manifest.platforms["windows-x86_64"].url,
    "https://www.tryfluent.co/Fluent-Setup.exe"
  );
});

test("throws if the tag version has a leading v", () => {
  assert.throws(
    () =>
      generateLatestJson({
        version: "v0.1.1",
        notes: "x",
        pubDate: "2026-07-07T12:00:00Z",
        signature: "sig",
        downloadUrl: "https://www.tryfluent.co/Fluent-Setup.exe",
      }),
    /version must not include a leading "v"/
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test windows/scripts/generate-latest-json.test.mjs`
Expected: FAIL — `generate-latest-json.mjs` does not exist yet (module not found error).

- [ ] **Step 3: Write minimal implementation**

Create `windows/scripts/generate-latest-json.mjs`:

```js
// Generates website/windows/updates/latest.json, the manifest the
// tauri-plugin-updater client polls on every app launch (see
// windows/src-tauri/src/update.rs and the `plugins.updater.endpoints` entry
// in tauri.conf.json). Schema: https://v2.tauri.app/plugin/updater/
//
// Used both as a library (generateLatestJson, for tests) and as a CLI:
//   node generate-latest-json.mjs <version> <notesFile> <sigFile> <downloadUrl> <outFile>

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

export function generateLatestJson({ version, notes, pubDate, signature, downloadUrl }) {
  if (version.startsWith("v")) {
    throw new Error('version must not include a leading "v" (strip the tag prefix first)');
  }
  return {
    version,
    notes,
    pub_date: pubDate,
    platforms: {
      "windows-x86_64": {
        signature,
        url: downloadUrl,
      },
    },
  };
}

const isMain = import.meta.url === `file://${process.argv[1]}`;
if (isMain) {
  const [, , version, notesFile, sigFile, downloadUrl, outFile] = process.argv;
  if (!version || !notesFile || !sigFile || !downloadUrl || !outFile) {
    console.error(
      "usage: generate-latest-json.mjs <version> <notesFile> <sigFile> <downloadUrl> <outFile>"
    );
    process.exit(1);
  }

  const notes = readFileSync(notesFile, "utf8").trim();
  const signature = readFileSync(sigFile, "utf8").trim();
  const pubDate = new Date().toISOString();

  const manifest = generateLatestJson({ version, notes, pubDate, signature, downloadUrl });

  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(manifest, null, 2) + "\n");
  console.log(`[generate-latest-json] wrote ${outFile} (version ${version})`);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test windows/scripts/generate-latest-json.test.mjs`
Expected: PASS (2 tests)

- [ ] **Step 5: Manually verify the CLI entry point**

```bash
cd windows/scripts
echo "Test release notes" > /tmp/notes.txt
echo "dW50cnVzdGVkIGNvbW1lbnQ6c2lnbmF0dXJl" > /tmp/sig.txt
node generate-latest-json.mjs 0.1.1 /tmp/notes.txt /tmp/sig.txt \
  https://www.tryfluent.co/Fluent-Setup.exe /tmp/latest.json
cat /tmp/latest.json
```

Expected output: valid JSON with `version: "0.1.1"`, `notes: "Test release notes"`,
a `pub_date` timestamp, and `platforms.windows-x86_64.{signature,url}` populated.

- [ ] **Step 6: Commit**

```bash
git add windows/scripts/generate-latest-json.mjs windows/scripts/generate-latest-json.test.mjs
git commit -m "feat(windows): add latest.json manifest generator for auto-update publish"
```

---

### Task 2: Wire tag-gated publish step into `windows-build.yml`

**Files:**
- Modify: `.github/workflows/windows-build.yml`

**Interfaces:**
- Consumes: `windows/scripts/generate-latest-json.mjs` CLI (Task 1) — invoked as
  `node scripts/generate-latest-json.mjs <version> <notesFile> <sigFile> <downloadUrl> <outFile>`.
- Consumes: the existing build outputs already produced by the "Build Windows installer"
  step — `windows/src-tauri/target/release/bundle/nsis/*-setup.exe` and its `*.sig` sibling.
- Produces: `website/windows/updates/latest.json` and `website/Fluent-Setup.exe`, committed
  and pushed to `main` — consumed by Vercel's existing deploy-on-push and by every installed
  Fluent Windows client polling the updater endpoint.

This task adds the version-match guard, notes extraction, manifest generation,
and git publish as new steps appended to the existing job, gated so they only
run on a tag push.

- [ ] **Step 1: Add a `startsWith(github.ref, 'refs/tags/v')` output so later steps can gate on it**

Add an `id` to the checkout step and a small step right after it in
`.github/workflows/windows-build.yml` (after line 25, the `actions/checkout@v4` step):

```yaml
      - uses: actions/checkout@v4

      - name: Determine if this is a release (tag) run
        id: release
        shell: bash
        run: |
          if [[ "${{ github.ref }}" == refs/tags/v* ]]; then
            echo "is_release=true" >> "$GITHUB_OUTPUT"
            echo "version=${GITHUB_REF#refs/tags/v}" >> "$GITHUB_OUTPUT"
          else
            echo "is_release=false" >> "$GITHUB_OUTPUT"
          fi
```

- [ ] **Step 2: Add the version-match guard, gated on `steps.release.outputs.is_release`**

Insert this step after the existing "Generate app icons" step (after line 59),
so it fails fast before the expensive build/sign steps run:

```yaml
      - name: Verify tag version matches tauri.conf.json
        if: steps.release.outputs.is_release == 'true'
        shell: bash
        run: |
          tag_version="${{ steps.release.outputs.version }}"
          conf_version=$(node -p "require('./src-tauri/tauri.conf.json').version")
          if [[ "$tag_version" != "$conf_version" ]]; then
            echo "::error::Tag version ($tag_version) does not match tauri.conf.json version ($conf_version)"
            exit 1
          fi
          echo "Version check passed: $tag_version"
```

- [ ] **Step 3: Add the notes-extraction step, gated on `is_release`**

Insert after the version-match guard:

```yaml
      - name: Extract release notes from the tag
        if: steps.release.outputs.is_release == 'true'
        shell: bash
        run: |
          tag_name="${GITHUB_REF#refs/tags/}"
          notes=$(git tag -l --format='%(contents)' "$tag_name")
          if [[ -z "$notes" ]]; then
            notes=$(git log -1 --format='%s' "$tag_name")
          fi
          # Write to a file rather than an env var/output: tag messages can
          # be multi-line and contain characters GITHUB_OUTPUT can't hold safely.
          printf '%s' "$notes" > "$RUNNER_TEMP/release-notes.txt"
          cat "$RUNNER_TEMP/release-notes.txt"
```

- [ ] **Step 4: Add the manifest-generation + publish step, gated on `is_release`, after the existing "Build Windows installer" step (after line 89)**

```yaml
      - name: Generate latest.json manifest
        if: steps.release.outputs.is_release == 'true'
        shell: bash
        run: |
          installer=$(ls src-tauri/target/release/bundle/nsis/*-setup.exe)
          sig="$installer.sig"
          node scripts/generate-latest-json.mjs \
            "${{ steps.release.outputs.version }}" \
            "$RUNNER_TEMP/release-notes.txt" \
            "$sig" \
            "https://www.tryfluent.co/Fluent-Setup.exe" \
            "$RUNNER_TEMP/latest.json"

      - name: Publish installer + manifest to website
        if: steps.release.outputs.is_release == 'true'
        shell: bash
        run: |
          installer=$(ls src-tauri/target/release/bundle/nsis/*-setup.exe)
          mkdir -p ../website/windows/updates
          cp "$RUNNER_TEMP/latest.json" ../website/windows/updates/latest.json
          cp "$installer" ../website/Fluent-Setup.exe

          cd ..
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add website/windows/updates/latest.json website/Fluent-Setup.exe
          git commit -m "release(windows): publish v${{ steps.release.outputs.version }}"
          git push origin HEAD:main
```

Note: this step runs with `working-directory: windows` (the job default), so
paths into `website/` go up one level (`../website`) — matching where
`release.sh`/`build_dmg.sh` already place `website/Fluent.dmg` relative to the
repo root.

- [ ] **Step 5: Update the workflow's top comment to describe the new behavior**

Replace lines 1-9 of `.github/workflows/windows-build.yml`:

```yaml
name: Windows installer

# Builds (and, when Azure secrets are present, code-signs) the Windows NSIS
# installer for the Fluent Tauri shell. Runs on windows-latest because Tauri
# compiles a native windows-msvc binary and bundles a Windows CPython engine —
# neither can be produced from macOS/Linux.
#
# Trigger it manually from the Actions tab for a test build (built + signed +
# uploaded as an artifact, not published). Push a "vX.Y.Z" tag matching
# src-tauri/tauri.conf.json's version to cut a real release: this also
# generates website/windows/updates/latest.json and publishes it + the
# installer to the website, so the in-app auto-updater picks it up.
```

- [ ] **Step 6: Also gate the artifact upload's name so test builds and releases are distinguishable (optional clarity improvement)**

Leave the existing "Upload installer" step (lines 91-98) unchanged — it should
run on every trigger (both `workflow_dispatch` and tag pushes) as today, so a
release run still leaves a recoverable artifact if the publish step fails
(per the spec's failure-handling section).

- [ ] **Step 7: Validate the YAML is well-formed**

```bash
cd /Users/rodrigocruzsouza/fluent
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/windows-build.yml'))" && echo "YAML OK"
```

Expected: `YAML OK` (fails loudly on any indentation/syntax mistake before pushing).

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/windows-build.yml
git commit -m "feat(ci): publish latest.json + installer to website on tagged Windows releases"
```

---

### Task 3: Update `windows/README.md` to remove the manual-publish instruction

**Files:**
- Modify: `windows/README.md:104-106`

**Interfaces:**
- Consumes: nothing (documentation-only task).
- Produces: nothing consumed by other tasks — this closes out the spec's
  identified gap where the README documented the manual step as a TODO.

- [ ] **Step 1: Replace the stale manual-publish instructions**

Read the current text at `windows/README.md:104-106`:

```
The build emits a `.sig` next to the installer. Publish the installer + a
`latest.json` manifest (version, notes, signature, download URL) at the
configured endpoint (`https://www.tryfluent.co/windows/updates/latest.json`).
```

Replace with:

```
The build emits a `.sig` next to the installer. Publishing is automated:
pushing a `vX.Y.Z` tag (matching `src-tauri/tauri.conf.json`'s `version`)
triggers `.github/workflows/windows-build.yml`, which generates
`website/windows/updates/latest.json` and commits it plus the signed
installer to the website — see `windows/scripts/generate-latest-json.mjs`.
Installed apps discover the update via `plugins.updater.endpoints` and
self-update on next launch (`windows/src-tauri/src/update.rs`).
```

- [ ] **Step 2: Commit**

```bash
git add windows/README.md
git commit -m "docs(windows): document automated latest.json publish flow"
```

---

## Self-Review Notes

- **Spec coverage:** tag-triggered CI publish (Task 2, Steps 1-4), version cross-check
  failing fast (Task 2, Step 2), tag-message release notes with commit-subject fallback
  (Task 2, Step 3), `workflow_dispatch` builds/signs/uploads but skips publish (Task 2's
  `if: steps.release.outputs.is_release == 'true'` gates on every new step), `latest.json`
  schema matching Tauri's updater format (Task 1), installer published at the unchanged
  `Fluent-Setup.exe` URL (Task 1 test + Task 2 Step 4), failure handling via the untouched
  artifact-upload step (Task 2 Step 6) — all covered.
- **Placeholder scan:** no TBDs; all code blocks are complete and runnable.
- **Type/name consistency:** `generateLatestJson`'s parameter names
  (`version, notes, pubDate, signature, downloadUrl`) match between the exported function
  (Task 1 Step 3) and its test (Task 1 Step 1); the CLI arg order matches between the
  script's usage string and Task 2 Step 4's invocation.
