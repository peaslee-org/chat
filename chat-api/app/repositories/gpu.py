"""gpu_sessions / gpu_cost_snapshots access. Hours = closed sessions + open sessions to `until`."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gpu import GpuCostSnapshot, GpuSession


class GpuSessionRepository:
    def __init__(self, db: AsyncSession, family: str = "transcription"):
        self.db = db
        self.family = family

    async def advisory_lock(self) -> None:
        # Transaction-scoped; released at commit/rollback of this session's transaction.
        await self.db.execute(text("SELECT pg_advisory_xact_lock(hashtext('gpu_controller'))"))

    async def close_open_sessions(self, now: datetime, end_reason: str = "unknown") -> int:
        # Reconciliation: a row can be left open by a worker that never got to call back
        # (e.g. it died before GpuSessionStore.close). Called when ListTasks shows nothing
        # running, so any still-open row is stale.
        result = await self.db.execute(
            update(GpuSession)
            .where(GpuSession.ended_at.is_(None), GpuSession.family == self.family)
            .values(ended_at=now, end_reason=end_reason)
        )
        return result.rowcount or 0

    async def hours_between(self, since: datetime, until: datetime, max_session_seconds: int) -> float:
        # Overlap of each session [span_start, min(coalesce(ended_at, until), until, span_start +
        # max_session_seconds)] with [since, until]. The max_session_seconds term clamps a single
        # runaway open session so it cannot inflate the caps forever. Not family-scoped: one pool,
        # one budget. Rows that never got an instance (`instance_id IS NULL`) cost nothing and are
        # excluded; a session's clock starts when the worker claimed it.
        span_start = func.coalesce(GpuSession.started_processing_at, GpuSession.started_at)
        span_end = func.least(
            func.coalesce(GpuSession.ended_at, until),
            until,
            span_start + timedelta(seconds=max_session_seconds),
        )
        stmt = select(
            func.coalesce(
                func.sum(
                    func.greatest(
                        0,
                        func.extract("epoch", span_end - func.greatest(span_start, since)),
                    )
                ),
                0,
            )
        ).where(
            GpuSession.instance_id.is_not(None),
            span_start < until,
            func.coalesce(GpuSession.ended_at, until) > since,
        )
        seconds = (await self.db.execute(stmt)).scalar_one()
        return round(float(seconds) / 3600.0, 3)

    async def warm_count_for_user_since(self, user_id: str, since: datetime) -> int:
        stmt = select(func.count()).where(
            GpuSession.started_by == user_id,
            GpuSession.reason == "warm",
            GpuSession.started_at >= since,
            GpuSession.family == self.family,
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def create(self, *, task_arn: str, started_by: str, reason: str,
                     warm_until: Optional[datetime]) -> GpuSession:
        row = GpuSession(
            task_arn=task_arn, started_by=started_by, reason=reason,
            warm_until=warm_until, family=self.family,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def extend_warm(self, warm_until: datetime) -> None:
        # Extend every open session (there is at most one worker task at a time per family).
        await self.db.execute(
            update(GpuSession)
            .where(GpuSession.ended_at.is_(None), GpuSession.family == self.family)
            .values(warm_until=warm_until)
        )

    async def request_release(self, *, mode: str, user_id: str, now: datetime) -> int:
        """Ask the family's live worker to exit (the worker polls release_mode). Clears warm_until so
        a graceful release is not deferred by a warm window. Returns rows updated: 0 = no live worker."""
        result = await self.db.execute(
            update(GpuSession)
            .where(GpuSession.ended_at.is_(None), GpuSession.family == self.family)
            .values(release_mode=mode, release_requested_at=now, release_requested_by=user_id, warm_until=None)
        )
        return result.rowcount

    async def sessions_since(self, since: datetime) -> list[GpuSession]:
        stmt = select(GpuSession).where(GpuSession.started_at >= since).order_by(GpuSession.started_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def latest_cost_snapshot(self, month: str) -> Optional[GpuCostSnapshot]:
        stmt = (select(GpuCostSnapshot).where(GpuCostSnapshot.month == month)
                .order_by(GpuCostSnapshot.fetched_at.desc()).limit(1))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def save_cost_snapshot(self, month: str, amount_usd: float) -> None:
        self.db.add(GpuCostSnapshot(month=month, amount_usd=Decimal(str(amount_usd))))
        await self.db.flush()
