from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

WorkerState = Literal["off", "starting", "running"]
GpuFamily = Literal["transcription", "photogrammetry"]
StartupKind = Literal["cold", "warm"]   # cold: an instance booted for the launch · warm: one was already up


class GpuStateResponse(BaseModel):
    worker_state: WorkerState
    estimated_wait_seconds: int                 # running 0 · off = startup_estimate · starting = remaining
    warm_until: Optional[datetime] = None       # when the idle clock can next fire (if known)
    notice: Optional[str] = None                # cap or launch problem, shown verbatim in the UI
    starting_since: Optional[datetime] = None   # the open session's started_at while starting
    startup_estimate_seconds: int = 0           # full expected off→ready duration
    estimate_basis: Literal["measured", "default"] = "default"
    estimate_samples: int = 0                   # startups the median was taken over
    start_kind: StartupKind = "cold"            # which kind the estimate above describes


class StartupStages(BaseModel):
    """Seconds per stage of one launch; None when a timestamp is missing (or the stage does not
    apply — capacity/boot on a warm start, where the instance predates the launch)."""
    capacity: Optional[int] = None    # RunTask → instance boot
    boot: Optional[int] = None        # instance boot → image pull start (agent up, task placed)
    pull: Optional[int] = None        # image pull
    container: Optional[int] = None   # pull done → container running
    init: Optional[int] = None        # container running → worker's first claim


class GpuSessionSummary(BaseModel):
    started_at: datetime
    ended_at: Optional[datetime]
    reason: str
    started_by: str
    end_reason: Optional[str]
    hours: float
    family: str = "transcription"
    estimated_startup_seconds: Optional[int] = None   # what the UI promised at launch
    actual_startup_seconds: Optional[int] = None      # started_processing_at − started_at
    kind: Optional[StartupKind] = None                # None until the worker reported the boot time
    stages: Optional[StartupStages] = None

    model_config = {"from_attributes": True}


class GpuUsageResponse(BaseModel):
    today_hours: float
    month_hours: float
    daily_cap_hours: float
    monthly_cap_hours: float
    warms_today_for_user: int
    warm_cap_per_user_per_day: int
    estimated_month_cost_usd: float
    hourly_rate_usd: float
    actual_month_to_date_usd: Optional[float] = None
    actual_fetched_at: Optional[datetime] = None
    sessions: List[GpuSessionSummary]
    startup_median_seconds: Optional[int] = None      # == cold_median_seconds (kept for compatibility)
    startup_samples: int = 0                          # == cold_samples
    cold_median_seconds: Optional[int] = None
    cold_samples: int = 0
    warm_median_seconds: Optional[int] = None
    warm_samples: int = 0
