"""Validation for versioned ingestion notifications from RabbitMQ."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

INGESTION_REQUESTED_EVENT = "document.ingestion.requested"
INGESTION_JOB_AGGREGATE = "INGESTION_JOB"
SUPPORTED_SCHEMA_VERSION = 1


class InvalidMessage(ValueError):
    """A broker message that cannot safely identify one ingestion job."""


@dataclass(frozen=True)
class IngestionRequestedMessage:
    event_id: UUID
    job_id: UUID
    document_id: UUID
    occurred_at: datetime
    purpose: str

    @classmethod
    def from_body(cls, body: bytes) -> "IngestionRequestedMessage":
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise InvalidMessage("Message body must be valid JSON.") from error

        if not isinstance(envelope, Mapping):
            raise InvalidMessage("Message envelope must be a JSON object.")
        if envelope.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise InvalidMessage("Message schema version is not supported.")
        if envelope.get("event_type") != INGESTION_REQUESTED_EVENT:
            raise InvalidMessage("Message event type is not supported.")
        if envelope.get("aggregate_type") != INGESTION_JOB_AGGREGATE:
            raise InvalidMessage("Message aggregate type is not supported.")

        data = envelope.get("data")
        if not isinstance(data, Mapping):
            raise InvalidMessage("Message data must be a JSON object.")

        event_id = _uuid(envelope.get("event_id"), "event_id")
        aggregate_id = _uuid(envelope.get("aggregate_id"), "aggregate_id")
        job_id = _uuid(data.get("job_id"), "data.job_id")
        document_id = _uuid(data.get("document_id"), "data.document_id")
        if aggregate_id != job_id:
            raise InvalidMessage("Message aggregate ID does not match its job ID.")

        occurred_at_value = envelope.get("occurred_at")
        if not isinstance(occurred_at_value, str):
            raise InvalidMessage("Message occurred_at must be an ISO-8601 timestamp.")
        try:
            occurred_at = datetime.fromisoformat(occurred_at_value)
        except ValueError as error:
            raise InvalidMessage(
                "Message occurred_at must be an ISO-8601 timestamp."
            ) from error
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise InvalidMessage("Message occurred_at must be timezone-aware.")

        purpose = data.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            raise InvalidMessage("Message purpose must be a nonempty string.")

        return cls(
            event_id=event_id,
            job_id=job_id,
            document_id=document_id,
            occurred_at=occurred_at,
            purpose=purpose,
        )


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidMessage(f"Message {field} must be a UUID.") from error

