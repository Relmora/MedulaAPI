"""Individual stages in the document-ingestion pipeline."""

from backend.ingestion.stages.chunk_document import ChunkedArtifact, ChunkStage
from backend.ingestion.stages.embed_document import EmbeddedArtifact, EmbedStage
from backend.ingestion.stages.extract_relations import (
    RelationExtractStage,
    RelationsArtifact,
)
from backend.ingestion.stages.index_document import IndexedArtifact, IndexStage
from backend.ingestion.stages.normalize_document import (
    NormalizedArtifact,
    NormalizeStage,
)
from backend.ingestion.stages.parse_document import ParsedArtifact, ParseStage
from backend.ingestion.stages.validate_source import (
    SourceValidationError,
    SourceValidator,
    ValidatedSource,
)

__all__ = [
    "ChunkStage",
    "ChunkedArtifact",
    "EmbedStage",
    "EmbeddedArtifact",
    "IndexStage",
    "IndexedArtifact",
    "NormalizedArtifact",
    "NormalizeStage",
    "ParseStage",
    "ParsedArtifact",
    "RelationExtractStage",
    "RelationsArtifact",
    "SourceValidationError",
    "SourceValidator",
    "ValidatedSource",
]
