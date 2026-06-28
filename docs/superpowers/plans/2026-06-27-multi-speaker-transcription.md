# Multi-speaker Meeting Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcribe an entire meeting chronologically, labeling the user's speech "You" and every other participant "Speaker 1", "Speaker 2", … in order.

**Architecture:** Reuse the existing three-file capture (mic/sys/mixed). Turn on Deepgram diarization for the mixed file to get per-utterance anonymous speakers, transcribe the mic-only file separately as the "You" oracle, then match the two to pick which Deepgram speaker is the user. Persist a new structured `segments` list alongside the existing flat `transcript` (additive, backward-compatible). Coaching stays scoped to "You". Harden macOS BlackHole capture so a silent system stream is detected and surfaced instead of silently degrading to mic-only.

**Tech Stack:** Python 3.11 (engine, `pytest` for tests), FastAPI + psycopg2 (backend), vanilla JS/CSS (frontend), Deepgram `nova-3` prerecorded API.

## Global Constraints

- Deepgram model/params base URL is `https://api.deepgram.com/v1/listen?model=nova-3&language=en&punctuate=true` — extend, do not replace.
- Never drop a recording: any diarization/attribution/transcription failure must fall back to the existing flat transcript and still save the session.
- All new data fields are **additive**. The flat `transcript` string is retained everywhere. Old sessions (no `segments`) must render and coach exactly as today.
- Speaker labels are exactly `"You"`, `"Speaker 1"`, `"Speaker 2"`, … (others numbered from 1 in first-appearance order).
- Engine system-audio capture must keep working mic-only when BlackHole is absent (`platform.open_system_capture` returns `None`).
- DB migrations use the existing `ALTER TABLE … ADD COLUMN IF NOT EXISTS` pattern in `backend/database.py` — never destructive.
- Coaching scope is unchanged: only "You" speech is coached.

---

## File Structure

**Engine (`fluent-engine/`)**
- `fluent/transcribe.py` — MODIFY: return structured result (flat text + utterances); request diarization on mixed; add mic-only transcription helper.
- `fluent/speakers.py` — CREATE: pure attribution logic (match mic vs diarized utterances → labeled `segments`). No I/O, fully unit-testable.
- `fluent/audio_check.py` — CREATE: `system_audio_captured(sys_path)` RMS silence check. Pure, testable.
- `fluent/pipeline.py` — MODIFY: wire structured transcription + attribution + silence flag into the payload; build coaching input from "You" segments.
- `fluent/coach.py` — MODIFY: `save_session_remote(...)` accepts and posts `segments` + `system_audio_captured`.
- `fluent/platform/mac.py` — MODIFY: add `is_fluent_output_active()` helper.
- `requirements-common.txt` — MODIFY: add `pytest` (dev/test dep).
- `tests/` — CREATE: `tests/test_speakers.py`, `tests/test_audio_check.py`, `tests/test_transcribe.py`.

**Backend (`backend/`)**
- `main.py` — MODIFY: `_deepgram_transcribe` returns flat text + utterances; `/transcribe`, `/transcribe/start` return both; `SessionPayload` + `/sessions` accept `segments` + `system_audio_captured`.
- `database.py` — MODIFY: add `segments`, `system_audio_captured` columns; `save_session(...)` + `get_session_with_issues(...)` persist/return them.

**Frontend (`frontend/`)**
- `report.js` — MODIFY: `buildTranscript` renders speaker-labeled turns when `segments` present; flat fallback otherwise; "couldn't capture others" notice.
- `report.css` — MODIFY: speaker-label styles.

---

## Task 1: Engine test harness + RMS silence detection

**Files:**
- Create: `fluent-engine/fluent/audio_check.py`
- Create: `fluent-engine/tests/__init__.py` (empty)
- Create: `fluent-engine/tests/test_audio_check.py`
- Modify: `fluent-engine/requirements-common.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `audio_check.system_audio_captured(sys_path: pathlib.Path) -> bool` — returns `True` if the WAV at `sys_path` contains non-silent audio (overall RMS ≥ threshold), `False` if missing, empty, or effectively silent.

- [ ] **Step 1: Add pytest to dev requirements**

Append to `fluent-engine/requirements-common.txt`:

```
pytest>=8.0
```

- [ ] **Step 2: Create the empty test package marker**

Create `fluent-engine/tests/__init__.py` with no content (empty file).

- [ ] **Step 3: Write the failing test**

Create `fluent-engine/tests/test_audio_check.py`:

```python
import struct
import wave
from pathlib import Path

from fluent.audio_check import system_audio_captured


def _write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_missing_file_is_not_captured(tmp_path):
    assert system_audio_captured(tmp_path / "nope.wav") is False


def test_silent_file_is_not_captured(tmp_path):
    p = tmp_path / "silent.wav"
    _write_wav(p, [0] * 16000)  # 1s of pure silence
    assert system_audio_captured(p) is False


