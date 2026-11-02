"""Deterministic document-chunking contracts and implementation."""

from backend.ingestion.chunking.chunker import BlockAwareChunker
from backend.ingestion.chunking.interface import Chunker, ChunkingError
from backend.ingestion.chunking.models import (
    CHUNKED_DOCUMENT_SCHEMA_VERSION,
    ChunkedDocument,
    ChunkingConfig,
    ChunkingStatistics,
    ChunkSourceSpan,
    DocumentChunk,
)

__all__ = [
    "CHUNKED_DOCUMENT_SCHEMA_VERSION",
    "BlockAwareChunker",
    "ChunkedDocument",
    "Chunker",
    "ChunkingConfig",
    "ChunkingError",
    "ChunkingStatistics",
    "ChunkSourceSpan",
    "DocumentChunk",
]
