"""constraints.txt must pin every package the Dockerfile installs, with exact versions only —
it exists so a rebuild reproduces the image that passed acceptance (speechbrain drifted to 1.1.1
on an unpinned rebuild, 2026-08-28)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints.txt"
DOCKERFILE = ROOT / "Dockerfile"
PYPROJECT = ROOT / "pyproject.toml"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins() -> dict[str, str]:
    pins = {}
    for line in CONSTRAINTS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==(\S+)", line)
        assert m, f"not an exact pin: {line!r}"
        pins[_norm(m.group(1))] = m.group(2)
    return pins


def _pip_install_lines() -> list[str]:
    return [m.group(1) for m in re.finditer(r"RUN pip install (.+)", DOCKERFILE.read_text())]


def _dockerfile_packages() -> set[str]:
    names = set()
    for line in _pip_install_lines():
        for tok in line.split():
            tok = tok.strip('"')
            if tok.startswith(("-", "/")):
                continue
            names.add(_norm(re.split(r"[=<>\[]", tok)[0]))
    return names


def _pyproject_packages() -> set[str]:
    # regex rather than tomllib: the transcription venv still runs Python 3.10 locally
    block = re.search(r"^dependencies = \[(.*?)^\]", PYPROJECT.read_text(), re.S | re.M).group(1)
    return {_norm(d) for d in re.findall(r'"([A-Za-z0-9_.\-]+)', block)} - {"gpu-worker"}


def test_every_pip_install_uses_constraints():
    for line in _pip_install_lines():
        assert "-c /app/constraints.txt" in line, line


def test_dockerfile_packages_are_pinned():
    missing = _dockerfile_packages() - _pins().keys()
    assert not missing, f"installed by the Dockerfile but not pinned: {sorted(missing)}"


def test_pyproject_packages_are_pinned():
    missing = _pyproject_packages() - _pins().keys()
    assert not missing, f"declared in pyproject but not pinned: {sorted(missing)}"


def test_inline_dockerfile_pins_agree_with_constraints():
    pins = _pins()
    for name, ver in re.findall(r'"([A-Za-z0-9_.\-]+)==([^"]+)"', DOCKERFILE.read_text()):
        assert pins[_norm(name)] == ver, f"{name}: Dockerfile says {ver}, constraints say {pins[_norm(name)]}"


def test_botocore_is_declared_not_just_transitive():
    """handlers/photogrammetry.py imports botocore.exceptions directly."""
    assert "botocore" in _pyproject_packages()
