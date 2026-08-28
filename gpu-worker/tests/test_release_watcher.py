"""ReleaseWatcher polls the session row's release_mode and raises the matching flags."""
import threading

from gpu_worker.release_watcher import ReleaseWatcher


class FakeStore:
    def __init__(self, modes):
        self._modes = list(modes)

    def release_mode(self):
        return self._modes.pop(0) if self._modes else None


def test_graceful_sets_released_only():
    released, abort = threading.Event(), threading.Event()
    w = ReleaseWatcher(FakeStore([None, "graceful"]), released=released, abort=abort, poll_seconds=0.01)
    w.start()
    assert released.wait(1.0)
    assert not abort.is_set()
    w.stop()


def test_immediate_sets_both_flags():
    released, abort = threading.Event(), threading.Event()
    w = ReleaseWatcher(FakeStore(["immediate"]), released=released, abort=abort, poll_seconds=0.01)
    w.start()
    assert released.wait(1.0) and abort.wait(1.0)
    w.stop()


def test_no_release_leaves_flags_clear():
    released, abort = threading.Event(), threading.Event()
    w = ReleaseWatcher(FakeStore([None, None, None]), released=released, abort=abort, poll_seconds=0.01)
    w.start()
    assert not released.wait(0.1)
    w.stop()
