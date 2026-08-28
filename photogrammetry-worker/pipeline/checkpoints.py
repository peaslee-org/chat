"""Stage markers in a job's scratch directory.

`<stage>.done` (JSON) means the stage finished and its outputs are on disk; `stage.started` names
the stage currently running. A `stage.started` with no matching `.done` on the next receipt means
the previous attempt died inside that stage without a handshake — the handler fails the job
instead of running it again (spec §2). Interrupted/released jobs clear `stage.started` first.
"""
import json
import os
import shutil
import time
from pathlib import Path

STAGES = ("sfm", "dense", "mesh", "texture", "publish")
_STARTED = "stage.started"


def _write_atomic(path: Path, text: str) -> None:
    """Write text to path atomically via a temporary file and os.replace()."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class Checkpoints:
    def __init__(self, work: Path):
        self._work = work

    def started(self, stage: str) -> None:
        self._work.mkdir(parents=True, exist_ok=True)
        _write_atomic(self._work / _STARTED, stage)

    def done(self, stage: str, **data) -> None:
        self._work.mkdir(parents=True, exist_ok=True)
        _write_atomic(self._work / f"{stage}.done", json.dumps(data))
        self.clear_started()

    def completed(self, stage: str) -> dict | None:
        p = self._work / f"{stage}.done"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            # Marker file is corrupt or unreadable; treat as not done and let it re-run.
            return None

    def crashed_stage(self) -> str | None:
        p = self._work / _STARTED
        if not p.exists():
            return None
        stage = p.read_text().strip()
        # Treat empty/whitespace-only stage name as not a crash.
        if not stage:
            return None
        return None if self.completed(stage) is not None else stage

    def clear_started(self) -> None:
        (self._work / _STARTED).unlink(missing_ok=True)

    def first_incomplete(self) -> str:
        for stage in STAGES:
            if self.completed(stage) is None:
                return stage
        return STAGES[-1]


def sweep_stale(root: Path, max_age_seconds: int = 86_400, now: float | None = None) -> list[Path]:
    """Delete job directories under `root` whose newest file is older than `max_age_seconds`."""
    now = time.time() if now is None else now
    removed = []
    if not root.exists():
        return removed
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            newest = max([d.stat().st_mtime] + [f.stat().st_mtime for f in d.rglob("*")])
        except OSError:
            # A file vanished mid-walk (e.g. a race with another cleanup) — skip this dir rather
            # than let the sweep die and take the rest of the (harmless) job dirs with it.
            continue
        if now - newest > max_age_seconds:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d)
    return removed
