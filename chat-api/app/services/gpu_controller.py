"""The one place GPU work starts. Caps → lock → ListTasks → RunTask → ledger row."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.schemas.gpu import GpuSessionSummary, GpuStateResponse, GpuUsageResponse, WorkerState
from app.services.ecs_launcher import GpuLaunchError

logger = logging.getLogger(__name__)

_STATE_CACHE_TTL = 30.0
_state_cache: dict[str, tuple[float, list[str]]] = {}   # family -> (expiry_monotonic, task statuses)

_STARTING = {"PROVISIONING", "PENDING", "ACTIVATING"}


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
                return self._response("off", notice="GPU status unavailable")
            cached = (mono + _STATE_CACHE_TTL, statuses)
            _state_cache[self._family] = cached
        return self._response(_state_from(cached[1]))

    def _response(self, state: WorkerState, notice: Optional[str] = None,
                  warm_until: Optional[datetime] = None) -> GpuStateResponse:
        wait = {"running": 0, "starting": self._s.gpu_wait_estimate_starting_seconds,
                "off": self._s.gpu_wait_estimate_off_seconds}[state]
        return GpuStateResponse(worker_state=state, estimated_wait_seconds=wait,
                                notice=notice, warm_until=warm_until)

    # ── launch ───────────────────────────────────────────────────────────────

    async def ensure_worker(self, reason: str, user_id: str, is_admin: bool = False) -> GpuStateResponse:
        now = self._now()
        await self._repo.advisory_lock()
        try:
            statuses = await asyncio.to_thread(self._launcher.list_worker_tasks)
        except GpuLaunchError as e:
            logger.error("ListTasks failed: %s", e)
            _state_cache.pop(self._family, None)
            return self._response("off", notice="GPU unavailable, retrying on next poll")
        state = _state_from(statuses)
        if state == "off":
            # ListTasks just confirmed nothing is running — any still-open row is stale
            # (e.g. a worker that died before it could close its own session). Reconcile
            # before the cap check reads gpu_sessions, or a phantom row inflates it forever.
            closed = await self._repo.close_open_sessions(now, end_reason="unknown")
            if closed:
                logger.info("Reconciled %d stale gpu_sessions row(s) before cap check", closed)
        notice = await self._check_caps(reason, user_id, is_admin, will_launch=(state == "off"))
        warm_until = None
        if state == "off":
            try:
                task_arn = await asyncio.to_thread(self._launcher.run_worker_task, user_id)
            except GpuLaunchError as e:
                logger.error("RunTask failed: %s", e)
                _state_cache.pop(self._family, None)
                return self._response("off", notice="GPU unavailable, retrying on next poll")
            warm_until = now + timedelta(seconds=self._s.gpu_idle_exit_seconds) if reason == "warm" else None
            await self._repo.create(task_arn=task_arn, started_by=user_id, reason=reason, warm_until=warm_until)
            state = "starting"
        elif reason == "warm":
            warm_until = now + timedelta(seconds=self._s.gpu_idle_exit_seconds)
            await self._repo.extend_warm(warm_until)
        _state_cache.pop(self._family, None)
        return self._response(state, notice=notice, warm_until=warm_until)

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
        sessions = [
            GpuSessionSummary(
                started_at=s.started_at, ended_at=s.ended_at, reason=s.reason, started_by=s.started_by,
                end_reason=s.end_reason, family=s.family,
                # Matches hours_between's phantom-hours rule: a row that never got an instance
                # cost nothing, and the clock starts when the worker claimed it, not on enqueue.
                hours=(
                    0.0 if s.instance_id is None
                    else round(((s.ended_at or now) - (s.started_processing_at or s.started_at)).total_seconds() / 3600.0, 2)
                ),
            )
            for s in await self._repo.sessions_since(month_start)
        ]
        return GpuUsageResponse(
            today_hours=today, month_hours=month,
            daily_cap_hours=self._s.gpu_daily_cap_hours, monthly_cap_hours=self._s.gpu_monthly_cap_hours,
            warms_today_for_user=warms, warm_cap_per_user_per_day=self._s.gpu_warm_per_user_per_day,
            estimated_month_cost_usd=round(month * self._s.gpu_hourly_rate_usd, 2),
            hourly_rate_usd=self._s.gpu_hourly_rate_usd,
            actual_month_to_date_usd=actual, actual_fetched_at=fetched_at, sessions=sessions,
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
