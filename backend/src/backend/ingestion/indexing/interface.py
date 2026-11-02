"""Provider-neutral contracts for durable vector indexing."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class IndexingError(ValueError):
    """A permanent indexing failure caused by invalid input or configuration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IndexingTransientError(RuntimeError):
    """A temporary indexing failure that may succeed after a retry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IndexChunk:
    chunk_id: UUID
    chunk_index: int
    text: str
    content_hash: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class IndexDocument:
    document_id: UUID
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_config_hash: str
    source_object_key: str
    source_storage_version: str | None
    chunks: tuple[IndexChunk, ...]


@dataclass(frozen=True)
class IndexWriteResult:
    document_id: UUID
    chunk_count: int
    embedding_config_hash: str


class VectorIndex(Protocol):
    def replace_document(self, document: IndexDocument) -> IndexWriteResult: ...
