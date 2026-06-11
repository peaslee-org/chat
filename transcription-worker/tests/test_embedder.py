"""Unit tests for EcapaTdnnEmbedder and _l2_normalize.

_l2_normalize tests run anywhere (only stdlib math needed).
encode_tensor tests require torch and are skipped when it is absent —
they run inside the Docker worker image where torch/torchaudio are installed.
"""
import importlib.util
import math
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Pre-compute which root packages are missing before any stubbing touches sys.modules.
# encode_tensor tests need both torch and torchaudio.
_HAS_TORCH = importlib.util.find_spec("torch") is not None
_HAS_FULL_STACK = _HAS_TORCH and importlib.util.find_spec("torchaudio") is not None

# Stub missing ML deps so services/embedder.py can be imported on the host.
# _l2_normalize only uses `math`, so it works fine through the stubs.
_MISSING_ROOTS = {
    pkg for pkg in ["torch", "torchaudio", "speechbrain", "config"]
    if importlib.util.find_spec(pkg) is None
}
for _stub in [
    "torch", "torchaudio", "torchaudio.transforms",
    "speechbrain", "speechbrain.pretrained", "config",
]:
    if _stub.split(".")[0] in _MISSING_ROOTS:
        sys.modules.setdefault(_stub, MagicMock())

if _HAS_TORCH:
    import torch

from services.embedder import _l2_normalize, EcapaTdnnEmbedder


# ---------------------------------------------------------------------------
# _l2_normalize — pure stdlib, runs everywhere
# ---------------------------------------------------------------------------

class TestL2Normalize:

    def test_unit_vector_unchanged(self):
        v = [1.0, 0.0, 0.0]
        result = _l2_normalize(v)
        assert abs(math.sqrt(sum(x * x for x in result)) - 1.0) < 1e-6

    def test_scales_to_unit_norm(self):
        v = [3.0, 4.0]  # norm = 5
        result = _l2_normalize(v)
        assert abs(result[0] - 0.6) < 1e-6
        assert abs(result[1] - 0.8) < 1e-6

    def test_large_norm_becomes_unit(self):
        # Mirrors the high-norm embeddings seen in production (norm ~315)
        v = [100.0] * 192
        result = _l2_normalize(v)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6

    def test_zero_vector_returned_unchanged(self):
        v = [0.0, 0.0, 0.0]
        result = _l2_normalize(v)
        assert result == [0.0, 0.0, 0.0]

    def test_negative_values_preserved_in_direction(self):
        v = [-3.0, 4.0]  # norm = 5
        result = _l2_normalize(v)
        assert abs(result[0] - (-0.6)) < 1e-6
        assert abs(result[1] - 0.8) < 1e-6


# ---------------------------------------------------------------------------
# encode_tensor — requires real torch; skipped on host, runs in Docker
# ---------------------------------------------------------------------------

def _make_embedder(raw_output) -> EcapaTdnnEmbedder:
    """Construct an embedder whose model returns raw_output from encode_batch."""
    embedder = object.__new__(EcapaTdnnEmbedder)
    mock_model = MagicMock()
    mock_model.encode_batch.return_value = raw_output
    embedder.model = mock_model
    return embedder


@pytest.mark.skipif(not _HAS_FULL_STACK, reason="torch+torchaudio not installed")
class TestEncodeNormalization:
    """encode_tensor must always return a unit-norm vector regardless of raw model output."""

    def test_unit_norm_output_for_large_raw_embedding(self):
        # Simulate the ~315-norm raw embeddings seen in production
        raw = torch.full((1, 1, 192), 5.0)
        result = _make_embedder(raw).encode_tensor(torch.randn(1, 16000), sample_rate=16000)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6

    def test_output_dimension_is_192(self):
        raw = torch.randn(1, 1, 192)
        result = _make_embedder(raw).encode_tensor(torch.randn(1, 16000), sample_rate=16000)
        assert len(result) == 192

    def test_same_input_same_output(self):
        raw = torch.tensor([[[1.0, 2.0, 3.0]]])
        embedder = _make_embedder(raw)
        waveform = torch.randn(1, 16000)
        assert embedder.encode_tensor(waveform, 16000) == embedder.encode_tensor(waveform, 16000)

    def test_stereo_averaged_to_mono_before_model(self):
        raw = torch.randn(1, 1, 192)
        embedder = _make_embedder(raw)
        stereo = torch.randn(2, 16000)
        embedder.encode_tensor(stereo, sample_rate=16000)
        called = embedder.model.encode_batch.call_args[0][0]
        assert called.shape[0] == 1  # mono (batch=1)

    def test_resampling_applied_for_non_16k_audio(self):
        raw = torch.randn(1, 1, 192)
        embedder = _make_embedder(raw)
        waveform_44k = torch.randn(1, 44100)
        embedder.encode_tensor(waveform_44k, sample_rate=44100)
        called = embedder.model.encode_batch.call_args[0][0]
        # Resampled from 44100 → 16000; allow a few samples of rounding
        assert abs(called.shape[-1] - 16000) < 50

    def test_distinct_raw_outputs_produce_distinct_embeddings(self):
        raw_a = torch.tensor([[[1.0, 0.0, 0.0]]])
        raw_b = torch.tensor([[[0.0, 1.0, 0.0]]])
        emb_a = _make_embedder(raw_a).encode_tensor(torch.randn(1, 16000), 16000)
        emb_b = _make_embedder(raw_b).encode_tensor(torch.randn(1, 16000), 16000)
        assert emb_a != emb_b
