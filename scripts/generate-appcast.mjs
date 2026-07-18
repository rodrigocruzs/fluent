// Generates website/mac/updates/appcast.xml, the feed Sparkle's
// SPUStandardUpdaterController polls (see SUFeedURL in
// fluent/Fluent/Info.plist). Schema:
// https://sparkle-project.org/documentation/publishing/
//
// Sparkle compares an installed app's CFBundleVersion (build number) against
// the appcast's <sparkle:version> to decide if an update is newer — NOT
// against the marketing version. So <sparkle:version> must carry the build
// number, and <sparkle:shortVersionString> carries the marketing version
// shown to users. Getting this backwards means every future dotted marketing
// version (e.g. "1.4") sorts as older than a plain build-number string
// (e.g. "4"), and updates are never offered.
//
// Used both as a library (generateAppcast, for tests) and as a CLI:
//   node generate-appcast.mjs <version> <buildNumber> <notesFile> <signature> <length> <downloadUrl> <outFile>

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { pathToFileURL } from "node:url";

function escapeXml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function generateAppcast({ version, buildNumber, notes, pubDate, signature, length, downloadUrl }) {
  if (version.startsWith("v")) {
    throw new Error('version must not include a leading "v" (strip the tag prefix first)');
  }

  return `<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>Fluent Changelog</title>
    <!-- Fixed by the app's SUFeedURL in Info.plist — not derived from downloadUrl, -->
    <!-- which now points at GitHub Releases and has no appcast.xml alongside it. -->
    <link>https://www.tryfluent.co/mac/updates/appcast.xml</link>
    <description>Most recent changes for Fluent on macOS.</description>
    <language>en</language>
    <item>
      <title>Version ${escapeXml(version)}</title>
      <description><![CDATA[${notes}]]></description>
      <pubDate>${pubDate}</pubDate>
      <sparkle:version>${escapeXml(String(buildNumber))}</sparkle:version>
      <sparkle:shortVersionString>${escapeXml(version)}</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      <enclosure
        url="${escapeXml(downloadUrl)}"
        length="${length}"
        type="application/octet-stream"
        sparkle:edSignature="${escapeXml(signature)}"
      />
    </item>
  </channel>
</rss>
`;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const [, , version, buildNumber, notesFile, signature, length, downloadUrl, outFile] = process.argv;
  if (!version || !buildNumber || !notesFile || !signature || !length || !downloadUrl || !outFile) {
    console.error(
      "usage: generate-appcast.mjs <version> <buildNumber> <notesFile> <signature> <length> <downloadUrl> <outFile>"
    );
    process.exit(1);
  }

  const notes = readFileSync(notesFile, "utf8").trim();
  const pubDate = new Date().toUTCString();

  const xml = generateAppcast({
    version,
    buildNumber: Number(buildNumber),
    notes,
    pubDate,
    signature,
    length: Number(length),
    downloadUrl,
  });

  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, xml);
  console.log(`[generate-appcast] wrote ${outFile} (version ${version}, build ${buildNumber})`);
}
