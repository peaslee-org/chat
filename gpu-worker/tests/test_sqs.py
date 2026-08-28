"""run_sqs_worker: dispatch by body.type, delete only on success, never on Interrupted."""
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from gpu_worker.sqs import Interrupted, run_sqs_worker


class FakeStore:
    def __init__(self):
        self.calls = []
    def claim(self): self.calls.append("claim")
    def heartbeat(self): self.calls.append("heartbeat")
    def warm_until(self): return None
    def close(self, end_reason): self.calls.append(("close", end_reason))


class FakeWatcher:
    interrupted = threading.Event()
    def __init__(self, *a, **k): pass
    @classmethod
    def idle_watcher(cls, region): return cls()
    def start(self): pass
    def stop(self): pass


def make_sqs(bodies):
    """Serve each body once, then empty polls forever."""
    sqs = MagicMock()
    queue = [[{"Body": json.dumps(b), "ReceiptHandle": f"rh-{i}"}] for i, b in enumerate(bodies)]
    sqs.receive_message.side_effect = lambda **kw: {"Messages": queue.pop(0)} if queue else {}
    return sqs


def run(bodies, handlers, idle_exit_seconds=0):
    FakeWatcher.interrupted.clear()
    sqs = make_sqs(bodies)
    store = FakeStore()
    reason = run_sqs_worker(
        queue_url="https://sqs.test/q", region="us-east-1", handlers=handlers,
        session_store=store, idle_exit_seconds=idle_exit_seconds, max_lifetime_seconds=10800,
        sqs_client=sqs, watcher_factory=FakeWatcher, idle_watcher_factory=FakeWatcher.idle_watcher,
    )
    return reason, sqs, store


def test_dispatches_by_type_and_deletes_on_success():
    seen = []
    reason, sqs, store = run([{"type": "a", "x": 1}], {"a": lambda body, msg: seen.append(body)})
    assert seen == [{"type": "a", "x": 1}]
    sqs.delete_message.assert_called_once()
    assert sqs.delete_message.call_args.kwargs["ReceiptHandle"] == "rh-0"
    assert reason == "idle" and store.calls[0] == "claim" and ("close", "idle") in store.calls


def test_handler_exception_leaves_message_for_retry():
    def boom(body, msg): raise RuntimeError("x")
    _, sqs, _ = run([{"type": "a"}], {"a": boom})
    sqs.delete_message.assert_not_called()


def test_interrupted_leaves_message_and_exits():
    def interrupt(body, msg):
        FakeWatcher.interrupted.set()
        raise Interrupted()
    reason, sqs, _ = run([{"type": "a"}, {"type": "a"}], {"a": interrupt}, idle_exit_seconds=900)
    sqs.delete_message.assert_not_called()
    assert reason == "spot_interruption"
    assert sqs.receive_message.call_count == 1   # exited before the second message


def test_unknown_type_is_not_deleted():
    _, sqs, _ = run([{"type": "nope"}], {"a": lambda b, m: None})
    sqs.delete_message.assert_not_called()


def test_receive_uses_long_poll_of_one():
    _, sqs, _ = run([], {})
    kw = sqs.receive_message.call_args.kwargs
    assert kw["MaxNumberOfMessages"] == 1 and kw["WaitTimeSeconds"] == 20


def test_extender_extends_visibility_while_handler_runs():
    FakeWatcher.interrupted.clear()
    sqs = make_sqs([{"type": "a"}])
    store = FakeStore()

    def slow(body, msg):
        time.sleep(0.08)

    run_sqs_worker(
        queue_url="https://sqs.test/q", region="us-east-1", handlers={"a": slow},
        session_store=store, idle_exit_seconds=0, max_lifetime_seconds=10800,
        visibility_timeout=123, visibility_extension_interval=0.01,
        sqs_client=sqs, watcher_factory=FakeWatcher, idle_watcher_factory=FakeWatcher.idle_watcher,
    )

    sqs.change_message_visibility.assert_any_call(
        QueueUrl="https://sqs.test/q", ReceiptHandle="rh-0", VisibilityTimeout=123
    )
    assert sqs.change_message_visibility.call_count >= 1

    call_count_after_return = sqs.change_message_visibility.call_count
    time.sleep(0.05)
    assert sqs.change_message_visibility.call_count == call_count_after_return


def test_release_watcher_flag_ends_loop_with_released():
    from gpu_worker.release_watcher import ReleaseWatcher

    class FakeRelease:
        def __init__(self, store): self.store = store
        def start(self): ReleaseWatcher.released.set()     # as if the row said release_mode='graceful'
        def stop(self): pass

    ReleaseWatcher.released.clear(); ReleaseWatcher.abort.clear()
    sqs = make_sqs([])
    store = FakeStore()
    reason = run_sqs_worker(
        queue_url="https://sqs.test/q", region="us-east-1", handlers={},
        session_store=store, idle_exit_seconds=10800, max_lifetime_seconds=10800,
        sqs_client=sqs, watcher_factory=FakeWatcher, idle_watcher_factory=FakeWatcher.idle_watcher,
        release_watcher_factory=FakeRelease,
    )
    assert reason == "released" and ("close", "released") in store.calls
    ReleaseWatcher.released.clear()
