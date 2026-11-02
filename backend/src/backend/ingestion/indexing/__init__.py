"""Validated document-vector indexing."""

from backend.ingestion.indexing.interface import (
    IndexChunk,
    IndexDocument,
    IndexingError,
    IndexingTransientError,
    IndexWriteResult,
    VectorIndex,
)
from backend.ingestion.indexing.pgvector import PgVectorIndex

__all__ = [
    "IndexChunk",
    "IndexDocument",
    "IndexingError",
    "IndexingTransientError",
    "IndexWriteResult",
    "PgVectorIndex",
    "VectorIndex",
]
