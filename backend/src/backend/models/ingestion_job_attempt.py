"""One durable worker execution of an ingestion job."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class IngestionJobAttempt(Base):
    __tablename__ = "ingestion_job_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_number > 0",
            name="ck_ingestion_job_attempts_number_positive",
        ),
        CheckConstraint(
            "length(worker_id) BETWEEN 1 AND 255",
            name="ck_ingestion_job_attempts_worker_id_length",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'ABANDONED', 'CANCELLED')",
            name="ck_ingestion_job_attempts_status",
        ),
        CheckConstraint(
            "current_stage IS NULL OR length(current_stage) BETWEEN 1 AND 64",
            name="ck_ingestion_job_attempts_stage_length",
        ),
        UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_ingestion_job_attempts_job_number",
        ),
        Index(
            "ix_ingestion_job_attempts_job_status",
            "job_id",
            "status",
        ),
        Index(
            "ix_ingestion_job_attempts_expired_lease",
            "status",
            "lease_expires_at",
        ),
        Index(
            "uq_ingestion_job_attempts_one_running",
            "job_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
            sqlite_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="RESTRICT"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), default="RUNNING", server_default="RUNNING"
    )
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
