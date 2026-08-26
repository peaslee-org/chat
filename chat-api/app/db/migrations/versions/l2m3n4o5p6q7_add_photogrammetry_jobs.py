"""add photogrammetry_jobs

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_ENUM = postgresql.ENUM(
    "pending", "queued", "processing", "complete", "failed",
    name="photogrammetry_job_status",
    create_type=False,
)


def upgrade() -> None:
    STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "photogrammetry_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("input_prefix", sa.String(1024), nullable=False),
        sa.Column("mesh_s3_key", sa.String(1024), nullable=True),
        sa.Column("preview_s3_key", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_photogrammetry_jobs_user_id", "photogrammetry_jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_photogrammetry_jobs_user_id", table_name="photogrammetry_jobs")
    op.drop_table("photogrammetry_jobs")
    STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
