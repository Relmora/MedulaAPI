"""Message-boundary behavior for the ingestion worker."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.ingestion.claim import (
    ClaimDisposition,
    ClaimedIngestionJob,
    IngestionJobClaimer,
)
from backend.ingestion.messages import IngestionRequestedMessage, InvalidMessage
from backend.ingestion.pipeline import (
    IngestionPipeline,
    PipelineDisposition,
)
from backend.ingestion.stages import (
    NormalizedArtifact,
    ParsedArtifact,
    ValidatedSource,
)


class Delivery(Protocol):
    def acknowledge(self) -> None: ...

    def reject(self, *, requeue: bool) -> None: ...


class HandleDisposition(StrEnum):
    CLAIMED = "CLAIMED"
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    ACKNOWLEDGED_SOURCE_REJECTED = "ACKNOWLEDGED_SOURCE_REJECTED"
    ACKNOWLEDGED_PARSE_REJECTED = "ACKNOWLEDGED_PARSE_REJECTED"
    ACKNOWLEDGED_NORMALIZE_REJECTED = "ACKNOWLEDGED_NORMALIZE_REJECTED"
    REQUEUED_TRANSIENT_FAILURE = "REQUEUED_TRANSIENT_FAILURE"
    ACKNOWLEDGED_RETRY_EXHAUSTED = "ACKNOWLEDGED_RETRY_EXHAUSTED"
    ACKNOWLEDGED_OBSOLETE = "ACKNOWLEDGED_OBSOLETE"
    REJECTED_INVALID = "REJECTED_INVALID"


@dataclass(frozen=True)
class HandleResult:
    disposition: HandleDisposition
    claimed: ClaimedIngestionJob | None = None
    source: ValidatedSource | None = None
    parsed_artifact: ParsedArtifact | None = None
    normalized_artifact: NormalizedArtifact | None = None
    reason: str | None = None


class IngestionWorker:
    """Validate a delivery and establish durable ownership before RAG work."""

    def __init__(
        self,
        claimer: IngestionJobClaimer,
        *,
        worker_id: str,
        pipeline: IngestionPipeline | None = None,
    ) -> None:
        self._claimer = claimer
        self._worker_id = worker_id
        self._pipeline = pipeline

    def handle(self, body: bytes, delivery: Delivery) -> HandleResult:
        try:
            message = IngestionRequestedMessage.from_body(body)
        except InvalidMessage as error:
            delivery.reject(requeue=False)
            return HandleResult(
                HandleDisposition.REJECTED_INVALID,
                reason=str(error),
            )

        result = self._claimer.claim(message, worker_id=self._worker_id)
        if result.disposition is ClaimDisposition.OBSOLETE:
            delivery.acknowledge()
            return HandleResult(
                HandleDisposition.ACKNOWLEDGED_OBSOLETE,
                reason=result.reason,
            )

        if self._pipeline is not None:
            pipeline_result = self._pipeline.process(result.claimed)
            if pipeline_result.disposition is PipelineDisposition.SOURCE_REJECTED:
                delivery.acknowledge()
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_SOURCE_REJECTED,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.PARSE_REJECTED:
                delivery.acknowledge()
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_PARSE_REJECTED,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.NORMALIZE_REJECTED:
                delivery.acknowledge()
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_NORMALIZE_REJECTED,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.NORMALIZED:
                return HandleResult(
                    HandleDisposition.NORMALIZED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                )
            if pipeline_result.disposition is PipelineDisposition.PARSED:
                return HandleResult(
                    HandleDisposition.PARSED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                )
            if pipeline_result.disposition is PipelineDisposition.RETRY_SCHEDULED:
                delivery.reject(requeue=True)
                return HandleResult(
                    HandleDisposition.REQUEUED_TRANSIENT_FAILURE,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.RETRY_EXHAUSTED:
                delivery.acknowledge()
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_RETRY_EXHAUSTED,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            return HandleResult(
                HandleDisposition.SOURCE_VALIDATED,
                claimed=result.claimed,
                source=pipeline_result.source,
            )

        # Until a pipeline is composed, a successful claim remains
        # unacknowledged. Later stages own it through a durable outcome.
        return HandleResult(
            HandleDisposition.CLAIMED,
            claimed=result.claimed,
        )
