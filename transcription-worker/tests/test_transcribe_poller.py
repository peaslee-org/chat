"""Unit tests for TranscribePoller.parse_diarized_transcript.

No AWS credentials, DB, or audio files needed — pure function under test.
"""
import sys
import os

# The worker has no package structure; source files live at the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from services.transcribe_poller import TranscribePoller


def make_poller():
    settings = MagicMock()
    settings.AWS_REGION = "us-east-1"
    with __import__("unittest.mock", fromlist=["patch"]).patch("boto3.client"):
        return TranscribePoller(settings)


def build_transcript(speaker_items: list[dict], word_items: list[dict]) -> dict:
    """Build a minimal AWS Transcribe diarized JSON structure."""
    return {
        "results": {
            "speaker_labels": {"segments": speaker_items},
            "items": word_items,
        }
    }


def pronunciation(start: str, end: str, word: str) -> dict:
    return {"type": "pronunciation", "start_time": start, "end_time": end,
            "alternatives": [{"content": word}]}


def punctuation(char: str) -> dict:
    return {"type": "punctuation", "alternatives": [{"content": char}]}


class TestParseDiarizedTranscript:

    def test_two_speakers_correct_start_times(self):
        """Regression: spk_1 start_time must be its own first word, not the transcript start."""
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [
                    {"start_time": "0.5", "end_time": "1.0"},
                    {"start_time": "1.1", "end_time": "1.8"},
                ]},
                {"speaker_label": "spk_1", "items": [
                    {"start_time": "2.0", "end_time": "2.5"},
                    {"start_time": "2.6", "end_time": "3.0"},
                ]},
            ],
            word_items=[
                pronunciation("0.5", "1.0", "Hello"),
                pronunciation("1.1", "1.8", "there"),
                pronunciation("2.0", "2.5", "World"),
                pronunciation("2.6", "3.0", "here"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 2
        spk0 = next(s for s in segments if s["speaker_label"] == "spk_0")
        spk1 = next(s for s in segments if s["speaker_label"] == "spk_1")

        assert spk0["start_time"] == 0.5
        assert spk0["end_time"] == 1.8
        # Core regression: spk_1 must start at 2.0, not 0.5
        assert spk1["start_time"] == 2.0
        assert spk1["end_time"] == 3.0

    def test_two_speakers_text_content(self):
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [{"start_time": "0.5", "end_time": "1.0"}]},
                {"speaker_label": "spk_1", "items": [{"start_time": "1.5", "end_time": "2.0"}]},
            ],
            word_items=[
                pronunciation("0.5", "1.0", "Hello"),
                pronunciation("1.5", "2.0", "World"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert segments[0]["text"] == "Hello"
        assert segments[1]["text"] == "World"

    def test_punctuation_attached_to_preceding_word(self):
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [
                    {"start_time": "0.5", "end_time": "1.0"},
                    {"start_time": "1.1", "end_time": "1.5"},
                ]},
            ],
            word_items=[
                pronunciation("0.5", "1.0", "Hello"),
                punctuation(","),
                pronunciation("1.1", "1.5", "there"),
                punctuation("."),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 1
        assert segments[0]["text"] == "Hello, there."

    def test_single_speaker_no_transition(self):
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [
                    {"start_time": "0.1", "end_time": "0.5"},
                    {"start_time": "0.6", "end_time": "1.0"},
                    {"start_time": "1.1", "end_time": "1.5"},
                ]},
            ],
            word_items=[
                pronunciation("0.1", "0.5", "One"),
                pronunciation("0.6", "1.0", "two"),
                pronunciation("1.1", "1.5", "three"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 1
        assert segments[0]["speaker_label"] == "spk_0"
        assert segments[0]["start_time"] == 0.1
        assert segments[0]["end_time"] == 1.5
        assert segments[0]["text"] == "One two three"

    def test_three_speakers_all_get_correct_starts(self):
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [{"start_time": "0.0", "end_time": "1.0"}]},
                {"speaker_label": "spk_1", "items": [{"start_time": "1.5", "end_time": "2.5"}]},
                {"speaker_label": "spk_2", "items": [{"start_time": "3.0", "end_time": "4.0"}]},
            ],
            word_items=[
                pronunciation("0.0", "1.0", "Alpha"),
                pronunciation("1.5", "2.5", "Beta"),
                pronunciation("3.0", "4.0", "Gamma"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 3
        assert segments[0] == {"speaker_label": "spk_0", "start_time": 0.0, "end_time": 1.0, "text": "Alpha"}
        assert segments[1] == {"speaker_label": "spk_1", "start_time": 1.5, "end_time": 2.5, "text": "Beta"}
        assert segments[2] == {"speaker_label": "spk_2", "start_time": 3.0, "end_time": 4.0, "text": "Gamma"}

    def test_speaker_returns_then_gets_merged_run(self):
        """spk_0 speaks, then spk_1, then spk_0 again — produces 3 separate segments."""
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [
                    {"start_time": "0.0", "end_time": "1.0"},
                    {"start_time": "3.0", "end_time": "4.0"},
                ]},
                {"speaker_label": "spk_1", "items": [
                    {"start_time": "1.5", "end_time": "2.5"},
                ]},
            ],
            word_items=[
                pronunciation("0.0", "1.0", "First"),
                pronunciation("1.5", "2.5", "Second"),
                pronunciation("3.0", "4.0", "Third"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 3
        assert segments[0] == {"speaker_label": "spk_0", "start_time": 0.0, "end_time": 1.0, "text": "First"}
        assert segments[1] == {"speaker_label": "spk_1", "start_time": 1.5, "end_time": 2.5, "text": "Second"}
        assert segments[2] == {"speaker_label": "spk_0", "start_time": 3.0, "end_time": 4.0, "text": "Third"}

    def test_empty_transcript_returns_empty_list(self):
        poller = make_poller()
        transcript = build_transcript(speaker_items=[], word_items=[])
        assert poller.parse_diarized_transcript(transcript) == []

    def test_unknown_word_time_falls_back_to_current_speaker(self):
        """A word with no speaker label entry keeps the current speaker."""
        poller = make_poller()
        transcript = build_transcript(
            speaker_items=[
                {"speaker_label": "spk_0", "items": [{"start_time": "0.0", "end_time": "1.0"}]},
            ],
            # Second word has a start_time not listed in speaker_labels
            word_items=[
                pronunciation("0.0", "1.0", "Hello"),
                pronunciation("1.5", "2.0", "world"),
            ],
        )

        segments = poller.parse_diarized_transcript(transcript)

        assert len(segments) == 1
        assert segments[0]["speaker_label"] == "spk_0"
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["end_time"] == 2.0


class TestParseWords:

    def test_basic_words_extracted(self):
        poller = make_poller()
        transcript = {
            "results": {
                "items": [
                    pronunciation("0.0", "0.5", "Hello"),
                    pronunciation("0.6", "1.0", "world"),
                ]
            }
        }
        words = poller.parse_words(transcript)
        assert len(words) == 2
        assert words[0] == {"word": "Hello", "start_time": 0.0, "end_time": 0.5}
        assert words[1] == {"word": "world", "start_time": 0.6, "end_time": 1.0}

    def test_punctuation_attached_to_preceding_word(self):
        poller = make_poller()
        transcript = {
            "results": {
                "items": [
                    pronunciation("0.0", "0.5", "Hello"),
                    punctuation(","),
                    pronunciation("0.6", "1.0", "world"),
                    punctuation("."),
                ]
            }
        }
        words = poller.parse_words(transcript)
        assert len(words) == 2
        assert words[0]["word"] == "Hello,"
        assert words[1]["word"] == "world."

    def test_empty_items_returns_empty_list(self):
        poller = make_poller()
        assert poller.parse_words({"results": {"items": []}}) == []

    def test_empty_transcript_returns_empty_list(self):
        poller = make_poller()
        assert poller.parse_words({}) == []

    def test_leading_punctuation_ignored_gracefully(self):
        """Punctuation with no preceding word is silently dropped."""
        poller = make_poller()
        transcript = {
            "results": {
                "items": [
                    punctuation("."),
                    pronunciation("0.0", "0.5", "Hello"),
                ]
            }
        }
        words = poller.parse_words(transcript)
        assert len(words) == 1
        assert words[0]["word"] == "Hello"


# ---------------------------------------------------------------------------
# wait_for_completion — release abort
# ---------------------------------------------------------------------------

def test_wait_for_completion_raises_interrupted_when_abort_is_set():
    """An *immediate* GPU release sets ReleaseWatcher.abort; the poll loop (the longest wait in
    the job) must give up on the next tick instead of sleeping out its 30 s interval."""
    import threading
    from gpu_worker.sqs import Interrupted
    poller = make_poller()
    poller.client.get_transcription_job.return_value = {
        "TranscriptionJob": {"TranscriptionJobStatus": "IN_PROGRESS"}
    }
    abort = threading.Event()
    abort.set()
    with pytest.raises(Interrupted):
        poller.wait_for_completion("job-1", poll_interval=30, abort=abort)
    assert poller.client.get_transcription_job.call_count == 0     # checked before each request


def test_wait_for_completion_without_abort_still_returns_on_completed():
    poller = make_poller()
    poller.client.get_transcription_job.return_value = {
        "TranscriptionJob": {"TranscriptionJobStatus": "COMPLETED"}
    }
    assert poller.wait_for_completion("job-1")["TranscriptionJobStatus"] == "COMPLETED"
