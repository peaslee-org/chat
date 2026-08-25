"""add gpu_sessions and gpu_cost_snapshots

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gpu_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_arn", sa.String(255), nullable=False, unique=True),
        sa.Column("instance_id", sa.String(32), nullable=True),
        sa.Column("started_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_processing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warm_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(20), nullable=True),
    )
    op.create_index("ix_gpu_sessions_started_at", "gpu_sessions", ["started_at"])
    op.create_table(
        "gpu_cost_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_gpu_cost_snapshots_month_fetched", "gpu_cost_snapshots", ["month", "fetched_at"])


def downgrade() -> None:
    op.drop_table("gpu_cost_snapshots")
    op.drop_table("gpu_sessions")
