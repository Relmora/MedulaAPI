"""Orchestrate durable ingestion stages after a worker claims a job."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select

from backend.ingestion.claim import ClaimedIngestionJob, SessionFactory
from backend.ingestion.parsing import ParseError
from backend.ingestion.stages import (
    ParsedArtifact,
    ParseStage,
    SourceValidationError,
    SourceValidator,
    ValidatedSource,
)
from backend.models import Document, IngestionJob, IngestionJobAttempt
from backend.object_storage import ObjectStorageUnavailableError

Clock = Callable[[], datetime]
MAX_FAILURE_MESSAGE_LENGTH = 4000


class PipelineDisposition(StrEnum):
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    PARSED = "PARSED"
    PARSE_REJECTED = "PARSE_REJECTED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


@dataclass(frozen=True)
class PipelineResult:
    disposition: PipelineDisposition
    source: ValidatedSource | None = None
    parsed_artifact: ParsedArtifact | None = None
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
        parse_stage: ParseStage | None = None,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._source_validator = source_validator
        self._parse_stage = parse_stage
        self._clock = clock

    def process(self, claimed: ClaimedIngestionJob) -> PipelineResult:
        try:
            source = self._source_validator.validate(claimed)
        except SourceValidationError as error:
            self._record_permanent_failure(claimed, error)
            return PipelineResult(
                PipelineDisposition.SOURCE_REJECTED,
                error_code=error.code,
            )
        if self._parse_stage is None:
            return PipelineResult(
                PipelineDisposition.SOURCE_VALIDATED,
                source=source,
            )
        try:
            artifact = self._parse_stage.execute(source)
        except ObjectStorageUnavailableError as error:
            retry_scheduled = self._record_retryable_failure(
                claimed,
                code="PARSED_ARTIFACT_UPLOAD_FAILED",
                message=str(error),
            )
            return PipelineResult(
                PipelineDisposition.RETRY_SCHEDULED
                if retry_scheduled
                else PipelineDisposition.RETRY_EXHAUSTED,
                error_code="PARSED_ARTIFACT_UPLOAD_FAILED",
            )
        except ParseError as error:
            self._record_permanent_failure(claimed, error)
            return PipelineResult(
                PipelineDisposition.PARSE_REJECTED,
                error_code=error.code,
            )
        self._record_parse_success(claimed, artifact)
        return PipelineResult(
            PipelineDisposition.PARSED,
            source=source,
            parsed_artifact=artifact,
        )

    def _record_permanent_failure(
        self,
        claimed: ClaimedIngestionJob,
        error: SourceValidationError | ParseError,
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

    def _record_retryable_failure(
        self,
        claimed: ClaimedIngestionJob,
        *,
        code: str,
        message: str,
    ) -> bool:
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

            retry_scheduled = job.attempt_count < job.max_attempts
            attempt.status = "FAILED"
            attempt.current_stage = "PARSE"
            attempt.heartbeat_at = now
            attempt.lease_expires_at = now
            attempt.finished_at = now
            attempt.failure_class = "TRANSIENT"
            attempt.failure_code = code
            attempt.failure_message = message[:MAX_FAILURE_MESSAGE_LENGTH]

            job.status = "RETRY_SCHEDULED" if retry_scheduled else "FAILED"
            job.current_stage = "PARSE"
            job.next_attempt_at = now if retry_scheduled else None
            job.claimed_by = None
            job.lease_expires_at = None
            job.last_error_code = code
            job.finished_at = None if retry_scheduled else now
            job.updated_at = now

            document.processing_status = "QUEUED" if retry_scheduled else "FAILED"
            document.failure_code = code
            document.processed_at = None if retry_scheduled else now
            document.updated_at = now
            return retry_scheduled

    def _record_parse_success(
        self,
        claimed: ClaimedIngestionJob,
        artifact: ParsedArtifact,
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

            document.parsed_storage_object_key = artifact.object_key
            document.parsed_storage_version = artifact.storage_version
            document.failure_code = None
            document.updated_at = now
            job.current_stage = "NORMALIZE"
            job.last_error_code = None
            job.updated_at = now
            attempt.current_stage = "NORMALIZE"
            attempt.heartbeat_at = now

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
