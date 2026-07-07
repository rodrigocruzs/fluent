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
