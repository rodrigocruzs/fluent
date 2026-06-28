"""
Tests for the Communication Profile endpoints against the local FastAPI app.

These run the real `backend.main:app` in-process via Starlette's TestClient, so
the routing, auth dependency, type validation, and the POST /sessions →
background regeneration → GET /profile round-trip are all exercised for real.

What's faked, and why:
- Auth: we override the `_current_user_id` dependency so we don't need a real
  JWT or a user row in Neon.
- DB: the three profile DB helpers (recent sessions, save, get) are patched to
  use an in-memory store, so the test never touches Postgres.
- Anthropic: the client is faked so generation is deterministic and free.
- PostHog: stubbed so `create_session` doesn't emit telemetry during tests.

Run: pytest backend/tests/test_profile.py
"""

import json

import pytest
from fastapi.testclient import TestClient

import backend.main as main


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeMessages:
    """Stands in for client.messages, returning a canned model response."""
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        # Mimic anthropic's response shape: response.content[0].text
        block = type("Block", (), {"text": self._text})()
        return type("Resp", (), {"content": [block]})()


class _FakeAnthropic:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def _make_fake_anthropic(text):
    # main.py calls `Anthropic(api_key=...)`, so the patched symbol must be a
    # callable that ignores its kwargs and returns our fake client.
    return lambda *args, **kwargs: _FakeAnthropic(text)


# ── Fixtures ──────────────────────────────────────────────────────────────────

USER_ID = 42


@pytest.fixture
def store():
    """In-memory stand-in for the user's stored profile + recent sessions."""
    return {"profile_json": None, "recent_sessions": []}


@pytest.fixture
def client(monkeypatch, store):
    # Auth: bypass JWT/DB and act as a fixed user.
    main.app.dependency_overrides[main._current_user_id] = lambda: USER_ID

    # Profile must not be short-circuited by a missing key.
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "sk-test")

    # DB helpers → in-memory store.
    monkeypatch.setattr(main, "get_recent_sessions_for_profile",
                        lambda user_id, limit=8: list(store["recent_sessions"]))
    monkeypatch.setattr(main, "save_communication_profile",
                        lambda user_id, profile_json: store.__setitem__("profile_json", profile_json))
    monkeypatch.setattr(main, "get_communication_profile",
                        lambda user_id: store["profile_json"])
    # save_session is called by POST /sessions; we only care about the profile
    # side effect, so stub the write and return a fake id.
    monkeypatch.setattr(main, "save_session", lambda **kwargs: 1)

    # Telemetry: no-op so create_session doesn't try to emit events.
    monkeypatch.setattr(main._posthog, "capture", lambda *a, **k: None)

    # TestClient WITHOUT the context manager so the startup event (init_db,
    # which hits Postgres) doesn't fire.
    c = TestClient(main.app)
    yield c

    main.app.dependency_overrides.clear()


def _post_session(client):
    return client.post("/sessions", json={
        "slug": "2026-06-28-standup",
        "name": "Daily standup",
        "date": "2026-06-28",
        "duration": 540,
        "transcript": "I think we should maybe ship the feature this week.",
        "issues": [],
        "segments": [],
        "system_audio_captured": True,
    })


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_profile_is_null_before_any_meeting(client):
    """Empty state: with no meetings at all, /profile returns null."""
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert resp.json() is None


def test_profile_generated_lazily_for_preexisting_meetings(client, monkeypatch, store):
    """
    A user who recorded meetings before the feature existed has no stored
    profile. GET /profile should generate one on-demand from those meetings,
    persist it, and return it — not show the empty state.
    """
    store["recent_sessions"] = [{
        "name": "Old planning call", "date": "2026-06-20",
        "transcript": "We discussed the roadmap and I walked through the trade-offs.",
        "issues": [],
    }]
    model_output = json.dumps({
        "type": "Strategic Communicator",
        "description": "You connect details to priorities, risks and business outcomes.",
        "strengths": ["Framed trade-offs clearly", "Tied detail to the roadmap",
                      "Kept the discussion focused"],
        "opportunities": ["State the recommendation up front",
                          "Quantify the risks", "Invite dissent explicitly"],
    })
    monkeypatch.setattr(main, "Anthropic", _make_fake_anthropic(model_output))

    assert store["profile_json"] is None  # nothing stored going in
    profile = client.get("/profile").json()
    assert profile["type"] == "Strategic Communicator"
    assert store["profile_json"] is not None  # generated + persisted
    # Persisted, so a second read returns the cached copy (no regeneration).
    assert client.get("/profile").json()["type"] == "Strategic Communicator"


