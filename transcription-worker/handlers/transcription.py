import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

import boto3
import torchaudio
from sqlalchemy import select

from config import Settings
from db import get_session
from gpu_worker.sqs import Interrupted
from models import SpeakerProfile, SpeakerSample, TranscriptionJob, TranscriptionJobEvent, TranscriptSegment, TranscriptTurnDistance
from services.aligner import align_words_to_turns, OVERLAP
from services.diarizer import PyannoteDiarizer
from services.embedder import EcapaTdnnEmbedder
from services.matcher import match_speaker, ProbableMatch
from services.s3_client import S3Client
from services.transcribe_poller import TranscribePoller

logger = logging.getLogger(__name__)


def _maybe_capture(job_id: uuid.UUID, stage: str, data: object, s3_prefix: str, s3: "S3Client") -> None:
    """Upload a fixture JSON file to S3 at <s3_prefix>/<job_id>/<stage>.json if s3_prefix is set.

    Used to record real AWS Transcribe output, pyannote turns, and matcher results so that
    dev_worker.py can replay them locally without running ML models.
    """
    if not s3_prefix:
        return
    key = f"{s3_prefix.rstrip('/')}/{job_id}/{stage}.json"
    s3.upload_bytes(key, json.dumps(data, indent=2).encode(), content_type="application/json")
    logger.info("Captured fixture: s3://%s/%s", s3.bucket, key)


def _log_event(job_id: uuid.UUID, event: str, detail: dict | None = None) -> None:
    with get_session() as session:
        session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event=event, detail=detail))



def _raise_if_aborted(abort: "threading.Event | None") -> None:
    if abort is not None and abort.is_set():
        raise Interrupted("GPU release requested")


