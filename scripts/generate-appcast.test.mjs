import { test } from "node:test";
import assert from "node:assert/strict";
import { generateAppcast } from "./generate-appcast.mjs";

test("generateAppcast produces a valid Sparkle appcast item", () => {
  const xml = generateAppcast({
    version: "1.3",
    notes: "Fixed a bug with session history.",
    pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
    signature: "abc123base64==",
    length: 45678,
    downloadUrl: "https://www.tryfluent.co/mac/updates/Fluent-1.3.zip",
  });

  assert.match(xml, /<rss xmlns:sparkle="http:\/\/www\.andymatuschak\.org\/xml-namespaces\/sparkle" version="2\.0">/);
  assert.match(xml, /<sparkle:version>1\.3<\/sparkle:version>/);
  assert.match(xml, /<sparkle:shortVersionString>1\.3<\/sparkle:shortVersionString>/);
  assert.match(xml, /url="https:\/\/www\.tryfluent\.co\/mac\/updates\/Fluent-1\.3\.zip"/);
  assert.match(xml, /length="45678"/);
  assert.match(xml, /sparkle:edSignature="abc123base64=="/);
  assert.match(xml, /<pubDate>Tue, 07 Jul 2026 12:00:00 \+0000<\/pubDate>/);
  assert.match(xml, /Fixed a bug with session history\./);
});

test("generateAppcast rejects a version with a leading v", () => {
  assert.throws(
    () =>
      generateAppcast({
        version: "v1.3",
        notes: "x",
        pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
        signature: "sig",
        length: 1,
        downloadUrl: "https://example.com/x.zip",
      }),
    /must not include a leading "v"/
  );
});
