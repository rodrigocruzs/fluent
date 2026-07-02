import fluent.coach as C


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_save_session_remote_includes_meeting_type(monkeypatch):
    """The meeting type chosen on a Coming Up row is sent to the backend."""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"id": 1})

    monkeypatch.setattr(C, "get_token", lambda: "tok")
    monkeypatch.setattr(C.httpx, "post", fake_post)

    C.save_session_remote(
        slug="2026-06-28_09-31",
        name="1:1 with Sarah",
        date="June 28, 2026",
        duration=540.0,
        transcript="hello",
        issues=[],
        segments=[],
        system_audio_captured=True,
        meeting_type="1:1 with Manager",
    )

    assert captured["url"].endswith("/sessions")
    assert captured["json"]["meeting_type"] == "1:1 with Manager"


def test_save_session_remote_meeting_type_defaults_to_none(monkeypatch):
    """When no meeting type is passed, the field is sent as null."""
    captured = {}
    monkeypatch.setattr(C, "get_token", lambda: "tok")
    monkeypatch.setattr(C.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        (captured.update(json=json), _FakeResp({"id": 1}))[1])

    C.save_session_remote(
        slug="s", name="n", date="d", duration=1.0,
        transcript="t", issues=[], segments=[], system_audio_captured=True,
    )

    assert captured["json"]["meeting_type"] is None


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
