"""
Standalone mock transcription worker for local development.

Polls PostgreSQL directly — no SQS, no torch, no pyannote, no SpeechBrain.
Reuses db.py / models.py from the worker package and services/aligner.py.

Per-job fixture files can be placed in DEV_FIXTURES_DIR/<job_id>/ to inject
real captured data at any pipeline stage:

  transcribe.json  — AWS Transcribe output (same format as transcript_raw.json)
  diarize.json     — [{"speaker_label": "SPEAKER_00", "start": 0.5, "end": 3.2}, ...]
  matcher.json     — [{"start": 0.5, "end": 3.2, "speaker_profile_id": "<uuid>|null",
                        "cosine_dist": 0.18}, ...]

Absent fixture → synthetic fallback for that stage.

Usage:
  DATABASE_URL=postgresql+psycopg2://... \\
  LOCAL_STORAGE_PATH=/tmp/mock-audio \\
  DEV_FIXTURES_DIR=/tmp/mock-fixtures \\
  AUDIO_BUCKET_NAME=unused TRANSCRIBE_SQS_QUEUE_URL=unused \\
  python dev_worker.py
"""
import json
import logging
import math
import os
import random
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from db import get_session
from models import (
    SpeakerSample,
    TranscriptionJob,
    TranscriptionJobEvent,
    TranscriptSegment,
    TranscriptTurnDistance,
)
from services.aligner import OVERLAP, align_words_to_turns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_STORAGE_PATH = os.environ.get("LOCAL_STORAGE_PATH", "/tmp/mock-audio")
DEV_FIXTURES_DIR = os.environ.get("DEV_FIXTURES_DIR", "/tmp/mock-fixtures")
POLL_INTERVAL = int(os.environ.get("DEV_WORKER_POLL_INTERVAL", "2"))
SEGMENTS_PER_JOB = int(os.environ.get("DEV_WORKER_SEGMENTS", "6"))
FAKE_SPEAKERS = ["SPEAKER_00", "SPEAKER_01"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_unit_vector(n: int) -> list[float]:
    """Return a random L2-normalised vector of length n (stdlib only)."""
    v = [random.gauss(0, 1) for _ in range(n)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm > 0 else v


def _load_fixture(job_id: uuid.UUID, stage: str) -> object | None:
    """Load a fixture JSON file for the given job and stage, or return None."""
    p = Path(DEV_FIXTURES_DIR) / str(job_id) / f"{stage}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load fixture %s: %s", p, exc)
        return None


def _get_audio_duration(audio_s3_key: str) -> float:
    """Try to read WAV duration from local storage; fall back to 60 s."""
    path = Path(LOCAL_STORAGE_PATH) / audio_s3_key
    if path.exists():
        try:
            with wave.open(str(path), "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            pass  # not a WAV or unreadable — use default
    return 60.0


def _parse_words_fixture(transcript_json: dict) -> list[dict]:
    """Extract [{word, start_time, end_time}] from an AWS Transcribe JSON fixture."""
    items = transcript_json.get("results", {}).get("items", [])
    words: list[dict] = []
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


def _synthetic_words(duration: float) -> list[dict]:
    """Generate one synthetic word every 0.5 s over the given duration."""
    words = []
    t = 0.0
    i = 0
    while t < duration:
        end = min(t + 0.45, duration)
        words.append({"word": f"word{i}", "start_time": round(t, 3), "end_time": round(end, 3)})
        t += 0.5
        i += 1
    return words


def _synthetic_turns(duration: float, n_turns: int) -> list[dict]:
    """Generate n_turns turns spread evenly over duration, alternating FAKE_SPEAKERS."""
    if n_turns == 0 or duration <= 0:
        return []
    step = duration / n_turns
    turns = []
    for i in range(n_turns):
        start = round(i * step, 3)
        end = round(min((i + 1) * step - 0.05, duration), 3)
        turns.append({
            "speaker_label": FAKE_SPEAKERS[i % len(FAKE_SPEAKERS)],
            "start": start,
            "end": end,
        })
    return turns


# ---------------------------------------------------------------------------
# Sample embedding
# ---------------------------------------------------------------------------

def process_pending_samples() -> int:
    """Find SpeakerSample rows in 'processing' state and mark them ready with a fake embedding."""
    with get_session() as session:
        rows = session.execute(
            select(SpeakerSample).where(SpeakerSample.status == "processing")
        ).scalars().all()
        for sample in rows:
            sample.embedding = _random_unit_vector(192)
            sample.status = "ready"
            logger.info("Sample %s → ready (fake 192-dim embedding)", sample.id)
        return len(rows)


# ---------------------------------------------------------------------------
# Transcription job
# ---------------------------------------------------------------------------

def _process_job(job_id: uuid.UUID) -> None:
    """Run the mock transcription pipeline for a single job."""

    # --- Stage 0: mark received ---
    with get_session() as session:
        job = session.get(TranscriptionJob, job_id)
        if job is None:
            logger.warning("Job %s not found — skipping", job_id)
            return
        audio_s3_key = job.audio_s3_key
        session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event="worker.received"))

    # --- Stage 1: Transcribe words ---
    transcribe_fixture = _load_fixture(job_id, "transcribe")
    if transcribe_fixture is not None:
        words = _parse_words_fixture(transcribe_fixture)
        logger.info("Job %s: transcribe fixture (%d words)", job_id, len(words))
    else:
        duration = _get_audio_duration(audio_s3_key)
        words = _synthetic_words(duration)
        logger.info("Job %s: synthetic words (%.1fs, %d words)", job_id, duration, len(words))

    with get_session() as session:
        session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event="transcribe.complete"))

    # --- Stage 2: Diarization turns ---
    diarize_fixture = _load_fixture(job_id, "diarize")
    matcher_fixture = _load_fixture(job_id, "matcher")

    if diarize_fixture is not None:
        turns = diarize_fixture  # [{speaker_label, start, end}]
        logger.info("Job %s: diarize fixture (%d turns)", job_id, len(turns))
    elif matcher_fixture is not None:
        # Derive turns from matcher entries when no separate diarize fixture
        turns = [
            {"speaker_label": f"SPEAKER_{i:02d}", "start": m["start"], "end": m["end"]}
            for i, m in enumerate(matcher_fixture)
        ]
        logger.info("Job %s: turns derived from matcher fixture (%d turns)", job_id, len(turns))
    else:
        duration = _get_audio_duration(audio_s3_key)
        turns = _synthetic_turns(duration, n_turns=SEGMENTS_PER_JOB)
        logger.info("Job %s: synthetic turns (%d turns)", job_id, len(turns))

    with get_session() as session:
        session.add(TranscriptionJobEvent(
            job_id=job_id, source="worker", event="diarization.complete",
            detail={"turn_count": len(turns), "synthetic": diarize_fixture is None and matcher_fixture is None},
        ))

    # --- Stage 3: Align words to turns ---
    segments = align_words_to_turns(words, turns)

    with get_session() as session:
        session.add(TranscriptionJobEvent(
            job_id=job_id, source="worker", event="alignment.complete",
            detail={"segment_count": len(segments)},
        ))

    # --- Stage 4: Speaker matching (from fixture) ---
    turn_profile_ids: list[str | None] = [None] * len(turns)
    turn_dist_rows: list[dict] = []

    if matcher_fixture is not None:
        match_by_turn: dict[tuple, dict] = {}
        for m in matcher_fixture:
            match_by_turn[(m["start"], m["end"])] = m
        for i, turn in enumerate(turns):
            m = match_by_turn.get((turn["start"], turn["end"]))
            if m:
                turn_profile_ids[i] = m.get("speaker_profile_id")
                if m.get("cosine_dist") is not None and m.get("speaker_profile_id"):
                    turn_dist_rows.append({
                        "job_id": job_id,
                        "candidate_id": uuid.UUID(m["speaker_profile_id"]),
                        "start_time": turn["start"],
                        "end_time": turn["end"],
                        "duration": turn["end"] - turn["start"],
                        "cosine_dist": m["cosine_dist"],
                        "threshold": 0.25,
                        "text": "",
                        "occurred_at": datetime.now(timezone.utc),
                    })

    # --- Stage 5: Insert segments and finalise ---
    matched_count = 0
    with get_session() as session:
        job = session.get(TranscriptionJob, job_id)
        for seg in segments:
            turn_idx = seg["turn_index"]
            if turn_idx == OVERLAP:
                anon_label = "OVERLAP"
                profile_id = None
            else:
                profile_id_str = turn_profile_ids[turn_idx] if turn_idx < len(turn_profile_ids) else None
                profile_id = uuid.UUID(profile_id_str) if profile_id_str else None
                if profile_id:
                    anon_label = f"TURN_{turn_idx}"
                    matched_count += 1
                else:
                    label = turns[turn_idx]["speaker_label"] if turn_idx < len(turns) else "UNKNOWN"
                    anon_label = label or "UNKNOWN"
            session.add(TranscriptSegment(
                job_id=job_id,
                speaker_profile_id=profile_id,
                anonymous_label=anon_label,
                start_time=seg["start_time"],
                end_time=seg["end_time"],
                text=seg["text"],
            ))
        session.add(TranscriptionJobEvent(
            job_id=job_id, source="worker", event="segments.inserted",
            detail={"count": len(segments)},
        ))
        job.status = "complete"
        job.completed_at = datetime.now(timezone.utc)
        job.matched_speaker_count = matched_count
        job.total_segment_count = len(segments)
        session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event="job.complete"))

    # Insert TurnDistance rows if matcher fixture supplied them
    if turn_dist_rows:
        try:
            with get_session() as session:
                for row in turn_dist_rows:
                    session.add(TranscriptTurnDistance(**row))
        except Exception as exc:
            logger.warning("Job %s: skipping TurnDistance rows (FK mismatch?): %s", job_id, exc)

    logger.info(
        "Job %s complete: %d segment(s), %d matched (fixture stages: transcribe=%s diarize=%s matcher=%s)",
        job_id, len(segments), matched_count,
        transcribe_fixture is not None, diarize_fixture is not None, matcher_fixture is not None,
    )


