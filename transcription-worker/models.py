"""
SQLAlchemy models duplicated from chat-api for deployment independence.
Uses classic Column-based style; pgvector type added via raw column definition.
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class SpeakerProfile(Base):
    __tablename__ = "speaker_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(256), nullable=False, index=True)
    speaker_name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    samples = relationship("SpeakerSample", back_populates="speaker_profile", lazy="select")


class SpeakerSample(Base):
    __tablename__ = "speaker_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    speaker_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    s3_key = Column(String(1024), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    status = Column(
        Enum("processing", "ready", "failed", name="sample_status"),
        nullable=False,
        default="processing",
    )
    embedding = Column(Vector(192), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    speaker_profile = relationship("SpeakerProfile", back_populates="samples")


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(256), nullable=False, index=True)
    audio_s3_key = Column(String(1024), nullable=False)
    aws_transcribe_job_name = Column(String(256), nullable=True)
    status = Column(
        Enum("pending", "transcribing", "matching", "complete", "failed", name="job_status"),
        nullable=False,
        default="pending",
    )
    speaker_count_hint = Column(Integer, nullable=False, default=2)
    language = Column(String(20), nullable=False, default="en-US")
    transcribe_output_s3_key = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)
    matched_speaker_count = Column(Integer, nullable=True)
    total_segment_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    segments = relationship(
        "TranscriptSegment", back_populates="job", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    speaker_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    anonymous_label = Column(String(50), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)

    job = relationship("TranscriptionJob", back_populates="segments")
    speaker_profile = relationship("SpeakerProfile")

    __table_args__ = (
        Index("ix_transcript_segments_job_start", "job_id", "start_time"),
    )


class TranscriptTurnDistance(Base):
    __tablename__ = "transcript_turn_distances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    cosine_dist = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_transcript_turn_distances_job", "job_id"),
    )


class TranscriptionJobEvent(Base):
    __tablename__ = "job_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source = Column(String(20), nullable=False)  # api | worker
    event = Column(String(100), nullable=False)
    detail = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_job_events_job_occurred", "job_id", "occurred_at"),
    )


class GpuSession(Base):
    """One row per worker task launch; created by chat-api's RunTask, completed by the worker."""
    __tablename__ = "gpu_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_arn = Column(String(255), nullable=False, unique=True)
    instance_id = Column(String(32), nullable=True)
    started_by = Column(String(255), nullable=False)          # cognito sub or "system"
    reason = Column(String(20), nullable=False)               # job | warm | resume
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_processing_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    warm_until = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(20), nullable=True)            # idle | max_lifetime | spot_interruption | error
