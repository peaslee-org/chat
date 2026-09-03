"""Turn a job's per-turn candidate distances into a labelled transcript.

`compile_turns` is a line-for-line port of `computeTurns` in
chat-vue/src/composables/useMatchingThresholds.ts. Both are tested against
chat-api/tests/fixtures/compile_turns_cases.json — change one, change both.
"""
from app.schemas.transcription import CompiledTurn, CompileSettings


def compile_turns(turns: list[dict], settings: CompileSettings) -> list[CompiledTurn]:
    out: list[CompiledTurn] = []
    for turn in turns:
        base = {"start_time": turn["start_time"], "end_time": turn["end_time"], "text": turn["text"]}
        ranked = sorted(turn["candidates"], key=lambda c: c["cosine_dist"])
        if not ranked:
            out.append(CompiledTurn(**base, label="Unknown", match_type="none"))
            continue
        best = ranked[0]
        name = best["speaker_name"] or "Unknown"
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
