"""WorkerLoop exits on idle, max lifetime and spot interruption — no SQS, DB or threads."""
import os
import sys
import threading
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker_loop import LoopConfig, WorkerLoop  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.wall = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def mono(self):
        return self.t

    def now(self):
        return self.wall

    def advance(self, seconds):
        self.t += seconds
        self.wall += timedelta(seconds=seconds)


class FakeSessions:
    def __init__(self, warm_until=None):
        self.calls = []
        self._warm_until = warm_until

    def claim(self):
        self.calls.append("claim")

    def heartbeat(self):
        self.calls.append("heartbeat")

    def warm_until(self):
        return self._warm_until

    def close(self, end_reason):
        self.calls.append(("close", end_reason))


def make_loop(clock, sessions, receive, interrupted=None, idle=900, lifetime=10800):
    processed = []

    def process(msg):
        processed.append(msg)

    loop = WorkerLoop(
        receive=receive,
        process=process,
        sessions=sessions,
        interrupted=interrupted or threading.Event(),
        config=LoopConfig(idle_exit_seconds=idle, max_lifetime_seconds=lifetime),
        clock=clock.mono,
        wall=clock.now,
    )
    return loop, processed


def test_exits_idle_after_idle_exit_seconds():
    clock = FakeClock()
    sessions = FakeSessions()

    def receive():          # every poll is an empty 20 s long-poll
        clock.advance(20)
        return []

    loop, _ = make_loop(clock, sessions, receive, idle=60)
    assert loop.run() == "idle"
    assert sessions.calls[0] == "claim"
    assert sessions.calls[-1] == ("close", "idle")
    assert "heartbeat" in sessions.calls


def test_work_resets_idle_clock():
    clock = FakeClock()
    polls = []

    def receive():
        clock.advance(20)
        polls.append(1)
        return [{"Body": "x"}] if len(polls) == 3 else []

    loop, processed = make_loop(clock, FakeSessions(), receive, idle=60)
    loop.run()
    assert processed == [{"Body": "x"}]
    assert len(polls) == 3 + 3          # 3 polls to the message, then 3 empty polls (60 s) to idle-out


def test_warm_until_defers_idle_exit():
    clock = FakeClock()
    sessions = FakeSessions(warm_until=clock.wall + timedelta(seconds=200))
    polls = []

    def receive():
        clock.advance(20)
        polls.append(1)
        return []

    loop, _ = make_loop(clock, sessions, receive, idle=60)
    assert loop.run() == "idle"
    assert len(polls) >= 10             # 200 s of warm before the 60 s idle window even starts


def test_exits_max_lifetime():
    clock = FakeClock()

    def receive():
        clock.advance(20)
        return [{"Body": "x"}]          # never idle

    loop, _ = make_loop(clock, FakeSessions(), receive, idle=60, lifetime=100)
    assert loop.run() == "max_lifetime"


def test_spot_flag_exits_between_messages_only():
    clock = FakeClock()
    interrupted = threading.Event()
    seen = []

    def receive():
        clock.advance(20)
        return [{"Body": "x"}]

    def process(msg):
        seen.append(msg)
        interrupted.set()               # notice arrives mid-job

    loop = WorkerLoop(receive=receive, process=process, sessions=FakeSessions(),
                      interrupted=interrupted,
                      config=LoopConfig(idle_exit_seconds=60, max_lifetime_seconds=999),
                      clock=clock.mono, wall=clock.now)
    assert loop.run() == "spot_interruption"
    assert len(seen) == 1               # the in-flight message finished; no second receive


def test_spot_flag_exits_mid_batch():
    """Spot notice during multi-message batch stops after current message."""
    clock = FakeClock()
    interrupted = threading.Event()
    seen = []

    def receive():
        clock.advance(20)
        return [{"Body": "x"}, {"Body": "y"}, {"Body": "z"}]  # Three messages in one batch

    def process(msg):
        seen.append(msg)
        if len(seen) == 1:
            interrupted.set()  # Notice arrives after first message

    loop = WorkerLoop(receive=receive, process=process, sessions=FakeSessions(),
                      interrupted=interrupted,
                      config=LoopConfig(idle_exit_seconds=60, max_lifetime_seconds=999),
                      clock=clock.mono, wall=clock.now)
    assert loop.run() == "spot_interruption"
    assert len(seen) == 1  # Only first message processed, not y or z


def test_max_lifetime_exits_mid_batch():
    """Max lifetime during multi-message batch stops after current message."""
    clock = FakeClock()
    seen = []

    def receive():
        clock.advance(20)
        return [{"Body": "x"}, {"Body": "y"}, {"Body": "z"}]  # Three messages in one batch

    def process(msg):
        seen.append(msg)
        if len(seen) == 1:
            clock.advance(150)  # Lifetime exceeded after first message

    loop = WorkerLoop(receive=receive, process=process, sessions=FakeSessions(),
                      interrupted=threading.Event(),
                      config=LoopConfig(idle_exit_seconds=60, max_lifetime_seconds=100),
                      clock=clock.mono, wall=clock.now)
    assert loop.run() == "max_lifetime"
    assert len(seen) == 1  # Only first message processed, not y or z
