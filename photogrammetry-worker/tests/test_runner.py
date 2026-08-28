"""Runner: stderr → StageError, deadline → JobTimeout, spot notice → Interrupted; children are killed."""
import logging
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gpu_worker.sqs import Interrupted
from pipeline.runner import JobTimeout, Runner, StageError

PY = sys.executable


def make(deadline_in=3600, poll=0.05):
    ev = threading.Event()
    r = Runner(deadline=__import__("time").monotonic() + deadline_in, interrupted=ev, poll_seconds=poll)
    return r, ev


def test_success_returns_combined_output(tmp_path):
    r, _ = make()
    out = r.run(
        [PY, "-c", "import sys; print('hello'); print('world', file=sys.stderr)"],
        cwd=tmp_path,
        tool="py",
    )
    assert "hello" in out
    assert "world" in out


def test_nonzero_exit_raises_stage_error_with_last_stderr_line(tmp_path):
    r, _ = make()
    with pytest.raises(StageError) as e:
        r.run([PY, "-c", "import sys; print('', file=sys.stderr); print('bad thing', file=sys.stderr); print('more', file=sys.stderr); sys.exit(3)"], cwd=tmp_path, tool="colmap")
    assert str(e.value) == "more" and e.value.tool == "colmap"
    assert "bad thing" in e.value.output


def test_stage_error_prefers_last_glog_error_line_and_strips_prefix(tmp_path):
    from pipeline.runner import summarize_stderr
    glog = ("I20260828 10:26:10.751535   473 incremental_pipeline.cc:323] Loading database\n"
            "I20260828 10:26:11.240109   473 incremental_pipeline.cc:439] => No good initial image pair found.\n"
            "E20260828 10:26:11.240190   473 sfm.cc:288] Failed to create any sparse model\n"
            "I20260828 10:26:11.240200   473 sfm.cc:300] Elapsed time: 0.5 [minutes]\n")
    assert summarize_stderr(glog, "x") == "Failed to create any sparse model"
    assert summarize_stderr("", "colmap mapper exited with 1") == "colmap mapper exited with 1"


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


def test_success_logs_tool_and_output_tail(tmp_path, caplog):
    r, _ = make()
    with caplog.at_level(logging.INFO):
        r.run([PY, "-c", "print('hello')"], cwd=tmp_path, tool="colmap mapper")
    ok_records = [rec for rec in caplog.records if "ok" in rec.getMessage()]
    assert any("colmap mapper" in rec.getMessage() and "hello" in rec.getMessage() for rec in ok_records)


def test_kill_logs_when_child_does_not_reap(caplog):
    proc = MagicMock()
    proc.pid = 4242
    proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="stuck", timeout=10)
    with caplog.at_level(logging.WARNING):
        Runner._kill(proc)
    assert any("4242" in record.getMessage() for record in caplog.records)
