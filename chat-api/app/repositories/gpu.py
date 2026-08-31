"""gpu_sessions / gpu_cost_snapshots access. Hours = closed sessions + open sessions to `until`."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, NamedTuple, Optional
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gpu import GpuCostSnapshot, GpuSession
from app.models.photogrammetry import PhotogrammetryJob
from app.models.transcription import TranscriptionJob


class JobLabel(NamedTuple):
    name: Optional[str]      # scans have one; transcripts don't
    created_at: datetime


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
                     warm_until: Optional[datetime],
                     estimated_startup_seconds: Optional[int] = None,
                     job_id: Optional[UUID] = None) -> GpuSession:
        row = GpuSession(
            task_arn=task_arn, started_by=started_by, reason=reason,
            warm_until=warm_until, family=self.family,
            estimated_startup_seconds=estimated_startup_seconds, job_id=job_id,
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

    async def recent_startups(self, family: str, limit: int = 20) -> list[GpuSession]:
        """The family's latest job-triggered launches that a worker actually claimed — the sample
        the startup estimates are measured from (started_processing_at − started_at), split into
        cold/warm by the controller. Warm-*reason* launches (pre-warming with nothing queued) are
        excluded: the claim never happens. 20 so both kinds get enough samples."""
        stmt = (
            select(GpuSession)
            .where(
                GpuSession.family == family,
                GpuSession.reason == "job",
                GpuSession.started_processing_at.is_not(None),
            )
            .order_by(GpuSession.started_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def open_session(self, family: str) -> Optional[GpuSession]:
        """The family's live (unended) session, newest first — None when no worker is up."""
        stmt = (
            select(GpuSession)
            .where(GpuSession.ended_at.is_(None), GpuSession.family == family)
            .order_by(GpuSession.started_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def last_ended_session(self, family: str) -> Optional[GpuSession]:
        """The family's most recently ended session — its ended_at says whether the instance is
        probably still up (inside the ASG's scale-in lag), i.e. whether the next start is warm."""
        stmt = (
            select(GpuSession)
            .where(GpuSession.ended_at.is_not(None), GpuSession.family == family)
            .order_by(GpuSession.ended_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def record_timings(self, task_arn: str, **fields: Optional[datetime]) -> None:
        """Copy ECS stage timestamps onto the session row. Only non-None inputs are applied, and
        only where the column is still NULL — the first stamp wins, later polls are no-ops."""
        values = {
            name: func.coalesce(getattr(GpuSession, name), value)
            for name, value in fields.items()
            if value is not None
        }
        if not values:
            return
        await self.db.execute(
            update(GpuSession).where(GpuSession.task_arn == task_arn).values(**values)
        )

    async def sessions_since(self, since: datetime) -> list[GpuSession]:
        stmt = select(GpuSession).where(GpuSession.started_at >= since).order_by(GpuSession.started_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def job_labels(self, sessions: Iterable[GpuSession]) -> dict[UUID, JobLabel]:
        """The job each session was launched for, looked up in the table its `family` names. A
        job deleted since simply has no entry. Not scoped to self.family: sessions_since isn't."""
        by_family: dict[str, set[UUID]] = {}
        for s in sessions:
            if s.job_id is not None:
                by_family.setdefault(s.family, set()).add(s.job_id)
        labels: dict[UUID, JobLabel] = {}
        if ids := by_family.get("photogrammetry"):
            stmt = select(PhotogrammetryJob.id, PhotogrammetryJob.name, PhotogrammetryJob.created_at).where(
                PhotogrammetryJob.id.in_(ids))
            for jid, name, created in (await self.db.execute(stmt)).all():
                labels[jid] = JobLabel(name, created)
        if ids := by_family.get("transcription"):
            stmt = select(TranscriptionJob.id, TranscriptionJob.created_at).where(TranscriptionJob.id.in_(ids))
            for jid, created in (await self.db.execute(stmt)).all():
                labels[jid] = JobLabel(None, created)
        return labels

    async def completed_photogrammetry_billables_since(self, since: datetime) -> list:
        """Completed scans with a billable window (worker claim → complete), newest first —
        matched to sessions by the usage panel. Rows, not ORM objects the caller could mutate."""
        stmt = (
            select(PhotogrammetryJob.id, PhotogrammetryJob.name, PhotogrammetryJob.user_id,
                   PhotogrammetryJob.image_count, PhotogrammetryJob.processing_started_at,
                   PhotogrammetryJob.completed_at)
            .where(PhotogrammetryJob.completed_at >= since,
                   PhotogrammetryJob.processing_started_at.isnot(None))
            .order_by(PhotogrammetryJob.completed_at.desc())
        )
        return list((await self.db.execute(stmt)).all())

    async def recent_completed_billables(self, limit: int = 20) -> list:
        """The last N completed scans with a billable window — the $/photo summary's sample."""
        stmt = (
            select(PhotogrammetryJob.id, PhotogrammetryJob.name, PhotogrammetryJob.user_id,
                   PhotogrammetryJob.image_count, PhotogrammetryJob.processing_started_at,
                   PhotogrammetryJob.completed_at)
            .where(PhotogrammetryJob.completed_at.isnot(None),
                   PhotogrammetryJob.processing_started_at.isnot(None))
            .order_by(PhotogrammetryJob.completed_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).all())

    async def latest_cost_snapshot(self, month: str) -> Optional[GpuCostSnapshot]:
        stmt = (select(GpuCostSnapshot).where(GpuCostSnapshot.month == month)
                .order_by(GpuCostSnapshot.fetched_at.desc()).limit(1))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def save_cost_snapshot(self, month: str, amount_usd: float) -> None:
        self.db.add(GpuCostSnapshot(month=month, amount_usd=Decimal(str(amount_usd))))
        await self.db.flush()
