"""Contracts and classified failures for relation extraction."""

from typing import Protocol

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.relation_extraction.models import (
    CandidateChunkExtraction,
    RelationExtractedDocument,
)


class RelationExtractionError(ValueError):
    """A permanent extraction failure caused by input or configuration."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("relation extraction error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class RelationExtractionTransientError(RuntimeError):
    """A provider failure that may succeed when the stage is retried."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("relation extraction error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class RelationExtractionProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def extract(
        self,
        text: str,
        *,
        allowed_entity_types: tuple[str, ...],
        allowed_relation_types: tuple[str, ...],
    ) -> CandidateChunkExtraction: ...


class RelationExtractor(Protocol):
    def extract_document(
        self,
        document: ChunkedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> RelationExtractedDocument: ...
