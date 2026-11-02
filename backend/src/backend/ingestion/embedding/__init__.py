"""Provider-neutral document embedding contracts and implementations."""

from backend.ingestion.embedding.embedder import (
    DocumentEmbedder,
    VertexAIEmbeddingProvider,
)
from backend.ingestion.embedding.interface import (
    Embedder,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingTransientError,
)
from backend.ingestion.embedding.models import (
    EMBEDDED_DOCUMENT_SCHEMA_VERSION,
    ChunkEmbedding,
    EmbeddedDocument,
    EmbeddingConfiguration,
    EmbeddingStatistics,
)

__all__ = [
    "EMBEDDED_DOCUMENT_SCHEMA_VERSION",
    "ChunkEmbedding",
    "DocumentEmbedder",
    "EmbeddedDocument",
    "Embedder",
    "EmbeddingConfiguration",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingStatistics",
    "EmbeddingTransientError",
    "VertexAIEmbeddingProvider",
]
