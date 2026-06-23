# Cloud Transcription (Deepgram via backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the engine's local faster-whisper/torch transcription with a backend-proxied Deepgram call, shedding ~2 GB from the engine.

**Architecture:** The engine's `transcribe(wav_path) -> str` keeps its signature but POSTs the WAV bytes (raw body, `Content-Type: audio/wav`) to a new authed backend endpoint `POST /transcribe`, which proxies Deepgram's pre-recorded `/v1/listen` and returns `{ "transcript": "..." }`. Diarisation (local, stdlib) and coaching (already backend-proxied) are unchanged. torch/torchaudio/faster-whisper are removed.

**Tech Stack:** Python (FastAPI backend on Vercel; httpx in engine), Deepgram REST (`nova-3`), `requests` (backend, already present).

## Global Constraints

- Deepgram model: `nova-3`; query `language=en&punctuate=true`. (verbatim from spec)
- Deepgram auth header: `Authorization: Token <DEEPGRAM_API_KEY>`. (verbatim)
- `DEEPGRAM_API_KEY` lives only in backend env (Vercel Prod+Dev set; in `.env.local`). Never shipped to client. (verbatim)
- Endpoint auth: reuse existing `Depends(_current_user_id)` (same as `/coach`). (verbatim)
- Engine backend base URL: `os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)` where `BACKEND_URL = "https://www.tryfluent.co/api"`. (verbatim from `fluent-engine/fluent/config.py`)
- Engine auth header: `Authorization: Bearer <token>` where token = `get_token()`. (verbatim from `coach.py`)
- Zero server-side audio persistence: bytes held only for the request duration; nothing written to disk/DB. (verbatim)
- Size guard: reject bodies > 25 MB → `413`. Deepgram/network failure → `502 {"error": "transcription_failed"}`. (verbatim)
- No new backend dependency: read the **raw request body** (`await request.body()`), NOT FastAPI `UploadFile` (avoids adding `python-multipart`). The engine sends raw WAV bytes.
- Do NOT add a Mac local-Whisper fallback flag (dropped per user for simplicity).
- This codebase has no pytest/test framework. Verification is done by running the backend locally and calling it with `curl`/a short Python snippet, matching how the project is validated today. Do not introduce a test framework.

---

### Task 1: Backend `POST /transcribe` endpoint

**Files:**
- Modify: `backend/main.py` (add a new route near `/coach` at line ~901; add `Request` is already imported, line 25)

**Interfaces:**
- Consumes: existing `_current_user_id` dependency (`backend/main.py:358`), `requests` (in `api/requirements.txt`).
- Produces: `POST /transcribe` — auth required; raw body = WAV bytes (`Content-Type: audio/wav`); returns JSON `{ "transcript": str }`. Errors: `401` (no/invalid token, via dependency), `413` (body > 25 MB), `502` `{"error":"transcription_failed"}`.

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, `import os` (line 21), `Request` (line 25), and the local `import requests as _requests` pattern are all already present. No new top-level imports needed. The endpoint uses the codebase's established `import requests as _requests` inside the function body.

Add this route (place it right after the `/coach` handler, after its closing `return`):

```python
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen?model=nova-3&language=en&punctuate=true"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # ~25 min of 16kHz mono int16 WAV


@app.post("/transcribe")
async def transcribe(request: Request, user_id: int = Depends(_current_user_id)):
    import requests as _requests
    audio = await request.body()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large.")
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise HTTPException(502, "transcription_failed")
    try:
        r = _requests.post(
            DEEPGRAM_URL,
            data=audio,
            headers={
                "Authorization": f"Token {key}",
                "Content-Type": "audio/wav",
            },
            timeout=120,
        )
        r.raise_for_status()
        result = r.json()
        text = (
            result["results"]["channels"][0]["alternatives"][0]["transcript"]
        )
    except Exception:
        raise HTTPException(502, "transcription_failed")
    return {"transcript": text}
```

- [ ] **Step 2: Run the backend locally**

