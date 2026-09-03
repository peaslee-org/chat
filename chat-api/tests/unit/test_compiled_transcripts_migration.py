"""The compiled_transcripts migration chains from the current head and imports cleanly."""
import importlib.util
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "versions"


def _load(name: str):
    path = next(VERSIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compiled_transcripts_migration_chains_from_is_public_flags():
    mod = _load("v2w3x4y5z6a7")
    assert mod.revision == "v2w3x4y5z6a7"
    assert mod.down_revision == "u1v2w3x4y5z6"
    assert callable(mod.upgrade) and callable(mod.downgrade)
