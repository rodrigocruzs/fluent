# Left Sidebar Navigation

**Date:** 2026-07-05
**Scope:** App-wide navigation shell (Mac + Windows, shared frontend). Adds a
collapsible left sidebar with Home/Meetings nav and an account popover
(plan + Settings). Does not change report/coaching page internals.

## Goal

Today the app has no persistent navigation: each page (`#sessions-page`,
`#settings-page`, `#recording-page`, `#auth-page`, the report view) is a
full-width sibling `<div>` toggled via `display`, reachable only by
one-way "back" links, and Settings is only reachable via the native macOS
menu bar (⌘,). Add a left sidebar (inspired by Granola's, screenshot
provided by user) with:

- **Home** — existing main page, unchanged content, becomes a nav item.
- **Meetings** — new page showing the full historic sessions list (what
  `#sessions-page`'s "History" section currently renders inline).
- **Account row** — bottom-anchored, opens a popover showing the user's
  current plan and a link into Settings.

Out of scope (explicitly excluded per user request): search, chat, shared
with me, folders, spaces, workspace switching, invite teammates, help
center, mobile app promo, template management.

## Constraints

- Frontend is plain HTML/CSS/vanilla JS: `frontend/report.html`,
  `frontend/report.css`, `frontend/report.js`. No framework, no router, no
  build step for this frontend. All changes stay confined to these three
  files.
- `windows/src/*` is a **generated copy** of `frontend/*`, produced by
  `windows/sync-frontend.mjs`. Never hand-edit `windows/src/*` — changes
  are made once in `frontend/` and picked up automatically on the next
  `tauri build`/`tauri dev`. No Swift or Rust/Tauri changes are needed:
  no new native bridge calls are introduced.
- Keep the existing minimal visual style: white background, soft orange
  accent (`--accent: #C96442`), existing CSS custom properties in
  `report.css`. No heavy cards, bright colors, or gamification.
- Existing page-swap functions (`showSessions()`, `showSettings()`,
  `showOnboarding()`, `loadReport()`, `loadSessions()`) keep their current
  signatures and behavior. The sidebar is additive, not a rewrite of
  navigation internals.
- macOS menu bar Settings item (⌘,) is unchanged and keeps calling
  `showSettings()` — the sidebar is a second, not exclusive, entry point.

## Layout approach

Wrap the existing page divs in one new app-shell container, rather than
duplicating sidebar markup per page or introducing a client-side router:

```html
<div id="app-shell">
  <aside id="sidebar" class="expanded">
    <nav class="sidebar-nav">
      <button class="nav-item" data-nav="home">Home</button>
      <button class="nav-item" data-nav="meetings">Meetings</button>
    </nav>
    <button id="sidebar-collapse-toggle" aria-label="Collapse sidebar">‹</button>
    <div class="sidebar-account" id="sidebar-account-trigger">
      <div class="avatar"></div>
      <span class="account-label">Plan name</span>
    </div>
  </aside>
  <div id="page-content">
    <!-- existing #sessions-page, #settings-page, #recording-page,
         #auth-page, .report-page — unchanged internals -->
    <!-- new: #meetings-page -->
  </div>
</div>
```

`showSessions()`/`showSettings()`/etc. continue to toggle `display` on
children of `#page-content` exactly as they do today on children of
`<body>`; only the parent changes.

**Sidebar-less states:** `#auth-page` (sign-in) and `#recording-page`
(active recording) render full-bleed, no sidebar. `#app-shell` gets a
`.no-sidebar` class toggled alongside those two page states, hiding
`#sidebar` via CSS. All other states (Home, Meetings, Settings, report
view) show the sidebar.

## Collapse behavior

- `#sidebar` toggles between `.expanded` (~220px, icons + labels) and
  `.collapsed` (~56px, icon-only rail) via a class swap, with a CSS
  width transition.
- Toggle control (`#sidebar-collapse-toggle`) lives inside the sidebar.
- State persists across restarts via `localStorage` (key e.g.
  `fluent.sidebarCollapsed`), read on load, defaulting to expanded if
  unset.
- Which nav item is active also persists the same way (key e.g.
  `fluent.activeNav`), read on load to restore Home/Meetings selection;
  falls back to Home if unset or invalid.

## Nav items and active state

Two top-level items: Home, Meetings. Settings is **not** a top-level nav
item — it's reached only via the account popover, matching the request
that Settings live inside the expandable account section.

- Clicking **Home** calls the existing `showSessions()`.
- Clicking **Meetings** calls new `showMeetings()`.
- Active item gets a highlighted class matching whichever top-level page
  is showing. Opening Settings (via the popover) does not change which
  nav item is marked active — Settings is layered on top of whatever was
  last active, and closing it returns to that same page.

## Meetings page

New `#meetings-page` div, sibling to the existing pages, shown by new
`window.showMeetings()`. Reuses the existing `renderSessionsList()`
renderer already in `report.js` — refactored to accept an optional
`limit` parameter (undefined/omitted = render full list, small N = render
a preview slice). Home keeps its current inline History preview
(unchanged behavior, just now calling the shared renderer with a limit);
Meetings renders the same data unlimited. This avoids duplicating the
row-building markup logic in two places.

Session data (fetched once via `loadSessions()` on app start, as today)
is shared between Home's preview and the Meetings page — no duplicate
fetch.

## Account popover

Clicking `#sidebar-account-trigger` toggles a popover positioned above
the account row (`position: absolute; bottom: ...`). Contents:

- Current plan name/status (e.g. "Free trial", "Pro", "Canceled" —
  reusing the same data shape already rendered in Settings' Plan
  section).
- A "Settings" button that calls the existing `showSettings()`.

No workspace switcher, invite flow, add-workspace, help center, or mobile
promo — explicitly out of scope per the request.

Popover closes on outside click or Escape (plain JS: one `document`
click listener that closes the popover when the click target is outside
both the trigger and popover elements, plus a `keydown` listener for
Escape). No new dependency.

### Plan data timing

Plan/billing data (`GET /billing/status`) is currently fetched only when
Settings opens. For the popover to show a plan label immediately (before
the user ever opens Settings), fetch `/billing/status` once on app load,
alongside the existing `loadSessions()` call. Settings' own render path
(`renderBillingStatus()`) is reused/called with this pre-fetched data
rather than re-fetching, unless the data is stale (e.g. after a billing
action like upgrade/cancel, which already triggers `/billing/sync`).

## Error handling

- If `/billing/status` fails on app load, the account popover falls back
  to showing just "Settings" with no plan label (fails soft — Settings
  itself already handles billing errors independently when opened).
- If `localStorage` is unavailable or throws (e.g. private/sandboxed
  context), sidebar state silently defaults to expanded + Home on every
  load — no error surfaced to the user.

## Testing

Manual verification (no existing automated test suite covers
`report.js`/`report.html`):

1. Launch app fresh (cleared localStorage) → sidebar expanded, Home
   active, Home page shows preview history.
2. Click Meetings → full history list renders, Meetings marked active.
3. Click Home → preview history still correct, Home marked active again.
4. Collapse sidebar → icon-only rail, labels hidden; reload app → stays
   collapsed.
5. Click account row → popover opens showing plan + Settings button;
   click outside → popover closes; Escape → popover closes.
6. Click Settings from popover → existing Settings page opens; back
   button returns to previously active page (Home or Meetings).
7. Trigger sign-in (`#auth-page`) and start a recording
   (`#recording-page`) → confirm sidebar is hidden in both states.
8. Repeat 1-7 on Windows build (after `tauri build` picks up synced
   frontend) to confirm parity — no Windows-specific code paths expected,
   but visual/layout regressions in Tauri's webview should be checked.
9. Verify macOS ⌘, still opens Settings independent of sidebar state.
