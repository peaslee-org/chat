# Feature Spec: Sliding-Window Re-Diarization (Option B)

> **Status (2026-08-29).** Not implemented. Both options were overtaken by moving diarization off AWS Transcribe entirely (`pyannote-diarization-plan.md`, ADR 002); Transcribe now only provides word timestamps, so sliding-window re-diarization of its output is moot. Kept for the analysis.

## Background

Option A (MaxSpeakerLabels fix) ensures AWS Transcribe is allowed to find the right number of speakers. Option B addresses the other failure mode: Transcribe sometimes assigns a long multi-speaker stretch to a single label, even when the speaker count is correct. This results in segments like:

```
[0.21 - 15.85] spk_0: Don't worry about it ... Sounds good to me. Good luck ... Thanks. You're welcome.
```

When the correct output should be four short turns across three speakers.

Option B adds a post-processing pass in the worker: after Transcribe's diarization is parsed, any long segment is examined with the ECAPA-TDNN model already in memory. If a speaker change is detected within the segment, it is split at the change point and two new speaker labels are created. The normal embedding + profile-matching pipeline then runs unchanged on the expanded label set.

**Relationship to Option C**: Option B is a stepping stone. It reuses the ECAPA-TDNN model already present and requires no new dependencies. Option C (pyannote) would replace Option B entirely — when Option C ships, Option B's re-diarization pass is simply removed. The `parse_words` method added in Option B will be reused by Option C.

---

## Algorithm

### Overview

```
AWS Transcribe output (segments + word timestamps)
         │
         ▼
   re_diarize_segments()
         │
         ├─ short segments (<MIN_DURATION) ──────────────────► pass through unchanged
         │
         └─ long segments (≥MIN_DURATION)
                  │
                  ▼
         sliding-window embeddings over segment audio
                  │
                  ▼
         cosine distance between adjacent windows
                  │
                  ▼
         smooth distances (moving average, width=3)
                  │
                  ├─ peak distance < CHANGE_THRESHOLD ────────► pass through unchanged
                  │
                  └─ peak distance ≥ CHANGE_THRESHOLD
                           │
                           ▼
                  locate nearest word boundary to change time
                           │
                           ▼
                  split → [sub_segment_A, sub_segment_B]
                  assign new unique labels to each half
                           │
                           ▼
                  recurse on each half (up to MAX_DEPTH)
         │
         ▼
   expanded segment list (original + all splits)
         │
         ▼
   ECAPA-TDNN embed per unique label (existing pipeline, unchanged)
         │
         ▼
   cosine match to SpeakerProfile DB (existing, unchanged)
```

### Step-by-step

**1. Extract word timestamps alongside segments**

`TranscribePoller.parse_words(transcript_json)` returns:

```python
[{"word": str, "start_time": float, "end_time": float}, ...]
```

This runs over the same JSON already downloaded, with no extra AWS calls. Punctuation tokens (no timestamp) are attached to the preceding word (same logic as `parse_diarized_transcript`).

**2. Re-diarize long segments**

`re_diarize_segments(segments, words, waveform, sample_rate, embedder, settings)` returns a new segment list.

For each segment:

- If `end_time - start_time < MIN_SEGMENT_DURATION`: yield unchanged.
- Otherwise: call `_try_split(segment, words_in_range, waveform, sample_rate, embedder, settings, depth=0)`.

**3. Sliding-window embedding**

For a segment `[t_start, t_end]`:

```
windows = []
t = t_start
while t + WINDOW_SIZE <= t_end:
    slice = waveform[:, int(t * sr) : int((t + WINDOW_SIZE) * sr)]
    windows.append(embedder.encode_tensor(slice, sr))
    t += WINDOW_STRIDE
```

Need at least 2 windows (i.e., segment must be `≥ WINDOW_SIZE + WINDOW_STRIDE`) to compute a distance. For very short segments this naturally falls back to no-split.

**4. Change-point detection**

```
distances = [cosine(windows[i], windows[i+1]) for i in range(len(windows) - 1)]
smoothed  = moving_average(distances, width=3)
peak_idx  = argmax(smoothed)
peak_dist = smoothed[peak_idx]
```

