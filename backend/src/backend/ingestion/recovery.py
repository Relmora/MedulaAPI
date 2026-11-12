"""Recover ingestion jobs whose worker lease expired."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from backend.ingestion.claim import Clock, SessionFactory
from backend.ingestion.retry import add_ingestion_retry_event, exponential_retry_delay
from backend.models import Document, IngestionJob, IngestionJobAttempt

LEASE_EXPIRED_CODE = "WORKER_LEASE_EXPIRED"
LEASE_EXPIRED_MESSAGE = "Worker lease expired before the attempt completed"
RetryDelay = Callable[[int], timedelta]


@dataclass(frozen=True)
class RecoveryBatchResult:
    recovered: int
    retries_scheduled: int
    exhausted: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionLeaseRecovery:
    """Convert abandoned processing leases into durable retries or failures."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        batch_size: int = 50,
        clock: Clock = _utc_now,
        retry_delay: RetryDelay = exponential_retry_delay,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._clock = clock
        self._retry_delay = retry_delay

    def recover_batch(self) -> RecoveryBatchResult:
        now = self._aware_now()
        retries_scheduled = 0
        exhausted = 0

        with self._session_factory() as db, db.begin():
            jobs = list(
                db.scalars(
                    select(IngestionJob)
                    .where(
                        IngestionJob.status == "PROCESSING",
                        IngestionJob.lease_expires_at.is_not(None),
                        IngestionJob.lease_expires_at <= now,
                    )
                    .order_by(IngestionJob.lease_expires_at, IngestionJob.id)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for job in jobs:
                # A heartbeat may have renewed the row while recovery waited for its lock.
                if not self._is_expired(job.lease_expires_at, now):
                    continue
                attempt = db.scalar(
                    select(IngestionJobAttempt)
                    .where(
                        IngestionJobAttempt.job_id == job.id,
                        IngestionJobAttempt.status == "RUNNING",
                    )
                    .order_by(IngestionJobAttempt.attempt_number.desc())
                    .with_for_update()
                )
                document = db.scalar(
                    select(Document)
                    .where(Document.id == job.document_id)
                    .with_for_update()
                )
                if document is None:
                    raise RuntimeError(
                        f"ingestion job {job.id} references a missing document"
                    )

                if attempt is not None:
                    attempt.status = "ABANDONED"
                    attempt.heartbeat_at = now
                    attempt.lease_expires_at = now
                    attempt.finished_at = now
                    attempt.failure_class = "TRANSIENT"
                    attempt.failure_code = LEASE_EXPIRED_CODE
                    attempt.failure_message = LEASE_EXPIRED_MESSAGE

                retry_scheduled = job.attempt_count < job.max_attempts
                retry_at = None
                if retry_scheduled:
                    delay = self._retry_delay(job.attempt_count)
                    if delay <= timedelta(0):
                        raise ValueError("retry_delay must return a positive duration")
                    retry_at = now + delay
                    retries_scheduled += 1
                else:
                    exhausted += 1

                job.status = "RETRY_SCHEDULED" if retry_scheduled else "FAILED"
                job.next_attempt_at = retry_at
                job.claimed_by = None
                job.lease_expires_at = None
                job.last_error_code = LEASE_EXPIRED_CODE
                job.finished_at = None if retry_scheduled else now
                job.updated_at = now

                document.processing_status = "QUEUED" if retry_scheduled else "FAILED"
                document.failure_code = LEASE_EXPIRED_CODE
                document.processed_at = None if retry_scheduled else now
                document.updated_at = now

                if retry_at is not None:
                    add_ingestion_retry_event(
                        db,
                        job,
                        document,
                        available_at=retry_at,
                    )

        return RecoveryBatchResult(
            recovered=retries_scheduled + exhausted,
            retries_scheduled=retries_scheduled,
            exhausted=exhausted,
        )

    @staticmethod
    def _is_expired(value: datetime | None, now: datetime) -> bool:
        if value is None:
            return False
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value <= now

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
