"""Runner: stderr → StageError, deadline → JobTimeout, spot notice → Interrupted; children are killed."""
import sys
import threading
from pathlib import Path

import pytest

from gpu_worker.sqs import Interrupted
from pipeline.runner import JobTimeout, Runner, StageError

PY = sys.executable


def make(deadline_in=3600, poll=0.05):
    ev = threading.Event()
    r = Runner(deadline=__import__("time").monotonic() + deadline_in, interrupted=ev, poll_seconds=poll)
    return r, ev


def test_success_returns_stdout(tmp_path):
    r, _ = make()
    out = r.run([PY, "-c", "print('hello')"], cwd=tmp_path, tool="py")
    assert out.strip() == "hello"


def test_nonzero_exit_raises_stage_error_with_first_stderr_line(tmp_path):
    r, _ = make()
    with pytest.raises(StageError) as e:
        r.run([PY, "-c", "import sys; print('', file=sys.stderr); print('bad thing', file=sys.stderr); print('more', file=sys.stderr); sys.exit(3)"], cwd=tmp_path, tool="colmap")
    assert str(e.value) == "bad thing" and e.value.tool == "colmap"


def test_deadline_kills_and_raises_job_timeout(tmp_path):
    r, _ = make(deadline_in=0.2)
    with pytest.raises(JobTimeout):
        r.run([PY, "-c", "import time; time.sleep(10)"], cwd=tmp_path)


def test_interrupt_kills_and_raises_interrupted(tmp_path):
    r, ev = make()
    threading.Timer(0.2, ev.set).start()
    with pytest.raises(Interrupted):
        r.run([PY, "-c", "import time; time.sleep(10)"], cwd=tmp_path)


def test_tool_defaults_to_command_name(tmp_path):
    r, _ = make()
    with pytest.raises(StageError) as e:
        r.run([PY, "-c", "import sys; sys.exit(1)"], cwd=tmp_path)
    assert e.value.tool == Path(PY).name
