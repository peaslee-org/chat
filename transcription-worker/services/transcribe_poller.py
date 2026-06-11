import json
import time
import logging

import boto3

from config import Settings

logger = logging.getLogger(__name__)


class TranscribePoller:

    def __init__(self, settings: Settings):
        self.client = boto3.client("transcribe", region_name=settings.AWS_REGION)

    def wait_for_completion(self, aws_job_name: str, poll_interval: int = 30) -> dict:
        """
        Polls AWS Transcribe until job completes or fails.
        Returns the full TranscriptionJob dict on COMPLETED.
        Raises RuntimeError on FAILED.
        """
        while True:
            resp = self.client.get_transcription_job(TranscriptionJobName=aws_job_name)
            job = resp["TranscriptionJob"]
            job_status = job["TranscriptionJobStatus"]
            if job_status == "COMPLETED":
                return job
            if job_status == "FAILED":
                reason = job.get("FailureReason", "Unknown reason")
                raise RuntimeError(f"AWS Transcribe job failed: {reason}")
            logger.info("Waiting for transcription job %s, status=%s", aws_job_name, job_status)
            time.sleep(poll_interval)

    def parse_diarized_transcript(self, transcript_json: dict) -> list[dict]:
        """
        Parses AWS Transcribe diarized output into segments.
        Returns list of {speaker_label, start_time, end_time, text}.
        """
        results = transcript_json.get("results", {})
        speaker_labels = results.get("speaker_labels", {})
        items = results.get("items", [])

        # Build a map of start_time -> speaker_label from speaker segments
        time_to_speaker: dict[str, str] = {}
        for seg in speaker_labels.get("segments", []):
            label = seg["speaker_label"]
            for item in seg.get("items", []):
                time_to_speaker[item["start_time"]] = label

        # Group items by consecutive speaker
        segments: list[dict] = []
        current_speaker = None
        current_start = None
        current_end = None
        current_words: list[str] = []

        for item in items:
            if item["type"] == "punctuation":
                if current_words:
                    current_words[-1] += item["alternatives"][0]["content"]
                continue

            start = item.get("start_time")
            end = item.get("end_time")
            word = item["alternatives"][0]["content"]
            speaker = time_to_speaker.get(start, current_speaker)

            if speaker != current_speaker:
                if current_speaker is not None:
                    segments.append({
                        "speaker_label": current_speaker,
                        "start_time": float(current_start),
                        "end_time": float(current_end),
                        "text": " ".join(current_words),
                    })
                    current_words = []
                current_speaker = speaker
                current_start = start
            current_end = end
            current_words.append(word)

        if current_words and current_speaker is not None:
            segments.append({
                "speaker_label": current_speaker,
                "start_time": float(current_start),
                "end_time": float(current_end),
                "text": " ".join(current_words),
            })

        return segments

    def parse_words(self, transcript_json: dict) -> list[dict]:
        """
        Returns list of {word, start_time, end_time} from AWS Transcribe output.
        Punctuation tokens (no timestamps) are attached to the preceding word.
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
