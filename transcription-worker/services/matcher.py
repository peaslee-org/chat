import logging
from dataclasses import dataclass

from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)


@dataclass
class ProbableMatch:
    """
    A speaker match that is above the hard threshold but still the clear best candidate.

    confidence is the product of two factors:
      - separation  = 1 - (best_dist / runner_up_dist)  — how much better best is vs runner-up
      - quality     = threshold / best_dist              — how far best is above threshold

    Example: threshold=0.25, best=0.52, runner_up=0.93 → confidence ≈ 0.21
             threshold=0.25, best=0.95, runner_up=1.36 → confidence ≈ 0.08
    """
    profile_id: str
    confidence: float  # 0.0–1.0


def match_speaker(
    segment_embedding: list[float],
    candidate_samples: list[dict],  # each: {speaker_profile_id, embedding}
    threshold: float = 0.25,
) -> tuple[str | None, dict[str, float], ProbableMatch | None]:
    """
    Returns (matched_profile_id | None, {profile_id: cosine_dist}, probable_match | None).

    matched_profile_id: closest profile if cosine distance <= threshold, else None.
    probable_match: set when best is above threshold but clearly better than runner-up;
                    None when there is a definite match, only one candidate, or the
                    separation/quality signal is zero.
    Uses per-speaker average of all ready sample embeddings.
    """
    if not candidate_samples:
        logger.warning("match_speaker called with no candidate samples")
        return None, {}, None

    # Group embeddings by speaker_profile_id and average them
    speaker_embeddings: dict[str, list[list[float]]] = {}
    for sample in candidate_samples:
        spk_id = str(sample["speaker_profile_id"])
        speaker_embeddings.setdefault(spk_id, []).append(sample["embedding"])

    best_id, best_dist = None, float("inf")
    candidate_dists: dict[str, float] = {}
    for spk_id, embeddings in speaker_embeddings.items():
        # Average all embeddings for this speaker
        n = len(embeddings)
        avg = [sum(e[i] for e in embeddings) / n for i in range(len(embeddings[0]))]
        dist = float(cosine(segment_embedding, avg))
        candidate_dists[spk_id] = dist
        logger.info(
            "  candidate %s (%d sample(s)): cosine_dist=%.4f threshold=%.4f %s",
            spk_id, n, dist, threshold, "MATCH" if dist <= threshold else "no match",
        )
        if dist < best_dist:
            best_dist, best_id = dist, spk_id

    matched = best_id is not None and best_dist <= threshold
    logger.info(
        "match_speaker result: best=%s dist=%.4f -> %s",
        best_id, best_dist, "MATCHED" if matched else "UNMATCHED",
    )

    if matched:
        return best_id, candidate_dists, None

    # Compute a probable match when best is above threshold and there are ≥2 candidates.
    # confidence = separation × quality
    #   separation = 1 - best_dist / runner_up_dist  (0 if tied, →1 as gap widens)
    #   quality    = threshold / best_dist            (1 at threshold, →0 as dist grows)
    probable: ProbableMatch | None = None
    if best_id is not None and len(candidate_dists) >= 2:
        runner_up_dist = min(d for spk, d in candidate_dists.items() if spk != best_id)
        if runner_up_dist > best_dist:
            separation = 1.0 - best_dist / runner_up_dist
            quality = threshold / best_dist
            confidence = round(separation * quality, 4)
            probable = ProbableMatch(profile_id=best_id, confidence=confidence)
            logger.info(
                "  probable match: %s confidence=%.4f (separation=%.4f quality=%.4f)",
                best_id, confidence, separation, quality,
            )

    return None, candidate_dists, probable
