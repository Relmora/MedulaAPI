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


class Delivery(Protocol):
    def acknowledge(self) -> None: ...

    def reject(self, *, requeue: bool) -> None: ...


class HandleDisposition(StrEnum):
    CLAIMED = "CLAIMED"
    ACKNOWLEDGED_OBSOLETE = "ACKNOWLEDGED_OBSOLETE"
    REJECTED_INVALID = "REJECTED_INVALID"


@dataclass(frozen=True)
class HandleResult:
    disposition: HandleDisposition
    claimed: ClaimedIngestionJob | None = None
    reason: str | None = None


class IngestionWorker:
    """Validate a delivery and establish durable ownership before RAG work."""

    def __init__(self, claimer: IngestionJobClaimer, *, worker_id: str) -> None:
        self._claimer = claimer
        self._worker_id = worker_id

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

        # A successful claim deliberately remains unacknowledged. The upcoming
        # RAG pipeline owns this delivery until its durable terminal/retry
        # transaction commits.
        return HandleResult(
            HandleDisposition.CLAIMED,
            claimed=result.claimed,
        )