def process_transcription_job(body: dict, settings: Settings, abort: "threading.Event | None" = None) -> None:
    """`abort` is ReleaseWatcher.abort: an *immediate* GPU release. It is polled at the two places a
    job spends real time — the Transcribe wait and the per-turn embedding loop — and raises
    Interrupted, which puts the row back to `transcribing` (the API's pre-worker `job_status`) and
    leaves the message for redelivery. Diarization itself (one in-process torch call) is not interruptible."""
    job_id = uuid.UUID(body["job_id"])
    aws_job_name = body["aws_transcribe_job_name"]
    speaker_ids = body.get("speaker_ids") or []

    s3 = S3Client(settings)
    poller = TranscribePoller(settings)
    embedder = EcapaTdnnEmbedder.get()
    start_time = time.time()

    with get_session() as session:
        job = session.get(TranscriptionJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found in DB")
        session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event="worker.received"))
        job.status = "matching"
        session.flush()

    try:
        # Step 2: Poll AWS Transcribe
        logger.info("Polling AWS Transcribe for job %s", aws_job_name)
        _log_event(job_id, "transcribe.polling")
        aws_job = poller.wait_for_completion(aws_job_name, abort=abort)
        _log_event(job_id, "transcribe.complete")

        # Step 4: Download transcript JSON
        transcript_output_key = aws_job["Transcript"]["TranscriptFileUri"]
        # TranscriptFileUri is an S3 URI; extract the key
        # Format: https://s3.amazonaws.com/bucket/key or s3://bucket/key
        if transcript_output_key.startswith("s3://"):
            key_part = transcript_output_key.split("/", 3)[3]
        else:
            key_part = "/".join(transcript_output_key.split("/")[4:])

        transcript_bytes = s3.download_bytes(key_part)
        transcript_json = json.loads(transcript_bytes.decode("utf-8"))

        # Step 5a: Extract word timestamps from Transcribe (no speaker info)
        words = poller.parse_words(transcript_json)
        _maybe_capture(job_id, "transcribe", transcript_json, settings.DEV_CAPTURE_FIXTURES_S3_PREFIX, s3)

        # Step 5b: Load source audio and job metadata
        with get_session() as session:
            job = session.get(TranscriptionJob, job_id)
            audio_s3_key = job.audio_s3_key
            user_id = job.user_id
            speaker_count_hint = job.speaker_count_hint

        source_audio_bytes = s3.download_bytes(audio_s3_key)
        _log_event(job_id, "audio.fetched")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(source_audio_bytes)
            tmp_path = tmp.name

        try:
            # Step 5b: Run pyannote diarization on the source audio file
            diarizer = PyannoteDiarizer.get()
            max_spk = max(
                len(speaker_ids) if speaker_ids else 0,
                speaker_count_hint or 0,
            ) or None
            logger.info("Running pyannote diarization (max_speakers=%s)", max_spk)
            diarization = diarizer.diarize(tmp_path, min_speakers=1, max_speakers=max_spk)

            # Log raw pyannote turns for diagnostics
            turns_by_speaker: dict[str, int] = {}
            for t in diarization["turns"]:
                turns_by_speaker[t["speaker_label"]] = turns_by_speaker.get(t["speaker_label"], 0) + 1
            logger.info(
                "Pyannote diarization: %d turn(s), speakers=%s",
                len(diarization["turns"]),
                dict(sorted(turns_by_speaker.items())),
            )
            for t in diarization["turns"]:
                logger.debug("  turn [%.3f - %.3f] %s", t["start"], t["end"], t["speaker_label"])
            _log_event(job_id, "diarization.complete", {
                "turn_count": len(diarization["turns"]),
                "speakers": turns_by_speaker,
                "turns": [
                    {"speaker": t["speaker_label"], "start": round(t["start"], 3), "end": round(t["end"], 3)}
                    for t in diarization["turns"]
                ],
            })
            _maybe_capture(job_id, "diarize", diarization["turns"], settings.DEV_CAPTURE_FIXTURES_S3_PREFIX, s3)

            # Step 5c: Align words to turns; overlapping windows get "OVERLAP" label
            segments = align_words_to_turns(words, diarization["turns"])

            overlap_count = sum(1 for s in segments if s["turn_index"] == OVERLAP)
            turn_count    = sum(1 for s in segments if s["turn_index"] != OVERLAP)
            logger.info(
                "Alignment: %d segment(s) — %d turn, %d overlap",
                len(segments), turn_count, overlap_count,
            )
            _log_event(job_id, "alignment.complete", {
                "segment_count": len(segments),
                "overlap_count": overlap_count,
            })
            if overlap_count:
                logger.info("Detected %d overlapping speech segment(s)", overlap_count)

            # Step 6: Load waveform for embedding (reuse the same temp file)
            logger.info("Loading source waveform for embedding extraction")
            source_waveform, source_sample_rate = torchaudio.load(tmp_path)
            duration_s = source_waveform.shape[1] / source_sample_rate
            logger.info(
                "Waveform loaded: %.1fs audio, %d Hz, %d channels",
                duration_s, source_sample_rate, source_waveform.shape[0],
            )
        finally:
            os.unlink(tmp_path)

        all_turns = diarization["turns"]

        # Build per-turn text directly from words using each word's midpoint.
        # Each word goes to the turn whose time range contains its midpoint; gap
        # words go to the nearest turn. Speaker labels are not used here — only
        # the turn time ranges matter until cosine distance is calculated.
        turn_texts: list[str] = [""] * len(all_turns)
        for word in words:
            midpoint = (word["start_time"] + word["end_time"]) / 2
            active = [i for i, t in enumerate(all_turns) if t["start"] <= midpoint < t["end"]]
            if len(active) > 1:
                continue  # overlap window — skip
            if len(active) == 1:
                turn_idx = active[0]
            else:
                # Gap — nearest turn by endpoint distance
                turn_idx = min(
                    range(len(all_turns)),
                    key=lambda i: min(abs(midpoint - all_turns[i]["start"]), abs(midpoint - all_turns[i]["end"])),
                )
            sep = " " if turn_texts[turn_idx] else ""
            turn_texts[turn_idx] += sep + word["word"]

        # Step 7: Load ready speaker samples for candidate matching
        with get_session() as session:
            query = select(SpeakerSample).where(
                SpeakerSample.status == "ready",
                SpeakerSample.speaker_profile_id.in_(
                    [uuid.UUID(sid) for sid in speaker_ids]
                ) if speaker_ids else True,
            )
            result = session.execute(query)
            samples = [s for s in result.scalars().all() if s.embedding is not None]

            if speaker_ids:
                # Race (live prod, 2026-09-02): a filtered speaker's `sample_embedding` message can
                # still be queued behind this job's message, so its sample is `processing` here.
                # The model is already loaded on the GPU — embed it inline rather than matching
                # against a candidate set that's short a speaker. The sample's own queued
                # `sample_embedding` message becomes a no-op when it's later delivered.
                pending_query = select(SpeakerSample).where(
                    SpeakerSample.status == "processing",
                    SpeakerSample.speaker_profile_id.in_(
                        [uuid.UUID(sid) for sid in speaker_ids]
                    ),
                )
                pending_samples = session.execute(pending_query).scalars().all()
                for pending in pending_samples:
                    logger.info(
                        "Sample %s (speaker %s) still processing — embedding inline before matching",
                        pending.id, pending.speaker_profile_id,
                    )
                    try:
                        audio_bytes = s3.download_bytes(pending.s3_key)
                        pending.embedding = embedder.encode(audio_bytes)
                        pending.status = "ready"
                        samples.append(pending)
                    except Exception as exc:
                        # Contain the failure to this one sample, matching the dedicated embedding
                        # handler (handlers/embedding.py) — the raced sample loses its shot at this
                        # job's matching, but the job itself must not fail over it.
                        logger.error(
                            "Inline embed failed for sample %s (speaker %s): %s",
                            pending.id, pending.speaker_profile_id, exc,
                        )
                        pending.status = "failed"
                        pending.error_message = str(exc)

            profile_ids = list({s.speaker_profile_id for s in samples})
            profile_result = session.execute(
                select(SpeakerProfile).where(SpeakerProfile.id.in_(profile_ids))
            )
            profile_id_to_name: dict[str, str] = {
                str(p.id): p.speaker_name for p in profile_result.scalars().all()
            }

            candidate_samples = [
                {
                    "speaker_profile_id": str(sample.speaker_profile_id),
                    "embedding": sample.embedding,
                }
                for sample in samples
            ]

        logger.info(
            "Loaded %d candidate sample(s) from DB (speaker_ids filter: %s)",
            len(candidate_samples), speaker_ids or "none (all ready samples)",
        )

        # Step 8: Embed and match each pyannote turn individually
        # turn_profile_ids[i]      — definite match profile_id (or None) for all_turns[i]
        # turn_probable_matches[i] — ProbableMatch (or None) when above threshold but best candidate
        turn_profile_ids: list[str | None] = []
        turn_probable_matches: list[ProbableMatch | None] = []
        turn_dist_rows: list[dict] = []
        logger.info("Embedding %d turn(s) individually", len(all_turns))
        for i, turn in enumerate(all_turns):
            _raise_if_aborted(abort)
            duration = turn["end"] - turn["start"]
            part = source_waveform[
                :,
                int(turn["start"] * source_sample_rate):int(turn["end"] * source_sample_rate),
            ]
            embedding = embedder.encode_tensor(part, source_sample_rate)
            if embedding is None:
                logger.info(
                    "Turn %d [%.3f - %.3f] %s (%.2fs): skipped (too short to embed)",
                    i, turn["start"], turn["end"], turn["speaker_label"], duration,
                )
                turn_profile_ids.append(None)
                turn_probable_matches.append(None)
                continue
            emb_norm = sum(x * x for x in embedding) ** 0.5
            logger.info(
                "Turn %d [%.3f - %.3f] %s (%.2fs): norm=%.4f",
                i, turn["start"], turn["end"], turn["speaker_label"], duration, emb_norm,
            )
            profile_id, candidate_dists, probable_match = match_speaker(embedding, candidate_samples, threshold=settings.MATCHING_THRESHOLD)
            turn_profile_ids.append(profile_id)
            turn_probable_matches.append(probable_match)
            matched_at = datetime.now(timezone.utc)
            if profile_id is None:
                if probable_match is not None:
                    prob_name = profile_id_to_name.get(probable_match.profile_id, probable_match.profile_id)
                    logger.info("  → PROBABLE %s (confidence=%.4f)", prob_name, probable_match.confidence)
                else:
                    logger.info("  → UNKNOWN (no match within threshold)")
            for cand_id, dist in candidate_dists.items():
                turn_dist_rows.append({
                    "job_id": job_id,
                    "candidate_id": uuid.UUID(cand_id),
                    "start_time": turn["start"],
                    "end_time": turn["end"],
                    "duration": duration,
                    "cosine_dist": dist,
                    "threshold": settings.MATCHING_THRESHOLD,
                    "text": turn_texts[i],
                    "occurred_at": matched_at,
                })

        logger.info(
            "Turn matching complete: %d matched, %d probable, %d unknown",
            sum(1 for p in turn_profile_ids if p is not None),
            sum(1 for p in turn_probable_matches if p is not None),
            sum(1 for p in turn_profile_ids if p is None),
        )
        _maybe_capture(job_id, "matcher", [
            {
                "start": t["start"],
                "end": t["end"],
                "speaker_profile_id": turn_profile_ids[i],
                "cosine_dist": next(
                    (r["cosine_dist"] for r in turn_dist_rows
                     if r["start_time"] == t["start"] and r["end_time"] == t["end"]),
                    None,
                ),
            }
            for i, t in enumerate(all_turns)
        ], settings.DEV_CAPTURE_FIXTURES_S3_PREFIX, s3)

        # Step 9: Write transcript_segments to DB
        matched_count = 0
        with get_session() as session:
            job = session.get(TranscriptionJob, job_id)
            for seg in segments:
                turn_idx = seg["turn_index"]
                if turn_idx == OVERLAP:
                    anon_label = "OVERLAP"
                    profile_id = None
                else:
                    profile_id_str = turn_profile_ids[turn_idx]
                    profile_id = uuid.UUID(profile_id_str) if profile_id_str else None
                    if profile_id:
                        anon_label = f"TURN_{turn_idx}"
                        matched_count += 1
                    else:
                        probable = turn_probable_matches[turn_idx]
                        if probable is not None:
                            prob_name = profile_id_to_name.get(probable.profile_id, probable.profile_id)
                            anon_label = f"PROBABLY_{prob_name}"
                        else:
                            anon_label = "UNKNOWN"
                db_segment = TranscriptSegment(
                    job_id=job_id,
                    speaker_profile_id=profile_id,
                    anonymous_label=anon_label,
                    start_time=seg["start_time"],
                    end_time=seg["end_time"],
                    text=seg["text"],
                )
                session.add(db_segment)
            session.add(TranscriptionJobEvent(
                job_id=job_id, source="worker", event="segments.inserted",
                detail={"count": len(segments)},
            ))

        # Write turn distance rows
        if turn_dist_rows:
            with get_session() as session:
                for row in turn_dist_rows:
                    session.add(TranscriptTurnDistance(**row))

        # Step 12: Update job to complete
        elapsed = time.time() - start_time
        matched_pct = (matched_count / len(segments) * 100) if segments else 0.0

        with get_session() as session:
            job = session.get(TranscriptionJob, job_id)
            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            job.matched_speaker_count = matched_count
            job.total_segment_count = len(segments)
            session.add(TranscriptionJobEvent(
                job_id=job_id, source="worker", event="job.complete",
                detail={"elapsed_seconds": round(elapsed, 1)},
            ))

        # Emit CloudWatch metrics
        _emit_metrics(settings, elapsed, matched_pct)
        logger.info(
            "Transcription job %s complete in %.1fs (matched %.0f%%)",
            job_id, elapsed, matched_pct,
        )

    except Interrupted:
        # Nothing has been written yet (segments land in step 9, after the last abort check), so
        # the redelivered message re-runs the job from the top.
        logger.warning("Transcription job %s interrupted by GPU release — back to transcribing", job_id)
        with get_session() as session:
            job = session.get(TranscriptionJob, job_id)
            if job:
                job.status = "transcribing"
                session.add(TranscriptionJobEvent(job_id=job_id, source="worker", event="job.interrupted"))
        raise
    except Exception as exc:
        step = "processing"
        error_msg = f"{step}: {type(exc).__name__}: {exc}"
        logger.error("ERROR Transcription job %s failed: %s", job_id, error_msg)
        with get_session() as session:
            job = session.get(TranscriptionJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = error_msg[:1000]
                session.add(TranscriptionJobEvent(
                    job_id=job_id, source="worker", event="job.failed",
                    detail={"error": error_msg[:200]},
                ))
        raise


def _emit_metrics(settings: Settings, elapsed_seconds: float, matched_pct: float) -> None:
    try:
        cloudwatch = boto3.client("cloudwatch", region_name=settings.AWS_REGION)
        cloudwatch.put_metric_data(
            Namespace="TranscriptionWorker",
            MetricData=[
                {
                    "MetricName": "TranscriptionJobDuration",
                    "Value": elapsed_seconds,
                    "Unit": "Seconds",
                },
                {
                    "MetricName": "SpeakerMatchSuccessRate",
                    "Value": matched_pct,
                    "Unit": "Percent",
                },
            ],
        )
    except Exception:
        logger.warning("Failed to emit CloudWatch metrics", exc_info=True)
