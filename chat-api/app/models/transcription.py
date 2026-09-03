import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, JSON, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class SpeakerProfile(UUIDMixin, Base):
    __tablename__ = "speaker_profiles"

    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    speaker_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    samples: Mapped[list["SpeakerSample"]] = relationship(
        back_populates="speaker_profile",
        cascade="all, delete-orphan",
    )


class SpeakerSample(UUIDMixin, Base):
    __tablename__ = "speaker_samples"

    speaker_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("processing", "ready", "failed", name="sample_status"),
        nullable=False,
        default="processing",
    )
    embedding: Mapped[Optional[list]] = mapped_column(Vector(192), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    speaker_profile: Mapped["SpeakerProfile"] = relationship(back_populates="samples")


class TranscriptionJob(UUIDMixin, Base):
    __tablename__ = "transcription_jobs"

    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    audio_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    aws_transcribe_job_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "pending", "transcribing", "matching", "complete", "failed",
            name="job_status",
        ),
        nullable=False,
        default="pending",
    )
    speaker_count_hint: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en-US")
    transcribe_output_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_speaker_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_segment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    speaker_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class TranscriptSegment(UUIDMixin, Base):
    __tablename__ = "transcript_segments"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    speaker_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    anonymous_label: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    job: Mapped["TranscriptionJob"] = relationship(back_populates="segments")
    speaker_profile: Mapped[Optional["SpeakerProfile"]] = relationship()

    __table_args__ = (
        Index("ix_transcript_segments_job_start", "job_id", "start_time"),
    )


class TranscriptTurnDistance(UUIDMixin, Base):
    __tablename__ = "transcript_turn_distances"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speaker_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    cosine_dist: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_transcript_turn_distances_job", "job_id"),
    )


class CompiledTranscript(UUIDMixin, Base):
    """One per job: the turn list produced by `compile_turns` plus the settings it used."""
    __tablename__ = "compiled_transcripts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    turns: Mapped[list] = mapped_column(JSON, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TranscriptionJobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # api | worker
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_job_events_job_occurred", "job_id", "occurred_at"),
    )
