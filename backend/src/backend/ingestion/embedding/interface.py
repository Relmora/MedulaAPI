"""Contracts and classified failures used by the EMBED stage."""

from typing import Protocol

from backend.ingestion.chunking import ChunkedDocument
from backend.ingestion.embedding.models import EmbeddedDocument


class EmbeddingError(ValueError):
    """A classified, permanent embedding failure."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("embedding error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class EmbeddingTransientError(RuntimeError):
    """A classified provider failure that can succeed when retried."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("embedding error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class Embedder(Protocol):
    def embed_document(
        self,
        document: ChunkedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> EmbeddedDocument: ...
