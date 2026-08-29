from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

WorkerState = Literal["off", "starting", "running"]
GpuFamily = Literal["transcription", "photogrammetry"]


class GpuStateResponse(BaseModel):
    worker_state: WorkerState
    estimated_wait_seconds: int                 # running 0 · off = startup_estimate · starting = remaining
    warm_until: Optional[datetime] = None       # when the idle clock can next fire (if known)
    notice: Optional[str] = None                # cap or launch problem, shown verbatim in the UI
    starting_since: Optional[datetime] = None   # the open session's started_at while starting
    startup_estimate_seconds: int = 0           # full expected off→ready duration
    estimate_basis: Literal["measured", "default"] = "default"
    estimate_samples: int = 0                   # startups the median was taken over


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
    startup_median_seconds: Optional[int] = None      # median over the family's recent job starts
    startup_samples: int = 0