def test_loud_file_is_captured(tmp_path):
    p = tmp_path / "loud.wav"
    _write_wav(p, [8000, -8000] * 8000)  # 1s of loud tone
    assert system_audio_captured(p) is True
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd fluent-engine && python -m pytest tests/test_audio_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fluent.audio_check'`

- [ ] **Step 5: Write minimal implementation**

Create `fluent-engine/fluent/audio_check.py`:

```python
"""Detect whether the system-audio stream actually captured anything.

On macOS the system stream comes from BlackHole. If the user wore headphones,
declined the driver install, or routed output away from the Fluent aggregate
device, the sys.wav will be silent. We detect that so the report can say so
instead of silently presenting a mic-only transcript as the whole meeting.
"""

import struct
import wave
from pathlib import Path

# int16 scale (0-32767). Matches the silence floor used in diarise.py.
SILENCE_RMS = 200


def _wav_rms(path: Path) -> float:
    if not path.exists() or path.stat().st_size < 44:
        return 0.0
    total_sq = 0
    total_n = 0
    with wave.open(str(path), "rb") as wf:
        while True:
            data = wf.readframes(16000)
            if not data:
                break
            samples = struct.unpack(f"<{len(data) // 2}h", data)
            total_sq += sum(s * s for s in samples)
            total_n += len(samples)
    if total_n == 0:
        return 0.0
    return (total_sq / total_n) ** 0.5


def system_audio_captured(sys_path: Path) -> bool:
    """True if sys.wav contains non-silent audio (other participants heard)."""
    return _wav_rms(Path(sys_path)) >= SILENCE_RMS
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd fluent-engine && python -m pytest tests/test_audio_check.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add fluent-engine/requirements-common.txt fluent-engine/tests/__init__.py fluent-engine/tests/test_audio_check.py fluent-engine/fluent/audio_check.py
git commit -m "feat(engine): detect silent system-audio capture"
```

---

## Task 2: Speaker attribution logic

**Files:**
- Create: `fluent-engine/fluent/speakers.py`
- Create: `fluent-engine/tests/test_speakers.py`

**Interfaces:**
- Consumes: nothing (pure logic over plain dicts).
- Produces:
  - Type alias `Utterance = dict` with keys `speaker: int`, `transcript: str`, `start: float`, `end: float`.
  - `speakers.attribute(mixed_utterances: list[dict], mic_utterances: list[dict]) -> list[dict]` — returns chronological `segments`, each `{"speaker": str, "text": str, "start": float, "end": float}` where exactly one Deepgram index becomes `"You"` (best match to mic) and the rest become `"Speaker 1"`, `"Speaker 2"`, … in first-appearance order. If `mic_utterances` is empty, no index is labeled "You" — all become "Speaker N". If `mixed_utterances` is empty, returns `[]`.

- [ ] **Step 1: Write the failing tests**

Create `fluent-engine/tests/test_speakers.py`:

```python
from fluent.speakers import attribute


def U(speaker, text, start, end):
    return {"speaker": speaker, "transcript": text, "start": start, "end": end}


def test_empty_mixed_returns_empty():
    assert attribute([], [U(0, "hi", 0, 1)]) == []


def test_no_mic_labels_all_as_speakers():
    mixed = [U(0, "hi", 0.0, 1.0), U(1, "hello there", 1.0, 2.5)]
    segs = attribute(mixed, [])
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2"]
    assert segs[0]["text"] == "hi"


def test_you_matched_by_overlap_and_text():
    # Deepgram speaker 0 == the user (matches mic), speaker 1 == someone else.
    mixed = [
        U(0, "hey can we start", 0.0, 1.8),
        U(1, "sure sounds good", 1.9, 3.2),
        U(0, "go ahead", 3.3, 4.0),
    ]
    mic = [
        {"transcript": "hey can we start", "start": 0.0, "end": 1.8},
        {"transcript": "go ahead", "start": 3.3, "end": 4.0},
    ]
    segs = attribute(mixed, mic)
    assert [s["speaker"] for s in segs] == ["You", "Speaker 1", "You"]
    # chronological order preserved
    assert [s["start"] for s in segs] == [0.0, 1.9, 3.3]


def test_other_speakers_numbered_in_first_appearance_order():
    mixed = [
        U(2, "first other", 0.0, 1.0),   # appears first -> Speaker 1
        U(5, "second other", 1.0, 2.0),  # appears next  -> Speaker 2
        U(2, "first again", 2.0, 3.0),   # still Speaker 1
    ]
    segs = attribute(mixed, [])
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2", "Speaker 1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fluent-engine && python -m pytest tests/test_speakers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fluent.speakers'`

- [ ] **Step 3: Write minimal implementation**

Create `fluent-engine/fluent/speakers.py`:

