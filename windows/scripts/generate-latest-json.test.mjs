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
