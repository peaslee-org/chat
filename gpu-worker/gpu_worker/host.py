"""Host facts visible from inside the container."""
from datetime import datetime, timedelta
from pathlib import Path

_UPTIME = Path("/proc/uptime")


def boot_time(now: datetime, path: Path = _UPTIME) -> datetime | None:
    """When the EC2 instance booted: now − /proc/uptime. The container shares the host kernel,
    so this is the instance's uptime, not the container's. None when it can't be read."""
    try:
        uptime = float(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return now - timedelta(seconds=uptime)