If `peak_dist < CHANGE_THRESHOLD`: no split, yield segment unchanged.

**5. Estimate change time and find word boundary**

```
change_time = t_start + peak_idx * WINDOW_STRIDE + WINDOW_SIZE / 2
```

This is the midpoint of the window pair with the highest distance. Find the word in `words_in_range` whose start time is nearest to `change_time` and use that as the split boundary.

Reject the split if either resulting sub-segment would be shorter than `MIN_SPLIT_DURATION`.

**6. Assign labels and recurse**

Use a module-level counter to generate fresh labels: `re_0`, `re_1`, `re_2`, … These labels are opaque strings — the downstream embedding step treats them identically to Transcribe's `spk_0`, `spk_1`.

Recurse on each half with `depth + 1`. Stop recursing at `MAX_SPLIT_DEPTH`.

---

## Configuration

Add to `transcription-worker/config.py`:

```python
REDIARIZE_MIN_SEGMENT_DURATION: float = 5.0
# Segments shorter than this are not re-examined. AWS Transcribe is
# generally reliable for short segments; splitting them risks fragmentation.

REDIARIZE_WINDOW_SIZE: float = 1.5
# Duration (seconds) of each embedding window. ECAPA-TDNN works best with
# ≥1 s of audio; 1.5 s gives a clean embedding without too much smearing.

REDIARIZE_WINDOW_STRIDE: float = 0.5
# Hop between windows (seconds). Smaller = finer temporal resolution but
# more ECAPA-TDNN inference calls per segment.

REDIARIZE_CHANGE_THRESHOLD: float = 0.40
# Cosine distance at which a peak is treated as a speaker change.
# Higher than the profile-matching threshold (0.25) to avoid false splits —
# we need confident evidence of a change before fragmenting a segment.

REDIARIZE_MIN_SPLIT_DURATION: float = 1.5
# Minimum duration (seconds) for either half of a split. Prevents creating
# sub-segments too short to embed reliably.

REDIARIZE_MAX_DEPTH: int = 3
# Maximum recursive splits per original segment. Caps the worst-case
# number of new segments from a single long Transcribe segment.
```

All values are tunable at deploy time via environment variables.

---

## Files Changed

| File | Change |
|---|---|
| `transcription-worker/config.py` | Add `REDIARIZE_*` settings |
| `transcription-worker/services/transcribe_poller.py` | Add `parse_words()` method |
| `transcription-worker/services/re_diarizer.py` | **New** — `re_diarize_segments()` and helpers |
| `transcription-worker/handlers/transcription.py` | Call `parse_words()` + `re_diarize_segments()` between Transcribe parsing and embedding loop |
| `transcription-worker/tests/test_re_diarizer.py` | **New** — unit tests (no model required) |
| `transcription-worker/tests/test_transcribe_poller.py` | Add tests for `parse_words()` |

---

## Detailed File Changes

### `services/transcribe_poller.py` — new method

```python
def parse_words(self, transcript_json: dict) -> list[dict]:
    """
    Returns [{word, start_time, end_time}] from Transcribe output.
    Punctuation tokens (no timestamp) are appended to the preceding word.
    """
    items = transcript_json.get("results", {}).get("items", [])
    words = []
    for item in items:
        if item["type"] == "punctuation":
            if words:
                words[-1]["word"] += item["alternatives"][0]["content"]
            continue
        words.append({
            "word": item["alternatives"][0]["content"],
            "start_time": float(item["start_time"]),
            "end_time": float(item["end_time"]),
        })
    return words
```

### `services/re_diarizer.py` — new file (full outline)

