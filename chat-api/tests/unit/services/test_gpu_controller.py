from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import gpu_controller as gc
from app.services.ecs_launcher import GpuLaunchError
from app.services.gpu_controller import GpuCapExceeded, GpuController

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)


def make(tasks=None, day_hours=0.0, month_hours=0.0, warms=0, lock=True, closed_sessions=0,
         family="transcription"):
    repo = MagicMock()
    repo.advisory_lock = AsyncMock()
    repo.hours_between = AsyncMock(
        side_effect=lambda since, until, max_session_seconds: day_hours if since.day == NOW.day else month_hours
    )
    repo.close_open_sessions = AsyncMock(return_value=closed_sessions)
    repo.warm_count_for_user_since = AsyncMock(return_value=warms)
    repo.create = AsyncMock()
    repo.extend_warm = AsyncMock()
    repo.sessions_since = AsyncMock(return_value=[])
    repo.latest_cost_snapshot = AsyncMock(return_value=None)
    repo.save_cost_snapshot = AsyncMock()
    launcher = MagicMock()
    launcher.list_worker_tasks = MagicMock(return_value=tasks or [])
    launcher.run_worker_task = MagicMock(return_value="arn:task/1")
    settings = MagicMock(
        gpu_idle_exit_seconds=900, gpu_max_lifetime_seconds=10800,
        gpu_daily_cap_hours=3.0, gpu_monthly_cap_hours=30.0,
        gpu_warm_per_user_per_day=3, gpu_hourly_rate_usd=0.2,
        gpu_wait_estimate_starting_seconds=120, gpu_wait_estimate_off_seconds=180,
        gpu_cost_tag_key="CostCenter", gpu_cost_tag_value="gpu",
    )
    gc._state_cache.clear()
    return GpuController(repo, launcher, settings, family=family, now=lambda: NOW), repo, launcher


async def test_ensure_worker_launches_when_nothing_running():
    ctl, repo, launcher = make()
    state = await ctl.ensure_worker("job", "u1")
    assert state.worker_state == "starting"
    assert state.estimated_wait_seconds == 120
    launcher.run_worker_task.assert_called_once_with("u1")
    repo.advisory_lock.assert_awaited_once()
    repo.create.assert_awaited_once()
    kwargs = repo.create.await_args.kwargs
    assert kwargs["task_arn"] == "arn:task/1" and kwargs["reason"] == "job"


async def test_off_state_reconciles_stale_sessions_before_cap_check():
    """C1(b): a stale open row must be closed before hours_between sees it for the cap check."""
    ctl, repo, launcher = make(closed_sessions=2)
    await ctl.ensure_worker("job", "u1")
    repo.close_open_sessions.assert_awaited_once()
    assert repo.close_open_sessions.await_args.args[0] == NOW
    names = [c[0] for c in repo.mock_calls]
    assert names.index("close_open_sessions") < names.index("hours_between")


async def test_running_state_does_not_reconcile():
    ctl, repo, launcher = make(tasks=["RUNNING"])
    await ctl.ensure_worker("job", "u1")
    repo.close_open_sessions.assert_not_awaited()


async def test_ensure_worker_is_idempotent_when_running():
    ctl, repo, launcher = make(tasks=["RUNNING"])
    state = await ctl.ensure_worker("job", "u1")
    assert state.worker_state == "running"
    launcher.run_worker_task.assert_not_called()


async def test_warm_extends_when_running():
    ctl, repo, launcher = make(tasks=["RUNNING"])
    state = await ctl.ensure_worker("warm", "u1")
    repo.extend_warm.assert_awaited_once()
    assert repo.extend_warm.await_args.args[0] == NOW + timedelta(seconds=900)
    assert state.warm_until == NOW + timedelta(seconds=900)


async def test_daily_cap_refuses():
    ctl, _, launcher = make(day_hours=3.0)
    with pytest.raises(GpuCapExceeded) as e:
        await ctl.ensure_worker("warm", "u1")
    assert "Daily GPU budget" in e.value.reason
    launcher.run_worker_task.assert_not_called()


async def test_monthly_cap_refuses():
    ctl, _, _ = make(month_hours=30.0)
    with pytest.raises(GpuCapExceeded):
        await ctl.ensure_worker("job", "u1")


async def test_hours_between_passes_the_max_lifetime_clamp():
    """C1(c): the controller must pass its configured max session length so the repo can clamp
    a single runaway open session instead of counting it forever."""
    ctl, repo, _ = make()
    await ctl.ensure_worker("job", "u1")
    for call in repo.hours_between.await_args_list:
        assert call.args[2] == 10800


async def test_per_user_warm_cap_only_applies_to_warm():
    ctl, _, launcher = make(warms=3)
    with pytest.raises(GpuCapExceeded):
        await ctl.ensure_worker("warm", "u1")
    await ctl.ensure_worker("job", "u1")
    launcher.run_worker_task.assert_called_once()


async def test_warm_on_running_worker_ignores_warm_cap():
    """Ruling: the per-user warm cap only bites when it would launch — extending warm on an
    already-running worker is free, so a user at their cap can still keep it warm."""
    ctl, repo, launcher = make(tasks=["RUNNING"], warms=3)
    state = await ctl.ensure_worker("warm", "u1")
    assert state.worker_state == "running" and state.notice is None
    repo.extend_warm.assert_awaited_once()
    launcher.run_worker_task.assert_not_called()


async def test_admin_bypasses_caps():
    ctl, _, launcher = make(day_hours=99.0)
    state = await ctl.ensure_worker("warm", "admin1", is_admin=True)
    assert state.worker_state == "starting"
    assert "cap" in (state.notice or "").lower()


