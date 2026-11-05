"""Provider-neutral contracts for durable graph persistence."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.ingestion.relation_extraction import RelationExtractedDocument


class GraphStorageError(ValueError):
    """A permanent graph-write failure caused by invalid input."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("graph storage error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class GraphStorageTransientError(RuntimeError):
    """A graph-write failure that may succeed when retried."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("graph storage error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


@dataclass(frozen=True)
class GraphWriteResult:
    document_id: UUID
    entity_count: int
    relationship_count: int
    created_entity_count: int
    created_relationship_count: int


class GraphStore(Protocol):
    def write(self, document: RelationExtractedDocument) -> GraphWriteResult: ...
