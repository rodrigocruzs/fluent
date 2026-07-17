# Meeting Type Zero-Debt Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend the single source of truth for a session's meeting type, eliminating the localStorage split-brain, the write asymmetry, the duplicated enum, and the "display-only" dead field.

**Architecture:** The backend owns the canonical meeting-type enum, validates every write, and serves the list to clients. Sessions store `meeting_type` in Postgres and expose read (`GET /sessions`, `GET /sessions/{slug}`) and write (`PATCH /sessions/{slug}`) paths. Pre-record intent (a type chosen on a Coming Up calendar row) is persisted server-side keyed by calendar event id and joined into `GET /calendar/upcoming`. The engine forwards the type into `/coach` so it actually shapes coaching. The frontend reads and writes exclusively through the API — it never persists meeting type in localStorage.

**Tech Stack:** FastAPI + psycopg2 (Neon Postgres) backend; Python stdlib HTTP engine (`fluent-engine`); vanilla-JS WebView frontend (`frontend/report.js`, mirrored to `windows/src/report.js`); pytest for backend + engine tests.

## Global Constraints

- Canonical meeting types (exact strings, order matters for the dropdown): `Internal Team Meeting`, `1:1 with Manager`, `Candidate Interview`, `Customer Call`, `Technical Discussion`, `Stakeholder Update`, `Behavioral Interview`, `Other`.
- Default meeting type: `Internal Team Meeting`.
- Never run destructive SQL. Schema changes use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` (matches existing migration style in `backend/database.py`).
- Do not print, expose, or commit DB credentials.
- Frontend changes must be applied identically to BOTH `frontend/report.js` (Mac) and `windows/src/report.js` (Windows). The two files are kept byte-identical for the shared logic. HTML/CSS live in `frontend/report.html`/`report.css` and `windows/src/index.html`/`report.css`.
- The Mac app loads a BUNDLED copy of `frontend/`; after frontend or engine changes, the cache-buster in `frontend/report.html` (`report.js?v=NN`) must be bumped, and the app rebuilt + reinstalled. This is handled once at the end (Task 9), not per task.
- Every backend `meeting_type` write validates against the canonical enum; unknown values are rejected with HTTP 422 (not silently coerced), EXCEPT the engine save path which coerces unknown/missing to `NULL` (so a stale client can't 500 the pipeline).
- Commit after each task.

---

## File Structure

- `backend/meeting_types.py` — **new**. Single source of truth: `MEETING_TYPES` tuple, `DEFAULT_MEETING_TYPE`, `is_valid_meeting_type()`, `normalize_meeting_type()`.
- `backend/main.py` — modify. `GET /meeting-types`; `PATCH /sessions/{slug}`; validate `meeting_type` on `POST /sessions`; thread `meeting_type` into `/coach` + `COACH_SYSTEM`; join event types into `GET /calendar/upcoming`; new `PUT /calendar/events/{event_id}/meeting-type`.
- `backend/database.py` — modify. `update_session_meeting_type()`; `event_meeting_types` table + `get_event_meeting_types()` / `set_event_meeting_type()`.
- `backend/tests/test_meeting_type.py` — **new**. Enum validation, PATCH, event-type store, calendar join, coach threading.
- `fluent-engine/fluent/coach.py` — modify. `coach()` sends `meeting_type`; `save_session_remote` already sends it (no change).
- `fluent-engine/fluent/pipeline.py` — modify. Pass `meeting_type` into `coach()`.
- `fluent-engine/tests/test_coach.py` — modify. Assert `coach()` includes `meeting_type`.
- `frontend/report.js` + `windows/src/report.js` — modify. Drop all localStorage meeting-type storage; read enum from API; read/write session type via API; read/write Coming Up type via API.
- `frontend/report.html` + `windows/src/index.html` — modify only if cache-buster bump (Task 9).

---

## Task 1: Canonical meeting-type module (backend source of truth)

**Files:**
- Create: `backend/meeting_types.py`
- Test: `backend/tests/test_meeting_type.py`

**Interfaces:**
- Produces:
  - `MEETING_TYPES: tuple[str, ...]` — the 8 canonical strings in order.
  - `DEFAULT_MEETING_TYPE: str` — `"Internal Team Meeting"`.
  - `is_valid_meeting_type(value: str | None) -> bool`
  - `normalize_meeting_type(value: str | None) -> str | None` — returns the value if valid, else `None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_meeting_type.py`:

```python
from backend.meeting_types import (
    MEETING_TYPES, DEFAULT_MEETING_TYPE,
    is_valid_meeting_type, normalize_meeting_type,
)


