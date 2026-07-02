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