```python
"""Attribute diarized utterances to speakers, labeling the user as "You".

Deepgram returns anonymous integer speaker indices (0, 1, 2…) for the mixed
stream. We identify which index is the user by matching the mixed utterances
against the mic-only transcript (the "You" oracle) using time overlap plus
text similarity. The winning index becomes "You"; all other indices become
"Speaker 1", "Speaker 2", … in order of first appearance.
"""

import re


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _text_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# A mixed utterance counts as "matching the mic" if it overlaps a mic utterance
# in time AND their text is at least this similar.
_MATCH_THRESHOLD = 0.5


def _you_index(mixed_utterances: list[dict], mic_utterances: list[dict]) -> int | None:
    """Pick the Deepgram speaker index that best matches the mic transcript."""
    if not mic_utterances:
        return None
    score: dict[int, float] = {}
    for mu in mixed_utterances:
        best = 0.0
        for mic in mic_utterances:
            if _overlaps(mu["start"], mu["end"], mic["start"], mic["end"]):
                sim = _text_similarity(mu.get("transcript", ""), mic.get("transcript", ""))
                if sim > best:
                    best = sim
        if best >= _MATCH_THRESHOLD:
            # Weight by utterance duration so a long, well-matched turn outvotes
            # a short coincidental overlap.
            dur = max(mu["end"] - mu["start"], 0.0)
            score[mu["speaker"]] = score.get(mu["speaker"], 0.0) + best * (dur + 1.0)
    if not score:
        return None
    return max(score, key=score.get)


def attribute(mixed_utterances: list[dict], mic_utterances: list[dict]) -> list[dict]:
    if not mixed_utterances:
        return []

    you_idx = _you_index(mixed_utterances, mic_utterances)

    # Number other speakers in first-appearance order.
    label_for: dict[int, str] = {}
    next_other = 1
    if you_idx is not None:
        label_for[you_idx] = "You"

    segments: list[dict] = []
    for mu in mixed_utterances:
        idx = mu["speaker"]
        if idx not in label_for:
            label_for[idx] = f"Speaker {next_other}"
            next_other += 1
        segments.append({
            "speaker": label_for[idx],
            "text": mu.get("transcript", ""),
            "start": mu["start"],
            "end": mu["end"],
        })
    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd fluent-engine && python -m pytest tests/test_speakers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add fluent-engine/fluent/speakers.py fluent-engine/tests/test_speakers.py
git commit -m "feat(engine): attribute diarized utterances, label user as You"
```

---

## Task 3: Backend Deepgram diarization

**Files:**
- Modify: `backend/main.py:946` (DEEPGRAM_URL), `backend/main.py:953-988` (`_deepgram_transcribe`), `backend/main.py:990-1084` (`/transcribe`, `/transcribe/start` handlers)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_deepgram_transcribe(...)` now returns `tuple[str, list[dict]]` = `(flat_transcript, utterances)` where each utterance is `{"speaker": int, "transcript": str, "start": float, "end": float}`. `/transcribe` and `/transcribe/start` JSON responses gain a `"utterances"` field (list, possibly empty) alongside the existing `"transcript"` string.

- [ ] **Step 1: Read the current transcription handlers**

Run: `sed -n '946,1085p' backend/main.py`
Confirm the two response sites: `/transcribe` returns `{"transcript": text}` and `/transcribe/start` returns `{"transcript": text}`.

- [ ] **Step 2: Add diarization params to the Deepgram URL**

Modify `backend/main.py:946`:

```python
DEEPGRAM_URL = ("https://api.deepgram.com/v1/listen"
                "?model=nova-3&language=en&punctuate=true"
                "&diarize=true&utterances=true")
```

- [ ] **Step 3: Make `_deepgram_transcribe` return utterances**

Replace the body's return/parse section of `_deepgram_transcribe` (`backend/main.py:953-988`). Change the signature's docstring and the final parse:

```python
def _deepgram_transcribe(*, data: bytes | None = None,
                         source_url: str | None = None,
                         content_type: str = "audio/wav") -> tuple[str, list[dict]]:
    """
    Call Deepgram's prerecorded API either by uploading bytes (short clips) or
    by handing it a URL to fetch (long sessions stored in R2). Returns
    (flat_transcript, utterances) where each utterance is
    {"speaker", "transcript", "start", "end"}. Raises HTTPException(502) on
    any failure.
    """
    import requests as _requests
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise HTTPException(502, "transcription_failed")
    try:
        if source_url is not None:
            r = _requests.post(
                DEEPGRAM_URL,
                json={"url": source_url},
                headers={"Authorization": f"Token {key}",
                         "Content-Type": "application/json"},
                timeout=300,
            )
        else:
            r = _requests.post(
                DEEPGRAM_URL,
                data=data,
                headers={"Authorization": f"Token {key}",
                         "Content-Type": content_type},
                timeout=120,
            )
        r.raise_for_status()
        result = r.json()
        flat = result["results"]["channels"][0]["alternatives"][0]["transcript"]
        raw = result["results"].get("utterances", []) or []
        utterances = [
            {"speaker": int(u.get("speaker", 0)),
             "transcript": u.get("transcript", ""),
             "start": float(u.get("start", 0.0)),
             "end": float(u.get("end", 0.0))}
            for u in raw
        ]
        return flat, utterances
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "transcription_failed")
```

- [ ] **Step 4: Update both call sites to return utterances**

In the `/transcribe` handler (around `backend/main.py:999-1000`), change:

```python
    text, utterances = _deepgram_transcribe(data=audio, content_type=content_type)
    return {"transcript": text, "utterances": utterances}
