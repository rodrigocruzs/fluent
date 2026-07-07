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
    # Break ties toward the lowest speaker index for determinism.
    best_score = max(score.values())
    return min(idx for idx, sc in score.items() if sc == best_score)


def attribute(mixed_utterances: list[dict], mic_utterances: list[dict]) -> list[dict]:
    if not mixed_utterances:
        return []

    you_idx = _you_index(mixed_utterances, mic_utterances)

    # Number other speakers in first-appearance order.
    label_for: dict[int, str] = {}
    next_other = 1
    if you_idx is not None:
        label_for[you_idx] = "You"

    # Deepgram emits many short utterances (often single words when the speaker
    # pauses). Rendering one block per utterance shatters a single person's
    # continuous speech into a wall of tiny "You" blocks. Merge consecutive
    # utterances from the same speaker into one turn — a new block only starts
    # when the speaker actually changes.
    segments: list[dict] = []
    for mu in mixed_utterances:
        idx = mu["speaker"]
        if idx not in label_for:
            label_for[idx] = f"Speaker {next_other}"
            next_other += 1
        speaker = label_for[idx]
        text = mu.get("transcript", "")
        if segments and segments[-1]["speaker"] == speaker:
            prev = segments[-1]
            prev["text"] = (prev["text"] + " " + text).strip() if text else prev["text"]
            prev["end"] = mu["end"]
        else:
            segments.append({
                "speaker": speaker,
                "text": text,
                "start": mu["start"],
                "end": mu["end"],
            })
    return segments
