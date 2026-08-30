import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import gpu_controller as gc
from app.services.ecs_launcher import GpuLaunchError
from app.repositories.gpu import JobLabel
from app.services.gpu_controller import GpuCapExceeded, GpuController

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)


def make(tasks=None, day_hours=0.0, month_hours=0.0, warms=0, lock=True, closed_sessions=0,
         family="transcription", startups=None, open_session=None, last_ended=None, timings=None):
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
    repo.job_labels = AsyncMock(return_value={})
    repo.recent_startups = AsyncMock(return_value=list(startups or []))
    repo.open_session = AsyncMock(return_value=open_session)
    repo.last_ended_session = AsyncMock(return_value=last_ended)
    repo.record_timings = AsyncMock()
    repo.latest_cost_snapshot = AsyncMock(return_value=None)
    repo.save_cost_snapshot = AsyncMock()
    launcher = MagicMock()
    launcher.list_worker_tasks = MagicMock(return_value=tasks or [])
    launcher.run_worker_task = MagicMock(return_value="arn:task/1")
    launcher.task_timings = MagicMock(return_value=timings)
    settings = MagicMock(
        gpu_idle_exit_seconds=900, gpu_max_lifetime_seconds=10800,
        gpu_daily_cap_hours=3.0, gpu_monthly_cap_hours=30.0,
        gpu_warm_per_user_per_day=3, gpu_hourly_rate_usd=0.2,
        gpu_wait_estimate_starting_seconds=420, gpu_wait_estimate_off_seconds=420,
        gpu_wait_estimate_warm_seconds=90, gpu_scale_in_seconds=900,
        gpu_cost_tag_key="CostCenter", gpu_cost_tag_value="gpu",
    )
    gc._state_cache.clear()
    return GpuController(repo, launcher, settings, family=family, now=lambda: NOW), repo, launcher


async def test_ensure_worker_launches_when_nothing_running():
    ctl, repo, launcher = make()
    state = await ctl.ensure_worker("job", "u1")
    assert state.worker_state == "starting"
    assert state.estimated_wait_seconds == 420
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
                   family="photogrammetry", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None, instance_id="i-1", started_processing_at=None, estimated_startup_seconds=None)
    repo.sessions_since = AsyncMock(return_value=[s])
    usage = await ctl.usage("u")
    assert usage.sessions[0].family == "photogrammetry"


async def test_usage_defaults_family_to_transcription_when_not_stamped():
    """The controller reads family off each session; a transcription-scoped repo's sessions
    carry family="transcription"."""
    ctl, repo, _ = make()
    repo.sessions_since = AsyncMock(return_value=[
        MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None,
                   family="transcription", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None, instance_id="i-1", started_processing_at=None, estimated_startup_seconds=None)
    ])
    u = await ctl.usage("u1")
    assert len(u.sessions) == 1
    assert u.sessions[0].family == "transcription"


async def test_usage_hours_is_zero_for_a_session_that_never_got_an_instance():
    """M7 / phantom-hours rule: a row with instance_id IS NULL cost nothing, matching
    GpuSessionRepository.hours_between's exclusion of such rows."""
    ctl, repo, _ = make()
    s = MagicMock(started_at=NOW, ended_at=NOW + timedelta(hours=1), reason="job", started_by="u",
                   end_reason=None, family="transcription", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None, instance_id=None, started_processing_at=None, estimated_startup_seconds=None)
    repo.sessions_since = AsyncMock(return_value=[s])
    u = await ctl.usage("u1")
    assert u.sessions[0].hours == 0.0