```

In the `/transcribe/start` handler (around `backend/main.py:1077-1084`), change the call and the return:

```python
        text, utterances = _deepgram_transcribe(source_url=get_url)
```

```python
    return {"transcript": text, "utterances": utterances}
```

(Keep the surrounding R2-delete logic unchanged.)

- [ ] **Step 5: Syntax-check the backend**

Run: `cd backend && python -c "import ast; ast.parse(open('main.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat(backend): return Deepgram diarized utterances alongside transcript"
```

---

## Task 4: Engine transcription returns structured result

**Files:**
- Modify: `fluent-engine/fluent/transcribe.py` (whole file — return shape + mic helper)
- Create/Modify: `fluent-engine/tests/test_transcribe.py`

**Interfaces:**
- Consumes: `/transcribe` + `/transcribe/start` responses now containing `"utterances"` (Task 3).
- Produces:
  - `transcribe(wav_path, _api_key="") -> tuple[str, list[dict]]` = `(flat_transcript, utterances)` (utterances as in Task 3). **Breaking change** to the return type — Task 5 updates the caller.
  - `transcribe_mic(wav_path) -> list[dict]` — transcribes the mic-only WAV and returns its utterances (no diarization needed; uses the same endpoint, ignores speaker indices). Used as the "You" oracle. Returns `[]` on any failure.

- [ ] **Step 1: Write the failing test**

Create `fluent-engine/tests/test_transcribe.py`:

```python
import fluent.transcribe as T


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_transcribe_returns_text_and_utterances(monkeypatch, tmp_path):
    wav = tmp_path / "mixed.wav"
    wav.write_bytes(b"\x00" * 100)

    monkeypatch.setattr(T, "get_token", lambda: "tok")
    monkeypatch.setattr(T, "_compress_to_m4a", lambda p: (b"x" * 10, "audio/mp4"))
    payload = {"transcript": "hey there",
               "utterances": [{"speaker": 0, "transcript": "hey there",
                               "start": 0.0, "end": 1.0}]}
    monkeypatch.setattr(T.httpx, "post", lambda *a, **k: _FakeResp(payload))

    text, utts = T.transcribe(wav)
    assert text == "hey there"
    assert utts[0]["speaker"] == 0


def test_transcribe_mic_returns_utterances_and_swallows_errors(monkeypatch, tmp_path):
    wav = tmp_path / "mic.wav"
    wav.write_bytes(b"\x00" * 100)

    monkeypatch.setattr(T, "get_token", lambda: "tok")
    monkeypatch.setattr(T, "_compress_to_m4a", lambda p: (b"x" * 10, "audio/mp4"))

    payload = {"transcript": "go ahead",
               "utterances": [{"speaker": 0, "transcript": "go ahead",
                               "start": 3.0, "end": 4.0}]}
    monkeypatch.setattr(T.httpx, "post", lambda *a, **k: _FakeResp(payload))
    assert T.transcribe_mic(wav)[0]["transcript"] == "go ahead"

    def _boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(T.httpx, "post", _boom)
    assert T.transcribe_mic(wav) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd fluent-engine && python -m pytest tests/test_transcribe.py -v`
Expected: FAIL (`transcribe` returns a str, not a tuple; `transcribe_mic` missing).

- [ ] **Step 3: Update `transcribe.py` to parse and return utterances**

In `fluent-engine/fluent/transcribe.py`, change `_transcribe_direct` and `_transcribe_via_r2` to return `(text, utterances)`:

In `_transcribe_direct` (replace its final line `return r.json().get("transcript", "")`):

```python
    body = r.json()
    return body.get("transcript", ""), body.get("utterances", []) or []
```

In `_transcribe_via_r2` (replace its final line `return start.json().get("transcript", "")`):

```python
    body = start.json()
    return body.get("transcript", ""), body.get("utterances", []) or []
```

Change the public `transcribe(...)` (the `len(audio) <= DIRECT_UPLOAD_LIMIT` branch already delegates — both branches now return tuples, so no change to its body is needed beyond the type). Update its signature/docstring return type to `tuple[str, list[dict]]`.

- [ ] **Step 4: Add `transcribe_mic`**

Append to `fluent-engine/fluent/transcribe.py`:

```python
def transcribe_mic(wav_path: Path) -> list[dict]:
    """Transcribe the mic-only WAV as the "You" oracle.

    Returns the utterances (speaker indices ignored by the caller). Never
    raises — returns [] on any failure so attribution degrades gracefully to
    generic "Speaker N" labels rather than losing the session.
    """
    try:
        _text, utterances = transcribe(wav_path)
        return utterances
    except Exception as e:
        print(f"[transcribe] mic transcription failed: {e}")
        return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd fluent-engine && python -m pytest tests/test_transcribe.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add fluent-engine/fluent/transcribe.py fluent-engine/tests/test_transcribe.py