async def test_launch_failure_is_reported_not_raised():
    ctl, _, launcher = make()
    launcher.run_worker_task.side_effect = GpuLaunchError("RESOURCE:GPU")
    state = await ctl.ensure_worker("job", "u1")
    assert state.worker_state == "off" and "unavailable" in state.notice


async def test_get_state_degrades_when_list_fails():
    ctl, _, launcher = make()
    launcher.list_worker_tasks.side_effect = GpuLaunchError("throttled")
    state = await ctl.get_state()
    assert state.worker_state == "off"
    assert "unavailable" in state.notice


async def test_ensure_worker_degrades_when_list_fails():
    ctl, _, launcher = make()
    launcher.list_worker_tasks.side_effect = GpuLaunchError("throttled")
    state = await ctl.ensure_worker("job", "u1")
    assert state.worker_state == "off"
    assert "unavailable" in state.notice
    launcher.run_worker_task.assert_not_called()


async def test_get_state_caches_for_30s():
    ctl, _, launcher = make(tasks=["PENDING"])
    assert (await ctl.get_state()).worker_state == "starting"
    launcher.list_worker_tasks.return_value = ["RUNNING"]
    assert (await ctl.get_state()).worker_state == "starting"      # cached
    gc._state_cache.clear()
    assert (await ctl.get_state()).worker_state == "running"


async def test_state_cache_is_per_family():
    a, _, la = make(tasks=["RUNNING"], family="transcription")
    b, _, lb = make(tasks=[], family="photogrammetry")
    assert (await a.get_state()).worker_state == "running"
    assert (await b.get_state()).worker_state == "off"      # not served from a's cache
    assert la.list_worker_tasks.call_count == 1 and lb.list_worker_tasks.call_count == 1


async def test_ensure_worker_invalidates_only_its_family():
    a, _, la = make(tasks=["RUNNING"], family="transcription")
    b, _, _ = make(tasks=[], family="photogrammetry")
    await a.get_state(); await b.get_state()
    await b.ensure_worker("job", "u")
    await a.get_state()
    assert la.list_worker_tasks.call_count == 1           # a's cache survived b's launch


async def test_usage_summary_carries_family():
    ctl, repo, _ = make(family="photogrammetry")
    s = MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None,
                   family="photogrammetry", instance_id="i-1", started_processing_at=None)
    repo.sessions_since = AsyncMock(return_value=[s])
    usage = await ctl.usage("u")
    assert usage.sessions[0].family == "photogrammetry"


async def test_usage_defaults_family_to_transcription_when_not_stamped():
    """The controller reads family off each session; a transcription-scoped repo's sessions
    carry family="transcription"."""
    ctl, repo, _ = make()
    repo.sessions_since = AsyncMock(return_value=[
        MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None,
                   family="transcription", instance_id="i-1", started_processing_at=None)
    ])
    u = await ctl.usage("u1")
    assert len(u.sessions) == 1
    assert u.sessions[0].family == "transcription"


async def test_usage_hours_is_zero_for_a_session_that_never_got_an_instance():
    """M7 / phantom-hours rule: a row with instance_id IS NULL cost nothing, matching
    GpuSessionRepository.hours_between's exclusion of such rows."""
    ctl, repo, _ = make()
    s = MagicMock(started_at=NOW, ended_at=NOW + timedelta(hours=1), reason="job", started_by="u",
                   end_reason=None, family="transcription", instance_id=None, started_processing_at=None)
    repo.sessions_since = AsyncMock(return_value=[s])
    u = await ctl.usage("u1")
    assert u.sessions[0].hours == 0.0


async def test_usage_hours_starts_the_clock_at_started_processing_at():
    """M7 / phantom-hours rule: the session's clock starts when the worker claimed it
    (started_processing_at), not on enqueue (started_at)."""
    ctl, repo, _ = make()
    s = MagicMock(
        started_at=NOW, started_processing_at=NOW + timedelta(minutes=10), ended_at=NOW + timedelta(hours=1),
        reason="job", started_by="u", end_reason=None, family="transcription", instance_id="i-1",
    )
    repo.sessions_since = AsyncMock(return_value=[s])
    u = await ctl.usage("u1")
    assert u.sessions[0].hours == 0.83


async def test_usage_estimates_and_snapshots():
    ctl, repo, _ = make(day_hours=1.5, month_hours=4.0)
    cost = MagicMock()
    cost.month_to_date_usd = MagicMock(return_value=12.34)
    ctl._cost = cost
    u = await ctl.usage("u1")
    assert u.today_hours == 1.5 and u.month_hours == 4.0
    assert u.estimated_month_cost_usd == 0.8
    assert u.actual_month_to_date_usd == 12.34
    repo.save_cost_snapshot.assert_awaited_once()


# ── admin release ──────────────────────────────────────────────────────────────────────────────

async def test_release_marks_live_session_and_returns_state():
    from app.services.gpu_controller import GpuNoWorker
    ctl, repo, launcher = make(tasks=["RUNNING"])
    repo.request_release = AsyncMock(return_value=1)
    state = await ctl.release("immediate", "admin1")
    assert state.worker_state == "running"
    repo.request_release.assert_awaited_once_with(mode="immediate", user_id="admin1", now=NOW)


async def test_release_without_live_session_raises():
    from app.services.gpu_controller import GpuNoWorker
    ctl, repo, _ = make()
    repo.request_release = AsyncMock(return_value=0)
    with pytest.raises(GpuNoWorker):
        await ctl.release("graceful", "admin1")


async def test_release_rejects_unknown_mode():
    ctl, repo, _ = make()
    repo.request_release = AsyncMock(return_value=1)
    with pytest.raises(ValueError):
        await ctl.release("now", "admin1")
