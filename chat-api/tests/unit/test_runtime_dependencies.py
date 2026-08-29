"""Modules imported by app/ must be runtime dependencies — the image installs with --no-dev
(no extras), so a package that only lives in the `dev` extra is missing in production.
(Pillow was, 2026-08-29: chat-api-prod:83 crash-looped on `No module named 'PIL'`.)"""
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _base_dependency_names() -> set[str]:
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    return {d.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower() for d in deps}


def test_pillow_is_a_runtime_dependency():
    assert "pillow" in _base_dependency_names()
