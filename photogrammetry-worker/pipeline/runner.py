"""Subprocess runner with a job deadline and a spot-interruption watch.

Every reconstruction tool runs through here so the handler can be read as a stage table.
"""
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from gpu_worker.sqs import Interrupted

logger = logging.getLogger(__name__)


class StageError(Exception):
    def __init__(self, tool: str, message: str, output: str = ""):
        super().__init__(message)
        self.tool = tool
        self.output = output  # the tool's stderr, for callers that recognise specific failures


_GLOG_PREFIX = re.compile(r"^[IWEF]\d{8} [\d:.]+\s+\d+ [^\]]*\] ")


def summarize_stderr(stderr: str, fallback: str) -> str:
    """One human-facing line from a tool's stderr: the last glog ERROR line if there is one, else the
    last non-empty line, glog prefixes stripped. COLMAP logs progress at INFO from the first line
    ("Loading database"), so the first line is never the reason (acceptance 7.3, 2026-08-28)."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return fallback
    errors = [line for line in lines if re.match(r"^E\d{8} ", line)]
    return _GLOG_PREFIX.sub("", (errors or lines)[-1])[:1000]


class JobTimeout(StageError):
    pass


class Released(Interrupted):
    """Immediate admin release: the child was killed; the message goes back to the queue
    (all Interrupted handling applies) and the next worker — on the current task-definition
    revision — retries the job."""


class Runner:
    def __init__(self, deadline: float, interrupted: threading.Event, clock=time.monotonic, poll_seconds: float = 5.0,
                 timeout_message: str = "Reconstruction exceeded 60 minutes", released: threading.Event | None = None):
        self._deadline = deadline
        self._interrupted = interrupted
        self._released = released or threading.Event()
        self._clock = clock
        self._poll = poll_seconds
        self._timeout_message = timeout_message

    def run(self, cmd: list[str], cwd: Path, tool: str | None = None) -> str:
        """Run `cmd`, returning combined stdout+stderr text.

        COLMAP (>= 3.9, glog) writes its progress — including the `Registered images:`
        line `pipeline/colmap.py` greps for — to stderr, not stdout. Callers that need
        tool output must not assume it lands on one stream or the other.
        """
        tool = tool or Path(cmd[0]).name
        logger.info("[%s] %s", tool, " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=self._poll)
                break
            except subprocess.TimeoutExpired:
                if self._released.is_set():
                    self._kill(proc)
                    raise Released()
                if self._interrupted.is_set():
                    self._kill(proc)
                    raise Interrupted()
                if self._clock() >= self._deadline:
                    self._kill(proc)
                    raise JobTimeout(tool, self._timeout_message)
        if proc.returncode != 0:
            logger.error("[%s] failed (%s):\n%s", tool, proc.returncode, stderr[-4000:])
            raise StageError(tool, summarize_stderr(stderr, f"{tool} exited with {proc.returncode}"), stderr)
        combined = stdout + stderr
        logger.info("[%s] ok\n%s", tool, combined[-4000:])
        return combined

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Killed child pid %s did not exit within 10 s — leaving it for the OS", proc.pid)