async def test_usage_hours_starts_the_clock_at_started_processing_at():
    """M7 / phantom-hours rule: the session's clock starts when the worker claimed it
    (started_processing_at), not on enqueue (started_at)."""
    ctl, repo, _ = make()
    s = MagicMock(
        started_at=NOW, started_processing_at=NOW + timedelta(minutes=10), ended_at=NOW + timedelta(hours=1),
        reason="job", started_by="u", end_reason=None, family="transcription", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None, instance_id="i-1",
        estimated_startup_seconds=None,
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


# ── measured startup estimates (item C) ───────────────────────────────────────────────────────

def startup(seconds: int, reason="job", started_at=NOW - timedelta(hours=1), booted_after=30,
            pull=None, container=None):
    """A completed job launch. booted_after: instance boot relative to started_at in seconds
    (positive → cold; a negative value large enough → warm; None → unknown)."""
    booted = started_at + timedelta(seconds=booted_after) if booted_after is not None else None
    return MagicMock(
        started_at=started_at, started_processing_at=started_at + timedelta(seconds=seconds),
        reason=reason, started_by="u", end_reason="idle", family="transcription", instance_id="i-1",
        ended_at=started_at + timedelta(hours=1), estimated_startup_seconds=None,
        instance_booted_at=booted,
        pull_started_at=started_at + timedelta(seconds=pull[0]) if pull else None,
        pull_stopped_at=started_at + timedelta(seconds=pull[1]) if pull else None,
        container_started_at=started_at + timedelta(seconds=container) if container is not None else None,
        task_arn="arn:task/old",
    )


async def test_off_estimate_is_the_median_of_recent_startups():
    ctl, *_ = make(startups=[startup(300), startup(500), startup(400)])
    state = await ctl.get_state()
    assert state.worker_state == "off"
    assert state.estimate_basis == "measured"
    assert state.estimate_samples == 3
    assert state.startup_estimate_seconds == 400
    assert state.estimated_wait_seconds == 400
    assert state.starting_since is None


async def test_fewer_than_three_samples_falls_back_to_the_config_default():
    ctl, *_ = make(startups=[startup(300), startup(500)])
    state = await ctl.get_state()
    assert state.estimate_basis == "default"
    assert state.estimate_samples == 2
    assert state.startup_estimate_seconds == 420
    assert state.estimated_wait_seconds == 420


async def test_starting_reports_remaining_time_and_starting_since():
    since = NOW - timedelta(seconds=150)
    ctl, *_ = make(tasks=["PENDING"], startups=[startup(400)] * 3, open_session=MagicMock(started_at=since, instance_booted_at=None, container_started_at=None, task_arn="arn:t"))
    state = await ctl.get_state()
    assert state.worker_state == "starting"
    assert state.starting_since == since
    assert state.startup_estimate_seconds == 400
    assert state.estimated_wait_seconds == 250


async def test_starting_remaining_clamps_at_zero():
    since = NOW - timedelta(seconds=999)
    ctl, *_ = make(tasks=["PENDING"], startups=[startup(400)] * 3, open_session=MagicMock(started_at=since, instance_booted_at=None, container_started_at=None, task_arn="arn:t"))
    state = await ctl.get_state()
    assert state.estimated_wait_seconds == 0


async def test_starting_without_an_open_row_reports_the_full_estimate():
    ctl, *_ = make(tasks=["PENDING"], startups=[startup(400)] * 3, open_session=None)
    state = await ctl.get_state()
    assert state.starting_since is None
    assert state.estimated_wait_seconds == 400


async def test_running_has_zero_wait_but_still_carries_the_estimate():
    ctl, *_ = make(tasks=["RUNNING"], startups=[startup(400)] * 3)
    state = await ctl.get_state()
    assert state.estimated_wait_seconds == 0
    assert state.startup_estimate_seconds == 400


async def test_ensure_worker_records_the_promised_estimate_on_the_ledger_row():
    ctl, repo, _ = make(startups=[startup(380), startup(420), startup(400)])
    state = await ctl.ensure_worker("job", "u1")
    assert state.estimated_wait_seconds == 400
    assert repo.create.await_args.kwargs["estimated_startup_seconds"] == 400


async def test_recent_startups_are_asked_for_the_controller_family():
    ctl, repo, _ = make(family="photogrammetry")
    await ctl.get_state()
    assert repo.recent_startups.await_args.args[0] == "photogrammetry"


async def test_usage_exposes_promised_vs_actual_startup_and_the_median():
    ctl, repo, _ = make(startups=[startup(300), startup(500), startup(400)])
    s = startup(360)
    s.estimated_startup_seconds = 400
    repo.sessions_since = AsyncMock(return_value=[s, startup(0)])
    u = await ctl.usage("u1")
    assert u.sessions[0].estimated_startup_seconds == 400
    assert u.sessions[0].actual_startup_seconds == 360
    assert u.startup_median_seconds == 400
    assert u.startup_samples == 3


async def test_usage_actual_startup_is_none_before_the_worker_claims():
    ctl, repo, _ = make()
    s = MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None,
                  family="transcription", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None, instance_id=None, started_processing_at=None,
                  estimated_startup_seconds=420)
    repo.sessions_since = AsyncMock(return_value=[s])
    u = await ctl.usage("u1")
    assert u.sessions[0].actual_startup_seconds is None
    assert u.sessions[0].estimated_startup_seconds == 420
    assert u.startup_median_seconds is None and u.startup_samples == 0


