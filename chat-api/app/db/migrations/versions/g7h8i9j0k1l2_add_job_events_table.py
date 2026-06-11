"""add job_events table

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-11 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', UUID(as_uuid=True), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('event', sa.String(100), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['transcription_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_events_job_occurred', 'job_events', ['job_id', 'occurred_at'])


def downgrade() -> None:
    op.drop_index('ix_job_events_job_occurred', table_name='job_events')
    op.drop_table('job_events')