def test_session_save_generates_and_persists_profile(client, monkeypatch, store):
    """POST /sessions → background regeneration → GET /profile returns it."""
    store["recent_sessions"] = [{
        "name": "Daily standup", "date": "2026-06-28",
        "transcript": "I think we should maybe ship the feature this week.",
        "issues": [{"category": "Phrasing", "original": "maybe ship",
                    "improved": "ship", "explanation": "hedging"}],
    }]
    model_output = json.dumps({
        "type": "Clear Explainer",
        "description": "You’re good at making complex ideas easier to understand.",
        "strengths": ["Explained the plan clearly", "Kept a professional tone",
                      "Asked useful follow-up questions"],
        "opportunities": ["Lead with the answer", "Reduce hedging words",
                          "Use more specific vocabulary"],
    })
    monkeypatch.setattr(main, "Anthropic", _make_fake_anthropic(model_output))

    # Background tasks run synchronously after the response with TestClient,
    # so the profile is already persisted by the time this returns.
    assert _post_session(client).status_code == 200

    resp = client.get("/profile")
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["type"] == "Clear Explainer"
    assert len(profile["strengths"]) == 3
    assert len(profile["opportunities"]) == 3
    assert profile["strengths"][0] == "Explained the plan clearly"


def test_invalid_type_is_coerced(client, monkeypatch, store):
    """A profile type the model invents is coerced to a valid one."""
    store["recent_sessions"] = [{
        "name": "Sync", "date": "2026-06-28",
        "transcript": "Some words were spoken in this meeting.", "issues": [],
    }]
    model_output = json.dumps({
        "type": "Galaxy Brain Communicator",   # not in PROFILE_TYPES
        "description": "n/a",
        "strengths": ["a", "b", "c"],
        "opportunities": ["x", "y", "z"],
    })
    monkeypatch.setattr(main, "Anthropic", _make_fake_anthropic(model_output))

    _post_session(client)
    profile = client.get("/profile").json()
    assert profile["type"] == "Developing Communicator"
    assert profile["type"] in main.PROFILE_TYPES


def test_lists_are_trimmed_to_three(client, monkeypatch, store):
    """More than three strengths/opportunities get trimmed."""
    store["recent_sessions"] = [{
        "name": "Sync", "date": "2026-06-28",
        "transcript": "Some words were spoken in this meeting.", "issues": [],
    }]
    model_output = json.dumps({
        "type": "Confident Presenter",
        "description": "You speak with structure, presence and conviction.",
        "strengths": ["s1", "s2", "s3", "s4", "s5"],
        "opportunities": ["o1", "o2", "o3", "o4"],
    })
    monkeypatch.setattr(main, "Anthropic", _make_fake_anthropic(model_output))

    _post_session(client)
    profile = client.get("/profile").json()
    assert profile["strengths"] == ["s1", "s2", "s3"]
    assert profile["opportunities"] == ["o1", "o2", "o3"]


def test_no_profile_generated_without_transcripts(client, monkeypatch, store):
    """If recent sessions have no spoken text, no profile is generated/saved."""
    store["recent_sessions"] = [{
        "name": "Empty", "date": "2026-06-28", "transcript": "   ", "issues": [],
    }]
    # If generation were (wrongly) attempted, this would blow up — proving it
    # short-circuits before ever touching the model.
    monkeypatch.setattr(main, "Anthropic", _make_fake_anthropic("should not be called"))

    _post_session(client)
    assert store["profile_json"] is None
    assert client.get("/profile").json() is None


def test_malformed_model_output_does_not_break_save(client, monkeypatch, store):
    """Non-JSON model output is swallowed; the session save still succeeds."""
    store["recent_sessions"] = [{
        "name": "Sync", "date": "2026-06-28",
        "transcript": "Some words were spoken.", "issues": [],
    }]
    monkeypatch.setattr(main, "Anthropic",
                        _make_fake_anthropic("Sorry, I can't do that."))

    assert _post_session(client).status_code == 200
    # Generation failed → nothing persisted → empty state holds.
    assert store["profile_json"] is None
    assert client.get("/profile").json() is None
