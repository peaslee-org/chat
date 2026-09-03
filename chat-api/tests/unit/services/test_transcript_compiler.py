"""compile_turns must agree with chat-vue's computeTurns; both read the same fixture file."""
import json
from pathlib import Path

import pytest

from app.schemas.transcription import CompileSettings, CompiledTurn
from app.services.transcript_compiler import compile_turns

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "compile_turns_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_compile_turns_matches_fixture(case):
    out = compile_turns(case["turns"], CompileSettings(**case["settings"]))
    assert [t.model_dump() for t in out] == case["expected"]


def test_compiled_turn_rejects_unknown_match_type():
    with pytest.raises(ValueError):
        CompiledTurn(start_time=0, end_time=1, text="a", label="x", match_type="great")


def test_compile_settings_defaults_and_bounds():
    s = CompileSettings()
    assert (s.cosine_dist_threshold, s.separation_min, s.quality_min, s.confidence_min) == (0.25, 0.0, 0.0, 0.0)
    for bad in (
        {"cosine_dist_threshold": 0},
        {"cosine_dist_threshold": 2.01},
        {"separation_min": -0.1},
        {"quality_min": 1.1},
        {"confidence_min": 2},
    ):
        with pytest.raises(ValueError):
            CompileSettings(**bad)