git commit -m "feat(engine): structured transcription result + mic-only oracle"
```

---

## Task 5: Pipeline wiring — segments, coaching scope, silence flag

**Files:**
- Modify: `fluent-engine/fluent/pipeline.py` (transcription call, attribution, payload, coaching input)
- Modify: `fluent-engine/fluent/coach.py:54-83` (`save_session_remote` signature + POST body)

**Interfaces:**
- Consumes: `transcribe(...) -> (str, list[dict])` and `transcribe_mic(...)` (Task 4); `speakers.attribute(...)` (Task 2); `audio_check.system_audio_captured(...)` (Task 1).
- Produces: `latest.json` / archive payload gains `"segments": list[dict]` and `"system_audio_captured": bool`. `save_session_remote(..., segments: list[dict], system_audio_captured: bool)` POSTs them to `/sessions`.

- [ ] **Step 1: Update imports and the transcription/attribution block in `pipeline.py`**

In `fluent-engine/fluent/pipeline.py`, update the imports near the top:

```python
from fluent.transcribe import transcribe, transcribe_mic
from fluent.speakers import attribute
from fluent.audio_check import system_audio_captured
```

(Keep the existing `from fluent.diarise import ...` import; `filter_user_segments`/`LABEL_USER` are no longer used for coaching but leave them to avoid touching unrelated code — see Step 2.)

Replace the transcription + diarisation block (`pipeline.py:44-62`, from the `print("[pipeline] transcribing ...")` line through the `user_transcript = (...)` assignment) with:

```python
    print(f"[pipeline] transcribing {paths.mixed} ...")
    transcript = ""
    utterances: list[dict] = []
    transcribe_error = ""
    try:
        transcript, utterances = transcribe(paths.mixed)
        print(f"[pipeline] {len(transcript)} chars, {len(utterances)} utterances")
    except Exception as e:
        transcribe_error = str(e)
        print(f"[pipeline] transcription failed, saving session anyway: {e}")

    # Did we actually capture the other participants?
    sys_captured = system_audio_captured(paths.sys)
    print(f"[pipeline] system audio captured: {sys_captured}")

    # Build speaker-labeled segments. Mic transcript is the "You" oracle.
    segments: list[dict] = []
    if utterances:
        mic_utterances = transcribe_mic(paths.mic)
        segments = attribute(utterances, mic_utterances)
    print(f"[pipeline] {len(segments)} segment(s)")

    # Coaching input: only the user's ("You") speech. Fall back to the flat
    # transcript when we have no segments (diarization unavailable / old path).
    you_text = "\n".join(s["text"] for s in segments if s["speaker"] == "You")
    coaching_source = you_text if you_text.strip() else transcript
    user_transcript = coaching_source
```

- [ ] **Step 2: Point coaching at the new source**

In `pipeline.py`, the coaching guard currently reads `if transcript.strip():`. Change it to use `coaching_source`:

```python
    issues = []
    if coaching_source.strip():
        print("[pipeline] coaching ...")
        try:
            issues = coach(user_transcript, config)
        except Exception as e:
            print(f"[pipeline] coaching failed, saving session without issues: {e}")
            issues = []
    else:
        print("[pipeline] empty transcript — skipping coaching")
```

- [ ] **Step 3: Add `segments` and `system_audio_captured` to the payload**

In `pipeline.py`, extend the `payload = {...}` dict (after the `transcribe_error` key):

```python
    payload = {
        "date": now.strftime("%B %d, %Y"),
        "name": name,
        "duration": duration,
        "transcript": saved_transcript,
        "segments": segments,
        "system_audio_captured": sys_captured,
        "issues": issues,
        "transcribe_error": transcribe_error,
    }
```

- [ ] **Step 4: Pass the new fields to `save_session_remote`**

In `pipeline.py`, update the `save_session_remote(...)` call:

```python
    save_session_remote(
        slug=slug,
        name=payload["name"],
        date=payload["date"],
        duration=duration,
        transcript=saved_transcript,
        issues=issues,
        segments=segments,
        system_audio_captured=sys_captured,
    )