```python
import itertools
import logging
from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)
_label_counter = itertools.count()   # module-level; resets each process start


def _next_label() -> str:
    return f"re_{next(_label_counter)}"


def _moving_average(values: list[float], width: int) -> list[float]:
    """Simple centred moving average; pads edges with edge values."""
    ...


def _words_in_range(
    words: list[dict], t_start: float, t_end: float
) -> list[dict]:
    return [w for w in words if t_start <= w["start_time"] < t_end]


def _try_split(
    segment: dict,
    words: list[dict],
    waveform,          # torch.Tensor
    sample_rate: int,
    embedder,
    settings,
    depth: int,
) -> list[dict]:
    """
    Attempts to detect a speaker-change within `segment` using sliding-window
    ECAPA-TDNN embeddings. Returns either [segment] (no split) or two or more
    refined sub-segments.
    """
    if depth >= settings.REDIARIZE_MAX_DEPTH:
        return [segment]

    t_start = segment["start_time"]
    t_end = segment["end_time"]
    duration = t_end - t_start

    # Build windows
    window_embeddings = []
    t = t_start
    while t + settings.REDIARIZE_WINDOW_SIZE <= t_end:
        start_frame = int(t * sample_rate)
        end_frame = int((t + settings.REDIARIZE_WINDOW_SIZE) * sample_rate)
        window_wav = waveform[:, start_frame:end_frame]
        emb = embedder.encode_tensor(window_wav, sample_rate)
        window_embeddings.append((t, emb))
        t += settings.REDIARIZE_WINDOW_STRIDE

    if len(window_embeddings) < 2:
        return [segment]

    distances = [
        cosine(window_embeddings[i][1], window_embeddings[i + 1][1])
        for i in range(len(window_embeddings) - 1)
    ]
    smoothed = _moving_average(distances, width=3)
    peak_idx = max(range(len(smoothed)), key=lambda i: smoothed[i])
    peak_dist = smoothed[peak_idx]

    if peak_dist < settings.REDIARIZE_CHANGE_THRESHOLD:
        logger.debug(
            "Segment [%.2f-%.2f] peak_dist=%.3f < threshold=%.3f, no split",
            t_start, t_end, peak_dist, settings.REDIARIZE_CHANGE_THRESHOLD,
        )
        return [segment]

    # Estimate change time = midpoint of the changing window pair
    change_time = window_embeddings[peak_idx][0] + settings.REDIARIZE_WINDOW_SIZE / 2

    # Find nearest word boundary
    seg_words = _words_in_range(words, t_start, t_end)
    if not seg_words:
        return [segment]

    split_word = min(seg_words, key=lambda w: abs(w["start_time"] - change_time))
    split_time = split_word["start_time"]

    # Reject if either half is too short
    if (split_time - t_start) < settings.REDIARIZE_MIN_SPLIT_DURATION:
        return [segment]
    if (t_end - split_time) < settings.REDIARIZE_MIN_SPLIT_DURATION:
        return [segment]

    words_a = [w for w in seg_words if w["start_time"] < split_time]
    words_b = [w for w in seg_words if w["start_time"] >= split_time]

    label_a = _next_label()
    label_b = _next_label()

    seg_a = {
        "speaker_label": label_a,
        "start_time": t_start,
        "end_time": split_time,
        "text": " ".join(w["word"] for w in words_a),
    }
    seg_b = {
        "speaker_label": label_b,
        "start_time": split_time,
        "end_time": t_end,
        "text": " ".join(w["word"] for w in words_b),
    }

    logger.info(
        "Split segment [%.2f-%.2f] label=%s at %.2f (peak_dist=%.3f) → %s [%.2f-%.2f], %s [%.2f-%.2f]",
        t_start, t_end, segment["speaker_label"], split_time, peak_dist,
        label_a, t_start, split_time,
        label_b, split_time, t_end,
    )

    result = []
    result.extend(_try_split(seg_a, words, waveform, sample_rate, embedder, settings, depth + 1))
    result.extend(_try_split(seg_b, words, waveform, sample_rate, embedder, settings, depth + 1))
    return result


def re_diarize_segments(
    segments: list[dict],
    words: list[dict],
    waveform,
    sample_rate: int,
    embedder,
    settings,
) -> list[dict]:
    """
    Post-processes Transcribe segments. Long segments are examined for
    internal speaker changes using sliding-window ECAPA-TDNN embeddings.
    Returns a new segment list; order is preserved.
    """
    result = []
    for seg in segments:
        duration = seg["end_time"] - seg["start_time"]
        if duration < settings.REDIARIZE_MIN_SEGMENT_DURATION:
            result.append(seg)
        else:
            result.extend(
                _try_split(seg, words, waveform, sample_rate, embedder, settings, depth=0)
            )
    logger.info(
        "re_diarize_segments: %d input segments → %d output segments",
        len(segments), len(result),
    )
    return result
```

