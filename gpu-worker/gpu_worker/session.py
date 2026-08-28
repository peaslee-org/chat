"""Worker side of the gpu_sessions ledger. Every method is best-effort: the loop's exit
decisions use local clocks and must survive a missing table or an unreachable database."""
import logging
from datetime import datetime, timezone

from gpu_worker.db import GpuSession

logger = logging.getLogger(__name__)


class GpuSessionStore:
    def __init__(self, task_arn: str | None, instance_id: str | None, session_factory):
        self._task_arn = task_arn
        self._instance_id = instance_id
        self._factory = session_factory
        self._warned = False

    def claim(self) -> None:
        self._update(lambda row, now: (
            setattr(row, "instance_id", self._instance_id),
            setattr(row, "started_processing_at", now),
        ))

    def heartbeat(self) -> None:
        self._update(lambda row, now: setattr(row, "last_seen_at", now))

    def warm_until(self) -> datetime | None:
        if not self._task_arn:
            return None
        try:
            with self._factory() as s:
                row = s.query(GpuSession).filter_by(task_arn=self._task_arn).one_or_none()
                return row.warm_until if row else None
        except Exception:
            self._warn()
            return None

    def release_mode(self) -> str | None:
        """'graceful' | 'immediate' once an admin has called POST /gpu/release for this row; else None."""
        if not self._task_arn:
            return None
        try:
            with self._factory() as s:
                row = s.query(GpuSession).filter_by(task_arn=self._task_arn).one_or_none()
                return row.release_mode if row else None
        except Exception:
            self._warn()
            return None

    def close(self, end_reason: str) -> None:
        self._update(lambda row, now: (
            setattr(row, "ended_at", now),
            setattr(row, "end_reason", end_reason),
        ))

    def _update(self, fn) -> None:
        if not self._task_arn:
            return
        try:
            with self._factory() as s:
                row = s.query(GpuSession).filter_by(task_arn=self._task_arn).one_or_none()
                if row is None:
                    return
                fn(row, datetime.now(timezone.utc))
        except Exception:
            self._warn()

    def _warn(self) -> None:
        if not self._warned:
            logger.warning("gpu_sessions unavailable — continuing without ledger", exc_info=True)
            self._warned = True
