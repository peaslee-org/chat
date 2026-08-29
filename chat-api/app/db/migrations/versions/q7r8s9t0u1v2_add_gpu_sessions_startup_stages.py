"""add gpu_sessions startup stage timestamps (instance boot, image pull, container start)

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("instance_booted_at", "pull_started_at", "pull_stopped_at", "container_started_at")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("gpu_sessions", sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("gpu_sessions", name)
