"""add is_public to conversations, transcription_jobs, photogrammetry_jobs (public demo opt-in)

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("conversations", "transcription_jobs", "photogrammetry_jobs")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "is_public")
