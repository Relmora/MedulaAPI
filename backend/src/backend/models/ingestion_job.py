"""Durable ingestion work accepted for an immutable document upload."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "length(purpose) BETWEEN 1 AND 64",
            name="ck_ingestion_jobs_purpose_length",
        ),
        CheckConstraint(
            "length(pipeline_version) BETWEEN 1 AND 64",
            name="ck_ingestion_jobs_pipeline_version_length",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'RETRY_SCHEDULED', "
            "'SUCCEEDED', 'FAILED', 'CANCELLING', 'CANCELLED')",
            name="ck_ingestion_jobs_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_ingestion_jobs_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="ck_ingestion_jobs_max_attempts_positive",
        ),
        CheckConstraint(
            "attempt_count <= max_attempts",
            name="ck_ingestion_jobs_attempt_budget",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_ingestion_jobs_idempotency_key",
        ),
        Index(
            "ix_ingestion_jobs_runnable",
            "status",
            "next_attempt_at",
        ),
        Index(
            "ix_ingestion_jobs_expired_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(64))
    pipeline_version: Mapped[str] = mapped_column(String(64))
    source_storage_version: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="QUEUED", server_default="QUEUED"
    )
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
