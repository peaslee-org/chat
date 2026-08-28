"""add gpu_sessions release columns (POST /gpu/release)

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gpu_sessions", sa.Column("release_mode", sa.String(10), nullable=True))
    op.add_column("gpu_sessions", sa.Column("release_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("gpu_sessions", sa.Column("release_requested_by", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("gpu_sessions", "release_requested_by")
    op.drop_column("gpu_sessions", "release_requested_at")
    op.drop_column("gpu_sessions", "release_mode")
