"""Transactional events waiting to be published to the message broker."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "length(event_type) BETWEEN 1 AND 100",
            name="ck_outbox_events_event_type_length",
        ),
        CheckConstraint(
            "length(aggregate_type) BETWEEN 1 AND 64",
            name="ck_outbox_events_aggregate_type_length",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_outbox_events_schema_version_positive",
        ),
        CheckConstraint(
            "publish_attempts >= 0",
            name="ck_outbox_events_publish_attempts_nonnegative",
        ),
        Index(
            "ix_outbox_events_due",
            "published_at",
            "available_at",
        ),
        Index(
            "ix_outbox_events_expired_claim",
            "published_at",
            "claim_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
