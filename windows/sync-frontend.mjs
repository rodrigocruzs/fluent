// Sync the shared web UI (../frontend) into ./src for Tauri to serve, and
// inject the Tauri bridge shim so report.js runs unchanged.
//
// Keeps ONE source of truth: frontend/ is authored once and used by both the
// macOS app (bundled directly) and the Windows shell (synced here). Run
// automatically before `tauri dev` / `tauri build` (see package.json), so the
// generated windows/src/ is a build artifact, not hand-edited.

import { copyFileSync, readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, "..", "frontend");
const webSrc = join(here, "web-src");
const out = join(here, "src");

mkdirSync(out, { recursive: true });

// Copy every asset from frontend/ verbatim (report.css, report.js, etc.).
for (const f of readdirSync(frontend)) {
  copyFileSync(join(frontend, f), join(out, f));
}

// Copy the Windows-only web sources (the bridge shim).
for (const f of readdirSync(webSrc)) {
  copyFileSync(join(webSrc, f), join(out, f));
}

// Build index.html from report.html with the bridge shim injected into <head>
// so it loads BEFORE report.js and synthesizes the native bridge interface.
const html = readFileSync(join(frontend, "report.html"), "utf8");
const shimTag = '<script src="tauri-bridge.js"></script>';
if (!html.includes("</head>")) {
  throw new Error("report.html has no </head> to inject the bridge shim into");
}
const injected = html.replace("</head>", `  ${shimTag}\n</head>`);
writeFileSync(join(out, "index.html"), injected);

console.log("[sync-frontend] synced frontend/ -> src/ and wrote index.html with bridge shim");
