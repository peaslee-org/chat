"""Unit tests for services/aligner.py — no models, AWS, or DB needed."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.aligner import align_words_to_turns, find_overlaps, OVERLAP


def word(w: str, start: float, end: float) -> dict:
    return {"word": w, "start_time": start, "end_time": end}


def turn(speaker: str, start: float, end: float) -> dict:
    return {"speaker_label": speaker, "start": start, "end": end}


class TestAlignWordToTurns:

    def test_normal_two_speakers(self):
        words = [word("Hello", 0.0, 0.5), word("there", 0.6, 1.0),
                 word("World", 1.5, 2.0), word("here", 2.1, 2.5)]
        turns = [turn("spk_0", 0.0, 1.2), turn("spk_1", 1.3, 2.6)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 2
        assert segs[0]["turn_index"] == 0
        assert segs[0]["text"] == "Hello there"
        assert segs[1]["turn_index"] == 1
        assert segs[1]["text"] == "World here"

    def test_word_in_gap_assigned_to_nearest_turn(self):
        # Word at 2.0-2.1 falls in a gap between turns ending at 1.5 and starting at 2.5
        words = [word("gap", 2.0, 2.1)]
        turns = [turn("spk_0", 0.0, 1.5), turn("spk_1", 2.5, 3.5)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 1
        # midpoint=2.05, dist to spk_0 end (1.5) = 0.55, dist to spk_1 start (2.5) = 0.45
        assert segs[0]["turn_index"] == 1

    def test_single_speaker(self):
        words = [word("One", 0.0, 0.5), word("two", 0.6, 1.0), word("three", 1.1, 1.5)]
        turns = [turn("spk_0", 0.0, 2.0)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 1
        assert segs[0]["turn_index"] == 0
        assert segs[0]["text"] == "One two three"
        assert segs[0]["start_time"] == 0.0
        assert segs[0]["end_time"] == 1.5

    def test_many_short_turns_interleaved(self):
        """Simulates rapid speaker alternation — each word in its own turn."""
        words = [word("A", 0.0, 0.5), word("B", 1.0, 1.5), word("A2", 2.0, 2.5)]
        turns = [
            turn("spk_0", 0.0, 0.6),
            turn("spk_1", 0.9, 1.6),
            turn("spk_0", 1.9, 2.6),
        ]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 3
        assert segs[0]["turn_index"] == 0
        assert segs[1]["turn_index"] == 1
        assert segs[2]["turn_index"] == 2

    def test_adjacent_same_label_turns_stay_separate(self):
        """
        Two consecutive turns with the same pyannote label must NOT be merged.
        They are distinct turns, independently embedded and matched.
        This is the core regression the turn-index approach prevents.
        """
        words = [
            word("hi",     0.2, 0.5), word("there",  0.6, 1.0),   # turn 0
            word("yes",    1.2, 1.5), word("indeed", 1.6, 2.0),   # turn 1
        ]
        turns = [
            turn("spk_0", 0.0, 1.1),   # turn 0
            turn("spk_0", 1.1, 2.1),   # turn 1 — same label, adjacent
        ]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 2
        assert segs[0]["turn_index"] == 0
        assert segs[1]["turn_index"] == 1

    def test_empty_words_returns_empty(self):
        assert align_words_to_turns([], [turn("spk_0", 0.0, 1.0)]) == []

    def test_empty_turns_returns_empty(self):
        assert align_words_to_turns([word("hi", 0.0, 0.5)], []) == []

    def test_consecutive_words_in_same_turn_merged(self):
        words = [word("Hi", 0.0, 0.3), word("there", 0.4, 0.8),
                 word("friend", 0.9, 1.2)]
        turns = [turn("spk_0", 0.0, 1.5)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 1
        assert segs[0]["text"] == "Hi there friend"

    def test_overlap_window_labeled_overlap(self):
        # spk_0: 0-3, spk_1: 1-2 → overlap from 1-2
        words = [word("before", 0.0, 0.5), word("overlap", 1.2, 1.8), word("after", 2.5, 3.0)]
        turns = [turn("spk_0", 0.0, 3.0), turn("spk_1", 1.0, 2.0)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 3
        assert segs[0]["turn_index"] == 0
        assert segs[0]["text"] == "before"
        assert segs[1]["turn_index"] == OVERLAP
        assert segs[1]["text"] == "overlap"
        assert segs[2]["turn_index"] == 0
        assert segs[2]["text"] == "after"

    def test_overlap_consecutive_words_merged(self):
        # Two words both in overlap window merge into one OVERLAP segment
        words = [word("yeah", 1.0, 1.4), word("I", 1.5, 1.8), word("can", 1.9, 2.2)]
        turns = [turn("spk_0", 0.0, 3.0), turn("spk_1", 0.8, 2.5)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 1
        assert segs[0]["turn_index"] == OVERLAP
        assert segs[0]["text"] == "yeah I can"

    def test_interjection_in_overlap_attributed_to_overlap(self):
        # Interjection where dominant speaker is also active → OVERLAP
        words = [word("Right", 2.0, 2.3)]
        turns = [turn("spk_0", 0.0, 5.0), turn("spk_1", 1.8, 2.5)]
        segs = align_words_to_turns(words, turns)
        assert len(segs) == 1
        assert segs[0]["turn_index"] == OVERLAP

    def test_exclusive_turns_unchanged_with_non_overlapping_input(self):
        # When turns don't actually overlap, behaviour is identical to before
        words = [word("A", 0.0, 0.5), word("B", 1.0, 1.5)]
        turns = [turn("spk_0", 0.0, 0.6), turn("spk_1", 0.9, 1.6)]
        segs = align_words_to_turns(words, turns)
        assert segs[0]["turn_index"] == 0
        assert segs[1]["turn_index"] == 1


class TestFindOverlaps:

    def test_no_overlaps_returns_empty(self):
        turns = [turn("spk_0", 0.0, 1.0), turn("spk_1", 1.0, 2.0)]
        excl = [turn("spk_0", 0.0, 1.0), turn("spk_1", 1.0, 2.0)]
        assert find_overlaps(turns, excl) == []

    def test_one_overlap_detected(self):
        # spk_0: 0-2, spk_1: 1-3 → overlap from 1-2
        turns = [turn("spk_0", 0.0, 2.0), turn("spk_1", 1.0, 3.0)]
        excl = [turn("spk_0", 0.0, 1.0), turn("spk_1", 1.0, 3.0)]
        overlaps = find_overlaps(turns, excl)
        assert len(overlaps) == 1
        assert overlaps[0]["start"] == 1.0
        assert overlaps[0]["end"] == 2.0
        assert set(overlaps[0]["speakers"]) == {"spk_0", "spk_1"}

    def test_adjacent_turns_not_overlapping(self):
        # Turns that share an endpoint should not produce an overlap
        turns = [turn("spk_0", 0.0, 1.0), turn("spk_1", 1.0, 2.0)]
        excl = turns
        assert find_overlaps(turns, excl) == []

    def test_empty_turns_returns_empty(self):
        assert find_overlaps([], []) == []
