"""Orchestrate durable ingestion stages after a worker claims a job."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select

from backend.ingestion.claim import ClaimedIngestionJob, SessionFactory
from backend.ingestion.stages import (
    SourceValidationError,
    SourceValidator,
    ValidatedSource,
)
from backend.models import Document, IngestionJob, IngestionJobAttempt

Clock = Callable[[], datetime]
MAX_FAILURE_MESSAGE_LENGTH = 4000


class PipelineDisposition(StrEnum):
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    SOURCE_REJECTED = "SOURCE_REJECTED"


@dataclass(frozen=True)
class PipelineResult:
    disposition: PipelineDisposition
    source: ValidatedSource | None = None
    error_code: str | None = None


class LostAttemptOwnershipError(RuntimeError):
    """The attempt can no longer be mutated by this worker."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionPipeline:
    """Run implemented stages and durably record permanent source rejection."""

    def __init__(
        self,
        session_factory: SessionFactory,
        source_validator: SourceValidator,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._source_validator = source_validator
        self._clock = clock

    def process(self, claimed: ClaimedIngestionJob) -> PipelineResult:
        try:
            source = self._source_validator.validate(claimed)
        except SourceValidationError as error:
            self._record_source_rejection(claimed, error)
            return PipelineResult(
                PipelineDisposition.SOURCE_REJECTED,
                error_code=error.code,
            )
        return PipelineResult(
            PipelineDisposition.SOURCE_VALIDATED,
            source=source,
        )

    def _record_source_rejection(
        self,
        claimed: ClaimedIngestionJob,
        error: SourceValidationError,
    ) -> None:
        now = self._aware_now()
        with self._session_factory() as db, db.begin():
            job = db.scalar(
                select(IngestionJob)
                .where(IngestionJob.id == claimed.job_id)
                .with_for_update()
            )
            attempt = db.scalar(
                select(IngestionJobAttempt)
                .where(IngestionJobAttempt.id == claimed.attempt_id)
                .with_for_update()
            )
            document = db.scalar(
                select(Document)
                .where(Document.id == claimed.document_id)
                .with_for_update()
            )
            if (
                job is None
                or attempt is None
                or document is None
                or attempt.job_id != job.id
                or job.document_id != document.id
                or attempt.worker_id != claimed.worker_id
                or attempt.status != "RUNNING"
                or job.status != "PROCESSING"
            ):
                raise LostAttemptOwnershipError(
                    "ingestion attempt is no longer owned by this worker"
                )

            attempt.status = "FAILED"
            attempt.heartbeat_at = now
            attempt.lease_expires_at = now
            attempt.finished_at = now
            attempt.failure_class = "PERMANENT"
            attempt.failure_code = error.code
            attempt.failure_message = str(error)[:MAX_FAILURE_MESSAGE_LENGTH]

            job.status = "FAILED"
            job.last_error_code = error.code
            job.claimed_by = None
            job.lease_expires_at = None
            job.finished_at = now
            job.updated_at = now

            document.processing_status = "REJECTED"
            document.failure_code = error.code
            document.processed_at = now
            document.updated_at = now

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
