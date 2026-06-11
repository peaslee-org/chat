"""rename transcript_turn_matches to transcript_turn_distances

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_transcript_turn_matches_job', table_name='transcript_turn_matches')
    op.rename_table('transcript_turn_matches', 'transcript_turn_distances')
    op.create_index('ix_transcript_turn_distances_job', 'transcript_turn_distances', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_transcript_turn_distances_job', table_name='transcript_turn_distances')
    op.rename_table('transcript_turn_distances', 'transcript_turn_matches')
    op.create_index('ix_transcript_turn_matches_job', 'transcript_turn_matches', ['job_id'])