```

- [ ] **Step 5: Update `save_session_remote` in `coach.py`**

Replace the `save_session_remote` signature and JSON body (`coach.py:54-83`):

```python
def save_session_remote(slug: str, name: str, date: str,
                        duration: float, transcript: str, issues: list,
                        segments: list | None = None,
                        system_audio_captured: bool = True) -> None:
    """POST the completed session to the backend for persistent storage."""
    token = get_token()
    if not token:
        return
    url = os.environ.get("FLUENT_BACKEND_URL", BACKEND_URL)
    try:
        r = httpx.post(
            f"{url}/sessions",
            json={
                "slug": slug,
                "name": name,
                "date": date,
                "duration": duration,
                "transcript": transcript,
                "issues": issues,
                "segments": segments or [],
                "system_audio_captured": system_audio_captured,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        print(f"[coach] session saved remotely (id={r.json().get('id')})")
    except Exception as e:
        print(f"[coach] failed to save session remotely: {e}")
```

- [ ] **Step 6: Syntax-check the engine modules**

Run: `cd fluent-engine && python -c "import ast; [ast.parse(open(f).read()) for f in ('fluent/pipeline.py','fluent/coach.py')]; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Run the full engine test suite**

Run: `cd fluent-engine && python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1, 2, 4 green)

- [ ] **Step 8: Commit**

```bash
git add fluent-engine/fluent/pipeline.py fluent-engine/fluent/coach.py
git commit -m "feat(engine): wire segments + silence flag into pipeline, coach You-only"
```

---

## Task 6: Backend persistence of segments

**Files:**
- Modify: `backend/database.py:67-73` (sessions DDL), `backend/database.py:45-60` (migration list — add a sessions migration block), `backend/database.py:137-166` (`save_session`), `backend/database.py:312-328` (`get_session_with_issues`)
- Modify: `backend/main.py:1089-1115` (`SessionPayload` + `/sessions` handler)

**Interfaces:**
- Consumes: `POST /sessions` body now includes `segments: list[dict]` and `system_audio_captured: bool` (Task 5).
- Produces: `sessions` rows persist `segments` (JSON text) + `system_audio_captured` (bool). `get_session_with_issues(...)` returns both fields. `/sessions/{slug}` includes them.

- [ ] **Step 1: Add columns to the sessions DDL**

In `backend/database.py`, inside the `CREATE TABLE IF NOT EXISTS sessions (...)` block (`database.py:67-73`), add two columns before the closing `UNIQUE (user_id, slug)`:

```python
                    transcript  TEXT    NOT NULL DEFAULT '',
                    segments    TEXT    NOT NULL DEFAULT '[]',
                    system_audio_captured BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at  FLOAT   NOT NULL,
```

- [ ] **Step 2: Add a migration block for existing sessions tables**

In `backend/database.py`, immediately after the `sessions` `CREATE TABLE` statement (before the `issues` CREATE TABLE), add the additive migration using the existing pattern:

```python
            for col, definition in [
                ("segments",              "TEXT NOT NULL DEFAULT '[]'"),
                ("system_audio_captured", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ]:
                cur.execute(f"""
                    ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {col} {definition}
                """)
```

- [ ] **Step 3: Persist the new fields in `save_session`**

In `backend/database.py`, update `save_session` (`database.py:137-166`). Change the signature and the INSERT:

```python
def save_session(user_id: int, slug: str, name: str, date: str,
                 duration: float, transcript: str,
                 issues: list[dict],
                 segments: list[dict] | None = None,
                 system_audio_captured: bool = True) -> int:
    import json
    segments_json = json.dumps(segments or [])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sessions (user_id, slug, name, date, duration, transcript,
                                      segments, system_audio_captured, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, slug) DO UPDATE
                    SET name                  = EXCLUDED.name,
                        date                  = EXCLUDED.date,
                        duration              = EXCLUDED.duration,
                        transcript            = EXCLUDED.transcript,
                        segments              = EXCLUDED.segments,
                        system_audio_captured = EXCLUDED.system_audio_captured
                RETURNING id
            """, (user_id, slug, name, date, duration, transcript,
                  segments_json, system_audio_captured, time.time()))
            session_id = cur.fetchone()[0]
```

(Leave the rest of `save_session` — the issues DELETE/INSERT and `return session_id` — unchanged.)

- [ ] **Step 4: Return the new fields from `get_session_with_issues`**

In `backend/database.py`, update the SELECT in `get_session_with_issues` (`database.py:314-317`):

```python
            cur.execute("""
                SELECT id, slug, name, date, duration, transcript,
                       segments, system_audio_captured
                FROM sessions WHERE user_id = %s AND slug = %s
            """, (user_id, slug))
            session = cur.fetchone()
            if not session:
                return None
```

Then after `session = dict(session)` and before `session["issues"] = cur.fetchall()`, parse the JSON column:

```python
            session = dict(session)
            import json
            try:
                session["segments"] = json.loads(session.get("segments") or "[]")
            except (ValueError, TypeError):
                session["segments"] = []
```

- [ ] **Step 5: Accept the new fields in `SessionPayload` and the handler**

In `backend/main.py`, extend `SessionPayload` (`main.py:1089-1095`):

```python
class SessionPayload(BaseModel):
    slug: str
    name: str
    date: str
    duration: float = 0
    transcript: str = ""
    issues: list[dict] = []
    segments: list[dict] = []
    system_audio_captured: bool = True
```

Update the `create_session` handler's `save_session(...)` call (`main.py:1099-1107`) to pass them:

```python
    session_id = save_session(
        user_id=user_id,
        slug=payload.slug,
        name=payload.name,
        date=payload.date,
        duration=payload.duration,
        transcript=payload.transcript,
        issues=payload.issues,
        segments=payload.segments,
        system_audio_captured=payload.system_audio_captured,
    )
```

- [ ] **Step 6: Syntax-check the backend**

Run: `cd backend && python -c "import ast; [ast.parse(open(f).read()) for f in ('main.py','database.py')]; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat(backend): persist session segments + system_audio_captured"
```

---

## Task 7: macOS output-routing check

**Files:**
- Modify: `fluent-engine/fluent/platform/mac.py` (add helper)

**Interfaces:**
- Consumes: `blackhole` module's device helpers.
- Produces: `mac.is_fluent_output_active() -> bool` — True if the current system default output is the Fluent multi-output aggregate device (so meeting audio reaches BlackHole). Best-effort; returns `True` on any error so it never blocks recording.

- [ ] **Step 1: Add the helper to `platform/mac.py`**

Append to `fluent-engine/fluent/platform/mac.py`:

```python
def is_fluent_output_active() -> bool:
    """True if the system default output routes through the Fluent aggregate
    device (so other participants' audio reaches BlackHole). Best-effort:
    returns True on any error so it never blocks recording.
    """
    try:
        from fluent import blackhole
        import ctypes, struct
        sel_def_out = struct.unpack(">I", b"dOut")[0]
        sel_glob = struct.unpack(">I", b"glob")[0]
        addr = blackhole._Addr(sel_def_out, sel_glob, 0)
        sz = ctypes.c_uint32(4)
        buf = ctypes.create_string_buffer(4)
        err = blackhole._ca.AudioObjectGetPropertyData(
            ctypes.c_uint32(blackhole.kAudioObjectSystemObject),
            ctypes.byref(addr), 0, None, ctypes.byref(sz), buf)
        if err != 0:
            return True
        cur_id = struct.unpack("<I", buf.raw[:4])[0]
        name = blackhole._device_name(cur_id)
        return blackhole.MULTI_OUTPUT_NAME.lower() in name.lower()
    except Exception:
        return True
```

- [ ] **Step 2: Syntax-check**

Run: `cd fluent-engine && python -c "import ast; ast.parse(open('fluent/platform/mac.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Manual verification (macOS only)**

Run: `cd fluent-engine && python -c "from fluent.platform import mac; print(mac.is_fluent_output_active())"`
Expected: prints `True` or `False` without raising. (Value depends on whether the Fluent aggregate device is currently the default output.)

- [ ] **Step 4: Commit**

```bash
git add fluent-engine/fluent/platform/mac.py
git commit -m "feat(engine): detect whether Fluent output routing is active"
```

---

## Task 8: Frontend speaker-labeled transcript rendering

**Files:**
- Modify: `frontend/report.js:105-123` (`buildTranscript`), `frontend/report.js:270-307` (render: read `segments` + `system_audio_captured`)
- Modify: `frontend/report.css:760-790` (add speaker-label styles)

**Interfaces:**
- Consumes: report `data` now may include `data.segments` (list of `{speaker, text, start, end}`) and `data.system_audio_captured` (bool).
- Produces: rendered speaker-labeled turns when `segments` present; flat fallback otherwise; notice when others weren't captured.

- [ ] **Step 1: Make `buildTranscript` render segments when present**

Replace `buildTranscript` (`frontend/report.js:107-123`) with:

```javascript
  function buildTranscript(issues, transcriptText, segments) {
    // Speaker-labeled chronological turns when diarized segments exist.
    if (Array.isArray(segments) && segments.length) {
      return segments.map((seg) => {
        let text = esc(seg.text || '');
        // Only the user's ("You") turns carry inline issue marks.
        if (seg.speaker === 'You') {
          issues.forEach((issue, idx) => {
            const n = idx + 1;
            const original = issue.original || '';
            if (!original || !(seg.text || '').includes(original)) return;
            const mark =
              `<mark class="flag" data-issue="${n}" id="flag-${n}">${esc(original)}` +
              `<span class="num">${n}</span></mark>`;
            text = text.replace(esc(original), () => mark);
          });
        }
        const who = esc(seg.speaker || 'Speaker');
        const cls = seg.speaker === 'You' ? 'turn turn-you' : 'turn';
        return `<div class="${cls}"><span class="turn-speaker">${who}</span>` +
               `<p class="turn-text">${text}</p></div>`;
      }).join('\n');
    }

    // Flat fallback (old sessions, or no diarization).
    let text = transcriptText || '';
    issues.forEach((issue, idx) => {
      const n = idx + 1;
      const original = issue.original || '';
      if (!original || !text.includes(original)) return;
      const replacement =
        `<mark class="flag" data-issue="${n}" id="flag-${n}">${esc(original)}` +
        `<span class="num">${n}</span></mark>`;
      text = text.replace(original, () => replacement);
    });
    const paras = text.split(/\n\n+/).filter(p => p.trim());
    if (!paras.length) paras.push(text);
    return paras.map(p => `<p>${p}</p>`).join('\n');
  }
```

- [ ] **Step 2: Read `segments` + capture flag in the main render and pass them through**

In `window.loadReport` (`frontend/report.js:270-286`), after `const transcript = data.transcript || '';` add:

```javascript
    const segments     = Array.isArray(data.segments) ? data.segments : [];
    const systemCaptured = data.system_audio_captured !== false;
```

Update the `hasTranscript` computation (it must be true when we have segments too):

```javascript
    const hasTranscript = transcript.trim().length > 0 || segments.length > 0;
```

Find the call `const transcriptHTML = buildTranscript(issues, transcript);` (around `report.js:305`) and replace it with:

```javascript
      const captureNotice = (!systemCaptured && segments.length === 0)
        ? '<p class="capture-notice">Only your microphone was captured this session — other participants weren&rsquo;t recorded.</p>'
        : '';
      const transcriptHTML = captureNotice + buildTranscript(issues, transcript, segments);
```

- [ ] **Step 3: Add speaker-label CSS**

Append to `frontend/report.css` (after the `.transcript .pause` block, around line 788):

```css
/* ── Speaker-labeled turns ── */
.transcript .turn { margin: 0 0 1.1em; }
.transcript .turn-speaker {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--gray-3);
  font-weight: 600;
  margin-bottom: 2px;
}
.transcript .turn-you .turn-speaker { color: var(--ink-2); }
.transcript .turn-text { margin: 0; }

.transcript .capture-notice {
  font-size: 13px;
  color: var(--gray-3);
  font-style: italic;
  margin: 0 0 1.4em;
}
```

- [ ] **Step 4: Manual verification with mock data**

Open `frontend/report.html` in a browser (or the app's report view) and in the console call:

```javascript
loadReport({
  name: "Test", date: "June 27, 2026", duration: 60,
  transcript: "hey can we start sure sounds good go ahead",
  segments: [
    {speaker:"You", text:"hey can we start", start:0, end:1.8},
    {speaker:"Speaker 1", text:"sure sounds good", start:1.9, end:3.2},
    {speaker:"You", text:"go ahead", start:3.3, end:4}
  ],
  system_audio_captured: true,
  issues: []
});
```

Expected: transcript shows three turns with "You" / "Speaker 1" labels in order.
Then call the same with `segments: []` and a flat `transcript` — expect the old flat-paragraph rendering.

- [ ] **Step 5: Commit**

```bash
git add frontend/report.js frontend/report.css
git commit -m "feat(frontend): render speaker-labeled transcript turns with flat fallback"
```

---

## Task 9: End-to-end verification

**Files:** none (manual verification + bundled-frontend rebuild reminder).

- [ ] **Step 1: Run the complete engine test suite**

Run: `cd fluent-engine && python -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1, 2, 4).

- [ ] **Step 2: Rebuild + reinstall the app with the bundled frontend**

The app loads a **bundled** copy of `frontend/`. Per the project's frontend build workflow, rebuild the app, reinstall to `/Applications`, and bump the cache so the new `report.js`/`report.css` take effect. (Follow the project's existing build/reinstall steps — `build_dmg.sh` / `ship.sh`.)

- [ ] **Step 3: Live multi-party call test**

Join a Google Meet (or Zoom) with at least 2 other participants. Record a short session through Fluent. After it ends, open the report and verify:
- Transcript shows chronological turns labeled "You" / "Speaker 1" / "Speaker 2".
- Your own lines are labeled "You" and carry any coaching marks.
- Coaching issues only reference your speech.

- [ ] **Step 4: Headphones / silent-capture test**

Repeat a short recording while wearing headphones (so system audio bypasses the Fluent aggregate device). Verify the report shows only your speech and the "other participants weren't recorded" notice (flat fallback, `system_audio_captured == false`).

- [ ] **Step 5: Final commit (if any verification fixes were needed)**

```bash
git add -A
git commit -m "test: verify multi-speaker transcription end-to-end"
```

---

## Notes for the implementer

- **Run tests from `fluent-engine/`** so `import fluent.*` resolves (the package root is `fluent-engine/`). If imports fail, run `python -m pytest` (not bare `pytest`) from that directory.
- **The mic file is reused, not re-recorded** — `paths.mic` already exists from capture; Task 5 just transcribes it a second time as the "You" oracle.
- **Backward compatibility is load-bearing:** every consumer must tolerate missing `segments` (old sessions). The flat `transcript` path is the fallback throughout.
- **Crosstalk is the known weak point** — `speakers.attribute` may mislabel overlapping turns. That's accepted for v1 (see spec). The `_MATCH_THRESHOLD` and duration weighting in `speakers.py` are the tuning knobs if attribution proves noisy in Step 3 of Task 9.