def test_enum_shape():
    assert MEETING_TYPES[0] == "Internal Team Meeting"
    assert DEFAULT_MEETING_TYPE == "Internal Team Meeting"
    assert "Other" in MEETING_TYPES
    assert len(MEETING_TYPES) == 8


def test_is_valid():
    assert is_valid_meeting_type("Customer Call") is True
    assert is_valid_meeting_type("Nonsense") is False
    assert is_valid_meeting_type(None) is False
    assert is_valid_meeting_type("") is False


def test_normalize():
    assert normalize_meeting_type("1:1 with Manager") == "1:1 with Manager"
    assert normalize_meeting_type("Nonsense") is None
    assert normalize_meeting_type(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.meeting_types'`

- [ ] **Step 3: Write the module**

Create `backend/meeting_types.py`:

```python
"""Single source of truth for meeting types across backend, engine, and client.

The client fetches this list via GET /meeting-types and the engine imports it,
so the canonical set lives in exactly one place.
"""

MEETING_TYPES: tuple[str, ...] = (
    "Internal Team Meeting",
    "1:1 with Manager",
    "Candidate Interview",
    "Customer Call",
    "Technical Discussion",
    "Stakeholder Update",
    "Behavioral Interview",
    "Other",
)

DEFAULT_MEETING_TYPE = "Internal Team Meeting"


def is_valid_meeting_type(value: str | None) -> bool:
    return isinstance(value, str) and value in MEETING_TYPES


def normalize_meeting_type(value: str | None) -> str | None:
    """Return the value if it's a known type, else None."""
    return value if is_valid_meeting_type(value) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest backend/tests/test_meeting_type.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/meeting_types.py backend/tests/test_meeting_type.py
git commit -m "feat(backend): canonical meeting-type module (single source of truth)"
```

---

## Task 2: Serve the enum — `GET /meeting-types`

**Files:**
- Modify: `backend/main.py` (import from Task 1; add endpoint near the other session routes ~line 1286)
- Test: `backend/tests/test_meeting_type.py`

**Interfaces:**
- Consumes: `MEETING_TYPES`, `DEFAULT_MEETING_TYPE` from `backend.meeting_types`.
- Produces: `GET /meeting-types` → `{"types": [...8 strings...], "default": "Internal Team Meeting"}`. Auth-required (uses `_current_user_id` like the other endpoints).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_meeting_type.py`:

```python
import backend.main as main
from fastapi.testclient import TestClient


def _client():
    main.app.dependency_overrides[main._current_user_id] = lambda: 1
    return TestClient(main.app)


def test_get_meeting_types():
    client = _client()
    try:
        r = client.get("/meeting-types")
        assert r.status_code == 200
        body = r.json()
        assert body["default"] == "Internal Team Meeting"
        assert body["types"][0] == "Internal Team Meeting"
        assert len(body["types"]) == 8
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_get_meeting_types -q`
Expected: FAIL with 404 (route not defined) — assertion on `status_code == 200` fails.

- [ ] **Step 3: Add the import and endpoint**

In `backend/main.py`, add to the imports near `from backend.database import (...)`:

```python
from backend.meeting_types import (
    MEETING_TYPES, DEFAULT_MEETING_TYPE,
    is_valid_meeting_type, normalize_meeting_type,
)
```

Add this endpoint right after the `@app.get("/sessions")` / `list_sessions` function:

```python
@app.get("/meeting-types")
def list_meeting_types(user_id: int = Depends(_current_user_id)):
    """Canonical meeting-type list + default, so clients render from the server."""
    return {"types": list(MEETING_TYPES), "default": DEFAULT_MEETING_TYPE}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_get_meeting_types -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_meeting_type.py
git commit -m "feat(backend): GET /meeting-types serves the canonical enum"
```

---

## Task 3: Validate meeting_type on POST /sessions

**Files:**
- Modify: `backend/main.py` (`create_session`, ~line 1262)
- Test: `backend/tests/test_meeting_type.py`

**Interfaces:**
- Consumes: `normalize_meeting_type` from Task 1.
- Produces: `POST /sessions` coerces an unknown/absent `meeting_type` to `None` before calling `save_session` (engine-save path must never 500 on a stale value).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_meeting_type.py`:

```python
def test_post_sessions_coerces_unknown_meeting_type(monkeypatch):
    client = _client()
    captured = {}
    monkeypatch.setattr(main, "save_session",
                        lambda **kw: (captured.update(kw), 1)[1])
    monkeypatch.setattr(main, "_regenerate_profile_safely", lambda uid: None)
    monkeypatch.setattr(main._posthog, "capture", lambda *a, **k: None)
    try:
        payload = {"slug": "s", "name": "n", "date": "d", "duration": 1,
                   "transcript": "t", "issues": [], "segments": [],
                   "system_audio_captured": True, "meeting_type": "Bogus"}
        assert client.post("/sessions", json=payload).status_code == 200
        assert captured["meeting_type"] is None

        payload["meeting_type"] = "Customer Call"
        client.post("/sessions", json=payload)
        assert captured["meeting_type"] == "Customer Call"
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_post_sessions_coerces_unknown_meeting_type -q`
Expected: FAIL — `captured["meeting_type"] == "Bogus"` (not coerced yet).

- [ ] **Step 3: Coerce in create_session**

In `backend/main.py`, in `create_session`, change the `save_session(...)` call so `meeting_type` is normalized:

```python
        meeting_type=normalize_meeting_type(payload.meeting_type),
```

(Replace the existing `meeting_type=payload.meeting_type,` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_post_sessions_coerces_unknown_meeting_type -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_meeting_type.py
git commit -m "feat(backend): coerce unknown meeting_type to null on POST /sessions"
```

---

## Task 4: Session-type write path — DB helper + PATCH /sessions/{slug}

**Files:**
- Modify: `backend/database.py` (add `update_session_meeting_type` after `get_session_with_issues`, ~line 415)
- Modify: `backend/main.py` (import helper; add `PATCH /sessions/{slug}` after `get_session`)
- Test: `backend/tests/test_meeting_type.py`

**Interfaces:**
- Consumes: `is_valid_meeting_type` from Task 1.
- Produces:
  - `database.update_session_meeting_type(user_id: int, slug: str, meeting_type: str) -> bool` — updates the row; returns `False` if no matching session.
  - `PATCH /sessions/{slug}` body `{"meeting_type": "<valid type>"}` → 200 `{"ok": true}`; 422 on invalid type; 404 if the session doesn't exist.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_meeting_type.py`:

```python
def test_patch_session_meeting_type(monkeypatch):
    client = _client()
    calls = {}
    monkeypatch.setattr(main, "update_session_meeting_type",
                        lambda user_id, slug, meeting_type:
                        calls.update(user_id=user_id, slug=slug, mt=meeting_type) or True)
    try:
        r = client.patch("/sessions/2026-06-28_09-31",
                         json={"meeting_type": "Candidate Interview"})
        assert r.status_code == 200
        assert calls["slug"] == "2026-06-28_09-31"
        assert calls["mt"] == "Candidate Interview"

        # invalid type → 422, helper not called
        calls.clear()
        r = client.patch("/sessions/x", json={"meeting_type": "Bogus"})
        assert r.status_code == 422
        assert calls == {}
    finally:
        main.app.dependency_overrides.clear()


def test_patch_session_not_found(monkeypatch):
    client = _client()
    monkeypatch.setattr(main, "update_session_meeting_type",
                        lambda user_id, slug, meeting_type: False)
    try:
        r = client.patch("/sessions/missing",
                         json={"meeting_type": "Customer Call"})
        assert r.status_code == 404
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_patch_session_meeting_type -q`
Expected: FAIL — 404/405 (route not defined) or ImportError on `update_session_meeting_type`.

- [ ] **Step 3: Add the DB helper**

In `backend/database.py`, add after `get_session_with_issues`:

```python
def update_session_meeting_type(user_id: int, slug: str, meeting_type: str) -> bool:
    """Set the meeting type on an existing session. Returns False if not found."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET meeting_type = %s WHERE user_id = %s AND slug = %s",
                (meeting_type, user_id, slug),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0
```

- [ ] **Step 4: Add the endpoint**

In `backend/main.py`, add `update_session_meeting_type` to the `from backend.database import (...)` list. Then add after `get_session` (the `GET /sessions/{slug}` handler):

```python
class MeetingTypePatch(BaseModel):
    meeting_type: str


@app.patch("/sessions/{slug}")
def patch_session(slug: str, patch: MeetingTypePatch,
                  user_id: int = Depends(_current_user_id)):
    if not is_valid_meeting_type(patch.meeting_type):
        raise HTTPException(422, "Unknown meeting type.")
    if not update_session_meeting_type(user_id, slug, patch.meeting_type):
        raise HTTPException(404, "Session not found.")
    return {"ok": True}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_patch_session_meeting_type backend/tests/test_meeting_type.py::test_patch_session_not_found -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/database.py backend/tests/test_meeting_type.py
git commit -m "feat(backend): PATCH /sessions/{slug} to update meeting type"
```

---

## Task 5: Persist Coming Up (pre-record) type server-side

**Files:**
- Modify: `backend/database.py` (create table in `init_db`; add `get_event_meeting_types` + `set_event_meeting_type`)
- Modify: `backend/main.py` (join into `GET /calendar/upcoming`; add `PUT /calendar/events/{event_id}/meeting-type`)
- Test: `backend/tests/test_meeting_type.py`

**Interfaces:**
- Consumes: `is_valid_meeting_type` from Task 1.
- Produces:
  - `database.set_event_meeting_type(user_id: int, event_id: str, meeting_type: str) -> None` — upsert.
  - `database.get_event_meeting_types(user_id: int, event_ids: list[str]) -> dict[str, str]` — map of event_id → type for the given ids.
  - `PUT /calendar/events/{event_id}/meeting-type` body `{"meeting_type"}` → 200 `{"ok": true}`; 422 on invalid.
  - `GET /calendar/upcoming` events each gain a `"meeting_type"` field (the stored value, or `null`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_meeting_type.py`:

```python
def test_put_event_meeting_type(monkeypatch):
    client = _client()
    calls = {}
    monkeypatch.setattr(main, "set_event_meeting_type",
                        lambda user_id, event_id, meeting_type:
                        calls.update(uid=user_id, eid=event_id, mt=meeting_type))
    try:
        r = client.put("/calendar/events/evt123/meeting-type",
                       json={"meeting_type": "Customer Call"})
        assert r.status_code == 200
        assert calls["eid"] == "evt123"
        assert calls["mt"] == "Customer Call"

        calls.clear()
        r = client.put("/calendar/events/evt123/meeting-type",
                       json={"meeting_type": "Bogus"})
        assert r.status_code == 422
        assert calls == {}
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_put_event_meeting_type -q`
Expected: FAIL — 404/405 (route not defined).

- [ ] **Step 3: Add the table + DB helpers**

In `backend/database.py`, inside `init_db` after the `issues` table block (before the `password_reset_tokens` block), add:

```python
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_meeting_types (
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    event_id     TEXT    NOT NULL,
                    meeting_type TEXT    NOT NULL,
                    updated_at   FLOAT   NOT NULL,
                    PRIMARY KEY (user_id, event_id)
                )
            """)
```

Add these helpers (place them after `update_session_meeting_type`):

```python
def set_event_meeting_type(user_id: int, event_id: str, meeting_type: str) -> None:
    """Upsert the pre-record meeting type chosen for a calendar event."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO event_meeting_types (user_id, event_id, meeting_type, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, event_id) DO UPDATE
                    SET meeting_type = EXCLUDED.meeting_type,
                        updated_at   = EXCLUDED.updated_at
            """, (user_id, event_id, meeting_type, time.time()))
        conn.commit()


def get_event_meeting_types(user_id: int, event_ids: list[str]) -> dict[str, str]:
    """Map of event_id -> meeting_type for the given ids (only those set)."""
    if not event_ids:
        return {}
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, meeting_type FROM event_meeting_types "
                "WHERE user_id = %s AND event_id = ANY(%s)",
                (user_id, list(event_ids)),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
```

- [ ] **Step 4: Add the endpoint + calendar join**

In `backend/main.py`, add `set_event_meeting_type, get_event_meeting_types` to the `from backend.database import (...)` list.

Add the PUT endpoint after `patch_session`:

```python
@app.put("/calendar/events/{event_id}/meeting-type")
def put_event_meeting_type(event_id: str, patch: MeetingTypePatch,
                           user_id: int = Depends(_current_user_id)):
    if not is_valid_meeting_type(patch.meeting_type):
        raise HTTPException(422, "Unknown meeting type.")
    set_event_meeting_type(user_id, event_id, patch.meeting_type)
    return {"ok": True}
```

In `calendar_upcoming`, after the `events = [...]` list is built and before `return events`, add the join. Note `calendar_upcoming` currently depends on `user` (not `user_id`) — use `user["id"]`:

```python
    type_map = get_event_meeting_types(user["id"], [e["id"] for e in events])
    for e in events:
        e["meeting_type"] = type_map.get(e["id"])
    return events
```

(Replace the bare `return events`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_put_event_meeting_type -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/database.py backend/tests/test_meeting_type.py
git commit -m "feat(backend): persist Coming Up meeting type per calendar event"
```

---

## Task 6: Thread meeting_type into coaching

**Files:**
- Modify: `backend/main.py` (`CoachRequest`, `COACH_SYSTEM`, `coach` handler)
- Modify: `fluent-engine/fluent/coach.py` (`coach()` sends `meeting_type`)
- Modify: `fluent-engine/fluent/pipeline.py` (pass `meeting_type` into `coach()`)
- Test: `backend/tests/test_meeting_type.py`, `fluent-engine/tests/test_coach.py`

**Interfaces:**
- Consumes: `normalize_meeting_type` from Task 1.
- Produces:
  - `CoachRequest.meeting_type: str | None`.
  - `COACH_SYSTEM` includes a `{meeting_context}` line describing the meeting.
  - Engine `coach(transcript, config, meeting_type=None)` posts `meeting_type` to `/coach`.

- [ ] **Step 1: Write the failing backend test**

Append to `backend/tests/test_meeting_type.py`:

```python
def test_coach_uses_meeting_type(monkeypatch):
    client = _client()
    seen = {}

    class _Msg:
        def create(self, **kw):
            seen["system"] = kw["system"]
            block = type("B", (), {"text": "[]"})()
            return type("R", (), {"content": [block]})()

    class _Anthropic:
        def __init__(self, **kw): self.messages = _Msg()

    monkeypatch.setattr(main, "Anthropic", lambda **kw: _Anthropic())
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(main._posthog, "capture", lambda *a, **k: None)
    try:
        r = client.post("/coach", json={"transcript": "hi",
                                        "meeting_type": "Candidate Interview"})
        assert r.status_code == 200
        assert "Candidate Interview" in seen["system"]
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_coach_uses_meeting_type -q`
Expected: FAIL — `"Candidate Interview"` not in the system prompt.

- [ ] **Step 3: Update CoachRequest, COACH_SYSTEM, and the coach handler**

In `backend/main.py`:

Add a line to `COACH_SYSTEM` right after `Their job context: {job_context}.`:

```
This meeting is: {meeting_context}. Tailor your suggestions to that setting.
```

Update `CoachRequest`:

```python
class CoachRequest(BaseModel):
    transcript: str
    native_language: str = ""  # kept for backwards compat, ignored
    job_context: str = "Professional"
    meeting_type: str | None = None
```

Update the `system = COACH_SYSTEM.format(...)` call in `coach`:

```python
    mt = normalize_meeting_type(req.meeting_type)
    system = COACH_SYSTEM.format(
        job_context=req.job_context,
        meeting_context=(mt or "a professional meeting"),
    )
```

- [ ] **Step 4: Run backend test to verify it passes**

Run: `python3 -m pytest backend/tests/test_meeting_type.py::test_coach_uses_meeting_type -q`
Expected: PASS

- [ ] **Step 5: Write the failing engine test**

Append to `fluent-engine/tests/test_coach.py`:

```python
def test_coach_sends_meeting_type(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _FakeResp([])

    monkeypatch.setattr(C, "get_token", lambda: "tok")
    monkeypatch.setattr(C.httpx, "post", fake_post)

    class _Cfg:
        native_language = "Spanish"
        job_context = "Professional"

    C.coach("hello", _Cfg(), meeting_type="Customer Call")
    assert captured["json"]["meeting_type"] == "Customer Call"
```

- [ ] **Step 6: Run engine test to verify it fails**

Run: `cd fluent-engine && python3 -m pytest tests/test_coach.py::test_coach_sends_meeting_type -q`
Expected: FAIL — `coach()` takes no `meeting_type` kwarg (TypeError) or the key is absent.

- [ ] **Step 7: Update engine coach() and pipeline call**

In `fluent-engine/fluent/coach.py`, change the `coach` signature and body:

```python
def coach(transcript: str, config: Config, meeting_type: str | None = None) -> list:
```

and add `"meeting_type": meeting_type,` to the `json={...}` posted to `/coach` (alongside `job_context`).

In `fluent-engine/fluent/pipeline.py`, the call at line ~81 becomes:

```python
            issues = coach(user_transcript, config, meeting_type=meeting_type)
```

- [ ] **Step 8: Run engine test to verify it passes**

Run: `cd fluent-engine && python3 -m pytest tests/test_coach.py -q`
Expected: PASS (all coach tests)

- [ ] **Step 9: Commit**

```bash
git add backend/main.py fluent-engine/fluent/coach.py fluent-engine/fluent/pipeline.py \
        backend/tests/test_meeting_type.py fluent-engine/tests/test_coach.py
git commit -m "feat: meeting type shapes coaching (threaded into /coach prompt)"
```

---

## Task 7: Frontend — read enum + session type from the API; drop session localStorage

**Files:**
- Modify: `frontend/report.js` AND `windows/src/report.js` (identical edits)

**Interfaces:**
- Consumes: `GET /meeting-types` (Task 2), `PATCH /sessions/{slug}` (Task 4), `apiFetch(path, opts)` (existing).
- Produces: no localStorage reads/writes for session meeting type; `meetingTypeForSlug(slug, backendType)` returns `backendType || DEFAULT_MEETING_TYPE`; session-page edit calls `PATCH`.

- [ ] **Step 1: Load the enum from the API at startup**

In BOTH files, keep `MEETING_TYPES` and `DEFAULT_MEETING_TYPE` as `let` (mutable fallback), and hydrate from the server. Change the declarations:

```javascript
  let MEETING_TYPES = [
    'Internal Team Meeting',
    '1:1 with Manager',
    'Candidate Interview',
    'Customer Call',
    'Technical Discussion',
    'Stakeholder Update',
    'Behavioral Interview',
    'Other',
  ];
  let DEFAULT_MEETING_TYPE = 'Internal Team Meeting';
```

Add a loader (place near `loadProfile`), and call it from `loadSessions` where `loadProfile` is called:

```javascript
  // Hydrate the meeting-type list from the backend (single source of truth).
  // Falls back to the built-in list if the call fails.
  function loadMeetingTypes(token) {
    token = token || _token();
    if (!token) return;
    apiFetch('/meeting-types')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && Array.isArray(data.types) && data.types.length) {
          MEETING_TYPES = data.types;
          if (data.default) DEFAULT_MEETING_TYPE = data.default;
        }
      })
      .catch(() => {});
  }
```

In `window.loadSessions`, in the `else` branch that calls `loadProfile(_token())`, add `loadMeetingTypes(_token());` right before it.

- [ ] **Step 2: Simplify meetingTypeForSlug — backend is the source of truth**

In BOTH files, replace the `meetingTypeKey`/`meetingTypeForSlug`/`saveMeetingType` block with:

```javascript
  // Meeting type comes from the backend session record. No localStorage.
  function meetingTypeForSlug(slug, backendType) {
    return (backendType && MEETING_TYPES.includes(backendType))
      ? backendType : DEFAULT_MEETING_TYPE;
  }

  function getMeetingType(data) {
    return meetingTypeForSlug(data.slug || '', data.meeting_type);
  }

  // Persist a session-page meeting-type change to the backend.
  function saveMeetingType(slug, type) {
    if (!slug) return;
    apiFetch('/sessions/' + encodeURIComponent(slug), {
      method: 'PATCH',
      body: { meeting_type: type },
    }).catch(() => {});
  }
```

(Delete the old `meetingTypeKey` function entirely.)

- [ ] **Step 3: Verify JS syntax**

Run: `node --check frontend/report.js && node --check windows/src/report.js`
Expected: both print nothing (exit 0)

- [ ] **Step 4: Manual behaviour check (reason through it)**

Confirm: `wireMeetingTypeSelector` still calls `saveMeetingType(_reportState.slug, type)` — now it PATCHes. History rows call `meetingTypeForSlug(slug, session.meeting_type)` — now backend-only. No remaining `localStorage` reference for `fluent_meeting_type_`.

Run: `grep -n "fluent_meeting_type_\|meetingTypeKey" frontend/report.js windows/src/report.js`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/report.js windows/src/report.js
git commit -m "refactor(frontend): session meeting type reads/writes via API, no localStorage"
```

---

## Task 8: Frontend — Coming Up type via API; drop upnext localStorage

**Files:**
- Modify: `frontend/report.js` AND `windows/src/report.js` (identical edits)

**Interfaces:**
- Consumes: `GET /calendar/upcoming` now returns `meeting_type` per event (Task 5); `PUT /calendar/events/{event_id}/meeting-type` (Task 5).
- Produces: no localStorage for upnext type; the chip reflects `ev.meeting_type`; changing it PUTs to the API; the record button passes the event's current type into `openRecordingPage`.

- [ ] **Step 1: Replace upnext localStorage helpers**

In BOTH files, replace the `upnextTypeKey`/`upnextTypeForEvent`/`saveUpnextType` block with:

```javascript
  // Coming Up meeting type is stored server-side per calendar event id.
  function upnextTypeForEvent(ev) {
    const t = ev && ev.meeting_type;
    return (t && MEETING_TYPES.includes(t)) ? t : DEFAULT_MEETING_TYPE;
  }

  function saveUpnextType(eventId, type) {
    if (!eventId) return;
    apiFetch('/calendar/events/' + encodeURIComponent(eventId) + '/meeting-type', {
      method: 'PUT',
      body: { meeting_type: type },
    }).catch(() => {});
  }
```

(Delete `upnextTypeKey` entirely. Note `upnextTypeForEvent` now takes the whole event object, not an id.)

- [ ] **Step 2: Update renderUpNext to use the event object**

In BOTH files, in `renderUpNext`, the per-event map callback currently does `const type = upnextTypeForEvent(eventId);`. Change it to pass the event:

```javascript
      const eventId  = ev.id || '';
      const type     = upnextTypeForEvent(ev);
```

And the record-button handler currently calls `openRecordingPage(title, upnextTypeForEvent(eventId))`. Change to:

```javascript
        openRecordingPage(title, upnextTypeForEvent(events[i]));
```

(The `change` handler on `.upnext-type-select` already calls `saveUpnextType(select.dataset.eventId, select.value)` — unchanged; it now PUTs.)

- [ ] **Step 3: Verify JS syntax**

Run: `node --check frontend/report.js && node --check windows/src/report.js`
Expected: exit 0, no output.

- [ ] **Step 4: Confirm no upnext localStorage remains**

Run: `grep -n "fluent_upnext_type_\|upnextTypeKey" frontend/report.js windows/src/report.js`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/report.js windows/src/report.js
git commit -m "refactor(frontend): Coming Up meeting type reads/writes via API, no localStorage"
```

---

## Task 9: Full-suite verification, cache-bump, build, deploy

**Files:**
- Modify: `frontend/report.html` (cache-buster bump) and mirror any needed bump in `windows/src/index.html` (Windows has no numbered cache-buster; skip if absent).

- [ ] **Step 1: Run all backend + engine tests**

Run:
```bash
python3 -m pytest backend/tests/ -q
cd fluent-engine && python3 -m pytest tests/ -q && cd ..
```
Expected: all pass (backend includes test_profile.py + test_meeting_type.py; engine includes test_coach.py).

- [ ] **Step 2: Mutation-check one wire (optional but recommended)**

Temporarily break `backend/main.py`'s coach `meeting_context` (set it to a constant), run `test_coach_uses_meeting_type`, confirm FAIL, then revert.

- [ ] **Step 3: Verify JS syntax both files**

Run: `node --check frontend/report.js && node --check windows/src/report.js`
Expected: exit 0.

- [ ] **Step 4: Bump the cache-buster**

In `frontend/report.html`, increment `report.js?v=NN` to the next number.

- [ ] **Step 5: Rebuild + reinstall the Mac app (bundles frontend + engine)**

Run:
```bash
xcodebuild -project fluent/Fluent.xcodeproj -scheme Fluent -configuration Debug build
```
Then reinstall per the project ritual: `pkill -x Fluent; pkill -f "fluent-engine/main.py"; rm -rf /Applications/Fluent.app; ditto <DerivedData>/Fluent.app /Applications/Fluent.app; open /Applications/Fluent.app`.

Verify the installed bundle: `grep -o 'report.js?v=[0-9]*' /Applications/Fluent.app/Contents/Resources/report.html` and `grep -c meeting_type /Applications/Fluent.app/Contents/Resources/fluent-engine/fluent/coach.py`.

- [ ] **Step 6: Commit the bump and deploy**

```bash
git add frontend/report.html
git commit -m "chore: bump cache-buster for meeting-type architecture"
git fetch . <current-branch>:main
git push origin main
```
Then confirm prod health: `curl -s -o /dev/null -w "%{http_code}\n" https://www.tryfluent.co/api/meeting-types` (expect 401 = route exists, auth required).

---

## Self-Review

**Spec coverage (the 5 debts):**
1. Two sources of truth → Task 7 removes localStorage read; `meetingTypeForSlug` is backend-only. ✅
2. Write asymmetry → Task 4 (PATCH session) + Task 5 (PUT event) give both edit paths a backend write. ✅
3. Two localStorage namespaces → Tasks 7 & 8 delete both (`fluent_meeting_type_*`, `fluent_upnext_type_*`). ✅
4. Duplicated/unvalidated enum → Task 1 (canonical module) + Task 2 (served) + Task 3/4/5 (validated on every write) + Task 7 Step 1 (client hydrates from server). ✅
5. Type doesn't influence coaching → Task 6 threads it into `/coach` + `COACH_SYSTEM`. ✅

**Placeholder scan:** No "TBD"/"handle appropriately"; every code step shows the code. ✅

**Type consistency:** `normalize_meeting_type`/`is_valid_meeting_type` used consistently; `upnextTypeForEvent` signature change (id → event object) is explicitly called out in Task 8 and its two call sites updated. `update_session_meeting_type` / `set_event_meeting_type` / `get_event_meeting_types` names match between database.py and main.py import + call sites. `MeetingTypePatch` defined once (Task 4) and reused (Task 5). ✅

**Note on migrations:** `event_meeting_types` uses `CREATE TABLE IF NOT EXISTS` in `init_db`, which runs on the FastAPI startup event in prod — consistent with existing schema management. The `sessions.meeting_type` column already exists (shipped earlier).
