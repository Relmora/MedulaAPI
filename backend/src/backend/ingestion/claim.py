"""Atomically claim one ingestion job and create its worker attempt."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ingestion.messages import IngestionRequestedMessage
from backend.models import Document, IngestionJob, IngestionJobAttempt

DEFAULT_LEASE_TTL = timedelta(seconds=60)
INITIAL_STAGE = "VALIDATE_SOURCE"
MAX_WORKER_ID_LENGTH = 255

SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]


class ClaimDisposition(StrEnum):
    CLAIMED = "CLAIMED"
    OBSOLETE = "OBSOLETE"


@dataclass(frozen=True)
class ClaimedIngestionJob:
    job_id: UUID
    document_id: UUID
    attempt_id: UUID
    attempt_number: int
    worker_id: str
    current_stage: str
    lease_expires_at: datetime
    event_id: UUID


@dataclass(frozen=True)
class ClaimResult:
    disposition: ClaimDisposition
    claimed: ClaimedIngestionJob | None = None
    reason: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionJobClaimer:
    """Serialize job ownership in PostgreSQL before processing begins."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        clock: Clock = _utc_now,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self._session_factory = session_factory
        self._lease_ttl = lease_ttl
        self._clock = clock

    def claim(
        self,
        message: IngestionRequestedMessage,
        *,
        worker_id: str,
    ) -> ClaimResult:
        normalized_worker_id = worker_id.strip()
        if not normalized_worker_id:
            raise ValueError("worker_id must be nonempty")
        if len(normalized_worker_id) > MAX_WORKER_ID_LENGTH:
            raise ValueError(
                f"worker_id must not exceed {MAX_WORKER_ID_LENGTH} characters"
            )

        now = self._aware_now()
        lease_expires_at = now + self._lease_ttl

        with self._session_factory() as db, db.begin():
            job = db.scalar(
                select(IngestionJob)
                .where(IngestionJob.id == message.job_id)
                .with_for_update()
            )
            if job is None:
                return ClaimResult(ClaimDisposition.OBSOLETE, reason="JOB_NOT_FOUND")
            if job.document_id != message.document_id:
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="DOCUMENT_ID_MISMATCH",
                )
            if job.purpose != message.purpose:
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="PURPOSE_MISMATCH",
                )
            if not self._is_runnable(job, now):
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="JOB_NOT_RUNNABLE",
                )
            if job.attempt_count >= job.max_attempts:
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="ATTEMPT_BUDGET_EXHAUSTED",
                )

            document = db.scalar(
                select(Document).where(Document.id == job.document_id).with_for_update()
            )
            if document is None:
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="DOCUMENT_NOT_FOUND",
                )
            if document.processing_status not in {"QUEUED", "PROCESSING"}:
                return ClaimResult(
                    ClaimDisposition.OBSOLETE,
                    reason="DOCUMENT_NOT_RUNNABLE",
                )

            attempt_number = job.attempt_count + 1
            attempt = IngestionJobAttempt(
                job_id=job.id,
                attempt_number=attempt_number,
                worker_id=normalized_worker_id,
                status="RUNNING",
                current_stage=INITIAL_STAGE,
                started_at=now,
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
            )
            db.add(attempt)

            job.status = "PROCESSING"
            job.current_stage = INITIAL_STAGE
            job.attempt_count = attempt_number
            job.next_attempt_at = None
            job.claimed_by = normalized_worker_id
            job.lease_expires_at = lease_expires_at
            job.last_error_code = None
            job.started_at = job.started_at or now
            job.finished_at = None
            job.updated_at = now
            document.processing_status = "PROCESSING"
            document.failure_code = None
            document.updated_at = now
            db.flush()

            claimed = ClaimedIngestionJob(
                job_id=job.id,
                document_id=document.id,
                attempt_id=attempt.id,
                attempt_number=attempt_number,
                worker_id=normalized_worker_id,
                current_stage=INITIAL_STAGE,
                lease_expires_at=lease_expires_at,
                event_id=message.event_id,
            )

        return ClaimResult(ClaimDisposition.CLAIMED, claimed=claimed)

    @staticmethod
    def _is_runnable(job: IngestionJob, now: datetime) -> bool:
        if job.status == "QUEUED":
            return True
        if job.status != "RETRY_SCHEDULED" or job.next_attempt_at is None:
            return False
        next_attempt_at = job.next_attempt_at
        if next_attempt_at.tzinfo is None or next_attempt_at.utcoffset() is None:
            next_attempt_at = next_attempt_at.replace(tzinfo=UTC)
        return next_attempt_at <= now

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
