"""Unit tests for match_speaker.

No DB, audio, or model loading — uses synthetic float vectors.
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.matcher import match_speaker, ProbableMatch

DIM = 8  # small dimension; logic is identical to 192-dim


def unit(v: list[float]) -> list[float]:
    """L2-normalise a vector."""
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


# Distinct unit vectors for synthetic speakers
SPK_A = unit([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
SPK_B = unit([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
SPK_C = unit([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def sample(profile_id: str, embedding: list[float]) -> dict:
    return {"speaker_profile_id": profile_id, "embedding": embedding}


class TestMatchSpeaker:

    def test_exact_match_returns_profile_id(self):
        candidates = [sample("profile-a", SPK_A)]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-a"
        assert "profile-a" in dists

    def test_no_candidates_returns_none(self):
        result, dists, _probable = match_speaker(SPK_A, [], threshold=0.25)
        assert result is None
        assert dists == {}

    def test_above_threshold_returns_none(self):
        # SPK_A and SPK_B are orthogonal: cosine distance = 1.0 > 0.25
        candidates = [sample("profile-b", SPK_B)]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result is None
        assert "profile-b" in dists

    def test_picks_closest_of_multiple_candidates(self):
        # SPK_A is close to a slight perturbation of itself, far from SPK_B
        close_to_a = unit([0.99, 0.14, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        candidates = [
            sample("profile-a", close_to_a),
            sample("profile-b", SPK_B),
        ]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-a"
        assert set(dists) == {"profile-a", "profile-b"}

    def test_multiple_samples_averaged_per_speaker(self):
        """Two samples for the same speaker should be averaged before comparison."""
        # Two samples that average to something close to SPK_A
        s1 = unit([0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        s2 = unit([0.9, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        candidates = [
            sample("profile-a", s1),
            sample("profile-a", s2),
        ]
        # Average of s1 and s2 points along [1, 0, ...], matching SPK_A
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-a"
        assert "profile-a" in dists

    def test_threshold_boundary_included(self):
        # Cosine distance exactly at threshold should match
        # Build a vector whose cosine distance from SPK_A is exactly 0.25
        # cos(theta) = 1 - 0.25 = 0.75 → theta ~ 41.4°
        cos_theta = 0.75
        sin_theta = math.sqrt(1 - cos_theta ** 2)
        boundary = unit([cos_theta, sin_theta, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        candidates = [sample("profile-boundary", boundary)]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-boundary"

    def test_threshold_boundary_excluded(self):
        # Just over the threshold should not match
        cos_theta = 0.74  # distance ≈ 0.26 > 0.25
        sin_theta = math.sqrt(1 - cos_theta ** 2)
        over = unit([cos_theta, sin_theta, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        candidates = [sample("profile-over", over)]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result is None
        assert "profile-over" in dists

    def test_best_match_chosen_even_with_unmatched_candidates(self):
        """Returns the closest profile even when others exceed threshold."""
        close = unit([0.98, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        far = SPK_B  # orthogonal, distance = 1.0
        candidates = [
            sample("profile-close", close),
            sample("profile-far", far),
        ]
        result, dists, _probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-close"
        assert set(dists) == {"profile-close", "profile-far"}


class TestProbableMatch:
    """
    Tests for the probable-match signal returned when best candidate is above threshold
    but clearly better than the runner-up.

    Confidence = (1 - d_best/d_runner_up) × (threshold / d_best)

    Key examples:
      d_best=0.52, d_runner_up=0.93 → confidence ≈ 0.21  (clear winner, moderate confidence)
      d_best=0.95, d_runner_up=1.36 → confidence ≈ 0.08  (same delta, but both very far out)
    """

    # Vectors whose cosine distance from SPK_A is controlled by their first component:
    #   distance = 1 - v[0]  (since SPK_A = [1,0,...] and v is unit)
    # Use different off-axis dimensions so the two candidates don't interfere.
    _CLOSE_52 = unit([0.48,  0.8773, 0.0,    0.0, 0.0, 0.0, 0.0, 0.0])  # dist ≈ 0.52
    _FAR_93   = unit([0.07,  0.0,    0.9975,  0.0, 0.0, 0.0, 0.0, 0.0])  # dist ≈ 0.93
    _CLOSE_95 = unit([0.05,  0.9987, 0.0,    0.0, 0.0, 0.0, 0.0, 0.0])  # dist ≈ 0.95
    _FAR_136  = unit([-0.36, 0.0,    0.9330,  0.0, 0.0, 0.0, 0.0, 0.0])  # dist ≈ 1.36

    def test_probable_match_returned_when_above_threshold(self):
        """When best is above threshold but clearly better than runner-up, probable is set."""
        candidates = [
            sample("profile-close", self._CLOSE_52),
            sample("profile-far",   self._FAR_93),
        ]
        result, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result is None                         # no definite match
        assert probable is not None
        assert probable.profile_id == "profile-close"
        assert isinstance(probable.confidence, float)
        assert 0.0 < probable.confidence <= 1.0

    def test_52_vs_93_yields_meaningful_confidence(self):
        """
        d=0.52 vs d=0.93: best is 2× closer to threshold — confidence should be
        reasonably high (>0.15) to signal a likely match.
        """
        candidates = [
            sample("profile-close", self._CLOSE_52),
            sample("profile-far",   self._FAR_93),
        ]
        _, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert probable is not None
        assert probable.confidence > 0.15

    def test_95_vs_136_yields_low_confidence(self):
        """
        d=0.95 vs d=1.36: same absolute delta as above but both candidates are far
        from threshold — confidence should be noticeably lower (<0.15).
        """
        candidates = [
            sample("profile-close", self._CLOSE_95),
            sample("profile-far",   self._FAR_136),
        ]
        _, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert probable is not None
        assert probable.confidence < 0.15

    def test_52_vs_93_confidence_higher_than_95_vs_136(self):
        """Confidence correctly ranks the two scenarios against each other."""
        _, _, probable_high = match_speaker(
            SPK_A,
            [sample("profile-close", self._CLOSE_52), sample("profile-far", self._FAR_93)],
            threshold=0.25,
        )
        _, _, probable_low = match_speaker(
            SPK_A,
            [sample("profile-close", self._CLOSE_95), sample("profile-far", self._FAR_136)],
            threshold=0.25,
        )
        assert probable_high is not None and probable_low is not None
        assert probable_high.confidence > probable_low.confidence

    def test_no_probable_match_on_definite_match(self):
        """A definite match (dist ≤ threshold) must not also produce a probable match."""
        candidates = [
            sample("profile-a", SPK_A),
            sample("profile-b", SPK_B),
        ]
        result, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result == "profile-a"
        assert probable is None

    def test_no_probable_match_with_single_candidate(self):
        """Can't establish relative advantage with only one candidate above threshold."""
        candidates = [sample("profile-b", SPK_B)]  # dist = 1.0 > 0.25
        result, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert result is None
        assert probable is None

    def test_no_probable_match_with_no_candidates(self):
        result, dists, probable = match_speaker(SPK_A, [], threshold=0.25)
        assert result is None
        assert dists == {}
        assert probable is None

    def test_probable_match_identifies_best_of_three(self):
        """With three candidates all above threshold, probable points to the closest."""
        candidates = [
            sample("profile-close", self._CLOSE_52),
            sample("profile-mid",   self._FAR_93),
            sample("profile-far",   SPK_B),   # dist = 1.0
        ]
        _, _dists, probable = match_speaker(SPK_A, candidates, threshold=0.25)
        assert probable is not None
        assert probable.profile_id == "profile-close"
