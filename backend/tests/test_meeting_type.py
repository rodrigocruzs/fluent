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
