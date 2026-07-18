import { test } from "node:test";
import assert from "node:assert/strict";
import { generateAppcast } from "./generate-appcast.mjs";

test("generateAppcast produces a valid Sparkle appcast item", () => {
  const xml = generateAppcast({
    version: "1.3",
    buildNumber: 4,
    notes: "Fixed a bug with session history.",
    pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
    signature: "abc123base64==",
    length: 45678,
    downloadUrl: "https://www.tryfluent.co/mac/updates/Fluent-1.3.zip",
  });

  assert.match(xml, /<rss xmlns:sparkle="http:\/\/www\.andymatuschak\.org\/xml-namespaces\/sparkle" version="2\.0">/);
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
        buildNumber: 4,
        notes: "x",
        pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
        signature: "sig",
        length: 1,
        downloadUrl: "https://example.com/x.zip",
      }),
    /must not include a leading "v"/
  );
});

test("generateAppcast pins the channel link to the tryfluent.co feed URL even with a GitHub download URL", () => {
  // Release artifacts are hosted on GitHub Releases, so downloadUrl looks like
  // https://github.com/rodrigocruzs/fluent/releases/download/v1.3/Fluent-1.3.zip.
  // The channel <link> must NOT be derived from that URL (it would produce a
  // nonexistent .../releases/download/v1.3/appcast.xml) — it must always point
  // at the real published feed.
  const xml = generateAppcast({
    version: "1.3",
    buildNumber: 4,
    notes: "x",
    pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
    signature: "sig",
    length: 1,
    downloadUrl: "https://github.com/rodrigocruzs/fluent/releases/download/v1.3/Fluent-1.3.zip",
  });

  assert.match(xml, /<link>https:\/\/www\.tryfluent\.co\/mac\/updates\/appcast\.xml<\/link>/);
});

test("generateAppcast puts the build number in sparkle:version, not the marketing version", () => {
  // Sparkle compares an installed app's CFBundleVersion (build number)
  // against <sparkle:version> to decide if an update is newer — not against
  // the marketing version. If this ever regresses to putting the marketing
  // version in <sparkle:version>, a dotted string like "1.4" would sort as
  // older than a plain build number like "4", and updates would silently
  // stop being offered.
  const xml = generateAppcast({
    version: "1.4",
    buildNumber: 5,
    notes: "x",
    pubDate: "Tue, 07 Jul 2026 12:00:00 +0000",
    signature: "sig",
    length: 1,
    downloadUrl: "https://example.com/x.zip",
  });

  assert.match(xml, /<sparkle:version>5<\/sparkle:version>/);
  assert.match(xml, /<sparkle:shortVersionString>1\.4<\/sparkle:shortVersionString>/);
});
