"""Message-boundary behavior for the ingestion worker."""

from dataclasses import dataclass
from enum import StrEnum

from backend.ingestion.claim import (
    ClaimDisposition,
    ClaimedIngestionJob,
    IngestionJobClaimer,
)
from backend.ingestion.graph_storage import GraphWriteResult
from backend.ingestion.messages import IngestionRequestedMessage, InvalidMessage
from backend.ingestion.pipeline import (
    IngestionPipeline,
    PipelineDisposition,
)
from backend.ingestion.stages import (
    ChunkedArtifact,
    EmbeddedArtifact,
    IndexedArtifact,
    NormalizedArtifact,
    ParsedArtifact,
    RelationsArtifact,
    ValidatedSource,
)


class HandleDisposition(StrEnum):
    CLAIMED = "CLAIMED"
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    CHUNKED = "CHUNKED"
    EMBEDDED = "EMBEDDED"
    INDEXED = "INDEXED"
    RELATIONS_EXTRACTED = "RELATIONS_EXTRACTED"
    GRAPH_STORED = "GRAPH_STORED"
    ACKNOWLEDGED_SOURCE_REJECTED = "ACKNOWLEDGED_SOURCE_REJECTED"
    ACKNOWLEDGED_PARSE_REJECTED = "ACKNOWLEDGED_PARSE_REJECTED"
    ACKNOWLEDGED_NORMALIZE_REJECTED = "ACKNOWLEDGED_NORMALIZE_REJECTED"
    ACKNOWLEDGED_CHUNK_REJECTED = "ACKNOWLEDGED_CHUNK_REJECTED"
    ACKNOWLEDGED_EMBED_REJECTED = "ACKNOWLEDGED_EMBED_REJECTED"
    ACKNOWLEDGED_INDEX_REJECTED = "ACKNOWLEDGED_INDEX_REJECTED"
    ACKNOWLEDGED_RELATION_EXTRACT_REJECTED = "ACKNOWLEDGED_RELATION_EXTRACT_REJECTED"
    ACKNOWLEDGED_GRAPH_STORE_REJECTED = "ACKNOWLEDGED_GRAPH_STORE_REJECTED"
    ACKNOWLEDGED_RETRY_SCHEDULED = "ACKNOWLEDGED_RETRY_SCHEDULED"
    ACKNOWLEDGED_RETRY_EXHAUSTED = "ACKNOWLEDGED_RETRY_EXHAUSTED"
    ACKNOWLEDGED_OBSOLETE = "ACKNOWLEDGED_OBSOLETE"
    REJECTED_INVALID = "REJECTED_INVALID"


class DeliveryOutcome(StrEnum):
    """Broker settlement requested after durable worker processing."""

    ACKNOWLEDGE = "ACKNOWLEDGE"
    REJECT_DISCARD = "REJECT_DISCARD"
    LEAVE_UNSETTLED = "LEAVE_UNSETTLED"


@dataclass(frozen=True)
class HandleResult:
    disposition: HandleDisposition
    delivery_outcome: DeliveryOutcome = DeliveryOutcome.LEAVE_UNSETTLED
    claimed: ClaimedIngestionJob | None = None
    source: ValidatedSource | None = None
    parsed_artifact: ParsedArtifact | None = None
    normalized_artifact: NormalizedArtifact | None = None
    chunked_artifact: ChunkedArtifact | None = None
    embedded_artifact: EmbeddedArtifact | None = None
    indexed_artifact: IndexedArtifact | None = None
    relations_artifact: RelationsArtifact | None = None
    graph_write_result: GraphWriteResult | None = None
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

    def handle(self, body: bytes) -> HandleResult:
        try:
            message = IngestionRequestedMessage.from_body(body)
        except InvalidMessage as error:
            return HandleResult(
                HandleDisposition.REJECTED_INVALID,
                delivery_outcome=DeliveryOutcome.REJECT_DISCARD,
                reason=str(error),
            )

        result = self._claimer.claim(message, worker_id=self._worker_id)
        if result.disposition is ClaimDisposition.OBSOLETE:
            return HandleResult(
                HandleDisposition.ACKNOWLEDGED_OBSOLETE,
                delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                reason=result.reason,
            )

        if self._pipeline is not None:
            pipeline_result = self._pipeline.process(result.claimed)
            if pipeline_result.disposition is PipelineDisposition.SOURCE_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_SOURCE_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.PARSE_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_PARSE_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.NORMALIZE_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_NORMALIZE_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.CHUNK_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_CHUNK_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.EMBED_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_EMBED_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.INDEX_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_INDEX_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                    reason=pipeline_result.error_code,
                )
            if (
                pipeline_result.disposition
                is PipelineDisposition.RELATION_EXTRACT_REJECTED
            ):
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_RELATION_EXTRACT_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                    indexed_artifact=pipeline_result.indexed_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.GRAPH_STORE_REJECTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_GRAPH_STORE_REJECTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    relations_artifact=pipeline_result.relations_artifact,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.GRAPH_STORED:
                return HandleResult(
                    HandleDisposition.GRAPH_STORED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                    indexed_artifact=pipeline_result.indexed_artifact,
                    relations_artifact=pipeline_result.relations_artifact,
                    graph_write_result=pipeline_result.graph_write_result,
                )
            if pipeline_result.disposition is PipelineDisposition.RELATIONS_EXTRACTED:
                return HandleResult(
                    HandleDisposition.RELATIONS_EXTRACTED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                    indexed_artifact=pipeline_result.indexed_artifact,
                    relations_artifact=pipeline_result.relations_artifact,
                )
            if pipeline_result.disposition is PipelineDisposition.INDEXED:
                return HandleResult(
                    HandleDisposition.INDEXED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                    indexed_artifact=pipeline_result.indexed_artifact,
                )
            if pipeline_result.disposition is PipelineDisposition.EMBEDDED:
                return HandleResult(
                    HandleDisposition.EMBEDDED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
                    embedded_artifact=pipeline_result.embedded_artifact,
                )
            if pipeline_result.disposition is PipelineDisposition.CHUNKED:
                return HandleResult(
                    HandleDisposition.CHUNKED,
                    claimed=result.claimed,
                    source=pipeline_result.source,
                    parsed_artifact=pipeline_result.parsed_artifact,
                    normalized_artifact=pipeline_result.normalized_artifact,
                    chunked_artifact=pipeline_result.chunked_artifact,
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
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
                    claimed=result.claimed,
                    reason=pipeline_result.error_code,
                )
            if pipeline_result.disposition is PipelineDisposition.RETRY_EXHAUSTED:
                return HandleResult(
                    HandleDisposition.ACKNOWLEDGED_RETRY_EXHAUSTED,
                    delivery_outcome=DeliveryOutcome.ACKNOWLEDGE,
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
