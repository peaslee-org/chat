"""Turn a job's per-turn candidate distances into a labelled transcript.

`compile_turns` is a line-for-line port of `computeTurns` in
chat-vue/src/composables/useMatchingThresholds.ts. Both are tested against
chat-api/tests/fixtures/compile_turns_cases.json — change one, change both.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.schemas.transcription import CompiledTurn, CompileSettings, SegmentResponse, TranscriptResponse


def compile_turns(turns: list[dict], settings: CompileSettings) -> list[CompiledTurn]:
    out: list[CompiledTurn] = []
    for turn in turns:
        base = {"start_time": turn["start_time"], "end_time": turn["end_time"], "text": turn["text"]}
        ranked = sorted(turn["candidates"], key=lambda c: c["cosine_dist"])
        if not ranked:
            out.append(CompiledTurn(**base, label="Unknown", match_type="none"))
            continue
        best = ranked[0]
        name = best["speaker_name"] if best["speaker_name"] is not None else "Unknown"
        if best["cosine_dist"] <= settings.cosine_dist_threshold:
            out.append(CompiledTurn(**base, label=name, match_type="high"))
            continue
        if len(ranked) >= 2 and ranked[1]["cosine_dist"] > best["cosine_dist"]:
            separation = 1 - best["cosine_dist"] / ranked[1]["cosine_dist"]
            quality = settings.cosine_dist_threshold / best["cosine_dist"]
            confidence = separation * quality
            if (
                separation >= settings.separation_min
                and quality >= settings.quality_min
                and confidence >= settings.confidence_min
            ):
                out.append(CompiledTurn(**base, label=name, match_type="medium"))
                continue
            if separation >= settings.separation_min:
                out.append(CompiledTurn(**base, label=name, match_type="low"))
                continue
        out.append(CompiledTurn(**base, label="Unknown", match_type="none"))
    return out


def compile_defaults(settings) -> CompileSettings:
    return CompileSettings(
        cosine_dist_threshold=settings.compile_cosine_dist_threshold,
        separation_min=settings.compile_separation_min,
        quality_min=settings.compile_quality_min,
        confidence_min=settings.compile_confidence_min,
    )


def group_turn_distances(rows) -> list[dict]:
    """(TranscriptTurnDistance, speaker_name) rows → one dict per turn with its candidates,
    in start-time order. The same shape TurnDistanceResponse serialises to."""
    turns: dict[tuple, dict] = {}
    for td, speaker_name in rows:
        key = (td.start_time, td.end_time)
        if key not in turns:
            turns[key] = {"start_time": td.start_time, "end_time": td.end_time, "text": td.text, "candidates": []}
        turns[key]["candidates"].append(
            {"candidate_id": td.candidate_id, "speaker_name": speaker_name, "cosine_dist": td.cosine_dist}
        )
    return list(turns.values())


async def load_or_compile(repo, job_id: UUID, defaults: CompileSettings, *, force: Optional[CompileSettings] = None):
    """The job's compiled transcript row. With `force`, always recompile with those settings;
    otherwise return the stored row, compiling with `defaults` on first read.
    None when the job has no turn-distance rows. Caller commits."""
    if force is None:
        row = await repo.get_compiled_transcript(job_id)
        if row is not None:
            return row
    grouped = group_turn_distances(await repo.get_turn_distances(job_id))
    if not grouped:
        return None
    settings = force or defaults
    turns = [t.model_dump() for t in compile_turns(grouped, settings)]
    return await repo.upsert_compiled_transcript(
        job_id=job_id, settings=settings.model_dump(), turns=turns, compiled_at=datetime.now(timezone.utc)
    )


def transcript_response(segments: list[SegmentResponse], compiled, defaults: CompileSettings) -> TranscriptResponse:
    if compiled is None:
        return TranscriptResponse(segments=segments, turns=None, settings=defaults, compiled_at=None)
    return TranscriptResponse(
        segments=segments,
        turns=[CompiledTurn(**t) for t in compiled.turns],
        settings=CompileSettings(**compiled.settings),
        compiled_at=compiled.compiled_at,
    )
