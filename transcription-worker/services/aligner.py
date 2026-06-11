
OVERLAP = -1  # turn_index sentinel for simultaneous speech from multiple speakers


def align_words_to_turns(
    words: list[dict],   # [{word, start_time, end_time}]
    turns: list[dict],   # [{start, end}, ...] — speaker_label field is ignored
) -> list[dict]:
    """
    Assigns each word to a turn by index using its midpoint timestamp.
    When multiple turns are active simultaneously the word is labeled OVERLAP (-1).
    Words in gaps (silence) are assigned to the nearest turn by endpoint distance.
    Consecutive words assigned to the same turn index are merged into segments.
    Returns [{turn_index, start_time, end_time, text}].
    turn_index == OVERLAP (-1) indicates simultaneous speech.

    Note: speaker_label is intentionally not used — two turns with the same pyannote
    label are distinct turns and must never be merged.
    """
    if not words:
        return []
    if not turns:
        return []

    sorted_turns = sorted(enumerate(turns), key=lambda x: x[1]["start"])
    sorted_indices = [i for i, _ in sorted_turns]
    sorted_ts     = [t for _, t in sorted_turns]

    def assign_index(midpoint: float) -> int:
        active = [
            sorted_indices[j]
            for j, t in enumerate(sorted_ts)
            if t["start"] <= midpoint < t["end"]
        ]
        if len(active) > 1:
            return OVERLAP
        if len(active) == 1:
            return active[0]
        # Gap — nearest turn by endpoint distance
        j = min(
            range(len(sorted_ts)),
            key=lambda k: min(
                abs(midpoint - sorted_ts[k]["start"]),
                abs(midpoint - sorted_ts[k]["end"]),
            ),
        )
        return sorted_indices[j]

    word_indices = [
        assign_index((w["start_time"] + w["end_time"]) / 2)
        for w in words
    ]

    # Group consecutive same-index words into segments
    segments: list[dict] = []
    cur_idx = word_indices[0]
    cur_start = words[0]["start_time"]
    cur_end   = words[0]["end_time"]
    cur_words = [words[0]["word"]]

    for i in range(1, len(words)):
        idx = word_indices[i]
        if idx == cur_idx:
            cur_end = words[i]["end_time"]
            cur_words.append(words[i]["word"])
        else:
            segments.append({
                "turn_index": cur_idx,
                "start_time": cur_start,
                "end_time":   cur_end,
                "text":       " ".join(cur_words),
            })
            cur_idx   = idx
            cur_start = words[i]["start_time"]
            cur_end   = words[i]["end_time"]
            cur_words = [words[i]["word"]]

    segments.append({
        "turn_index": cur_idx,
        "start_time": cur_start,
        "end_time":   cur_end,
        "text":       " ".join(cur_words),
    })

    return segments


def find_overlaps(
    turns: list[dict],            # [{speaker_label, start, end}] regular diarization
    exclusive_turns: list[dict],  # [{speaker_label, start, end}] exclusive diarization
) -> list[dict]:
    """
    Segments present in `turns` but absent from `exclusive_turns` represent
    overlapping speech. Returns [{start, end, speakers: [...]}].

    Uses a sweep-line over regular turns to find intervals where multiple
    speakers are simultaneously active.
    """
    # Build (time, delta, speaker) events.
    # delta=0 for end, delta=1 for start — sorts ends before starts at same timestamp
    # so adjacent (non-overlapping) turns don't produce phantom overlaps.
    events: list[tuple[float, int, str]] = []
    for t in turns:
        events.append((t["start"], 1, t["speaker_label"]))
        events.append((t["end"],   0, t["speaker_label"]))
    events.sort(key=lambda e: (e[0], e[1]))

    active: set[str] = set()
    overlaps: list[dict] = []
    seg_start: float | None = None

    for time, delta, speaker in events:
        # Close the current overlap segment before mutating active set
        if seg_start is not None and time > seg_start and len(active) > 1:
            overlaps.append({"start": seg_start, "end": time, "speakers": sorted(active)})
            seg_start = None

        if delta == 1:
            active.add(speaker)
        else:
            active.discard(speaker)

        # Start tracking a new overlap if we now have multiple active speakers
        if len(active) > 1:
            seg_start = time
        else:
            seg_start = None

    return overlaps
