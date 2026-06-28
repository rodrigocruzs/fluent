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
