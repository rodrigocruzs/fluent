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


def test_no_match_above_threshold_falls_back_to_speakers():
    # Mic has speech, but its text does not match any mixed utterance,
    # so no Deepgram index should be labeled "You".
    mixed = [U(0, "completely different words here", 0.0, 2.0),
             U(1, "yet more unrelated content", 2.0, 4.0)]
    mic = [{"transcript": "zzz qqq xyz nothing alike", "start": 0.0, "end": 2.0}]
    segs = attribute(mixed, mic)
    assert "You" not in [s["speaker"] for s in segs]
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2"]
