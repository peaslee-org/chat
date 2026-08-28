"""Admin release: poll this worker's gpu_sessions row for release_mode and raise the flags.

`released` ends the WorkerLoop between messages (graceful). `abort` additionally tells a
job runner to kill the running child (immediate); the message returns to the queue and the
next worker — on the current task-definition revision — retries it.
"""
import logging
import threading

logger = logging.getLogger(__name__)

_POLL_SECONDS = 10.0


class ReleaseWatcher:
    # Process-wide, like SpotWatcher.interrupted: WorkerLoop reads `released`; job runners read `abort`.
    released = threading.Event()
    abort = threading.Event()

    def __init__(self, sessions, *, released: threading.Event | None = None, abort: threading.Event | None = None,
                 poll_seconds: float = _POLL_SECONDS):
        self._sessions = sessions
        self._released = released if released is not None else ReleaseWatcher.released
        self._abort = abort if abort is not None else ReleaseWatcher.abort
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            mode = self._sessions.release_mode()
            if mode is None:
                continue
            logger.warning("Admin release requested (%s) — exiting %s", mode,
                           "now" if mode == "immediate" else "after the current job")
            if mode == "immediate":
                self._abort.set()
            self._released.set()
            return