def process_pending_jobs() -> int:
    with get_session() as session:
        rows = session.execute(
            select(TranscriptionJob).where(TranscriptionJob.status == "transcribing")
        ).scalars().all()
        job_ids = [job.id for job in rows]

    for job_id in job_ids:
        try:
            _process_job(job_id)
        except Exception:
            logger.error("Job %s failed", job_id, exc_info=True)
            try:
                with get_session() as session:
                    job = session.get(TranscriptionJob, job_id)
                    if job:
                        job.status = "failed"
                        job.error_message = "dev_worker processing error — check logs"
                        session.add(TranscriptionJobEvent(
                            job_id=job_id, source="worker", event="job.failed",
                        ))
            except Exception:
                logger.error("Could not mark job %s as failed", job_id, exc_info=True)

    return len(job_ids)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> None:
    logger.info(
        "Dev worker started — poll_interval=%ds, fixtures=%s, storage=%s",
        POLL_INTERVAL, DEV_FIXTURES_DIR, LOCAL_STORAGE_PATH,
    )
    while True:
        try:
            n_samples = process_pending_samples()
            n_jobs = process_pending_jobs()
            if n_samples or n_jobs:
                logger.info("Processed %d sample(s), %d job(s)", n_samples, n_jobs)
        except Exception:
            logger.error("Poll iteration failed", exc_info=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