Run (from repo root, with `.env.local` loaded — the project's normal dev command):
```bash
cd backend && uvicorn main:app --reload --port 8000
```
Expected: server starts, no import errors. (If `DATABASE_URL` etc. must be loaded, use the project's standard local run; the engine/backend already run locally per CLAUDE.md.)

- [ ] **Step 3: Verify auth is enforced (unauthed → 401)**

In another terminal:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/transcribe --data-binary @/dev/null
```
Expected: `401` (no Bearer token → `_current_user_id` raises).

- [ ] **Step 4: Verify a real transcription (authed) returns text**

Get a valid JWT (sign in via the app, or reuse the token in your Credential Manager/Keychain). Record or grab any short WAV (e.g. an existing `~/.fluent` session `*_mixed.wav`, or any 16 kHz mono WAV). Then:
```bash
TOKEN="<paste a valid JWT>"
WAV="<path to a short wav with speech>"
curl -s -X POST http://localhost:8000/transcribe \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: audio/wav" \
  --data-binary @"$WAV" | head -c 400; echo
```
Expected: `{"transcript":"...some words..."}` with the spoken content.

- [ ] **Step 5: Verify size guard (oversized → 413)**

```bash
TOKEN="<valid JWT>"
head -c 27000000 /dev/zero > /tmp/big.wav
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/transcribe \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: audio/wav" \
  --data-binary @/tmp/big.wav
rm -f /tmp/big.wav
```
Expected: `413`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat(backend): add /transcribe endpoint proxying Deepgram

Authed (reuses _current_user_id), reads raw WAV body, forwards to
Deepgram nova-3, returns {transcript}. 25MB cap -> 413; failures -> 502.
No server-side audio persistence.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Engine `transcribe.py` calls the backend

**Files:**
- Modify: `fluent-engine/fluent/transcribe.py` (full rewrite)

**Interfaces:**
- Consumes: `POST /transcribe` from Task 1; `get_token()` (`fluent-engine/fluent/coach.py:18`); `BACKEND_URL` (`fluent-engine/fluent/config.py:6`); `httpx` (common dep).
- Produces: `transcribe(wav_path: Path, _api_key: str = "") -> str` — same signature `pipeline.py:40` already calls. Returns transcript string; raises `RuntimeError` on not-logged-in / expired, `httpx.HTTPStatusError` on other failures.

- [ ] **Step 1: Rewrite the module**

Replace the entire contents of `fluent-engine/fluent/transcribe.py` with:

```python
"""
Transcription via the Fluent backend, which proxies Deepgram.
The engine uploads the recorded WAV; no local speech model is used.
"""

import os
from pathlib import Path

import httpx

from fluent.config import BACKEND_URL
from fluent.coach import get_token


def transcribe(wav_path: Path, _api_key: str = "") -> str:
    token = get_token()
    if not token:
        raise RuntimeError("Not logged in. Please sign in to Fluent.")

    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    audio = Path(wav_path).read_bytes()
    r = httpx.post(
        f"{url}/transcribe",
        content=audio,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "audio/wav",
        },
        timeout=180,
    )
    if r.status_code == 401:
        raise RuntimeError("Session expired. Please sign in again.")
    r.raise_for_status()
    return r.json().get("transcript", "")
```

- [ ] **Step 2: Verify the module imports cleanly without torch**

```bash
cd fluent-engine
python -c "import ast; ast.parse(open('fluent/transcribe.py').read()); print('parse ok')"
python -c "import importlib,sys; sys.path.insert(0,'.'); m=importlib.import_module('fluent.transcribe'); print('import ok:', m.transcribe.__name__)"
```
Expected: `parse ok` then `import ok: transcribe`. (No `faster_whisper`/`torch` import error — note: if the venv still has torch installed that's fine; the point is `transcribe.py` no longer imports it.)

- [ ] **Step 3: Verify no remaining torch/whisper imports in transcribe.py**

```bash
grep -n "faster_whisper\|torch\|WhisperModel\|MODEL_DIR\|MODELS_DIR" fluent-engine/fluent/transcribe.py || echo "clean"
```
Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
git add fluent-engine/fluent/transcribe.py
git commit -m "feat(engine): transcribe via backend Deepgram proxy

transcribe(wav_path) now uploads the WAV to BACKEND/transcribe with the
same JWT used by /coach, instead of running faster-whisper locally. Same
signature, drop-in for pipeline.py.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Remove the model-download step from onboarding

**Files:**
- Modify: `fluent-engine/fluent/setup_window.py` (replace `step1_model` body, ~line 138-175)

**Interfaces:**
- Consumes: nothing new.
- Produces: `step1_model()` no longer imports `faster_whisper`/`WhisperModel`; it immediately marks the step done and chains to `step2_audio()`. The 3-row UI is preserved (row 0 label still shows, just instantly completes) — minimal change, no layout refactor.

- [ ] **Step 1: Replace the `step1_model` function**

Find `def step1_model():` (currently ~line 138). Replace the ENTIRE function (from `def step1_model():` up to but not including `def step2_audio():`) with:

```python
    def step1_model():
        # Transcription is now performed in the cloud (Deepgram via the
        # backend); there is no local speech model to download.
        root.after(0, lambda: set_active(0))
        root.after(0, lambda: set_skip(0, "Ready"))
        step2_audio()
```

- [ ] **Step 2: Verify no `WhisperModel` / faster_whisper usage remains in setup_window.py**

```bash
grep -n "faster_whisper\|WhisperModel" fluent-engine/fluent/setup_window.py || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Verify the file still parses**

```bash
python -c "import ast; ast.parse(open('fluent-engine/fluent/setup_window.py').read()); print('parse ok')"
```
Expected: `parse ok`.

- [ ] **Step 4: Commit**

```bash
git add fluent-engine/fluent/setup_window.py
git commit -m "feat(engine): drop Whisper model download from onboarding

Cloud transcription means there is no local model to fetch; step1 now
completes instantly and chains to audio setup. UI rows unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Drop torch/torchaudio/faster-whisper from requirements

**Files:**
- Modify: `fluent-engine/requirements-common.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: a `requirements-common.txt` with no torch/torchaudio/faster-whisper lines, so fresh engine environments (Mac and Windows) install ~2 GB lighter.

- [ ] **Step 1: Remove the three lines**

Edit `fluent-engine/requirements-common.txt` to delete the `torch>=2.0.0`, `torchaudio>=2.0.0`, and `faster-whisper>=1.0.0` lines. Result should be:

```
# Cross-platform engine dependencies (macOS + Windows).
# Installed on every platform alongside the OS-specific requirements file.
# Transcription is cloud-based (Deepgram via the backend) — no local ML.
anthropic>=0.28.0
pyaudio>=0.2.14
httpx>=0.27.0
```

- [ ] **Step 2: Verify the heavy deps are gone**

```bash
grep -nE "torch|faster.?whisper" fluent-engine/requirements-common.txt fluent-engine/requirements-win.txt fluent-engine/requirements-mac.txt || echo "clean"
```
Expected: `clean`.

- [ ] **Step 3: Verify a fresh install resolves without torch (dry run)**

```bash
python3 -m venv /tmp/eng-req-test
/tmp/eng-req-test/bin/pip install --dry-run -r fluent-engine/requirements-common.txt 2>&1 | grep -iE "torch|whisper" && echo "UNEXPECTED torch present" || echo "no torch in resolution — good"
rm -rf /tmp/eng-req-test
```
Expected: `no torch in resolution — good`.

- [ ] **Step 4: Commit**

```bash
git add fluent-engine/requirements-common.txt
git commit -m "feat(engine): remove torch/torchaudio/faster-whisper deps

Cloud transcription removes the only consumers of these (~2GB). Fresh
Mac and Windows engine environments are now lightweight, unblocking a
small Windows installer.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end verification (Mac now; Windows tonight on hardware)

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-4. Requires the backend deployed (or run locally with `FLUENT_BACKEND_URL` pointed at it) and a signed-in engine.

- [ ] **Step 1: Deploy backend (or point engine at local)**

If using prod: ensure the `/transcribe` change is deployed to Vercel and `DEEPGRAM_API_KEY` is set on Production (already done this session). If testing locally, run the engine with `FLUENT_BACKEND_URL=http://localhost:8000` against the local backend from Task 1.

- [ ] **Step 2: Full record → report on Mac**

With the Mac app (or engine hand-run) signed in: record a short session with speech, stop, and confirm the report renders with a correct transcript. Confirm in the engine log that it called `/transcribe` (not a local model).

```bash
grep -i "transcrib" "$(python3 -c "import tempfile,os;print(os.path.join('/tmp','fluent-engine.log'))")" 2>/dev/null | tail || echo "(check engine stdout)"
```
Expected: report shows a sensible transcript; coaching issues populate as before.

- [ ] **Step 3: Confirm the engine process imports no torch**

```bash
cd fluent-engine && python -c "import sys; sys.path.insert(0,'.'); from fluent import pipeline; print('torch' in sys.modules)"
```
Expected: `False` (pipeline import chain no longer pulls torch).

- [ ] **Step 4: Windows end-to-end (run tonight on the Windows laptop)**

On Windows: pull the branch, recreate/refresh the engine venv from `requirements-common.txt` + `requirements-win.txt` (now torch-free), launch the app, sign in, record with a YouTube clip + speech, stop, confirm the report renders with a transcript. This is the milestone that proves the lightweight-engine path on Windows.

- [ ] **Step 5: No commit** (verification task). If any fix is needed, it gets its own commit referencing the failing step.

---

## Self-Review

**Spec coverage:**
- Backend `/transcribe` (spec §Components A) → Task 1. ✓
- Engine `transcribe.py` rewrite (§B) → Task 2. ✓
- Drop torch/whisper + model-download step (§C) → Task 4 (deps) + Task 3 (setup_window). ✓
- Windows shell unchanged (§D) → no task needed (correctly nothing to do). ✓
- Mac shared engine, no fallback flag (§E) → honored (no flag added); covered by Task 5 Step 2. ✓
- Verification (§Verification) → Task 5 (Mac no-regression, Windows e2e) + Task 1 Steps 3-5 (auth/size/happy-path). ✓
- Zero retention, size cap, error codes (Global Constraints) → Task 1 endpoint body + Steps 3-5. ✓

**Deviation from spec (intentional, noted in Global Constraints):** spec §A said "multipart/form-data, field audio". The plan uses **raw request body** instead, to avoid adding `python-multipart` (not currently installed) and a new failure mode. Functionally equivalent; Deepgram wants raw bytes anyway. Engine sends raw bytes accordingly (Task 2).

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every command shows expected output. ✓

**Type consistency:** `transcribe(wav_path, _api_key="") -> str` matches `pipeline.py:40`. Endpoint returns `{"transcript": str}`; engine reads `r.json().get("transcript", "")`. `get_token()` / `BACKEND_URL` / `Bearer` header names match source. ✓