# ── stages, cold/warm (this round) ────────────────────────────────────────────────────────────

def open_row(since, container_started_at=None, booted_after=None, arn="arn:task/open"):
    booted = since + timedelta(seconds=booted_after) if booted_after is not None else None
    return MagicMock(started_at=since, task_arn=arn, container_started_at=container_started_at,
                     instance_booted_at=booted, started_processing_at=None, ended_at=None)


async def test_get_state_records_task_timings_for_the_open_session_once():
    since = NOW - timedelta(seconds=200)
    timings = {"pull_started_at": since + timedelta(seconds=100),
               "pull_stopped_at": since + timedelta(seconds=150),
               "container_started_at": since + timedelta(seconds=160)}
    ctl, repo, launcher = make(tasks=["RUNNING"], open_session=open_row(since), timings=timings)
    await ctl.get_state()
    launcher.task_timings.assert_called_once_with("arn:task/open")
    repo.record_timings.assert_awaited_once_with("arn:task/open", **timings)


async def test_get_state_does_not_refetch_timings_once_container_started_is_known():
    since = NOW - timedelta(seconds=200)
    row = open_row(since, container_started_at=since + timedelta(seconds=160))
    ctl, repo, launcher = make(tasks=["RUNNING"], open_session=row)
    await ctl.get_state()
    launcher.task_timings.assert_not_called()
    repo.record_timings.assert_not_awaited()


async def test_get_state_tolerates_missing_task_timings():
    ctl, repo, launcher = make(tasks=["PENDING"], open_session=open_row(NOW - timedelta(seconds=5)), timings=None)
    state = await ctl.get_state()
    assert state.worker_state == "starting"
    repo.record_timings.assert_not_awaited()


async def test_get_state_skips_timings_when_no_task_is_listed():
    ctl, repo, launcher = make(tasks=[], open_session=open_row(NOW))
    await ctl.get_state()
    launcher.task_timings.assert_not_called()


async def test_ensure_worker_never_fetches_timings():
    ctl, repo, launcher = make(tasks=["RUNNING"], open_session=open_row(NOW - timedelta(seconds=60)))
    await ctl.ensure_worker("job", "u1")
    launcher.task_timings.assert_not_called()


def test_startup_kind_cold_when_the_instance_booted_for_this_launch():
    assert gc.startup_kind(startup(300, booted_after=30)) == "cold"


def test_startup_kind_allows_60s_of_clock_slack():
    assert gc.startup_kind(startup(300, booted_after=-59)) == "cold"
    assert gc.startup_kind(startup(300, booted_after=-61)) == "warm"


def test_startup_kind_unknown_without_a_boot_time():
    assert gc.startup_kind(startup(300, booted_after=None)) is None


async def test_state_quotes_cold_median_by_default():
    cold = [startup(400, booted_after=30), startup(380, booted_after=30), startup(420, booted_after=30)]
    warm = [startup(70, booted_after=-3600), startup(80, booted_after=-3600), startup(90, booted_after=-3600)]
    ctl, *_ = make(startups=cold + warm)
    state = await ctl.get_state()
    assert state.start_kind == "cold"
    assert state.startup_estimate_seconds == 400
    assert state.estimate_basis == "measured" and state.estimate_samples == 3


