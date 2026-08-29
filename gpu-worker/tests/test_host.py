"""boot_time: the instance's boot from /proc/uptime (the container shares the host kernel)."""
from datetime import datetime, timedelta, timezone

from gpu_worker.host import boot_time

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_boot_time_is_now_minus_uptime(tmp_path):
    p = tmp_path / "uptime"
    p.write_text("350.25 1400.00\n")
    assert boot_time(NOW, path=p) == NOW - timedelta(seconds=350.25)


def test_unreadable_uptime_is_none(tmp_path):
    assert boot_time(NOW, path=tmp_path / "missing") is None
    bad = tmp_path / "bad"
    bad.write_text("not a number\n")
    assert boot_time(NOW, path=bad) is None
