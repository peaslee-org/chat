"""Idle-aware SQS consumption loop.

Importable without torch/pyannote: main.py injects the real receive/process callables.
Exits (returns the end reason) on idle, max lifetime, or a spot-interruption flag —
checked between messages, never mid-job.
"""
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopConfig:
    idle_exit_seconds: int
    max_lifetime_seconds: int


class WorkerLoop:
    def __init__(
        self,
        receive: Callable[[], list],
        process: Callable[[dict], None],
        sessions,
        interrupted: threading.Event,
        config: LoopConfig,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._receive = receive
        self._process = process
        self._sessions = sessions
        self._interrupted = interrupted
        self._config = config
        self._clock = clock
        self._wall = wall

    def run(self) -> str:
        start = self._clock()
        last_work = start
        self._sessions.claim()
        end_reason = "idle"
        try:
            while True:
                messages = self._receive()

                # Process each message, checking after each one
                for msg in messages:
                    self._process(msg)
                    last_work = self._clock()

                    # Check after each message (before next one)
                    stop_reason = self._check_exit_conditions(start)
                    if stop_reason:
                        end_reason = stop_reason
                        break

                # If we broke due to spot/lifetime, exit outer loop
                if end_reason != "idle":
                    break

                now = self._clock()
                self._sessions.heartbeat()

                # Check again after empty poll
                stop_reason = self._check_exit_conditions(start)
                if stop_reason:
                    end_reason = stop_reason
                    break

                # Check idle (only in the main loop after empty poll)
                if now - last_work >= self._config.idle_exit_seconds and self._warm_remaining() <= 0:
                    end_reason = "idle"
                    break

            return end_reason
        except Exception:
            end_reason = "error"
            raise
        finally:
            # Always ledgered, even on an exception escaping the loop.
            logger.info("Worker loop ending: %s (uptime %.0fs)", end_reason, self._clock() - start)
            self._sessions.close(end_reason)

    def _check_exit_conditions(self, start: float) -> Optional[str]:
        """Check interrupted and max_lifetime conditions. Return reason or None."""
        if self._interrupted.is_set():
            return "spot_interruption"
        now = self._clock()
        if now - start >= self._config.max_lifetime_seconds:
            return "max_lifetime"
        return None

    def _warm_remaining(self) -> float:
        warm_until: Optional[datetime] = self._sessions.warm_until()
        if warm_until is None:
            return 0.0
        return (warm_until - self._wall()).total_seconds()
