"""add transcription tables

Revision ID: a1b2c3d4e5f6
Revises: 5c8e1a2d4f6b
Create Date: 2026-03-03 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5c8e1a2d4f6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        'speaker_profiles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(length=256), nullable=False),
        sa.Column('speaker_name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_speaker_profiles_user_id', 'speaker_profiles', ['user_id'], unique=False)

    op.create_table(
        'speaker_samples',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('speaker_profile_id', sa.UUID(), nullable=False),
        sa.Column('s3_key', sa.String(length=1024), nullable=False),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('processing', 'ready', 'failed', name='sample_status'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['speaker_profile_id'], ['speaker_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_speaker_samples_speaker_profile_id', 'speaker_samples', ['speaker_profile_id'], unique=False)
    # pgvector column — must be added after the extension is created
    op.execute("ALTER TABLE speaker_samples ADD COLUMN embedding vector(256)")
    op.execute(
        "CREATE INDEX ix_speaker_samples_embedding "
        "ON speaker_samples USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        'transcription_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(length=256), nullable=False),
        sa.Column('audio_s3_key', sa.String(length=1024), nullable=False),
        sa.Column('aws_transcribe_job_name', sa.String(length=256), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'transcribing', 'matching', 'complete', 'failed', name='job_status'),
            nullable=False,
        ),
        sa.Column('speaker_count_hint', sa.Integer(), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column('transcribe_output_s3_key', sa.String(length=1024), nullable=True),
        sa.Column('result_s3_key', sa.String(length=1024), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_transcription_jobs_user_id', 'transcription_jobs', ['user_id'], unique=False)

    op.create_table(
        'transcript_segments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('speaker_profile_id', sa.UUID(), nullable=True),
        sa.Column('anonymous_label', sa.String(length=50), nullable=False),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['transcription_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['speaker_profile_id'], ['speaker_profiles.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_transcript_segments_job_start',
        'transcript_segments', ['job_id', 'start_time'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_transcript_segments_job_start', table_name='transcript_segments')
    op.drop_table('transcript_segments')

    op.drop_index('ix_transcription_jobs_user_id', table_name='transcription_jobs')
    op.drop_table('transcription_jobs')

    op.execute("DROP INDEX IF EXISTS ix_speaker_samples_embedding")
    op.drop_index('ix_speaker_samples_speaker_profile_id', table_name='speaker_samples')
    op.drop_table('speaker_samples')

    op.drop_index('ix_speaker_profiles_user_id', table_name='speaker_profiles')
    op.drop_table('speaker_profiles')

    op.execute("DROP TYPE IF EXISTS sample_status")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE")
