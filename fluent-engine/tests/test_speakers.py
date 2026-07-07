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


def test_consecutive_same_speaker_utterances_merge_into_one_turn():
    # A single person speaking produces many short utterances (Deepgram splits
    # on pauses). They must collapse into one block, not one block per word.
    mixed = [
        U(0, "Your", 0.0, 0.4),
        U(0, "hi there.", 0.5, 1.2),
        U(0, "Fluent is your AI coach.", 1.3, 3.0),
    ]
    mic = [{"transcript": "your hi there fluent is your ai coach",
            "start": 0.0, "end": 3.0}]
    segs = attribute(mixed, mic)
    assert len(segs) == 1
    assert segs[0]["speaker"] == "You"
    assert segs[0]["text"] == "Your hi there. Fluent is your AI coach."
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 3.0


def test_merge_only_within_a_speaker_run():
    # You, You, Speaker1, You -> three turns: merged You, Speaker1, You.
    mixed = [
        U(0, "let me", 0.0, 0.6),
        U(0, "start us off", 0.7, 1.5),
        U(1, "sure go ahead", 1.6, 2.4),
        U(0, "great thanks", 2.5, 3.2),
    ]
    mic = [
        {"transcript": "let me start us off", "start": 0.0, "end": 1.5},
        {"transcript": "great thanks", "start": 2.5, "end": 3.2},
    ]
    segs = attribute(mixed, mic)
    assert [s["speaker"] for s in segs] == ["You", "Speaker 1", "You"]
    assert segs[0]["text"] == "let me start us off"


def test_no_match_above_threshold_falls_back_to_speakers():
    # Mic has speech, but its text does not match any mixed utterance,
    # so no Deepgram index should be labeled "You".
    mixed = [U(0, "completely different words here", 0.0, 2.0),
             U(1, "yet more unrelated content", 2.0, 4.0)]
    mic = [{"transcript": "zzz qqq xyz nothing alike", "start": 0.0, "end": 2.0}]
    segs = attribute(mixed, mic)
    assert "You" not in [s["speaker"] for s in segs]
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2"]
