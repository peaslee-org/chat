"""The estimated_startup_seconds migration chains from the current head and imports cleanly."""
import importlib.util
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "versions"


def _load(name: str):
    path = next(VERSIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_startup_estimate_migration_chains_from_warnings():
    mod = _load("p6q7r8s9t0u1")
    assert mod.revision == "p6q7r8s9t0u1"
    assert mod.down_revision == "o5p6q7r8s9t0"
    assert callable(mod.upgrade) and callable(mod.downgrade)
