"""GPU ledger: one gpu_sessions row per worker task launch; daily Cost Explorer snapshots."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GpuSession(Base):
    __tablename__ = "gpu_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_arn: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    instance_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_by: Mapped[str] = mapped_column(String(255), nullable=False)   # cognito sub | "system"
    reason: Mapped[str] = mapped_column(String(20), nullable=False)        # job | warm | resume
    family: Mapped[str] = mapped_column(String(32), nullable=False, server_default="transcription")  # transcription | photogrammetry
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_processing_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    warm_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[Optional[str]] = mapped_column(String(20))  # idle | max_lifetime | spot_interruption | error | unknown (reconciled)


class GpuCostSnapshot(Base):
    __tablename__ = "gpu_cost_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)          # "2026-09"
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
