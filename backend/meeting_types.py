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
