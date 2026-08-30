"""The one place GPU work starts. Caps → lock → ListTasks → RunTask → ledger row."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Callable, Optional
from uuid import UUID

from app.schemas.gpu import (
    GpuSessionSummary, GpuStateResponse, GpuUsageResponse, StartupKind, StartupStages, WorkerState,
)
from app.services.ecs_launcher import GpuLaunchError

logger = logging.getLogger(__name__)

_STATE_CACHE_TTL = 30.0
_state_cache: dict[str, tuple[float, list[str]]] = {}   # family -> (expiry_monotonic, task statuses)

_STARTING = {"PROVISIONING", "PENDING", "ACTIVATING"}
_ESTIMATE_WINDOW = 20      # job starts the medians are taken over (both kinds together)
_ESTIMATE_MIN_SAMPLES = 3  # below this, per kind, the config default is used
_BOOT_SLACK = timedelta(seconds=60)   # instance clock vs API clock; boots this close still count as cold

Estimate = tuple[int, str, int]   # (seconds, basis, samples)


def startup_kind(session) -> Optional[StartupKind]:
    """cold: the instance booted for this launch (boot at or after RunTask, minus clock slack).
    warm: it was already up — the ASG had not scaled it in yet, so only the container had to
    start. None until the worker has reported the boot time."""
    booted = getattr(session, "instance_booted_at", None)
    if booted is None:
        return None
    return "cold" if booted >= session.started_at - _BOOT_SLACK else "warm"


def _seconds(later: Optional[datetime], earlier: Optional[datetime]) -> Optional[int]:
    if later is None or earlier is None:
        return None
    return max(0, int((later - earlier).total_seconds()))


def startup_stages(session) -> Optional[StartupStages]:
    """Per-stage seconds for one launch, or None when no stage timestamp was recorded at all."""
    booted = getattr(session, "instance_booted_at", None)
    pull_started = getattr(session, "pull_started_at", None)
    pull_stopped = getattr(session, "pull_stopped_at", None)
    container = getattr(session, "container_started_at", None)
    if booted is None and pull_started is None and pull_stopped is None and container is None:
        return None
    cold = startup_kind(session) == "cold"
    stages = StartupStages(
        capacity=_seconds(booted, session.started_at) if cold else None,
        boot=_seconds(pull_started, booted) if cold else None,
        pull=_seconds(pull_stopped, pull_started),
        container=_seconds(container, pull_stopped),
        init=_seconds(session.started_processing_at, container),
    )
    return stages if any(v is not None for v in stages.model_dump().values()) else None


class GpuNoWorker(Exception):
    """POST /gpu/release with no live session row for the family."""


class GpuCapExceeded(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _state_from(statuses: list[str]) -> WorkerState:
    if any(s == "RUNNING" for s in statuses):
        return "running"
    if any(s in _STARTING for s in statuses):
        return "starting"
    return "off"


class GpuController:
    def __init__(self, repo, launcher, settings, family: str = "transcription", cost_client=None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._repo = repo
        self._launcher = launcher
        self._s = settings
        self._family = family
        self._cost = cost_client
        self._now = now

    # ── state ────────────────────────────────────────────────────────────────

    async def get_state(self) -> GpuStateResponse:
        mono = time.monotonic()
        cached = _state_cache.get(self._family)
        if cached is None or mono >= cached[0]:
            try:
                statuses = await asyncio.to_thread(self._launcher.list_worker_tasks)
            except GpuLaunchError as e:
                logger.warning("ListTasks failed: %s", e)
                return await self._response("off", notice="GPU status unavailable")
            cached = (mono + _STATE_CACHE_TTL, statuses)
            _state_cache[self._family] = cached
        state = _state_from(cached[1])
        open_row = await self._repo.open_session(self._family) if state != "off" else None
        if open_row is not None and open_row.container_started_at is None and cached[1]:
            await self._record_timings(open_row)
        return await self._response(state, open_row=open_row)

    async def _record_timings(self, open_row) -> None:
        """Copy the ECS task's pull/start stamps onto the session once they exist. Poll-time only —
        never on the launch path — and skipped once container_started_at is known."""
        try:
            timings = await asyncio.to_thread(self._launcher.task_timings, open_row.task_arn)
        except GpuLaunchError as e:
            logger.warning("DescribeTasks failed: %s", e)
            return
        if timings:
            await self._repo.record_timings(open_row.task_arn, **timings)

    async def release(self, mode: str, user_id: str) -> GpuStateResponse:
        """Admin: make the live worker exit — after its current job ("graceful") or now
        ("immediate": the job's message goes back to the queue for the next worker, which starts on
        the current task-definition revision). Lets a bad deploy be reloaded without waiting for
        idle-exit, and frees a worker stuck in a job."""
        if mode not in ("graceful", "immediate"):
            raise ValueError(f"unknown release mode {mode!r}")
        if not await self._repo.request_release(mode=mode, user_id=user_id, now=self._now()):
            raise GpuNoWorker(f"no live {self._family} worker session")
        _state_cache.pop(self._family, None)
        return await self.get_state()

    # ── startup estimate ─────────────────────────────────────────────────────

    async def _startup_estimates(self) -> dict[StartupKind, Estimate]:
        """Per kind: the median off→ready time (RunTask → worker's first claim) of the family's
        recent job starts, "measured" at ≥3 samples of that kind, else the config default.
        cold spans capacity-provider reaction, boot, pull and container start; warm only the
        last two. Launches whose kind is unknown (no boot time yet) count as cold — that is
        every launch before the worker started reporting it."""
        recent = await self._repo.recent_startups(self._family, _ESTIMATE_WINDOW)
        samples: dict[StartupKind, list[int]] = {"cold": [], "warm": []}
        for s in recent:
            if s.started_processing_at is None:
                continue
            samples[startup_kind(s) or "cold"].append(int((s.started_processing_at - s.started_at).total_seconds()))
        defaults = {"cold": self._s.gpu_wait_estimate_off_seconds, "warm": self._s.gpu_wait_estimate_warm_seconds}
        return {
            kind: ((int(median(v)), "measured", len(v)) if len(v) >= _ESTIMATE_MIN_SAMPLES
                   else (defaults[kind], "default", len(v)))
            for kind, v in samples.items()
        }

    async def _quoted_kind(self, open_row) -> StartupKind:
        """warm when the open session is already known warm, or the family's last session ended
        inside the ASG's scale-in lag (its instance is still up); otherwise cold."""
        if open_row is not None and startup_kind(open_row) == "warm":
            return "warm"
        last = await self._repo.last_ended_session(self._family)
        if last is not None and last.ended_at is not None:
            if self._now() - last.ended_at <= timedelta(seconds=self._s.gpu_scale_in_seconds):
                return "warm"
        return "cold"

    async def _response(self, state: WorkerState, notice: Optional[str] = None,
                        warm_until: Optional[datetime] = None,
                        estimates: Optional[dict[StartupKind, Estimate]] = None,
                        starting_since: Optional[datetime] = None,
                        open_row=None, kind: Optional[StartupKind] = None) -> GpuStateResponse:
        if estimates is None:
            estimates = await self._startup_estimates()
        if state == "starting" and starting_since is None:
            if open_row is None:
                open_row = await self._repo.open_session(self._family)
            starting_since = open_row.started_at if open_row is not None else None
        if kind is None:
            kind = await self._quoted_kind(open_row)
        full, basis, samples = estimates[kind]
        if state == "running":
            wait = 0
        elif state == "starting":
            elapsed = int((self._now() - starting_since).total_seconds()) if starting_since else 0
            wait = max(0, full - elapsed)
        else:
            wait = full
        return GpuStateResponse(
            worker_state=state, estimated_wait_seconds=wait, notice=notice, warm_until=warm_until,
            starting_since=starting_since if state == "starting" else None,
            startup_estimate_seconds=full, estimate_basis=basis, estimate_samples=samples,
            start_kind=kind,
        )

    # ── launch ───────────────────────────────────────────────────────────────

    async def ensure_worker(self, reason: str, user_id: str, is_admin: bool = False,
                            job_id: Optional[UUID] = None) -> GpuStateResponse:
        """`job_id`: the job a "job" launch is for — recorded on the ledger row for the usage panel."""
        now = self._now()
        await self._repo.advisory_lock()
        try:
            statuses = await asyncio.to_thread(self._launcher.list_worker_tasks)
        except GpuLaunchError as e:
            logger.error("ListTasks failed: %s", e)
            _state_cache.pop(self._family, None)
            return await self._response("off", notice="GPU unavailable, retrying on next poll")
        state = _state_from(statuses)
        if state == "off":
            # ListTasks just confirmed nothing is running — any still-open row is stale
            # (e.g. a worker that died before it could close its own session). Reconcile
            # before the cap check reads gpu_sessions, or a phantom row inflates it forever.
            closed = await self._repo.close_open_sessions(now, end_reason="unknown")
            if closed:
                logger.info("Reconciled %d stale gpu_sessions row(s) before cap check", closed)
        notice = await self._check_caps(reason, user_id, is_admin, will_launch=(state == "off"))
        estimates = await self._startup_estimates()
        kind = await self._quoted_kind(None)
        warm_until = None
        starting_since = None
        if state == "off":
            try:
                task_arn = await asyncio.to_thread(self._launcher.run_worker_task, user_id)
            except GpuLaunchError as e:
                logger.error("RunTask failed: %s", e)
                _state_cache.pop(self._family, None)
                return await self._response("off", notice="GPU unavailable, retrying on next poll",
                                            estimates=estimates, kind=kind)
            warm_until = now + timedelta(seconds=self._s.gpu_idle_exit_seconds) if reason == "warm" else None
            # Record the promise (of the kind quoted): the usage panel compares it with what the
            # start actually took.
            await self._repo.create(task_arn=task_arn, started_by=user_id, reason=reason,
                                    warm_until=warm_until, estimated_startup_seconds=estimates[kind][0],
                                    job_id=job_id)
            state = "starting"
            starting_since = now
        elif reason == "warm":
            warm_until = now + timedelta(seconds=self._s.gpu_idle_exit_seconds)
            await self._repo.extend_warm(warm_until)
        _state_cache.pop(self._family, None)
        return await self._response(state, notice=notice, warm_until=warm_until,
                                    estimates=estimates, starting_since=starting_since, kind=kind)

    async def _check_caps(self, reason: str, user_id: str, is_admin: bool, will_launch: bool) -> Optional[str]:
        now = self._now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        problems = []
        if await self._repo.hours_between(day_start, now, self._s.gpu_max_lifetime_seconds) >= self._s.gpu_daily_cap_hours:
            problems.append(f"Daily GPU budget used ({self._s.gpu_daily_cap_hours:g} h). Resets at midnight UTC.")
        if await self._repo.hours_between(month_start, now, self._s.gpu_max_lifetime_seconds) >= self._s.gpu_monthly_cap_hours:
            problems.append(f"Monthly GPU budget used ({self._s.gpu_monthly_cap_hours:g} h). Resets on the 1st.")
        # Warm cap only bites when it would actually start a new task — extending the warm
        # window on a worker that's already up costs nothing extra.
        if (
            will_launch
            and reason == "warm"
            and await self._repo.warm_count_for_user_since(user_id, day_start) >= self._s.gpu_warm_per_user_per_day
        ):
            problems.append(f"You have used your {self._s.gpu_warm_per_user_per_day} warm-ups for today.")
        if not problems:
            return None
        if is_admin:
            return "Admin: cap bypassed — " + " ".join(problems)
        raise GpuCapExceeded(" ".join(problems))

    # ── usage ────────────────────────────────────────────────────────────────

    async def usage(self, user_id: str) -> GpuUsageResponse:
        now = self._now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        today = await self._repo.hours_between(day_start, now, self._s.gpu_max_lifetime_seconds)
        month = await self._repo.hours_between(month_start, now, self._s.gpu_max_lifetime_seconds)
        warms = await self._repo.warm_count_for_user_since(user_id, day_start)
        actual, fetched_at = await self._actual_cost(now)
        estimates = await self._startup_estimates()
        cold_seconds, _, cold_samples = estimates["cold"]
        warm_seconds, _, warm_samples = estimates["warm"]
        rows = await self._repo.sessions_since(month_start)
        jobs = await self._repo.job_labels(rows)
        sessions = [
            GpuSessionSummary(
                started_at=s.started_at, ended_at=s.ended_at, reason=s.reason, started_by=s.started_by,
                end_reason=s.end_reason, family=s.family,
                estimated_startup_seconds=s.estimated_startup_seconds,
                actual_startup_seconds=(
                    int((s.started_processing_at - s.started_at).total_seconds())
                    if s.started_processing_at is not None else None
                ),
                kind=startup_kind(s),
                stages=startup_stages(s),
                job=jobs.get(s.job_id) if s.job_id is not None else None,
                # Matches hours_between's phantom-hours rule: a row that never got an instance
                # cost nothing, and the clock starts when the worker claimed it, not on enqueue.
                hours=(
                    0.0 if s.instance_id is None
                    else round(((s.ended_at or now) - (s.started_processing_at or s.started_at)).total_seconds() / 3600.0, 2)
                ),
            )
            for s in rows
        ]
        return GpuUsageResponse(
            today_hours=today, month_hours=month,
            daily_cap_hours=self._s.gpu_daily_cap_hours, monthly_cap_hours=self._s.gpu_monthly_cap_hours,
            warms_today_for_user=warms, warm_cap_per_user_per_day=self._s.gpu_warm_per_user_per_day,
            estimated_month_cost_usd=round(month * self._s.gpu_hourly_rate_usd, 2),
            hourly_rate_usd=self._s.gpu_hourly_rate_usd,
            actual_month_to_date_usd=actual, actual_fetched_at=fetched_at, sessions=sessions,
            startup_median_seconds=cold_seconds if cold_samples >= _ESTIMATE_MIN_SAMPLES else None,
            startup_samples=cold_samples,
            cold_median_seconds=cold_seconds if cold_samples >= _ESTIMATE_MIN_SAMPLES else None,
            cold_samples=cold_samples,
            warm_median_seconds=warm_seconds if warm_samples >= _ESTIMATE_MIN_SAMPLES else None,
            warm_samples=warm_samples,
        )

    async def _actual_cost(self, now: datetime) -> tuple[Optional[float], Optional[datetime]]:
        if self._cost is None:
            return None, None
        month = now.strftime("%Y-%m")
        snap = await self._repo.latest_cost_snapshot(month)
        if snap is not None and now - snap.fetched_at < timedelta(hours=24):
            return float(snap.amount_usd), snap.fetched_at
        try:
            amount = await asyncio.to_thread(
                self._cost.month_to_date_usd, self._s.gpu_cost_tag_key, self._s.gpu_cost_tag_value, now.date()
            )
        except Exception:
            logger.warning("Cost Explorer fetch failed", exc_info=True)
            return (float(snap.amount_usd), snap.fetched_at) if snap else (None, None)
        await self._repo.save_cost_snapshot(month, amount)
        return amount, now