async def test_state_quotes_warm_when_the_last_session_ended_inside_the_scale_in_window():
    cold = [startup(400, booted_after=30)] * 3
    warm = [startup(70, booted_after=-3600), startup(80, booted_after=-3600), startup(90, booted_after=-3600)]
    last = MagicMock(ended_at=NOW - timedelta(seconds=300))
    ctl, *_ = make(startups=cold + warm, last_ended=last)
    state = await ctl.get_state()
    assert state.start_kind == "warm"
    assert state.startup_estimate_seconds == 80
    assert state.estimate_samples == 3


async def test_state_quotes_cold_when_the_last_session_ended_outside_the_scale_in_window():
    last = MagicMock(ended_at=NOW - timedelta(seconds=901))
    ctl, *_ = make(startups=[startup(400, booted_after=30)] * 3, last_ended=last)
    state = await ctl.get_state()
    assert state.start_kind == "cold"


async def test_warm_default_applies_below_three_warm_samples():
    last = MagicMock(ended_at=NOW - timedelta(seconds=10))
    ctl, *_ = make(startups=[startup(400, booted_after=30)] * 3 + [startup(70, booted_after=-3600)], last_ended=last)
    state = await ctl.get_state()
    assert state.start_kind == "warm"
    assert state.estimate_basis == "default"
    assert state.startup_estimate_seconds == 90
    assert state.estimate_samples == 1


async def test_starting_on_a_known_warm_open_session_quotes_warm():
    since = NOW - timedelta(seconds=20)
    warm = [startup(70, booted_after=-3600), startup(80, booted_after=-3600), startup(90, booted_after=-3600)]
    ctl, *_ = make(tasks=["PENDING"], startups=[startup(400, booted_after=30)] * 3 + warm,
                   open_session=open_row(since, booted_after=-3600))
    state = await ctl.get_state()
    assert state.start_kind == "warm"
    assert state.estimated_wait_seconds == 60


async def test_ensure_worker_records_the_estimate_of_the_quoted_kind():
    last = MagicMock(ended_at=NOW - timedelta(seconds=10))
    warm = [startup(70, booted_after=-3600), startup(80, booted_after=-3600), startup(90, booted_after=-3600)]
    ctl, repo, _ = make(startups=[startup(400, booted_after=30)] * 3 + warm, last_ended=last)
    state = await ctl.ensure_worker("job", "u1")
    assert state.start_kind == "warm"
    assert repo.create.await_args.kwargs["estimated_startup_seconds"] == 80


def test_startup_stages_for_a_cold_start():
    s = startup(300, booted_after=100, pull=(200, 230), container=240)
    st = gc.startup_stages(s)
    assert (st.capacity, st.boot, st.pull, st.container, st.init) == (100, 100, 30, 10, 60)


def test_startup_stages_for_a_warm_start_have_no_capacity_or_boot():
    s = startup(60, booted_after=-3600, pull=(5, 20), container=25)
    st = gc.startup_stages(s)
    assert st.capacity is None and st.boot is None
    assert (st.pull, st.container, st.init) == (15, 5, 35)


def test_startup_stages_none_inputs_and_negatives():
    s = startup(300, booted_after=None, pull=None, container=None)
    assert gc.startup_stages(s) is None
    s = startup(300, booted_after=30, pull=(20, 25), container=200)   # boot before pull? clamp
    st = gc.startup_stages(s)
    assert st.boot == 0 and st.init == 100


async def test_usage_exposes_kind_stages_and_both_medians():
    cold = [startup(400, booted_after=30, pull=(200, 230), container=240)] * 3
    warm = [startup(70, booted_after=-3600), startup(80, booted_after=-3600), startup(90, booted_after=-3600)]
    ctl, repo, _ = make(startups=cold + warm)
    repo.sessions_since = AsyncMock(return_value=[cold[0], warm[0], startup(0, booted_after=None)])
    u = await ctl.usage("u1")
    assert u.sessions[0].kind == "cold" and u.sessions[0].stages.capacity == 30
    assert u.sessions[1].kind == "warm" and u.sessions[1].stages is None
    assert u.sessions[2].kind is None and u.sessions[2].stages is None
    assert (u.cold_median_seconds, u.cold_samples) == (400, 3)
    assert (u.warm_median_seconds, u.warm_samples) == (80, 3)
    assert (u.startup_median_seconds, u.startup_samples) == (400, 3)