### `handlers/transcription.py` — integration points

Two additions after `transcript_json` is downloaded:

```python
# Step 5a: parse words (needed for re-diarizer and future Option C alignment)
words = poller.parse_words(transcript_json)

# Step 5b: parse diarized segments (existing)
segments = poller.parse_diarized_transcript(transcript_json)

# Step 5c: re-diarize long segments using ECAPA-TDNN
# (source audio already downloaded; waveform loaded below in step 6)
```

And then after the waveform is loaded in step 6, before the unique-labels loop:

```python
from services.re_diarizer import re_diarize_segments
segments = re_diarize_segments(
    segments, words, source_waveform, source_sample_rate, embedder, settings
)
```

Everything from step 6 onward (unique label discovery, embedding, matching) runs unchanged on the expanded segment list.

---

## Test Plan

### `tests/test_re_diarizer.py` (new, no model required)

All tests use stubbed embedders and synthetic segments. No SpeechBrain, no torch, no AWS.

| Test | Description |
|---|---|
| `test_short_segment_passes_through` | Segments below `MIN_SEGMENT_DURATION` are returned unchanged |
| `test_no_split_below_threshold` | Sliding-window distances all below threshold → no split |
| `test_split_on_peak_above_threshold` | Distance spike at midpoint → segment split at nearest word boundary |
| `test_split_respects_min_split_duration` | Change detected but either half is too short → no split |
| `test_recursive_split` | Long segment with two change points → two splits at depth 1 |
| `test_max_depth_respected` | `MAX_DEPTH=0` → no splitting regardless of distances |
| `test_no_words_in_range` | Segment with no word timestamps → no split |
| `test_label_uniqueness` | All new labels across multiple calls are unique strings |
| `test_text_reconstruction` | Words are correctly distributed to sub-segments after split |

### `tests/test_transcribe_poller.py` (additions)

| Test | Description |
|---|---|
| `test_parse_words_basic` | Normal item list returns correct word/timestamp dicts |
| `test_parse_words_punctuation_attached` | Punctuation appended to preceding word, not a separate entry |
| `test_parse_words_empty` | Empty items list returns empty list |

---

## Caveats and Risks

**ECAPA-TDNN inference cost**: Each long segment triggers multiple `encode_tensor` calls (one per window). A 30-second segment with `WINDOW_SIZE=1.5` and `STRIDE=0.5` produces ~57 windows and ~56 comparisons. At ~20ms per inference on Fargate CPU, that's ~1 second of extra processing per long segment. For typical meeting recordings this is acceptable; for very long recordings with many long segments it can add up.

**Short audio at segment boundaries**: If a segment is just barely above `MIN_SEGMENT_DURATION`, the windows at the edges may contain very little audio or silence. The min-split-duration guard (`MIN_SPLIT_DURATION`) mitigates this.

**Label counter persists across jobs in the same process**: `_label_counter` is module-level and increments across jobs within a single worker process. Labels like `re_0`, `re_1` are only meaningful within a single job and are not persisted to the DB (only the matched `speaker_profile_id` is). This is intentional and not a bug.

**Does not help with under-labelling**: If Transcribe assigns `spk_0` to everything (MaxSpeakerLabels=1 effective), Option B will detect the changes and create new labels, but those labels will all match the same profile (or none). Option A's MaxSpeakerLabels fix is required for Option B to be most effective.

**Superseded by Option C**: Option B is removed when pyannote (Option C) is deployed. The `parse_words` method added here is retained and reused by Option C for word-to-turn alignment.

---

## Rollout

1. Implement `parse_words` in `TranscribePoller` and its tests (no behaviour change to existing pipeline).
2. Implement `re_diarizer.py` and its tests in isolation (pure Python, no model).
3. Integrate into `handlers/transcription.py`.
4. Deploy. Monitor `SpeakerMatchSuccessRate` CloudWatch metric for improvement.
5. Tune `REDIARIZE_CHANGE_THRESHOLD` based on observed false-split and missed-split rates in production logs. The `INFO`-level split log line (`Split segment [...]`) makes this easy to query in CloudWatch Logs Insights.
