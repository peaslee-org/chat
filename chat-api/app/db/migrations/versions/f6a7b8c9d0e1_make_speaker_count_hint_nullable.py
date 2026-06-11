"""make speaker_count_hint nullable

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-06 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the column default first, then allow nulls.
    # Existing rows keep their current integer value; new rows without a hint store NULL.
    op.alter_column(
        'transcription_jobs',
        'speaker_count_hint',
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    # Restore NOT NULL. Back-fill NULLs with 10 (the safe maximum) before adding constraint.
    op.execute("UPDATE transcription_jobs SET speaker_count_hint = 10 WHERE speaker_count_hint IS NULL")
    op.alter_column(
        'transcription_jobs',
        'speaker_count_hint',
        existing_type=sa.Integer(),
        nullable=False,
        server_default='2',
    )
