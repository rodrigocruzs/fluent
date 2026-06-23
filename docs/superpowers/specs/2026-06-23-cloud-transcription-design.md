# Cloud transcription (Deepgram via backend) — design

**Date:** 2026-06-23
**Status:** Approved (design); pending implementation plan

## Problem

Fluent's local engine transcribes meetings with `faster-whisper` + `torch` (~2 GB).
This heavy local-ML dependency is the dominant cost of any installer size — it makes a
small, friendly Windows download impossible and bloats the Mac app too. The product does
not need to work offline.

Modern meeting apps (Granola, etc.) do not bundle transcription: they stream/upload audio
to a cloud STT provider (Granola uses Deepgram), keep only the text, and ship a tiny shell.
We are adopting that model.

## Goal

Replace local transcription with a backend-proxied cloud call to Deepgram, so that:
- the engine sheds `torch` / `torchaudio` / `faster-whisper` entirely (~2 GB);
- the Windows installer becomes a lightweight shell (no Python-ML bundle) — unblocks M6;
- the Mac app gets the same benefit (shared engine, single code path);
- the existing record → stop → transcribe → diarise → coach → report flow is otherwise
  unchanged.

## Non-goals

- Real-time / streaming transcription (current flow is batch: record → stop → transcribe).
  Deepgram's pre-recorded REST endpoint fits the batch flow with no rework.
- Changing diarisation — it is energy-based (pure stdlib `wave`/`struct`, no ML) and stays
  local at zero cost.
- Changing coaching — already backend-proxied to Claude; unchanged.
- A Mac local-Whisper fallback flag — explicitly dropped for simplicity (YAGNI).

## Architecture & data flow

```
engine pipeline.py
  └─ transcribe(mixed.wav)                       [signature unchanged: (wav_path)->str]
       └─ POST  BACKEND/transcribe               (multipart WAV + JWT)
                        │
                 backend /transcribe  ── Deepgram /v1/listen?model=nova-3&language=en
                        │                   header Authorization: Token <DEEPGRAM_API_KEY>
                        │                   (no server-side persistence; Deepgram no-retention)
                 returns { "transcript": "..." }
       ◀── transcript str ──┘
  └─ diarise(mixed.wav)        ← stays LOCAL (stdlib, energy-based)
  └─ coach(...)                ← unchanged (already backend-proxied to Claude)
  └─ write latest.json, save_session_remote, notify_report_ready   ← unchanged
```

Key properties:
- `transcribe(wav_path) -> str` keeps its exact signature — a drop-in swap; `pipeline.py`
  does not change.
- The Deepgram key lives only in backend env (`DEEPGRAM_API_KEY`). It is never shipped to
  the client.
- Auth reuses the existing JWT (same token the engine already uses for `/coach` and
  `save_session_remote`, via `platform.get_token()`).
- Zero server-side audio retention: the WAV bytes exist only for the duration of the
  request; Deepgram's API does not retain by default.

## Components

### A. Backend — new `POST /transcribe` (`backend/main.py`)
Mirrors the existing `/coach` pattern (authed, proxies an AI provider, returns JSON).

- Auth: same JWT dependency as `/coach`.
- Body: `multipart/form-data`, field `audio` = mixed WAV (`audio/wav`).
- Action: forward bytes to `https://api.deepgram.com/v1/listen?model=nova-3&language=en&punctuate=true`
  with header `Authorization: Token <DEEPGRAM_API_KEY>` and `Content-Type: audio/wav`.
- Parse: `results.channels[0].alternatives[0].transcript`.
- Return: `{ "transcript": "<text>" }`.
- Size guard: reject bodies over ~25 MB (≈ 25 min of 16 kHz mono int16 WAV) → `413`.
- Errors: Deepgram non-200 or network failure → `502 {"error": "transcription_failed"}`.
  Engine surfaces this the same way a coach failure surfaces today.
- Deps: uses `requests` (already in `api/requirements.txt`). No new package.
- Env: `DEEPGRAM_API_KEY` — already added to Vercel Production + Development, and present
  in `.env.local`.
- No persistence: nothing written to disk or DB; bytes held only in the request.

### B. Engine — rewrite `transcribe.py`
Same public signature, new body:
```python
def transcribe(wav_path: Path, _api_key: str = "") -> str:
    # read WAV bytes; POST multipart to BACKEND/transcribe with JWT from platform.get_token()
    # return resp.json()["transcript"]; raise on failure
```
- Uses the engine's existing backend base URL + `platform.get_token()` (same JWT path as
  `/coach`, `save_session_remote`).
- Uses `httpx` (already a common dep). No new package.
- Removes the local-model load/download branch.

### C. Engine — drop the local-ML surface
- `requirements-common.txt`: remove `torch`, `torchaudio`, `faster-whisper` (the ~2 GB win).
- `setup_window.py`: remove the Whisper model-download step (the only other torch importer);
  first launch no longer downloads a model.
- Remove `~/.fluent/models` references and the stale `transcribe.py` docstring.

### D. Windows shell — no change
The engine still serves `:2788` and still writes `latest.json`. The shell already proxies
authed calls. M6 packaging becomes trivial: no Python-ML bundle, just engine source + a
lightweight Python.

### E. Mac — same shared engine, no fallback flag
Mac picks up the new `transcribe.py` automatically (single shared code path). No
`FLUENT_LOCAL_WHISPER` escape hatch — dropped for simplicity per user.

## Verification

- **Backend unit:** `POST /transcribe` with a short fixture WAV (authed) returns a sane
  transcript; unauthed → 401; oversized → 413; Deepgram failure simulated → 502.
- **Mac end-to-end (no regression):** record → stop → report renders with a correct
  transcript, now sourced from Deepgram. Confirm `torch` no longer imported.
- **Windows end-to-end (tonight, on hardware):** record → stop → report renders; engine
  runs without torch in its environment.
- **Size:** confirm the engine environment no longer pulls torch/whisper (the installer-size
  win that unblocks M6).

## Risks

1. **Transcript style change** vs local `tiny.en`. Deepgram Nova-3 is more accurate, but
   coaching prompts were tuned against whisper output. *Mitigation:* spot-check coaching
   output quality on a couple of real sessions; coaching prompt is unchanged and operates on
   plain text, so risk is low.
2. **Latency / large files.** A long meeting WAV upload + Deepgram round-trip replaces local
   compute. *Mitigation:* batch endpoint is fast (Nova ~realtime-factor << 1); 25 MB cap
   bounds the worst case.
3. **Per-minute cost** (~$0.0043/min). Acceptable and bounded by auth (per-user) + size cap.
4. **Network dependency** for transcription. Accepted — the product is online-only by design.

## Out of scope
- Streaming transcription, Mac capture changes (ScreenCaptureKit), Windows M6 packaging
  itself (separate milestone, unblocked by this work).
