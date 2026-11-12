"""Shared durable retry policy for ingestion work."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.ingestion.messages import (
    INGESTION_JOB_AGGREGATE,
    INGESTION_REQUESTED_EVENT,
    SUPPORTED_SCHEMA_VERSION,
)
from backend.models import Document, IngestionJob, OutboxEvent

MAX_RETRY_DELAY = timedelta(minutes=5)


def exponential_retry_delay(attempt_number: int) -> timedelta:
    """Return bounded exponential backoff for a completed attempt."""
    if attempt_number <= 0:
        raise ValueError("attempt_number must be positive")
    return min(timedelta(seconds=5 * (2 ** (attempt_number - 1))), MAX_RETRY_DELAY)


def add_ingestion_retry_event(
    db: Session,
    job: IngestionJob,
    document: Document,
    *,
    available_at: datetime,
) -> None:
    """Add the next delivery to the same transaction as retry state."""
    db.add(
        OutboxEvent(
            event_type=INGESTION_REQUESTED_EVENT,
            aggregate_type=INGESTION_JOB_AGGREGATE,
            aggregate_id=job.id,
            schema_version=SUPPORTED_SCHEMA_VERSION,
            payload={
                "job_id": str(job.id),
                "document_id": str(document.id),
                "purpose": job.purpose,
            },
            available_at=available_at,
        )
    )
