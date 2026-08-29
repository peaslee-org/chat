"""add gpu_sessions.estimated_startup_seconds (the startup estimate promised at launch)

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gpu_sessions", sa.Column("estimated_startup_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("gpu_sessions", "estimated_startup_seconds")
