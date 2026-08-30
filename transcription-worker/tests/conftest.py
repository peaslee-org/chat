"""Host-side test setup: the ML stack (torch, torchaudio, speechbrain, pyannote) and `config` /
`db` (which builds an engine from Settings at import) do not exist outside the worker image.
Stub whatever is missing in sys.modules *before* any test module is collected, so collection
order cannot matter. Test modules read HAS_TORCH / HAS_FULL_STACK from here to skip what needs
the real thing."""
import importlib.util
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_FULL_STACK = HAS_TORCH and importlib.util.find_spec("torchaudio") is not None

_MISSING_ROOTS = {
    pkg for pkg in ["torch", "torchaudio", "speechbrain", "pyannote", "config"]
    if importlib.util.find_spec(pkg) is None
}
for _stub in [
    "torch", "torchaudio", "torchaudio.transforms",
    "speechbrain", "speechbrain.pretrained",
    "pyannote", "pyannote.audio", "config",
]:
    if _stub.split(".")[0] in _MISSING_ROOTS:
        sys.modules.setdefault(_stub, MagicMock())
sys.modules.setdefault("db", MagicMock())
