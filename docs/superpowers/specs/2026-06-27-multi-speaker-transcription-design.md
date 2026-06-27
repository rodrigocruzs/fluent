# Multi-speaker meeting transcription — Design

**Date:** 2026-06-27
**Status:** Approved (design), pending implementation plan

## Goal

Transcribe an entire meeting chronologically, attributing each utterance to a
speaker: the user is labeled **"You"**, and every other participant gets a
generic, stable label (**"Speaker 1"**, **"Speaker 2"**, …). Example output for
a Google Meet call with the user plus four others:

```
You:       Hey, can we start?
Speaker 1: Sure, sounds good.
Speaker 2: I had a question about the rollout.
You:       Go ahead.
Speaker 1: Are we still launching Friday?
```

Today Fluent only surfaces the user's own speech. This feature captures and
transcribes everyone, in order, while keeping English coaching focused on the
user.

## Scope decisions (locked during brainstorming)

- **Naming:** Voice-only, generic labels. No meeting-platform integration, no
  real names. Works in any app (Meet, Zoom, Teams) and in person.
- **Diarisation engine:** Deepgram cloud diarization (`diarize=true`), reusing
  the existing transcription call. No local model, no new infra.
- **"You" identification:** Diarise the mixed stream for the full transcript,
  AND transcribe the mic-only file separately. The mic transcript is the oracle
  for which words are "You"; match it against the diarized mixed transcript to
  pick which Deepgram speaker index is the user.
- **Coaching scope:** Unchanged — coach only "You". Others appear in the
  transcript for context/chronology only.
- **macOS capture hardening:** In scope. Detect silent/missing system capture
  and surface it instead of silently degrading to mic-only.
- **ScreenCaptureKit migration:** Out of scope — tracked as a separate, larger
  native effort.
- **Windows parity:** Out of scope for this spec (engine changes apply, but the
  WASAPI capture path is validated separately).

## Current architecture (what exists today)

The engine already records three files per session (`fluent-engine/fluent/audio.py`):

- `session_*_mic.wav` — microphone only
- `session_*_sys.wav` — system audio (other participants, via BlackHole on macOS)
- `session_*.wav` — mixed (mic + system), used for transcription

Pipeline (`fluent-engine/fluent/pipeline.py`):

1. `transcribe(paths.mixed)` → flat transcript string (Deepgram via backend).
2. `diarise(...)` → RMS energy heuristic that only distinguishes mic-dominant
   ("You") vs system-dominant ("Other") windows. **Cannot** separate multiple
   people inside the system stream.
3. `filter_user_segments(...)` → keeps only "You" speech for coaching.
4. Writes `latest.json` + timestamped archive, saves session remotely, fires a
   Darwin notification to wake the Swift frontend.

Transcription (`fluent-engine/fluent/transcribe.py`): compresses WAV → AAC/m4a,
uploads either directly (≤4MB) or via R2 presigned PUT (long sessions). Backend
(`backend/main.py`) proxies Deepgram (`nova-3`) and returns the flat transcript.

Frontend (`frontend/report.js`): `buildTranscript()` renders the flat string as
plain paragraphs, inserting inline issue `<mark>`s by string match.

The capability gap is **not** capture (system audio is already recorded) — it's
that diarisation can't separate multiple participants, and the transcript is a
flat string with no speaker structure.

## Design

### 1. Capture (unchanged) + macOS hardening

Recording stays exactly as-is: `mic.wav`, `sys.wav`, `mixed.wav`. The only
capture work is hardening the BlackHole path so "capture others" is reliable and
failures are visible:

- **Silent-capture detection** (`pipeline.py` / a small helper): after recording,
  compute overall RMS of `sys.wav`. If it is effectively silent across the whole
  session, the system stream captured nothing (BlackHole not routed, headphones,
  declined install). Set a `system_audio_captured: false` flag on the session so
  the report can say "couldn't capture other participants" instead of silently
  producing a mic-only transcript labeled as if it were the whole meeting.
