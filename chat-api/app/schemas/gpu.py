from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

WorkerState = Literal["off", "starting", "running"]
GpuFamily = Literal["transcription", "photogrammetry"]


class GpuStateResponse(BaseModel):
    worker_state: WorkerState
    estimated_wait_seconds: int
    warm_until: Optional[datetime] = None       # when the idle clock can next fire (if known)
    notice: Optional[str] = None                # cap or launch problem, shown verbatim in the UI


class GpuSessionSummary(BaseModel):
    started_at: datetime
    ended_at: Optional[datetime]
    reason: str
    started_by: str
    end_reason: Optional[str]
    hours: float
    family: str = "transcription"

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
