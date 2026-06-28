# Coaching Report Redesign

**Date:** 2026-06-28
**Scope:** The session/coaching report page only (`window.loadReport` render path). Not the home/sessions page.

## Goal

Transform the session page from a transcript viewer with sentence-level English
corrections into a post-meeting communication coaching report that answers:
"How can I communicate better next time?"

Fluent is not just correcting spoken English — it helps non-native professionals
become clearer, more confident, and more effective in workplace communication.

## Constraints

- Keep the existing minimal style: white background, whitespace, clean typography,
  soft orange accent (`--accent: #C96442`). No heavy cards, bright colors, charts,
  badges, or gamification. Linear / Notion / Apple / Raycast feel. Premium and calm.
- Keep the existing route and data fetching. Entry point `window.loadReport(data)`
  stays. No backend changes. No `report.html` changes.
- Copy tone: supportive executive communication coach. Avoid "mistake", "wrong",
  "bad", "score", "errors". Prefer "opportunity", "pattern", "try this",
  "why this matters", "rule to remember".

## Data model (existing, unchanged)

`data` passed to `loadReport`:
- `issues[]` — each: `category`, `original`, `improved` | `better_phrasing`, `explanation`
- `transcript` (string), `segments[]` (speaker turns: `{speaker, text}`)
- `duration`, `slug`, `name`, `date`, `system_audio_captured`, optional `strengths[]`

## Coaching adapter — `buildCoaching(data, meetingType)`

Maps flat issues into a coaching model. Resilient to missing fields.

Per pattern:
- `categoryLabel` ← `issue.category` (fallback "Clarity")
- `said` ← `issue.original`
- `tryThis` ← `issue.improved` || `issue.better_phrasing`
- `whyMatters` ← `issue.explanation`, else a meeting-type-aware generated line
- `diagnosis` ← generated client-side from category via lookup (generic fallback)
- `rule` ← generated client-side from category via lookup (generic fallback)
- `count` ← number of issues sharing the same normalized category; "Seen N times
  today" rendered only when N > 1

Derived sections:
- **Biggest lesson** ← from `data.biggest_lesson` if present, else synthesized from
  the most-frequent category (headline + description keyed by category), else
  falls back to the first issue's category. Description references the meeting type.
- **Strengths** ← `data.strengths[]` if present, else 2–3 fallbacks:
  "You explained the business context clearly.", "You kept a professional tone.",
  "You moved the conversation forward."

Lookup tables (category → diagnosis/rule/lesson) live as small const maps in
`report.js` with a `DEFAULT` entry. Do not overbuild the data layer.

## Meeting type

Values: Internal Team Meeting, 1:1 with Manager, Candidate Interview, Customer Call,
Technical Discussion, Stakeholder Update, Behavioral Interview, Other.

- Default "Internal Team Meeting" if not provided (use `data.meeting_type` if present).
- Editable via a styled native `<select>` near the title/meta:
  "Coaching based on: [Internal Team Meeting ▾]".
- Persisted to `localStorage` keyed by session slug (`fluent_meeting_type_<slug>`),
  so it survives reopening. `// TODO: persist meeting type to backend` marks where
  real persistence belongs.
- Changing it live re-renders the hero supporting line, the biggest-lesson
  description, and each pattern's "why this matters" (the parts that name the
  meeting type) — without a full page reload or losing transcript expand state.

## Page structure (single column, ~640px content width)

1. **SessionHeader** — back link, title, meta line ("June 13, 2026 · 09:31 · 22 sec"),
   MeetingTypeSelector.
2. **Hero** — "Your biggest opportunities from this meeting" +
   "Based on this being an Internal Team Meeting." (updates on type change).
   Replaces the old "N suggestions across Ys of your speech."
3. **BiggestLesson** — eyebrow "Today's biggest lesson", headline, description.
4. **CoachingPattern** list — each pattern shows: category label, diagnosis,
   "Why this matters", "What you said" (excerpt), "Try this next time" (improved),
   "Rule to remember", and occurrence count when > 1.
5. **StrengthsSection** — "What you did well", 2–3 calm encouraging strengths.
6. **TranscriptSection** — collapsed by default behind a "Show transcript" button.
   Expanded: existing clean transcript (speaker turns or flat fallback).
   `mark.flag` anchors keep their underline but drop the superscript number and
   the margin-note hover wiring (no margin column exists anymore).

## States

- **Has issues:** full structure above.
- **No issues, transcript present:** hero becomes "Nothing major to improve from
  this short recording." Still show meta, meeting-type selector, StrengthsSection,
  and collapsed/available transcript. No "No suggestions" as the main message.
- **No transcript (silence):** keep the existing `.no-transcript` state unchanged.

## Components (functions in report.js)

`renderSessionHeader`, `renderMeetingTypeSelector`, `renderHero`, `renderBiggestLesson`,
`renderCoachingPattern`/`renderPatterns`, `renderStrengths`, `renderTranscriptSection`.
Plus `buildCoaching` adapter and a `rerenderMeetingTypeDependent()` for live updates.

## CSS

New classes using existing tokens only: `.coaching-hero`, `.coaching-hero-sub`,
`.meeting-type`, `.lesson`, `.lesson-eyebrow`, `.lesson-headline`, `.lesson-desc`,
`.patterns`, `.pattern`, `.pattern-category`, `.pattern-diagnosis`, `.pattern-why`,
`.pattern-said`, `.pattern-try`, `.pattern-rule`, `.pattern-count`, `.strengths`,
`.strength`, `.transcript-toggle`. Narrow `.report-page` max-width (single column).
Keep `mark.flag` underline; remove `.num` rendering in JS.

## Out of scope

Home/sessions page redesign. Backend persistence of meeting type. New backend
fields for strengths/lesson (consumed if present, otherwise fallbacks).