- **Active-output verification** (`platform/mac.py`, surfaced at record start):
  verify the `Fluent Audio` multi-output device is the current system default
  output. If not, warn the user (their meeting audio won't reach BlackHole).
- **Headphones case:** when output is routed to a device outside the aggregate
  (e.g. AirPods), `sys.wav` will be silent → covered by silent-capture detection,
  with a clearer message where detectable.

Hardening is additive and must not break the existing mic-only fallback in
`platform.open_system_capture` (which returns `None` when BlackHole is absent).

### 2. Transcription with diarization (core change)

**Backend (`backend/main.py`):**

- Add `diarize=true` and `utterances=true` to the Deepgram request (both the
  direct-body and the R2 `source_url` paths). `nova-3` supports these.
- `_deepgram_transcribe(...)` returns a structured result, not just the flat
  string:
  - `transcript`: the existing flat string (`channels[0].alternatives[0].transcript`)
    — kept for backward compatibility and coaching input.
  - `utterances`: list of `{speaker: int, transcript: str, start: float, end: float}`
    from `results.utterances[]`.
- Endpoints `/transcribe`, `/transcribe/start` return both fields. Old clients
  that read only `transcript` continue to work.

**Engine (`fluent-engine/fluent/transcribe.py`):**

- `transcribe()` returns a structured object (flat text + utterances) instead of
  a bare string. Callers updated accordingly.
- **"You" attribution** — new step:
  1. Transcribe `mixed.wav` with diarization → diarized utterances with anonymous
     speaker indices (0, 1, 2…).
  2. Transcribe `mic.wav` separately (cheap, mic-only, **no** diarization needed)
     → the user's words with timestamps.
  3. **Match:** for each Deepgram speaker index in the mixed transcript, score how
     well its utterances align with the mic transcript by **time overlap** and
     **text similarity**. The best-matching index is labeled `"You"`.
  4. All remaining speaker indices are mapped to `"Speaker 1"`, `"Speaker 2"`, …
     in order of first appearance.
- Net cost: ~2 Deepgram calls per session (mixed-diarized + mic). The
  direct-vs-R2 upload split is unchanged; both files use the same logic. On the
  R2 path, both files are uploaded.

**Matching heuristic (explicit, to avoid ambiguity):**

- A diarized utterance is attributed to "You" if its time window overlaps mic
  speech AND its text is similar to the overlapping mic text (normalized token
  overlap above a threshold).
- Aggregate per Deepgram speaker index: the index whose utterances most
  consistently match the mic transcript wins the "You" label. Exactly one index
  is chosen as "You"; ties resolve to the index with the greatest total
  mic-overlap duration.
- If `sys.wav` is silent (single-speaker / no system audio captured), there is
  effectively one speaker → label it "You" and emit no "Speaker N".

### 3. Data model

Add a structured `segments` field alongside the existing flat `transcript`.

Session payload (`pipeline.py`, `latest.json`, archive copy):

```json
{
  "date": "June 27, 2026",
  "name": "Afternoon session",
  "duration": 612.0,
  "transcript": "Hey, can we start? ...",          // flat, kept for compat + coaching
  "segments": [
    {"speaker": "You",       "text": "Hey, can we start?",      "start": 0.0, "end": 1.8},
    {"speaker": "Speaker 1", "text": "Sure, sounds good.",      "start": 1.9, "end": 3.2},
    {"speaker": "Speaker 2", "text": "I had a question about…", "start": 3.3, "end": 6.0}
  ],
  "system_audio_captured": true,
  "issues": [ ... ],
  "transcribe_error": ""
}
```

**Backend DB (`backend/database.py`):** add a nullable `segments` JSON/TEXT
column to the `sessions` table — additive migration only, no destructive change.
`save_session_remote` / the save endpoint persist `segments` when present. Old
rows have `segments = NULL` and render via the flat fallback.

### 4. Coaching (minimal change)

`coach.py` keeps coaching **only "You"**:

- Build the coaching input from `segments` where `speaker == "You"` (the diarized
  "You" text is more accurate than today's RMS-filtered estimate). Fall back to
  the flat `transcript` when `segments` is absent (old behavior).
- `report.js` issue-highlighting anchors inline `<mark>`s to "You" turns only.

### 5. Frontend rendering (`frontend/report.js`, `frontend/report.css`)

- `buildTranscript()` renders **speaker-labeled chronological turns** when
  `segments` exists: each turn shows a speaker label ("You" / "Speaker N") and
  the utterance text. "You" turns still carry inline issue `<mark>`s.
- **Flat fallback:** when `segments` is absent (old sessions, or
  `system_audio_captured == false` with mic-only), render the existing
  flat-paragraph view unchanged.
- When `system_audio_captured == false`, show a small notice that other
  participants couldn't be captured.
- Modest CSS for speaker labels; reuse existing transcript typography.

## Data flow (new)

```
record → mic.wav, sys.wav, mixed.wav
   │
   ├─ transcribe(mixed.wav, diarize=true) → flat text + diarized utterances (spk 0,1,2…)
   ├─ transcribe(mic.wav)                 → user words + timestamps  ("You" oracle)
   │
   ├─ attribute → match mic vs mixed → pick "You" index; others → Speaker 1,2,…
   │            → segments[] (speaker-labeled, chronological)
   │
   ├─ coach(You-segments)                 → issues (unchanged scope)
   ├─ silent-capture check (sys.wav RMS)  → system_audio_captured flag
   │
   └─ pipeline writes latest.json + segments → save_session_remote (segments → DB)
                                              → notify_report_ready → frontend renders turns
```

## Error handling & edge cases

- **Deepgram diarization unavailable / errors:** fall back to the existing flat
  transcript (no `segments`); session still saves. Never drop a recording.
- **System audio silent (`system_audio_captured == false`):** treat as
  single-speaker; everything is "You"; show the notice. No fake "Speaker N".
- **Crosstalk / overlapping speech:** the dominant risk. Attribution may
  mislabel overlapping turns; acceptable for v1. Worth prototyping first.
- **mic.wav transcription fails but mixed succeeds:** emit `segments` with
  generic "Speaker N" for all and skip "You" labeling rather than failing the
  session; coaching falls back to flat transcript.
- **Old sessions (no `segments`):** flat rendering, unchanged.
- **Backward compatibility:** flat `transcript` field retained everywhere; new
  fields are additive.

## Testing

- Unit: "You"-attribution matcher against synthetic mic/mixed utterance fixtures
  (clean turns, crosstalk, mic-fails, single-speaker).
- Unit: silent-capture detection on silent vs non-silent `sys.wav`.
- Backend: Deepgram response parsing with `utterances` present/absent.
- Frontend: segment rendering + flat fallback + `system_audio_captured == false`
  notice.
- End-to-end: real multi-party calls on Google Meet and Zoom (3–5 participants),
  verifying chronological order and correct "You" labeling.

## Effort estimate

| Area | Work | Effort |
|---|---|---|
| Backend Deepgram diarization | Add flags, return structured utterances, keep flat fallback | 0.5 day |
| Engine: "You" attribution | 2nd mic call + overlap/text matching, speaker labeling | 1.5–2 days |
| Data model + migration | `segments` JSON field through engine → backend → DB | 0.5 day |
| Pipeline + coaching wiring | Build coaching input from You-segments, store segments | 0.5 day |
| Frontend rendering | Speaker-labeled turns + CSS + flat fallback | 1 day |
| macOS BlackHole hardening | Silent-capture detection, output-device check, warnings | 1 day |
| Testing (real multi-party calls, edge cases) | End-to-end on Meet/Zoom | 1 day |

**Total: ~6–7 working days** for a polished, tested feature.
**MVP (~2–3 days):** skip hardening and "You"-attribution refinement; label all
speakers "Speaker N" (including the user) with no mic-matching.

Windows parity adds ~1 day for the WASAPI capture path (separate validation).

## Out of scope

- Real participant names / meeting-platform integration (Meet/Zoom bots/APIs).
- Local/offline diarisation model.
- ScreenCaptureKit migration (separate native effort).
- Coaching other participants.
- Windows WASAPI capture validation.
```