async def test_usage_warm_median_is_none_below_three_samples():
    ctl, repo, _ = make(startups=[startup(400, booted_after=30)] * 3 + [startup(70, booted_after=-3600)])
    u = await ctl.usage("u1")
    assert u.warm_median_seconds is None and u.warm_samples == 1


async def test_ensure_worker_stamps_the_job_it_launched_for():
    """The usage panel links each startup to the scan/transcript that triggered it."""
    ctl, repo, _ = make()
    jid = uuid.uuid4()
    await ctl.ensure_worker("job", "u1", job_id=jid)
    assert repo.create.await_args.kwargs["job_id"] == jid


async def test_ensure_worker_without_a_job_stamps_none():
    ctl, repo, _ = make()
    await ctl.ensure_worker("warm", "u1")
    assert repo.create.await_args.kwargs["job_id"] is None


async def test_usage_attaches_the_launching_job_to_each_session():
    ctl, repo, _ = make(family="photogrammetry")
    jid = uuid.uuid4()
    s = MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None,
                  family="photogrammetry", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None,
                  container_started_at=None, instance_id="i-1", started_processing_at=None,
                  estimated_startup_seconds=None, job_id=jid)
    repo.sessions_since = AsyncMock(return_value=[s])
    repo.job_labels = AsyncMock(return_value={jid: JobLabel("Sample scan", NOW)})
    usage = await ctl.usage("u")
    repo.job_labels.assert_awaited_once_with([s])
    assert usage.sessions[0].job.id == jid
    assert usage.sessions[0].job.name == "Sample scan"


async def test_usage_session_without_a_job_or_with_a_deleted_job_has_job_none():
    ctl, repo, _ = make()
    gone = uuid.uuid4()
    rows = [
        MagicMock(started_at=NOW, ended_at=None, reason="warm", started_by="u", end_reason=None, family="transcription",
                  instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None,
                  instance_id="i-1", started_processing_at=None, estimated_startup_seconds=None, job_id=None),
        MagicMock(started_at=NOW, ended_at=None, reason="job", started_by="u", end_reason=None, family="transcription",
                  instance_booted_at=None, pull_started_at=None, pull_stopped_at=None, container_started_at=None,
                  instance_id="i-1", started_processing_at=None, estimated_startup_seconds=None, job_id=gone),
    ]
    repo.sessions_since = AsyncMock(return_value=rows)
    usage = await ctl.usage("u")
    assert [x.job for x in usage.sessions] == [None, None]


async def test_usage_attaches_a_job_only_to_the_callers_own_sessions():
    """/gpu/usage is visible to every user (one pool, one budget), but a scan's name is another
    user's content and its link would dead-end (jobs are user-scoped) — so only your own launches
    carry a job."""
    ctl, repo, _ = make(family="photogrammetry")
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    def row(uid, jid):
        return MagicMock(started_at=NOW, ended_at=None, reason="job", started_by=uid, end_reason=None,
                         family="photogrammetry", instance_booted_at=None, pull_started_at=None, pull_stopped_at=None,
                         container_started_at=None, instance_id="i-1", started_processing_at=None,
                         estimated_startup_seconds=None, job_id=jid)
    repo.sessions_since = AsyncMock(return_value=[row("me", mine), row("someone-else", theirs)])
    repo.job_labels = AsyncMock(return_value={mine: JobLabel("Mine", NOW), theirs: JobLabel("Theirs", NOW)})
    usage = await ctl.usage("me")
    assert usage.sessions[0].job.name == "Mine"
    assert usage.sessions[1].job is None
    assert [s.job_id for s in repo.job_labels.await_args.args[0]] == [mine]    # not even looked up
